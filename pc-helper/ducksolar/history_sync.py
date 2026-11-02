"""Phone half of one-click delta history sync. Immutable transfer snapshot; collection pauses only for capture and commit."""
import json,os,re,hashlib,shutil,copy,time
import csv as csv_module
from pathlib import Path
from datetime import date,datetime
from uuid import uuid4
from .sync_store import Store,atomic,hashed,CONTRACT,checked,fingerprint
from .prepared_history import digest,PreparedHistory
from .compact_history import schema_path
from .preparation_model import model_types

def base(runtime):return Path(runtime.cfg.root_dir)/'Data/HistorySync'
def load(path,default=None):
 try:return json.loads(Path(path).read_text('utf-8'))
 except (OSError,ValueError):return default

def begin(runtime,frozen=None,cancelled=lambda:False):
 root=Path(runtime.cfg.root_dir);folder=base(runtime);folder.mkdir(parents=True,exist_ok=True)
 pending=folder/'local-plan.json'
 if runtime.maintenance_mode and pending.exists():
  local=load(pending);saved=local['request']
  if local.get('inventory_revision')==2 and saved['model']==dict(runtime.history.model_signature()):return saved
  pending.replace(folder/('old-model-'+str(time.time_ns())+'.json'))
 if frozen is None:runtime.enter_maintenance()
 capturing=frozen is not None
 frozen=frozen or {}
 store=Store(folder/'store');reader=runtime.history;today=date.today();streams=load(folder/'streams.json',{});private=[];request_rows={}
 active=load(folder/'current.json',{});known={}
 if active:
  manifest=load(folder/'manifests'/(active['generation']+'.json'),{})
  for row in manifest.get('history',[]):known[str(folder/'active/history'/row['member'])]=row['id']
 for day in reader.available_dates(refresh=True):
  for origin,paths in zip(('Local','SmartESS'),reader.find_day_files(day)):
   for path in paths:
    path=path.resolve();path.relative_to(root.resolve())
    live=day==today and origin=='Local' and path.parent in (reader.paths['inverter_logs'].resolve(),(root/'Data/CompactHistory'/runtime.primary_id/'Local').resolve())
    if cancelled():raise InterruptedError('Синхронізацію зупинено')
    captured=frozen.get(str(path))
    if capturing and live and not captured:continue
    csv=captured['csv'] if captured else store.snapshot(path,immutable=True);meta=schema_path(path);schema=captured['schema'] if captured else store.snapshot(meta,immutable=True) if meta.exists() else None
    relative=path.relative_to(root.resolve()).as_posix();key=relative
    if live:
     previous=streams.get(key);first=b''
     with path.open('rb') as f:f.readline();first=f.readline()
     try:
      with path.open(encoding='utf-8-sig',newline='') as f:initial=next(csv_module.DictReader(f),{})
      decoded=reader.decode_compact(path,initial);instant=reader._parse_dt(decoded.get('time') or decoded.get('Timestamp') or decoded.get('timestamp'),day)
      start=instant.isoformat() if instant else hashlib.sha256(first).hexdigest()
     except (OSError,ValueError,KeyError):start=hashlib.sha256(first).hexdigest()
     stream=previous['stream'] if previous and previous.get('first')==start and csv['bytes']>=previous.get('bytes',0) else uuid4().hex+uuid4().hex
     streams[key]=dict(stream=stream,first=start,bytes=csv['bytes'])
    else:stream=known.get(str(path)) or hashed([origin,day.isoformat(),csv['sha256'],schema['sha256'] if schema else None])
    row=dict(stream=stream,day=day.isoformat(),source=origin,csv=csv,live=live,backup_only=False)
    if schema:row['schema']=schema
    signature=(origin,day.isoformat(),csv['sha256'],schema['sha256'] if schema else None)
    if signature not in request_rows or live:request_rows[signature]=row
    private.append(dict(path=relative,csv=csv,schema=schema,day=day.isoformat(),signature=list(signature),stream=stream,live=live))
 # Original-only imports suppressed by the calculation reader are still archived.
 seen={p['path'] for p in private}
 for original_root in (root/'Data/ImportedArchive').glob('*/Originals'):
  for path in original_root.rglob('*.csv'):
   rel=path.relative_to(root).as_posix()
   if rel in seen or path.is_symlink():continue
   try:day=date.fromisoformat(path.stem)
   except ValueError:continue
   origin=reader._classify(path);csv=store.snapshot(path,immutable=True);meta=schema_path(path);schema=store.snapshot(meta,immutable=True) if meta.exists() else None
   signature=(origin,day.isoformat(),csv['sha256'],schema['sha256'] if schema else None);stream=hashed(['backup',*signature])
   row=dict(stream=stream,day=day.isoformat(),source=origin,csv=csv,live=False,backup_only=True)
   if schema:row['schema']=schema
   request_rows.setdefault(signature,row);private.append(dict(path=rel,csv=csv,schema=schema,day=day.isoformat(),signature=list(signature),stream=stream,live=False))
 # Seed references to existing caches. No second archive, no monolithic ZIP.
 patterns=[(root/'Data/PreparedHistory/objects','*'),(root/'Data/PreparedHistory/packages','**/*'),(root/'Data/EnergyWork/PreparedInputs-v3','*.db'),(root/'Data/HistoryViews','**/*.json'),(root/'Data/EnergyAudit','**/*')]
 from .history_migration import active_folder
 old=active_folder(root,runtime.primary_id)
 if old:
  patterns.extend([(old.parent/'balances','*'),(old.parent/'seeds','*')])
 for directory,pattern in patterns:
  for path in directory.glob(pattern):
   if cancelled():raise InterruptedError('Синхронізацію зупинено')
   if path.is_file() and not path.is_symlink() and path.suffix in ('.json','.gz','.db','.jsonl'):
    if path.suffix=='.db' and Path(str(path)+'-wal').exists() and Path(str(path)+'-wal').stat().st_size:
     import sqlite3
     temp=folder/('sqlite-'+uuid4().hex+'.db');src=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(temp)
     try:src.backup(dst);dst.execute('PRAGMA journal_mode=DELETE')
     finally:dst.close();src.close()
     store.snapshot(temp,immutable=True);temp.unlink()
    else:
     try:store.snapshot(path,immutable=True,cancelled=cancelled)
     except OSError:continue
     except ValueError as error:
      if 'File changed during sync snapshot' not in str(error):raise
 rows=sorted(request_rows.values(),key=lambda r:(r['source'],r['day'],r['stream']))
 request=dict(contract=CONTRACT,installation=runtime.cfg.installation_id,device_id=runtime.primary_id,pn=runtime.cfg.dtu_pn,model=dict(reader.model_signature()),model_types=model_types(dict(reader.model_signature())),readings_json=json.dumps(__import__('ducksolar.wire',fromlist=['encode']).encode(runtime.storage.list_meter_readings(limit=100000)),ensure_ascii=False,separators=(',',':')),files=rows)
 request['capabilities']=['compressed-artifacts-v1']
 request['id']=hashed(request)[:32]
 for row in private:row['stream']=request_rows[tuple(row['signature'])]['stream']
 atomic(pending,dict(request=request,private=private,inventory_revision=2));atomic(folder/'streams.json',streams);store.save()
 runtime.migration_state.update(sync_session=request['id']);atomic(runtime.migration_path,runtime.migration_state)
 return request

