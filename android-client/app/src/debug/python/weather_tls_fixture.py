import json,time,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone
import android_client as c
import push_client_fixture
import weather_fixture
from ducksolar import weather_client as w
_saved=None
def install(root,cache,url,pin,token):
 global _saved
 push_client_fixture.install(root,url,pin,token)
 c.resume()
 weather_fixture.install(cache)
 # Use the real paired identity for real authenticated server history jobs.
 c.weather_identity=_identity=lambda:c.connection_profile()+'|'+str(c._cfg.get('serial',''))
 _saved=w.History.__init__,w.Forecast._get_json
 original_init=w.History.__init__;original_fetch=w.Forecast._get_json
 def init(self,sync,path):
  def gated(known):
   if known and not getattr(w,'_tls_allow',False):
    while True:w.check();time.sleep(.02)
   return sync(known)
  original_init(self,gated,path)
 def fetch(self,host,path,params):
  if 'previous-runs' not in host:return original_fetch(self,host,path,params)
  start=datetime.fromisoformat(params['start_date']).replace(tzinfo=timezone.utc)
  end=datetime.fromisoformat(params['end_date']).replace(tzinfo=timezone.utc)+timedelta(days=1)
  count=int((end-start).total_seconds()/3600)
  return dict(timezone='UTC',hourly={'time':[int((start+timedelta(hours=i)).timestamp()) for i in range(count+1)],'global_tilted_irradiance_previous_day1':[100]*(count+1)})
 w.History.__init__=init;w.Forecast._get_json=fetch;w._tls_allow=False
 w.settings(c._root,c.weather_identity(),dict(location='Київ',latitude=45.35,longitude=28.83,installed_kw=6,tilt_deg=30,azimuth_deg=180))
def allow():w._tls_allow=True
def result():
 obj=w.status(c._root,c.weather_identity())
 return json.dumps(obj,ensure_ascii=False)
def restore():
 if _saved:w.History.__init__,w.Forecast._get_json=_saved
 weather_fixture.restore();push_client_fixture.restore()
