import copy,io,json,tempfile,threading,time,unittest
from pathlib import Path
from datetime import datetime,date,timedelta
from types import SimpleNamespace
from unittest.mock import Mock,patch
import hourly_patch_checks as original
from ducksolar import hourly_projection as hourly
from ducksolar import graph_cache_job as manager
from ducksolar.energy_accounting import ZONE

class Checks(original.Checks):
 def test_full_projection_serves_every_mode_without_row_scan(self):
  self.append(80)
  hourly.day(self.view,self.anchor,'Auto',['pv_v'],lambda:False)
  with patch.object(hourly,'_ordered_rows',side_effect=AssertionError('Existing cache rebuilt')):
   for fields,source in ((['pv_w','output_w'],'Auto'),(['battery_v','charge_a'],'Local')):
    rows,stats=hourly.day(self.view,self.anchor,source,fields,lambda:False)
    self.assertTrue(stats['cache_hit']);self.assertEqual(stats['new_rows'],0)
    self.same(self.select(rows,fields),self.expected(fields,source))
 def test_existing_scalar_extended_only_for_missing_columns(self):
  self.append(90)
  scalar=self.view.view_path/f'hourly-index-v1-{self.anchor}-Auto-scalar.json'
  hourly._day(self.view,self.anchor,'Auto',hourly.FIELDS,scalar,lambda:False)
  seen=[];real=hourly._batch
  def batch(state,rows,keys,*args):seen.extend(keys);return real(state,rows,keys,*args)
  with patch.object(hourly,'_batch',side_effect=batch):
   rows,stats=hourly.day(self.view,self.anchor,'Auto',['grid_v'],lambda:False)
  self.assertTrue(stats['reused_scalar']);self.assertNotIn('pv_w',seen);self.assertNotIn('output_w',seen)
  self.same(self.select(rows,['pv_w','output_w','grid_v']),self.expected(['pv_w','output_w','grid_v']))
 def test_legacy_pc_completed_day_adopted_without_reading_measurements(self):
  self.anchor=date(2026,10,24);self.base=datetime(2026,10,24,10,tzinfo=ZONE).timestamp();self.append(70)
  rows=self.view._hourly(None,'Auto',self.reader.graph_day_rows(self.anchor))
  hourly.export_portable(self.view,self.anchor,'Auto',rows)
  local=next(self.view.view_path.glob('period-*.json'));imported=self.root/local.name;local.replace(imported)
  with patch('ducksolar.prepared_history.PreparedHistory._object',lambda self,name:imported if name==imported.name else None),patch.object(hourly,'_ordered_rows',side_effect=AssertionError('Legacy cache rebuilt')):
   result,stats=hourly.day(self.view,self.anchor,'Auto',['grid_v'],lambda:False)
  self.assertTrue(stats['adopted_legacy']);self.assertEqual(stats['new_rows'],0)
  self.same(self.select(result,['pv_w','grid_v']),self.select(rows,['pv_w','grid_v']))
 def test_art_hourly_groups_equal_reference_with_gaps_and_counters(self):
  from ducksolar.cpu_energy import backend
  rows=[];keys=['pv_w','output_w','grid_v','grid_import_energy_total_kwh']
  for i in range(4096):
   t=self.base+i*5+(1800 if i>=1000 else 0)
   rows.append(dict(timestamp=datetime.fromtimestamp(t,ZONE),pv_w=None if i%53==0 else i%500,output_w=i%300,grid_v=230.,grid_import_energy_total_kwh=200.+i*.001,grid_import_source='measured' if i%333 else 'estimated',grid_import_origin='meter'))
  seed=lambda:dict(closed=[],open=None,last_epoch=None,records=0)
  ref,actual=seed(),seed()
  for row in rows:hourly._add(ref,row,900)
  hourly._batch(actual,rows,keys,900,lambda:False)
  self.same(hourly._result(ref),hourly._result(actual))
  engine=backend()
  if engine is not None:
   stats=json.loads(str(engine.status()));self.assertTrue(stats['outside_python_gil']);self.assertGreaterEqual(stats['peak_active_workers'],2);self.assertGreaterEqual(stats['hourly_rows'],4096)
 def runtime(self):
  from ducksolar import resource_manager as memory
  memory.update(4*1024**3,100*1024**2,8*1024**3,False)
  return SimpleNamespace(cfg=self.cfg,devices={'inverter-1':SimpleNamespace(cfg=self.cfg)},logs=Mock(),api=SimpleNamespace(jobs=SimpleNamespace(lock=threading.Lock(),jobs={})),maintenance_mode=False)
 def wait_job(self,job,state='completed'):
  deadline=time.monotonic()+8
  while time.monotonic()<deadline:
   value=job.status()
   if value['state']==state:return value
   if value['state']=='error':self.fail(str(value))
   time.sleep(.02)
  self.fail(str(job.status()))
 def test_job_reuses_existing_cache_and_deduplicates_requests(self):
  self.append(50);hourly.day(self.view,self.anchor,'Auto',['grid_v'],lambda:False)
  with patch.object(manager,'HistoryReader',lambda cfg:self.new_view()[0]),patch.object(hourly,'_ordered_rows',side_effect=AssertionError('Ready cache rebuilt')):
   job=manager.GraphCacheJob(self.runtime())
   try:
    first=job.request();second=job.request();self.assertEqual(first['run_id'],second['run_id'])
    result=self.wait_job(job);self.assertEqual(result['total'],1);self.assertEqual(result['cache_hits'],1);self.assertEqual(result['prepared'],0)
   finally:job.stop()
 def test_job_parallelism_and_durable_resume(self):
  self.append(10);rt=self.runtime();gate=threading.Event();both=threading.Barrier(2);entered=threading.Event()
  original_reader=self.new_view()[0];dates=[self.anchor-timedelta(days=i) for i in (1,2)]
  def reader(cfg):
   value=self.new_view()[0];value.available_dates=lambda refresh=False:dates;value.find_day_files=lambda d:([self.path],[]);return value
  def prepare(view,anchor,source,fields,cancelled):
   both.wait(4);entered.set()
   while not gate.wait(.01):
    if cancelled():raise InterruptedError('Stopped')
   return [],dict(day=str(anchor),cache_hit=True,new_rows=0)
  with patch.object(manager,'HistoryReader',reader),patch.object(manager,'day',prepare):
   job=manager.GraphCacheJob(rt)
   try:
    job.request();self.assertTrue(entered.wait(4));self.assertTrue(job.manual_active());self.assertEqual(len(job.status()['active_tasks']),2)
    # No screen/UI reference exists; the durable job remains active until stop.
    job.stop();self.assertEqual(job.status()['state'],'paused_server')
   finally:gate.set();job.stop()
  with patch.object(manager,'HistoryReader',reader),patch.object(manager,'day',lambda view,anchor,*args:([],dict(day=str(anchor),cache_hit=True,new_rows=0))):
   resumed=manager.GraphCacheJob(rt)
   try:
    result=self.wait_job(resumed);self.assertTrue(result['resumed']);self.assertEqual(result['completed'],2);self.assertEqual(result['cache_hits'],2)
   finally:resumed.stop()

