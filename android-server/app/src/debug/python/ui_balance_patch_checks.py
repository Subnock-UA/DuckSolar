import sys,unittest,tempfile,json,csv,hashlib,copy
from pathlib import Path
from datetime import date,datetime,timedelta
from types import SimpleNamespace
from ducksolar.forecast_comparison import comparison
from ducksolar.energy_accounting import ZONE
from ducksolar.audit_codec import InputEncoder,compact,expand
from ducksolar.energy_streaming import MonthAccounting,_json
from ducksolar.history_reader import HistoryReader
from ducksolar.config import AppConfig

class Checks(unittest.TestCase):
 def test_qmod_freshness_is_bound_to_the_actual_connection(self):
  from ducksolar.core.device import DeviceMonitor
  import threading
  monitor=object.__new__(DeviceMonitor);monitor._state={'raw':{}};monitor._state_lock=threading.RLock();monitor.transport=SimpleNamespace(connection_id='fixture-A')
  monitor._apply_update(SimpleNamespace(telemetry=False,name='QMOD'),'B',dict(mode_code='B'),123.0,('fixture',))
  self.assertEqual(monitor._state['mode_received_monotonic'],123.0);self.assertEqual(monitor._state['mode_connection_id'],'fixture-A')
  monitor.transport.connection_id='fixture-B'
  self.assertNotEqual(monitor._state['mode_connection_id'],monitor.transport.connection_id)
 def test_audit_fast_path_is_byte_identical_and_preserves_missing_null_and_large_int(self):
  encoder=InputEncoder()
  rows=[dict(timestamp='2026-10-31T23:59:58+02:00',pv_w=12.3,grid_import_w=0),dict(timestamp='2026-11-01T00:00:02+02:00',pv_w=None,grid_import_counter_id='Лічильник',grid_import_energy_total_kwh=2**60),dict(timestamp='2026-11-01T00:00:03+02:00',pv_w=0)]
  for row in rows*3:
   encoded=encoder.encode(row)
   self.assertEqual(encoded,(_json(compact(dict(type='input',row=row)))+'\n').encode())
   self.assertEqual(expand(json.loads(encoded))['row'],row)
 def fixture(self,day=date(2026,10,31)):
  start=datetime.combine(day,datetime.min.time(),ZONE);end=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE)
  times=[];t=start.timestamp()
  while t<end.timestamp():times.append(datetime.fromtimestamp(t,ZONE).isoformat());t+=3600
  prediction=dict(expected_kwh=len(times)*.5,issued_at=(start-timedelta(days=1)).isoformat(),hourly=[dict(time=t,kwh=.5,power_w=500) for t in times])
  points=[dict(label=t,pv_w=.4,coverage_seconds=dict(pv_w=3600)) for t in times]
  return prediction,points,end
 def test_completed_day_has_matching_sums_and_two_series(self):
  p,a,end=self.fixture();v=comparison(date(2026,10,31),a,p,end+timedelta(hours=2))
  self.assertEqual(v['covered_hours'],24);self.assertAlmostEqual(v['actual_period_kwh'],9.6);self.assertAlmostEqual(v['error_kwh'],2.4);self.assertAlmostEqual(v['error_pct'],20)
  self.assertEqual([x['x'] for x in v['graph']['points']],list(range(24)))
 def test_today_excludes_current_partial_hour_and_future_fact(self):
  p,a,_=self.fixture();now=datetime(2026,10,31,11,25,tzinfo=ZONE)
  v=comparison(now.date(),a,p,now)
  self.assertEqual(v['expected_hours'],11);self.assertEqual(v['covered_hours'],11);self.assertAlmostEqual(v['forecast_period_kwh'],5.5);self.assertAlmostEqual(v['actual_period_kwh'],4.4)
  self.assertTrue(all(x['actual'] is None for x in v['graph']['points'][11:]));self.assertFalse(v['complete'])
 def test_gaps_are_not_zero_or_valid_error(self):
  p,a,end=self.fixture();a[12]['coverage_seconds']['pv_w']=100
  v=comparison(date(2026,10,31),a,p,end)
  self.assertEqual(v['missing_hours'],1);self.assertIsNone(v['error_kwh']);self.assertIsNone(v['error_pct']);self.assertEqual(v['graph']['points'][12]['actual'],.4);self.assertTrue(v['graph']['points'][12]['actual_partial'])
 def test_same_day_issue_never_scores_earlier_hours(self):
  p,a,end=self.fixture();p['issued_at']='2026-10-31T11:15:00+02:00'
  v=comparison(date(2026,10,31),a,p,end)
  self.assertEqual(v['expected_hours'],12)
  self.assertTrue(all(x['forecast']==.5 and x['actual']==.4 for x in v['graph']['points'][:12]))
  p.pop('issued_at');v=comparison(date(2026,10,31),a,p,end)
  self.assertIsNone(v['error_kwh']);self.assertEqual(v['expected_hours'],0)
 def test_dst_twenty_five_hours_keep_distinct_repeated_hour(self):
  day=date(2026,10,25);p,a,end=self.fixture(day);v=comparison(day,a,p,end)
  self.assertEqual(v['covered_hours'],25);self.assertEqual(len(v['graph']['points']),25)
  self.assertEqual(len({r['label'] for r in v['graph']['points']}),25)
 def test_no_prediction_keeps_known_fact_but_no_error(self):
  _,a,end=self.fixture();v=comparison(date(2026,10,31),a,None,end)
  self.assertIsNone(v['forecast_period_kwh']);self.assertIsNone(v['error_kwh']);self.assertAlmostEqual(v['observed_kwh'],9.6);self.assertEqual(len(v['graph']['points']),24)
 def test_forecast_report_drops_events_even_on_unavailable_prediction(self):
  from ducksolar.forecast_analytics import ForecastAnalytics
  obj=ForecastAnalytics(None,SimpleNamespace(cached_result=lambda _:{}))
  result=dict(kind='forecast',hourly_actual=[],summary={'old':1},events=[{}],outages=[{}],statistics=[{}])
  obj.attach_day('fixture',None,result,date(2026,10,31),'Auto',lambda:False)
  for k in ('summary','events','outages','statistics','hourly_actual'):self.assertNotIn(k,result)
  self.assertIn('comparison',result)
 def test_closed_boundary_support_row_reuses_after_append_and_rejects_edit(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=AppConfig(root_dir=tmp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   fields=['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz']
   def append(day,clock,pv=100):
    p=folder/(day+'.csv');fresh=not p.exists()
    with p.open('a',newline='',encoding='utf8') as f:
     w=csv.DictWriter(f,fields)
     if fresh:w.writeheader()
     w.writerow(dict(time=day+'T'+clock+'+02:00',pv_w=pv,output_w=50,battery_v=53,charge_a=0,grid_v=230,grid_hz=50))
    return p
   append('2026-10-31','23:59:52');oldpath=append('2026-10-31','23:59:57');path=append('2026-11-01','00:00:02')
   store=SimpleNamespace(list_meter_readings=lambda **kw:[]);month=date(2026,10,1)
   original=MonthAccounting().report(reader,store,cfg,month,source='Local')
   originals={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (oldpath,path)}
   append('2026-11-01','00:00:07')
   updated=MonthAccounting().report(HistoryReader(cfg),store,cfg,month,source='Local')
   self.assertTrue(updated['incremental'],updated['diagnostics']);self.assertEqual(updated['diagnostics']['used_records'],0)
   for key in ('pv','inverter_import','inverter_export'):self.assertEqual(original[key],updated[key])
   self.assertEqual(hashlib.sha256(oldpath.read_bytes()).hexdigest(),originals[oldpath])
   # A prefix edit still invalidates the cached numerical result.
   oldpath.write_bytes(oldpath.read_bytes().replace(b',100,',b',200,',1))
   repaired=MonthAccounting().report(HistoryReader(cfg),store,cfg,month,source='Local')
   self.assertFalse(repaired['incremental']);self.assertNotEqual(repaired['pv']['kwh'],original['pv']['kwh'])
 def test_advancing_end_does_not_skip_a_clipped_pair(self):
  from ducksolar.energy_streaming import _resume_checkpoint
  end=datetime(2026,10,31,13,tzinfo=ZONE)
  signature=dict(algorithm='a',start='s',device_id='i',source='Local',model={},history_semantics=None,schemas=[],files=[],end=None)
  prior=dict(signature);prior['end']=None
  old=dict(checkpoint=dict(signature=prior,prefixes=[],last_row=dict(timestamp=(end+timedelta(seconds=2)).isoformat())),report=dict(end=end.isoformat()))
  reader=SimpleNamespace(_balance_stats={})
  self.assertIsNone(_resume_checkpoint(old,[],reader,signature,end+timedelta(hours=1),lambda:False))
  self.assertEqual(reader._balance_stats['checkpoint_rejected'],'changed_time_boundary')
 def test_open_month_support_pair_replays_into_closed_month_without_full_scan(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=AppConfig(root_dir=tmp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   fields=['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz']
   for day,clocks in [('2026-10-31',['23:59:52','23:59:57']),('2026-11-01',['00:00:02','00:00:07'])]:
    with (folder/(day+'.csv')).open('w',newline='') as f:
     w=csv.DictWriter(f,fields);w.writeheader()
     for t in clocks:w.writerow(dict(time=day+'T'+t+'+02:00',pv_w=100,output_w=50,battery_v=53,charge_a=0,grid_v=230,grid_hz=50))
   store=SimpleNamespace(list_meter_readings=lambda **kw:[]);month=date(2026,10,1);end=datetime(2026,10,31,23,59,55,tzinfo=ZONE)
   first=MonthAccounting().report(reader,store,cfg,month,now=end,source='Auto')
   target=Path(tmp)/'Data/EnergyAudit/inverter-1';summary=target/'2026-10-Auto.summary.json'
   saved=json.loads(summary.read_text());immutable={p['path']:hashlib.sha256(Path(p['path']).read_bytes()).hexdigest() for p in saved['input_parts']}
   updated=MonthAccounting().report(HistoryReader(cfg),store,cfg,month,source='Auto')
   self.assertTrue(updated['incremental'],updated['diagnostics']);self.assertTrue(updated['diagnostics']['boundary_pair_replayed'])
   self.assertLess(updated['diagnostics']['used_records'],updated['input_count'])
   self.assertEqual(immutable,{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in immutable})
   # A separate root with identical originals is the independent cold reference.
   import shutil
   with tempfile.TemporaryDirectory() as cold:
    cfg2=AppConfig(root_dir=cold);r2=HistoryReader(cfg2);r2.paths['inverter_logs'].mkdir(parents=True,exist_ok=True)
    for p in folder.glob('*.csv'):shutil.copyfile(p,r2.paths['inverter_logs']/p.name)
    reference=MonthAccounting().report(r2,store,cfg2,month,source='Auto')
   for key in ('pv','inverter_import','inverter_export','input_count'):self.assertEqual(updated[key],reference[key],key)
   from ducksolar.deferred_audit import inputs
   latest=json.loads(summary.read_text());rows=list(inputs(latest['input_parts']))
   self.assertEqual(len(rows),updated['input_count']);self.assertEqual(len({r['timestamp'] for r in rows}),len(rows))

def run():
 import io
 from ducksolar import cpu_energy
 text=io.StringIO();result=unittest.TextTestRunner(stream=text,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=text.getvalue(),cpu=cpu_energy.status()))

