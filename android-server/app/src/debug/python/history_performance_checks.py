import csv,json,sys,tempfile,unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'main/python')]
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.energy_streaming import MonthAccounting,_json
from ducksolar.energy_accounting import ZONE
class Storage:
 def list_meter_readings(self,**kw):return []
class PerformancePatch(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.cfg=AppConfig(root_dir=self.tmp.name,poll_interval_s=5);self.reader=HistoryReader(self.cfg);self.view=HistoryViews(self.reader,self.cfg,'inverter-1')
 def tearDown(self):self.tmp.cleanup()
 def append(self,t,power=100,origin='Local'):
  p=self.reader.paths['inverter_logs' if origin=='Local' else 'history']/(t.date().isoformat()+'.csv');p.parent.mkdir(parents=True,exist_ok=True)
  row=dict(time=t.isoformat(),pv_w=power,output_w=power/2,grid_v=230,grid_hz=50) if origin=='Local' else {'Timestamp':t.isoformat(),'PV total Power':power,'Output Active Power':power/2}
  new=not p.exists()
  with p.open('a',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,list(row))
   if new:w.writeheader()
   w.writerow(row)
  self.reader.available_dates(refresh=True);return p
 def balance(self,t):return MonthAccounting().report(HistoryReader(self.cfg),Storage(),self.cfg,date(2026,10,1),now=t,source='Auto')
 def test_old_checkpoint_without_local_boundary_does_not_rebuild_local_only(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);self.append(t);self.append(t+timedelta(seconds=5));self.balance(t+timedelta(seconds=6))
  p=Path(self.tmp.name)/'Data/EnergyAudit/inverter-1/2026-10-Auto.summary.json';obj=json.loads(p.read_text());obj['checkpoint'].pop('merge_last_local');p.write_text(_json(obj))
  self.append(t+timedelta(seconds=10));r=self.balance(t+timedelta(seconds=11));self.assertTrue(r['incremental']);self.assertEqual(r['diagnostics']['used_records'],1)
 def test_input_segments_no_copy_and_lazy_audit_identical_totals(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE)
  for i in range(3):self.append(t+timedelta(minutes=i))
  a=self.balance(t+timedelta(minutes=3));target=Path(self.tmp.name)/'Data/EnergyAudit/inverter-1';self.assertFalse((target/'2026-10-Auto.audit.jsonl').exists())
  summary=json.loads((target/'2026-10-Auto.summary.json').read_text());first=summary['input_parts'][0];before=Path(first['path']).read_bytes()
  self.append(t+timedelta(minutes=4));b=self.balance(t+timedelta(minutes=5));self.assertEqual(b['diagnostics']['audit_copy_bytes'],0);self.assertEqual(Path(first['path']).read_bytes(),before)
  rows=[];offset=0
  while True:
   page=MonthAccounting().audit_page(self.cfg,date(2026,10,1),'Auto',b['audit_id'],offset,2);rows.extend(page['records']);offset=page['next_offset']
   if page['done']:break
  self.assertEqual(sum(x['type']=='input' for x in rows),4)
  total=sum(i['kwh'] for x in rows if x['type']=='interval' and x['direction']=='pv' for i in x['intervals']);self.assertEqual(total,b['pv']['kwh'])
  self.assertEqual(rows[-1]['report']['audit_id'],b['audit_id'])
  self.assertTrue(self.balance(t+timedelta(minutes=5))['cache_hit'])
 def test_year_month_cache_reuses_closed_month_after_append_and_restart(self):
  sept=datetime(2026,9,30,23,55,tzinfo=ZONE);oct=datetime(2026,10,1,0,5,tzinfo=ZONE)
  self.append(sept);self.append(oct);self.append(oct+timedelta(minutes=5))
  a=self.view.graph_data('year',date(2026,10,1),'Auto');self.assertEqual(len(a['points']),2)
  self.append(oct+timedelta(minutes=10),200)
  reader=HistoryReader(self.cfg);view=HistoryViews(reader,self.cfg,'inverter-1')
  b=view.graph_data('year',date(2026,10,1),'Auto');chunks=b['diagnostics']['month_chunks'];self.assertTrue(chunks[0]['cache_hit']);self.assertTrue(chunks[1]['incremental']);self.assertEqual(chunks[1]['new_rows'],1)
  self.assertEqual(a['points'][0],b['points'][0]);self.assertEqual(b['records'],4)
 def test_snapshot_append_during_calculation_is_saved_then_resumed(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);self.append(t);self.append(t+timedelta(minutes=1))
  import ducksolar.month_graph as graph
  original=graph.write_json;changed=[]
  def publish(p,obj):
   if not changed:self.append(t+timedelta(minutes=2));changed.append(True)
   return original(p,obj)
  with patch.object(graph,'write_json',side_effect=publish):a=self.view.graph_data('year',date(2026,10,1),'Auto')
  self.assertEqual(a['records'],2)
  b=self.view.graph_data('year',date(2026,10,1),'Auto');self.assertEqual(b['records'],3);self.assertTrue(b['diagnostics']['month_chunks'][0]['incremental']);self.assertEqual(b['diagnostics']['month_chunks'][0]['new_rows'],1)
 def test_cold_graph_does_not_prepare_full_history_objects(self):
  t=datetime(2026,9,1,12,tzinfo=ZONE);self.append(t);self.append(t+timedelta(minutes=1))
  with patch('ducksolar.prepared_history.PreparedHistory.prepare',side_effect=AssertionError('Full preparation forbidden')):
   r=self.view.graph_data('year',date(2026,9,1),'Auto');self.assertEqual(r['records'],2)
   day=self.view.graph_data('day',date(2026,9,1),'Auto');self.assertEqual(day['records'],2)
 def test_corrupt_input_segment_rebuilds_balance(self):
  t=datetime(2026,10,13,12,tzinfo=ZONE);self.append(t);self.append(t+timedelta(minutes=1));a=self.balance(t+timedelta(minutes=2))
  p=Path(self.tmp.name)/'Data/EnergyAudit/inverter-1/2026-10-Auto.summary.json';summary=json.loads(p.read_text());Path(summary['input_parts'][0]['path']).write_bytes(b'broken')
  b=self.balance(t+timedelta(minutes=2));self.assertFalse(b['incremental']);self.assertEqual(a['pv'],b['pv'])
 def test_typed_index_preserves_large_integer_boolean_and_zero(self):
  from ducksolar.energy_streaming import _input_database,_insert_inputs,_projection_cursor
  con=_input_database(Path(self.tmp.name)/'typed.db')
  try:
   row=dict(timestamp='2026-10-13T12:00:00+03:00',pv_w=False,output_w=0,grid_import_energy_total_kwh=2**70)
   _insert_inputs(con,[(10,row)]);con.commit()
   actual=list(_projection_cursor(con,dict(range_start=0,range_end=20),None))[0][1]
   self.assertIs(actual['pv_w'],False);self.assertEqual(actual['output_w'],0);self.assertEqual(actual['grid_import_energy_total_kwh'],2**70)
  finally:con.close()
 def test_schema_default_timestamp_is_read_and_old_checkpoint_is_repaired(self):
  from ducksolar.compact_history import Codec
  t=datetime(2026,10,13,12,tzinfo=ZONE)
  path=self.reader.paths['inverter_logs']/'2026-10-13.csv';codec=Codec(path,['time','pv_w','output_w','normalized_json'])
  for i in range(2):codec.append(dict(time=(t+timedelta(minutes=i)).isoformat(),pv_w=100,output_w=50,normalized_json={}))
  a=self.balance(t+timedelta(minutes=2));self.assertEqual(a['input_count'],2);self.assertAlmostEqual(a['pv']['kwh'],100/60/1000)
  p=Path(self.tmp.name)/'Data/EnergyAudit/inverter-1/2026-10-Auto.summary.json';value=json.loads(p.read_text());value['checkpoint']['signature'].pop('input_semantics');p.write_text(_json(value))
  b=self.balance(t+timedelta(minutes=3));self.assertFalse(b['incremental']);self.assertEqual(b['diagnostics']['checkpoint_rejected'],'changed_input_semantics');self.assertEqual(b['input_count'],2)
if __name__=='__main__':unittest.main(verbosity=2)

def run():
 import io
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(PerformancePatch)
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream).run(suite)
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