def run(root):
 old=tempfile.tempdir;tempfile.tempdir=root;stream=io.StringIO()
 try:
  result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
  Path(root,'cache-checks.log').write_text(stream.getvalue(),'utf-8')
  if not result.wasSuccessful():raise AssertionError(stream.getvalue())
  return json.dumps(dict(passed=True,checks=result.testsRun))
 finally:tempfile.tempdir=old

_ui={}
def ui_setup(root):
 import android_bridge
 case=Checks();case.setUp();case.append(10);rt=case.runtime();gate=threading.Event();entered=threading.Event()
 def prepare(view,anchor,source,fields,cancelled):
  entered.set()
  while not gate.wait(.01):
   if cancelled():raise InterruptedError('Stopped')
  return [],dict(day=str(anchor),cache_hit=True,new_rows=0)
 patches=[patch.object(manager,'HistoryReader',lambda cfg:case.new_view()[0]),patch.object(manager,'day',prepare)]
 for item in patches:item.start()
 job=manager.GraphCacheJob(rt);rt.maintenance=SimpleNamespace(graph_cache=job)
 _ui.update(case=case,job=job,gate=gate,entered=entered,patches=patches,previous=android_bridge._runtime)
 android_bridge._runtime=rt
 return True
def ui_started():
 assert _ui['entered'].wait(5),'Activity did not start cache preparation'
 return json.dumps(_ui['job'].status())
def ui_after_close():
 assert _ui['job'].manual_active(),'Closing Activity cancelled server job'
 _ui['gate'].set();return json.dumps(_ui['case'].wait_job(_ui['job']))
def ui_cleanup():
 import android_bridge
 if not _ui:return
 _ui['gate'].set();_ui['job'].stop();android_bridge._runtime=_ui['previous']
 for item in reversed(_ui['patches']):item.stop()
 _ui['case'].tearDown();_ui.clear()
