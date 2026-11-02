"""Independent forecast scheduler. Manual launch bypasses only power/queue policy."""
import threading,time,json
from pathlib import Path
from datetime import datetime,timedelta,date
from .energy_accounting import ZONE
from . import weather_client as engine
from .prepared_history import write_json
class ServerForecast:
 def __init__(self,runtime):
  self.runtime=runtime;self.root=Path(runtime.cfg.root_dir)/'Server/Forecast';self.next=0;self.lock=threading.RLock();self.cancelled=threading.Event();self.automatic_device=None;self.thread=None
  from .forecast_analytics import ForecastAnalytics
  self.analytics=ForecastAnalytics(runtime,self)
  self.path=self.root/'auto.json'
  try:self.done=json.loads(self.path.read_text('utf-8'))
  except (OSError,ValueError):self.done={}
  engine.configure(lambda code,details=None,**kw:runtime.logs.event(code,code=code,**(details or {})))
 def identity(self,device):return self.runtime.cfg.installation_id+'|'+device
 def _set(self,device,**values):
  with self.lock:
   row=self.done.setdefault(device,{})
   if all(row.get(k)==v for k,v in values.items()):return
   row.update(values,checked_at=time.time());write_json(self.path,self.done)
 def settings(self,device,value=None):
  prior=engine.settings(self.root,self.identity(device));result=engine.settings(self.root,self.identity(device),value)
  if value is not None and result!=prior:
   with self.lock:self.done.pop(device,None);write_json(self.path,self.done);self.next=0
  return result
 def _charging(self):
  maintenance=getattr(self.runtime,'maintenance',None)
  return bool(maintenance and maintenance.charging.is_set())
 def cached_result(self,device):
  try:return engine.engine(self.root,self.identity(device)).cached_forecast() or {}
  except ValueError:return {}
 def status(self,device):
  result=engine.status(self.root,self.identity(device));calibration=result.get('result',{}).get('calibration',{});trained=calibration.get('sample_count',0)>0
  with self.lock:automatic=dict(self.done.get(device,{}))
  if not result.get('settings'):waiting='Налаштуйте місце та параметри панелей'
  elif result.get('state')=='running':waiting='Навчання виконується' if result.get('training') else 'Оновлення погоди'
  elif not self._charging():waiting='Автонавчання очікує підключення сервера до зарядки'
  else:waiting=automatic.get('message','Первинне навчання очікує запуску' if not trained else 'Автоматичне навчання за завершеними добами')
  if 'result' in result:
   result['result']=dict(result['result']);result['result']['forecast_archive']={day:{k:v for k,v in row.items() if k not in ('by_horizon','previous_issued_forecast')} for day,row in result['result'].get('forecast_archive',{}).items()}
  result.update(automatic=automatic,trained=trained,training_note=waiting,quality_policy='Не менше95% сонячного часу; не менше6 валідних діб; спільні перевірки даних')
  return result
 def _signature(self,device):
  from .history_reader import HistoryReader
  reader=HistoryReader(self.runtime.device(device).cfg);today=datetime.now(ZONE).date();days=sorted(d for d in reader.available_dates(refresh=True) if d<today)[-180:]
  files=[p for day in days for group in reader.find_day_files(day) for p in group]
  return repr((reader._files_signature(files),reader.model_signature(),self.settings(device)))
 def start(self,device,train=False,automatic=False,force=False):
  if force and (not train or automatic):raise ValueError('Примусовий режим доступний лише для ручного навчання')
  if self.runtime.maintenance_mode:raise ValueError('Спочатку завершіть міграцію історії')
  from .history_reader import HistoryReader
  from .forecast_summary import summaries
  identity=self.identity(device);signature=self._signature(device) if train else None
  initial=not self.status(device).get('trained')
  def sync(known):
   obj=engine.engine(self.root,identity);location=obj.resolve_location();reader=HistoryReader(self.runtime.device(device).cfg)
   engine.update('history',done=0,total=0)
   values=summaries(reader,location['latitude'],location['longitude'],cancelled=engine._cancel.is_set,progress=lambda done,total:engine.update('history',server_done=done,server_total=total),priority=1 if automatic else 0)
   yesterday=(datetime.now(ZONE).date()-timedelta(days=1)).isoformat();latest=values.get(yesterday,{})
   if automatic and not initial and latest.get('summary',{}).get('solar_coverage_pct',0)<95:raise ValueError('Відкладено: покриття сонячного часу завершеної доби менше95%')
   self._set(device,day=yesterday,revision=latest.get('revision'),status='training',message='Навчання за фактичними даними')
   return dict(manifest={day:x['revision'] for day,x in values.items()},changed=[dict(day=day,**row) for day,row in values.items() if known.get(day)!=row['revision']])
  with self.lock:
   result=engine.start(self.root,identity,sync if train else None)
   self.automatic_device=device if automatic else None
  if train:
   self.runtime.logs.event('Forecast training requested',code='forecast.training.requested',device_id=device,automatic=automatic,force_policy=force,quality_policy='solar95.min6')
   self._set(device,status='training',message='Примусовий ручний запуск; якість даних перевіряється' if force else 'Навчання виконується')
   def finish():
    while engine._active and not self.cancelled.wait(.25):pass
    if self.cancelled.is_set():return
    status=self.status(device);cal=status.get('result',{}).get('calibration',{})
    if status.get('state')=='complete' and cal.get('sample_count',0)>0:
     self._set(device,status='trained',trained_signature=signature,sample_count=cal['sample_count'],message='Навчено за'+str(cal['sample_count'])+' фактичними добами')
    else:self._set(device,status='waiting_data',message=status.get('error') or cal.get('note') or 'Очікується достатня якісна історія')
   threading.Thread(target=finish,name='ForecastCheckpoint',daemon=True).start()
  return result
 def cancel(self,device):return engine.cancel(self.root,self.identity(device))
 def power_lost(self):
  self.next=0
  with self.lock:
   if engine._active and self.automatic_device is not None:self.cancel(self.automatic_device)
 def stop(self):
  self.cancelled.set()
  for device in self.runtime.devices:self.cancel(device)
  if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=2)
 def start_scheduler(self):
  if self.thread and self.thread.is_alive():return
  self.cancelled.clear()
  def work():
   while not self.cancelled.wait(15):
    try:
     if getattr(self.runtime,'active',False):self.tick()
    except Exception as exc:self.runtime.logs.event('Forecast scheduling error',code='forecast.scheduler.failed',error=str(exc))
  self.thread=threading.Thread(target=work,name='ForecastScheduler',daemon=True);self.thread.start()
 def tick(self):
  if self.cancelled.is_set() or engine._active:return
  if not self._charging():return
  if time.monotonic()<self.next:return
  with self.runtime.api.jobs.lock:
   if any(j['state'] not in ('completed','error','cancelled') for j in self.runtime.api.jobs.jobs.values()):
    for device in self.runtime.devices:self._set(device,status='waiting_queue',message='Автонавчання очікує завершення запитів історії')
    return
  self.next=time.monotonic()+900
  for device in self.runtime.devices:
   if not self.settings(device):continue
   signature=self._signature(device)
   with self.lock:saved=dict(self.done.get(device,{}))
   if saved.get('trained_signature')==signature:continue
   self.start(device,True,True);break
