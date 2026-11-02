"""Views built on existing period checkpoints; never recalculate N daily balances."""
import json,calendar,sqlite3,time
from contextlib import closing
from pathlib import Path
from datetime import date,datetime,timedelta
from .energy_accounting import ZONE
from .config import app_paths
from .events import EventJournal

FIELDS=('pv_w','output_w','grid_import_w','grid_export_w','saldo')
NAMES={'pv_w':'Генерація','output_w':'Споживання','grid_import_w':'Імпорт','grid_export_w':'Експорт','saldo':'Сальдо'}

def markers(cfg,device,result):
 points=result.get('points',[])
 if not points:return []
 anchor=date.fromisoformat(result['anchor']);period=result['period'];bars=result['kind']=='bars'
 start=datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE) if period=='day' else datetime(anchor.year,anchor.month,1,tzinfo=ZONE) if period=='month' else datetime(anchor.year,1,1,tzinfo=ZONE)
 end=start+timedelta(days=1) if period=='day' else (start.replace(day=28)+timedelta(days=4)).replace(day=1) if period=='month' else datetime(anchor.year+1,1,1,tzinfo=ZONE)
 if period=='all':return []
 rows=EventJournal(app_paths(cfg)['component_logs']/'Events.jsonl').recent([device],2000)
 commands=Path(cfg.root_dir)/'Data/ParameterCommands.json'
 # Namespace may differ; derive ledger through the same app_paths used by the writer.
 commands=app_paths(cfg)['data']/'ParameterCommands.json'
 try:
  for record in json.loads(commands.read_text(encoding='utf-8')).values():
   if record.get('device_id')==device and record.get('status')=='verified':rows.append(dict(time=record.get('updated',record.get('created')),code='parameter.changed',message=record['parameter']+': '+record['old']+' → '+record['new']))
 except (OSError,ValueError,KeyError):pass
 output=[]
 for row in rows:
  if row.get('code') not in ('grid','parameter.changed') and not row.get('code','').startswith('connection.'):continue
  try:
   stamp=datetime.fromisoformat(row['time']);stamp=stamp.replace(tzinfo=ZONE) if stamp.tzinfo is None else stamp.astimezone(ZONE)
   if not start.timestamp()<=stamp.timestamp()<end.timestamp():continue
   if not bars:x=stamp.timestamp()*1000
   elif period=='month':x=stamp.day-1
   elif period=='year':x=stamp.month-1
   else:
    # Match a real hourly bucket, including the two distinct hours on a DST fall-back day.
    timed=[(datetime.fromisoformat(p['label']).timestamp(),p['x']) for p in points]
    choices=[(t,v) for t,v in timed if t<=stamp.timestamp()<t+3600]
    if not choices:continue
    x=choices[0][1]
   output.append(dict(x=x,time=stamp.isoformat(),message=row.get('message',''),code=row['code']))
  except (ValueError,KeyError,TypeError):continue
 return sorted(output,key=lambda x:x['time'])[-300:]

def extras(cfg,device,start,end):
 p=Path(cfg.root_dir)/'Server/Insights.sqlite3'
 if not p.exists():return dict(outages=[],statistics=[])
 with closing(sqlite3.connect('file:'+p.as_posix()+'?mode=ro',uri=True,timeout=5)) as db:
  db.row_factory=sqlite3.Row
  outages=[dict(x) for x in db.execute('SELECT * FROM outages WHERE device=? AND start<? AND (end IS NULL OR end>?) ORDER BY start',(device,end.timestamp(),start.timestamp()))]
  for row in outages:
   row['duration_s']=max(0,min(row['end'] or time.time(),end.timestamp())-max(row['start'],start.timestamp()));row['start_iso']=datetime.fromtimestamp(row['start'],ZONE).isoformat();row['end_iso']=datetime.fromtimestamp(row['end'],ZONE).isoformat() if row['end'] else None
  stats=[dict(x) for x in db.execute('SELECT day,min_soc,max_load FROM extrema WHERE device=? AND day>=? AND day<? ORDER BY day',(device,start.date().isoformat(),end.date().isoformat()))]
 return dict(outages=outages,statistics=stats)

def report_events(events,outages):
 # Grid transitions already represented by the same outage endpoint are one
 # event in the report. Connectivity/parameter events remain independent.
 from .energy_accounting import stamp
 endpoints=[v for row in outages for v in (row.get('start'),row.get('end')) if isinstance(v,(int,float))]
 result=[]
 for row in events:
  try:duplicate=row.get('code')=='grid' and any(abs(stamp(row['time']).timestamp()-v)<1 for v in endpoints)
  except (ValueError,KeyError,TypeError):duplicate=False
  if not duplicate:result.append(row)
 return result

