import sys,json,tempfile,copy,gzip,hashlib,unittest,shutil
from pathlib import Path
from datetime import date,datetime
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'main/python'),str(Path(__file__).resolve().parents[5])]
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.energy_streaming import MonthAccounting,_files
from ducksolar.balance_portable import revision,load
from ducksolar.energy_accounting import ZONE
class Store:
 def __init__(self):self.rows=[dict(id=1,meter_id=1,reading_date='2026-08-01 00:00:00',import_day=100,import_night=0,export_day=20,export_night=0),dict(id=2,meter_id=1,reading_date='2026-09-01 00:00:00',import_day=200,import_night=0,export_day=40,export_night=0)]
 def list_meter_readings(self,**kw):return copy.deepcopy(self.rows)
class Portable29(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cfg=AppConfig(root_dir=str(self.root));self.store=Store();self.now=datetime(2026,10,19,tzinfo=ZONE);self.anchor=date(2026,8,1);self.stem='2026-08-Local';self.reader=HistoryReader(self.cfg)
  self.source=self.reader.paths['inverter_logs']/'2026-08-01.csv';self.source.parent.mkdir(parents=True,exist_ok=True);self.source.write_text('time,pv_w,output_w,battery_v,charge_a,grid_v,grid_hz\n2026-08-01T12:00:00+03:00,100,50,52,0,230,50\n2026-08-01T12:01:00+03:00,200,80,52,0,230,50\n')
  self.base=MonthAccounting().report(self.reader,self.store,self.cfg,self.anchor,now=self.now,source='Local');self.target=self.root/'Data/EnergyAudit/inverter-1';self.cache=self.target/(self.stem+'.summary.json');summary=json.loads(self.cache.read_text());self.sig=copy.deepcopy(summary['checkpoint']['signature'])
  MonthAccounting().audit_page(self.cfg,self.anchor,source='Local',audit_id=self.base['audit_id'])
  ledger=self.target/(self.stem+'.audit.jsonl');raw=ledger.read_bytes();self.base['audit_id']=hashlib.sha256(raw).hexdigest()
  self.package=self.root/'Data/CompactHistory/packages'/('a'*64);(self.package/'history').mkdir(parents=True);(self.package/'balances').mkdir();(self.package.parent.parent/'current.json').write_text(json.dumps(dict(generation='a'*64,device_id='inverter-1')))
  self.audit=self.package/'balances'/(self.stem+'.audit.jsonl.gz')
  with gzip.open(self.audit,'wb') as f:f.write(raw)
  files=_files(self.reader,datetime(2026,8,1,tzinfo=ZONE),datetime(2026,9,1,tzinfo=ZONE),'Local',lambda:False)
  value=dict(revision=revision(self.reader,files,self.sig,lambda:False),report=self.base,audit_bytes=len(raw));self.balance=self.package/'balances'/(self.stem+'.json');self.balance.write_text(json.dumps(value))
  self.manifest=dict(device_id='inverter-1',model=dict(self.reader.model_signature()),model_types={k:'float' if isinstance(v,float) else 'int' for k,v in self.reader.model_signature()},readings_json=json.dumps(self.store.rows),files=[])
  self.publish()
 def tearDown(self):self.tmp.cleanup()
 def publish(self):
  self.manifest['files']=[dict(name=p.relative_to(self.package).as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (self.balance,self.audit)]
  (self.package/'manifest.json').write_text(json.dumps(self.manifest))
 def report(self):return MonthAccounting().report(HistoryReader(self.cfg),self.store,self.cfg,self.anchor,now=self.now,source='Local')
 def later(self):self.store.rows.append(dict(self.store.rows[-1],id=3,reading_date='2026-10-17 12:00:00',import_day=300))
 def test_exact_original_package_supported(self):
  actual=self.report();self.assertTrue(actual['portable_cache_hit']);self.assertEqual('exact_revision',actual['diagnostics']['portable_cache_reason']);self.assertEqual(self.base['pv'],actual['pv'])
 def test_later_meter_reading_reuses_without_any_inverter_iteration(self):
  self.later()
  with patch('ducksolar.energy_streaming._ordered_rows',side_effect=AssertionError('No inverter iteration allowed')):actual=self.report()
  self.assertTrue(actual['portable_cache_hit']);self.assertTrue(actual['meter_recalculated']);self.assertEqual('meter_rebased',actual['diagnostics']['portable_cache_reason']);self.assertEqual(self.base['house_meter'],actual['house_meter'])
  for key in ('pv','inverter_import','inverter_export'):self.assertEqual(self.base[key],actual[key])
 def test_changed_in_period_reading_updates_only_household(self):
  self.store.rows[-1]['import_day']=250
  with patch('ducksolar.energy_streaming._ordered_rows',side_effect=AssertionError('No inverter iteration allowed')):actual=self.report()
  self.assertNotEqual(self.base['house_meter'],actual['house_meter']);self.assertEqual(self.base['pv'],actual['pv'])
 def test_rebased_audit_has_current_meter_rows_and_stable_pagination(self):
  self.later();actual=self.report();account=MonthAccounting();rows=[];offset=0
  for _ in range(20):
   page=account.audit_page(self.cfg,self.anchor,source='Local',audit_id=actual['audit_id'],offset=offset,limit=2);rows+=page['records'];offset=page['next_offset']
   if page['done']:break
  meter=[r['row'] for r in rows if r['type']=='meter_reading'];self.assertEqual(self.store.rows,meter)
  self.assertEqual(actual['audit_id'],[r for r in rows if r['type']=='summary'][0]['report']['audit_id']);self.assertTrue(any(r['type']=='input' for r in rows));self.assertTrue(any(r['type']=='interval' for r in rows))
  saved=json.loads(self.cache.read_text(encoding='utf-8'));mtime=(self.target/(self.stem+'.audit.jsonl')).stat().st_mtime_ns
  self.report();account.audit_page(self.cfg,self.anchor,source='Local',audit_id=actual['audit_id']);self.assertEqual(mtime,(self.target/(self.stem+'.audit.jsonl')).stat().st_mtime_ns)
 def test_multiple_meter_edits_do_not_reuse_old_audit_identity(self):
  self.later();a=self.report();self.store.rows[-1]['import_day']=310;b=self.report();self.assertNotEqual(a['audit_id'],b['audit_id']);self.assertEqual(a['pv'],b['pv'])
  with self.assertRaises(ValueError):MonthAccounting().audit_page(self.cfg,self.anchor,source='Local',audit_id=a['audit_id'])
 def test_model_change_rejects_old_inverter_values(self):
  self.cfg.pv_correction_factor=1.1;actual=self.report();self.assertFalse(actual.get('portable_cache_hit',False));self.assertEqual('model_changed',actual['diagnostics']['portable_cache_miss'])
 def test_source_edit_rejects_old_inverter_values(self):
  self.source.write_text(self.source.read_text().replace(',100,',',900,'));actual=self.report();self.assertFalse(actual.get('portable_cache_hit',False));self.assertEqual('inverter_revision_changed',actual['diagnostics']['portable_cache_miss'])
 def test_member_corruption_is_reported_without_accepting_old_values(self):
  self.balance.write_bytes(self.balance.read_bytes()+b' ');actual=self.report();self.assertFalse(actual.get('portable_cache_hit',False));self.assertEqual('package_member_checksum',actual['diagnostics']['portable_cache_miss'])
 def test_corrupt_lazy_audit_cannot_replace_previous_destination(self):
  self.later();actual=self.report();destination=self.target/(self.stem+'.audit.jsonl');old=destination.read_bytes();self.audit.write_bytes(self.audit.read_bytes()[:-8])
  with self.assertRaises((ValueError,OSError,EOFError)):MonthAccounting().audit_page(self.cfg,self.anchor,source='Local',audit_id=actual['audit_id'])
  self.assertEqual(old,destination.read_bytes());self.assertEqual([],list(self.target.glob('.audit-*.tmp')))
 def test_cancellation_prevents_cache_publication(self):
  self.later();old=self.cache.read_bytes()
  with self.assertRaises(ValueError):MonthAccounting().report(HistoryReader(self.cfg),self.store,self.cfg,self.anchor,now=self.now,source='Local',cancelled=lambda:True)
  self.assertEqual(old,self.cache.read_bytes())

 def test_changed_algorithm_rejected_with_specific_reason(self):
  value=json.loads(self.balance.read_text());value['report']['algorithm']='other';self.balance.write_text(json.dumps(value));self.publish();actual=self.report();self.assertEqual('changed_algorithm',actual['diagnostics']['portable_cache_miss']);self.assertFalse(actual.get('portable_cache_hit',False))
 def test_invalid_manifest_readings_safe_fallback(self):
  self.later();self.manifest['readings_json']='null';self.publish();actual=self.report();self.assertEqual('invalid_original_readings',actual['diagnostics']['portable_cache_miss']);self.assertFalse(actual.get('portable_cache_hit',False))


def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Portable29))
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
