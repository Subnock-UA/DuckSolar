"""Explicit opt-in server schedule; user edits last until the next tariff boundary."""
import json,time,threading,copy
from datetime import datetime
from pathlib import Path
from .energy_accounting import ZONE
from .drivers.parameter_library import command,current_value,normalized
class NightCharge:
 def __init__(self,runtime):
  self.runtime=runtime;self.path=Path(runtime.cfg.root_dir)/'Server/NightCharge.json';self.lock=threading.RLock();self.next={}
  try:self.rows=json.loads(self.path.read_text('utf-8'))
  except (OSError,ValueError):self.rows={}
 def save(self):
  from .prepared_history import write_json
  write_json(self.path,self.rows)
 @staticmethod
 def slot(at):
  from datetime import timedelta
  local=at.astimezone(ZONE);night=local.hour>=23 or local.hour<7
  day=(local.date()-timedelta(days=1)) if local.hour<7 else local.date()
  return day.isoformat()+(' night' if night else ' day'),night
 def config(self,device,user,value=None):
  with self.lock:
   row=self.rows.setdefault(device,dict(enabled=False,day_a=10,night_a=60,adaptive_enabled=False,night_battery_share_pct=100,status='disabled'))
   row.setdefault('adaptive_enabled',False);row.setdefault('night_battery_share_pct',100)
   if value is not None:
    if not isinstance(value,dict) or set(value)-{'enabled','day_a','night_a','adaptive_enabled','night_battery_share_pct'}:raise ValueError('Невідомі налаштування нічного заряду')
    candidate={**row,**value}
    if type(candidate['adaptive_enabled']) is not bool:raise ValueError('Некоректний перемикач адаптивного заряду')
    if type(candidate['night_battery_share_pct']) not in (int,float) or not 0<=candidate['night_battery_share_pct']<=100:raise ValueError('Частка нічного навантаження має бути0–100%')
    if type(candidate['enabled']) is not bool:raise ValueError('Некоректний перемикач')
    for key in ('day_a','night_a'):command('charging.utility_current_limit',candidate[key])
    if candidate['enabled']:
     dev=self.runtime.device(device);snapshot=dev.parameters.snapshot()
     if snapshot['stale']:raise ValueError('Оновіть параметри інвертора перед ввімкненням')
     total=float(current_value('charging.total_current_limit',snapshot['raw']))
     if max(candidate['day_a'],candidate['night_a'])>total:raise ValueError('Струм розкладу перевищує загальний ліміт '+str(total)+' А; загальний ліміт автоматично не змінюється')
     candidate['identity']=dev.driver.identity(snapshot['raw'])
    candidate.update(user=user,status='waiting' if candidate['enabled'] else 'disabled',applied_slot=None,operation_id=None,error='')
    row=candidate;self.rows[device]=row;self.next[device]=0;self.save()
   return copy.deepcopy(row)
 def authorize(self,device,row):
  account=next((x for x in self.runtime.api.accounts.inventory() if x['username']==row['user']),None)
  if not account or account['blocked'] or device not in json.loads(account['grants']):raise ValueError('Дозвіл власника розкладу відкликано')
  if self.rows.get(device) is not row or not row.get('enabled'):raise ValueError('Розклад змінений або вимкнений')
 def tick(self,device):
  if time.monotonic()<self.next.get(device,0):return
  self.next[device]=time.monotonic()+30
  with self.lock:
   row=self.rows.get(device)
   if not row or not row.get('enabled'):return
   slot,night=self.slot(datetime.now(ZONE));target=row['night_a'] if night else row['day_a']
   try:
    self.authorize(device,row);dev=self.runtime.device(device);snapshot=dev.parameters.snapshot()
    if snapshot['stale']:raise ValueError('Очікування свіжих параметрів')
    if row.get('identity')!=dev.driver.identity(snapshot['raw']):raise ValueError('Ідентичність інвертора змінилася; переввімкніть розклад')
    actual=current_value('charging.utility_current_limit',snapshot['raw'])
    if row.get('operation_id'):
     result=self.runtime.commands.status(row['operation_id'],row['user'],device)
     if result['status'] not in self.runtime.commands.TERMINAL:return
     row.update(status=result['status'],error=result.get('message',''),operation_id=None);self.save()
    if row.get('applied_slot')==slot:return
    if night and row.get('adaptive_enabled'):
     try:plan=self.runtime.forecast.analytics.plan(device,dev.history,refresh=False)
     except (ValueError,OSError,KeyError,TypeError) as error:plan=dict(available=False,note='План недоступний: '+str(error))
     row['applied_plan']=plan
     if plan.get('available'):target=plan['recommended_a']
     else:self.runtime.logs.event('Adaptive charge uses fixed fallback',code='night_charge.adaptive.fallback',device_id=device,reason=plan.get('note'))
    if target>float(current_value('charging.total_current_limit',snapshot['raw'])):raise ValueError('План перевищує поточний загальний ліміт')
    row['target_a']=target
    if normalized(actual)==normalized(target):row.update(applied_slot=slot,status='already_set',error='');self.save();return
    result=self.runtime.commands.submit(device,'charging.utility_current_limit',target,actual,row['user'],lambda:self.authorize(device,row))
    row.update(applied_slot=slot,operation_id=result['operation_id'],status='queued',target_a=target,error='');self.save()
   except Exception as exc:
    message=str(exc)
    if row.get('error')!=message:row.update(status='waiting',error=message);self.save();self.runtime.logs.event('Night charge waiting',code='night_charge.waiting',device_id=device,error=message)
