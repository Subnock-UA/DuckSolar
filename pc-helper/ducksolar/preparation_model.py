"""Typed PC/Android calculation model. Never silently upgrade an old model."""
import math
NUMERIC={'pv_correction_factor','inverter_self_consumption_w','max_integration_gap_s','poll_interval_s','grid_present_min_v','grid_present_max_v','grid_present_min_hz','grid_present_max_hz'}
EXTRA={'generation_basis','pv_night_noise_w','latitude','longitude'}
def model_types(model):
 return {k:'null' if v is None else 'str' if isinstance(v,str) else 'float' if isinstance(v,float) else 'int' for k,v in model.items()}
def decode_model(model,types=None):
 if not isinstance(model,dict) or set(model) not in (NUMERIC,NUMERIC|EXTRA):raise ValueError('Unsupported preparation model keys')
 types=types or model_types(model)
 if set(types)!=set(model):raise ValueError('Invalid model type metadata')
 result={}
 for key,value in model.items():
  kind=types[key]
  if key=='generation_basis':
   # b1.0.8 inventory incorrectly labelled this known string as int.
   if value!='pv.accounted.v2' or kind not in ('str','int'):raise ValueError('Unsupported generation model')
   result[key]=value;continue
  if key in ('latitude','longitude') and value is None:
   if kind not in ('null','int'):raise ValueError('Invalid coordinate metadata')
   result[key]=None;continue
  if kind not in ('float','int') or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Invalid numeric model: '+key)
  if kind=='int' and value!=int(value):raise ValueError('Invalid integer model: '+key)
  result[key]=float(value) if kind=='float' else int(value)
 if any(result[k]<=0 for k in ('pv_correction_factor','max_integration_gap_s','poll_interval_s')):raise ValueError('Invalid positive model range')
 if not 0<result['pv_correction_factor']<=10 or result['max_integration_gap_s']>86400 or result['poll_interval_s']>3600:raise ValueError('Invalid model range')
 for key,limit in [('latitude',90),('longitude',180)]:
  if result.get(key) is not None and abs(result[key])>limit:raise ValueError('Invalid coordinate range')
 if result.get('pv_night_noise_w',0)<0:raise ValueError('Invalid PV noise threshold')
 return result
def apply_model(cfg,model,types=None):
 value=decode_model(model,types)
 for key,item in value.items():
  if key=='generation_basis':continue
  setattr(cfg,{'latitude':'weather_latitude','longitude':'weather_longitude'}.get(key,key),item)
 return value
