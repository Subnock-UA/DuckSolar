"""Parallel independent day projections; one coordinator owns summary JSON."""
import hashlib,json,copy,threading
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import datetime,timedelta
from pathlib import Path
from .energy_accounting import stamp,ZONE
from .solar_time import active_windows
from .prepared_history import write_json
from .history_reader import HistoryReader
from .concurrency import CPU_WORKERS,heavy_slot,keyed_lock,path_key,active_count

def _number(v):
 import math
 return type(v) in (int,float) and math.isfinite(v) and v>=0

def _legacy_day(reader,day,latitude,longitude,cancelled,source='Auto',until=None):
 windows=active_windows(day,latitude,longitude);active=sum(b-a for a,b in windows)
 start=datetime.combine(day,datetime.min.time(),ZONE).timestamp();end=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE).timestamp()
 seven=datetime.combine(day,datetime.min.time(),ZONE).replace(hour=7).timestamp();late=datetime.combine(day,datetime.min.time(),ZONE).replace(hour=23).timestamp()
 groups={'day':[(seven,late)],'night':[(start,seven),(late,end)]}
 covered=0.;pv=0.;load={k:0. for k in groups};load_covered={k:0. for k in groups};rows=reader.energy_graph_rows(day,source,cancelled)
 from .cpu_energy import forecast as cpu_forecast
 calculated=cpu_forecast(rows,windows,groups,reader.cfg.max_integration_gap_s,until,cancelled)
 if calculated is not None:pv,covered,load,load_covered=calculated
 else:
  for index,(a,b) in enumerate(zip(rows,rows[1:])):
   if index%256==0 and cancelled():raise InterruptedError('Навчання скасовано')
   ta,tb=stamp(a['timestamp']).timestamp(),stamp(b['timestamp']).timestamp();dt=tb-ta
   if not 0<dt<=reader.cfg.max_integration_gap_s:continue
   stop=min(tb,until) if until is not None else tb
   if stop<=ta:continue
   def integrate(field,x,y):
    left=a[field]+(b[field]-a[field])*(x-ta)/dt;right=a[field]+(b[field]-a[field])*(y-ta)/dt
    return (left+right)*.5*(y-x)/3600000
   if all(_number(x.get('pv_w')) for x in (a,b)):
    pv+=integrate('pv_w',ta,stop);covered+=sum(max(0,min(stop,y)-max(ta,x)) for x,y in windows)
   if all(_number(x.get('output_w')) for x in (a,b)):
    for key,ranges in groups.items():
     for x,y in ranges:
      left,right=max(ta,x),min(stop,y)
      if right>left:load[key]+=integrate('output_w',left,right);load_covered[key]+=right-left
 return dict(day=day.isoformat(),pv_kwh=pv,records=len(rows),solar_coverage_pct=min(100,100*covered/active) if active>0 else 0,solar_active_s=active,solar_covered_s=covered,coverage_pct=0,load_tariff_kwh=load,load_tariff_covered_s=load_covered,load_tariff_duration_s={k:sum(y-x for x,y in ranges) for k,ranges in groups.items()})

def _day(reader,day,latitude,longitude,cancelled,source='Auto',until=None):
 from .history_views import HistoryViews
 previous=getattr(reader,'_forecast_location',None);reader._forecast_location=(latitude,longitude)
 try:
  result=HistoryViews(reader,reader.cfg,reader.cfg.history_device_id or 'inverter-1')._day_energy(None,day,source,cancelled)
  basis=result.get('forecast_basis')
  if basis and (until is None or basis.get('last_ts') is None or basis['last_ts']<=until):return dict(basis)
 finally:
  if previous is None:reader.__dict__.pop('_forecast_location',None)
  else:reader._forecast_location=previous
 return _legacy_day(reader,day,latitude,longitude,cancelled,source,until)

def summaries(reader,latitude,longitude,maximum=180,cancelled=lambda:False,progress=None,priority=0,parallel=True):
 path=Path(reader.cfg.root_dir)/'Data/ForecastSummaries'/((reader.cfg.history_device_id or 'inverter-1')+'.json')
 return _summaries(reader,latitude,longitude,maximum,cancelled,progress,priority,path,parallel)

