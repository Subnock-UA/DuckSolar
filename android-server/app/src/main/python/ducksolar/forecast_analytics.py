"""Actual issued-forecast accuracy, live remainder and conservative charge plans."""
import json,math,statistics,time,hashlib,threading
from datetime import datetime,date,timedelta
from pathlib import Path
from .energy_accounting import ZONE,stamp
from .forecast_summary import summaries,_day
from .solar_time import active_windows

def number(v):return type(v) in (int,float) and math.isfinite(v)
def model_key(reader):return hashlib.sha256(json.dumps(reader.model_signature(),sort_keys=True,default=str).encode()).hexdigest()
def fraction_remaining(rows,day,now,start_hour=None,end_hour=None):
 total=0.
 for row in rows:
  if row.get('day')!=day:continue
  at=stamp(row['time']);a=at.timestamp();b=a+3600
  if start_hour is not None:
   start=datetime.combine(at.date(),datetime.min.time(),ZONE).replace(hour=start_hour).timestamp();end=datetime.combine(at.date(),datetime.min.time(),ZONE).replace(hour=end_hour).timestamp();a=max(a,start);b=min(b,end)
  left=max(a,now)
  if b>left and number(row.get('kwh')):total+=row['kwh']*(b-left)/3600
 return total

def predictions(row):
 result=dict(row.get('by_horizon',{}));current=row
 for _ in range(16):
  if not current:break
  lead=current.get('horizon_days',0)
  if type(lead) is int and lead>=1:result.setdefault(str(lead),current)
  current=current.get('previous_issued_forecast')
 return result

def valid_issue(day,row,lead):
 try:
  issued=stamp(row['issued_at']);target=datetime.combine(date.fromisoformat(day),datetime.min.time(),ZONE)
  return number(row.get('expected_kwh')) and row['expected_kwh']>=0 and issued.timestamp()<target.timestamp() and (target.date()-issued.astimezone(ZONE).date()).days==lead
 except (KeyError,ValueError,TypeError):return False

