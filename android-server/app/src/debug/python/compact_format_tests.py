import sys,csv,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
sys.path[:0]=[str(ROOT/'android-server/app/src/main/python'),str(ROOT)]
from ducksolar.compact_history import Codec,convert,normalized,schema_path
from ducksolar.prepared_history import PreparedHistory
from ducksolar.history_reader import HistoryReader
from ducksolar.config import AppConfig

class CompactTests(unittest.TestCase):
 def test_dynamic_metadata_scalars_and_missing_are_lossless(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'2026-09-01.csv';codec=Codec(path,['time','pv_w','output_va','load_pct','warnings','normalized_json','temperature_c','bus_v'])
   rows=[]
   for i in range(4):
    rows.append(dict(time=f'2026-09-01T12:0{i}:00',pv_w=['0','','~x','300'][i],output_va='100',load_pct=str(i),warnings=['','','W',''][i],temperature_c='55',bus_v='400',normalized_json=dict(metrics={'pv.w':{'value':[0,None,20,300][i],'quality':['measured','missing','estimated','measured'][i]},'temperature_c':{'value':55}},counters={'export':{'value':9007199254740993+i,'id':'meter-A'}},warnings=[] if i<2 else ['changed'])))
   for row in rows:codec.append(row)
   codec=Codec(path)
   with path.open(encoding='utf-8',newline='') as f:restored=[codec.decode(row) for row in csv.DictReader(f)]
   self.assertEqual(len(restored),4)
   for original,actual in zip(rows,restored):
    self.assertEqual(actual['normalized_json'],normalized(original))
    for key in codec.schema['fields']:self.assertEqual(actual[key],original[key])
    self.assertNotIn('temperature_c',actual);self.assertNotIn('bus_v',actual)
   with path.open('ab') as f:f.write(b'incomplete')
   codec.append(rows[-1])
   with path.open(encoding='utf-8') as f:self.assertEqual(len(list(csv.DictReader(f))),5)
 def test_conversion_preserves_source_and_invalidates_schema(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'old.csv';target=root/'new.csv'
   source.write_text('time,pv_w,output_va,load_pct,temperature_c\n2026-09-01T00:00:00,0,20,1,55\n2026-09-01T00:01:00,,30,2,56\n',encoding='utf-8')
   before=source.read_bytes();result=convert(source,target)
   self.assertEqual(result['rows'],2);self.assertEqual(before,source.read_bytes())
   cfg=AppConfig(root_dir=str(root));store=PreparedHistory(HistoryReader(cfg))
   from datetime import date
   first=store.identity(target,'Local',date(2026,9,1))[0]
   data=json.loads(schema_path(target).read_text());data['defaults']['load_pct']='77';schema_path(target).write_text(json.dumps(data))
   self.assertNotEqual(first,store.identity(target,'Local',date(2026,9,1))[0])
 def test_empty_day(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'old.csv';p.write_text('time,pv_w\n');out=p.with_name('new.csv')
   self.assertEqual(convert(p,out)['rows'],0);self.assertTrue(schema_path(out).is_file())
 def test_actual_writer_and_compact_archive_restore(self):
  from ducksolar.storage import Storage,TelemetryRecord
  from ducksolar.synchronized_history import import_file,import_status
  from datetime import datetime,date
  from ducksolar.prepared_history import digest
  import shutil
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);cfg=AppConfig(root_dir=str(root));storage=Storage(cfg)
   record=TelemetryRecord(datetime(2026,9,1,12,0),'Local',dict(pv_w=300,output_va=120,load_pct=5,bus_v=400,temperature_c=55))
   storage.append_telemetry(record);storage.append_telemetry(record)
   path=root/'Data/CompactHistory/inverter-1/Local/2026-09-01.csv'
   codec=Codec(path)
   with path.open(encoding='utf-8') as f:rows=[codec.decode(row) for row in csv.DictReader(f)]
   self.assertEqual(len(rows),1);self.assertEqual(rows[0]['output_va'],'120');self.assertNotIn('bus_v',rows[0])
   reader=HistoryReader(cfg);self.assertEqual(reader.graph_day_rows(date(2026,9,1),'Local')[0]['pv_w'],300)
   staged=root/'Data/ArchiveDownloads/test.part';staged.parent.mkdir();shutil.copyfile(path,staged);shutil.copyfile(schema_path(path),schema_path(staged))
   row=dict(source_id='pc',source='Local',sha256=digest(path),name='2026-09-01.csv',key='Local/compact-day',device_id='inverter-1',bytes=path.stat().st_size,schema=dict(sha256=digest(schema_path(path)),bytes=schema_path(path).stat().st_size))
   self.assertEqual(import_file(root,staged,row)['state'],'imported');self.assertTrue(import_status(root,row))
if __name__=='__main__':unittest.main()