def data(view,kind,anchor,source='Auto',other=None,period='day',metric='pv_w',cancelled=None,progress=None):
 if kind not in ('calendar','compare','report','outages','forecast') or period not in ('day','month') or metric not in FIELDS:raise ValueError('Некоректний вид аналітики')
 if not isinstance(anchor,date):raise ValueError('Некоректна дата')
 period='month' if kind=='calendar' else 'day' if kind=='forecast' else period
 if kind=='outages':
  start=datetime(anchor.year,anchor.month,1,tzinfo=ZONE) if period=='month' else datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE)
  end=(start.replace(day=28)+timedelta(days=4)).replace(day=1) if period=='month' else start+timedelta(days=1)
  return dict(kind=kind,anchor=anchor.isoformat(),period=period,**extras(view.cfg,view.device_id,start,end))
 started=time.perf_counter()
 if kind=='report' and period=='day':
  if progress:progress(0,3)
  value=view._day_energy(None,anchor,source,cancelled)
  calculated=time.perf_counter()
  start=datetime.fromisoformat(value['energy_summary']['start']);end=datetime.fromisoformat(value['energy_summary']['end'])
  if progress:progress(1,3)
  extra=extras(view.cfg,view.device_id,start,end);extra_done=time.perf_counter()
  # Markers require just period/anchor/one point for day coordinates.
  events=markers(view.cfg,view.device_id,dict(points=[{}],period='day',anchor=anchor.isoformat(),kind='line'))
  if progress:progress(3,3)
  return dict(contract='ducksolar.insights.v1',kind=kind,period=period,metric=metric,anchor=anchor.isoformat(),source=source,
    summary=value['energy_summary'],forecast_basis=value.get('forecast_basis'),events=report_events(events,extra['outages']),**extra,
    statistics_note='Екстремуми обліковуються з моменту ввімкнення моніторингу; відсутнє значення не нуль.',
    diagnostics=dict(summary_s=round(calculated-started,4),extras_s=round(extra_done-calculated,4),events_s=round(time.perf_counter()-extra_done,4),total_s=round(time.perf_counter()-started,4),records=value['records'],day_checkpoint=value.get('diagnostics',{})))
 a=view.graph_data(period,anchor,source,list(FIELDS[:4]),2000,cancelled,progress,mode='energy')
 for point in a['points']:point['saldo']=point['grid_export_w']-point['grid_import_w'] if all(isinstance(point.get(k),(int,float)) for k in ('grid_export_w','grid_import_w')) else None
 start=datetime.fromisoformat(a['energy_summary']['start']);end=datetime.fromisoformat(a['energy_summary']['end'])
 result=dict(contract='ducksolar.insights.v1',kind=kind,period=period,metric=metric,anchor=anchor.isoformat(),source=source,summary=a['energy_summary'],diagnostics=a.get('diagnostics',{}),**extras(view.cfg,view.device_id,start,end))
 if kind=='calendar':
  values={p['label']:p for p in a['points']};result['days']=[dict(day=date(anchor.year,anchor.month,n).isoformat(),**{k:v for k,v in values.get(date(anchor.year,anchor.month,n).isoformat(),{}).items() if k not in ('x','label')}) for n in range(1,calendar.monthrange(anchor.year,anchor.month)[1]+1)]
 elif kind=='compare':
  if not isinstance(other,date):raise ValueError('Оберіть другу дату')
  b=view.graph_data(period,other,source,list(FIELDS[:4]),2000,cancelled,progress,mode='energy')
  for point in b['points']:point['saldo']=point['grid_export_w']-point['grid_import_w'] if all(isinstance(point.get(k),(int,float)) for k in ('grid_export_w','grid_import_w')) else None
  result['other_summary']=b['energy_summary'];result['other']=other.isoformat();joined={}
  for name,graph,day in [('a',a,anchor),('b',b,other)]:
   midnight=datetime(day.year,day.month,day.day,tzinfo=ZONE).timestamp()
   for row in graph['points']:
    index=int((datetime.fromisoformat(row['label']).timestamp()-midnight)//3600) if period=='day' else int(row['label'][-2:])-1
    target=joined.setdefault(index,dict(x=index,label=(str(index+1)+' день') if period=='month' else (str(index)+' год від початку'),coverage_seconds={}))
    target[name]=row.get(metric);target['coverage_seconds'][name]=row.get('coverage_seconds',{}).get(metric,0)
  result['graph']=dict(contract='ducksolar.graph.v1',kind='bars',mode='energy',suppress_summary=True,points=[joined[k] for k in sorted(joined)],fields=[dict(key='a',label=NAMES[metric]+' '+anchor.isoformat(),unit='кВт·год'),dict(key='b',label=NAMES[metric]+' '+other.isoformat(),unit='кВт·год')],note='Дні зіставлені за годинами від початку (DST23/25год збережено). Місяці — за номером дня.')
 elif kind in ('report','forecast'):
  if kind=='forecast':result['hourly_actual']=a['points']
  result['events']=report_events(markers(view.cfg,view.device_id,a),result['outages'])
  result['statistics_note']='Екстремуми АКБ/навантаження обліковуються з моменту цього оновлення; відсутнє значення не нуль.'
 return result
