"""Instrumentation fixtures: temporary files, no equipment or account writes."""
import json,tempfile,csv,time
from pathlib import Path
from datetime import datetime,date,timedelta
def run(root):
 from ducksolar.config import AppConfig
 from ducksolar.storage import Storage,TelemetryRecord
 from ducksolar.history_reader import HistoryReader
 from ducksolar.history_views import HistoryViews
 from ducksolar.csv_codec import unpack
 from ducksolar.resource_manager import operation,rss,update
 with tempfile.TemporaryDirectory(dir=root) as folder:
  cfg=AppConfig(root_dir=folder);storage=Storage(cfg)
  normalized={'metrics':{'grid.estimated_import_power':dict(value=100,unit='W',quality='good',source='fixture'),'grid.estimated_export_power':dict(value=0,unit='W',quality='good',source='fixture')},'metadata':{'note':'тест'*2000}}
  for i in range(1000):storage.append_telemetry(TelemetryRecord(datetime(2026,9,1)+timedelta(seconds=i*5),'Local',dict(pv_w=1000,output_w=500,battery_v=54,normalized_json=json.dumps(normalized,ensure_ascii=False)),'inverter-1'))
  p=Path(folder)/'Logs/Inverter/2026-09-01.csv'
  with p.open(encoding='utf-8-sig',newline='') as f:
   row=next(csv.DictReader(f));assert unpack(row['normalized_json'])==normalized;assert '$ds_normalized' in row['normalized_json']
  reader=HistoryReader(cfg);view=HistoryViews(reader,cfg,'inverter-1')
  outputs={}
  for period in ('day','month','year','all'):
   result=view.graph_data(period,date(2026,9,1),'Local',fields=['pv_w','battery_v'],max_points=100)
   assert len(result['points'])<=100;assert result['source']=='Local';assert result['contract']=='ducksolar.graph.v1'
   outputs[period]=len(result['points'])
  assert view.graph_data('day',date(2026,9,1),'SmartESS')['points']==[]
  class Device:history=reader
  class Logs:
   def event(self,*a,**k):pass
  class Runtime:devices={'inverter-1':Device()};logs=Logs()
  baseline=rss();reader._append_cache['memory-fixture']={'payload':[bytearray(8*1024*1024) for _ in range(8)]};peak=rss()
  with operation(Runtime(),{'i':view},'fixture'):
   pass
  after=rss();assert not reader._append_cache;assert not view.daily_memory and not view.graph_memory
  return json.dumps(dict(periods=outputs,csv_bytes=p.stat().st_size,metadata_exact=True,rss_baseline=baseline,rss_peak=peak,rss_after=after,released_bytes=peak-after if peak and after else None,caches_empty=True))
