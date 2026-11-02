"""Server wall time advanced exclusively by monotonic elapsed time on Client."""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import threading
import time
_lock=threading.RLock()
_wall=None
_instant=None
_tick=None
_zone=timezone.utc

def update(wall,utc=None):
    global _wall,_tick,_zone,_instant
    stamp=datetime.fromisoformat(wall) if isinstance(wall,str) else wall
    if not isinstance(stamp,datetime):return
    with _lock:
        _wall=stamp.replace(tzinfo=None);_tick=time.monotonic()
        if utc:
            universal=datetime.fromisoformat(utc).astimezone(timezone.utc).replace(tzinfo=None)
            offset=round((stamp.replace(tzinfo=None)-universal).total_seconds()/60)*60
            if abs(offset)<86400:
                kyiv=ZoneInfo('Europe/Kyiv')
                _zone=kyiv if datetime.fromisoformat(utc).astimezone(kyiv).utcoffset().total_seconds()==offset else timezone(timedelta(seconds=offset))
        elif stamp.tzinfo is not None:_zone=stamp.tzinfo
        _instant=stamp.replace(tzinfo=_zone) if stamp.tzinfo is None else stamp.astimezone(_zone)

def now():
    with _lock:
        if _instant is not None:return datetime.fromtimestamp(_instant.timestamp()+max(0,time.monotonic()-_tick),_zone).replace(tzinfo=None)
    # Only the pre-login shell can run before the first Server envelope.
    return datetime.now()
def today():return now().date()
def display_datetime(value):
    stamp=datetime.fromisoformat(value) if isinstance(value,str) else value
    with _lock:zone=_zone
    return stamp.astimezone(zone) if stamp.tzinfo else stamp
