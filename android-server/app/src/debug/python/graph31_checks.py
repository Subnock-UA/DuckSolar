import csv,io,json,tempfile,unittest
from pathlib import Path
from datetime import date,datetime
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.energy_accounting import ZONE
from ducksolar.graph_window import bounds,clip
class Graph31(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.cfg=AppConfig(root_dir=self.temp.name,max_integration_gap_s=7200);self.reader=HistoryReader(self.cfg);self.view=HistoryViews(self.reader,self.cfg,'inverter-1');self.day=date(2026,10,19)
  self.path=self.reader.paths['inverter_logs']/'2026-10-19.csv';self.path.parent.mkdir(parents=True,exist_ok=True);self.write()
 def tearDown(self):self.temp.cleanup()
 def write(self,third=3000):
  with self.path.open('w',encoding='utf-8',newline='') as f:
   w=csv.writer(f);w.writerow(['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz'])
   for h,p in [(8,1000),(9,2000),(10,third)]:w.writerow([f'2026-10-19 {h:02d}:00:00',p,500,52,0,230,50])
 def graph(self,mode='power',**kw):return self.view.graph_data('day',self.day,fields=['pv_w','output_w'],mode=mode,**kw)
 def test_window_interpolates_edges_and_totals_from_full_input(self):
  r=self.graph(window_start='08:30',window_end='09:30');self.assertEqual([p['pv_w'] for p in r['points']],[1500,2000,2500]);self.assertAlmostEqual(r['energy_summary']['generation']['kwh'],2);self.assertAlmostEqual(r['energy_summary']['consumption']['kwh'],.5)
 def test_energy_and_power_window_totals_match(self):
  p=self.graph(window_start='08:30',window_end='09:30');e=self.graph('energy',window_start='08:30',window_end='09:30');self.assertEqual(p['energy_summary'],e['energy_summary']);self.assertEqual(e['bucket'],'hour')
 def test_full_day_remains_same_as_explicit_full_window(self):
  self.assertEqual(self.graph()['energy_summary'],self.graph(window_start='00:00',window_end='24:00')['energy_summary'])
 def test_missing_interval_not_interpolated_or_zero_filled(self):
  self.cfg.max_integration_gap_s=900;r=self.graph(window_start='08:30',window_end='09:30');self.assertEqual(len(r['points']),1);self.assertIsNone(r['energy_summary']['generation']['kwh']);self.assertTrue(r['energy_summary']['generation']['partial'])
 def test_scalar_rows_equal_legacy_energy_values(self):
  old=self.reader.graph_day_rows(self.day);new=self.reader.energy_graph_rows(self.day)
  keys=['pv_w','output_w','grid_import_w','grid_export_w','grid_import_source','grid_export_source']
  self.assertEqual([{k:r.get(k) for k in keys} for r in old],[{k:r.get(k) for k in keys} for r in new])
 def test_same_size_edit_invalidates_scalar_projection(self):
  before=self.graph()['energy_summary']['generation']['kwh'];self.write(9000);after=self.graph()['energy_summary']['generation']['kwh'];self.assertGreater(after,before)
 def test_cancellation_never_publishes_partial_graph(self):
  with self.assertRaises(ValueError):self.graph(cancelled=lambda:True)
 def test_non_energy_fields_still_use_full_reader(self):
  r=self.view.graph_data('day',self.day,fields=['battery_v'],window_start='08:30',window_end='09:30');self.assertTrue(all(p['battery_v']==52 for p in r['points']))
 def test_invalid_or_overnight_window_rejected(self):
  for a,b in [('25:00','26:00'),('12:00','08:00'),('24:00','24:00'),('08:00','08:00'),('8:00','09:00')]:
   with self.assertRaises(ValueError):bounds('day',self.day,a,b)
  with self.assertRaises(ValueError):bounds('month',self.day,'08:00','09:00')
 def test_dst_ambiguous_and_missing_boundary_rejected(self):
  for day in (date(2026,3,29),date(2026,10,25)):
   with self.assertRaises(ValueError):bounds('day',day,'03:15','04:30')
  self.assertEqual((bounds('day',date(2026,10,25),'00:00','24:00')[1].timestamp()-bounds('day',date(2026,10,25),'00:00','24:00')[0].timestamp())/3600,25)
 def test_endpoints_match_legacy_with_unsorted_rows_and_auto_suppression(self):
  self.path.write_text('time,pv_w,output_w,battery_v,charge_a,grid_v,grid_hz\n2026-10-19 10:00:00,3000,500,52,0,230,50\n2026-10-19 08:00:00,1000,500,52,0,230,50\n2026-10-19 09:00:00,2000,500,52,0,230,50\n',encoding='utf-8')
  smart=self.reader.paths['history']/'2026-10-19.csv';smart.parent.mkdir(parents=True,exist_ok=True)
  smart.write_text('Timestamp,PV total Power,Output Active Power,Battery Voltage,Battery Charging Current,AC Input Voltage,AC Input Frequency\n2026-10-19 10:00:05,9000,500,52,0,230,50\n2026-10-19 07:00:00,500,500,52,0,230,50\n',encoding='utf-8')
  self.reader.available_dates(True)
  for source in ('Auto','Local','SmartESS'):
   rows=self.reader.graph_day_rows(self.day,source);edges=self.reader.graph_endpoints(self.day,source)
   for key,row in [('first',rows[0]),('last',rows[-1])]:
    self.assertEqual(row['timestamp'],edges[key]['timestamp']);self.assertEqual(row['pv_w'],edges[key]['pv_w'])
 def test_endpoints_use_compact_default_timestamp(self):
  from ducksolar.compact_history import Codec
  self.path.unlink();codec=Codec(self.path,['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz','normalized_json'])
  row=dict(time='2026-10-19 08:00:00',pv_w='1000',output_w='500',battery_v='52',charge_a='0',grid_v='230',grid_hz='50',normalized_json='{}')
  codec.append(row);codec.append(dict(row,time='2026-10-19 09:00:00',pv_w='2000'))
  edges=self.reader.graph_endpoints(self.day);self.assertEqual(edges['first']['timestamp'].hour,8);self.assertEqual(edges['last']['timestamp'].hour,9)
 def test_source_change_does_not_interpolate_grid_power(self):
  a,b=bounds('day',self.day,'08:30','09:30');rows=[dict(timestamp=datetime(2026,10,19,h,tzinfo=ZONE),grid_import_w=100,grid_import_source=kind,grid_import_origin='x') for h,kind in [(8,'measured'),(9,'estimated'),(10,'estimated')]]
  r=clip(rows,a,b,7200);self.assertIsNone(r[0]['grid_import_w']);self.assertEqual(r[-1]['grid_import_w'],100)
def run():
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Graph31))
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
if __name__=='__main__':unittest.main()
