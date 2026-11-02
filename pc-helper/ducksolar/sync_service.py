"""LAN synchronization transport. Immutable blocks and durable scoped sessions."""
import json,re,threading,subprocess,sys,time
from pathlib import Path
from .sync_store import Store,atomic,hashed,checked,HEX,CONTRACT,BLOCK
from .preparation_model import decode_model
from .preparation_lock import running
from .worker_launch import launch_worker,WorkerLaunchError
from .tool_paths import worker_python,history_tool

def cached_store(method):
 def call(self,*args,**kwargs):
  from .sync_store import session_store
  with self.lock:
   plan=args[0] if method.__name__=='start' else self.plan(args[0])
   with session_store(self.scope(plan)/'store') as store:
    self._active_store=store
    try:return method(self,*args,**kwargs)
    finally:self._active_store=None
 return call

class SyncService:
 def __init__(self,root,worker_python=None):
  self.worker_python=Path(worker_python) if worker_python else None
  self.root=Path(root);self.base=self.root/'Data/HistorySync';self.sessions=self.base/'sessions';self.sessions.mkdir(parents=True,exist_ok=True)
  self.lock=threading.RLock();self.processes={};self.streams={}
 def session(self,ident):
  if not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('Invalid sync session')
  return self.sessions/ident
 def plan(self,ident):return json.loads((self.session(ident)/'plan.json').read_text('utf-8'))
 def scope(self,plan):return self.base/'scopes'/hashed([plan['device_id'],plan['pn']])
 def store(self,plan):return self._active_store if getattr(self,'_active_store',None) is not None else Store(self.scope(plan)/'store')
 def descriptors(self,plan):
  for row in plan['files']:
   yield row['csv']
   if row.get('schema'):yield row['schema']
 def bootstrap(self,plan,store):
  needed={d['sha256']:d for d in self.descriptors(plan) if store.existing(d) is None}
  if not needed:return
  for source in (self.root/'Data/AndroidSupport/Migrations').glob('*/plan.json'):
   try:old=json.loads(source.read_text('utf-8'))
   except (OSError,ValueError):continue
   if any(old.get(k)!=plan[k] for k in ('device_id','pn')):continue
   for row in old['files']:
    for entry in (row,row.get('schema')):
     if not entry or entry['sha256'] not in needed:continue
     path=source.parent/'originals'/entry['name']
     if path.is_file() and path.stat().st_size==needed[entry['sha256']]['bytes']:
      desc=store.snapshot(path,immutable=True)
      if desc['sha256']==entry['sha256']:needed.pop(entry['sha256'],None)
   history=source.parent/'work/Data/CompactHistory'/plan['device_id']
   for proof in history.rglob('*.verified.json'):
    try:
     value=json.loads(proof.read_text('utf-8'));csv=proof.with_name(proof.name.removesuffix('.verified.json')+'.csv')
     for key,path in [('csv',csv),('schema',Path(str(csv)+'.schema.json'))]:
      sha=value[key]
      if sha in needed and path.is_file() and path.stat().st_size==needed[sha]['bytes']:
       desc=store.snapshot(path,immutable=True)
       if desc['sha256']==sha:needed.pop(sha,None)
    except (OSError,ValueError,KeyError):continue
  store.save()
 @cached_store
 def start(self,request):
  if request.get('contract')!=CONTRACT:raise ValueError('Unsupported history sync protocol')
  typed_model=decode_model(request['model'],request['model_types'])
  if not re.fullmatch('[0-9a-f]{32}',request['installation']) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',request['device_id']) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',request['pn']):raise ValueError('Invalid sync scope')
  if not isinstance(json.loads(request['readings_json']),list):raise ValueError('Invalid meter snapshot')
  plan={k:request[k] for k in ('contract','installation','device_id','pn','model','model_types','readings_json')};plan['model']=typed_model;plan['files']=[]
  if len(request['files'])>50000:raise ValueError('Too many history streams')
  for row in request['files']:
   from datetime import date
   date.fromisoformat(row['day'])
   if row['source'] not in ('Local','SmartESS') or not HEX.fullmatch(row['stream']):raise ValueError('Invalid history stream')
   clean={k:row[k] for k in ('stream','day','source','csv')};checked(clean['csv'])
   clean.update(live=bool(row.get('live')),backup_only=bool(row.get('backup_only')))
   if row.get('schema'):clean['schema']=checked(row['schema'])
   plan['files'].append(clean)
  if request.get('capabilities') is not None:
   if request['capabilities']!=['compressed-artifacts-v1']:raise ValueError('Unsupported sync capabilities')
   plan['capabilities']=request['capabilities']
  plan['id']=hashed(plan)[:32]
  if request.get('id') and request['id']!=plan['id']:raise ValueError('Ідентифікатор плану не відповідає типізованим параметрам; сеанс не створено')
  folder=self.session(plan['id'])
  with self.lock:
   scope=self.scope(plan);scope.mkdir(parents=True,exist_ok=True)
   active=scope/'active.json'
   if active.exists():
    other=json.loads(active.read_text('utf-8'))['id']
    # A newer snapshot may queue after a recovered prior worker; no workspace is copied.
    if other!=plan['id'] and running(scope):pass
   folder.mkdir(exist_ok=True);atomic(folder/'plan.json',plan);(folder/'cancel.request').unlink(missing_ok=True)
   store=self.store(plan);self.bootstrap(plan,store)
   atomic(folder/'state.json',dict(state='receiving',id=plan['id']))
  return self.status(plan['id'])
 @cached_store
 def need(self,ident,cursor=0):
  plan=self.plan(ident);store=self.store(plan);blocks={b['sha256']:b for d in self.descriptors(plan) for b in d['blocks']}
  for desc in self.descriptors(plan):store.existing(desc)
  missing=[b for b in blocks.values() if not store.has(b)];store.save()
  if not 0<=cursor<=len(missing):raise ValueError('Invalid missing block cursor')
  return dict(items=missing[cursor:cursor+32],missing=len(missing),next_cursor=cursor+32 if cursor+32<len(missing) else None)
 @cached_store
 def upload(self,ident,sha,data):
  folder=self.session(ident)
  if (folder/'cancel.request').exists():raise ValueError('Синхронізацію зупинено')
  plan=self.plan(ident)
  if sha not in {b['sha256'] for d in self.descriptors(plan) for b in d['blocks']}:raise ValueError('Block not in sync plan')
  with self.lock:store=self.store(plan);store.put(sha,data);store.save()
  return dict(state='stored',sha256=sha)
 def prepare(self,ident):
  with self.lock:
   folder=self.session(ident);plan=self.plan(ident);scope=self.scope(plan)
   if (folder/'cancel.request').exists():raise ValueError('Синхронізацію зупинено')
   process=self.processes.get(ident)
   if process and process.poll() is None:return self.status(ident)
   owner_path=scope/'active.json'
   active=json.loads(owner_path.read_text('utf-8')) if owner_path.exists() else {}
   owner=self.processes.get(active.get('id'))
   if running(scope) or (owner is not None and owner.poll() is None):
    active=json.loads((scope/'active.json').read_text('utf-8'))
    if active.get('id')!=ident:atomic(folder/'state.json',dict(state='waiting',id=ident,stage='waiting_previous_sync'))
    else:atomic(folder/'state.json',dict(state='preparing',id=ident,stage='resuming_existing_sync'))
    return self.status(ident)
   store=self.store(plan)
   for desc in self.descriptors(plan):
    if any(not store.has(b) for b in desc['blocks']):raise ValueError('Спочатку завершіть передавання відсутніх блоків')
   from .tool_paths import history_tool
   python=self.worker_python or worker_python();script=history_tool('sync_worker.py')
   if not python.is_file() or not script.is_file():raise ValueError('History sync worker is unavailable')
   atomic(scope/'active.json',dict(id=ident));atomic(folder/'state.json',dict(state='preparing',id=ident,stage='checking_changes'))
   previous=self.streams.pop(ident,None)
   if previous:previous.close()
   try:
    process,stream=launch_worker([python,script,'--root',self.root,'--session',ident],folder/'worker.log')
    self.processes[ident]=process;self.streams[ident]=stream
   except WorkerLaunchError as error:
    self.processes.pop(ident,None)
    atomic(folder/'state.json',dict(state='error',stage='launch_failed',id=ident,error=str(error),**error.details))
    active=scope/'active.json'
    if active.exists() and json.loads(active.read_text('utf-8')).get('id')==ident and not running(scope):active.unlink(missing_ok=True)
    raise
  return self.status(ident)
 def status(self,ident):
  folder=self.session(ident);plan=self.plan(ident);scope=self.scope(plan)
  state=json.loads((folder/'state.json').read_text('utf-8'))
  if (folder/'cancel.request').exists():
   active=json.loads((scope/'active.json').read_text('utf-8')) if (scope/'active.json').exists() else {}
   return dict(state='cancelling' if active.get('id')==ident and running(scope) else 'cancelled',id=ident)
  if state['state']=='waiting' and not running(scope):return self.prepare(ident)
  process=self.processes.get(ident)
  if state['state']=='preparing' and ((process and process.poll() is not None) or (not process and not running(scope))):
   # Child can publish ready immediately before exiting; reread before marking error.
   latest=json.loads((folder/'state.json').read_text('utf-8'))
   if latest['state']!='preparing':return latest
   state=dict(state='error',stage='worker_stopped',id=ident,error='Підготовку перервано. Повторіть синхронізацію для продовження.',error_code='history.worker_stopped',exit_code=process.returncode if process else None)
   atomic(folder/'state.json',state)
   stream=self.streams.pop(ident,None)
   if stream:stream.close()
  return state
 def manifest(self,ident):
  state=self.status(ident)
  if state['state']!='ready':raise ValueError('Sync result not ready')
  return state
 @cached_store
 def block(self,ident,sha):
  folder=self.session(ident)
  if (folder/'cancel.request').exists():raise ValueError('Синхронізацію зупинено')
  plan=self.plan(ident);return self.store(plan).read(sha)
 def cancel(self,ident):
  # b1.0.6 hashed JSONObject-normalized ints instead of the declared floats.
  # Find only that exact legacy receiving session; never move/delete its data.
  self.session(ident)
  if not (self.session(ident)/'plan.json').exists():
   matches=[]
   for path in self.sessions.glob('*/plan.json'):
    try:
     old=json.loads(path.read_text('utf-8'));body={k:v for k,v in old.items() if k!='id'}
     body['model']=decode_model(body['model'],body['model_types'])
     if hashed(body)[:32]==ident:matches.append(path.parent.name)
    except (OSError,ValueError,KeyError):continue
   if len(matches)!=1:raise ValueError('Активний сеанс для цього плану не знайдено')
   ident=matches[0]
  self.plan(ident);folder=self.session(ident);atomic(folder/'cancel.request',dict(at=time.time()))
  process=self.processes.get(ident)
  if process and process.poll() is None:
   try:process.wait(timeout=2)
   except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
  return self.status(ident)
