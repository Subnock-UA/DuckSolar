import time
import weather_fixture
from ducksolar import weather_client as w
_fetch=None
def install(cache):
 global _fetch
 weather_fixture.install(cache)
 _fetch=w.Forecast.fetch_10_day
 def blocked(self,location_name=None,reader=None):
  while True:w.check();time.sleep(.02)
 w.Forecast.fetch_10_day=blocked
def allow():
 w.Forecast.fetch_10_day=_fetch
def restore():
 allow();weather_fixture.restore()