class ForecastAnalytics:
 def __init__(self,runtime,forecast):
  self.runtime=runtime;self.forecast=forecast
  self._live_lock=threading.Lock();self._live_facts={}
 def _live_actual(self,device,reader,today,lat,lon,cancelled,now):
  key=(device,today.isoformat(),model_key(reader),lat,lon)
  while not self._live_lock.acquire(timeout=.1):
   if cancelled():raise ValueError('Скасовано')
  try:
   saved=self._live_facts.get(key)
   if saved and 0<=now-saved[0]<30:return saved[1],saved[0],True
   result=_day(reader,today,lat,lon,cancelled,until=now,with_hourly=True)
   if cancelled():raise ValueError('Скасовано')
   self._live_facts={key:(now,result)}
   return result,now,False
  finally:self._live_lock.release()
 def weather(self,device):return self.forecast.cached_result(device)
 def location(self,weather):
  location=weather.get('location',{});lat,lon=location.get('latitude'),location.get('longitude')
  if not all(number(v) for v in (lat,lon)):raise ValueError('Спочатку оновіть погоду та координати станції')
  return lat,lon
 def accuracy(self,device,reader,cancelled,progress=None,anchor=None):
  weather=self.weather(device);lat,lon=self.location(weather);today=anchor or datetime.now(ZONE).date();archive=weather.get('forecast_archive',{});start=today-timedelta(days=30)
  candidates={day:row for day,row in archive.items() if start<=date.fromisoformat(day)<today and predictions(row)}
  actual=summaries(reader,lat,lon,maximum=90,cancelled=cancelled,progress=progress,parallel=False) if candidates else {}
  rows=[];excluded=[]
  for day,row in sorted(candidates.items()):
   if cancelled():raise ValueError('Скасовано')
   summary=actual.get(day,{}).get('summary',{})
   if summary.get('solar_coverage_pct',0)<95:
    excluded.append(dict(day=day,coverage_pct=summary.get('solar_coverage_pct',0)));continue
   for key,prediction in predictions(row).items():
    try:lead=int(key)
    except ValueError:continue
    if not valid_issue(day,prediction,lead):continue
    observed=summary['pv_kwh'];expected=prediction['expected_kwh'];error=expected-observed
    rows.append(dict(day=day,horizon=lead,issued_at=prediction['issued_at'],forecast_kwh=expected,actual_kwh=observed,error_kwh=error,error_pct=100*error/expected if expected>0 else None,solar_coverage_pct=summary['solar_coverage_pct']))
  windows={}
  for count in (7,30):
   values=[r for r in rows if date.fromisoformat(r['day'])>=today-timedelta(days=count)];groups=[]
   for lead in sorted({r['horizon'] for r in values}):
    items=[r for r in values if r['horizon']==lead];errors=[abs(r['error_pct']) for r in items if r['error_pct'] is not None]
    groups.append(dict(horizon=lead,samples=len(items),mae_kwh=statistics.mean(abs(r['error_kwh']) for r in items),bias_kwh=statistics.mean(r['error_kwh'] for r in items),mae_pct=statistics.mean(errors) if errors else None))
   windows[str(count)]=groups
  return dict(kind='forecast_stats',anchor=today.isoformat(),windows=windows,rows=rows,excluded=excluded,note='Плюс: прогноз завищений; мінус: занижений. Лише видані до початку доби прогнози та ≥95% сонячного покриття. Статистика накопичується з реальних збережених прогнозів.')
 def day_analysis(self,device,reader,day,source='Auto',cancelled=lambda:False,basis=None):
  weather=self.weather(device);lat,lon=self.location(weather);actual=basis if basis and basis.get('day')==day.isoformat() and basis.get('coordinates')==[lat,lon] else _day(reader,day,lat,lon,cancelled,source);archive=weather.get('forecast_archive',{}).get(day.isoformat(),{});prediction=predictions(archive).get('1') or archive
  complete=day<datetime.now(ZONE).date();valid=complete and actual['solar_coverage_pct']>=95 and valid_issue(day.isoformat(),prediction,1)
  expected=prediction.get('expected_kwh');error=expected-actual['pv_kwh'] if valid else None
  return dict(forecast=prediction or None,forecast_actual_kwh=actual['pv_kwh'],solar_coverage_pct=actual['solar_coverage_pct'],forecast_error_kwh=error,forecast_error_pct=100*error/expected if error is not None and expected>0 else None,forecast_note='Прогноз − факт; плюс означає завищення. Похибка лише для завершеної доби з ≥95% сонячного покриття і прогнозом напередодні.',forecast_analysis_version=2)
 def attach_day(self,device,reader,result,day,source,cancelled):
  try:result.update(self.day_analysis(device,reader,day,source,cancelled,result.pop('forecast_basis',None)))
  except ValueError as error:
   if cancelled():raise
   result.update(forecast_note=str(error),forecast_analysis_version=2)
  if result.get('kind')!='forecast':return result
  from .forecast_comparison import comparison
  matched=comparison(day,result.pop('hourly_actual',[]),result.get('forecast'))
  result['comparison']=matched;result['graph']=matched.pop('graph')
  result.setdefault('diagnostics',{})['forecast_display']=matched['diagnostics']
  result.update(forecast_note=matched['note'],forecast_analysis_version=4)
  # Forecast/fact is a focused comparison, not a duplicate daily events report.
  for key in ('events','outages','statistics','summary','house_meter'):
   result.pop(key,None)
  return result
 def live(self,device,reader,cancelled=lambda:False):
  now=time.time();today=datetime.fromtimestamp(now,ZONE).date();weather=self.weather(device);lat,lon=self.location(weather);hourly=weather.get('latest_hourly')
  try:issued=stamp(weather['updated']).timestamp();fresh=bool(hourly) and 0<=now-issued<=43200
  except (KeyError,TypeError,ValueError):fresh=False
  actual,actual_at,fact_cached=self._live_actual(device,reader,today,lat,lon,cancelled,now);elapsed=sum(max(0,min(actual_at,b)-a) for a,b in active_windows(today,lat,lon));coverage=min(100,100*actual['solar_covered_s']/elapsed) if elapsed>0 else 100.
  remaining=fraction_remaining(hourly or [],today.isoformat(),actual_at);total=actual['pv_kwh']+remaining if coverage>=95 and actual['records']>=2 else None
  from .forecast_comparison import comparison
  matched=comparison(today,actual.get('hourly_points',[]),dict(issued_at=weather.get('updated'),hourly=hourly or []) if fresh else None,datetime.fromtimestamp(actual_at,ZONE))
  return dict(kind='forecast_live',actual_as_of=datetime.fromtimestamp(actual_at,ZONE).isoformat(),actual_age_s=max(0,now-actual_at),fact_cache_hit=fact_cached,available=fresh,day=today.isoformat(),weather_updated=weather.get('updated'),actual_kwh=actual['pv_kwh'] if actual['records']>=2 else None,solar_coverage_pct=coverage,remaining_kwh=remaining if fresh else None,expected_total_kwh=total if fresh else None,original_kwh=(weather.get('forecast_archive',{}).get(today.isoformat()) or weather.get('generation_by_day',{}).get(today.isoformat(),{})).get('expected_kwh'),note='Факт + залишок за останньою погодою; початковий прогноз не змінюється. Неповний факт не екстраполюється.' if fresh else 'Оновіть погодинний прогноз; наявний факт збережено.',hourly=[],graph=matched['graph'])
 def _load_cache(self,device,reader):
  path=Path(reader.cfg.root_dir)/'Data/ForecastSummaries'/((reader.cfg.history_device_id or 'inverter-1')+'.json')
  try:rows=json.loads(path.read_text('utf-8'))
  except (OSError,ValueError):return []
  today=datetime.now(ZONE).date();key=model_key(reader);values=[]
  for day,row in rows.items():
   if not today-timedelta(days=14)<=date.fromisoformat(day)<today or row.get('model_key')!=key:continue
   summary=row.get('summary',{});covered=summary.get('load_tariff_covered_s',{});duration=summary.get('load_tariff_duration_s',{})
   if all(duration.get(k,0)>0 and covered.get(k,0)>=.95*duration[k] for k in ('day','night')):values.append(summary)
  return sorted(values,key=lambda r:r['day'])[-7:]
 def plan(self,device,reader,cancelled=lambda:False,refresh=False):
  from .drivers.parameter_library import current_value,RULES
  state=self.runtime.device_snapshot(self.runtime.device(device));estimate=state.get('battery',{}).get('estimate',{});cfg=self.runtime.insights.config(device);night=self.runtime.night_charge.config(device,'')
  def unavailable(message):return dict(kind='charge_plan',available=False,note=message,fallback='Фіксований нічний струм; адаптивна автоматика не застосовується')
  if state.get('stale',True) or (estimate.get('confidence')!='measured' or not estimate.get('source','').startswith('bms.')) or not number(estimate.get('remaining_kwh')):return unavailable('Немає актуального SOC БМС або заданої ємності АКБ')
  weather=self.weather(device)
  if not weather.get('calibration',{}).get('sample_count',0)>=6:return unavailable('Потрібен навчений прогноз')
  if not weather.get('updated') or not 0<=time.time()-stamp(weather['updated']).timestamp()<=43200:return unavailable('Оновіть прогноз: погоді понад12год')
  lat,lon=self.location(weather)
  if refresh:summaries(reader,lat,lon,maximum=14,cancelled=cancelled,parallel=False)
  history=self._load_cache(device,reader)
  if len(history)<3:return unavailable('Потрібно щонайменше3доби споживання з ≥95% покриттям денного й нічного тарифних періодів')
  now=datetime.now(ZONE);morning=now.replace(hour=7,minute=0,second=0,microsecond=0)
  if now.hour>=7:morning+=timedelta(days=1)
  start=now if now.hour>=23 or now.hour<7 else now.replace(hour=23,minute=0,second=0,microsecond=0)
  hours=(morning.timestamp()-start.timestamp())/3600;day=morning.date().isoformat()
  generation=(weather.get('latest_generation_by_day') or weather.get('generation_by_day',{})).get(day)
  if not generation or not number(generation.get('low_kwh')):return unavailable('Немає прогнозу на день після нічного заряду')
  day_w=statistics.median(r['load_tariff_kwh']['day']*3600000/r['load_tariff_covered_s']['day'] for r in history)
  night_w=statistics.median(r['load_tariff_kwh']['night']*3600000/r['load_tariff_covered_s']['night'] for r in history)
  eta=cfg.get('efficiency',.9);charge_eta=cfg.get('charge_efficiency',.95);cap=cfg['usable_kwh'];reserve=cap*cfg.get('reserve_pct',20)/100
  solar=generation['low_kwh'];hourly=[r for r in weather.get('latest_hourly',weather.get('hourly',[])) if r.get('day')==day]
  if hourly:
   total=sum(r['kwh'] for r in hourly);day_solar=fraction_remaining(hourly,day,float('-inf'),7,23)
   solar*=day_solar/total if total>0 else 0
  self_w=reader.cfg.inverter_self_consumption_w
  day_need=day_w*16/1000/eta+self_w*16/1000;target=min(cap,max(reserve,reserve+day_need-solar*charge_eta));remaining=estimate['remaining_kwh']
  if 7<=now.hour<23:
   latest=weather.get('latest_hourly')
   if not latest:return unavailable('Оновіть погоду для оцінки залишку генерації до початку ночі')
   until_start=(start.timestamp()-now.timestamp())/3600;pv_left=fraction_remaining(latest,now.date().isoformat(),now.timestamp());today_model=weather.get('latest_generation_by_day',{}).get(now.date().isoformat(),{})
   ratio=today_model.get('low_kwh',0)/max(.001,today_model.get('expected_kwh',0));remaining=max(0,min(cap,remaining+pv_left*ratio*charge_eta-day_w*until_start/1000/eta-self_w*until_start/1000))
  share=night.get('night_battery_share_pct',100)/100;night_need=(night_w/eta+self_w)*hours/1000*share;needed=max(0,target+night_need-remaining)
  params=state.get('parameters',{})
  if params.get('stale',True):return unavailable('Очікування свіжих лімітів заряду інвертора')
  total_limit=float(current_value('charging.total_current_limit',params['raw']));voltage=state.get('data',{}).get('battery_v')
  if not number(voltage) or voltage<=0:return unavailable('Немає актуальної напруги АКБ')
  choices=[v for v in RULES['charging.utility_current_limit']['values'] if v<=min(total_limit,night['night_a'])]
  if not choices:return unavailable('Немає підтримуваного струму в установлених межах')
  required=needed*1000/max(.001,voltage*hours*charge_eta);current=next((v for v in choices if v>=required),choices[-1]);can_add=current*voltage*hours*charge_eta/1000
  return dict(kind='charge_plan',available=True,start=start.isoformat(),end=morning.isoformat(),target_day=day,hours=hours,history_days=len(history),day_load_kwh=day_w*16/1000,night_load_kwh=night_w*hours/1000,night_battery_share_pct=share*100,pv_low_kwh=solar,estimated_start_kwh=remaining,target_kwh=target,target_pct=100*target/cap,needed_kwh=needed,recommended_a=current,required_a=required,current_cap_a=min(total_limit,night['night_a']),can_reach_target=can_add>=needed,forecast_updated=weather['updated'],note='Рекомендація приблизна. Нічне навантаження враховане у заданій частці від АКБ; мінімальний підтримуваний ліміт2А не вимикає заряд. Фізичні ліміти інвертора не підвищуються.')
