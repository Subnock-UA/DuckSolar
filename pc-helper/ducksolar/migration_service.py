from .worker_launch import launch_worker,WorkerLaunchError
from .tool_paths import worker_python,history_tool
"""LAN migration transport; verified originals are immutable PC archives."""
import hashlib,json,re,subprocess,threading,shutil,os,time
from uuid import uuid4
from pathlib import Path
from .pc_support import digest_file,CHUNK
from .preparation_service import KEYS
from .preparation_lock import running

CONTRACT='ducksolar.history-migration.v2'
def replace_retry(source,target):
 deadline=time.monotonic()+20
 while True:
  try:os.replace(source,target);return
  except PermissionError:
   if time.monotonic()>=deadline:raise
   time.sleep(.1)

def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
 try:
  temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');replace_retry(temp,path)
 finally:temp.unlink(missing_ok=True)

class MigrationService:
 def __init__(self,root):
  self.root=Path(root);self.folder=self.root/'Data/AndroidSupport/Migrations';self.lock=threading.RLock();self.processes={};self.streams={};self.plans={};self.results={};self.original_catalogs={}
 def plan(self,ident):
  path=self.job(ident)/'plan.json';stat=path.stat();fingerprint=(stat.st_size,stat.st_mtime_ns)
  cached=self.plans.get(ident)
  if not cached or cached[0]!=fingerprint:
   value=json.loads(path.read_text(encoding='utf-8'))
   entries={entry['name']:entry for row in value['files'] for entry in (row,row.get('schema')) if entry is not None}
   cached=(fingerprint,value,entries);self.plans[ident]=cached
  return cached[1],cached[2]
 def job(self,ident):
  if not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('Invalid migration ID')
  return self.folder/ident
 def start(self,plan):
  if plan.get('contract')!=CONTRACT:raise ValueError('Unsupported migration contract')
  from .preparation_model import decode_model
  decode_model(plan.get('model'),plan.get('model_types'))
  if not isinstance(json.loads(plan.get('readings_json','')),list):raise ValueError('Invalid meter snapshot')
  if not re.fullmatch('[0-9a-f]{32}',plan.get('installation','')) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',plan.get('device_id','')):raise ValueError('Invalid migration device')
  # Never accept phone filesystem paths as PC paths.
  clean={k:plan[k] for k in ('contract','id','installation','device_id','pn','model','model_types','readings_json')};clean['files']=[]
  for row in plan['files']:
   if row.get('source') not in ('Local','SmartESS'):raise ValueError('Invalid source')
   from datetime import date
   date.fromisoformat(row['day'])
   item={k:row[k] for k in ('name','sha256','bytes','source','day')}
   if row.get('backup_only'):item['backup_only']=True
   if 'schema' in row:item['schema']={k:row['schema'][k] for k in ('name','sha256','bytes')}
   for entry in (item,item.get('schema')):
    if entry is None:continue
    if not re.fullmatch('[0-9a-f]{64}',entry['sha256']) or entry['name']!='migration_'+entry['sha256']+('.csv' if entry is item else '.json') or type(entry['bytes']) is not int or entry['bytes']<0:raise ValueError('Invalid migration original')
   clean['files'].append(item)
  folder=self.job(clean['id']);folder.mkdir(parents=True,exist_ok=True)
  with self.lock:
   path=folder/'plan.json'
   if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=clean:raise ValueError('Migration ID already belongs to another plan')
   (folder/'cancel.request').unlink(missing_ok=True)
   atomic(path,clean)
   if all(self.file_status(clean['id'],e['name'])['verified'] for row in clean['files'] for e in (row,row.get('schema')) if e is not None):self.prepare(clean['id'])
   return self.status(clean['id'])
 def entry(self,ident,name):
  plan,entries=self.plan(ident)
  if name not in entries:raise ValueError('Original is not in the migration plan')
  return entries[name]
 def _catalog(self,ident):
  plan,_=self.plan(ident)
  scope=(plan['installation'],plan['device_id'],plan['pn'])
  candidates=[]
  for source in self.folder.glob('*/plan.json'):
   if source.parent.name==ident:continue
   try:
    other=json.loads(source.read_text(encoding='utf-8'))
    if (other.get('installation'),other.get('device_id'),other.get('pn'))==scope:candidates.append(source)
   except (OSError,ValueError):continue
  signature=tuple((str(p),p.stat().st_mtime_ns) for p in candidates)
  saved=self.original_catalogs.get(ident)
  if saved and saved[0]==signature:return saved[1]
  catalog={}
  def add(name,path):
   if path.is_file() and not path.is_symlink():catalog.setdefault(name,[]).append(path)
  for source in candidates:
   other=json.loads(source.read_text(encoding='utf-8'))
   for row in other['files']:
    for entry in (row,row.get('schema')):
     if entry is not None:add(entry['name'],source.parent/'originals'/entry['name'])
   # A new compact plan may refer to an old conversion's OUTPUT, rather than
   # its raw input. Reuse both CSV and schema only after full hash validation.
   for checkpoint in (source.parent/'work/Data/CompactHistory'/plan['device_id']).rglob('*.verified.json'):
    try:
     proof=json.loads(checkpoint.read_text(encoding='utf-8'));csv=checkpoint.with_name(checkpoint.name.removesuffix('.verified.json')+'.csv')
     add('migration_'+proof['csv']+'.csv',csv)
     add('migration_'+proof['schema']+'.json',Path(str(csv)+'.schema.json'))
    except (OSError,ValueError,KeyError):continue
  self.original_catalogs[ident]=(signature,catalog)
  return catalog
 def _reuse_original(self,ident,name,item,path):
  for candidate in self._catalog(ident).get(name,[]):
   if candidate.stat().st_size!=item['bytes'] or digest_file(candidate)!=item['sha256']:continue
   path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.reuse-'+uuid4().hex)
   try:
    shutil.copyfile(candidate,temp)
    if temp.stat().st_size!=item['bytes'] or digest_file(temp)!=item['sha256']:continue
    replace_retry(temp,path)
    atomic(path.with_suffix(path.suffix+'.receipt.json'),dict(bytes=item['bytes'],sha256=item['sha256']))
    return True
   finally:temp.unlink(missing_ok=True)
  return False
 def file_status(self,ident,name):
  with self.lock:return self._file_status(ident,name)
 def _file_status(self,ident,name):
  item=self.entry(ident,name);path=self.job(ident)/'originals'/name
  if not path.exists() or path.stat().st_size!=item['bytes']:
   self._reuse_original(ident,name,item,path)
  if not path.exists():
   plan,_=self.plan(ident)
   candidate=None
   if item['bytes']==0:
    path.parent.mkdir(parents=True,exist_ok=True);path.touch()
   elif name.endswith('.csv'):
    for prefix in ('','History_'):
     trial=self.root/'Logs/Inverter/AndroidBackups'/plan['installation']/(prefix+item['day']+'.csv')/(item['sha256']+'.csv')
     if trial.is_file() and not trial.is_symlink() and trial.stat().st_size==item['bytes'] and digest_file(trial)==item['sha256']:candidate=trial;break
    if candidate:
     import shutil
     path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(candidate,path)
   if path.exists() and digest_file(path)==item['sha256']:
    atomic(path.with_suffix(path.suffix+'.receipt.json'),dict(bytes=item['bytes'],sha256=item['sha256']))
  size=path.stat().st_size if path.exists() else 0
  receipt=path.with_suffix(path.suffix+'.receipt.json');verified=False
  if receipt.exists() and size==item['bytes']:
   try:proof=json.loads(receipt.read_text())
   except (OSError,ValueError):proof={}
   stat=path.stat()
   fingerprint=[stat.st_size,stat.st_mtime_ns,stat.st_ino]
   if proof.get('bytes')==size and proof.get('sha256')==item['sha256']:
    verified=proof.get('fingerprint')==fingerprint or digest_file(path)==item['sha256']
    if verified and proof.get('fingerprint')!=fingerprint:atomic(receipt,dict(proof,fingerprint=fingerprint))
  if path.exists() and size==item['bytes'] and not verified and digest_file(path)==item['sha256']:
   stat=path.stat();atomic(receipt,dict(bytes=size,sha256=item['sha256'],fingerprint=[stat.st_size,stat.st_mtime_ns,stat.st_ino]));verified=True
  if path.exists() and size>=item['bytes'] and not verified:
   # Preserve the damaged copy for diagnosis; request a complete retransmission.
   import time
   path.replace(path.with_name(path.name+'.damaged-'+str(time.time_ns())))
   receipt.unlink(missing_ok=True);size=0
  return dict(bytes=size,verified=verified)
 def upload(self,ident,name,offset,data,sha):
  if not 0<len(data)<=CHUNK or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Invalid original chunk')
  with self.lock:
   if (self.job(ident)/'cancel.request').exists():raise ValueError('Міграцію зупинено')
   item=self.entry(ident,name);path=self.job(ident)/'originals'/name;path.parent.mkdir(parents=True,exist_ok=True)
   state=self.file_status(ident,name)
   if state['verified']:return state
   if offset!=state['bytes'] or offset+len(data)>item['bytes']:raise ValueError('Original upload offset mismatch')
   with path.open('ab') as f:f.write(data);f.flush()
   if path.stat().st_size==item['bytes']:
    if digest_file(path)!=item['sha256']:
     path.unlink();raise ValueError('Original checksum mismatch; restart this file')
    atomic(path.with_suffix(path.suffix+'.receipt.json'),dict(bytes=item['bytes'],sha256=item['sha256']))
   return self.file_status(ident,name)
 def prepare(self,ident):
  process=self.processes.get(ident)
  if process and process.poll() is None:return
  folder=self.job(ident)
  if running(folder):return
  if (folder/'result.json').exists():
   if self.result_valid(ident):return
   (folder/'result.json').unlink()
  python=worker_python();script=history_tool('migrate.py')
  plan,_=self.plan(ident)
  if 'generation_basis' in plan['model']:
   from .tool_paths import history_tool
   script=history_tool('migrate.py')
  if not python.is_file() or not script.is_file():raise ValueError('Configure DS_WORKER_PYTHON and install pc-helper requirements')
  previous=self.streams.pop(ident,None)
  if previous:previous.close()
  error_path=folder/'launch-error.json'
  try:
   process,stream=launch_worker([python,script,'--root',self.root,'--job',ident],folder/'worker.log')
   self.processes[ident]=process;self.streams[ident]=stream
  except WorkerLaunchError as error:
   self.processes.pop(ident,None);atomic(error_path,dict(state='error',id=ident,error=str(error),**error.details));raise
  error_path.unlink(missing_ok=True)
 def cancel(self,ident):
  with self.lock:return self._cancel(ident)
 def _cancel(self,ident):
  folder=self.job(ident)
  self.plan(ident)
  atomic(folder/'cancel.request',dict(requested_at=time.time()))
  process=self.processes.get(ident)
  if process and process.poll() is None:
   try:process.wait(timeout=2)
   except subprocess.TimeoutExpired:
    # This exact child was launched by this service, never an unrelated Python.
    process.terminate();process.wait(timeout=5)
  return self.status(ident)
 def result_valid(self,ident):
  folder=self.job(ident);path=folder/'history.zip';result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
  if result.get('projection_contract')!='ducksolar.scalar-inputs.v3':return False
  if not path.is_file() or path.stat().st_size!=result['bytes']:return False
  stat=path.stat();fingerprint=(stat.st_size,stat.st_mtime_ns,stat.st_ino,result['sha256'])
  if self.results.get(ident)==fingerprint:return True
  if digest_file(path)!=result['sha256']:return False
  self.results[ident]=fingerprint;return True
 def status(self,ident):
  folder=self.job(ident);result=folder/'result.json';progress=folder/'progress.json'
  if (folder/'cancel.request').exists():return dict(state='cancelling' if running(folder) else 'cancelled',id=ident)
  if result.exists():
   if not self.result_valid(ident):return dict(state='error',id=ident,error='Підготовлений пакет пошкоджений; повторіть запуск для відновлення з архіву ПК')
   plan,_=self.plan(ident)
   if not all(self.file_status(ident,e['name'])['verified'] for row in plan['files'] for e in (row,row.get('schema')) if e is not None):
    return dict(state='error',id=ident,error='Архів оригіналів на ПК змінений або неповний; очищення телефона заборонено')
   return json.loads(result.read_text(encoding='utf-8'))
  error_path=folder/'launch-error.json'
  if error_path.exists():return json.loads(error_path.read_text('utf-8'))
  process=self.processes.get(ident)
  alive=(process and process.poll() is None) or running(folder)
  state='preparing' if alive else 'error' if process or progress.exists() else 'waiting_for_originals'
  out=dict(state=state,id=ident)
  if progress.exists():out.update(json.loads(progress.read_text(encoding='utf-8')))
  if not alive and (process is not None or progress.exists()):
   out['state']='error';out['error']='Підготовка перервана; повторіть запуск'
   log=folder/'worker.log'
   if log.exists():
    with log.open('rb') as stream:stream.seek(max(0,log.stat().st_size-4096));out['details']=stream.read().decode('utf-8',errors='replace')
  return out
 def chunk(self,ident,sha,offset,length):
  if (self.job(ident)/'cancel.request').exists():raise ValueError('Міграцію зупинено')
  state=json.loads((self.job(ident)/'result.json').read_text(encoding='utf-8'))
  if state.get('state')!='ready' or state.get('sha256')!=sha or not 0<length<=CHUNK or not 0<=offset<state['bytes']:raise ValueError('Invalid migration download')
  with (self.job(ident)/'history.zip').open('rb') as f:f.seek(offset);return f.read(min(length,state['bytes']-offset))
