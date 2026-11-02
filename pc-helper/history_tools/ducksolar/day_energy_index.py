"""Independent, restartable month contributions; no daily balance reports."""
import hashlib
import json
from datetime import date, datetime, timedelta

from .energy_accounting import ZONE, stamp
from .energy_streaming import (_files, _ordered_rows, _resume_checkpoint,
                               _prefix_hash, _json, _hash_context)
from .prepared_history import write_json


def day(view,anchor,source,cancelled=None):
    from .concurrency import keyed_lock,path_key
    from .graph_energy import accumulate,boundary,summary
    cancelled=cancelled or (lambda:False)
    cache=view.view_path/f'day-energy-index-v1-{anchor}-{source}.json'
    with keyed_lock(path_key('day-energy',cache),cancelled):
        value,diagnostics=_day(view,anchor,source,cancelled)
    # Boundary intervals are applied to a copy and never counted in the checkpoint.
    value=json.loads(_json(value))
    start=datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE);end=start+timedelta(days=1)
    if value['first']:
        before=boundary(view,anchor-timedelta(days=1),source,cancelled,edge='last')['last']
        after=boundary(view,anchor+timedelta(days=1),source,cancelled,edge='first')['first']
        if before:accumulate(value['sums'],value['coverage'],before,value['first'],view.cfg,start=start,end=end,hourly=True)
        if after:accumulate(value['sums'],value['coverage'],value['last'],after,view.cfg,start=start,end=end,hourly=True)
    points=[dict(x=i,label=key,coverage_seconds=value['coverage'][key],**v) for i,(key,v) in enumerate(sorted(value['sums'].items()))]
    return dict(kind='bars',points=points,records=value['records'],reduced=False,energy_summary=summary(points,start,end),forecast_basis=value.get('forecast_basis'),diagnostics=diagnostics)

