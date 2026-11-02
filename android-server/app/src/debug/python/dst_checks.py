import sys,unittest
from datetime import datetime,timedelta,date
from types import SimpleNamespace
from pathlib import Path
from ducksolar.energy_accounting import ZONE,interval_energy,meter_segments
from ducksolar.energy_pair import Pair
from ducksolar.history_reader import HistoryReader
from ducksolar.graph_energy import accumulate
from ducksolar.graph_window import bounds
from ducksolar.display_retention import DisplayRetention
from ducksolar.grid_flow import valid_metric
class DST(unittest.TestCase):
 def test_full_days_energy_coverage_and_hour_buckets(self):
  for day,hours in [(date(2026,3,29),23),(date(2026,10,25),25)]:
   with self.subTest(day=day):
    start,end=bounds('day',day,'00:00','24:00');rows=[]
    for n in range(hours*12+1):
     rows.append(dict(timestamp=datetime.fromtimestamp(start.timestamp()+n*300,ZONE),pv_w=1000,output_w=500))
    self.assertEqual(HistoryReader.coverage_percent(rows),100)
    self.assertAlmostEqual(interval_energy(rows,'pv',start,end)['kwh'],hours)
    sums={};coverage={}
    for a,b in zip(rows,rows[1:]):accumulate(sums,coverage,a,b,SimpleNamespace(max_integration_gap_s=900),grid=False,start=start,end=end,hourly=True)
    self.assertEqual(len(sums),hours);self.assertAlmostEqual(sum(x['pv_w'] for x in sums.values()),hours)
 def test_fold_clip_and_pair_cache_distinguish_same_wall_time(self):
  def t(h,m,fold=0):return datetime(2026,10,25,h,m,tzinfo=ZONE,fold=fold)
  a=dict(timestamp=t(3,10),pv_w=1000);b=dict(timestamp=t(3,50,1),pv_w=1000)
  pair=Pair(a,b,7200)
  for fold in (0,1):
   start,end=t(3,20,fold),t(3,30,fold)
   result=pair.energy('pv',start,end)['intervals'][0]
   self.assertAlmostEqual(result['kwh'],1/6);self.assertEqual(result['start'],start.isoformat())
   self.assertAlmostEqual(interval_energy([a,b],'pv',start,end,7200)['kwh'],1/6)
 def test_clip_interval_across_backward_wall_clock(self):
  a=dict(timestamp=datetime(2026,10,25,3,50,tzinfo=ZONE,fold=0),pv_w=1000)
  b=dict(timestamp=datetime(2026,10,25,3,10,tzinfo=ZONE,fold=1),pv_w=1000)
  start=datetime(2026,10,25,3,55,tzinfo=ZONE,fold=0);end=datetime(2026,10,25,3,5,tzinfo=ZONE,fold=1)
  self.assertAlmostEqual(interval_energy([a,b],'pv',start,end,7200)['kwh'],1/6)
  self.assertAlmostEqual(Pair(a,b,7200).energy('pv',start,end)['intervals'][0]['kwh'],1/6)
 def test_meter_order_uses_actual_instants(self):
  a=dict(meter_id='x',reading_date='2026-10-25T03:50:00+03:00',import_day=0,import_night=0,export_day=0,export_night=0)
  b=dict(a,reading_date='2026-10-25T03:10:00+02:00',import_day=1)
  result=meter_segments([b,a],datetime.fromisoformat(a['reading_date']),datetime.fromisoformat(b['reading_date']))
  self.assertEqual(result['import_kwh'],1)
 def test_live_age_after_both_transitions(self):
  for raw in ['2026-03-29T02:59:55+02:00','2026-10-25T03:59:55+03:00']:
   old=datetime.fromisoformat(raw).astimezone(ZONE);now=datetime.fromtimestamp(old.timestamp()+10,ZONE)
   item=dict(value=100,unit='W',quality='good',timestamp=old.isoformat())
   self.assertTrue(valid_metric(item,'W',now))
   retention=DisplayRetention(clock=lambda:100);retention.update({'grid.power':item},'a',now)
   self.assertAlmostEqual(retention.apply({},'a',True)['grid.power']['age_s'],10)
 def test_bad_window_boundaries_fail_explicitly(self):
  for day in (date(2026,3,29),date(2026,10,25)):
   with self.assertRaises(ValueError):bounds('day',day,'03:15','04:30')
if __name__=='__main__':unittest.main(verbosity=2)
def run():
 import io,json
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
