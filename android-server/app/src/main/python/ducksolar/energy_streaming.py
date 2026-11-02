"""Disk-backed, compact month accounting for the Android resource budget.
The legacy interval formula is reused verbatim for each pair. Full inputs and
intervals are streamed to an audit, never embedded in the API response.
"""
from contextlib import contextmanager,ExitStack
import heapq
from contextvars import ContextVar
from datetime import date,datetime,timedelta
import csv,hashlib,io,json,os,sqlite3,tempfile,threading,time,uuid
from pathlib import Path
from .energy_accounting import ZONE,stamp,seconds,interval_energy,meter_segments
from .core.models import checked_id
from .energy_pair import Pair

ALGORITHM='energy.streaming.v6-month-only'
_report_locks={}
_report_lock_guard=threading.Lock()
@contextmanager
def _report_lock(cfg,device_id,anchor,source,cancelled,stop):
    parsed=date.fromisoformat(anchor+'-01' if len(anchor)==7 else anchor) if isinstance(anchor,str) else anchor
    key=(str(Path(cfg.root_dir).resolve()),device_id,parsed.year,parsed.month,source)
    with _report_lock_guard:lock=_report_locks.setdefault(key,threading.Lock())
    while not lock.acquire(timeout=.1):
        if stop.is_set() or (cancelled and cancelled()):raise ValueError('Розрахунок балансу скасовано')
    try:yield
    finally:lock.release()
_hash_context=ContextVar('energy_prefix_hashes',default=None)
FIELDS=('timestamp','pv_w','output_w','grid_import_w','grid_export_w','grid_import_source',
 'grid_export_source','grid_import_origin','grid_export_origin','grid_import_reason',
 'grid_export_reason','grid_import_energy_total_kwh','grid_export_energy_total_kwh',
 'grid_import_counter_id','grid_export_counter_id','grid_import_counter_modulus_kwh',
 'grid_export_counter_modulus_kwh')

_encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,allow_nan=False,
                         separators=(',',':'),default=lambda x:x.isoformat())
def _json(value):
    return _encoder.encode(value)

def _scalar_insert(con, batch, fields=FIELDS):
    """A disposable typed index avoids decoding JSON on every calculation."""
    columns=','.join(fields)
    placeholders=','.join('?' for _ in range(len(fields)+1))
    values=[]
    for ts,payload in batch:
        row=payload if isinstance(payload,dict) else json.loads(payload)
        def cell(value):
            if isinstance(value,bool):return b'b:1' if value else b'b:0'
            if isinstance(value,int) and not -(1<<63)<=value<(1<<63):return b'i:'+str(value).encode('ascii')
            return value
        values.append((ts,*(cell(row.get(key)) for key in fields)))
    con.executemany('INSERT OR IGNORE INTO scalar_inputs(ts,'+columns+') VALUES('+placeholders+')',values)

def _insert_inputs(con,batch,fields=FIELDS):
    _scalar_insert(con,batch,fields)

def _files(reader,start,end,source,cancelled=None):
    reader.available_dates()
    found=[];day=(start-timedelta(days=1)).date()
    while day<=end.date():
        if cancelled and cancelled():raise ValueError('History query cancelled')
        local,smart=reader.find_day_files(day)
        groups=[('Local',local)] if source=='Local' else [('SmartESS',smart)] if source=='SmartESS' else [('Local',local),('SmartESS',smart)]
        for origin,paths in groups:
            for path in paths:
                try:
                    st=path.stat()
                    found.append((path,origin,day,st.st_size,st.st_mtime_ns))
                except FileNotFoundError:continue
        day+=timedelta(days=1)
    available={'Local':0,'SmartESS':0}
    for day,(local,smart) in reader._file_index.items():
        if start.date()<=day<=end.date():
            available['Local']+=len(local);available['SmartESS']+=len(smart)
    reader._balance_stats['available_files_by_source']=available
    reader._balance_stats['archive_discovery']=getattr(reader,'_archive_diagnostics',{})
    from .prepared_history import PreparedHistory
    prepared=PreparedHistory(reader);unique=[];seen=set()
    for entry in found:
        p,origin,day,size,mtime=entry
        if day<date.today():
            key,_=prepared.identity(p,origin,day,cancelled)
            if key in seen:continue
            seen.add(key)
        unique.append(entry)
    reader._balance_stats['identical_files_skipped']=len(found)-len(unique)
    return unique

def _snapshot_lines(path,size):
    # Read only the committed prefix captured at calculation start. A later
    # appended row belongs to the next source revision, and a partial row is ignored.
    with path.open('rb') as stream:
        remaining=size;first=True
        while remaining:
            line=stream.readline(remaining);remaining-=len(line)
            if not line or not line.endswith(b'\n'):break
            yield line.decode('utf-8-sig' if first else 'utf-8')
            first=False

