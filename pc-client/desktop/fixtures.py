from datetime import datetime,timedelta
from types import SimpleNamespace
from pathlib import Path
import json,time
from .model import ZONE
from ducksolar.notification_settings import DEFAULTS
METRICS={
'pv.total_power':(2540,'W','Генерація PV'),'pv.inputs.aggregate.voltage':(325,'V','Напруга PV'),'pv.inputs.aggregate.current':(7.81,'A','Струм PV'),
'grid.import_power':(0,'W','Імпорт'),'grid.export_power':(620,'W','Експорт'),'grid.phases.L1.voltage':(231,'V','Напруга мережі'),'grid.phases.L1.current':(2.68,'A','Струм мережі'),'grid.phases.L1.frequency':(50,'Hz','Частота мережі'),
'output.active_power':(1320,'W','Потужність навантаження'),'output.apparent_power':(1460,'VA','Повна потужність'),'output.phases.L1.voltage':(230,'V','Вихідна напруга'),'output.phases.L1.current':(6.35,'A','Струм навантаження'),'output.phases.L1.frequency':(50,'Hz','Вихідна частота'),'output.load_percent':(21,' %','Навантаження'),
'battery.channels.main.soc':(74,' %','SOC БМС'),'battery.channels.main.voltage':(53.2,'V','Напруга АКБ'),'battery.channels.main.charge_current':(10.5,'A','Струм заряду'),'battery.channels.main.discharge_current':(0,'A','Струм розряду'),'battery.charge_power':(558.6,'W','Потужність заряду'),'battery.discharge_power':(0,'W','Потужність від АКБ'),'temperature.inverter':(39,'C','Температура інвертора'),'dc.bus_voltage':(390,'V','Напруга DC-шини'),'battery.scc_voltage':(53.2,'V','Напруга SCC')}
def envelope():
 return dict(connected=True,route='local',connection_message='Сервер підключено; дані актуальні',last_received_age_s=.6,state=dict(device_id='inverter-1',stale=False,updated=datetime.now(ZONE).isoformat(),normalized=dict(metrics={k:dict(value=v,unit=u,quality='good',source='inverter',age_s=1,valid_for_s=15) for k,(v,u,n) in METRICS.items()}),descriptor=dict(name='DAXTROMN 6.2 PRO BMS',metric_definitions=[dict(canonical_id=k,ui_name=n,unit=u) for k,(v,u,n) in METRICS.items()]),server_phone=dict(available=True,age_s=1,battery_percent=74,external_power=False,wifi_connected=True,wifi_rssi_dbm=-59)))
def graph(mode='power',period='day',fields=None):
 fields=fields or ['pv_w','output_w'];start=datetime(2026,10,26,7,tzinfo=ZONE)
 points=[]
 for i in range(24):
  row=dict(x=i if mode=='energy' else (start+timedelta(minutes=20*i)).timestamp()*1000,label=f'2026-10-{i+1:02d}' if mode=='energy' else (start+timedelta(minutes=20*i)).isoformat())
  for f in fields:row[f]=round((max(0,12-abs(12-i))*220 if f=='pv_w' else 850+i*35)*(0.001 if mode=='energy' else 1),3)
  points.append(row)
 totals={key:dict(kwh=value,coverage_seconds=86400,partial=False) for key,value in [('generation',18.75),('consumption',14.2),('export',5.6),('import',1.3),('balance',4.3)]}
 return dict(contract='ducksolar.graph.v1',kind='bars' if mode=='energy' else 'line',mode=mode,period=period,anchor='2026-10-26',source='Auto',fields=[dict(key=f,label={'pv_w':'Генерація','output_w':'Споживання'}.get(f,f),unit='кВт·год' if mode=='energy' else 'Вт') for f in fields],points=points,energy_summary=totals,events=[dict(x=11 if mode=='energy' else points[11]['x'],time=points[11]['label'],code='grid',message='Відновлено мережу')])
