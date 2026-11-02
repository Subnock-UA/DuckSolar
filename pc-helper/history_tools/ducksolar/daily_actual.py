"""Extra full-resolution aggregates collected with the energy checkpoint."""
import math
from datetime import datetime,timedelta
from .energy_accounting import ZONE,stamp
from .solar_time import active_windows

def location(reader):
 value=getattr(reader,'_forecast_location',None)
 if value is None:value=(getattr(reader.cfg,'weather_latitude',None),getattr(reader.cfg,'weather_longitude',None))
 if not isinstance(value,(tuple,list)) or len(value)!=2 or not all(type(x) in (int,float) and math.isfinite(x) for x in value):return None
 return list(value)
def empty(day,coordinates):
 start=datetime.combine(day,datetime.min.time(),ZONE);end=start+timedelta(days=1)
 windows=active_windows(day,*coordinates)
 groups={'day':[(start.replace(hour=7).timestamp(),start.replace(hour=23).timestamp())],'night':[(start.timestamp(),start.replace(hour=7).timestamp()),(start.replace(hour=23).timestamp(),end.timestamp())]}
 return dict(day=day.isoformat(),coordinates=coordinates,pv_kwh=0.,solar_active_s=sum(b-a for a,b in windows),solar_covered_s=0.,solar_coverage_pct=0.,coverage_pct=0,load_tariff_kwh={k:0. for k in groups},load_tariff_covered_s={k:0. for k in groups},load_tariff_duration_s={k:sum(b-a for a,b in v) for k,v in groups.items()},records=0),windows,groups
def add(value,rows,windows,groups,cfg,cancelled):
 from .cpu_energy import forecast
 result=forecast(rows,windows,groups,cfg.max_integration_gap_s,None,cancelled)
 if result is None:
  pv=covered=0.;load={k:0. for k in groups};coverage={k:0. for k in groups}
  def valid(v):return type(v) in (int,float) and math.isfinite(v) and v>=0
  for i,(a,b) in enumerate(zip(rows,rows[1:])):
   if i%256==0 and cancelled():raise InterruptedError('Скасовано')
   ta,tb=stamp(a['timestamp']).timestamp(),stamp(b['timestamp']).timestamp();dt=tb-ta
   if not 0<dt<=cfg.max_integration_gap_s:continue
   def integrate(key,x,y):
    left=a[key]+(b[key]-a[key])*(x-ta)/dt;right=a[key]+(b[key]-a[key])*(y-ta)/dt
    return (left+right)*.5*(y-x)/3600000
   if valid(a.get('pv_w')) and valid(b.get('pv_w')):
    pv+=integrate('pv_w',ta,tb);covered+=sum(max(0,min(tb,y)-max(ta,x)) for x,y in windows)
   if valid(a.get('output_w')) and valid(b.get('output_w')):
    for key,ranges in groups.items():
     for x,y in ranges:
      left,right=max(ta,x),min(tb,y)
      if right>left:load[key]+=integrate('output_w',left,right);coverage[key]+=right-left
  result=pv,covered,load,coverage
 pv,covered,load,coverage=result
 value['pv_kwh']+=pv;value['solar_covered_s']+=covered
 for key in groups:value['load_tariff_kwh'][key]+=load[key];value['load_tariff_covered_s'][key]+=coverage[key]
 value['solar_coverage_pct']=min(100,100*value['solar_covered_s']/value['solar_active_s']) if value['solar_active_s']>0 else 0
