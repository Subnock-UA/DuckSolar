import csv,json,math,tempfile,threading,time,unittest,io
from pathlib import Path
from datetime import datetime,date,timedelta
from types import SimpleNamespace
from unittest.mock import Mock,patch
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.energy_accounting import ZONE
from ducksolar.hourly_projection import day

class Checks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.cfg=AppConfig(root_dir=self.tmp.name);self.anchor=date(2026,10,25)
  self.path=self.root/'2026-10-25.csv';self.smart=self.root/'smart.csv'
  self.reader,self.view=self.new_view()
  self.base=datetime(2026,10,25,2,tzinfo=ZONE).timestamp()
 def tearDown(self):self.tmp.cleanup()
 def new_view(self):
  reader=HistoryReader(self.cfg)
  reader.find_day_files=lambda d:([self.path] if d==self.anchor and self.path.exists() else [],[self.smart] if d==self.anchor and self.smart.exists() else [])
  reader.available_dates=lambda refresh=False:[self.anchor]
  return reader,HistoryViews(reader,self.cfg,'inverter-1')
 def append(self,count,offset=0):
  keys=['time','pv_w','output_w','output_va','pv_v','battery_v','charge_a','discharge_a','grid_v','grid_hz','output_v','output_hz','grid_available']
  first=not self.path.exists()
  with self.path.open('a',encoding='utf-8',newline='') as f:
   writer=csv.DictWriter(f,keys)
   if first:writer.writeheader()
   for i in range(offset,offset+count):
    writer.writerow(dict(time=datetime.fromtimestamp(self.base+i*5,ZONE).isoformat(),pv_w=100+i%600,output_w=200+i%20,output_va=230,pv_v=320,battery_v=52,charge_a=1,discharge_a=0,grid_v=230,grid_hz=50,output_v=229,output_hz=50,grid_available=1))
 def expected(self,fields,source='Auto'):
  rows=self.view._hourly(None,source,self.reader.graph_day_rows(self.anchor,source))
  return self.select(rows,fields)
 def select(self,rows,fields):
  keys=set(fields)|{'timestamp','_gap','grid_import_source','grid_export_source','grid_import_origin','grid_export_origin'}
  return [{k:v for k,v in row.items() if k in keys} for row in rows]
 def same(self,a,b):
  self.assertEqual(len(a),len(b))
  for left,right in zip(a,b):
   self.assertEqual(left.keys(),right.keys())
   for key,value in left.items():
    if isinstance(value,(int,float)):self.assertTrue(math.isclose(value,right[key],rel_tol=1e-11,abs_tol=1e-9),(key,value,right[key]))
    elif isinstance(value,datetime):
     self.assertEqual(value.timestamp(),right[key].timestamp());self.assertEqual(value.isoformat(),right[key].isoformat())
    else:self.assertEqual(value,right[key])
 def test_scalar_and_voltage_means_dst_and_restart_append(self):
  self.append(2800)
  for fields in (['pv_w','output_w'],['pv_v','battery_v','grid_v','output_v']):
   rows,stats=day(self.view,self.anchor,'Auto',fields,lambda:False)
   self.same(self.select(rows,fields),self.expected(fields));self.assertEqual(stats['new_rows'],2800 if fields[0]=='pv_w' else 0)
   _,warm=day(self.view,self.anchor,'Auto',fields,lambda:False);self.assertTrue(warm['cache_hit'])
  # A fresh reader/process resumes the durable unfinished mean using sum/count.
  self.append(4,2800);self.reader,self.view=self.new_view()
  for fields in (['pv_w','output_w'],['pv_v','battery_v','grid_v','output_v']):
   rows,stats=day(self.view,self.anchor,'Auto',fields,lambda:False)
   self.assertEqual(stats['new_rows'],4 if fields[0]=='pv_w' else 0)
   if fields[0]=='pv_w':self.assertTrue(stats['incremental'],stats)
   self.same(self.select(rows,fields),self.expected(fields))
 def test_edited_prefix_and_partial_line(self):
  self.append(15);fields=['pv_w','output_w'];day(self.view,self.anchor,'Auto',fields,lambda:False)
  raw=self.path.read_bytes().replace(b',100,200,',b',900,200,',1);self.path.write_bytes(raw)
  rows,stats=day(self.view,self.anchor,'Auto',fields,lambda:False)
  self.assertFalse(stats['incremental']);self.assertEqual(stats['checkpoint_rejected'],'edited_prefix')
  self.same(self.select(rows,fields),self.expected(fields))
  with self.path.open('ab') as f:f.write(b'partial')
  _,stats=day(self.view,self.anchor,'Auto',fields,lambda:False);self.assertEqual(stats['new_rows'],0)
 def test_auto_new_local_retracts_previous_ess_tail(self):
  with self.smart.open('w',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,['Timestamp','PV total Power','Output Active Power']);w.writeheader()
   for seconds in (0,10,20):w.writerow({'Timestamp':datetime.fromtimestamp(self.base+seconds,ZONE).isoformat(),'PV total Power':100,'Output Active Power':50})
  fields=['pv_w','output_w'];day(self.view,self.anchor,'Auto',fields,lambda:False)
  self.append(1,5)
  rows,stats=day(self.view,self.anchor,'Auto',fields,lambda:False)
  self.assertFalse(stats['incremental']);self.assertEqual(stats['checkpoint_rejected'],'auto_merge_boundary')
  self.same(self.select(rows,fields),self.expected(fields))
 def test_compact_timestamp_defaults_and_grid_decode_equivalence(self):
  self.append(30)
  from ducksolar.compact_history import convert,Codec
  compact=self.root/'compact.csv';convert(self.path,compact)
  self.path=compact;self.reader,self.view=self.new_view()
  times=self.reader.timestamp_decoder(compact);codec=Codec(compact)
  for row in csv.DictReader(compact.open(encoding='utf-8')):
   full=codec.decode(row,True);self.assertEqual(times(row),full['time'])
   a=self.reader._canonical(full,'Local',self.anchor,True)
   b=self.reader._canonical(full,'Local',self.anchor,True,parsed_time=self.reader._parse_dt(times(row),self.anchor))
   self.assertEqual(a,b)
  fields=['pv_w','output_w'];rows,_=day(self.view,self.anchor,'Auto',fields,lambda:False)
  self.same(self.select(rows,fields),self.expected(fields))
 def test_cancel_does_not_replace_committed_hourly_cache(self):
  self.append(20);fields=['pv_w','output_w'];day(self.view,self.anchor,'Auto',fields,lambda:False)
  target=next(self.view.view_path.glob('hourly-index*.json'));before=target.read_bytes();self.append(200,20)
  calls=0
  def cancelled():
   nonlocal calls;calls+=1;return calls>20
  with self.assertRaises(ValueError):day(self.view,self.anchor,'Auto',fields,cancelled)
  self.assertEqual(target.read_bytes(),before)
 def test_legacy_graph_day_job_returns_list_without_meter_attachment(self):
  from ducksolar import resource_manager as memory
  from ducksolar.api import APIServer
  from ducksolar.history_jobs import HistoryJobs
  memory.update(4*1024**3,100*1024**2,8*1024**3,False)
  api=APIServer.__new__(APIServer);api.stop_event=threading.Event();api.job_context_lock=threading.Lock();api.job_contexts={};api.jobs=HistoryJobs(self.root/'jobs',Mock())
  device=SimpleNamespace(cfg=self.cfg,definition=SimpleNamespace(id='inverter-1'))
  api.runtime=SimpleNamespace(maintenance_mode=False,device=lambda ident:device,logs=Mock(),storage=Mock())
  try:
   with patch.object(HistoryViews,'graph_day',lambda self,day,source='Auto',cancelled=None,progress=None:[dict(pv_w=42)]):
    job=api.call('history','job_start',[dict(method='graph_day',args=[self.anchor,'Auto'])],{},'owner')
    api.jobs.jobs[job['job_id']]['future'].result(timeout=10)
    state=api.jobs.status('owner',job['job_id']);self.assertEqual(state['state'],'completed',state)
    self.assertEqual(api.jobs.result('owner',job['job_id'])['result'],[dict(pv_w=42)])
    api.runtime.storage.list_meter_readings.assert_not_called()
  finally:api.jobs.stop();api.jobs.executor.shutdown(wait=True,cancel_futures=True);api.jobs.reaper.join(timeout=1)

def run(root):
 old=tempfile.tempdir;tempfile.tempdir=root;stream=io.StringIO()
 try:
  result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
  Path(root,'hourly-checks.log').write_text(stream.getvalue(),'utf-8')
  if not result.wasSuccessful():raise AssertionError(stream.getvalue())
  return json.dumps(dict(passed=True,checks=result.testsRun))
 finally:tempfile.tempdir=old
