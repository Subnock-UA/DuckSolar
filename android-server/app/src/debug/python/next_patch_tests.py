import sys,json,tempfile,unittest,importlib.util,time,csv
from pathlib import Path
from datetime import date,datetime,timedelta
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[5]
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.prepared_history import PreparedHistory,import_package,export_package
from ducksolar.energy_streaming import MonthAccounting
class Storage:
 def list_meter_readings(self,**kwargs):return []
class NextPatch(unittest.TestCase):
 def test_live_append_and_modified_prefix_are_both_read_correctly(self):
  with tempfile.TemporaryDirectory() as temp:
   reader=HistoryReader(AppConfig(root_dir=temp));path=Path(temp)/'2026-09-01.csv'
   path.write_text('time,pv_w,output_w\n'+''.join(f'2026-09-01T12:{i:02d}:00,100,50\n' for i in range(30)))
   first=reader._read_file(path,'Local',date(2026,9,1),compact=True)
   self.assertEqual(len(first),30)
   with path.open('a') as out:out.write('2026-09-01T12:30:00,200,50\n')
   self.assertEqual(len(reader._read_file(path,'Local',date(2026,9,1),compact=True)),31)
   text=path.read_text().replace('12:25:00,100','12:25:00,900')
   path.write_text(text+'2026-09-01T12:31:00,300,50\n')
   actual=list(reader._read_file(path,'Local',date(2026,9,1),compact=True).values())
   self.assertEqual(len(actual),32);self.assertEqual(actual[25]['pv_w'],900)
 def test_index_reuse_and_identical_archives_keep_totals(self):
  with tempfile.TemporaryDirectory() as temp:
   cfg=AppConfig(root_dir=temp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   p=folder/'2026-09-01.csv'
   with p.open('w',newline='') as out:
    w=csv.DictWriter(out,fieldnames=['time','pv_w','output_w']);w.writeheader()
    for i in range(800):w.writerow(dict(time=(datetime(2026,9,1)+timedelta(seconds=i*5)).isoformat(),pv_w=1000,output_w=500))
   duplicate=folder/'copies/2026-09-01.csv';duplicate.parent.mkdir();duplicate.write_bytes(p.read_bytes())
   store=PreparedHistory(reader);store.prepare(p,'Local',date(2026,9,1))
   service=MonthAccounting();one=service.report(reader,Storage(),cfg,date(2026,9,1),now=datetime(2026,9,2))
   # Exercise the lower-level index independently of the new month checkpoint.
   (Path(temp)/'Data/EnergyAudit/inverter-1/2026-09-Auto.summary.json').unlink()
   with patch.object(PreparedHistory,'rows',side_effect=lambda *a,**k:iter(())):
    two=service.report(HistoryReader(cfg),Storage(),cfg,date(2026,9,1),now=datetime(2026,9,3))
   self.assertEqual(one['pv']['kwh'],two['pv']['kwh']);self.assertEqual(two['diagnostics']['prepared_index_hits'],1)
   self.assertEqual(two['diagnostics']['identical_files_skipped'],1)
 def test_month_hourly_cache_matches_period_pass_and_invalidates(self):
  with tempfile.TemporaryDirectory() as temp:
   cfg=AppConfig(root_dir=temp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   for day in ('2026-09-01','2026-09-02'):
    (folder/(day+'.csv')).write_text(f'time,pv_w,output_w\n{day}T12:00:00,100,50\n{day}T12:05:00,300,100\n')
   view=HistoryViews(reader,cfg,'inverter-1');days=reader.available_dates(True)
   reference=view._hourly(None,'Local',view._period_rows(days,'Local'))
   result=view.month_series(date(2026,9,1),'Local');self.assertEqual(result,reference)
   with patch.object(HistoryReader,'graph_day_rows',side_effect=AssertionError('closed chunks reread')):
    self.assertEqual(HistoryViews(HistoryReader(cfg),cfg,'inverter-1').month_series(date(2026,9,1),'Local'),reference)
 def test_import_keeps_originals_and_previous_package_generations(self):
  with tempfile.TemporaryDirectory() as temp:
   cfg=AppConfig(root_dir=temp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
   original=folder/'2026-09-01.csv';original.write_text('time,pv_w,output_w\n2026-09-01T12:00:00,100,50\n')
   snapshot=original.read_bytes();result=export_package(reader,Path(temp)/'a.zip');import_package(temp,Path(temp)/'a.zip',result['sha256'],result['model'])
   prior=list((Path(temp)/'Data/PreparedHistory/packages').glob('*'));sentinel=Path(temp)/'Data/ImportedArchive/preserved.bin';sentinel.parent.mkdir(parents=True);sentinel.write_bytes(b'original archive')
   result=export_package(reader,Path(temp)/'b.zip');import_package(temp,Path(temp)/'b.zip',result['sha256'],result['model'])
   self.assertEqual(original.read_bytes(),snapshot);self.assertEqual(sentinel.read_bytes(),b'original archive');self.assertTrue(all(p.exists() for p in prior))
if __name__=='__main__':unittest.main(verbosity=2)
