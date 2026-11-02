"""One persistent workspace per inverter/model. No per-session copies or full ZIP."""
import argparse,json,sys,copy,hashlib,os,sqlite3,time,gzip,shutil
from pathlib import Path
from datetime import date,datetime,timedelta
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ducksolar.sync_store import Store,atomic,hashed,CONTRACT,fingerprint
from ducksolar.preparation_model import apply_model,decode_model
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.prepared_history import PreparedHistory,digest
from ducksolar.compact_history import schema_path,convert,Codec
from ducksolar.energy_accounting import ZONE
from ducksolar.energy_streaming import MonthAccounting,_files
from ducksolar.balance_portable import revision
from ducksolar.history_views import HistoryViews
from ducksolar.hourly_projection import day as hourly,columns,export_portable
from preparation_lock import preparation_lock
parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--session',required=True);args=parser.parse_args()
root=args.root.resolve();base=root/'Data/HistorySync';session=base/'sessions'/args.session;plan=json.loads((session/'plan.json').read_text('utf-8'))
scope=base/'scopes'/hashed([plan['device_id'],plan['pn']]);scope.mkdir(parents=True,exist_ok=True)
model_key=hashed([decode_model(plan['model'],plan['model_types']),'sync.compute.v1']);state_path=scope/'models'/model_key/'state.json'
try:state=json.loads(state_path.read_text('utf-8'))
except (OSError,ValueError):state={}
store=Store(scope/'store');today=datetime.now(ZONE).date()
stats=dict(new_inputs=0,inputs_unchanged=0,new_conversions=0,days_checked=0,days_recalculated=0,day_new_rows=0,months_checked=0,months_recalculated=0,balance_new_rows=0,sqlite_backups=0,artifacts_reused=0,pc_archive_files=0)
def cancelled():return (session/'cancel.request').exists()
def check():
 if cancelled():raise InterruptedError('Синхронізацію зупинено')
def progress(stage,**extra):
 check();atomic(session/'state.json',dict(state='preparing',id=args.session,stage=stage,stats=stats,**extra))
class Meters:
 def list_meter_readings(self,**kwargs):
  from ducksolar.wire import decode
  return decode(json.loads(plan['readings_json']))
def scope_matches(p):return all(p.get(k)==plan[k] for k in ('device_id','pn'))
def read_json(path,default=None):
 try:return json.loads(path.read_text('utf-8'))
 except (OSError,ValueError):return default