def _save_day(path,day,value,cancelled):
 # Never hold a file lock while waiting for worker admission: an API request
 # may already own the only heavy slot. Merge only the completed day instead.
 with keyed_lock(path_key('forecast-summaries',path),cancelled):
  try:existing=json.loads(path.read_text('utf-8'))
  except (OSError,ValueError):existing={}
  existing[day]=value;write_json(path,existing)

def portable_revision(reader,day,latitude,longitude,prepared=None):
 from .prepared_history import PreparedHistory
 store=prepared or PreparedHistory(reader);identities=[];seen=set()
 for origin,paths in zip(('Local','SmartESS'),reader.find_day_files(day)):
  for path in paths:
   key=(origin,store.identity(path,origin,day)[0])
   if key not in seen:identities.append(key);seen.add(key)
 return hashlib.sha256(repr((identities,reader.model_signature(),latitude,longitude,'solar-v3-portable')).encode()).hexdigest()

def _summaries(reader,latitude,longitude,maximum,cancelled,progress,priority,path,parallel):
 try:cached=json.loads(path.read_text('utf-8'))
 except (OSError,ValueError):cached={}
 cfg=copy.deepcopy(reader.cfg);model=HistoryReader(cfg).model_signature();today=datetime.now(ZONE).date();days=sorted(day for day in reader.available_dates(refresh=True) if day<today)[-maximum:];result={};pending=[]
 for day in days:
  if cancelled():raise InterruptedError('Навчання скасовано')
  files=[p for group in reader.find_day_files(day) for p in group];revision=portable_revision(reader,day,latitude,longitude)
  old=cached.get(day.isoformat())
  if old and old.get('revision')==revision:result[day.isoformat()]=old
  else:pending.append((day,revision))
 if progress:progress(len(result),len(days))
 if not pending:return {day.isoformat():result[day.isoformat()] for day in days}
 failed=threading.Event();local=threading.local()
 def stopped():return failed.is_set() or cancelled()
 def calculate(item):
  day,revision=item
  from .concurrency import wait_interactive
  wait_interactive(stopped)
  with heavy_slot('forecast.day',stopped,max(1,priority)):
   if not hasattr(local,'reader'):local.reader=HistoryReader(cfg)
   return day.isoformat(),dict(model_key=hashlib.sha256(json.dumps(model,sort_keys=True,default=str).encode()).hexdigest(),revision=revision,summary=_day(local.reader,day,latitude,longitude,stopped))
 if not parallel:
  for item in pending:
   day,value=calculate(item);result[day]=value;cached[day]=value;_save_day(path,day,value,stopped)
   if progress:progress(len(result),len(days))
  return {day.isoformat():result[day.isoformat()] for day in days}
 pool=ThreadPoolExecutor(max_workers=min(CPU_WORKERS,len(pending)),thread_name_prefix='ForecastDay')
 tasks={};iterator=iter(pending)
 try:
  for _ in range(min(CPU_WORKERS,len(pending))):
   item=next(iterator);tasks[pool.submit(calculate,item)]=item
  while tasks:
   if cancelled():raise InterruptedError('Навчання скасовано')
   done,_=wait(tasks,timeout=.1,return_when=FIRST_COMPLETED)
   for future in done:
    tasks.pop(future);day,value=future.result();result[day]=value;cached[day]=value
    # Only this coordinator commits: no lost days or concurrent JSON writers.
    _save_day(path,day,value,stopped)
    if progress:progress(len(result),len(days))
    item=next(iterator,None)
    if item is not None:tasks[pool.submit(calculate,item)]=item
 except BaseException:
  failed.set()
  for future in tasks:future.cancel()
  raise
 finally:
  pool.shutdown(wait=True,cancel_futures=True)
  if not active_count():
   from .resource_manager import release
   release()
 return {day.isoformat():result[day.isoformat()] for day in days}