def _prefix_hash(path,size,cancelled):
    if cancelled():raise ValueError('Розрахунок балансу скасовано')
    before=path.stat();context=_hash_context.get()
    key=(str(path.resolve()),size,before.st_size,before.st_mtime_ns,before.st_ino)
    if context is not None and key in context[0]:
        context[1]['prefix_hash_hits']=context[1].get('prefix_hash_hits',0)+1
        return context[0][key]
    started=time.perf_counter();digest=hashlib.sha256()
    with path.open('rb') as stream:
        remaining=size
        while remaining:
            if cancelled():raise ValueError('Розрахунок балансу скасовано')
            block=stream.read(min(256*1024,remaining))
            if not block:raise ValueError('Історія змінена під час розрахунку')
            digest.update(block);remaining-=len(block)
    after=path.stat();result=digest.hexdigest()
    if context is not None:
        context[1]['prefix_hash_bytes']=context[1].get('prefix_hash_bytes',0)+size
        context[1]['prefix_hash_s']=context[1].get('prefix_hash_s',0)+time.perf_counter()-started
        if (after.st_size,after.st_mtime_ns,after.st_ino)==(before.st_size,before.st_mtime_ns,before.st_ino) and len(context[0])<256:
            context[0][key]=result
    return result

def _input_database(db,fields=FIELDS):
    for attempt in range(2):
        con=sqlite3.connect(str(db))
        try:
            from .resource_manager import configure
            configure(con)
            # This is a disposable projection, not user history. A lost commit
            # after power failure is safely rebuilt from the authoritative CSV.
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA synchronous=NORMAL')
            con.execute('CREATE TABLE IF NOT EXISTS inputs (ts REAL PRIMARY KEY,payload TEXT) WITHOUT ROWID')
            # No numeric affinity: preserve integer/float/missing distinctions,
            # including unusually large counters stored as an ASCII BLOB.
            columns=','.join(key+' BLOB' for key in fields)
            con.execute('CREATE TABLE IF NOT EXISTS scalar_inputs(ts REAL PRIMARY KEY,'+columns+') WITHOUT ROWID')
            con.execute('CREATE TABLE IF NOT EXISTS revision (id INTEGER PRIMARY KEY, size INTEGER, digest TEXT, fields TEXT, mtime INTEGER)')
            if 'mtime' not in {row[1] for row in con.execute('PRAGMA table_info(revision)')}:
                con.execute('ALTER TABLE revision ADD COLUMN mtime INTEGER')
            if con.execute('PRAGMA user_version').fetchone()[0]!=19:
                cursor=con.execute('SELECT ts,payload FROM inputs')
                while batch:=cursor.fetchmany(1024):_scalar_insert(con,batch,fields)
                con.execute('PRAGMA user_version=19');con.commit()
            return con
        except sqlite3.DatabaseError as error:
            con.close()
            if attempt or getattr(error,'sqlite_errorcode',None) not in (sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_NOTADB):raise
            db.unlink(missing_ok=True) # disposable inputs, never the original CSV

def _projection_cursor(con,stats,after,fields=FIELDS):
    start,end=stats['range_start'],stats['range_end']
    # Separate indexed ranges avoid an OR scan of all old payloads when
    # only a few new records are requested from a large daily projection.
    suffix=' AND ts>?' if after is not None else ''
    columns='ts,'+','.join(fields)
    table='scalar_inputs'
    query=('SELECT '+columns+' FROM '+table+' WHERE ts BETWEEN ? AND ?'+suffix+
           ' UNION SELECT '+columns+' FROM '+table+' WHERE ts=(SELECT MAX(ts) FROM '+table+' WHERE ts<?)'+suffix+
           ' UNION SELECT '+columns+' FROM '+table+' WHERE ts=(SELECT MIN(ts) FROM '+table+' WHERE ts>?)'+suffix)
    args=[start,end]
    if after is not None:args.append(after)
    args.append(start)
    if after is not None:args.append(after)
    args.append(end)
    if after is not None:args.append(after)
    def rows():
        stats['typed_index_reads']=stats.get('typed_index_reads',0)+1
        for record in con.execute(query+' ORDER BY ts',args):
            def cell(value):
                if not isinstance(value,bytes):return value
                if value.startswith(b'b:'):return value==b'b:1'
                return int(value[2:] if value.startswith(b'i:') else value)
            yield record[0],{key:cell(value) for key,value in zip(fields,record[1:]) if value is not None}
    return rows()

@contextmanager
def _projected_file(reader,path,origin,day,size,mtime,cancelled,after=None):
    from .concurrency import keyed_lock,path_key
    # Serialize only projection creation/update. WAL readers retain their own
    # snapshots and can stream concurrently after the write phase completes.
    with ExitStack() as opened:
        with keyed_lock(path_key('projection-build',path),cancelled):
            cursor=opened.enter_context(_projected_file_impl(reader,path,origin,day,size,mtime,cancelled,after))
        yield cursor

