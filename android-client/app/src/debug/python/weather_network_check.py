import json
from pathlib import Path
from ducksolar import weather_client as w
def run(cache):
 root=Path(cache)/'weather-network-check'
 w.settings(root,'fixture',dict(location='Київ',latitude=45.35,longitude=28.83,installed_kw=6,tilt_deg=30,azimuth_deg=180))
 data=w.engine(root,'fixture').fetch_10_day()
 assert len(data['days'])==10 and len({d['date'] for d in data['days']})==10
 assert len(data['generation_by_day'])>=9
 return json.dumps(dict(passed=True,days=len(data['days']),pv_days=len(data['generation_by_day']),timezone=data['timezone']))
