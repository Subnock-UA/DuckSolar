import sys,json,tempfile,unittest,hashlib,copy
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'main/python'),str(Path(__file__).resolve().parents[5])]
from ducksolar.display_retention import DisplayRetention
from ducksolar.compact_history import Codec,schema_path,compatible_schema,schema_contract
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.energy_streaming import MonthAccounting
from ducksolar.energy_accounting import ZONE
class Patch28(unittest.TestCase):
 def test_auxiliary_survives_omission_but_expires_and_scope_changes(self):
  now=[100.];r=DisplayRetention(lambda:now[0]);instant=datetime(2026,10,19,tzinfo=timezone.utc)
  r.update({'temperature.inverter':{'value':0,'quality':'good'}},'a',instant)
  now[0]=160;m=r.apply({'temperature.inverter':{'value':None}},'a',True)
  self.assertEqual(m['temperature.inverter']['value'],0);self.assertEqual(m['temperature.inverter']['age_s'],60)
  now[0]=191;self.assertIsNone(r.apply({},'a',True)['temperature.inverter']['value'])
  self.assertEqual(r.apply({},'b',True),{})
 def test_timestamp_is_actual_receipt_not_render(self):
  now=[100.];r=DisplayRetention(lambda:now[0]);instant=datetime(2026,10,19,tzinfo=timezone.utc)
  r.update({'temperature.inverter':{'value':30,'timestamp':(instant-timedelta(seconds=4)).isoformat()}},'a',instant)
  now[0]+=5;self.assertEqual(9,r.apply({},'a',True)['temperature.inverter']['age_s'])
  self.assertTrue(r.apply({'x':{'value':1}},'a',False)['x']['stale'])
 def test_schema_extension_proven_without_accepting_existing_edits(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'x.csv';c=Codec(p,['time','pv_w','normalized_json'])
   a=dict(time='2026-10-19T01:00:00+03:00',pv_w='100',normalized_json=json.dumps({'metrics':{'a':{'value':1}}}))
   c.append(a);sha=hashlib.sha256(schema_path(p).read_bytes()).hexdigest();old=copy.deepcopy(c.schema)
   c.append(dict(a,normalized_json=json.dumps({'metrics':{'a':{'value':1},'b':{'value':2}}})))
   self.assertTrue(compatible_schema(c.schema,sha));self.assertTrue(compatible_schema(c.schema,sha,schema_contract(old)))
   c.schema['defaults']['pv_w']='999';self.assertFalse(compatible_schema(c.schema,sha));self.assertFalse(compatible_schema(c.schema,sha,schema_contract(old)))
 def test_append_template_keeps_balance_incremental_with_full_equivalence(self):
  with tempfile.TemporaryDirectory() as td:
   cfg=AppConfig(root_dir=td);reader=HistoryReader(cfg);p=reader.paths['inverter_logs']/'2026-10-19.csv';p.parent.mkdir(parents=True,exist_ok=True)
   class Store:
    def list_meter_readings(self,**kw):return []
   t=datetime(2026,10,19,12,tzinfo=ZONE)
   def append(offset,extra=False):
    row=dict(time=(t+timedelta(seconds=offset)).isoformat(),pv_w=100,output_w=50,battery_v=52,charge_a=0,grid_v=230,grid_hz=50,normalized_json=json.dumps({'metrics':{'x':{'value':1},**({'y':{'value':2}} if extra else {})}}))
    Codec(p,list(row)).append(row)
   append(0);append(5)
   def report():return MonthAccounting().report(HistoryReader(cfg),Store(),cfg,date(2026,10,1),now=t+timedelta(minutes=1),source='Local')
   old=report();append(10,True);actual=report()
   self.assertTrue(actual['incremental']);self.assertEqual(1,actual['diagnostics']['used_records']);self.assertEqual(1,actual['diagnostics']['read_records']);self.assertEqual(1,actual['diagnostics']['compatible_schema_extensions'])
   summary=Path(td)/'Data/EnergyAudit/inverter-1/2026-10-Local.summary.json';summary.unlink();expected=report()
   for key in ('pv','inverter_import','inverter_export'):self.assertEqual(expected[key],actual[key])


def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Patch28))
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
