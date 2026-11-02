"""Isolated real-size history replay; no equipment connections."""
import csv,json,time,tempfile,shutil
from pathlib import Path
from datetime import datetime,timedelta

def run(root,source):
 from ducksolar.config import AppConfig
 from ducksolar.history_reader import HistoryReader
 from ducksolar.energy_streaming import MonthAccounting
 class Storage:
  def list_meter_readings(self,**kw):return []
 class Reader(HistoryReader):
  calls=0
  def _canonical(self,*args,**kw):self.calls+=1;return super()._canonical(*args,**kw)
 with tempfile.TemporaryDirectory(prefix='night-replay-',dir=root) as folder:
  cfg=AppConfig(root_dir=folder);reader=Reader(cfg);engine=MonthAccounting()
  path=reader.paths['inverter_logs']/'2026-10-10.csv';path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
  started=time.monotonic();first=engine.report(reader,Storage(),cfg,'2026-10',now='2026-10-10T10:25:00+03:00',source='Local');cold=time.monotonic()-started
  initial=reader.calls
  started=time.monotonic();warm=engine.report(reader,Storage(),cfg,'2026-10',now='2026-10-10T10:25:01+03:00',source='Local');reuse=time.monotonic()-started
  assert reader.calls==initial and first['pv']['kwh']==warm['pv']['kwh']
  with path.open(encoding='utf-8-sig',newline='') as stream:
   rows=csv.DictReader(stream);fields=rows.fieldnames
   for row in rows:last=row
  last['time']=(datetime.fromisoformat(last['time'])+timedelta(seconds=5)).isoformat()
  with path.open('a',encoding='utf-8',newline='') as out:csv.DictWriter(out,fields).writerow(last)
  started=time.monotonic();appended=engine.report(reader,Storage(),cfg,'2026-10',now='2026-10-10T10:25:02+03:00',source='Local');append=time.monotonic()-started
  assert reader.calls==initial+1 and appended['input_count']==first['input_count']+1
  return json.dumps(dict(rows=first['input_count'],source_bytes=Path(source).stat().st_size,cold_s=cold,warm_recalculation_s=reuse,append_recalculation_s=append,appended_rows_parsed=1,pv_kwh=first['pv']['kwh']))
