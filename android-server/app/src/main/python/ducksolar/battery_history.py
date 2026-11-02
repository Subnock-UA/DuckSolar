"""Small minute history of the energy estimate; no inverter SOC substitution."""
import sqlite3,threading,time,math
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timedelta
from .energy_accounting import ZONE
class BatteryHistory:
 def __init__(self,root,logs=None):
  self.path=Path(root)/'Server/BatteryHistory.sqlite3';self.logs=logs;self.last={};self.lock=threading.RLock();self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.connection() as db:
   db.execute('PRAGMA journal_mode=WAL')
   db.execute('CREATE TABLE IF NOT EXISTS points(device TEXT,at REAL,soc REAL,energy REAL,confidence TEXT,gap REAL,anchor REAL,charged REAL,discharged REAL,PRIMARY KEY(device,at))')
   db.execute('CREATE TABLE IF NOT EXISTS anchors(device TEXT,at REAL,capacity REAL,source TEXT,PRIMARY KEY(device,at))')
 @contextmanager
 def connection(self):
  db=sqlite3.connect(self.path,timeout=.25)
  try:
   with db:yield db
  finally:db.close()
 def anchor(self,device,at,capacity,source):
  try:
   with self.connection() as db:db.execute('INSERT OR REPLACE INTO anchors VALUES(?,?,?,?)',(device,at,capacity,source))
   self.last.pop(device,None)
  except sqlite3.Error as error:self.failure(error)
 def failure(self,error):
  if self.logs:self.logs.event('Battery estimate history unavailable',code='battery.history.failed',error=str(error))
 def record(self,device,at,row,fresh):
  with self.lock:
   if at-self.last.get(device,float('-inf'))<60:return
   try:
    soc=100*row['energy_kwh']/row['capacity_kwh'] if row and fresh else None;energy=row['energy_kwh'] if row and fresh else None
    with self.connection() as db:db.execute('INSERT OR REPLACE INTO points VALUES(?,?,?,?,?,?,?,?,?)',(device,at,soc,energy,'unavailable' if not row or not fresh else 'uncertain' if row.get('gap_s',0)>30 else 'estimated',row.get('gap_s') if row else None,row.get('anchor_at') if row else None,row.get('charged_kwh') if row else None,row.get('discharged_kwh') if row else None))
    self.last[device]=at
   except sqlite3.Error as error:self.failure(error)
 def record_bms(self,device,at,soc,energy,source):
  with self.lock:
   if at-self.last.get(device,float('-inf'))<60:return
   try:
    with self.connection() as db:db.execute('INSERT OR REPLACE INTO points VALUES(?,?,?,?,?,?,?,?,?)',(device,at,soc,energy,'bms' if soc is not None else 'unavailable',None,None,None,None))
    self.last[device]=at
   except sqlite3.Error as error:self.failure(error)
 def query(self,device,anchor,period='day',cancelled=lambda:False):
  start=datetime(anchor.year,anchor.month,1 if period=='month' else anchor.day,tzinfo=ZONE)
  end=(start.replace(day=28)+timedelta(days=4)).replace(day=1) if period=='month' else start+timedelta(days=1)
  with self.connection() as db:
   db.row_factory=sqlite3.Row
   rows=[dict(r) for r in db.execute('SELECT * FROM points WHERE device=? AND at>=? AND at<? ORDER BY at',(device,start.timestamp(),end.timestamp()))]
   anchors=[dict(r) for r in db.execute('SELECT * FROM anchors WHERE device=? AND at>=? AND at<? ORDER BY at',(device,start.timestamp(),end.timestamp()))]
  points=[];known=0.;charged=0.;discharged=0.
  for index,row in enumerate(rows):
   if cancelled():raise ValueError('Скасовано')
   if index:
    previous=rows[index-1];dt=row['at']-previous['at']
    if dt>120 or row['confidence']!=previous['confidence']:points.append(dict(x=(previous['at']+1)*1000,soc=None,energy=None))
    if 0<dt<=120 and all(r['soc'] is not None for r in (previous,row)):known+=dt
    if row['anchor']==previous['anchor']:
     if row['charged'] is not None and previous['charged'] is not None:charged+=max(0,row['charged']-previous['charged'])
     if row['discharged'] is not None and previous['discharged'] is not None:discharged+=max(0,row['discharged']-previous['discharged'])
   points.append(dict(source=row['confidence'],x=row['at']*1000,label=datetime.fromtimestamp(row['at'],ZONE).isoformat(),soc=row['soc'],energy=row['energy']))
  # Limit transfer size while retaining extrema and explicit gaps.
  if len(points)>2000:
   selected={0,len(points)-1};size=max(1,math.ceil(len(points)/250))
   for i in range(0,len(points),size):
    group=list(range(i,min(len(points),i+size)));selected.update((group[0],group[-1]))
    for field in ('soc','energy'):
     valid=[j for j in group if points[j].get(field) is not None]
     if valid:selected.update((min(valid,key=lambda j:points[j][field]),max(valid,key=lambda j:points[j][field])))
    missing=next((j for j in group if points[j].get('soc') is None),None)
    if missing is not None:selected.add(missing)
   points=[points[i] for i in sorted(selected)]
  markers=[dict(x=r['at']*1000,message='Автоматична опора100%' if r['source']=='automatic_full_charge' else 'Ручна опора100%') for r in anchors]
  graphs=[dict(kind='line',mode='power',points=points,fields=[dict(key=key,label=label,unit=unit)],events=markers) for key,label,unit in [('soc','SOC БМС / історична оцінка','%'),('energy','Розрахунковий залишок енергії','кВт·год')]]
  return dict(kind='battery',anchor=anchor.isoformat(),period=period,graphs=graphs,anchors=anchors,battery_summary=dict(records=len(rows),known_hours=known/3600,charged_kwh=charged,discharged_kwh=discharged),note='Нові точки — SOC БМС; старі розрахункові точки збережені з їхнім джерелом. Пропуски не замінені оцінкою. Залишок енергії залежить від заданої ємності.')