def block_source(runtime,sha):
 from .sync_store import session_store
 folder=base(runtime)
 with session_store(folder/'store') as store:data=store.read(sha)
 path=folder/'upload-blocks'/sha;path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():path.write_bytes(data)
 return str(path)

def transfer_plan(runtime,manifest_path,limit=32):
 from .sync_store import session_store
 with session_store(base(runtime)/'store') as store:return _transfer_plan(runtime,manifest_path,limit,store)

def _transfer_plan(runtime,manifest_path,limit,store):
 folder=base(runtime);manifest=load(manifest_path);local=load(folder/'local-plan.json');request=local['request']
 for key in ('contract','id','installation','device_id','pn','model','model_types','readings_json'):
  if manifest.get(key)!=request.get(key):raise ValueError('Sync manifest identity/model mismatch: '+key)
 cache=getattr(runtime,'_sync_transfer_queue',None)
 token=(request['id'],str(manifest_path),fingerprint(manifest_path))
 if not cache or cache['token']!=token:
  entries=[]
  for row in manifest['history']:
   entries.extend([('history',row['csv'],None),('schema',row['schema'],None)])
  for row in manifest['artifacts']:entries.append((row['role'],row['snapshot'],row.get('content_snapshot')))
  seen=set();queue=[];categories={}
  for role,desc,content in entries:
   checked(desc)
   if content is not None:checked(content)
   if store.existing(content or desc) is not None:continue
   for block in desc['blocks']:
    if block['sha256'] in seen:continue
    seen.add(block['sha256'])
    if not store.has(block):queue.append(block);categories[role]=categories.get(role,0)+block['bytes']
  cache=dict(token=token,queue=queue,total_bytes=sum(b['bytes'] for b in queue),categories=categories)
  runtime._sync_transfer_queue=cache;store.save()
 # Advance only accepted/verified blocks. Repeated calls never rescan the archive.
 queue=cache['queue']
 while queue and store.has(queue[0]):queue.pop(0)
 store.save();remaining=sum(b['bytes'] for b in queue)
 return dict(items=queue[:limit],total_bytes=cache['total_bytes'],remaining_bytes=remaining,received_bytes=cache['total_bytes']-remaining,categories=cache['categories'])

