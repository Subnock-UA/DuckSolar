"""Approximate geometric elevation, NOAA fractional-year equations (UTC)."""
import math,calendar
from datetime import datetime,timezone,timedelta
from functools import lru_cache

def elevation(at,latitude,longitude):
 t=at.astimezone(timezone.utc);h=t.hour+t.minute/60+t.second/3600;g=2*math.pi/(366 if calendar.isleap(t.year) else 365)*(t.timetuple().tm_yday-1+(h-12)/24)
 eq=229.18*(.000075+.001868*math.cos(g)-.032077*math.sin(g)-.014615*math.cos(2*g)-.040849*math.sin(2*g))
 dec=.006918-.399912*math.cos(g)+.070257*math.sin(g)-.006758*math.cos(2*g)+.000907*math.sin(2*g)-.002697*math.cos(3*g)+.00148*math.sin(3*g)
 angle=math.radians(((h*60+eq+4*longitude)%1440)/4-180);lat=math.radians(latitude)
 return math.degrees(math.asin(max(-1,min(1,math.sin(lat)*math.sin(dec)+math.cos(lat)*math.cos(dec)*math.cos(angle)))))
@lru_cache(maxsize=800)
def active_windows(day,latitude,longitude):
 from .energy_accounting import ZONE
 start=datetime.combine(day,datetime.min.time(),ZONE).timestamp();end=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE).timestamp();windows=[];opened=None;t=start
 while t<end:
  active=elevation(datetime.fromtimestamp(t+30,timezone.utc),latitude,longitude)>=-.833
  if active and opened is None:opened=t
  if not active and opened is not None:windows.append((opened,t));opened=None
  t+=60
 if opened is not None:windows.append((opened,end))
 return tuple(windows)
