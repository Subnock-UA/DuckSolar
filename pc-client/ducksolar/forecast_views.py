"""Persist forecasts as issued; evaluate against future actuals without hindsight."""
import json,math
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo

def enrich(result,weather,profile,path):
 zone=ZoneInfo(result.get('timezone') or 'Europe/Kyiv');hourly=weather.get('hourly',{});groups={}
 for stamp,value in zip(hourly.get('time',[]),hourly.get('global_tilted_irradiance',[])):
  try:
   at=datetime.fromisoformat(stamp) if isinstance(stamp,str) else datetime.fromtimestamp(stamp,zone)
   if at.tzinfo is None:at=at.replace(tzinfo=zone)
   if not isinstance(value,(int,float)) or not math.isfinite(value):continue
   at=datetime.fromtimestamp(at.timestamp()-3600,zone)
   groups.setdefault(at.date().isoformat(),[]).append((at,max(0.,float(value))))
  except (ValueError,TypeError):continue
 rows=[]
 for day,values in groups.items():
  prediction=result.get('generation_by_day',{}).get(day,{}).get('expected_kwh');total=sum(v for _,v in values)
  if not isinstance(prediction,(int,float)) or total<=0:continue
  for at,radiation in values:
   kwh=min(profile['installed_kw'],prediction*radiation/total)
   rows.append(dict(time=at.isoformat(),day=day,kwh=kwh,power_w=kwh*1000))
 for day in groups:
  item=result.get('generation_by_day',{}).get(day)
  selected=[row for row in rows if row['day']==day]
  if item and selected:
   item['unconstrained_kwh']=item['expected_kwh'];item['expected_kwh']=sum(row['kwh'] for row in selected)
 result['hourly']=sorted(rows,key=lambda x:x['time']);result['hourly_note']='Погодинна оцінка за сонячною радіацією; не є вимірюванням. Межа — встановлена потужність панелей.'
 try:archive=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):archive={}
 scope=dict(geometry_key=result.get('geometry_key'),latitude=result.get('location',{}).get('latitude'),longitude=result.get('location',{}).get('longitude'))
 archive={day:row for day,row in archive.items() if row.get('scope')==scope}
 issued=result['updated'];issue_dt=datetime.fromisoformat(issued)
 if issue_dt.tzinfo is None:issue_dt=issue_dt.replace(tzinfo=zone)
 for day,prediction in result.get('generation_by_day',{}).items():
  # Freeze before the target day starts; same-day forecasts remain identifiable as such.
  old=archive.get(day);lead=(datetime.fromisoformat(day).date()-issue_dt.date()).days;new=dict(scope=scope,issued_at=issued,expected_kwh=prediction['expected_kwh'],hourly=[r for r in rows if r['day']==day],horizon_days=lead,basis='day_ahead' if lead==1 else 'ahead' if lead>1 else 'same_day')
  if old is None or new['basis']=='day_ahead' and old.get('basis')!='day_ahead':
   if old is not None:new['previous_issued_forecast']=old
   archive[day]=new
 archive={k:archive[k] for k in sorted(archive)[-90:]};path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(archive,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
 result['forecast_archive']=archive
 return result