def missing(runtime,manifest_path,limit=32):return transfer_plan(runtime,manifest_path,limit)['items']

def materialize_artifact(store,row,target,mutable=False):
 desc=row.get('content_snapshot')
 if not desc:return store.materialize(row['snapshot'],target,mutable=mutable)
 checked(desc)
 if row.get('encoding')!='gzip':raise ValueError('Unsupported artifact encoding')
 if store.existing(desc) is not None:return store.materialize(desc,target,mutable=mutable)
 import gzip
 packed=store.root/'compressed'/(row['snapshot']['sha256']+'.gz');store.materialize(row['snapshot'],packed)
 raw=store.root/'expanded'/desc['sha256'];raw.parent.mkdir(parents=True,exist_ok=True);tmp=raw.with_suffix('.tmp')
 try:
  total=0;sha=hashlib.sha256()
  with gzip.open(packed,'rb') as inp,tmp.open('wb') as out:
   while block:=inp.read(1024*1024):
    total+=len(block)
    if total>desc['bytes']:raise ValueError('Oversized artifact')
    sha.update(block);out.write(block)
  if total!=desc['bytes'] or sha.hexdigest()!=desc['sha256']:raise ValueError('Expanded artifact checksum mismatch')
  tmp.replace(raw);actual=store.snapshot(raw,immutable=True)
  if actual!=desc:raise ValueError('Artifact block contract mismatch')
  return store.materialize(desc,target,mutable=mutable)
 finally:tmp.unlink(missing_ok=True)


def safe_member(member):
 parts=member.split('/')
 if any(p in ('','.','..') or ':' in p or '\\' in p for p in parts) or len(parts)!=3 or parts[0] not in ('Local','SmartESS'):raise ValueError('Invalid synchronized history path')
 date.fromisoformat(Path(parts[-1]).stem)
 return member

def remove_file(path,cleanup):
 st=path.stat()
 if st.st_nlink==1:cleanup['freed_bytes']+=getattr(st,'st_blocks',0)*512 if hasattr(st,'st_blocks') else st.st_size
 path.unlink();cleanup['removed_files']+=1

def remove_tree(path,cleanup):
 # Only callers' validated derived trees; count blocks whose last hardlinks
 # all live inside this tree, rather than confusing logical with physical size.
 import collections
 inodes=collections.Counter();stats={}
 for p in path.rglob('*'):
  if p.is_file() and not p.is_symlink():
   st=p.stat();key=(st.st_dev,st.st_ino);inodes[key]+=1;stats[key]=st
 for key,count in inodes.items():
  st=stats[key]
  if count==st.st_nlink:cleanup['freed_bytes']+=getattr(st,'st_blocks',0)*512 if hasattr(st,'st_blocks') else st.st_size
 cleanup['removed_files']+=sum(inodes.values());shutil.rmtree(path)

def prefix_digest(path,size):
 remaining=size;sha=hashlib.sha256()
 with Path(path).open('rb') as f:
  while remaining:
   data=f.read(min(1024*1024,remaining))
   if not data:raise ValueError('History prefix truncated')
   sha.update(data);remaining-=len(data)
 return sha.hexdigest()

def progress(runtime,stage,done=0,total=0):
 now=time.time();prior=load(base(runtime)/'progress.json',{})
 value=dict(stage=stage,done=done,total=total,updated=now,stage_started=prior.get('stage_started',now) if prior.get('stage')==stage else now)
 runtime._sync_progress=value;atomic(base(runtime)/'progress.json',value)
 if prior.get('stage')!=stage and hasattr(runtime,'logs'):runtime.logs.event('History sync stage',code='history.sync.stage',stage=stage,previous=prior.get('stage',''),previous_s=round(max(0,now-prior.get('stage_started',now)),3))

