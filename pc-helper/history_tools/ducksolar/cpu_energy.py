"""Bounded ART batches. Java arithmetic runs with the Chaquopy GIL released.

Desktop/helper consumers retain the reference implementation. Android never
silently hides a broken bridge. Unrepresentable integer counters retain Python
precision through an explicitly counted reference fallback.
"""
import json, math, sys, threading, time
from array import array
from datetime import datetime,timedelta
from .energy_accounting import stamp,ZONE,number

BLOCK=4096
_backend=None;_loaded=False;_lock=threading.Lock();_fallback=0

def backend():
 global _loaded,_backend
 with _lock:
  if not _loaded:
   try:from java import jclass
   except ImportError:_backend=None
   else:_backend=jclass('ua.ducksolar.b2.server.HistoryCpuEngine')
   _loaded=True
  return _backend

def status():
 engine=backend()
 result=json.loads(str(engine.status())) if engine else dict(engine='python.reference',outside_python_gil=False)
 result['precision_fallback_batches']=_fallback
 return result

def _bytes(values):
 values=array('d',values)
 if sys.byteorder!='little':values.byteswap()
 return values.tobytes()

def _encode(rows):
 identities={};data=array('d')
 def ident(value,required=False):
  if required and not value:return 0.
  if value not in identities:identities[value]=len(identities)+1
  return float(identities[value])
 def value(row,key):
  raw=row.get(key)
  if not number(raw):return math.nan
  if isinstance(raw,int) and abs(raw)>2**53:raise OverflowError('Integer cannot be represented exactly in double')
  return float(raw)
 for row in rows:
  data.append(stamp(row['timestamp']).timestamp())
  data.extend(value(row,k) for k in ('pv_w','output_w','grid_import_w','grid_export_w',
   'grid_import_energy_total_kwh','grid_export_energy_total_kwh'))
  data.extend(ident(row.get('grid_'+d+'_counter_id'),True) for d in ('import','export'))
  data.extend(value(row,'grid_'+d+'_counter_modulus_kwh') for d in ('import','export'))
  data.extend({'measured':1.,'estimated':2.}.get(row.get('grid_'+d+'_source'),0.) for d in ('import','export'))
  data.extend(ident(row.get('grid_'+d+'_origin')) for d in ('import','export'))
 if sys.byteorder!='little':data.byteswap()
 return data.tobytes()

