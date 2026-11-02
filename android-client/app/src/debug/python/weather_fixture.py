import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import android_client as c
from ducksolar import weather_client as w
from ducksolar.clock import today
_saved=None
fail=False
def install(cache):
 global _saved,fail
 fail=False
 _saved=(c.weather_identity,w.folder,w.Forecast._get_json,w._job)
 c.weather_identity=lambda:'weather-ui-fixture'
 import uuid
 test_folder=Path(cache)/('weather-ui-fixture-'+uuid.uuid4().hex)
 w.folder=lambda root,identity:test_folder
 w._job={'state':'idle'}
 w.settings(c._root,c.weather_identity(),dict(location='Київ',latitude=45.35,longitude=28.83,installed_kw=6,tilt_deg=30,azimuth_deg=180))
 def fetch(self,host,path,params):
  import threading
  assert threading.current_thread() is not threading.main_thread()
  if fail:raise ConnectionError('Тест: мережа недоступна')
  start=datetime.combine(today(),datetime.min.time(),timezone.utc)
  stamps=[int((start+timedelta(hours=i)).timestamp()) for i in range(24*11+1)]
  days=[int((start+timedelta(days=i)).timestamp()) for i in range(11)]
  return dict(timezone='UTC',hourly=dict(time=stamps,global_tilted_irradiance=[100]*len(stamps),cloud_cover=[25]*len(stamps)),daily=dict(time=days,weather_code=[2]*11,temperature_2m_max=[21]*11,temperature_2m_min=[12]*11,precipitation_probability_max=[10]*11,precipitation_sum=[0]*11,wind_speed_10m_max=[14]*11,sunshine_duration=[21600]*11,sunrise=[d+6*3600 for d in days],sunset=[d+18*3600 for d in days]))
 w.Forecast._get_json=fetch
 return True
def offline():
 global fail
 fail=True
def restore():
 global _saved
 if _saved:c.weather_identity,w.folder,w.Forecast._get_json,w._job=_saved
 _saved=None
