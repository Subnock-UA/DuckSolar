"""Authoritative reading intervals; calendar allocations never replace exact deltas."""
from datetime import datetime,timedelta
from .energy_accounting import stamp,seconds,ZONE

def report(readings,start,end):
 start,end=stamp(start),stamp(end);now=datetime.now(ZONE);ordered=sorted(readings,key=lambda r:stamp(r['reading_date']).timestamp());pairs=[]
 for a,b in zip(ordered,ordered[1:]):
  if a['meter_id']!=b['meter_id']:continue
  x,y=stamp(a['reading_date']),stamp(b['reading_date'])
  if y.timestamp()<=x.timestamp():continue
  values={k:float(b[k])-float(a[k]) for k in ('import_day','import_night','export_day','export_night')}
  if any(v<0 for v in values.values()):continue
  pairs.append(dict(start=x.isoformat(),end=y.isoformat(),source='meter',meter_id=a['meter_id'],reading_ids=[a.get('id'),b.get('id')],**values,**{'import':values['import_day']+values['import_night'],'export':values['export_day']+values['export_night']}))
 def near(target):
  choices=[stamp(x['reading_date']) for x in ordered if -3<=(stamp(x['reading_date']).date()-target.date()).days<=2 and stamp(x['reading_date']).timestamp()<=now.timestamp()]
  return min(choices,key=lambda t:(abs((t.date()-target.date()).days),t.timestamp())) if choices else None
 left,right=start,end
 if start.day==1 and start.hour==0 and seconds(start,end)>=20*86400:
  left=near(start) or start
  if end.day==1 and end.hour==0:right=near(end) or end
  else:
   before=[stamp(x['reading_date']) for x in ordered if left.timestamp()<stamp(x['reading_date']).timestamp()<=end.timestamp()]
   right=max(before,key=lambda t:t.timestamp()) if before else end
 selected=[p for p in pairs if stamp(p['start']).timestamp()>=left.timestamp() and stamp(p['end']).timestamp()<=right.timestamp()]
 refs=[p for p in pairs if stamp(p['start']).timestamp()<end.timestamp() and stamp(p['end']).timestamp()>start.timestamp()]
 allocated=[]
 for p in refs:
  a,b=stamp(p['start']),stamp(p['end']);x=max(a,start,key=lambda t:t.timestamp());y=min(b,end,key=lambda t:t.timestamp());fraction=seconds(x,y)/seconds(a,b)
  allocated.append(dict(start=x.isoformat(),end=y.isoformat(),source='meter' if fraction==1 else 'meter_estimated_boundary',**{'import':p['import']*fraction,'export':p['export']*fraction}))
 sums={key:sum(p[key] for p in selected) if selected else None for key in ('import','export')}
 exact_seconds=sum(seconds(p['start'],p['end']) for p in selected)
 return dict(boundary='house_input',contract='meter.intervals.v2',source='meter',authoritative=True,segments=selected,reference_intervals=refs,import_kwh=sums['import'],export_kwh=sums['export'],saldo_kwh=sums['export']-sums['import'] if selected else None,period_start=selected[0]['start'] if selected else None,period_end=selected[-1]['end'] if selected else None,requested_start=start.isoformat(),requested_end=end.isoformat(),coverage_pct=min(100,exact_seconds/max(1,seconds(start,end))*100),calendar_estimate=dict(segments=allocated,import_kwh=sum(p['import'] for p in allocated) if allocated else None,export_kwh=sum(p['export'] for p in allocated) if allocated else None,source='temporal_allocation'),note='Точні суми лише за фактичні інтервали показників будинку. Розподіл по днях/годинах — оцінка; інвертор має окрему межу обліку.')
