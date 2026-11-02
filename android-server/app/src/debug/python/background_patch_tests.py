import sys,threading,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import date,datetime,timedelta
from unittest.mock import patch

from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_maintenance import HistoryMaintenance
from ducksolar.energy_streaming import MonthAccounting
from ducksolar.energy_accounting import ZONE
class Log:
 def event(self,*a,**kw):pass
class Storage:
 def list_meter_readings(self,**kw):return []
class Background(unittest.TestCase):
 def test_charging_prepares_durable_month_once_and_yields_to_jobs(self):
  with tempfile.TemporaryDirectory() as temp:
   cfg=AppConfig(root_dir=temp);reader=HistoryReader(cfg);folder=reader.paths['inverter_logs'];folder.mkdir(parents=True)
   day=date.today();t=datetime.combine(day,datetime.min.time(),tzinfo=ZONE)
   (folder/(day.isoformat()+'.csv')).write_text('time,pv_w,output_w,battery_v,charge_a,grid_v,grid_hz\n'+''.join(f'{(t+timedelta(minutes=i)).isoformat()},100,30,52,0,230,50\n' for i in range(4)))
   jobs=SimpleNamespace(lock=threading.Lock(),jobs={});runtime=SimpleNamespace(api=SimpleNamespace(jobs=jobs),logs=Log(),storage=Storage())
   bg=HistoryMaintenance.__new__(HistoryMaintenance);bg.runtime=runtime;bg.stop_event=threading.Event();bg.charging=threading.Event();bg.last_current={};bg.lock=threading.Lock();bg.state={};bg.path=Path(temp)/'Data/PreparedHistory/background.json'
   dev=SimpleNamespace(cfg=cfg,definition=SimpleNamespace(id='inverter-1'))
   bg._current(dev,reader);self.assertFalse((Path(temp)/'Data/EnergyAudit').exists())
   bg.charging.set();jobs.jobs={'busy':{'state':'running'}};bg._current(dev,reader);self.assertFalse((Path(temp)/'Data/EnergyAudit').exists())
   jobs.jobs={}
   with patch('ducksolar.history_maintenance.time.monotonic',return_value=10):bg._current(dev,reader)
   self.assertEqual(len(list((Path(temp)/'Data/EnergyAudit/inverter-1').glob('*.summary.json'))),3)
   with patch('ducksolar.history_maintenance.time.monotonic',return_value=10),patch.object(MonthAccounting,'report',side_effect=AssertionError('Unchanged five-minute window must not run again')):bg._current(dev,reader)
   resumed=MonthAccounting().report(HistoryReader(cfg),runtime.storage,cfg,day.replace(day=1),source='Local')
   self.assertTrue(resumed['cache_hit'] or resumed['incremental'])
if __name__=='__main__':unittest.main()