def cleanup_after_commit(runtime):
 folder=base(runtime);task=load(folder/'cleanup-pending.json',{})
 if not task:return {}
 # A later paused/active transfer owns new blocks which the older GC intent
 # cannot yet know. Keep them pinned until that transfer commits.
 task_time=(folder/'cleanup-pending.json').stat().st_mtime_ns
 if (folder/'local-plan.json').exists() or any(p.stat().st_mtime_ns>task_time for p in folder.glob('paused-*.json')):return dict(deferred_reason='pending_sync')
 cleanup=task['cleanup'];store=Store(folder/'store')
 try:
  progress(runtime,'cleanup')
  for row in task.get('retired',[]):
   path=Path(row['path']);path.resolve().relative_to(Path(runtime.cfg.root_dir).resolve())
   if path.is_file() and store.snapshot(path)['sha256']==row['csv']['sha256']:
    remove_file(path,cleanup)
    if schema_path(path).exists():remove_file(schema_path(path),cleanup)
  result=store.prune(task['keep']);store.save()
  cleanup['removed_files']+=result['removed_files'];cleanup['freed_bytes']+=result['freed_bytes']
  backup=Path(task['backup'])
  if backup.exists():backup.resolve().relative_to(folder.resolve());remove_tree(backup,cleanup)
  for preflight in folder.glob('preflight-*'):
   if preflight.is_dir():remove_tree(preflight,cleanup)
  for directory in (store.root/'compressed',store.root/'expanded',folder/'upload-blocks',folder/'downloads',folder/'raw-checkpoints'):
   for old in directory.glob('*'):
    if old.is_file():remove_file(old,cleanup)
  referenced={str(Path(p['path']).resolve()) for path in (Path(runtime.cfg.root_dir)/'Data/EnergyAudit'/runtime.primary_id).glob('*.summary.json') for p in load(path,{}).get('input_parts',[])}
  for old in (folder/'segments').glob('*'):
   if old.is_file() and str(old.resolve()) not in referenced:remove_file(old,cleanup)
  for old in (folder/'manifests').glob('*.json'):
   if old.stem!=task['generation']:remove_file(old,cleanup)
  legacy=Path(runtime.cfg.root_dir)/'Data/CompactHistory/packages'
  for old in legacy.glob('*'):
   if old.is_dir() and re.fullmatch('[0-9a-f]{64}',old.name) and not old.is_symlink():remove_tree(old,cleanup)
  atomic(folder/'cleanup-report.json',cleanup);(folder/'cleanup-pending.json').unlink(missing_ok=True)
 except Exception as error:
  cleanup['deferred_error']=str(error);atomic(folder/'cleanup-report.json',cleanup)
 return cleanup

def prepare_activation(runtime,manifest_path):
 folder=base(runtime);manifest=load(manifest_path);generation=hashed(manifest);store=Store(folder/'store')
 reserve=sum((a.get('content_snapshot') or a['snapshot'])['bytes'] for a in manifest['artifacts'])+sum(r['csv']['bytes']+r['schema']['bytes'] for r in manifest['history'])
 if shutil.disk_usage(folder).free<reserve+16*1024*1024:raise OSError('Недостатньо місця для безпечної активації історії')
 progress(runtime,'validating',0,len(manifest['artifacts']))
 for row in manifest['history']:safe_member(row['member'])
 for desc in [d for r in manifest['history'] for d in (r['csv'],r['schema'])]:
  if store.existing(desc) is None:store.materialize(desc,store.root/'files'/desc['sha256'])
 preflight=folder/('preflight-'+generation);preflight.mkdir(exist_ok=True)
 for n,row in enumerate(manifest['artifacts']):
  if row['role'] not in ('prepared','view','index','balance','segment','checkpoint') or '/' in row['name'] or '\\' in row['name'] or ':' in row['name'] or row['name'].startswith('.'):raise ValueError('Invalid sync artifact')
  if row['role']=='index' and not re.fullmatch(r'[0-9a-f]{64}\.db',row['name']):raise ValueError('Invalid sync SQLite name')
  materialize_artifact(store,row,preflight/str(n))
  if n%64==0:progress(runtime,'validating',n,len(manifest['artifacts']))
 by_work={r['work_path']:r for r in manifest['history']}
 for row in manifest['artifacts']:
  if row['role']!='checkpoint':continue
  desc=row.get('content_snapshot') or row['snapshot'];value=load(store.existing(desc));checkpoint=value['checkpoint']
  if any(p not in by_work for p,*_ in checkpoint['signature']['files']):raise ValueError('Checkpoint source missing')
  segments={a['name'] for a in manifest['artifacts'] if a['role']=='segment'}
  if any(hashed(p['path'])+'.jsonl' not in segments for p in value['input_parts']):raise ValueError('Missing synchronized checkpoint segment')
  for prefix in checkpoint['prefixes']:
   source=by_work.get(prefix['path'])
   if not source or prefix['size']>source['csv']['bytes'] or prefix_digest(store.existing(source['csv']),prefix['size'])!=prefix['digest']:raise ValueError('Checkpoint input checksum mismatch')
 store.save()
 runtime._sync_validated=(str(manifest_path),fingerprint(manifest_path))

