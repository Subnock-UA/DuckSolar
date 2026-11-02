"""Live derived metrics use source freshness, never a stale result's metadata."""
import math
from datetime import datetime,timezone

def usable(item,unit=None):
 if not isinstance(item,dict) or item.get('stale') or item.get('quality','good') not in ('good','estimated'):return False
 value=item.get('value')
 return type(value) in (int,float) and math.isfinite(value) and value>=0 and (unit is None or item.get('unit')==unit) and item.get('age_s',0)<=item.get('valid_for_s',float('inf'))

def calculated(value,unit,inputs,source,online=True):
 ready=online and all(usable(x) for x in inputs) and type(value) in (int,float) and math.isfinite(value) and value>=0
 result=dict(value=value if ready else None,unit=unit,quality='good' if ready else 'unavailable',source=source,confidence='estimated',measurement_kind='estimated',stale=not ready)
 if ready:
  stamps=[x.get('timestamp') for x in inputs if x.get('timestamp')]
  result.update(input_timestamps=stamps,age_s=max((x.get('age_s',0) for x in inputs),default=0),valid_for_s=max((x.get('age_s',0) for x in inputs),default=0)+min((max(0,x.get('valid_for_s',15)-x.get('age_s',0)) for x in inputs),default=15))
  if stamps:result['timestamp']=min(stamps,key=lambda s:datetime.fromisoformat(s).timestamp())
 else:result['unavailable_reason']='Немає свіжих вихідних даних для розрахунку'
 return result

def pv(metrics,corrected,online=True):
 power=metrics.get('pv.total_power',{});voltage=metrics.get('pv.inputs.aggregate.voltage',{})
 if corrected is not None:
  raw=dict(power)
  metrics['pv.raw_power']=raw
  metrics['pv.total_power']=calculated(corrected,'W',[power],'pv.accounted.v2',online)
  metrics['pv.corrected_power']=dict(metrics['pv.total_power'])
 power=metrics.get('pv.total_power',{})
 if usable(power,'W') and usable(voltage,'V') and voltage['value']>0:
  metrics['pv.inputs.aggregate.current']=calculated(power['value']/voltage['value'],'A',[power,voltage],'pv.accounted.v2.P/U',online)
 elif not usable(metrics.get('pv.inputs.aggregate.current'),'A'):
  metrics['pv.inputs.aggregate.current']=calculated(None,'A',[power,voltage],'pv.accounted.v2.P/U',False)
 return metrics
