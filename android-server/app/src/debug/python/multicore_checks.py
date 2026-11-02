"""Targeted CPU-kernel verification, no runtime/listener or equipment starts."""
import json,math,random,time,sqlite3,tempfile
from pathlib import Path
from datetime import datetime,date,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from ducksolar import cpu_energy as cpu
from ducksolar.energy_accounting import ZONE
from ducksolar.energy_pair import Pair
from ducksolar.energy_streaming import _Summary
from ducksolar.graph_energy import accumulate

def close(a,b,path=''):
 if isinstance(a,dict):
  assert a.keys()==b.keys(),(path,a.keys(),b.keys())
  for key in a:close(a[key],b[key],path+'.'+str(key))
 elif isinstance(a,(list,tuple)):
  assert len(a)==len(b),(path,len(a),len(b))
  for i,(x,y) in enumerate(zip(a,b)):close(x,y,path+str(i))
 elif isinstance(a,(float,int)) and not isinstance(a,bool):assert math.isclose(a,b,rel_tol=2e-11,abs_tol=2e-8),(path,a,b)
 else:assert a==b,(path,a,b)

def run(root):
 engine=cpu.backend();assert engine is not None
 cfg=SimpleNamespace(max_integration_gap_s=900)
 rng=random.Random(106);base=datetime(2026,10,25,tzinfo=ZONE).timestamp()
 rows=[];t=base;imp=100.;exp=50.
 for i in range(9000):
  t+=rng.choice((5,5,5,20,910));imp+=.003;exp+=.001
  if i%700==0:imp=1.
  row=dict(timestamp=datetime.fromtimestamp(t,ZONE),pv_w=rng.randrange(5000),output_w=rng.randrange(2000),grid_import_w=rng.randrange(2000),grid_export_w=rng.randrange(2000),grid_import_source='measured',grid_export_source='estimated',grid_import_origin='x',grid_export_origin='y',grid_import_energy_total_kwh=imp,grid_export_energy_total_kwh=exp,grid_import_counter_id='one',grid_export_counter_id='two')
  if i%19==0:row['pv_w']=None
  if i%23==0:row['grid_export_energy_total_kwh']=None
  if i%29==0:row['grid_import_counter_id']='changed'
  if i%31==0:row['grid_export_origin']='changed'
  if i%37==0:row['output_w']=True
  if i%41==0:row['grid_import_w']=float('nan')
  rows.append(row)
 start=datetime.fromtimestamp(base+8,ZONE);end=rows[-1]['timestamp']-timedelta(seconds=7)
 ref={d:_Summary(start,end) for d in ('pv','import','export')};new={d:_Summary(start,end) for d in ref}
 before=time.perf_counter()
 for a,b in zip(rows,rows[1:]):Pair(a,b,900).accumulate(ref,start,end)
 reference_s=time.perf_counter()-before;before=time.perf_counter()
 batch=cpu.BalanceBatch(new,start,end,900)
 for row in rows:batch.add(row)
 batch.flush();native_s=time.perf_counter()-before
 close({k:v.state() for k,v in ref.items()},{k:v.state() for k,v in new.items()})
 # Graph windows span the repeated DST hour and day/month boundaries.
 for hourly in (False,True):
  short=rows[:1200];sums={};cov={};daily={} if not hourly else None;dc={} if not hourly else None
  previous=None
  for row in short:accumulate(sums,cov,previous,row,cfg,daily=daily,daily_coverage=dc,start=start,end=end,hourly=hourly);previous=row
  actual={};coverage={};ad={} if not hourly else None;ac={} if not hourly else None
  cpu.graph(actual,coverage,None,short,cfg,daily=ad,daily_coverage=ac,start=start,end=end,hourly=hourly)
  close((sums,cov,daily,dc),(actual,coverage,ad,ac))
 # Counter rollover, no power fallback after an overlong gap, exact huge ints.
 a=dict(timestamp=start,pv_w=0,grid_import_energy_total_kwh=99,grid_import_counter_id='r',grid_import_counter_modulus_kwh=100)
 b=dict(a,timestamp=start+timedelta(seconds=2000),grid_import_energy_total_kwh=1)
 result=cpu.calculate([a,b],[(start.timestamp(),b['timestamp'].timestamp())],900)[0]
 close(list(result[11:16]),(2.,2000.,2000.,1.,0.))
 a['grid_import_energy_total_kwh']=2**60;b['grid_import_energy_total_kwh']=2**60+1
 assert cpu.calculate([a,b],[(start.timestamp(),b['timestamp'].timestamp())],900) is None
 # Native forecast must retain solar-only coverage, nonnegative quality, tariffs.
 from ducksolar.forecast_summary import _day
 day=date(2026,10,25);forecast_rows=[]
 for i in range(0,25*3600+1,60):
  ts=datetime.fromtimestamp(base+i,ZONE);forecast_rows.append(dict(timestamp=ts,pv_w=900 if 8<=ts.hour<=17 else 0,output_w=250))
 forecast_rows[50]['pv_w']=-2;forecast_rows[60]['output_w']=None
 reader=SimpleNamespace(cfg=cfg,energy_graph_rows=lambda *args:forecast_rows)
 expected=None
 with patch.object(cpu,'_backend',None):expected=_day(reader,day,49.,30.,lambda:False)
 close(expected,_day(reader,day,49.,30.,lambda:False))
 # Plain compact SQLite daily-generation integration (including invalid gaps).
 con=sqlite3.connect(':memory:');con.execute('CREATE TABLE samples(t,p,l,c,i,e)')
 raw=[(base+i*5,100. if i%7 else None,200.,10.,20.,5.) for i in range(6000)]
 con.executemany('INSERT INTO samples VALUES(?,?,?,?,?,?)',raw)
 actual=cpu.generation(con.execute('SELECT * FROM samples ORDER BY t'),900,lambda:False);values=[0.]*5
 for a,b in zip(raw,raw[1:]):
  for index in range(5):
   if a[index+1] is not None and b[index+1] is not None:values[index]+=(a[index+1]+b[index+1])*.5*5/3600000
 close(actual,dict(values=values,covered=5999*5,records=6000));con.close()
 # Cancellation aborts before accepting a numerical batch.
 try:cpu.calculate(rows[:10],[(base,base+3600)],900,lambda:True)
 except ValueError:pass
 else:raise AssertionError('Cancellation ignored')
 # A real CPU batch with enough work must use >1 simultaneously active ART worker.
 cpu.calculate(rows,[(base,t+1)],900)
 status=cpu.status();assert status['outside_python_gil']
 assert status['processor_limit']>=2 and status['peak_active_workers']>=2,status
 assert status['active_workers']==0 and status['worker_cpu_ms']>0,status
 result=dict(passed=True,checks=7,reference_balance_s=reference_s,art_balance_s=native_s,cpu=status)
 Path(root,'multicore-result.json').write_text(json.dumps(result),encoding='utf-8')
 return json.dumps(result)
