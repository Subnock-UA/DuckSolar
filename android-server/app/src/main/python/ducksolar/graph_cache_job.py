"""Server-owned durable cache preparation, never owned by an Android Activity."""
import copy,json,threading,time,uuid,hashlib
from datetime import date
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
from .concurrency import CPU_WORKERS,heavy_slot
from .history_reader import HistoryReader
from .history_views import HistoryViews
from .hourly_projection import day,columns,effective_source
from .prepared_history import write_json

ACTIVE=('queued','running','waiting_client','waiting_charging','waiting_resources','paused_server','cancelling')
class ClientYield(Exception):pass

class GraphCacheJob:
 def __init__(self,runtime,charging=lambda:False):
  self.runtime=runtime;self.charging=charging;self.lock=threading.RLock();self.stop_event=threading.Event();self.cancel_event=threading.Event();self.wake=threading.Event()
  self.path=Path(runtime.cfg.root_dir)/'Data/PreparedHistory/graph-cache-job.json';self.last_auto=0.;self.last_save=0.;self.executing=False
  self.index_path=self.path.with_name('graph-cache-index.json')
  try:self.index=json.loads(self.index_path.read_text('utf-8'))
  except (OSError,ValueError):self.index={}
  if not isinstance(self.index,dict):self.index={}
  try:self.state=json.loads(self.path.read_text('utf-8'))
  except (OSError,ValueError):self.state={}
  if not isinstance(self.state,dict):self.state={}
  if self.state.get('state') in ACTIVE:self.state.update(state='queued',resumed=True)
  self.state.setdefault('state','idle');self.thread=threading.Thread(target=self._run,name='GraphCacheCoordinator',daemon=True);self.thread.start()
  if self.state['state']=='queued':self.wake.set()
 def status(self):
  with self.lock:return dict(self.state,charging=bool(self.charging()),worker_limit=CPU_WORKERS)
 def _update(self,force=False,**values):
  with self.lock:
   self.state.update(values,updated_at=time.time())
   if force or time.monotonic()-self.last_save>=1:
    write_json(self.path,self.state);self.last_save=time.monotonic()
 def active(self):
  with self.lock:return self.state.get('state') in ACTIVE
 def manual_active(self):
  with self.lock:return self.state.get('manual',False) and self.state.get('state') in ACTIVE
 def request(self,manual=True):
  with self.lock:
   if self.active() or self.executing:
    if manual:self._update(force=True,manual=True,auto_paused=False)
    return self.status()
   if not manual:
    if self.state.get('auto_paused') or not self.charging() or time.monotonic()-self.last_auto<300:return self.status()
    self.last_auto=time.monotonic()
   self.cancel_event.clear();self.state=dict(state='queued',manual=bool(manual),auto_paused=False,run_id=uuid.uuid4().hex,completed=0,total=0,cache_hits=0,adopted=0,prepared=0,new_rows=0,started_at=time.time(),active_tasks=[])
   self._update(force=True);self.wake.set();return self.status()
 def cancel(self):
  with self.lock:
   self.cancel_event.set();self._update(force=True,state='cancelling' if self.executing else 'cancelled',auto_paused=True,finished_at=time.time());return self.status()
 def _cancelled(self):return self.stop_event.is_set() or self.cancel_event.is_set()
 def _busy(self):
  jobs=getattr(getattr(self.runtime,'api',None),'jobs',None)
  if jobs is None:return False
  with jobs.lock:return any(x.get('state') not in ('completed','error','cancelled') for x in jobs.jobs.values())
 def _allowed(self):
  if self._cancelled():raise InterruptedError('Cache preparation cancelled')
  if getattr(self.runtime,'maintenance_mode',False):raise InterruptedError('Server history migration active')
  with self.lock:manual=self.state.get('manual',False)
  if not manual and not self.charging():raise InterruptedError('Waiting for charger')
 def _fingerprint(self,reader,anchor,source):
  local,smart=reader.find_day_files(anchor)
  # Cheap scheduling hint only. The projection reader still owns SHA/model validation.
  value=[reader._files_signature(local),reader._files_signature(smart),reader.model_signature(),source,anchor<date.today(),'unified-full-v1']
  return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
 def _cache_path(self,reader,ident,anchor,source):
  return reader.paths['data']/'HistoryViews'/ident/f'hourly-index-v1-{anchor.isoformat()}-{source}-telemetry.json'
 def _output_stamp(self,path):
  try:
   stat=path.stat();return [stat.st_size,stat.st_mtime_ns,stat.st_ino]
  except OSError:return None
 def _summary(self):
  value=self.status();value.pop('active_tasks',None)
  value['elapsed_s']=round(time.time()-value.get('started_at',time.time()),3)
  path=self.path.with_name('graph-cache-runs.json')
  try:rows=json.loads(path.read_text('utf-8'))
  except (OSError,ValueError):rows=[]
  if not isinstance(rows,list):rows=[]
  rows=[row for row in rows if row.get('run_id')!=value.get('run_id')]
  write_json(path,(rows+[value])[-64:])
  logs=getattr(self.runtime,'logs',None)
  if logs:logs.event('Graph cache run checkpoint',code='history.cache.run',**value)
 def _work(self):
  self._allowed();tasks=[];snapshots={};planned={};skipped=0;total=0
  manual=self.state.get('manual',False)
  for ident,dev in self.runtime.devices.items():
   reader=HistoryReader(copy.deepcopy(dev.cfg));dates=reader.available_dates(refresh=True);snapshots[ident]=reader
   for anchor in dates:
    local,smart=reader.find_day_files(anchor);sources=[]
    if local:sources.append('Local')
    if smart:sources.append('SmartESS')
    if local or smart:sources.append('Auto')
    for source in sorted({effective_source(s,local,smart) for s in sources}):
     item=(ident,anchor,source);key=f'{ident}:{anchor}:{source}';total+=1
     fingerprint=self._fingerprint(reader,anchor,source);path=self._cache_path(reader,ident,anchor,source)
     stamp=self._output_stamp(path);saved=self.index.get(key,{})
     if not manual and stamp and saved.get('input')==fingerprint and saved.get('output')==stamp:
      skipped+=1;continue
     planned[item]=(key,fingerprint,path);tasks.append(item)
  self._update(force=True,state='running',error='',total=total,completed=skipped,cache_hits=skipped,skipped_unchanged=skipped,scheduled=len(tasks),adopted=0,prepared=0,new_rows=0,active_tasks=[])
  self._summary()
  local=threading.local();failed=threading.Event()
  def resource_stopped():return failed.is_set() or self._cancelled() or (not self.state.get('manual',False) and not self.charging()) or getattr(self.runtime,'maintenance_mode',False)
  def stopped():return resource_stopped() or self._busy()
  def calculate(item):
   self._allowed()
   while self._busy():
    self._update(state='waiting_client');self._allowed();self.stop_event.wait(.2)
   ident,anchor,source=item;tag=f'{ident}:{anchor}:{source}'
   self._update(state='waiting_resources')
   with heavy_slot('graph.cache.day',resource_stopped,priority=1):
    self._allowed()
    if not hasattr(local,'views'):local.views={}
    if ident not in local.views:
     original=snapshots[ident];reader=HistoryReader(copy.deepcopy(original.cfg))
     reader._file_index=copy.deepcopy(original._file_index);reader._dates_cache=list(original._dates_cache or []);reader._dates_cache_at=time.monotonic()
     local.views[ident]=HistoryViews(reader,reader.cfg,ident,None)
    with self.lock:self.state['active_tasks'].append(tag);self._update(state='running')
    try:return day(local.views[ident],anchor,source,list(columns()),stopped)[1]
    except (ValueError,InterruptedError) as error:
     if not self._cancelled() and self._busy():raise ClientYield('Foreground client request') from error
     raise
    finally:
     with self.lock:
      if tag in self.state['active_tasks']:self.state['active_tasks'].remove(tag)
  pool=ThreadPoolExecutor(max_workers=CPU_WORKERS,thread_name_prefix='GraphCacheDay');pending={};iterator=iter(tasks)
  try:
   for _ in range(min(CPU_WORKERS,len(tasks))):
    item=next(iterator);pending[pool.submit(calculate,item)]=item
   while pending:
    self._allowed();done,_=wait(pending,timeout=.2,return_when=FIRST_COMPLETED)
    for future in done:
     item=pending.pop(future)
     try:stats=future.result()
     except ClientYield:
      self._update(state='waiting_client');pending[pool.submit(calculate,item)]=item;continue
     key,fingerprint,path=planned[item]
     ident,anchor,source=item
     stamp=self._output_stamp(path)
     # Never record a newer live tail as covered by an older committed snapshot.
     if stamp and fingerprint==self._fingerprint(snapshots[ident],anchor,source):
      self.index[key]=dict(input=fingerprint,output=stamp)
     with self.lock:
      self._update(completed=self.state['completed']+1,cache_hits=self.state['cache_hits']+int(stats.get('cache_hit',False)),
       adopted=self.state['adopted']+int(stats.get('adopted_legacy',False)),prepared=self.state['prepared']+int(not stats.get('cache_hit',False)),
       new_rows=self.state['new_rows']+stats.get('new_rows',0),last_day=stats['day'])
     item=next(iterator,None)
     if item is not None:pending[pool.submit(calculate,item)]=item
  finally:
   failed.set()
   for future in pending:future.cancel()
   pool.shutdown(wait=True,cancel_futures=True)
   write_json(self.index_path,self.index)
 def _run(self):
  while not self.stop_event.is_set():
   self.wake.wait(1)
   if not self.wake.is_set():continue
   self.wake.clear()
   if self._cancelled():continue
   with self.lock:self.executing=True
   state='completed';error_text=''
   try:
    self._work();self._allowed()
   except Exception as error:
    error_text=str(error)
    if self.stop_event.is_set():state='paused_server'
    elif self.cancel_event.is_set():state='cancelled'
    elif not self.state.get('manual') and not self.charging():state='waiting_charging'
    else:state='error'
   finally:
    # Publish terminal state and release execution atomically: immediate restart
    # must not return an already completed run while its coordinator is exiting.
    with self.lock:
     try:
      self._update(force=True,state=state,error=error_text,active_tasks=[],finished_at=time.time())
      self._summary()
     finally:self.executing=False
   if state=='waiting_charging' and not self.stop_event.wait(1):self.wake.set()
 def stop(self):
  self.stop_event.set();self.wake.set()
  with self.lock:
   if self.state.get('state') in ACTIVE:self._update(force=True,state='paused_server',active_tasks=[])
  if self.thread is not threading.current_thread():self.thread.join(timeout=3)
