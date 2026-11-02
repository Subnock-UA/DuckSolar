"""Persistent energy estimate anchored by confirmed manual or qualified automatic full charge, never inverter SOC."""
import json,math,time,threading
from pathlib import Path
from collections import deque

def valid(v):return type(v) in (int,float) and math.isfinite(v)
class BatteryLedger:
 def __init__(self,root,clock=time.time,logs=None):
  self.path=Path(root)/'Server/BatteryEnergy.json';self.lock=threading.RLock();self.clock=clock;self.previous={};self.curves={};self.full_candidates={};self.full_latched=set();self.saved_at=0
  from .battery_history import BatteryHistory
  self.history=BatteryHistory(root,logs)
  try:self.rows=json.loads(self.path.read_text('utf-8'))
  except (OSError,ValueError):self.rows={}
 def save(self):
  from .prepared_history import write_json
  write_json(self.path,self.rows);self.saved_at=self.clock()
 def anchor(self,device,capacity,fraction=1.,source=None):
  if not valid(capacity) or capacity<=0:raise ValueError('Спочатку задайте корисну ємність АКБ')
  with self.lock:
   self.rows[device]=dict(energy_kwh=capacity*fraction,capacity_kwh=capacity,anchor_at=self.clock(),updated_at=self.clock(),gap_s=0.,charged_kwh=0.,discharged_kwh=0.,source=source or ('user_full_charge' if fraction==1 else 'user_anchor'));self.previous.pop(device,None);self.curves.pop(device,None);self.save();self.history.anchor(device,self.rows[device]['anchor_at'],capacity,self.rows[device]['source'])
 def full_charge_eligible(self,state):
  # Zero current alone is not evidence of full charge. Require current settings,
  # live permitted source and voltage at the configured float plateau.
  from .drivers.parameter_library import current_value,matches
  data=state.get('data',{});params=state.get('parameters',{});raw=params.get('raw',{})
  if state.get('stale',True) or params.get('stale',True) or not matches(raw):return False
  try:
   total=float(current_value('charging.total_current_limit',raw));utility=float(current_value('charging.utility_current_limit',raw));floating=float(current_value('charging.float_voltage',raw))
  except (KeyError,ValueError,TypeError,IndexError):return False
  try:priority=int(raw['QPIRI'].split()[17])
  except (KeyError,ValueError,IndexError):return False
  if priority not in (0,1,2):return False
  # 0 Solar first, 1 Solar + Utility, 2 Only Solar. Activity flags can be zero
  # precisely at full charge and are absent in native 4501 frames.
  pv=valid(data.get('pv_w')) and data['pv_w']>20
  grid=bool(data.get('grid_available')) and utility>0 and priority in (0,1)
  return (total>0 and (grid or pv) and valid(data.get('battery_v')) and data['battery_v']>=floating-.2
          and data.get('charge_a')==0 and data.get('discharge_a')==0)
 def view(self,device,state,cfg):
  now=self.clock();data=state.get('data',{});capacity=cfg.get('usable_kwh');voltage=data.get('battery_v');charge=data.get('charge_a');discharge=data.get('discharge_a');load=data.get('output_w')
  fresh=not state.get('stale',True) and all(valid(v) and v>=0 for v in (voltage,charge,discharge)) and voltage>0
  measured_at=state.get('updated')
  with self.lock:
   eligible=fresh and self.full_charge_eligible(state)
   candidate=self.full_candidates.get(device)
   if eligible:
    if candidate is None or now-candidate['last']>30 or now<candidate['last']:
     candidate=dict(start=now,last=now,sample=measured_at,count=1);self.full_candidates[device]=candidate
    elif candidate['sample']!=measured_at:
     candidate.update(last=now,sample=measured_at,count=candidate['count']+1)
    if (device not in self.full_latched and now-candidate['start']>=180 and candidate['count']>=30
        and now-candidate['last']<=15 and valid(capacity) and capacity>0):
     self.anchor(device,capacity,source='automatic_full_charge');self.full_latched.add(device)
   else:self.full_candidates.pop(device,None)
   # Only a real resumed discharge re-arms calibration, not a transient flag gap.
   if fresh and discharge>0:self.full_latched.discard(device)
   row=self.rows.get(device);previous=self.previous.get(device)
   if row and valid(capacity) and capacity!=row['capacity_kwh']:
    self.rows.pop(device);row=None;self.previous.pop(device,None);previous=None;self.full_candidates.pop(device,None);self.full_latched.discard(device);self.save()
   if row and previous and now>previous['time']:
    dt=now-previous['time']
    if fresh and previous['fresh'] and dt<=30:
     cw=(previous['charge_w']+voltage*charge)*.5;dw=(previous['discharge_w']+voltage*discharge)*.5
     added=cw*dt/3600000*cfg.get('charge_efficiency',.95);spent=dw*dt/3600000
     row['energy_kwh']=max(0,min(row['capacity_kwh'],row['energy_kwh']+added-spent));row['charged_kwh']+=added;row['discharged_kwh']+=spent
    else:row['gap_s']+=dt
   elif row and not previous:
    row['gap_s']+=max(0,now-row.get('updated_at',now))
   self.previous[device]=dict(time=now,fresh=fresh,charge_w=voltage*charge if fresh else 0,discharge_w=voltage*discharge if fresh else 0,sample=measured_at)
   curve=self.curves.setdefault(device,deque(maxlen=3600))
   if fresh and (not curve or now-curve[-1][0]>=4):curve.append((now,max(0,voltage*discharge-voltage*charge),load if valid(load) else None))
   while curve and now-curve[0][0]>3600:curve.popleft()
   recent=[x for x in curve if now-x[0]<=300];average=sum(x[1] for x in recent)/len(recent) if recent else None
   if row:
    row['updated_at']=now
    if now-self.saved_at>=30:self.save()
   self.history.record(device,now,row,fresh)
   soc=100*row['energy_kwh']/row['capacity_kwh'] if row else None;available=max(0,row['energy_kwh']-row['capacity_kwh']*cfg.get('reserve_pct',20)/100) if row else None
   # Replay the last hour's discharge curve. Grid-powered zeros cannot imply unlimited battery life.
   curve_power=sum(x[1] for x in curve)/len(curve) if curve else None
   current=voltage*discharge-voltage*charge if fresh else None
   hours=lambda power:available*1000/power if available is not None and valid(power) and power>=10 and fresh else None
   return dict(charged_kwh=row.get('charged_kwh') if row else None,discharged_kwh=row.get('discharged_kwh') if row else None,anchor_source=row.get('source') if row else None,soc=soc,source='energy_ledger' if row else 'unavailable',confidence='uncertain' if row and row['gap_s']>30 else 'estimated' if row else 'unavailable',gap_s=row['gap_s'] if row else None,anchor_at=row['anchor_at'] if row else None,remaining_kwh=row['energy_kwh'] if row else None,available_kwh=available,current_hours=hours(current),average_hours=hours(average),curve_hours=hours(curve_power),curve_samples=len(curve),discharge_w=current,average_discharge_w=average,charging=fresh and charge>discharge,note='Орієнтовний облік енергії від підтвердженого повного заряду; пропуски знижують достовірність.' if row else 'Очікується автоматичне визначення повного заряду або ручне підтвердження. SOC інвертора не використовується.')
