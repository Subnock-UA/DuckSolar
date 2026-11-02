import csv,json,sys,tempfile,unittest
from pathlib import Path
from datetime import date,datetime,timedelta
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.energy_streaming import MonthAccounting
from ducksolar.energy_accounting import ZONE
class Storage:
 readings=[]
 def list_meter_readings(self,**kw):return list(self.readings)
class Incremental(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.cfg=AppConfig(root_dir=self.temp.name,max_integration_gap_s=900,poll_interval_s=5);self.reader=HistoryReader(self.cfg);self.storage=Storage();self.storage.readings=[]
 def tearDown(self):self.temp.cleanup()
 def append(self,origin,instant,pv=100):
  path=self.reader.paths['inverter_logs' if origin=='Local' else 'history']/(instant.date().isoformat()+'.csv');path.parent.mkdir(parents=True,exist_ok=True)
  values=dict(time=instant.isoformat(),pv_w=pv,output_w=50,battery_v=52,charge_a=0,grid_v=230,grid_hz=50) if origin=='Local' else {'Timestamp':instant.isoformat(),'PV total Power':pv,'Output Active Power':50,'Battery Voltage':52,'Battery Charging Current':0,'AC Input Voltage':230,'AC Input Frequency':50}
  new=not path.exists()
  with path.open('a',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,list(values));
   if new:w.writeheader()
   w.writerow(values)
  return path
 def report(self,source,now):return MonthAccounting().report(HistoryReader(self.cfg),self.storage,self.cfg,date(2026,10,1),now=now,source=source)
 def full(self,source,now):
  folder=Path(self.cfg.root_dir)/'Data/EnergyAudit/inverter-1';summary=folder/f'2026-10-{source}.summary.json'
  # Remove only this test's derived summary; retain source and audit for comparison.
  summary.unlink();return self.report(source,now)
 def compare(self,a,b):
  self.assertEqual(a['input_count'],b['input_count'])
  for key in ('pv','inverter_import','inverter_export','house_meter'):self.assertEqual(a[key],b[key])
 def test_auto_new_day_resume_after_new_reader_and_audit_api(self):
  t=datetime(2026,10,12,23,55,tzinfo=ZONE)
  self.append('Local',t);self.append('Local',t+timedelta(minutes=1));self.append('SmartESS',t-timedelta(minutes=1))
  old=self.report('Auto',t+timedelta(minutes=2))
  self.append('Local',t+timedelta(minutes=5),200);self.append('Local',t+timedelta(minutes=6),300)
  now=t+timedelta(minutes=7);updated=self.report('Auto',now)
  self.assertTrue(updated['incremental']);self.assertEqual(updated['reused_input_count'],old['input_count']);self.assertEqual(updated['diagnostics']['used_records'],2)
  expected=self.full('Auto',now);self.compare(updated,expected)
  page=MonthAccounting().audit_page(self.cfg,date(2026,10,1),source='Auto',audit_id=expected['audit_id'],limit=100)
  self.assertTrue(all(isinstance(x,dict) for x in page['records']));self.assertTrue(any(x['type']=='interval' for x in page['records']))
 def test_auto_future_local_suppression_forces_safe_rebuild(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);self.append('Local',t);self.append('SmartESS',t+timedelta(seconds=40))
  self.report('Auto',t+timedelta(seconds=45));self.append('Local',t+timedelta(seconds=50))
  now=t+timedelta(seconds=55);actual=self.report('Auto',now)
  self.assertFalse(actual['incremental']);self.assertEqual(actual['diagnostics']['checkpoint_rejected'],'auto_merge_boundary');self.compare(actual,self.full('Auto',now))
 def test_model_edit_and_prefix_edit_invalidate(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);p=self.append('Local',t);self.append('Local',t+timedelta(minutes=1));now=t+timedelta(minutes=2);self.report('Local',now)
  self.cfg.pv_correction_factor+=.1;result=self.report('Local',now+timedelta(minutes=1));self.assertFalse(result['incremental']);self.assertEqual(result['diagnostics']['checkpoint_rejected'],'changed_model')
  p.write_bytes(p.read_bytes().replace(b',100,',b',900,'));result=self.report('Local',now+timedelta(minutes=2));self.assertFalse(result['incremental']);self.assertEqual(result['diagnostics']['checkpoint_rejected'],'edited_prefix');self.compare(result,self.full('Local',now+timedelta(minutes=2)))
if __name__=='__main__':unittest.main()
