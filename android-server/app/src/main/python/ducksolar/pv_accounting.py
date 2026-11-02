"""One derived PV basis; raw inverter fields remain unchanged in stored CSV."""
import math
from .energy_accounting import stamp
VERSION='pv.accounted.v2'
def number(x):return type(x) in (int,float) and math.isfinite(x)
def power(raw,cfg,at):
 if not number(raw):return None
 value=max(0,raw);threshold=getattr(cfg,'pv_night_noise_w',6.)
 lat=getattr(cfg,'weather_latitude',None);lon=getattr(cfg,'weather_longitude',None)
 if threshold>0 and value<=threshold and number(lat) and number(lon):
  from .solar_time import elevation
  if elevation(stamp(at),lat,lon)<-6:value=0
 return value*cfg.pv_correction_factor

def project(row,cfg):
 raw=row.get('pv_raw_w',row.get('pv_w'));at=row.get('timestamp');value=power(raw,cfg,at) if at is not None else None
 if value is None:return row
 row.update(pv_raw_w=raw,pv_w=value,pv_corrected_w=value,pv_basis=VERSION)
 normalized=row.get('normalized') or {};metrics=normalized.setdefault('metrics',{})
 from .energy_model import calculate_flows,FlowInput
 if all(number(row.get(k)) for k in ('output_w','battery_v','charge_a')):
  flow=calculate_flows(FlowInput(value,row['output_w'],row['battery_v'],row['charge_a'],bool(row.get('grid_available'))),1.,cfg.inverter_self_consumption_w)
  row.update(battery_charge_w=flow.battery_charge_w,estimated_grid_import_w=flow.grid_import_w,estimated_export_w=flow.export_w)
  for direction,v in [('import',flow.grid_import_w),('export',flow.export_w)]:
   key='grid.estimated_'+direction+'_power';metrics[key]={**metrics.get(key,{}),'value':v,'unit':'W','source':'energy_model','quality':'good'}
 from .grid_flow import select_grid_flows,flat_grid_fields
 normalized=select_grid_flows(normalized,stamp(at),owned=True);row.update(flat_grid_fields(normalized,stamp(at)));row['normalized']=normalized
 return row