def _day(view, anchor, source, cancelled):
    grid=True
    reader, cfg = view.reader, view.cfg
    start = datetime(anchor.year, anchor.month, anchor.day, tzinfo=ZONE)
    end = start+timedelta(days=1)
    stats = dict(range_start=start.timestamp(), range_end=end.timestamp(),
                 used_records=0, opened_files=0, read_records=0, projection_hits=0)
    reader._balance_stats = stats
    token = _hash_context.set(({}, stats))
    try:
        files = [entry for entry in _files(reader, start, end, source, cancelled)
                 if entry[2] == anchor]
        from .compact_history import schema_path
        schemas = [(str(p), _prefix_hash(schema_path(p), schema_path(p).stat().st_size, cancelled))
                   for p, origin, day, size, mtime in files if schema_path(p).exists()]
        reader._balance_schemas = dict(schemas)
        signature = dict(algorithm='graph.day.v1', start=start.isoformat(),
                         device_id=view.device_id, source=source,
                         model=reader.model_signature(), readings=[], end=None,
                         files=[(str(p), o, d.isoformat(), size, mtime) for p, o, d, size, mtime in files],
                         schemas=schemas, grid=grid)
        from .compact_history import schema_contract
        signature['schema_contracts']={key:schema_contract(json.loads(schema_path(key).read_text(encoding='utf-8'))) for key,_ in schemas}
        if source != 'Local':
            signature['history_semantics'] = 'smartess-missing-v2'
        digest = hashlib.sha256(_json(signature).encode()).hexdigest()
        cache = view.view_path / f'day-energy-index-v1-{anchor}-{source}.json'
        from .daily_actual import location,empty,add
        coordinates=location(reader)
        old = None
        core_hit=False
        try:
            old = json.loads(cache.read_text(encoding='utf-8'))
            core_hit=old['signature']==digest
            if core_hit and (coordinates is None or old['value'].get('forecast_basis',{}).get('coordinates')==coordinates):
                return old['value'],dict(cache_hit=True,incremental=False,new_rows=0,actual_cache_hit=True)
        except (OSError, ValueError, KeyError):
            old=None
        resume = old.get('checkpoint') if core_hit else _resume_checkpoint(old,files,reader,signature,end,cancelled) if old else None
        value = json.loads(_json(old['value'])) if resume else dict(sums={}, coverage={}, daily={}, daily_coverage={}, records=0, first=None, last=None)
        previous = resume['last_row'] if resume else None
        after = stamp(previous['timestamp']).timestamp() if previous else None
        work = files
        if resume:
            sizes = {p['path']: p['size'] for p in resume['prefixes']}
            work = [e for e in files if str(e[0]) not in sizes or e[3] > sizes[str(e[0])]]
        fields = ('pv_w','output_w','grid_import_w','grid_export_w')
        if coordinates is None:value.pop('forecast_basis',None)
        basis=value.get('forecast_basis')
        extra_rebuild=coordinates is not None and (not basis or basis.get('coordinates')!=coordinates)
        if coordinates is not None:
            fresh,windows,groups=empty(anchor,coordinates)
            if extra_rebuild:basis=fresh
        scan=files if extra_rebuild else work
        captured={str(p):_prefix_hash(p,size,cancelled) for p,origin,day,size,mtime in scan}
        from .cpu_energy import graph as cpu_graph,BLOCK
        pending=[];extra=[];batch_previous=previous;extra_previous=None if extra_rebuild else previous
        extra_rows=0
        with _ordered_rows(reader,scan,source,cancelled,None if extra_rebuild else after,
                           None if extra_rebuild else resume.get('merge_last_local') if resume else None) as rows:
            for row in rows:
                if cancelled():raise ValueError('History query cancelled')
                instant=stamp(row['timestamp']).timestamp()
                if coordinates is not None:
                    extra.append(row);extra_rows+=1
                    if len(extra)>=BLOCK:
                        add(basis,([extra_previous] if extra_previous else [])+extra,windows,groups,cfg,cancelled)
                        extra_previous=extra[-1];extra=[]
                if core_hit or after is not None and instant<=after:continue
                key=stamp(row['timestamp']).replace(minute=0,second=0,microsecond=0).isoformat()
                value['sums'].setdefault(key,{k:None for k in fields});value['coverage'].setdefault(key,{k:0. for k in fields})
                pending.append(row)
                if len(pending)>=BLOCK:
                    cpu_graph(value['sums'],value['coverage'],batch_previous,pending,cfg,grid,start=start,end=end,hourly=True,cancelled=cancelled)
                    batch_previous=row;pending=[]
                if value['first'] is None:value['first']=row
                previous=row;value['records']+=1;stats['used_records']+=1
        if pending:cpu_graph(value['sums'],value['coverage'],batch_previous,pending,cfg,grid,start=start,end=end,hourly=True,cancelled=cancelled)
        if coordinates is not None:
            if extra:add(basis,([extra_previous] if extra_previous else [])+extra,windows,groups,cfg,cancelled)
            basis['records']=value['records'];basis['last_ts']=stamp(previous['timestamp']).timestamp() if previous else None
            value['forecast_basis']=basis
        value['last']=previous
        prior = {p['path']: p for p in resume['prefixes']} if resume else {}
        prefixes = []
        for p, origin, day, size, mtime in files:
            saved = prior.get(str(p))
            sha = saved['digest'] if saved and saved['size'] == size and saved['mtime'] == mtime else _prefix_hash(p, size, cancelled)
            if str(p) in captured and sha!=captured[str(p)]:
                raise ValueError('Graph source prefix changed during calculation')
            prefixes.append(dict(path=str(p), size=size, mtime=mtime, digest=sha))
        checkpoint = dict(signature=signature, last_row=previous, count=value['records'], prefixes=prefixes,
                          merge_last_local=stats.get('merge_last_local', resume.get('merge_last_local') if resume else None))
        # Save the captured prefix even if new rows arrived during calculation.
        # Prefix validation will prove append-only reuse on the next request.
        write_json(cache, dict(signature=digest, checkpoint=checkpoint,
                              report=dict(end=end.isoformat()), value=value))
        return value, dict(cache_hit=False, incremental=bool(resume),
                           new_rows=stats['used_records'],
                           checkpoint_rejected=stats.get('checkpoint_rejected'),actual_extra_rows=extra_rows,actual_upgraded=extra_rebuild,actual_cache_hit=False)
    finally:
        reader._balance_schemas={}
        _hash_context.reset(token)


def cached_boundary(view,anchor,source,edge,cancelled):
 cache=view.view_path/f'day-energy-index-v1-{anchor}-{source}.json'
 try:old=json.loads(cache.read_text('utf-8'))
 except (OSError,ValueError):return None
 if not old.get('checkpoint') or not old.get('value'):return None
 reader=view.reader;start=datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE);end=start+timedelta(days=1)
 files=[entry for entry in _files(reader,start,end,source,cancelled) if entry[2]==anchor]
 sig=old['checkpoint']['signature']
 current=[(str(p),o,d.isoformat(),size,mtime) for p,o,d,size,mtime in files]
 if _json(sig.get('model'))!=_json(reader.model_signature()) or sig.get('source')!=source:return None
 from .compact_history import schema_path
 schemas=[(str(p),_prefix_hash(schema_path(p),schema_path(p).stat().st_size,cancelled)) for p,*_ in files if schema_path(p).exists()]
 if _json(current)==_json(sig['files']) and _json(schemas)==_json(sig.get('schemas',[])):return dict(first=old['value']['first'],last=old['value']['last'])
 if edge!='first':return None
 signature=dict(sig,files=current,schemas=schemas)
 previous=getattr(reader,'_balance_stats',{});reader._balance_stats={}
 try:
  if _resume_checkpoint(old,files,reader,signature,end,cancelled):return dict(first=old['value']['first'],last=None)
 finally:reader._balance_stats=previous
 return None