def activate(runtime,manifest_path):
 cleanup=dict(removed_files=0,freed_bytes=0)
 root=Path(runtime.cfg.root_dir);folder=base(runtime);manifest=load(manifest_path);pending=load(folder/'local-plan.json');plan=pending['request'];private=pending['private']
 for key in ('contract','id','installation','device_id','pn','model','model_types','readings_json'):
  if manifest.get(key)!=plan.get(key):raise ValueError('Sync activation identity mismatch')
 if dict(runtime.history.model_signature())!=plan['model']:raise ValueError('Model changed during synchronization')
 receipts={r['stream']:r for r in manifest['receipts'] if r['channel']=='phone'}
 for row in plan['files']:
  receipt=receipts.get(row['stream'])
  if not receipt or receipt['csv']!=row['csv']['sha256'] or receipt.get('schema')!=row.get('schema',{}).get('sha256'):raise ValueError('PC did not confirm original archive')
 forecast_path=root/'Data/ForecastSummaries'/((runtime.cfg.history_device_id or runtime.primary_id)+'.json')
 forecasts=load(forecast_path,{})
 from .forecast_summary import portable_revision
 eligible={};forecast_inputs=PreparedHistory(runtime.history)
 lat,lon=runtime.cfg.weather_latitude,runtime.cfg.weather_longitude
 try:
  location=runtime.forecast.analytics.weather(runtime.primary_id).get('location',{})
  lat,lon=location.get('latitude',lat),location.get('longitude',lon)
 except AttributeError:pass
 for day_text,value in forecasts.items():
  try:
   day=date.fromisoformat(day_text);files=[p for group in runtime.history.find_day_files(day) for p in group]
   old=hashlib.sha256(repr((runtime.history._files_signature(files),runtime.history.model_signature(),lat,lon,'solar-v2-load')).encode()).hexdigest()
   new=portable_revision(runtime.history,day,lat,lon,forecast_inputs)
   if value.get('revision') in (old,new):eligible[day_text]=new
  except (OSError,ValueError,KeyError,TypeError):continue
 store=Store(folder/'store');generation=hashed(manifest);stored=folder/'manifests'/(generation+'.json');atomic(stored,manifest)
 # Verify source fingerprints before any cleanup. A newer local file is retained.
 originals=[];prior_journal=load(folder/'activation.json',{});live_outputs=prior_journal.get('live_outputs',{})
 for row in private:
  path=root/row['path'];path.resolve().relative_to(root.resolve())
  if path.exists():
   actual=store.snapshot(path)
   if actual['sha256']!=row['csv']['sha256']:
    appended=row['live'] and actual['bytes']>=row['csv']['bytes'] and prefix_digest(path,row['csv']['bytes'])==row['csv']['sha256']
    recovering=load(folder/'activation.json',{}).get('stage')=='applying'
    canonical=next((r for r in manifest['history'] if r.get('external_stream')==row['stream'] and r['csv']['sha256']==actual['sha256']),None)
    recovered=live_outputs.get(row['stream'],{}).get('csv',{}).get('sha256')==actual['sha256']
    if not appended and not (recovering and (canonical or recovered)):raise ValueError('Phone history changed during synchronization')
   originals.append((path,row))
 installed=load(folder/'installed.json',{})
 if load(folder/'current.json',{}).get('generation')==generation and installed:
  intact=True
  for path,expected in installed.items():
   try:
    if fingerprint(path)!=expected:intact=False;break
   except OSError:intact=False;break
  if intact:
   runtime.migration_state.update(active=False,stage='ready',sync_session='');atomic(runtime.migration_path,runtime.migration_state)
   (folder/'local-plan.json').unlink(missing_ok=True);(folder/'activation.json').unlink(missing_ok=True);store.save()
   return dict(state='ready',generation=generation,stats=manifest['stats'],unchanged=True,transferred_bytes=0)
 active=folder/'active';stage=folder/('stage-'+generation);backup=folder/('previous-'+generation)
 journal=folder/'activation.json'
 if getattr(runtime,'_sync_validated',None)!=(str(manifest_path),fingerprint(manifest_path)):prepare_activation(runtime,manifest_path)
 atomic(journal,dict(generation=generation,manifest=str(stored),stage='applying',live_outputs=live_outputs))
 runtime.migration_state.update(active=True,stage='activated');atomic(runtime.migration_path,runtime.migration_state)
 stage.mkdir(parents=True,exist_ok=True);(stage/'history').mkdir(exist_ok=True);mapping={};legacy_mapping={};live_by_stream={r['stream']:r for r in private if r['live']}
 for row in manifest['history']:
  member=safe_member(row['member']);destination=active/'history'/member
  external=live_by_stream.get(row.get('external_stream'))
  if external:
   destination=root/external['path'];output=stage/'live'/row['external_stream'];output.parent.mkdir(parents=True,exist_ok=True)
   saved=live_outputs.get(row['external_stream'])
   if saved:
    store.materialize(saved['csv'],output,mutable=True);store.materialize(saved['schema'],schema_path(output),mutable=True)
   else:
    store.materialize(row['csv'],output,mutable=True);store.materialize(row['schema'],schema_path(output),mutable=True)
    boundary=external['csv']['bytes']
    if destination.exists() and destination.stat().st_size>boundary:
     from .compact_history import Codec,MARKER,EXTRAS
     from .sync_reconcile import schema_extends
     if schema_path(destination).exists() and destination.stat().st_size>=row['csv']['bytes'] and prefix_digest(destination,row['csv']['bytes'])==row['csv']['sha256'] and schema_extends(schema_path(output),schema_path(destination)):
      shutil.copyfile(destination,output);shutil.copy2(schema_path(destination),schema_path(output))
     else:
      codec=Codec(output)
      with destination.open('rb') as inp:header=inp.readline().decode('utf-8-sig');inp.seek(boundary);tail=inp.read().decode('utf-8')
      import io
      fields=next(csv_module.reader([header]))
      with output.open('a',encoding='utf-8',newline='') as out:
       writer=csv_module.DictWriter(out,codec.schema['fields']+[MARKER,EXTRAS],lineterminator='\n')
       for cells in csv_module.reader(io.StringIO(tail)):
        if len(cells)!=len(fields):raise ValueError('Incomplete live history tail')
        writer.writerow(codec.encode(runtime.history.decode_compact(destination,dict(zip(fields,cells)))))
       out.flush();os.fsync(out.fileno())
    saved=dict(csv=store.snapshot(output,immutable=True),schema=store.snapshot(schema_path(output),immutable=True))
    live_outputs[row['external_stream']]=saved;atomic(journal,dict(generation=generation,manifest=str(stored),stage='applying',live_outputs=live_outputs))
  else:
   store.materialize(row['csv'],stage/'history'/member);store.materialize(row['schema'],schema_path(stage/'history'/member))
  mapping[row['work_path']]=str(destination)
  for old,row_private in originals:
   if row_private['csv']['sha256']==row['csv']['sha256'] and row_private['schema']:
     from .sync_reconcile import schema_equal
     if schema_equal(schema_path(old),store.existing(row['schema'])):legacy_mapping[str(old)]=str(destination)
 artifacts=manifest['artifacts'];segments={};checkpoints=[];legacy_files=[]
 progress(runtime,'installing',0,len(artifacts))
 for artifact_number,row in enumerate(artifacts):
  if artifact_number%64==0:progress(runtime,'installing',artifact_number,len(artifacts))
  role,name,desc=row['role'],row['name'],row['snapshot']
  if '/' in name or '\\' in name or ':' in name or name.startswith('.'):raise ValueError('Invalid sync artifact')
  if role=='prepared':target=root/'Data/PreparedHistory/objects'/name;mutable=False
  elif role=='view':target=root/'Data/HistoryViews'/runtime.primary_id/name;mutable=True
  elif role=='index':
   if not re.fullmatch(r'[0-9a-f]{64}\.db',name):raise ValueError('Invalid sync SQLite name')
   target=root/'Data/EnergyWork/PreparedInputs-v3'/name;mutable=True
   for suffix in ('-wal','-shm'):Path(str(target)+suffix).unlink(missing_ok=True)
  elif role=='balance':target=stage/'balances'/name;mutable=False
  elif role=='segment':target=folder/'segments'/name;mutable=False;segments[name]=str(target)
  elif role=='checkpoint':target=folder/'raw-checkpoints'/desc['sha256'];mutable=False;checkpoints.append((name,target))
  else:raise ValueError('Unsupported sync artifact role')
  materialize_artifact(store,row,target,mutable=mutable)
  if role=='balance':legacy_files.append(dict(name='balances/'+name,bytes=desc['bytes'],sha256=desc['sha256']))
 for row in manifest['history']:
  if row.get('external_stream') in live_outputs:
   target=root/live_by_stream[row['external_stream']]['path'];saved=live_outputs[row['external_stream']]
   store.materialize(saved['csv'],target,mutable=True);store.materialize(saved['schema'],schema_path(target),mutable=True)
 if (stage/'live').exists():shutil.rmtree(stage/'live')
 progress(runtime,'committing')
 # Compatibility metadata lets the existing completed-month reader reuse totals.
 atomic(stage/'generation.json',dict(generation=generation))
 atomic(stage/'manifest.json',dict(device_id=runtime.primary_id,model=manifest['model'],model_types=manifest['model_types'],readings_json=manifest['readings_json'],files=legacy_files))
 if load(active/'generation.json',{}).get('generation')==generation:
  store.rebase(stage,active)
  if stage.exists():shutil.rmtree(stage)
 else:
  if active.exists() and not backup.exists():active.replace(backup);store.rebase(active,backup)
  if stage.exists():stage.replace(active);store.rebase(stage,active)
 from .energy_streaming import _json
 from .deferred_audit import part
 # Rebase pre-existing local checkpoint paths without changing their totals.
 audit_root=root/'Data/EnergyAudit'/runtime.primary_id;audit_root.mkdir(parents=True,exist_ok=True)
 for path in audit_root.glob('*.summary.json'):
  value=load(path,{})
  if value.get('portable_audit'):
   candidate=active/'balances'/Path(value['portable_audit']).name
   if candidate.exists():value['portable_audit']=str(candidate);atomic(path,value)
   elif Path(value['portable_audit']).exists():
    desc=store.snapshot(Path(value['portable_audit']),immutable=True);target=folder/'legacy-audits'/(desc['sha256']+'.gz');store.materialize(desc,target);value['portable_audit']=str(target);atomic(path,value)
  checkpoint=value.get('checkpoint')
  if not checkpoint:continue
  signature=checkpoint['signature']
  if all(p in legacy_mapping for p,*_ in signature.get('files',[])):
   for row in checkpoint['prefixes']:
    path_new=Path(legacy_mapping[row['path']]);row.update(path=str(path_new),mtime=path_new.stat().st_mtime_ns)
   signature['files']=[(legacy_mapping[p],o,d,size,Path(legacy_mapping[p]).stat().st_mtime_ns) for p,o,d,size,mtime in signature['files']]
   signature['schemas']=[(legacy_mapping[p],sha) for p,sha in signature.get('schemas',[])]
   signature['schema_contracts']={legacy_mapping[p]:v for p,v in signature.get('schema_contracts',{}).items()}
   value['signature']=hashlib.sha256(_json(signature).encode()).hexdigest();value['audit_metadata'].update(signature);atomic(path,value)
 for path in (root/'Data/HistoryViews'/runtime.primary_id).glob('*.json'):
  value=load(path,{})
  checkpoint=value.get('checkpoint');signature=checkpoint.get('signature') if checkpoint else None
  checkpoint_mapping={**legacy_mapping,**mapping}
  if not signature or not all(p in checkpoint_mapping for p,*_ in signature.get('files',[])):continue
  signature['files']=[(checkpoint_mapping[p],o,d,size,Path(checkpoint_mapping[p]).stat().st_mtime_ns) for p,o,d,size,mtime in signature['files']]
  signature['schemas']=[(checkpoint_mapping[p],sha) for p,sha in signature.get('schemas',[])]
  signature['schema_contracts']={checkpoint_mapping[p]:v for p,v in signature.get('schema_contracts',{}).items()}
  for item in checkpoint.get('prefixes',[]):
   target=Path(checkpoint_mapping[item['path']]);item.update(path=str(target),mtime=target.stat().st_mtime_ns)
  value['signature']=hashlib.sha256(_json(signature).encode()).hexdigest();atomic(path,value)
 for name,path in checkpoints:
  value=load(path);checkpoint=value['checkpoint'];signature=checkpoint['signature']
  if any(p not in mapping for p,*_ in signature['files']):raise ValueError('Checkpoint source missing from synchronized history')
  for row in checkpoint['prefixes']:
   target=Path(mapping[row['path']])
   if target.stat().st_size<row['size'] or prefix_digest(target,row['size'])!=row['digest']:raise ValueError('Checkpoint input checksum mismatch')
   row.update(path=str(target),mtime=target.stat().st_mtime_ns)
  signature['files']=[(mapping[p],o,d,size,Path(mapping[p]).stat().st_mtime_ns) for p,o,d,size,mtime in signature['files']]
  signature['schemas']=[(mapping[p],sha) for p,sha in signature.get('schemas',[])]
  signature['schema_contracts']={mapping[p]:v for p,v in signature.get('schema_contracts',{}).items()}
  updated=[]
  for item in value['input_parts']:
   key=hashed(item['path'])+'.jsonl'
   if key not in segments:raise ValueError('Missing synchronized checkpoint segment')
   updated.append(part(Path(segments[key]),item['start'],item['end']))
  value['input_parts']=updated;value['signature']=hashlib.sha256(_json(signature).encode()).hexdigest();value['audit_metadata'].update(signature);value['audit_metadata']['source_signature']=value['signature']
  atomic(audit_root/name,value)
 identity_index=load(root/'Data/PreparedHistory/index.json',{})
 for row in manifest['history']:
  path=Path(mapping[row['work_path']]);meta=schema_path(path)
  actual=live_outputs.get(row.get('external_stream'),row)
  identity_index[str(path.resolve())]=dict(fingerprint=fingerprint(path)+fingerprint(meta),raw_sha256=hashlib.sha256((actual['csv']['sha256']+actual['schema']['sha256']).encode()).hexdigest())
 atomic(root/'Data/PreparedHistory/index.json',identity_index)
 atomic(folder/'current.json',dict(contract=CONTRACT,generation=generation,device_id=runtime.primary_id,history=str(active/'history')))
 runtime.history._dates_cache=None
 forecast_inputs=PreparedHistory(runtime.history)
 for day_text,expected in eligible.items():
  try:
   actual=portable_revision(runtime.history,date.fromisoformat(day_text),lat,lon,forecast_inputs)
   if actual==expected:forecasts[day_text]['revision']=actual
  except (OSError,ValueError,KeyError,TypeError):pass
 if forecasts:atomic(forecast_path,forecasts)
 # Carry the completed-day scheduling hints across the path change too.
 # They are hints only; readers still verify model/schema/content before use.
 revisions=load(root/'Data/PreparedHistory/background-revisions.json',{})
 completed={};graph_index=load(root/'Data/PreparedHistory/graph-cache-index.json',{})
 for day in runtime.history.available_dates(refresh=True):
  if day>=date.today():continue
  local,smart=runtime.history.find_day_files(day);files=local+smart
  completed[day.isoformat()]=[runtime.history._files_signature(files),runtime.history.model_signature()]
  for source in ('Local','SmartESS','Auto'):
   path=root/'Data/HistoryViews'/runtime.primary_id/f'hourly-index-v1-{day.isoformat()}-{source}-telemetry.json'
   cached=load(path,{});prior=cached.get('checkpoint',{}).get('signature',{})
   current=[]
   for origin,paths in [('Local',local),('SmartESS',smart)]:
    if source not in ('Auto',origin):continue
    for item in paths:st=item.stat();current.append((str(item),origin,day.isoformat(),st.st_size,st.st_mtime_ns))
   if _json(prior.get('files'))!=_json(current) or _json(prior.get('model'))!=_json(runtime.history.model_signature()):continue
   expected_schemas=dict(prior.get('schemas',[]))
   if any(expected_schemas.get(str(item))!=digest(schema_path(item)) for origin,paths in [('Local',local),('SmartESS',smart)] if source in ('Auto',origin) for item in paths if schema_path(item).exists()):continue
   value=[runtime.history._files_signature(local),runtime.history._files_signature(smart),runtime.history.model_signature(),source,True,'unified-full-v1']
   stamp=path.stat();graph_index[f'{runtime.primary_id}:{day}:{source}']=dict(input=hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest(),output=[stamp.st_size,stamp.st_mtime_ns,stamp.st_ino])
 revisions[runtime.primary_id]=completed
 atomic(root/'Data/PreparedHistory/background-revisions.json',revisions)
 atomic(root/'Data/PreparedHistory/graph-cache-index.json',graph_index)
 # The finalized active tree is selected before removing verified obsolete copies.
 # Current live files remain appendable, so subsequent syncs send only new blocks.
 retired=[dict(path=str(path),csv=row['csv'],schema=row.get('schema')) for path,row in originals if not row['live'] and not path.is_relative_to(active)]
 runtime.history._dates_cache=None;runtime.history._compact_codecs={}
 # Retain exactly the current synchronized objects and any audit segments
 # still referenced by a local numerical checkpoint. Old raw snapshots remain
 # archived on the PC, not duplicated indefinitely on the phone.
 keep=[]
 for row in manifest['history']:keep.extend([row['csv'],row['schema']])
 # Retain the verified expanded object. Compressed transport can be absent
 # when a matching raw object was reused, and is disposable after commit.
 keep.extend(a.get('content_snapshot') or a['snapshot'] for a in manifest['artifacts'])
 for value in live_outputs.values():keep.extend([value['csv'],value['schema']])
 keep.append(store.snapshot(stored,immutable=True))
 for local_summary in audit_root.glob('*.summary.json'):
  value=load(local_summary,{})
  for part in value.get('input_parts',[]):
   if Path(part['path']).is_file():keep.append(store.snapshot(Path(part['path']),immutable=True))
 installed={}
 for directory in (active,root/'Data/PreparedHistory/objects',root/'Data/EnergyWork/PreparedInputs-v3',root/'Data/HistoryViews'/runtime.primary_id,audit_root,folder/'segments'):
  for path in directory.rglob('*'):
   if path.is_file() and not path.name.endswith(('-wal','-shm')):installed[str(path.resolve())]=fingerprint(path)
 atomic(folder/'installed.json',installed)
 store.save();atomic(folder/'cleanup-pending.json',dict(generation=generation,keep=keep,backup=str(backup),cleanup=cleanup,retired=retired))
 atomic(journal,dict(generation=generation,manifest=str(stored),stage='complete'))
 runtime.migration_state.update(active=False,stage='ready',sync_session='');atomic(runtime.migration_path,runtime.migration_state)
 (folder/'local-plan.json').unlink(missing_ok=True);journal.unlink(missing_ok=True)
 progress(runtime,'committed')
 return dict(state='ready',generation=generation,stats=manifest['stats'],cleanup=cleanup,transferred_bytes=store.stats['new_bytes'])
