"""PC-only worker for a1.0.7. Read immutable originals, verify compact copies."""
import argparse,json,sys,os,shutil,zipfile
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--job',required=True)
args=parser.parse_args();root=args.root.resolve()
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.compact_history import convert,schema_path
from ducksolar.prepared_history import write_json,digest as raw_digest,export_package

def cancelled():return (folder/'cancel.request').exists()

def digest(path,cancel=None):return raw_digest(path,cancel or cancelled)

def write_progress(path,value):
 if cancelled():raise InterruptedError('Міграцію зупинено')
 if 'reuse' in globals():value=dict(value,**reuse.stats)
 try:write_json(path,value)
 except PermissionError as exc:print('Progress update delayed: '+str(exc),flush=True)

from ducksolar.history_migration import CONTRACT
from ducksolar.energy_streaming import MonthAccounting,_files
from ducksolar.balance_portable import revision
from ducksolar.wire import decode
from datetime import date,datetime,timedelta
import gzip
import re
if not re.fullmatch('[0-9a-f]{32}',args.job):raise ValueError('Invalid job ID')
folder=root/'Data/AndroidSupport/Migrations'/args.job
from preparation_lock import preparation_lock
import atexit
lock=preparation_lock(folder);lock.__enter__()
atexit.register(lambda:lock.__exit__(None,None,None))
plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
work=folder/'work';history=work/'Data/CompactHistory'/plan['device_id']
history.mkdir(parents=True,exist_ok=True)
cfg=AppConfig(root_dir=str(work),history_device_id=plan['device_id'])
from ducksolar.preparation_model import apply_model
apply_model(cfg,plan['model'],plan['model_types'])
cfg.primary_device_id=plan['device_id']
from migration_reuse import Reuse
reuse=Reuse(folder,plan,cfg,cancelled)
total=len(plan['files']);before=0;after=0;rows=0
converted=set()
for index,item in enumerate(plan['files']):
 source=folder/'originals'/item['name']
 meta=None
 if source.stat().st_size!=item['bytes'] or digest(source)!=item['sha256']:raise ValueError('Original archive verification failed')
 if 'schema' in item:
  meta=folder/'originals'/item['schema']['name']
  if meta.stat().st_size!=item['schema']['bytes'] or digest(meta)!=item['schema']['sha256']:raise ValueError('Original schema verification failed')
 identity=(item['source'],item['day'],item['sha256'],item.get('schema',{}).get('sha256'))
 before+=item['bytes']
 if item.get('backup_only'):continue
 if identity in converted:continue
 converted.add(identity)
 destination=history/item['source']/f'{index:06d}'/(item['day']+'.csv')
 checkpoint=destination.with_suffix('.verified.json')
 if destination.exists() and checkpoint.exists():
  saved=json.loads(checkpoint.read_text())
  valid=saved.get('original')==item['sha256'] and saved.get('csv')==digest(destination) and saved.get('schema')==digest(schema_path(destination))
 else:valid=False
 if not valid:
  result=reuse.conversion(item,destination)
  if result is None:
   result=convert(source,destination,cancelled=cancelled,source_schema=meta);reuse.stats['conversions_new']+=1
  write_json(checkpoint,dict(original=item['sha256'],csv=digest(destination),schema=digest(schema_path(destination)),result=result))
 else:result=saved['result']
 after+=result['bytes'];rows+=result['rows']
 try:
  write_progress(folder/'progress.json',dict(stage='compact_conversion',done=index+1,total=total,original_bytes=before,compact_bytes=after,rows=rows))
 except PermissionError as exc:
  print('Progress update delayed: '+str(exc),flush=True)
write_progress(folder/'progress.json',dict(stage='indices_and_periods',done=total,total=total,original_bytes=before,compact_bytes=after,rows=rows))
write_progress(folder/'progress.json',dict(stage='reuse_existing_caches',done=0,total=1))
reuse.seed_objects(work)
reuse.seed_hourly(HistoryReader(cfg))
prepared=folder/'prepared.zip'
result=export_package(HistoryReader(cfg),prepared,cancelled=cancelled,progress=lambda done,count:write_progress(folder/'progress.json',dict(stage='indices_and_periods',done=done,total=count,original_bytes=before,compact_bytes=after,rows=rows)))
reader=HistoryReader(cfg);balances=folder/'balances';balances.mkdir(exist_ok=True)
class MeterSnapshot:
 def list_meter_readings(self,**kwargs):return decode(json.loads(plan['readings_json']))
