"""Human duration formatting; no changes to transport, timestamps or stored values."""
import math

FACTORS={'h':3600,'hr':3600,'hours':3600,'год':3600,'год.':3600,
 'min':60,'minutes':60,'хв':60,'хв.':60,'s':1,'sec':1,'seconds':1,'с':1,'с.':1,'ms':.001,'мс':.001}

def duration(seconds):
 if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<=seconds<=1e12:return '—'
 if seconds<=1800:
  minutes,remainder=divmod(math.floor(seconds+.5),60)
  return f'{remainder} с.' if not minutes else f'{minutes} хв.'+(f' {remainder} с.' if remainder else '')
 hours,minutes=divmod(math.floor(seconds/60+.5),60)
 return f'{hours} год. {minutes} хв.' if hours else f'{minutes} хв.'

def format_unit(value,unit):
 factor=FACTORS.get(unit.strip().lower()) if isinstance(unit,str) else None
 if factor is None:return None
 return duration(value*factor) if isinstance(value,(int,float)) and not isinstance(value,bool) else '—'

def field_unit(key):
 if key in ('time_s','timestamp_s','time_ms','timestamp_ms'):return None
 if key.endswith(('_hours','_h')) or key=='hours':return 'h'
 if key.endswith(('_seconds','_s')) or key=='seconds':return 's'
 if key.endswith('_ms'):return 'ms'
 return None