def calculate(rows,windows,max_gap,cancelled=None):
 global _fallback
 if cancelled and cancelled():raise ValueError('History query cancelled')
 engine=backend()
 if engine is None:return None
 try:encoded=_encode(rows)
 except (OverflowError,TypeError):
  with _lock:_fallback+=1
  return None
 from .concurrency import active_count,CPU_WORKERS
 workers=max(1,CPU_WORKERS//max(1,active_count()))
 raw=engine.calculate(encoded,_bytes(v for pair in windows for v in pair),float(max_gap),workers)
 out=array('d');out.frombytes(bytes(raw))
 if sys.byteorder!='little':out.byteswap()
 if len(out)!=len(windows)*21:raise ValueError('CPU kernel result version mismatch')
 if cancelled and cancelled():raise ValueError('History query cancelled')
 return [out[i:i+21] for i in range(0,len(out),21)]

class BalanceBatch:
 def __init__(self,summaries,start,end,max_gap,previous=None,cancelled=None,diagnostics=None):
  self.summaries=summaries;self.start=start;self.end=end;self.max_gap=max_gap
  self.rows=[previous] if previous is not None else [];self.cancelled=cancelled;self.diagnostics=diagnostics
 def add(self,row):
  self.rows.append(row)
  if len(self.rows)>BLOCK:self.flush()
 def flush(self):
  if len(self.rows)<2:return
  started=time.perf_counter()
  result=calculate(self.rows,[(self.start.timestamp(),self.end.timestamp())],self.max_gap,self.cancelled)
  if result is None:
   from .energy_pair import Pair
   prior=None
   for a,b in zip(self.rows,self.rows[1:]):
    if self.cancelled and self.cancelled():raise ValueError('History query cancelled')
    pair=Pair(a,b,self.max_gap,prior);pair.accumulate(self.summaries,self.start,self.end);prior=pair.y
  else:
   for direction,index in (('pv',0),('import',2),('export',3)):
    value=result[0][1+index*5:6+index*5];bucket=self.summaries[direction]
    bucket.kwh+=value[0];bucket.covered+=value[1];bucket.measured+=value[2]
    bucket.count+=int(value[3]);bucket.resets+=int(value[4])
  if self.diagnostics is not None:
   self.diagnostics['cpu_batches']=self.diagnostics.get('cpu_batches',0)+int(result is not None)
   self.diagnostics['cpu_batch_s']=self.diagnostics.get('cpu_batch_s',0)+time.perf_counter()-started
  self.rows=[self.rows[-1]]

def graph(sums,coverage,previous,rows,cfg,grid=True,daily=None,daily_coverage=None,start=None,end=None,hourly=False,cancelled=None):
 """One stream block, including its previous row, with UTC calendar windows."""
 full=([previous] if previous is not None else [])+rows
 if len(full)<2:return
 first=stamp(full[0]['timestamp']);last=stamp(full[-1]['timestamp'])
 begin=start or first;stop=end or last
 if stop.timestamp()<=begin.timestamp():return
 windows=[];keys=[];left=begin
 while left.timestamp()<stop.timestamp():
  if hourly:
   edge=datetime.fromtimestamp((int(left.timestamp())//3600+1)*3600,ZONE)
   key=datetime.fromtimestamp(int(left.timestamp())//3600*3600,ZONE).isoformat()
  elif daily is not None:
   edge=datetime(left.year,left.month,left.day,tzinfo=ZONE)+timedelta(days=1);key=left.strftime('%Y-%m')
  else:
   edge=datetime(left.year+int(left.month==12),1 if left.month==12 else left.month+1,1,tzinfo=ZONE);key=left.strftime('%Y-%m')
  right=min(edge,stop,key=lambda t:t.timestamp())
  windows.append((left.timestamp(),right.timestamp()));keys.append((key,left.date().isoformat()))
  left=right
 result=calculate(full,windows,cfg.max_integration_gap_s,cancelled)
 if result is None:
  from .graph_energy import accumulate
  for row in rows:
   if cancelled and cancelled():raise ValueError('History query cancelled')
   accumulate(sums,coverage,previous,row,cfg,grid,daily,daily_coverage,start,end,hourly);previous=row
  return
 fields=('pv_w','output_w','grid_import_w','grid_export_w') if grid else ('pv_w','output_w')
 for (key,day),values in zip(keys,result):
  if not values[0]:continue
  targets=[(sums.setdefault(key,{k:None for k in fields}),coverage.setdefault(key,{k:0. for k in fields}))]
  if daily is not None:targets.append((daily.setdefault(day,{k:None for k in fields}),daily_coverage.setdefault(day,{k:0. for k in fields})))
  for index,field in enumerate(fields):
   offset=1+index*5
   if values[offset+3]:
    for target,covered in targets:
     target[field]=(target[field] or 0.)+values[offset];covered[field]+=values[offset+1]

def forecast(rows,solar,groups,max_gap,until,cancelled):
 """Partition once by solar/tariff boundaries; the native workers integrate."""
 if backend() is None:return None
 if len(rows)<2:return (0.,0.,{k:0. for k in groups},{k:0. for k in groups})
 start=stamp(rows[0]['timestamp']).timestamp();end=stamp(rows[-1]['timestamp']).timestamp()
 if until is not None:end=min(end,until)
 if end<=start:return (0.,0.,{k:0. for k in groups},{k:0. for k in groups})
 edges=sorted({start,end,*[v for pair in solar for v in pair if start<v<end],
  *[v for ranges in groups.values() for pair in ranges for v in pair if start<v<end]})
 windows=list(zip(edges,edges[1:]));pv=covered=0.;load={k:0. for k in groups};coverage={k:0. for k in groups}
 previous=None
 for offset in range(0,len(rows),BLOCK):
  # Forecast quality excludes negative measurements, unlike general accounting.
  block=[dict(timestamp=row['timestamp'],**{key:row.get(key) if number(row.get(key)) and row[key]>=0 else None for key in ('pv_w','output_w')}) for row in rows[offset:offset+BLOCK]]
  full=([previous] if previous is not None else [])+block
  result=calculate(full,windows,max_gap,cancelled)
  if result is None:return None
  for (left,right),values in zip(windows,result):
   pv+=values[1];mid=(left+right)*.5
   if any(a<=mid<b for a,b in solar):covered+=values[2]
   for key,ranges in groups.items():
    if any(a<=mid<b for a,b in ranges):load[key]+=values[6];coverage[key]+=values[7]
  if block:previous=block[-1]
 return pv,covered,load,coverage

def generation(cursor,max_gap,cancelled):
 """Compact SQLite scalar rows are already ordered and decoded; no dictionaries."""
 engine=backend()
 if engine is None:return None
 from .concurrency import CPU_WORKERS,active_count
 totals=[0.]*6;previous=None;records=0
 while True:
  if cancelled():raise ValueError('History query cancelled')
  block=cursor.fetchmany(BLOCK)
  if not block:break
  records+=len(block)
  full=([previous] if previous is not None else [])+block
  raw=engine.plain(_bytes(v if v is not None else math.nan for row in full for v in row),float(max_gap),max(1,CPU_WORKERS//max(1,active_count())))
  result=array('d');result.frombytes(bytes(raw))
  if sys.byteorder!='little':result.byteswap()
  if cancelled():raise ValueError('History query cancelled')
  for i,value in enumerate(result):totals[i]+=value
  previous=block[-1]
 return dict(values=totals[:5],covered=totals[5],records=records)
