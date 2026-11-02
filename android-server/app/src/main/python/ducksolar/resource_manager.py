"""Use available memory on demand; release heavy-operation state on every exit."""
import ctypes,gc,os,threading,time
from contextlib import contextmanager
STATE={};_state_lock=threading.Lock();_heavy=threading.RLock();_local=threading.local()
def update(available,threshold,total,low=False):
 with _state_lock:STATE.update(available=int(available),threshold=int(threshold),total=int(total),low=bool(low),at=time.monotonic())
def budget():
 with _state_lock:state=dict(STATE)
 if time.monotonic()-state.get('at',0)>20:
  try:
   with open('/proc/meminfo') as stream:
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in stream if ':' in line and len(line.split())>=2}
   state.update(available=mem.get('MemAvailable',mem.get('MemFree',0)),total=mem.get('MemTotal',0))
  except (OSError,ValueError):pass
 # OS reserve grows with the actual device; no fixed application RAM ceiling.
 total=state.get('total',512*1024*1024);available=state.get('available',total//2)
 reserve=max(state.get('threshold',0),total//20)
 return max(1024*1024,available-reserve) if not state.get('low') else 1024*1024
def sqlite_kib():
 from .concurrency import active_count
 return max(256,(budget()//2)//max(2,getattr(_local,'connections',2)*max(1,active_count()))//1024)
def configure(con,initial=True):
 con.execute('PRAGMA cache_size=-'+str(sqlite_kib()))
 # SQLite may use spare RAM for temporary work, spilling to file when needed.
 if initial:con.execute('PRAGMA temp_store=FILE')
 with _state_lock:low=STATE.get('low',False)
 if low:con.execute('PRAGMA shrink_memory')
def rss():
 try:return int(open('/proc/self/statm').read().split()[1])*os.sysconf('SC_PAGE_SIZE')
 except (OSError,ValueError,IndexError):return None
def release(runtime=None,views=None):
 if runtime:
  for device in runtime.devices.values():
   device.history._append_cache.clear()
 if views:
  for view in views.values():
   view.daily_memory.clear();view.graph_memory.clear();view.period_memory.clear()
 from .concurrency import active_count
 if active_count()>1:return
 gc.collect()
 try:
  trim=getattr(ctypes.CDLL(None),'malloc_trim',None)
  if trim:trim(0)
 except (OSError,AttributeError,TypeError):pass
def pressure(runtime,views):
 from .concurrency import active_count
 if active_count():return
 if _heavy.acquire(blocking=False):
  try:release(runtime,views)
  finally:_heavy.release()
@contextmanager
def operation(runtime,views,name,logs=None,keep_cache=False):
 before=rss();started=time.monotonic()
 try:yield
 finally:
  release(runtime,None if keep_cache else views)
  journal=logs or (runtime.logs if runtime else None)
  if journal:journal.event('Heavy operation resources released',code='resources.operation.released',operation=name,budget_bytes=budget(),rss_before=before,rss_after=rss(),elapsed_s=round(time.monotonic()-started,3))
@contextmanager
def connections(count):
 previous=getattr(_local,'connections',2);_local.connections=max(2,count)
 try:yield
 finally:_local.connections=previous
