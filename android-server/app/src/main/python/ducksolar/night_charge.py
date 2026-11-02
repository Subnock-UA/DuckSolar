"""Durable opt-in tariff schedule with verified restore and exclusive writes."""
import copy,json,threading,time
from datetime import datetime
from pathlib import Path
from .energy_accounting import ZONE
from .drivers.parameter_library import command,current_value,normalized

CONTROLLED=('charging.source_priority','charging.utility_current_limit')
LOCKED=CONTROLLED+('charging.total_current_limit',)
LOCK_MESSAGE='Ввімкнено режим нічного заряджання'

class NightCharge:
 def __init__(self,runtime):
  self.runtime=runtime;self.path=Path(runtime.cfg.root_dir)/'Server/NightCharge.json';self.lock=threading.RLock();self.next={}
  self._token=object();self._workers=set();self._plans=set()
  try:self.rows=json.loads(self.path.read_text('utf-8'))
  except (OSError,ValueError):self.rows={}
  for row in self.rows.values():
   row['confirmed']={};row['applied_key']=None
   # Older schedules did not capture a source snapshot. Never invent its value.
   if row.get('enabled') and not row.get('original'):
    row.update(enabled=False,status='migration_required',error='Попередній розклад зупинено. Оновіть параметри й увімкніть режим, щоб зберегти початкові налаштування.')
 def save(self):
  from .prepared_history import write_json
  write_json(self.path,self.rows)
 @staticmethod
 def slot(at):
  from datetime import timedelta
  local=at.astimezone(ZONE);night=local.hour>=23 or local.hour<7
  day=local.date()-timedelta(days=1) if local.hour<7 else local.date()
  return day.isoformat()+(' night' if night else ' day'),night
 def guard(self,device,parameter,automation=None):
  with self.lock:
   row=self.rows.get(device,{})
   if automation is not None:
    token,revision,period=automation
    if token is not self._token or revision!=row.get('revision',0) or not (row.get('enabled') or row.get('restore_pending')):
     raise ValueError('Розклад змінений або вимкнений; застарілу команду скасовано')
    if period is not None and period!=self.slot(datetime.now(ZONE))[0]:raise ValueError('Період розкладу змінився; застарілу команду скасовано')
   elif parameter in LOCKED and (row.get('enabled') or row.get('restore_pending')):
    raise ValueError(LOCK_MESSAGE if row.get('enabled') else 'Триває відновлення налаштувань нічного заряджання')
 def config(self,device,user,value=None):
  with self.lock:
   row=self.rows.setdefault(device,dict(enabled=False,day_a=10,night_a=60,adaptive_enabled=False,night_battery_share_pct=100,status='disabled'))
   row.setdefault('adaptive_enabled',False);row.setdefault('night_battery_share_pct',100)
   if value is None:return copy.deepcopy(row)
   if not isinstance(value,dict) or set(value)-{'enabled','day_a','night_a','adaptive_enabled','night_battery_share_pct'}:raise ValueError('Невідомі налаштування нічного заряду')
   candidate={**row,**value}
   if type(candidate['enabled']) is not bool or type(candidate['adaptive_enabled']) is not bool:raise ValueError('Некоректний перемикач')
   if type(candidate['night_battery_share_pct']) not in (int,float) or not 0<=candidate['night_battery_share_pct']<=100:raise ValueError('Частка нічного навантаження має бути 0–100%')
   for key in ('day_a','night_a'):command('charging.utility_current_limit',candidate[key])
   if row.get('restore_pending') and candidate['enabled']:raise ValueError('Дочекайтеся відновлення початкових налаштувань')
   if candidate['enabled']:
    if getattr(self.runtime,'profile_batches',{}).get(device):raise ValueError('Дочекайтеся завершення профілю')
    dev=self.runtime.device(device);snapshot=dev.parameters.snapshot()
    if snapshot['stale'] and not row.get('enabled'):raise ValueError('Оновіть параметри інвертора перед ввімкненням')
    total=float(current_value('charging.total_current_limit',snapshot['raw']))
    if max(candidate['day_a'],candidate['night_a'])>total:raise ValueError('Струм розкладу перевищує загальний ліміт '+str(total)+' А; загальний ліміт автоматично не змінюється')
    identity=dev.driver.identity(snapshot['raw'])
    if not identity.get('serial'):raise ValueError('Серійний номер інвертора ще не отримано')
    if not row.get('enabled'):
     commands=self.runtime.commands
     from contextlib import nullcontext
     with getattr(commands,'lock',nullcontext()):
      if any(item.get('device_id')==device and item.get('status') not in commands.TERMINAL for item in commands.items.values()):raise ValueError('Дочекайтеся перевірки попередньої операції')
      for item in reversed(list(commands.items.values())):
       parameter=item.get('parameter')
       if item.get('device_id')==device and parameter in LOCKED and item.get('status')=='verified':
        if normalized(current_value(parameter,snapshot['raw']))!=normalized(item.get('actual',item['new'])):raise ValueError('Оновіть параметри після попередньої зміни')
        break
     # Capture BEFORE any write, once per enable/restore cycle.
     original={key:current_value(key,snapshot['raw']) for key in CONTROLLED}
     for key,target in original.items():command(key,target)
     candidate.update(original=original,identity=identity)
    elif candidate.get('identity')!=identity:raise ValueError('Ідентичність інвертора змінилася')
   restoring=bool(row.get('restore_pending') or row.get('enabled') and not candidate['enabled'])
   candidate.update(user=user,revision=row.get('revision',0)+1,restore_pending=restoring,confirmed={},applied_key=None,applied_plan=None,blocked_write=None,
                    status='restoring' if restoring else 'waiting' if candidate['enabled'] else 'disabled',error='')
   self.rows[device]=candidate
   try:self.save()
   except Exception:
    self.rows[device]=row
    raise
   self.next[device]=0
   # Dispatch now; do not wait for the periodic supervisor or tariff boundary.
   self._wake(device)
   return copy.deepcopy(candidate)
 def _wake(self,device):
  if device in self._workers:return
  self._workers.add(device)
  def work():
   try:self.tick(device,force=True)
   finally:
    with self.lock:self._workers.discard(device)
  threading.Thread(target=work,name='NightChargeApply',daemon=True).start()
 def authorize(self,device,user):
  account=next((x for x in self.runtime.api.accounts.inventory() if x['username']==user),None)
  if not account or account['blocked'] or device not in json.loads(account['grants']):raise ValueError('Дозвіл власника розкладу відкликано')
 def tick(self,device,force=False):
  with self.lock:
   if not force and time.monotonic()<self.next.get(device,0):return
   self.next[device]=time.monotonic()+1
   row=self.rows.get(device)
   if not row or not (row.get('enabled') or row.get('restore_pending')):return
   try:
    user=row['user'];self.authorize(device,user)
    dev=self.runtime.device(device)
    # Finish/observe an old operation even after the configuration revision changes.
    if row.get('operation_id'):
     result=self.runtime.commands.status(row['operation_id'],row.get('operation_user',user),device)
     if result['status'] not in self.runtime.commands.TERMINAL:return
     row['operation_id']=None
     if result['status']=='verified':row.setdefault('confirmed',{})[result['parameter']]=result.get('actual',result['new'])
     else:
      row.update(error=result.get('message','Зміну не підтверджено'),status='restoring' if row.get('restore_pending') else 'waiting')
      row['confirmed']={}
      if result.get('sent'):row['blocked_write']=[result['parameter'],str(result['new']),row.get('operation_revision')]
      self.next[device]=0 if row.get('operation_revision')!=row.get('revision',0) else time.monotonic()+30
      dev.parameters.request_refresh();self.save();return
    slot,night=self.slot(datetime.now(ZONE));key=[row.get('revision',0),slot]
    if not row.get('restore_pending') and row.get('applied_key')==key:return
    if row.get('step_key')!=key and not row.get('restore_pending'):
     row.update(step_key=key,confirmed={},applied_plan=None)
    snapshot=dev.parameters.snapshot()
    if snapshot['stale']:
     dev.parameters.request_refresh();raise ValueError('Очікування свіжих параметрів')
    if row.get('identity')!=dev.driver.identity(snapshot['raw']):raise ValueError('Ідентичність інвертора змінилася; застосування зупинено')
    if row.get('restore_pending'):
     targets=row.get('original')
     if not targets or set(targets)!=set(CONTROLLED):raise ValueError('Початкові налаштування відсутні; автоматичне відновлення неможливе')
     row['target_source']=targets[CONTROLLED[0]];row['target_a']=targets[CONTROLLED[1]]
    else:
     target=row['night_a'] if night else row['day_a']
     if night and row.get('adaptive_enabled'):
      plan=row.get('applied_plan')
      if not plan:
       plan_key=(device,row.get('revision',0),slot)
       if plan_key not in self._plans:
        self._plans.add(plan_key);row.update(status='planning',error='');self.save()
        def prepare_plan(row=row,dev=dev,plan_key=plan_key):
         try:
          try:result=self.runtime.forecast.analytics.plan(device,dev.history,refresh=False)
          except Exception as error:result=dict(available=False,note='План недоступний: '+str(error))
          with self.lock:
           if self.rows.get(device) is row and row.get('enabled') and plan_key[1]==row.get('revision',0) and plan_key[2]==self.slot(datetime.now(ZONE))[0]:
            row['applied_plan']=result;self.save();self.next[device]=0
         finally:
          with self.lock:self._plans.discard(plan_key)
        threading.Thread(target=prepare_plan,name='NightChargePlan',daemon=True).start()
       return
      if plan.get('available'):target=min(row['night_a'],plan['recommended_a'])
     targets={CONTROLLED[0]:1 if night else 2,CONTROLLED[1]:target}
     row.update(target_a=target,target_source=targets[CONTROLLED[0]])
    if float(targets[CONTROLLED[1]])>float(current_value('charging.total_current_limit',snapshot['raw'])):raise ValueError('Ціль перевищує поточний загальний ліміт заряду')
    # Close the daytime source first; set the night/restore current before opening mains.
    order=CONTROLLED if normalized(targets[CONTROLLED[0]])==2 else tuple(reversed(CONTROLLED))
    for parameter in order:
     actual=row.get('confirmed',{}).get(parameter,current_value(parameter,snapshot['raw']))
     if normalized(actual)==normalized(targets[parameter]):continue
     revision=row.get('revision',0)
     blocked=row.get('blocked_write')
     if blocked and blocked[0]==parameter and normalized(blocked[1])==normalized(targets[parameter]) and blocked[2]==revision:raise ValueError('Запис не підтверджено; автоматичний повтор зупинено. Оновіть параметри та збережіть режим для повторної спроби.')
     result=self.runtime.commands.submit(device,parameter,targets[parameter],actual,user,
         lambda device=device,user=user:self.authorize(device,user),automation=(self._token,revision,None if row.get('restore_pending') else slot))
     row.update(operation_id=result['operation_id'],operation_user=user,operation_revision=revision,status='restoring' if row.get('restore_pending') else 'applying',error='')
     self.save();return
    if row.get('restore_pending'):
     row.update(restore_pending=False,status='disabled',original=None,confirmed={},error='',applied_key=None)
    else:row.update(applied_key=key,status='applied',error='')
    self.save()
   except Exception as exc:
    message=str(exc)
    if row.get('error')!=message:
     row.update(status='restoring' if row.get('restore_pending') else 'waiting',error=message);self.save()
     self.runtime.logs.event('Night charge waiting',code='night_charge.waiting',device_id=device,error=message)