class FixtureController:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.profile=dict(lan='https://192.0.2.10:28766',remote='https://example.invalid:28766',username='fixture',serial='fixture');self.backend=SimpleNamespace(_cfg=dict(client_id='a'*32));self.alert_history=[];self.calls=[];self.jobs={};self.visible=True;self.notify=None
 def snapshot(self):return envelope()
 def set_visible(self,value):self.visible=value
 def close(self):pass
 def call(self,method,*args):
  self.calls.append((method,args))
  if method=='connection_health':return dict(connected=True,route='local',server_phone=envelope()['state']['server_phone'])
  if method=='notification_settings':return dict(settings=DEFAULTS,pending=False)
  if method=='event_rows':return [dict(time='2026-10-26T12:00:00+02:00',code='grid',message='Напруга мережі відновлена',active=False)]
  if method=='history_dates':return dict(count=3,dates=['2026-10-26','2026-10-25','2026-10-24'])
  if method=='parameter_snapshot':return dict(stale=False,device_id='inverter-1',server_profile='fixture',rows=[dict(canonical_id='charging.utility_current_limit',name='Струм заряду від мережі',raw_value='010',value=10,unit='A',writable=True,present=True,allowed_note='0–80 А',write_rule=dict(minimum=0,maximum=80))])
  if method=='tariff_status':return dict(history=[dict(effective_from='2026-01-01',uah_per_kwh=6.4,source='НКРЕКП')])
  if method=='weather_profile':return dict(installed_kw=6.2,tilt_deg=35,azimuth_deg=180)
  if method=='weather_status':return dict(state='complete',settings=dict(location='Київ',installed_kw=6.2,tilt_deg=35,azimuth_deg=180),result=dict(location=dict(name='Київ'),days=[dict(date='2026-10-26',temp_min_c=8,temp_max_c=16,condition='Мінлива хмарність')],generation_by_day={'2026-10-26':dict(expected_kwh=18.5,low_kwh=14.2,high_kwh=21.8)},calibration=dict(sample_count=12,note='Навчено за повними днями')))
  if method=='graph_start':
   self.jobs['graph_status']=dict(state='complete',result=graph(args[4],args[0],json.loads(args[3])));return dict(state='running')
  if method=='balance_start':self.jobs['balance_status']=dict(state='complete',result=dict(month=args[0],generation_kwh=18.,import_kwh=2.,export_kwh=4.,saldo_kwh=2.));return dict(state='running')
  if method=='feature_start':self.jobs['feature_status']=dict(state='complete',result=dict(kind=args[0],summary=graph()['energy_summary'],graph=graph('energy')));return dict(state='running')
  if method in self.jobs:return self.jobs[method]
  if method in ('meter_readings','commands'):return []
  return dict(state='complete')
 def feature(self,method,*args):
  self.calls.append(('feature.'+method,args))
  if method=='profiles':return {'Звичайний':{'charging.utility_current_limit':'10'}}
  if method=='commands':return [dict(created='2026-10-26 07:00',parameter='charging.utility_current_limit',old='060',new='010',status='verified')]
  if method=='battery_config':return dict(usable_kwh=10.0,reserve_pct=10.,charge_efficiency=.95)
  if method=='battery':return dict(estimate=dict(remaining_kwh=10.61,available_kwh=9.18,current_hours=7.2,average_hours=6.8,curve_hours=6.9,confidence='measured',source='bms.inverter',note='SOC БМС; залишок енергії — за заданою ємністю'),values=dict(soc=74.))
  if method=='night_charge':return dict(enabled=False,day_a=10,night_a=60,adaptive_enabled=False,night_battery_share_pct=100,status='disabled')
  if method=='pv_correction':return dict(pv_correction_factor=1.0,pv_night_noise_w=0.,weather_latitude=50.45,weather_longitude=30.52)
  return {}
