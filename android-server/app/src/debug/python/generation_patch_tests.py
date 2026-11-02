import sys,csv,json,tempfile,unittest,tracemalloc,time
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from dataclasses import asdict
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'main/python'),str(Path(__file__).resolve().parents[5])]
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.balance import summarize_day
from ducksolar.generation_summary import summarize
from ducksolar.energy_accounting import ZONE

class Generation(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.cfg=AppConfig(root_dir=str(self.root),max_integration_gap_s=900)
  self.reader=HistoryReader(self.cfg);self.day=date(2025,10,26)
 def tearDown(self):self.temp.cleanup()
 def write(self,name,origin,offsets):
  p=self.root/name
  fields=['time','pv_w','output_w','battery_v','charge_a','grid_v','grid_hz'] if origin=='Local' else ['Timestamp','PV total Power','Output Active Power','Battery Voltage','Battery Charging Current','AC Input Voltage','AC Input Frequency']
  start=datetime.combine(self.day,datetime.min.time(),ZONE).astimezone(timezone.utc)
  with p.open('w',encoding='utf-8',newline='') as f:
   w=csv.writer(f);w.writerow(fields)
   for n,offset in enumerate(offsets):w.writerow([(start+timedelta(seconds=offset)).astimezone(ZONE).isoformat(),1000+n,500,52,1,230,50])
  return p
 def files(self,local,smart):
  self.reader.find_day_files=lambda day:(local,smart)
  self.reader.available_dates=lambda:[self.day]
  self.reader._file_index={self.day:(local,smart)}
 def compare(self):
  old=asdict(summarize_day(self.reader,self.day,'Auto',900));old['day']=old['day'].isoformat()
  new=summarize(self.reader,self.day)
  self.assertEqual(old.keys(),new.keys())
  for key in old:
   if key=='day':self.assertEqual(old[key],new[key])
   else:self.assertAlmostEqual(old[key],new[key],places=10,msg=key)
  self.assertFalse(self.reader._cache);self.assertFalse(self.reader._append_cache)
  self.assertFalse(list((self.root/'Data/EnergyWork/Generation').glob('*.db')))
 def test_auto_duplicates_unsorted_gaps_and_dst(self):
  p=self.write('local.csv','Local',[600,0,300,300,7200,7210,7220])
  s=self.write('ess.csv','SmartESS',[0,10,30,90,400,700,850,910,7205])
  self.files([p],[s]);self.compare()
 def test_ess_only(self):
  p=self.write('ess.csv','SmartESS',[0,300,600,900]);self.files([],[p]);self.compare()
 def test_compact_originals_not_changed(self):
  from ducksolar.compact_history import convert
  p=self.write('original.csv','Local',range(0,3600,10));compact=self.root/'compact.csv'
  convert(p,compact);original=p.read_bytes();self.files([compact],[]);self.compare();self.assertEqual(original,p.read_bytes())
 def test_no_day_loading_and_valid_cache_reused(self):
  p=self.write('local.csv','Local',[0,300,600]);self.files([p],[])
  view=HistoryViews(self.reader,self.cfg,'inverter-1');updates=[]
  with patch.object(self.reader,'load_day',side_effect=AssertionError('Full day forbidden')):
   result=view.generation_sync(progress=lambda a,b:updates.append((a,b)))
   with patch('ducksolar.generation_summary.summarize',side_effect=AssertionError('Valid cache reused')):
    self.assertFalse(view.generation_sync(result['manifest'])['changed'])
  self.assertTrue(result['changed'][0]['summary']['pv_kwh']>0);self.assertEqual(updates[-1],(1,1))
 def test_cancellation_frees_index_and_no_partial_summary(self):
  p=self.write('local.csv','Local',range(2000));self.files([p],[]);count=0
  def cancelled():
   nonlocal count
   count+=1;return count>100
  view=HistoryViews(self.reader,self.cfg,'inverter-1')
  with self.assertRaises(ValueError):view.generation_sync(cancelled=cancelled)
  self.assertFalse(view.cache);self.assertFalse(self.reader._cache)
  self.assertFalse(list((self.root/'Data/EnergyWork/Generation').glob('*.db')))
 def test_dense_stream_has_small_python_peak(self):
  p=self.write('dense.csv','Local',range(20000));self.files([p],[])
  tracemalloc.start();start=time.monotonic();result=summarize(self.reader,self.day)
  peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
  self.assertEqual(20000,result['records']);self.assertLess(peak,12*1024**2)
  print('DENSE_FIXTURE',json.dumps(dict(records=20000,python_peak_bytes=peak,seconds=round(time.monotonic()-start,3))),flush=True)

if __name__=='__main__':unittest.main(verbosity=2)