@contextmanager
def _projected_file_impl(reader,path,origin,day,size,mtime,cancelled,after=None):
    """Persist small accounting inputs on disk; never retain month rows in RAM.

    Verify the previous prefix before reusing it, including after file edits.
    A partial trailing CSV record is retried on the next request. SQLite commits
    inputs and their source revision together, so cancellation cannot bless a
    partially rebuilt cache.
    """
    stats=getattr(reader,'_balance_stats',{})
    fields=getattr(reader,'_projection_columns',FIELDS)
    graph=fields!=FIELDS
    projection_started=time.perf_counter()
    stats['opened_files']=stats.get('opened_files',0)+1
    stats.setdefault('files',[]).append(str(path))
    def verify_schema():
        expected=getattr(reader,'_balance_schemas',{}).get(str(path))
        if expected:
            from .compact_history import schema_path
            metadata=schema_path(path)
            if _prefix_hash(metadata,metadata.stat().st_size,cancelled)!=expected:raise ValueError('Compact schema changed; repeat the query')
    verify_schema()
    from .prepared_history import PreparedHistory
    # A prepared PC/phone projection is independent of the requested month.
    ready=PreparedHistory(reader).rows(path,origin,day,cancelled,create=False)
    if ready is not None:
        # An indexed accounting-only projection avoids repeatedly decoding all
        # telemetry fields from portable gzip objects. This is disposable data.
        store=PreparedHistory(reader)
        key,metadata=store.identity(path,origin,day,cancelled)
        if graph:key=hashlib.sha256((key+repr(fields)).encode()).hexdigest()
        from .projection_contract import folder as projection_folder
        folder=projection_folder(reader.cfg.root_dir)
        folder.mkdir(parents=True,exist_ok=True)
        db=folder/(key+'.db');con=_input_database(db,fields)
        try:
            saved=con.execute('SELECT digest FROM revision WHERE id=1').fetchone()
            if not saved or saved[0]!=key:
                con.execute('BEGIN');con.execute('DELETE FROM inputs');con.execute('DELETE FROM scalar_inputs')
                batch=[]
                for row in ready:
                    if cancelled():raise ValueError('Розрахунок балансу скасовано')
                    instant=stamp(row['timestamp'])
                    projected={k:row[k] for k in fields if row.get(k) is not None}
                    projected['timestamp']=instant.isoformat()
                    batch.append((instant.timestamp(),projected))
                    if len(batch)>=1024:
                        _insert_inputs(con,batch,fields);batch.clear()
                if batch:_insert_inputs(con,batch,fields)
                con.execute('INSERT OR REPLACE INTO revision VALUES (1,?,?,?,?)',(size,key,'[]',mtime))
                con.commit()
            else:stats['prepared_index_hits']=stats.get('prepared_index_hits',0)+1
            stats['prepared_hits']=stats.get('prepared_hits',0)+1
            stats['projection_s']=stats.get('projection_s',0)+time.perf_counter()-projection_started
            verify_schema()
            yield _projection_cursor(con,stats,after,fields)
        finally:con.close()
        return
    folder=Path(reader.cfg.root_dir)/'Data'/'EnergyWork'/'Inputs'
    folder.mkdir(parents=True,exist_ok=True)
    identity=_json([str(path.resolve()),origin,reader.model_signature(),ALGORITHM,'timestamp-defaults-v4-compatible-schema',stats['range_start']])
    if graph:identity+=repr(fields)
    from .compact_history import schema_path
    schema=schema_path(path)
    schema_data=json.loads(schema.read_text(encoding='utf-8')) if schema.exists() else None
    schema_sha=getattr(reader,'_balance_schemas',{}).get(str(path))
    if origin=='SmartESS':identity+='smartess-missing-v2'
    db=folder/(hashlib.sha256(identity.encode()).hexdigest()+'.db')
    # Derived inputs use available storage; originals and audits are not evicted.
    import shutil
    disk=shutil.disk_usage(folder)
    from .concurrency import active_count
    if active_count()<=1 and disk.free<=max(64*1024*1024,disk.total//50):
        candidates=[p for p in folder.glob('*.db') if p!=db and not p.is_symlink()]
        for candidate in sorted(candidates,key=lambda p:p.stat().st_mtime_ns):
            disk=shutil.disk_usage(folder)
            if disk.free>max(64*1024*1024,disk.total//50):break
            if cancelled():raise ValueError('Розрахунок балансу скасовано')
            candidate.unlink(missing_ok=True)
    con=_input_database(db,fields)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS schema_revision (id INTEGER PRIMARY KEY, sha TEXT, contract TEXT)')
        old=con.execute('SELECT size,digest,fields,mtime FROM revision WHERE id=1').fetchone()
        saved_schema=con.execute('SELECT sha,contract FROM schema_revision WHERE id=1').fetchone()
        if old and schema_data is not None:
            from .compact_history import compatible_schema
            if not saved_schema or (saved_schema[0]!=schema_sha and not compatible_schema(schema_data,saved_schema[0],json.loads(saved_schema[1]))):
                stats['projection_schema_rebuilt']=stats.get('projection_schema_rebuilt',0)+1;old=None
        elif old and saved_schema:old=None
        if old and old[0]==size and old[3]==mtime:
            stats['projection_hits']=stats.get('projection_hits',0)+1
            stats['projection_s']=stats.get('projection_s',0)+time.perf_counter()-projection_started
            verify_schema()
            yield _projection_cursor(con,stats,after,fields)
            return
        append=bool(old and old[0]>0 and json.loads(old[2]) and size>=old[0] and _prefix_hash(path,old[0],cancelled)==old[1])
        offset=old[0] if append else 0
        header=json.loads(old[2]) if append else None
        con.execute('BEGIN')
        if not append:
            con.execute('DELETE FROM inputs');con.execute('DELETE FROM scalar_inputs')
        with path.open('rb') as stream:
            stream.seek(offset);committed=offset
            def lines():
                nonlocal committed
                first=offset==0
                while stream.tell()<size:
                    line=stream.readline(size-stream.tell())
                    if not line or not line.endswith(b'\n'):break
                    committed=stream.tell()
                    yield line.decode('utf-8-sig' if first else 'utf-8')
                    first=False
            records=csv.DictReader(lines(),fieldnames=header,strict=True)
            decode=reader.compact_decoder(path,'graph' if graph else True)
            boundary=None;boundary_time=None;boundary_ts=float('-inf')
            inserted=0;batch=[]
            def insert(raw,decoded=False,parsed_time=None):
                nonlocal inserted
                inserted+=1
                if inserted%256==0:
                    from .resource_manager import configure
                    configure(con,False)
                phase=time.perf_counter()
                row=reader._canonical(raw if decoded else decode(raw),origin,day,compact='graph' if graph else True,parsed_time=parsed_time)
                stats['canonical_s']=stats.get('canonical_s',0)+time.perf_counter()-phase
                if not row:return
                projected={key:row[key] for key in fields if row.get(key) is not None}
                instant=stamp(row['timestamp'])
                projected['timestamp']=instant.isoformat()
                batch.append((instant.timestamp(),projected))
                if len(batch)>=1024:
                    _insert_inputs(con,batch,fields);batch.clear()
            for raw in records:
                stats['read_records']=stats.get('read_records',0)+1
                if cancelled():raise ValueError('Розрахунок балансу скасовано')
                if None in raw or any(v is None for v in raw.values()):continue
                # Compact cells may omit the first timestamp by referring to
                # schema defaults. Decode before filtering its time range.
                phase=time.perf_counter();item=decode(raw)
                dt=reader._parse_dt(item.get('time') or item.get('Timestamp') or item.get('timestamp') or '',day)
                stats['scalar_decode_s']=stats.get('scalar_decode_s',0)+time.perf_counter()-phase
                if dt is None:continue
                t=stamp(dt).timestamp()
                if t<stats['range_start']:
                    if t>boundary_ts:boundary,boundary_time,boundary_ts=item,dt,t
                    continue
                insert(item,True,dt)
            if boundary is not None:insert(boundary,True,boundary_time)
            if batch:_insert_inputs(con,batch,fields)
            header=records.fieldnames or header or []
        current=path.stat()
        if current.st_size<size or (current.st_size==size and current.st_mtime_ns!=mtime):
            raise ValueError('Історія змінена під час розрахунку; повторіть запит')
        if decode.schema_sha256 and _prefix_hash(schema,schema.stat().st_size,cancelled)!=decode.schema_sha256:raise ValueError('Compact schema changed; repeat the query')
        digest=_prefix_hash(path,committed,cancelled)
        con.execute('INSERT OR REPLACE INTO revision VALUES(1,?,?,?,?)',(committed,digest,_json(header),mtime))
        if schema_data is not None:
            from .compact_history import schema_contract
            con.execute('INSERT OR REPLACE INTO schema_revision VALUES(1,?,?)',(decode.schema_sha256,_json(schema_contract(schema_data))))
        else:con.execute('DELETE FROM schema_revision')
        con.commit()
        stats['projection_s']=stats.get('projection_s',0)+time.perf_counter()-projection_started
        yield _projection_cursor(con,stats,after,fields)
    finally:
        con.close()

@contextmanager
def _ordered_rows(reader,files,source,cancelled,after=None,last_local=None):
    from .resource_manager import connections
    with connections(len(files)+1), ExitStack() as stack:
        cursors=[stack.enter_context(_projected_file(reader,p,o,d,size,mtime,cancelled,after))
                 for p,o,d,size,mtime in files]
        def group(origin):
            previous=None
            def tagged(cursor,index):
                for counter,(ts,payload) in enumerate(cursor):
                    if counter%256==0:
                        from .concurrency import yield_background
                        yield_background(cancelled)
                    if counter%256==0 and hasattr(cursor,'connection'):
                        from .resource_manager import configure
                        configure(cursor.connection,False)
                    yield ts,index,payload
            selected=[tagged(cursor,i) for i,cursor in enumerate(cursors) if files[i][1]==origin]
            for ts,index,payload in heapq.merge(*selected):
                if cancelled():raise ValueError('Розрахунок балансу скасовано')
                if ts==previous:continue
                previous=ts;yield ts,payload
        def merged():
            local=iter(group('Local'));smart=iter(group('SmartESS'))
            left=next(local,None);right=next(smart,None);local_time=last_local
            gap=max(15.,reader.cfg.poll_interval_s*3.)
            while left is not None or right is not None:
                if cancelled():raise ValueError('Розрахунок балансу скасовано')
                if left is not None and (right is None or left[0]<=right[0]):
                    local_time=left[0];reader._balance_stats['merge_last_local']=local_time
                    yield left[1] if isinstance(left[1],dict) else json.loads(left[1]);left=next(local,None)
                else:
                    t,payload=right
                    nearby=(local_time is not None and t-local_time<=gap) or (left is not None and left[0]-t<=gap)
                    if source!='Auto' or not nearby:yield payload if isinstance(payload,dict) else json.loads(payload)
                    right=next(smart,None)
        yield merged()

class _Summary:
    def __init__(self,start,end):
        self.start,self.end=start,end;self.kwh=0.;self.covered=0.;self.measured=0.;self.count=0;self.resets=0
    def add(self,pair):
        for interval in pair['intervals']:
            duration=pair['duration_s'] if 'duration_s' in pair else seconds(interval['start'],interval['end'])
            self.kwh+=interval['kwh'];self.covered+=duration;self.count+=1
            if interval['source'] in ('counter','counter_rollover','measured'):self.measured+=duration
        self.resets+=len(pair['resets'])
    def result(self):
        period=max(0,seconds(self.start,self.end))
        return dict(kwh=self.kwh if self.count else None,
          coverage_pct=min(100,self.covered/period*100) if period else 0,
          measured_pct=min(100,self.measured/period*100) if period else 0,
          estimated_pct=min(100,(self.covered-self.measured)/period*100) if period else 0,
          missing_pct=max(0,100-self.covered/period*100) if period else 0,
          interval_count=self.count,reset_count=self.resets,boundary='inverter')
    def state(self):
        return {key:getattr(self,key) for key in ('kwh','covered','measured','count','resets')}
    def restore(self,state):
        for key in ('kwh','covered','measured','count','resets'):setattr(self,key,state[key])

def _audit_valid(old,audit):
    if old.get('deferred_audit'):
        from .deferred_audit import valid_parts
        return (hashlib.sha256(_json(old['report']).encode()).hexdigest()==old.get('report_checksum')
                and valid_parts(old.get('input_parts',[])))
    return (hashlib.sha256(_json(old['report']).encode()).hexdigest()==old.get('report_checksum')
        and audit.exists() and audit.stat().st_size==old.get('audit_bytes')
        and audit.stat().st_mtime_ns==old.get('audit_mtime_ns'))

def _resume_checkpoint(old,files,reader,signature,end,aborted):
    """Resume only a proven append-only stream. Every other edit rebuilds.

    Verify the full old prefix, not merely the first CSV bytes. Reject late,
    corrected, duplicate and partial records, and changed calculation settings.
    Auto additionally proves that new Local rows cannot suppress a saved ESS row.
    """
    state=old.get('checkpoint')
    if not state or not state.get('last_row'):
        reader._balance_stats['checkpoint_rejected']='no_saved_input_boundary';return None
    prior=state['signature']
    if signature.get('end') is not None and {k:v for k,v in prior.items() if k!='readings'}==json.loads(_json({k:v for k,v in signature.items() if k!='readings'})):
        return state # Only meter readings changed: verified inverter audit/totals are reusable.
    stats=reader._balance_stats
    def reject(reason):stats['checkpoint_rejected']=reason;return None
    for key in ('algorithm','start','device_id','source','model','history_semantics'):
        if _json(prior.get(key))!=_json(signature.get(key)):return reject('changed_'+key)
    if prior.get('input_semantics','raw-v1')!=signature.get('input_semantics','raw-v1'):
        return reject('changed_input_semantics')
    old_schemas=dict(prior.get('schemas',[]));new_schemas=dict(signature.get('schemas',[]))
    for key,value in old_schemas.items():
        if new_schemas.get(key)==value:continue
        from .compact_history import schema_path,compatible_schema
        try:
            schema=json.loads(schema_path(key).read_text(encoding='utf-8'))
            compatible=compatible_schema(schema,value,prior.get('schema_contracts',{}).get(key))
        except (OSError,ValueError,TypeError,KeyError):compatible=False
        if not compatible:
            stats['schema_changed_file']=key
            stats['schema_change_reason']='existing_definition_changed_or_unproven'
            return reject('changed_schema')
        stats['compatible_schema_extensions']=stats.get('compatible_schema_extensions',0)+1
    last=stamp(state['last_row']['timestamp'])
    previous_end=stamp(old['report']['end']).timestamp()
    # UTC order also handles the repeated local hour at the DST transition.
    if end.timestamp()<previous_end:return reject('changed_time_boundary')
    # The first sample after the end is intentional interpolation support.
    # For an unchanged closed boundary its contribution is already complete.
    # If the end advances replay that clipped pair from verified immutable audit
    # inputs, or rebuild when a safe look-behind cannot be proven.
    needs_rewind=last.timestamp()>previous_end and end.timestamp()!=previous_end
    current={str(p):(p,o,d,size,mtime) for p,o,d,size,mtime in files}
    previous={item['path']:item for item in state['prefixes']}
    if not set(previous)<=set(current):return reject('removed_source')
    for key,(path,origin,day,size,mtime) in current.items():
        if aborted():raise ValueError('Розрахунок балансу скасовано')
        saved=previous.get(key)
        if saved:
            offset=saved['size']
            if size<offset:return reject('truncated_source')
            if size==offset and mtime==saved['mtime']:continue
            if _prefix_hash(path,offset,aborted)!=saved['digest']:return reject('edited_prefix')
        else:offset=0
        # An incomplete old CSV record must be reparsed in full, not skipped.
        with path.open('rb') as stream:
            if offset:
                stream.seek(offset-1)
                if stream.read(1)!=b'\n':return reject('partial_old_record')
            stream.seek(0)
            header=next(csv.reader([stream.readline().decode('utf-8-sig')]),[])
            stream.seek(offset)
            lines=_snapshot_lines(path,size) if not offset else None
            if offset:
                def appended():
                    while stream.tell()<size:
                        line=stream.readline(size-stream.tell())
                        if not line or not line.endswith(b'\n'):break
                        yield line.decode('utf-8')
                records=csv.DictReader(appended(),fieldnames=header,strict=True)
            else:records=csv.DictReader(lines,strict=True)
            decode_time=reader.timestamp_decoder(path)
            for row in records:
                if aborted():raise ValueError('Розрахунок балансу скасовано')
                if None in row or any(v is None for v in row.values()):continue
                dt=reader._parse_dt(decode_time(row),day)
                if dt is not None:
                    instant=stamp(dt).timestamp()
                    if instant<=last.timestamp():return reject('late_or_duplicate_record')
                    # A new Local sample may retroactively suppress the last
                    # accepted ESS sample. Resume only when that cannot happen.
                    has_smart = any(entry[1]=='SmartESS' for entry in files) or any(entry[1]=='SmartESS' for entry in prior['files'])
                    if signature['source']=='Auto' and has_smart and origin=='Local' and state.get('merge_last_local')!=last.timestamp() and instant-last.timestamp()<=max(15.,reader.cfg.poll_interval_s*3.):return reject('auto_merge_boundary')
    if needs_rewind:
        from .balance_boundary import rewind
        replay=rewind(old,reader,aborted)
        return replay if replay is not None else reject('changed_time_boundary')
    return state

class MonthAccounting:
    def __init__(self,stop_event=None):
        self.lock=threading.Lock();self.stop_event=stop_event or threading.Event();self.calculations=0
    def report(self,reader,storage,cfg,anchor,now=None,device_id='inverter-1',source='Auto',cancelled=None,progress=None):
        if not self.lock.acquire(blocking=False):raise ValueError('Баланс вже розраховується; повторіть запит пізніше')
        started=time.perf_counter()
        reader._balance_stats=dict(opened_files=0,read_records=0,used_records=0,projection_hits=0,files=[])
        token=_hash_context.set(({},reader._balance_stats))
        try:
            reader._balance_progress=progress
            if progress:progress(0,3)
            with _report_lock(cfg,device_id,anchor,source,cancelled,self.stop_event):
                result=self._report(reader,storage,cfg,anchor,now,device_id,source,cancelled)
            result=dict(result)
            available=reader._balance_stats.get('available_files_by_source',{})
            if source=='Local' and not available.get('Local') and available.get('SmartESS'):
                note=f"Local за період відсутній; доступно файлів SmartESS: {available['SmartESS']}. Інше джерело не підставлялось у Local-баланс."
                result['quality_note']=note+' '+result.get('quality_note','')
                reader._balance_stats['source_note']=note
            result['diagnostics']=dict(reader._balance_stats,total_s=round(time.perf_counter()-started,4),
                start=result['start'],end=result['end'],source=source,cached=result['cache_hit'],incremental=result.get('incremental',False))
            if progress:progress(3,3)
            return result
        except Exception as error:
            error.history_diagnostics=dict(reader._balance_stats,total_s=round(time.perf_counter()-started,4))
            raise
        finally:
            reader._balance_progress=None
            reader._balance_schemas={}
            _hash_context.reset(token)
            self.lock.release()
    def audit_page(self,*args,**kwargs):
        if not self.lock.acquire(blocking=False):raise ValueError('Audit is being updated; retry later')
        try:
            cfg=args[0] if args else kwargs['cfg']
            anchor=args[1] if len(args)>1 else kwargs['anchor']
            source=args[2] if len(args)>2 else kwargs.get('source','Auto')
            with _report_lock(cfg,kwargs.get('device_id','inverter-1'),anchor,source,None,self.stop_event):
                return self._audit_page(*args,**kwargs)
        finally:self.lock.release()
    def _audit_page(self,cfg,anchor,source='Auto',audit_id='',offset=0,limit=100,device_id='inverter-1'):
        if source not in ('Auto','Local','SmartESS'):raise ValueError('Invalid history source')
        if isinstance(offset,bool) or not isinstance(offset,int) or offset<0:raise ValueError('Invalid audit offset')
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=200:raise ValueError('Invalid audit limit')
        anchor=date.fromisoformat(anchor+'-01' if isinstance(anchor,str) and len(anchor)==7 else anchor) if isinstance(anchor,str) else anchor
        target=Path(cfg.root_dir)/'Data'/'EnergyAudit'/checked_id(device_id)
        stem=anchor.strftime('%Y-%m')+'-'+source
        summary=json.loads((target/(stem+'.summary.json')).read_text(encoding='utf-8'))
        if audit_id!=summary['report']['audit_id']:raise ValueError('Audit revision changed; request the latest month result')
        audit=target/(stem+'.audit.jsonl')
        if summary.get('deferred_audit'):
            from .deferred_audit import materialize
            materialize(summary,audit,self.stop_event.is_set)
        if summary.get('portable_audit'):
            from .balance_portable import expand_audit
            if summary.get('portable_rebased') or not audit.exists() or audit.stat().st_size!=summary['audit_bytes'] or _prefix_hash(audit,audit.stat().st_size,lambda:False)!=audit_id:
                expand_audit(summary,audit,self.stop_event.is_set)
        rows=[];byte_count=0
        with (target/(stem+'.audit.jsonl')).open('rb') as stream:
            if offset:
                stream.seek(offset-1)
                if stream.read(1)!=b'\n':raise ValueError('Audit offset is not a record boundary')
            stream.seek(offset)
            while len(rows)<limit:
                pos=stream.tell();line=stream.readline(256*1024+1)
                if not line:break
                if len(line)>256*1024:raise ValueError('Audit record exceeds page budget')
                if rows and byte_count+len(line)>256*1024:stream.seek(pos);break
                from .audit_codec import expand
                rows.append(expand(json.loads(line)));byte_count+=len(line)
            next_offset=stream.tell();done=next_offset==os.fstat(stream.fileno()).st_size
        return dict(audit_id=audit_id,records=rows,next_offset=next_offset,done=done)
    def _report(self,reader,storage,cfg,anchor,now,device_id,source,cancelled):
        if source not in ('Auto','Local','SmartESS'):raise ValueError('Некоректне джерело історії')
        device_id=checked_id(device_id)
        supplied_now=now is not None;now=stamp(now or datetime.now(ZONE))
        anchor=date.fromisoformat(anchor+'-01' if isinstance(anchor,str) and len(anchor)==7 else anchor) if isinstance(anchor,str) else anchor
        start=datetime(anchor.year,anchor.month,1,tzinfo=ZONE)
        next_month=(start.replace(day=28)+timedelta(days=4)).replace(day=1);end=min(now,next_month)
        if end<=start:raise ValueError('Період ще не почався за часом Server')
        reader._balance_stats.update(range_start=start.timestamp(),range_end=end.timestamp())
        cancelled=cancelled or (lambda:False)
        aborted=lambda:self.stop_event.is_set() or cancelled()
        if aborted():raise ValueError('Розрахунок балансу скасовано')
        stage=time.perf_counter();files=_files(reader,start,end,source,cancelled)
        reader._balance_stats['discovery_s']=round(time.perf_counter()-stage,4)
        reader._balance_stats['selected_files']=len(files)
        if getattr(reader,'_balance_progress',None):reader._balance_progress(1,3)
        readings=storage.list_meter_readings(limit=100000)
        signature=dict(algorithm=ALGORITHM,start=start.isoformat(),device_id=device_id,source=source,
                       files=[(str(p),o,d.isoformat(),size,mtime) for p,o,d,size,mtime in files],
                       model=reader.model_signature(),readings=readings,
                       end=end.isoformat() if supplied_now or end==next_month else None)
        if source!='Local':signature['history_semantics']='smartess-missing-v2'
        from .compact_history import schema_path
        from .prepared_history import digest as schema_digest
        signature['schemas']=[(str(p),schema_digest(schema_path(p),aborted)) for p,o,d,size,mtime in files if schema_path(p).exists()]
        # Old raw compact projections could omit a schema-default timestamp.
        # Rebuild their numerical checkpoint once; imported PC summaries used
        # full canonical decoding and retain their portable compatibility.
        signature['input_semantics']='timestamp-defaults-v2' if signature['schemas'] else 'raw-v1'
        from .compact_history import schema_contract
        signature['schema_contracts']={key:schema_contract(json.loads(schema_path(key).read_text(encoding='utf-8'))) for key,_ in signature['schemas']}
        reader._balance_schemas=dict(signature['schemas'])
        digest=hashlib.sha256(_json(signature).encode()).hexdigest()
        target=Path(cfg.root_dir)/'Data'/'EnergyAudit'/device_id;target.mkdir(parents=True,exist_ok=True)
        cache=target/(start.strftime('%Y-%m')+'-'+source+'.summary.json')
        if end==next_month:
            from .balance_portable import load
            portable=load(reader,files,signature,target,start.strftime('%Y-%m')+'-'+source,aborted)
            if portable is not None:return portable
        old=None;resume=None
        audit_path=target/(start.strftime('%Y-%m')+'-'+source+'.audit.jsonl')
        try:
            old=json.loads(cache.read_text(encoding='utf-8'))
            if old['signature']==digest and (supplied_now or end==next_month or abs(time.time()-old['created_at'])<30):
                if _audit_valid(old,audit_path):
                    reader._balance_stats['cache_reason']='unchanged_revision'
                    result=old['report'];result['cache_hit']=True;return result
            if _audit_valid(old,audit_path):resume=_resume_checkpoint(old,files,reader,signature,end,aborted)
            else:reader._balance_stats['checkpoint_rejected']='invalid_audit'
        except (OSError,ValueError,KeyError,TypeError):reader._balance_stats['cache_reason']='no_valid_month_summary'
        if resume:reader._balance_stats['cache_reason']='verified_checkpoint'
        summaries={key:_Summary(start,end) for key in ('pv','import','export')}
        if resume:
            for key,bucket in summaries.items():bucket.restore(resume['totals'][key])
        scratch=target/('.'+uuid.uuid4().hex+'.tmp');hasher=hashlib.sha256();count=resume['count'] if resume else 0
        try:
            with scratch.open('wb') as audit:
                from .audit_codec import InputEncoder
                input_encoder=InputEncoder()
                def write(value):
                    from .audit_codec import compact
                    value=compact(value)
                    data=(_json(value)+'\n').encode();hasher.update(data);audit.write(data)
                metadata=dict(signature,type='metadata',end=end.isoformat(),source_signature=digest)
                metadata.pop('readings')
                write(metadata)
                for reading in readings:write(dict(type='meter_reading',row=reading))
                body_start=audit.tell()
                input_parts=[]
                if resume:
                    if old.get('deferred_audit'):
                        input_parts=list(resume.get('input_parts',old['input_parts']))
                    else:
                        # One-time promotion of an old ledger. Never overwrite a
                        # file referenced by a committed checkpoint or audit page.
                        import shutil
                        from .deferred_audit import part
                        saved=target/('.inputs-'+uuid.uuid4().hex+'.jsonl')
                        # Keep a fresh mtime: orphan collection must not mistake
                        # this uncommitted promotion for an old abandoned file.
                        shutil.copyfile(audit_path,saved)
                        input_parts=[part(saved,resume['body_start'],resume['body_end'])]
                    reader._balance_stats['audit_copy_bytes']=0
                previous=resume['last_row'] if resume else None
                after=stamp(previous['timestamp']).timestamp() if previous else None
                work_files=files
                if resume:
                    # Verified old rows are already in the audit and totals.
                    # Do not reopen (or rebuild an evicted projection of) past days.
                    saved_sizes={item['path']:item['size'] for item in resume['prefixes']}
                    if not resume.get('rewound_support_pair'):
                        work_files=[entry for entry in files if str(entry[0]) not in saved_sizes or entry[3]>saved_sizes[str(entry[0])]]
                with _ordered_rows(reader,work_files,source,aborted,after,resume.get('merge_last_local') if resume else None) as rows:
                    if getattr(reader,'_balance_progress',None):reader._balance_progress(2,3)
                    integration_started=time.perf_counter();audit_write_s=0.;pair_s=0.
                    from .cpu_energy import BalanceBatch
                    cpu=BalanceBatch(summaries,start,end,cfg.max_integration_gap_s,previous,aborted,reader._balance_stats)
                    for row in rows:
                        if aborted():raise ValueError('Розрахунок балансу скасовано')
                        reader._balance_stats['used_records']+=1
                        phase=time.perf_counter();data=input_encoder.encode(row);hasher.update(data);audit.write(data);audit_write_s+=time.perf_counter()-phase;count+=1
                        phase=time.perf_counter();cpu.add(row);pair_s+=time.perf_counter()-phase
                        previous=row
                    phase=time.perf_counter();cpu.flush();pair_s+=time.perf_counter()-phase
                reader._balance_stats['integration_audit_s']=round(time.perf_counter()-integration_started,4)
                reader._balance_stats.update(audit_write_s=round(audit_write_s,4),pair_accumulate_s=round(pair_s,4))
                reader._balance_stats['audit_mode']='deferred_intervals'
                report=dict(algorithm=ALGORITHM,schema='energy.month.compact.v1',start=start.isoformat(),end=end.isoformat(),
                  device_id=device_id,max_gap_s=cfg.max_integration_gap_s,history_source=source,
                  pv=summaries['pv'].result(),inverter_import=summaries['import'].result(),inverter_export=summaries['export'].result(),
                  house_meter=meter_segments(readings,start,end),
                  # Empty compatibility field for Client a1.6.9; no daily calculation.
                  days=[],daily_detail=False,
                  input_count=count,cache_hit=False,source_signature=digest,
                  incremental=bool(resume),reused_input_count=resume['count'] if resume else 0,
                  quality_note='Покриття і частки джерел — орієнтовна надійність, не метрологічна точність')
                body_end=audit.tell()
                audit.flush();os.fsync(audit.fileno())
            prior_prefixes={item['path']:item for item in resume['prefixes']} if resume else {}
            prefixes=[]
            for p,o,d,size,mtime in files:
                saved=prior_prefixes.get(str(p))
                digest_prefix=saved['digest'] if saved and saved['size']==size and saved['mtime']==mtime else _prefix_hash(p,size,aborted)
                prefixes.append(dict(path=str(p),size=size,mtime=mtime,digest=digest_prefix))
            checkpoint=dict(signature=signature,last_row=previous,count=count,body_start=body_start,body_end=body_end,
                merge_last_local=reader._balance_stats.get('merge_last_local',resume.get('merge_last_local') if resume else None),
                totals={key:bucket.state() for key,bucket in summaries.items()},
                prefixes=prefixes)
            from .deferred_audit import part
            segment=target/('.inputs-'+uuid.uuid4().hex+'.jsonl')
            scratch.replace(segment)
            input_parts.append(part(segment,body_start,body_end))
            report['audit_id']=hashlib.sha256(_json([digest,end.isoformat(),count,hasher.hexdigest(),input_parts]).encode()).hexdigest()
            report['audit_deferred']=True
            reader._balance_stats['audit_segments']=len(input_parts)
            reader._balance_stats['audit_input_bytes']=body_end-body_start
            temp=cache.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            try:
                checksum=hashlib.sha256(_json(report).encode()).hexdigest()
                value=dict(signature=digest,created_at=time.time(),report=report,report_checksum=checksum,
                           deferred_audit=True,input_parts=input_parts,audit_metadata=metadata,checkpoint=checkpoint)
                from .prepared_history import write_json
                write_json(cache,value)
                # Only the disposable expanded audit is superseded. Original
                # archives and immutable input segments remain untouched.
                try:audit_path.unlink(missing_ok=True)
                except OSError:pass # A stale expanded file is rejected by its ID.
                from .deferred_audit import collect_unused
                collect_unused(target)
            finally:temp.unlink(missing_ok=True)
            self.calculations+=1
            return report
        finally:
            scratch.unlink(missing_ok=True)
