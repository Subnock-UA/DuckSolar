"""Show observed energy independently of forecast eligibility; score matched hours only."""
import math
from datetime import datetime,timedelta
from .energy_accounting import ZONE,stamp

def number(v):return type(v) in (int,float) and math.isfinite(v)

def _rows(rows,key,start,end):
 result={}
 for row in rows:
  try:at=stamp(row[key]).timestamp()
  except (KeyError,TypeError,ValueError):continue
  if start<=at<end:result[at]=row
 return result

def comparison(day,points,prediction,now=None):
 now=stamp(now or datetime.now(ZONE));start=datetime.combine(day,datetime.min.time(),ZONE)
 end=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE)
 a,b=start.timestamp(),end.timestamp();as_of=max(a,min(b,now.timestamp()))
 cutoff=max(a,min(b,now.replace(minute=0,second=0,microsecond=0).timestamp()))
 try:issued=stamp(prediction['issued_at']) if prediction else None
 except (KeyError,TypeError,ValueError):issued=None
 fair_start=a
 if issued is not None and issued.timestamp()>a:
  boundary=issued.replace(minute=0,second=0,microsecond=0).timestamp()
  fair_start=boundary+(3600 if issued.timestamp()>boundary else 0)
 actual=_rows(points,'label',a,b)
 predicted=_rows((prediction or {}).get('hourly',[]),'time',a,b)
 graph=[];expected=0.;observed=0.;scored_actual=0.;hours=0;missing=0;eligible=0;observed_hours=0;partial_hours=0
 for at in sorted(actual.keys()|predicted.keys()):
  p=predicted.get(at,{});q=actual.get(at,{})
  energy=p.get('kwh')
  if not number(energy) and number(p.get('power_w')):energy=p['power_w']/1000
  if not number(energy) or energy<0:energy=None
  value=q.get('pv_w');covered=q.get('coverage_seconds',{}).get('pv_w',0)
  elapsed=max(0,min(3600,as_of-at))
  # A known partial sum remains a partial sum; never extrapolate or replace gaps by zero.
  known=number(value) and value>=0 and number(covered) and 0<covered<=elapsed+1 and elapsed>0
  partial=known and (elapsed<3600 or covered<3599)
  comparable=energy is not None and issued is not None and at>=fair_start and at+3600<=cutoff
  good=comparable and known and covered>=3420
  row=dict(x=len(graph),label=q.get('label') or p.get('time'),forecast=energy,actual=value if known else None,
           coverage_seconds=dict(actual=covered if known else 0),actual_partial=bool(partial))
  graph.append(row)
  if known:observed+=value;observed_hours+=1;partial_hours+=int(partial)
  if comparable:
   expected+=energy;eligible+=1
   if good:scored_actual+=value;hours+=1
   else:missing+=1
 valid=eligible>0 and missing==0
 error=expected-scored_actual if valid else None
 note='Факт показано за всіма наявними записами незалежно від часу видання прогнозу. Неповні години не доповнюються й не прирівнюються до нуля. Похибка: прогноз − факт; лише за завершені години після видання прогнозу з ≥95% покриттям кожної години.'
 if not predicted:note='Немає погодинного прогнозу на цю дату. '+note
 return dict(day=day.isoformat(),period_end=datetime.fromtimestamp(cutoff,ZONE).isoformat(),
  actual_as_of=datetime.fromtimestamp(as_of,ZONE).isoformat(),complete=as_of>=b,
  forecast_day_kwh=(prediction or {}).get('expected_kwh'),forecast_period_kwh=expected if eligible else None,
  actual_period_kwh=scored_actual if hours else None,observed_kwh=observed if observed_hours else None,
  observed_hours=observed_hours,partial_hours=partial_hours,error_kwh=error,
  error_pct=100*error/expected if error is not None and expected>0 else None,
  covered_hours=hours,expected_hours=eligible,missing_hours=missing,issued_at=(prediction or {}).get('issued_at'),note=note,
  diagnostics=dict(version=4,input_actual_hours=len(actual),forecast_hours=len(predicted),visible_actual_hours=observed_hours,partial_actual_hours=partial_hours,comparable_hours=eligible),
  graph=dict(kind='bars',mode='energy',suppress_summary=True,points=graph,note=note,
    fields=[dict(key='forecast',label='Прогноз',unit='кВт·год'),dict(key='actual',label='Факт (наявні дані)',unit='кВт·год')]))