months=sorted({(day.year,day.month) for day in reader.available_dates() if (day.year,day.month)<(date.today().year,date.today().month)})
for year,month in months:
 for source in ('Local','SmartESS','Auto'):
  write_progress(folder/'progress.json',dict(stage='monthly_balance',period=f'{year}-{month:02d}',source=source,done=0,total=len(months)*3))
  if reuse.month(reader,MeterSnapshot(),date(year,month,1),source,balances):continue
  report=MonthAccounting().report(reader,MeterSnapshot(),cfg,date(year,month,1),source=source,device_id=plan['device_id'],cancelled=cancelled)
  stem=f'{year}-{month:02d}-{source}';audit_folder=work/'Data/EnergyAudit'/plan['device_id']
  cached=json.loads((audit_folder/(stem+'.summary.json')).read_text(encoding='utf-8'))
  if cached.get('deferred_audit'):
   from ducksolar.deferred_audit import materialize
   materialize(cached,audit_folder/(stem+'.audit.jsonl'),cancelled)
  signature=cached['checkpoint']['signature']
  signature['model']=reader.model_signature();signature['readings']=MeterSnapshot().list_meter_readings()
  from ducksolar.energy_accounting import ZONE
  start=datetime(year,month,1,tzinfo=ZONE);end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
  files=_files(reader,start,end,source,cancelled)
  write_json(balances/(stem+'.json'),dict(revision=revision(reader,files,signature,cancelled),report=report,audit_bytes=cached['audit_bytes']))
  with (audit_folder/(stem+'.audit.jsonl')).open('rb') as inp,gzip.open(balances/(stem+'.audit.jsonl.gz'),'wb',compresslevel=1) as out:shutil.copyfileobj(inp,out,1024*1024)
  reuse.record_month(balances,stem)
# Seed the unfinished month as a verified checkpoint, never as a final total.
from ducksolar.balance_seed import export as export_seed
seed_members=[]
today=date.today()
if any(day.year==today.year and day.month==today.month for day in reader.available_dates()):
 for source in ('Local','SmartESS','Auto'):
  write_progress(folder/'progress.json',dict(stage='open_month_checkpoint',source=source,done=0,total=3))
  stem=f'{today.year}-{today.month:02d}-{source}'
  reuse.seed_open_month(reader,stem)
  MonthAccounting().report(reader,MeterSnapshot(),cfg,today.replace(day=1),source=source,device_id=plan['device_id'],cancelled=cancelled)
  seed_members.extend(export_seed(work/'Data/EnergyAudit'/plan['device_id']/(stem+'.summary.json'),history,folder/'seeds',stem))
members=[]
for path in sorted(history.rglob('*')):
 if path.is_file() and (path.name.endswith('.csv') or path.name.endswith('.csv.schema.json')):
  members.append((path,'history/'+path.relative_to(history).as_posix()))
members.append((prepared,'prepared.zip'))
for path in balances.iterdir():
 if not path.name.endswith('.reuse.json'):members.append((path,'balances/'+path.name))
from ducksolar.projection_contract import export as export_indices,CONTRACT as INDEX_CONTRACT
members.extend(export_indices(work,folder/'indices',cancelled))
members.extend(seed_members)
manifest={k:plan[k] for k in ('contract','id','installation','device_id','pn','model','model_types','readings_json')}
manifest.update(projection_contract=INDEX_CONTRACT,originals=plan['files'],prepared_sha256=result['sha256'],files=[dict(name=name,bytes=path.stat().st_size,sha256=digest(path)) for path,name in members])
temporary=folder/'history.zip.tmp';target=folder/'history.zip'
with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
 z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
 for path,name in members:
  reuse.check();z.write(path,name)
os.replace(temporary,target)
write_json(folder/'result.json',dict(state='ready',id=args.job,contract=CONTRACT,projection_contract=INDEX_CONTRACT,reuse=reuse.stats,sha256=digest(target),bytes=target.stat().st_size,original_bytes=before,compact_bytes=after,rows=rows))
print(json.dumps(dict(state='ready',files=total,bytes=target.stat().st_size)),flush=True)
