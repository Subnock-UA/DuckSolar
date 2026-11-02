"""Bounded, live-only server phone telemetry; no network identifiers."""
import json,threading,time
_lock=threading.Lock()
_value={};_received=None

def update(level,scale,plugged,signal):
 global _value,_received
 value={}
 if type(level) is int and type(scale) is int and scale>0 and 0<=level<=scale:value['battery_percent']=round(100*level/scale,1)
 if type(plugged) is bool:value['external_power']=plugged
 try:
  row=json.loads(signal) if isinstance(signal,str) else signal
  if isinstance(row,dict):
   associated=row.get('association')=='COMPLETED' and not row.get('unavailable')
   if row.get('association') and not row.get('unavailable'):value['wifi_connected']=bool(associated)
   rssi=row.get('rssi_dbm')
   if associated and type(rssi) is int and -126<rssi<0:value['wifi_rssi_dbm']=rssi
 except (TypeError,ValueError):pass
 with _lock:_value=value;_received=time.monotonic()

def snapshot():
 with _lock:
  if _received is None:return dict(available=False)
  age=max(0,time.monotonic()-_received)
  return dict(_value,available=age<=45,age_s=round(age,1))