def run():
 progress('discovering_changes')
 work=Path(state['workspace']) if state.get('workspace') else None;adopted=None
 if work is None:
  # Pin the most recent completed workspace in place. Paths/inodes/checkpoints
  # remain valid: not one old projection is copied or invalidated by a new id.
  candidates=[]
  for p in (root/'Data/AndroidSupport/Migrations').glob('*/result.json'):
   old=read_json(p.with_name('plan.json'),{});result=read_json(p,{})
   if scope_matches(old) and result.get('state')=='ready' and decode_model(old['model'],old.get('model_types'))==decode_model(plan['model'],plan['model_types']):candidates.append(p)
  if candidates:
   adopted=max(candidates,key=lambda p:p.stat().st_mtime_ns).parent;work=adopted/'work'
   old_plan=read_json(adopted/'plan.json',{})
   state.update(processed_revision='adopted',readings_json=old_plan.get('readings_json'),last_day=(today-timedelta(days=1)).isoformat())
  else:work=scope/'models'/model_key/'work'
  state['workspace']=str(work);state['adopted_from']=str(adopted) if adopted else None
  atomic(scope/'workspace-reference.json',dict(workspace=str(work),model=model_key,pinned=True))
 cfg=AppConfig(root_dir=str(work),history_device_id=plan['device_id']);cfg.primary_device_id=plan['device_id'];cfg.dtu_pn=plan['pn'];apply_model(cfg,plan['model'],plan['model_types'])
 history=work/'Data/CompactHistory'/plan['device_id'];history.mkdir(parents=True,exist_ok=True)
 dataset=state.setdefault('dataset',{});aliases=state.setdefault('aliases',{});seen=state.setdefault('seen_inputs',{});proofs=state.setdefault('conversions',{})
 if not dataset and not any(history.rglob('*.csv')):
  # A new phone installation or model still sees this inverter's PC archive.
  alternatives=[]
  for path in (scope/'models').glob('*/state.json'):
   prior=read_json(path,{})
   if path!=state_path and prior.get('dataset'):alternatives.append((path,prior))
  if alternatives:
   _,prior=max(alternatives,key=lambda x:x[0].stat().st_mtime_ns)
   for key,row in prior['dataset'].items():
    copied=dict(row);output=history/row['member']
    store.materialize(row['csv'],output);store.materialize(row['schema'],schema_path(output));copied['work_path']=str(output);dataset[key]=copied
   aliases.update(prior.get('aliases',{}));seen.update(prior.get('seen_inputs',{}));proofs.update(prior.get('conversions',{}))
  else:
   legacy=[]
   for path in (root/'Data/AndroidSupport/Migrations').glob('*/result.json'):
    old=read_json(path.with_name('plan.json'),{})
    if scope_matches(old) and read_json(path,{}).get('state')=='ready':legacy.append(path)
   if legacy:
    source=max(legacy,key=lambda p:p.stat().st_mtime_ns).parent/'work/Data/CompactHistory'/plan['device_id']
    for path in source.rglob('*.csv'):
     if not schema_path(path).exists():continue
     member=path.relative_to(source);output=history/member
     store.materialize(store.snapshot(path,immutable=True),output);store.materialize(store.snapshot(schema_path(path),immutable=True),schema_path(output))
 if not dataset:
  for path in sorted(history.rglob('*.csv')):
   check();relative=path.relative_to(history);origin=relative.parts[0]
   if origin not in ('Local','SmartESS') or not schema_path(path).exists():continue
   key=hashed(['legacy',relative.as_posix()]);csv=store.snapshot(path,immutable=True);schema=store.snapshot(schema_path(path),immutable=True)
   dataset[key]=dict(id=key,source=origin,day=path.stem,member=relative.as_posix(),work_path=str(path),csv=csv,schema=schema)
  for p in history.rglob('*.verified.json'):
   saved=read_json(p,{})
   csv=p.with_name(p.name.removesuffix('.verified.json')+'.csv')
   match=next((k for k,v in dataset.items() if v['work_path']==str(csv)),None)
   if match:proofs[saved.get('original','')]=match
 # Import verified raw->compact identities from earlier finished preparations.
 for old_plan_path in (root/'Data/AndroidSupport/Migrations').glob('*/plan.json'):
  old_plan=read_json(old_plan_path,{})
  if not scope_matches(old_plan):continue
  for proof_path in (old_plan_path.parent/'work/Data/CompactHistory'/plan['device_id']).rglob('*.verified.json'):
   proof=read_json(proof_path,{})
   match=next((k for k,v in dataset.items() if v['csv']['sha256']==proof.get('csv') and v['schema']['sha256']==proof.get('schema')),None)
   if match:proofs[proof['original']]=match
 from ducksolar.sync_reconcile import reconcile,semantic,schema_equal,extends
 repaired=reconcile(dataset,aliases,work,store,cancelled,persist=lambda:atomic(state_path,state),conversions=proofs)
 stats.update(duplicates_merged=repaired['merged'],prefixes_promoted=repaired['prefixes_promoted'])
 affected=set();live={};receipts=[]
 def receive(row,channel):
  check();input_key=channel+':'+row['stream'];signature=hashed([row['csv']['sha256'],(row.get('schema') or {}).get('sha256')]);old_alias=aliases.get(input_key)
  receipts.append(dict(stream=row['stream'],csv=row['csv']['sha256'],schema=(row.get('schema') or {}).get('sha256'),channel=channel))
  if seen.get(input_key)==signature and old_alias in dataset:
   stats['inputs_unchanged']+=1
   if channel=='phone' and row.get('live'):live[old_alias]=row['stream']
   return
  # Verify descriptor's full hash before treating uploaded blocks as an archive.
  input_path=scope/'inputs'/(row['csv']['sha256']+'.csv');store.materialize(row['csv'],input_path,cancelled=cancelled);store.snapshot(input_path,immutable=True,cancelled=cancelled)
  meta=None
  if row.get('schema'):
   meta=scope/'inputs'/(row['schema']['sha256']+'.json');store.materialize(row['schema'],meta,cancelled=cancelled);store.snapshot(meta,immutable=True)
  if row.get('backup_only'):seen[input_key]=signature;return
  existing=next((k for k,v in dataset.items() if v['source']==row['source'] and v['day']==row['day'] and v['csv']['sha256']==row['csv']['sha256'] and (v['schema']['sha256']==(row.get('schema') or {}).get('sha256') or meta is not None and schema_equal(schema_path(v['work_path']),meta))),None)
  if existing is None and meta is None:existing=proofs.get(row['csv']['sha256'])
  if existing in dataset:
   aliases[input_key]=existing;seen[input_key]=signature;stats['inputs_unchanged']+=1
   if channel=='phone' and row.get('live'):live[existing]=row['stream']
   return
  if meta is not None:
   incoming=dict(source=row['source'],day=row['day'],csv=row['csv'],schema=row['schema'],work_path=str(input_path))
   # Incoming sidecars are archived under SHA names, so use the verified
   # semantic contract through a temporary descriptor path wrapper below.
   from ducksolar.sync_reconcile import schema_extends
   def relation(short,long,short_meta,long_meta):
    if short['source']!=long['source'] or short['day']!=long['day'] or short['csv']['bytes']>long['csv']['bytes']:return False
    if not schema_extends(short_meta,long_meta):return False
    from ducksolar.prepared_history import digest
    remaining=short['csv']['bytes'];sha=hashlib.sha256()
    with Path(long['work_path']).open('rb') as f:
     while remaining:
      check();chunk=f.read(min(256*1024,remaining))
      if not chunk:return False
      sha.update(chunk);remaining-=len(chunk)
    return sha.hexdigest()==short['csv']['sha256']
   candidates=[]
   for candidate,prior in dataset.items():
    if relation(prior,incoming,schema_path(prior['work_path']),meta):candidates.append(candidate)
    elif relation(incoming,prior,meta,schema_path(prior['work_path'])):
     aliases[input_key]=candidate;seen[input_key]=signature;stats['inputs_unchanged']+=1
     if channel=='phone' and row.get('live') and incoming['csv']['sha256']==prior['csv']['sha256']:live[candidate]=row['stream']
     return
   if candidates:
    old_alias=max(candidates,key=lambda k:dataset[k]['csv']['bytes'])
    stats['append_sources_reused']=stats.get('append_sources_reused',0)+1
  key=old_alias if old_alias in dataset else hashed([channel,row['stream']]);member=dataset[key]['member'] if key in dataset else row['source']+'/sync-'+key+'/'+row['day']+'.csv';output=history/member
  if meta is not None:
   Codec(input_path,meta_path=meta)
   out_csv=row['csv'];out_schema=row['schema']
   store.materialize(out_csv,output,cancelled=cancelled);store.materialize(out_schema,schema_path(output),cancelled=cancelled)
  else:
   convert(input_path,output,cancelled=cancelled);stats['new_conversions']+=1
   out_csv=store.snapshot(output,immutable=True);out_schema=store.snapshot(schema_path(output),immutable=True)
  old=dataset.get(key)
  dataset[key]=dict(id=key,source=row['source'],day=row['day'],member=member,work_path=str(output),csv=out_csv,schema=out_schema)
  aliases[input_key]=key;seen[input_key]=signature;stats['new_inputs']+=1;affected.add(date.fromisoformat(row['day']))
  if old:affected.add(date.fromisoformat(old['day']))
  if channel=='phone' and row.get('live'):live[key]=row['stream']
 for i,row in enumerate(plan['files']):
  receive(row,'phone')
  if i%16==0:progress('discovering_changes',done=i,total=len(plan['files']))
 # Automatic PC archive binding: config or an unambiguous existing PN binding.
 known_pns=set()
 for p in (root/'Data/AndroidSupport/Migrations').glob('*/plan.json'):
  old=read_json(p,{})
  if old.get('pn'):known_pns.add(old['pn'])
 config=read_json(root/'Server/DS_Server_Alpha_0.3.4/config.json',{})
 bound=config.get('dtu_pn') or (next(iter(known_pns)) if len(known_pns)==1 else None)
 if bound and bound!=plan['pn']:stats['pc_archive_other_inverter']=True
 if bound==plan['pn']:
  for origin,folder in [('Local',root/'Logs/Inverter'),('SmartESS',root/'History')]:
   for path in sorted(folder.rglob('*.csv')):
    if path.is_symlink() or any(p.lower() in ('androidbackups','clean','devices') for p in path.parts):continue
    try:day=date.fromisoformat(path.stem)
    except ValueError:continue
    try:
     csv=store.snapshot(path,copy_blocks=True,cancelled=cancelled);meta=schema_path(path);schema=store.snapshot(meta,copy_blocks=True) if meta.exists() else None
    except ValueError:stats['active_archive_files_deferred']=stats.get('active_archive_files_deferred',0)+1;continue
    row=dict(stream=hashed(['pc',str(path.relative_to(root))]),source=origin,day=day.isoformat(),csv=csv,schema=schema)
    receive(row,'pc');stats['pc_archive_files']+=1
 # Include verified append backups and older Android archives of this PN
 # automatically. An old prepared copy is a recovery source only for missing
 # days; it must not multiply already present day variants.
 from ducksolar.archive_sync import ArchiveExport
 archive_export=ArchiveExport(root);installations={plan['installation']};bindings={}
 for metadata in (root/'Data/AndroidSupport/Migrations').glob('*/plan.json'):
  old=read_json(metadata,{})
  if old.get('installation') and old.get('pn'):bindings.setdefault(old['installation'],set()).add(old['pn'])
 for installation,pns in bindings.items():
  if pns=={plan['pn']}:installations.add(installation)
 for source in sorted(installations):
  for key,(path,origin,name) in archive_export._candidates(source).items():
   check();day=date.fromisoformat(name[:-4])
   if '/prepared/' in key and any(v['source']==origin and v['day']==day.isoformat() for v in dataset.values()):continue
   try:
    csv=store.snapshot(path,copy_blocks=True,cancelled=cancelled);meta=schema_path(path)
    if not meta.exists():
     backup_name=path.parents[1].name if path.name=='current.csv' else path.parent.name
     meta=root/'Data/AndroidSupport/Received'/source/'inverter'/(backup_name+'.schema.json')/'latest.log'
    schema=store.snapshot(meta,copy_blocks=True) if meta.exists() else None
   except ValueError:stats['active_archive_files_deferred']=stats.get('active_archive_files_deferred',0)+1;continue
   row=dict(stream=hashed(['android-backup',source,key]),source=origin,day=day.isoformat(),csv=csv,schema=schema)
   receive(row,'pc');stats['pc_archive_files']+=1
 if state.get('last_day') and state['last_day']!=today.isoformat():affected.add(date.fromisoformat(state['last_day']))
 if not state.get('processed_revision'):
  # The adopted workspace has already computed these files. Probe cache-backed
  # paths once; new workspaces necessarily calculate their initial data once.
  affected.update(date.fromisoformat(v['day']) for v in dataset.values())
 meter_changed=state.get('readings_json')!=plan['readings_json'];reader=HistoryReader(cfg);view=HistoryViews(reader,cfg,plan['device_id'])
 for anchor in sorted(affected):
  progress('updating_changed_days',day=anchor.isoformat())
  if anchor<today:
   prepared=PreparedHistory(reader)
   for origin,paths in zip(('Local','SmartESS'),reader.find_day_files(anchor)):
    for path in paths:prepared.prepare(path,origin,anchor,cancelled)
  day_rows_before=stats['day_new_rows']
  for source in ('Local','SmartESS','Auto'):
   rows,measure=hourly(view,anchor,source,list(columns()),cancelled);export_portable(view,anchor,source,rows)
   stats['day_new_rows']+=measure.get('new_rows',0)
  stats['days_checked']+=1
  if stats['day_new_rows']>day_rows_before:stats['days_recalculated']+=1
 months={(d.year,d.month) for d in affected}
 if meter_changed:months.update((date.fromisoformat(v['day']).year,date.fromisoformat(v['day']).month) for v in dataset.values())
 portable=scope/'models'/model_key/'balances';portable.mkdir(parents=True,exist_ok=True)
 if adopted:
  for p in (adopted/'balances').glob('*'):
   if p.name.endswith('.reuse.json') or not p.is_file():continue
   target=portable/p.name
   if not target.exists():
    try:os.link(p,target)
    except OSError:shutil.copyfile(p,target)
 for year,month in sorted(months):
  anchor=date(year,month,1)
  for source in ('Local','SmartESS','Auto'):
   progress('updating_changed_months',period=f'{year}-{month:02d}',source=source)
   report=MonthAccounting().report(reader,Meters(),cfg,anchor,source=source,device_id=plan['device_id'],cancelled=cancelled)
   new_rows=report.get('diagnostics',{}).get('used_records',0);stats['balance_new_rows']+=new_rows;stats['months_checked']+=1
   if new_rows:stats['months_recalculated']+=1
   if (year,month)<(today.year,today.month):
    stem=f'{year}-{month:02d}-{source}';summary_path=work/'Data/EnergyAudit'/plan['device_id']/(stem+'.summary.json');summary=read_json(summary_path)
    # An unchanged completed month retains its exact pre-existing portable audit.
    if report.get('cache_hit') and (portable/(stem+'.json')).exists():continue
    from ducksolar.deferred_audit import materialize
    audit=summary_path.with_name(stem+'.audit.jsonl');materialize(summary,audit,cancelled)
    start=datetime(year,month,1,tzinfo=ZONE);end=(start.replace(day=28)+timedelta(days=4)).replace(day=1);signature=summary['checkpoint']['signature'];signature['model']=reader.model_signature();signature['readings']=Meters().list_meter_readings()
    files=_files(reader,start,end,source,cancelled)
    atomic(portable/(stem+'.json'),dict(revision=revision(reader,files,signature,cancelled),report=report,audit_bytes=summary['audit_bytes']))
    with audit.open('rb') as inp,gzip.open(portable/(stem+'.audit.jsonl.gz'),'wb',compresslevel=1) as out:
     while block:=inp.read(1024*1024):check();out.write(block)
 # Period graph caches are invalidated by their own day revisions, not by job ids.
 for year,month in sorted({(d.year,d.month) for d in affected if d<today}):
  for source in ('Local','SmartESS','Auto'):view.month_series(date(year,month,1),source,cancelled)
 for year in sorted({d.year for d in affected if d<today}):
  for source in ('Local','SmartESS','Auto'):view.graph_data('year',date(year,1,1),source,cancelled=cancelled)
 progress('publishing_changes')
 artifacts=[];fp_cache=state.setdefault('artifact_fingerprints',{})
 def artifact(role,path,name=None):
  check();key=role+':'+(name or path.name);fp=fingerprint(path);wal=Path(str(path)+'-wal')
  if path.suffix=='.db' and wal.exists():fp+=fingerprint(wal)
  old=fp_cache.get(key)
  if old and old['fingerprint']==fp:desc=old['snapshot'];stats['artifacts_reused']+=1
  elif path.suffix=='.db':
   temp=scope/('snapshot-'+uuid4().hex+'.db');src=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(temp)
   try:src.backup(dst);dst.execute('PRAGMA journal_mode=DELETE')
   finally:dst.close();src.close()
   desc=store.snapshot(temp,immutable=True,cancelled=cancelled);temp.unlink();stats['sqlite_backups']+=1
  else:desc=store.snapshot(path,immutable=True,cancelled=cancelled)
  fp=fingerprint(path)
  if path.suffix=='.db' and wal.exists():fp+=fingerprint(wal)
  fp_cache[key]=dict(fingerprint=fp,snapshot=desc)
  entry=dict(role=role,name=name or path.name,snapshot=desc)
  if 'compressed-artifacts-v1' in plan.get('capabilities',[]) and role in ('index','segment'):
   packed=scope/'compressed'/(desc['sha256']+'.gz');packed.parent.mkdir(parents=True,exist_ok=True)
   if not packed.exists():
    raw=store.existing(desc) or path;tmp=packed.with_suffix('.tmp')
    try:
     with raw.open('rb') as inp,tmp.open('wb') as out,gzip.GzipFile(filename='',mode='wb',fileobj=out,compresslevel=1,mtime=0) as gz:
      while block:=inp.read(1024*1024):check();gz.write(block)
     tmp.replace(packed)
    finally:tmp.unlink(missing_ok=True)
   entry.update(encoding='gzip',content_snapshot=desc,snapshot=store.snapshot(packed,immutable=True,cancelled=cancelled))
  artifacts.append(entry)
  if len(artifacts)%16==0:progress('publishing_changes',done=len(artifacts),object_role=role)
 for path in (work/'Data/PreparedHistory/objects').glob('*.jsonl.gz'):artifact('prepared',path)
 for pattern in ('period-*.json','hourly-index-*.json','month-energy-*.json','day-energy-index-*.json'):
  for path in view.view_path.glob(pattern):artifact('view',path)
 for path in (work/'Data/EnergyWork/PreparedInputs-v3').glob('*.db'):artifact('index',path)
 for path in portable.glob('*'):
  if path.is_file() and not path.name.endswith('.reuse.json'):artifact('balance',path)
 # Only unfinished-month checkpoints need segments; completed portable objects
 # already on the phone remain byte-identical, avoiding raw audit retransfers.
 current=f'{today.year}-{today.month:02d}'
 exported_parts=set()
 for path in (work/'Data/EnergyAudit'/plan['device_id']).glob(current+'-*.summary.json'):
  value=read_json(path,{})
  if not value.get('deferred_audit'):continue
  artifact('checkpoint',path)
  for part in value['input_parts']:
   if part['path'] not in exported_parts:
    exported_parts.add(part['path']);artifact('segment',Path(part['path']),hashed(part['path'])+'.jsonl')
 files=[]
 for key,row in dataset.items():
  files.append(dict(row,external_stream=live.get(key)))
 revision_hash=hashed([[(k,v['csv']['sha256'],v['schema']['sha256']) for k,v in sorted(dataset.items())],plan['model'],plan['readings_json']])
 manifest=dict(contract=CONTRACT,id=args.session,installation=plan['installation'],device_id=plan['device_id'],pn=plan['pn'],model=plan['model'],model_types=plan['model_types'],readings_json=plan['readings_json'],history=files,artifacts=artifacts,receipts=receipts,stats=stats,workspace=str(work),data_revision=revision_hash)
 # Byte-identical objects remain references. Only this small manifest is new.
 path=session/'manifest.json';prior_manifest=read_json(path,{})
 state.update(processed_revision=revision_hash,readings_json=plan['readings_json'],last_day=today.isoformat());atomic(state_path,state);store.save()
 progress('deduplicating_archives')
 from ducksolar.sync_reconcile import deduplicate_archives
 cleanup=deduplicate_archives(root,store,cancelled,plan['pn']);stats['archive_cleanup']=cleanup
 # Manifest describes final counters too, without changing data revisions.
 manifest['stats']=stats
 comparable=lambda value:{k:v for k,v in value.items() if k!='stats'}
 if comparable(prior_manifest)==comparable(manifest):manifest=prior_manifest
 atomic(path,manifest);desc=store.snapshot(path,immutable=True);store.save()
 atomic(session/'state.json',dict(state='ready',id=args.session,manifest=desc,stats=stats,data_revision=revision_hash))
 print(json.dumps(dict(state='ready',stats=stats)),flush=True)
with preparation_lock(scope):
 try:run()
 except BaseException as error:
  store.save();atomic(state_path,state);atomic(session/'state.json',dict(state='cancelled' if cancelled() else 'error',id=args.session,error=str(error),stats=stats));raise
