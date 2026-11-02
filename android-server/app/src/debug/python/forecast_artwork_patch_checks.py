import sys,unittest,json,tempfile,csv,hashlib,time
from pathlib import Path
from datetime import date,datetime,timedelta
from unittest.mock import patch,Mock
from types import SimpleNamespace

from ducksolar.forecast_comparison import comparison
from ducksolar.energy_accounting import ZONE
from ducksolar.forecast_analytics import ForecastAnalytics

class Checks(unittest.TestCase):
 day=date(2026,11,1)
 def row(self,h,value=.8,covered=3600,offset='+02:00'):
  return dict(label=f'2026-11-01T{h:02d}:00:00'+offset,pv_w=value,coverage_seconds={'pv_w':covered})
 def prediction(self,issue='2026-11-01T11:15:00+02:00',hours=(10,11,12)):
  return dict(issued_at=issue,expected_kwh=3,hourly=[dict(time=f'2026-11-01T{h:02d}:00:00+02:00',kwh=1) for h in hours])
 def compare(self,rows,prediction=None,now='2026-11-01T12:30:00+02:00'):
  return comparison(self.day,rows,prediction,datetime.fromisoformat(now))
 def test_reported_case_keeps_both_measured_hours_before_issue(self):
  v=self.compare([self.row(10,1.7),self.row(11,1.9)],self.prediction())
  self.assertEqual([p['actual'] for p in v['graph']['points'][:2]],[1.7,1.9]);self.assertAlmostEqual(v['observed_kwh'],3.6)
  self.assertEqual(v['expected_hours'],0);self.assertIsNone(v['error_kwh'])
 def test_missing_issue_does_not_erase_fact_or_forecast(self):
  prediction=self.prediction();prediction.pop('issued_at')
  v=self.compare([self.row(10)],prediction)
  self.assertEqual(v['graph']['points'][0]['actual'],.8);self.assertEqual(v['graph']['points'][0]['forecast'],1)
  self.assertIsNone(v['error_pct'])
 def test_union_retains_actual_hours_absent_from_forecast(self):
  v=self.compare([self.row(8),self.row(10)],self.prediction(hours=(9,)))
  self.assertEqual([p['label'][11:13] for p in v['graph']['points']],['08','09','10'])
  self.assertEqual([p['actual'] for p in v['graph']['points']],[.8,None,.8])
  self.assertEqual([p['forecast'] for p in v['graph']['points']],[None,1,None])
 def test_partial_coverage_preserves_exact_energy_without_extrapolation(self):
  v=self.compare([self.row(10,.25,900)],self.prediction('2026-10-31T12:00:00+02:00',hours=(10,)))
  p=v['graph']['points'][0];self.assertEqual(p['actual'],.25);self.assertEqual(p['coverage_seconds']['actual'],900)
  self.assertTrue(p['actual_partial']);self.assertEqual(v['partial_hours'],1);self.assertIsNone(v['error_kwh'])
 def test_current_partial_hour_is_displayed_but_never_scored(self):
  v=self.compare([self.row(12,.2,1500)],self.prediction('2026-10-31T12:00:00+02:00',hours=(12,)))
  self.assertEqual(v['graph']['points'][0]['actual'],.2);self.assertTrue(v['graph']['points'][0]['actual_partial'])
  self.assertEqual(v['expected_hours'],0);self.assertIsNone(v['error_kwh'])
 def test_future_fact_or_impossible_coverage_is_not_shown(self):
  v=self.compare([self.row(12,.8,3600),self.row(13,.8,3600)],self.prediction())
  self.assertTrue(all(p['actual'] is None for p in v['graph']['points'] if p['label'][11:13] in ('12','13')))
 def test_zero_requires_positive_known_coverage(self):
  v=self.compare([self.row(9,0,3600),self.row(10,0,0),self.row(11,None,3600)])
  self.assertEqual([p['actual'] for p in v['graph']['points']],[0,None,None]);self.assertEqual(v['observed_kwh'],0)
 def test_completed_fair_hours_still_have_correct_error(self):
  v=self.compare([self.row(10,.8),self.row(11,.9)],self.prediction('2026-10-31T12:00:00+02:00',hours=(10,11)))
  self.assertAlmostEqual(v['error_kwh'],.3);self.assertAlmostEqual(v['error_pct'],15);self.assertEqual(v['covered_hours'],2)
 def test_no_forecast_or_unknown_issue_has_no_score(self):
  v=self.compare([self.row(10)])
  self.assertEqual(v['observed_kwh'],.8);self.assertIsNone(v['actual_period_kwh']);self.assertIsNone(v['error_kwh'])
 def test_dst_repeated_hour_is_two_distinct_measurements(self):
  day=date(2026,10,25);rows=[dict(label='2026-10-25T03:00:00'+offset,pv_w=value,coverage_seconds={'pv_w':3600}) for offset,value in [('+03:00',.1),('+02:00',.2)]]
  v=comparison(day,rows,None,datetime.fromisoformat('2026-10-26T00:00:00+02:00'))
  self.assertEqual(len(v['graph']['points']),2);self.assertAlmostEqual(v['observed_kwh'],.3)
 def test_real_history_points_survive_attach_day_and_json_for_both_clients(self):
  from ducksolar.config import AppConfig
  from ducksolar.history_reader import HistoryReader
  from ducksolar.history_views import HistoryViews
  with tempfile.TemporaryDirectory() as tmp:
   cfg=AppConfig(root_dir=tmp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   path=folder/'2026-10-31.csv';fields=['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz']
   with path.open('w',newline='') as f:
    w=csv.DictWriter(f,fields);w.writeheader()
    for at in [(datetime(2026,10,31,10)+timedelta(minutes=5*i)).strftime('%H:%M:%S') for i in range(13)]:w.writerow(dict(time='2026-10-31T'+at+'+02:00',pv_w=1000,output_w=100,battery_v=53,charge_a=0,grid_v=230,grid_hz=50))
   before=hashlib.sha256(path.read_bytes()).hexdigest()
   result=HistoryViews(reader,cfg,'inverter-1').insights_data('forecast',date(2026,10,31),'Auto')
   analytics=ForecastAnalytics(None,None)
   with patch.object(analytics,'day_analysis',return_value=dict(forecast=dict(issued_at='2026-10-31T11:15:00+02:00',hourly=[dict(time='2026-10-31T10:00:00+02:00',kwh=1)]))):analytics.attach_day('i',reader,result,date(2026,10,31),'Auto',lambda:False)
   result=json.loads(json.dumps(result,allow_nan=False));actual=[p['actual'] for p in result['graph']['points'] if p['actual'] is not None]
   self.assertTrue(actual);self.assertGreater(actual[0],.9);self.assertEqual(result['diagnostics']['forecast_display']['visible_actual_hours'],1)
   self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())
 def test_live_uses_same_fact_builder_even_when_forecast_missing_or_stale(self):
  now=datetime(2026,11,1,12,30,tzinfo=ZONE).timestamp()
  for fresh in (True,False):
   weather=dict(location=dict(latitude=50,longitude=30),updated=datetime.fromtimestamp(now-(0 if fresh else 50000),ZONE).isoformat(),latest_hourly=self.prediction()['hourly'])
   analytics=ForecastAnalytics(None,SimpleNamespace(cached_result=lambda _:weather))
   actual=dict(pv_kwh=1.6,records=100,solar_covered_s=0,hourly_points=[self.row(10),self.row(11)])
   with patch.object(analytics,'_live_actual',return_value=(actual,now,False)),patch('ducksolar.forecast_analytics.time.time',return_value=now):
    result=analytics.live('i',Mock())
   self.assertEqual([p['actual'] for p in result['graph']['points'] if p['actual'] is not None],[.8,.8])
   self.assertEqual(result['available'],fresh)
 def test_live_actual_cache_contains_hourly_points_from_real_history(self):
  from ducksolar.config import AppConfig
  from ducksolar.history_reader import HistoryReader
  with tempfile.TemporaryDirectory() as tmp:
   cfg=AppConfig(root_dir=tmp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   path=folder/'2026-11-01.csv'
   with path.open('w',newline='') as f:
    fields=['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz'];w=csv.DictWriter(f,fields);w.writeheader()
    for i in range(13):w.writerow(dict(time=(datetime(2026,11,1,10,tzinfo=ZONE)+timedelta(minutes=5*i)).isoformat(),pv_w=1000,output_w=100,battery_v=53,charge_a=0,grid_v=230,grid_hz=50))
   now=datetime(2026,11,1,12,30,tzinfo=ZONE).timestamp();analytics=ForecastAnalytics(None,None)
   first,at,hit=analytics._live_actual('i',reader,self.day,50,30,lambda:False,now)
   second,at2,hit2=analytics._live_actual('i',reader,self.day,50,30,lambda:False,now+10)
   self.assertFalse(hit);self.assertTrue(hit2);self.assertIs(first,second);self.assertEqual(at,at2)
   self.assertTrue(first['hourly_points']);self.assertGreater(first['hourly_points'][0]['pv_w'],.9)
 def test_accuracy_keeps_excluding_insufficient_days_instead_of_faking_error(self):
  weather=dict(location=dict(latitude=50,longitude=30),forecast_archive={'2026-10-31':dict(issued_at='2026-10-30T12:00:00+02:00',expected_kwh=5,horizon_days=1)})
  analytics=ForecastAnalytics(None,SimpleNamespace(cached_result=lambda _:weather))
  with patch('ducksolar.forecast_analytics.summaries',return_value={'2026-10-31':dict(summary=dict(pv_kwh=1,solar_coverage_pct=40))}):
   v=analytics.accuracy('i',Mock(),lambda:False,anchor=self.day)
  self.assertEqual(v['rows'],[]);self.assertEqual(len(v['excluded']),1)

def run():
 import io
 from ducksolar import cpu_energy
 text=io.StringIO();result=unittest.TextTestRunner(stream=text,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=text.getvalue(),cpu=cpu_energy.status()))

