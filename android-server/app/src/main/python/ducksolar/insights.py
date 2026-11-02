"""Persistent grid outages/settings profiles and battery daily extrema.
No extra equipment polling, no changes to original telemetry archives.
"""
import json,sqlite3,threading,time,math,copy
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
from .energy_accounting import ZONE

DEFAULTS=dict(usable_kwh=None,reserve_pct=20,efficiency=.9,scenario_w=300,charge_efficiency=.95)
class Insights:
 def __init__(self,runtime):
  self.runtime=runtime;self.lock=threading.RLock();self.previous={};self.active={};self.profile_jobs={};self.stats={}
  self.path=Path(runtime.cfg.root_dir)/'Server/Insights.json';self.dbpath=self.path.with_suffix('.sqlite3');self.path.parent.mkdir(parents=True,exist_ok=True)
  try:self.saved=json.loads(self.path.read_text(encoding='utf-8'))
  except (OSError,ValueError):self.saved={}
  with self.db() as db:
   db.execute('CREATE TABLE IF NOT EXISTS outages(id TEXT PRIMARY KEY,device TEXT,start REAL,end REAL,soc_start REAL,soc_end REAL,known_s REAL DEFAULT 0,uncertain INTEGER DEFAULT 0)')
   db.execute('CREATE INDEX IF NOT EXISTS outage_device_start ON outages(device,start)')
   db.execute('CREATE TABLE IF NOT EXISTS extrema(device TEXT,day TEXT,min_soc REAL,max_load REAL,PRIMARY KEY(device,day))')
   for row in db.execute('SELECT * FROM outages WHERE end IS NULL'):
    self.active[row['device']]=dict(row);db.execute('UPDATE outages SET uncertain=1 WHERE id=?',(row['id'],))
    self.active[row['device']]['uncertain']=1
 @contextmanager
 def db(self):
  db=sqlite3.connect(self.dbpath,timeout=5);db.row_factory=sqlite3.Row
  try:
   with db:yield db
  finally:db.close()
 def _save(self):
  p=self.path.with_suffix('.tmp');p.write_text(json.dumps(self.saved,ensure_ascii=False,allow_nan=False),encoding='utf-8');p.replace(self.path)
 def config(self,device,value=None):
  with self.lock:
   old={**DEFAULTS,**self.saved.get('battery',{}).get(device,{})}
   if value is not None:
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('Некоректні налаштування АКБ')
    new={**old,**value}
    for k,lo,hi in [('usable_kwh',.1,1000),('reserve_pct',0,95),('efficiency',.5,1),('scenario_w',10,100000),('charge_efficiency',.5,1)]:
     v=new[k]
     if k=='usable_kwh' and v is None:continue
     if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError(k+': значення поза діапазоном')
    self.saved.setdefault('battery',{})[device]=new;self._save();old=new
   return old
 def pv_config(self,device,value=None):
  cfg=self.runtime.device(device).cfg
  with self.lock:
   current={key:getattr(cfg,key) for key in ('pv_correction_factor','pv_night_noise_w','weather_latitude','weather_longitude')}
   current.update(self.saved.get('pv_correction',{}).get(device,{}))
   if value is not None:
    if not isinstance(value,dict) or set(value)-set(current):raise ValueError('Невідомі параметри PV')
    current.update(value)
    for key,lo,hi in [('pv_correction_factor',.5,1.5),('pv_night_noise_w',0,20),('weather_latitude',-90,90),('weather_longitude',-180,180)]:
     v=current[key]
     if v is None and key.startswith('weather_'):continue
     if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Некоректне поле '+key)
    self.saved.setdefault('pv_correction',{})[device]=current;self._save()
   for key,v in current.items():setattr(cfg,key,v)
   return current
 def observe(self,device,state):
  now=time.time();soc=state.get('battery',{}).get('values',{}).get('soc');load=state.get('data',{}).get('output_w');stale=state.get('stale',True)
  grid=state.get('normalized',{}).get('grid',{}).get('voltage_present')
  if not isinstance(grid,bool) or stale:grid=None
  with self.lock,self.db() as db:
   previous=self.previous.get(device);self.previous[device]=(now,grid)
   active=self.active.get(device)
   if grid is False and not active:
    active=dict(id=uuid4().hex,device=device,start=now,end=None,soc_start=soc,soc_end=None,known_s=0.,uncertain=int(previous is None or previous[1] is None));self.active[device]=active
    db.execute('INSERT INTO outages VALUES(:id,:device,:start,:end,:soc_start,:soc_end,:known_s,:uncertain)',active)
   if active:
    if grid is None:active['uncertain']=1
    if previous and previous[1] is False and grid is not None:
     dt=now-previous[0]
     if 0<=dt<=30:active['known_s']+=dt
     else:active['uncertain']=1
    if grid is True:active.update(end=now,soc_end=soc);self.active.pop(device,None)
    if grid is not False or not previous or int(now//60)!=int(previous[0]//60):
     db.execute('UPDATE outages SET end=:end,soc_end=:soc_end,known_s=:known_s,uncertain=:uncertain WHERE id=:id',active)
   if not stale:
    day=datetime.fromtimestamp(now,ZONE).date().isoformat()
    good=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
    soc=soc if good(soc) else None;load=load if good(load) else None
    old=self.stats.get((device,day),(None,None))
    new=(min(v for v in (old[0],soc) if v is not None) if any(v is not None for v in (old[0],soc)) else None,max(v for v in (old[1],load) if v is not None) if any(v is not None for v in (old[1],load)) else None)
    if new!=old:
     self.stats[(device,day)]=new
     db.execute('INSERT INTO extrema VALUES(?,?,?,?) ON CONFLICT(device,day) DO UPDATE SET min_soc=CASE WHEN excluded.min_soc IS NULL THEN min_soc WHEN min_soc IS NULL THEN excluded.min_soc ELSE MIN(min_soc,excluded.min_soc) END,max_load=CASE WHEN excluded.max_load IS NULL THEN max_load WHEN max_load IS NULL THEN excluded.max_load ELSE MAX(max_load,excluded.max_load) END',(device,day,*new))

 def outages(self,device,start,end):
  with self.lock,self.db() as db:
   rows=[dict(x) for x in db.execute('SELECT * FROM outages WHERE device=? AND start<? AND (end IS NULL OR end>?) ORDER BY start DESC',(device,end,start))]
   for row in rows:
    if row['end'] is None and device in self.active:row.update(self.active[device])
    row['duration_s']=max(0,min(row['end'] or time.time(),end)-max(row['start'],start));row['start_iso']=datetime.fromtimestamp(row['start'],ZONE).isoformat();row['end_iso']=datetime.fromtimestamp(row['end'],ZONE).isoformat() if row['end'] else None
   return rows
 def commands(self,device,user):
  with self.runtime.commands.lock:return sorted([copy.deepcopy(x) for x in self.runtime.commands.items.values() if x.get('device_id')==device and x.get('username')==user],key=lambda x:x.get('created',''),reverse=True)[:200]
 def profiles(self,device,user,name=None,values=None,delete=False):
  key=user+'|'+device
  with self.lock:
   profiles=self.saved.setdefault('profiles',{}).setdefault(key,{})
   if name is not None:
    if not isinstance(name,str) or not 1<=len(name.strip())<=64:raise ValueError('Назва профілю:1–64символи')
    if delete:profiles.pop(name,None)
    else:
     if len(profiles)>=12 and name not in profiles:raise ValueError('Не більше12профілів')
     state=self.runtime.device(device).parameters.snapshot();raw=state['raw']
     from .drivers.parameter_library import command
     if not isinstance(values,dict) or not 1<=len(values)<=32:raise ValueError('Порожній профіль')
     for k,v in values.items():command(k,v)
     profiles[name]=dict(values=values,identity=self.runtime.device(device).driver.identity(raw))
    self._save()
   return copy.deepcopy(profiles)
 def preview(self,device,user,name):
  profile=self.profiles(device,user).get(name)
  if not profile:raise ValueError('Профіль не знайдений')
  dev=self.runtime.device(device);state=dev.parameters.snapshot()
  if state['stale']:raise ValueError('Спочатку перечитайте актуальні параметри')
  if profile['identity']!=dev.driver.identity(state['raw']):raise ValueError('Профіль іншого інвертора/прошивки')
  from .drivers.parameter_library import current_value,normalized
  return [dict(parameter=k,old=current_value(k,state['raw']),new=str(v)) for k,v in profile['values'].items() if normalized(current_value(k,state['raw']))!=normalized(v)]
 def apply(self,device,user,name,expected,authorize):
  changes=self.preview(device,user,name)
  if changes!=expected:raise ValueError('Параметри змінилися; повторіть перегляд профілю')
  for change in changes:self.runtime.night_charge.guard(device,change['parameter'])
  ident=uuid4().hex
  with self.lock,self.runtime.commands.lock:
   for key in list(self.profile_jobs):
    if len(self.profile_jobs)<25:break
    if self.profile_jobs[key]['status']!='running':self.profile_jobs.pop(key)
   if device in self.runtime.profile_batches:raise ValueError('Профіль вже виконується')
   self.runtime.profile_batches[device]=ident;self.profile_jobs[ident]=dict(id=ident,device=device,user=user,status='running',steps=[],total=len(changes))
  def work():
   job=self.profile_jobs[ident];pending=list(changes)
   try:
    from .drivers.parameter_library import validate_state,current_value,normalized
    while pending:
     authorize();dev=self.runtime.device(device);snapshot=dev.parameters.snapshot()
     if snapshot['stale']:raise ValueError('Параметри застарілі; профіль зупинено')
     selected=None
     for change in pending:
      # A profile never overwrites a concurrent/manual change made after preview.
      if normalized(current_value(change['parameter'],snapshot['raw']))!=normalized(change['old']):raise ValueError('Початкове значення змінилося')
      try:validate_state(change['parameter'],change['new'],snapshot['raw'],dev.monitor.snapshot().get('mode_code','L'));selected=change;break
      except ValueError:continue
     if selected is None:raise ValueError('Неможливий безпечний порядок змін; змініть профіль')
     result=self.runtime.commands.submit(device,selected['parameter'],selected['new'],selected['old'],user,authorize,batch_id=ident)
     until=time.monotonic()+130
     while result['status'] not in self.runtime.commands.TERMINAL and time.monotonic()<until:
      if self.runtime.event_stop.wait(.5):raise ValueError('Сервер зупиняється')
      result=self.runtime.commands.status(result['operation_id'],user,device)
     with self.lock:job['steps'].append(result)
     if result['status']!='verified':raise ValueError('Зміну не підтверджено; наступні не виконувалися')
     pending.remove(selected);dev.parameters.request_refresh();until=time.monotonic()+45
     while pending:
      latest=dev.parameters.snapshot()
      if not latest['stale'] and normalized(current_value(selected['parameter'],latest['raw']))==normalized(selected['new']):break
      if time.monotonic()>until or self.runtime.event_stop.wait(.5):raise ValueError('Контрольні параметри ще не оновлені')
    with self.lock:job['status']='verified'
   except Exception as exc:
    with self.lock:job.update(status='stopped',error=str(exc))
   finally:
    with self.lock:self.runtime.profile_batches.pop(device,None)
  threading.Thread(target=work,name='ParameterProfile',daemon=True).start()
  return dict(self.profile_jobs[ident])
 def job(self,device,user,ident):
  with self.lock:
   job=self.profile_jobs.get(ident,{})
   if job.get('device')!=device or job.get('user')!=user:raise ValueError('Операцію не знайдено')
   return copy.deepcopy(job)
