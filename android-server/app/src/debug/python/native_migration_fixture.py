import json,tempfile,shutil
from pathlib import Path
from datetime import date
from ducksolar.config import AppConfig
from ducksolar.server_runtime import ServerRuntime
from ducksolar.history_migration import inventory,activate
from ducksolar.history_reader import HistoryReader
from ducksolar.energy_streaming import MonthAccounting
_temp=None;_runtime=None;_baseline=None;_source=None
def begin(root):
 global _temp,_runtime,_baseline,_source
 _temp=tempfile.TemporaryDirectory(prefix='native-migration-',dir=root)
 cfg=AppConfig(root_dir=_temp.name,api_port=0,cloud_proxy_enabled=False,dtu_pn='NATIVE-TEST')
 _runtime=ServerRuntime(cfg);reader=_runtime.history
 _source=reader.paths['inverter_logs']/'2026-09-01.csv';_source.parent.mkdir(parents=True,exist_ok=True)
 _source.write_text('time,pv_w,output_w,output_va,load_pct\n'+''.join(f'2026-09-01T12:{i:02d}:00,300,100,120,5\n' for i in range(30)))
 _baseline=MonthAccounting().report(reader,_runtime.storage,cfg,date(2026,9,1),source='Local')
 _runtime.api.start();_runtime.active=True;_runtime.enter_maintenance()
 plan=inventory(_runtime);plan['root']=_temp.name
 return json.dumps(plan)
def finish(path,sha):
 result=activate(_runtime,path,sha)
 report=MonthAccounting().report(HistoryReader(_runtime.device().cfg),_runtime.storage,_runtime.device().cfg,date(2026,9,1),source='Local')
 if report['pv']!=_baseline['pv'] or not report.get('portable_cache_hit') or _source.exists():raise AssertionError('Native migration balance/original/cache mismatch')
 return json.dumps(dict(result,portable_balance=True,maintenance_api_alive=_runtime.api.thread.is_alive()))
def close():
 global _runtime,_temp
 if _runtime:_runtime.stop();_runtime=None
 if _temp:_temp.cleanup();_temp=None
