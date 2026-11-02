import sys, unittest, tempfile, csv
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import patch
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.energy_accounting import ZONE
from ducksolar.graph_energy import accumulate, summary

class GraphEnergyTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.cfg=AppConfig(root_dir=self.tmp.name,max_integration_gap_s=900)
  self.reader=HistoryReader(self.cfg);self.view=HistoryViews(self.reader,self.cfg,'inverter-1')
 def tearDown(self):self.tmp.cleanup()
 def row(self,stamp,pv=1000,load=500,imp=100,exp=200):
  return dict(timestamp=stamp.isoformat(),pv_w=pv,output_w=load,grid_import_w=imp,grid_export_w=exp,
   grid_import_source='measured',grid_export_source='measured',grid_import_origin='test',grid_export_origin='test')
 def append(self,stamp,pv=1000):
  p=self.reader.paths['inverter_logs']/(stamp.date().isoformat()+'.csv');p.parent.mkdir(parents=True,exist_ok=True)
  row=dict(time=stamp.isoformat(),pv_w=pv,output_w=pv/2,grid_v=230,grid_hz=50)
  new=not p.exists()
  with p.open('a',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,list(row))
   if new:w.writeheader()
   w.writerow(row)
  self.reader.available_dates(refresh=True)
 def test_month_daily_without_balance_or_hourly_reports(self):
  t=datetime(2026,10,13,23,55,tzinfo=ZONE)
  for i in (0,10,15):self.append(t+timedelta(minutes=i))
  with patch('ducksolar.energy_streaming.MonthAccounting.report',side_effect=AssertionError('No daily balance')), \
       patch.object(self.view,'month_series',side_effect=AssertionError('No hourly reduction')):
   r=self.view.graph_data('month',date(2026,10,1),'Local',mode='energy')
  self.assertEqual(r['bucket'],'day');self.assertEqual(len(r['points']),31)
  self.assertIsNone(r['points'][0]['pv_w'])
  self.assertAlmostEqual(r['points'][12]['pv_w'],1/12)
  self.assertAlmostEqual(r['points'][13]['pv_w'],1/6)
  self.assertAlmostEqual(r['energy_summary']['generation']['kwh'],.25)
  self.assertIsNone(r['energy_summary']['import']['kwh'])
  self.assertIsNone(r['energy_summary']['balance']['kwh'])
  self.assertEqual(r['fields'][0]['unit'],'кВт·год')
 def test_year_all_share_full_resolution_totals_and_valid_units(self):
  t=datetime(2026,9,30,23,55,tzinfo=ZONE)
  for i in (0,10,15):self.append(t+timedelta(minutes=i))
  for period in ('year','all'):
   r=self.view.graph_data(period,date(2026,10,1),'Local')
   self.assertAlmostEqual(r['energy_summary']['generation']['kwh'],.25)
   self.assertAlmostEqual(sum(p['output_w'] for p in r['points']),.125)
   self.assertTrue(all(f['unit']=='кВт·год' for f in r['fields']))
 def test_month_restart_append_does_not_recalculate_prior_records(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE)
  self.append(t);self.append(t+timedelta(minutes=5))
  self.view.graph_data('month',date(2026,10,1),'Local',mode='energy')
  self.append(t+timedelta(minutes=10),2000)
  fresh=HistoryViews(HistoryReader(self.cfg),self.cfg,'inverter-1')
  r=fresh.graph_data('month',date(2026,10,1),'Local',mode='energy')
  self.assertTrue(r['diagnostics']['month_chunks'][0]['incremental'])
  self.assertEqual(r['diagnostics']['month_chunks'][0]['new_rows'],1)
  self.assertAlmostEqual(r['energy_summary']['generation']['kwh'],(1000+1500)/12/1000)
 def test_day_energy_uses_original_rows_and_splits_hours(self):
  t=datetime(2026,10,13,12,55,tzinfo=ZONE)
  for i in (0,5,10):self.append(t+timedelta(minutes=i),1000 if i!=5 else 2000)
  with patch.object(self.view,'month_series',side_effect=AssertionError('No reduction')):
   r=self.view.graph_data('day',t.date(),'Local',mode='energy')
  self.assertEqual(r['bucket'],'hour');self.assertEqual(len(r['points']),2)
  self.assertAlmostEqual(r['energy_summary']['generation']['kwh'],.25)
  power=self.view.graph_data('day',t.date(),'Local');self.assertEqual(power['kind'],'line')
  self.assertEqual(power['energy_summary'],r['energy_summary'])
 def test_zero_unknown_negative_balance_and_gap(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);a=self.row(t,pv=0,imp=300,exp=100);b=self.row(t+timedelta(minutes=10),pv=0,imp=300,exp=100)
  sums,cov={},{};accumulate(sums,cov,a,b,self.cfg)
  points=[dict(coverage_seconds=cov[k],**v) for k,v in sums.items()]
  r=summary(points,t,t+timedelta(minutes=10))
  self.assertEqual(r['generation']['kwh'],0)
  self.assertAlmostEqual(r['balance']['kwh'],-1/30)
  self.assertFalse(r['balance']['partial'])
  b['timestamp']=(t+timedelta(hours=2)).isoformat();sums,cov={},{};accumulate(sums,cov,a,b,self.cfg)
  r=summary([dict(coverage_seconds=cov[k],**v) for k,v in sums.items()],t,t+timedelta(hours=2))
  self.assertIsNone(r['generation']['kwh']);self.assertIsNone(r['balance']['kwh'])
 def test_counters_priority_and_source_change(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);a=self.row(t);b=self.row(t+timedelta(minutes=10))
  for direction in ('import','export'):
   a['grid_'+direction+'_counter_id']=b['grid_'+direction+'_counter_id']='meter'
   a['grid_'+direction+'_energy_total_kwh']=10
   b['grid_'+direction+'_energy_total_kwh']=11
  sums,cov={},{};accumulate(sums,cov,a,b,self.cfg)
  self.assertEqual(sums['2026-10']['grid_import_w'],1)
  b['grid_import_counter_id']='changed';b['grid_import_origin']='changed'
  sums,cov={},{};accumulate(sums,cov,a,b,self.cfg)
  self.assertIsNone(sums['2026-10']['grid_import_w'])
 def test_dst_hour_energy_preserves_both_folds(self):
  # Europe/Kyiv repeats 03:00 on October 25, 2026.
  self.cfg.max_integration_gap_s=7200
  a=self.row(datetime(2026,10,25,3,30,tzinfo=ZONE,fold=0))
  b=self.row(datetime(2026,10,25,3,30,tzinfo=ZONE,fold=1))
  sums,cov={},{};accumulate(sums,cov,a,b,self.cfg,hourly=True)
  self.assertEqual(len(sums),2)
  self.assertAlmostEqual(sum(v['pv_w'] for v in sums.values()),1.)
 def test_cancel_and_invalid_mode(self):
  with self.assertRaises(ValueError):self.view.graph_data('month',date(2026,10,1),mode='bad')
  with self.assertRaises(ValueError):self.view.graph_data('month',date(2026,10,1),mode='energy',cancelled=lambda:True)
  with self.assertRaises(ValueError):self.view.graph_data('year',date(2026,10,1),mode='power')
 def test_month_boundary_matches_year_bucket_without_double_count(self):
  t=datetime(2026,9,30,23,55,tzinfo=ZONE)
  for i in (0,10,15):self.append(t+timedelta(minutes=i))
  y=self.view.graph_data('year',date(2026,10,1),'Local')
  m=self.view.graph_data('month',date(2026,10,1),'Local',mode='energy')
  self.assertAlmostEqual(m['energy_summary']['generation']['kwh'],y['points'][1]['pv_w'])
  again=self.view.graph_data('month',date(2026,10,1),'Local',mode='energy')
  self.assertEqual(m['energy_summary'],again['energy_summary'])
  day=self.view.graph_data('day',date(2026,10,1),'Local',mode='energy')
  self.assertAlmostEqual(day['energy_summary']['generation']['kwh'],m['energy_summary']['generation']['kwh'])
 def test_empty_energy_is_unknown_and_legacy_power_is_unchanged(self):
  r=self.view.graph_data('month',date(2026,10,1),'SmartESS',mode='energy')
  self.assertEqual(r['points'],[])
  for k in ('generation','consumption','export','import','balance'):self.assertIsNone(r['energy_summary'][k]['kwh'])
  self.assertEqual(self.view.graph_data('month',date(2026,10,1),'Local')['kind'],'line')

if __name__=='__main__':unittest.main(verbosity=2)
