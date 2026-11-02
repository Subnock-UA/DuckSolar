import sys,unittest,tempfile,json,time,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[5];sys.path[:0]=[str(ROOT/'android-server/app/src/main/python'),str(ROOT)]
from ducksolar.push_alerts import PushAlerts
from ducksolar.notification_settings import DEFAULTS,GROUPS
from ducksolar.events import EventJournal
class Alerts(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.t=[1000.];self.a=PushAlerts(Path(self.tmp.name)/'push.json',clock=lambda:self.t[0]);self.a.settings('alice','client',['inverter']);self.row=self.a.rows['alice|client']
 def settings(self,**kw):self.a.settings('alice','client',['inverter'],kw)
 def feed(self):return self.a.feed('alice','client',['inverter'])
 def observe(self,**data):self.a.observe('inverter',dict(stale=False,updated=str(self.t[0]),data=data))
 def test_new_defaults_off(self):self.assertTrue(all(self.row['settings'][k] is False for k in GROUPS));self.assertTrue(self.row['settings']['grid_lost'])
 def test_exact_threshold_and_ack(self):
  self.settings(server_battery_threshold=92);self.a.battery(92);self.assertEqual(self.feed()[0]['percent'],92);self.a.battery(91);self.assertEqual(len(self.feed()),1);self.a.acknowledge('alice','client',[self.feed()[0]['id']]);self.a.battery(90);self.assertFalse(self.feed());self.a.battery(95);self.a.battery(92);self.assertEqual(len(self.feed()),1)
 def test_threshold_change_rearms(self):self.settings(server_battery_threshold=92);self.a.battery(92);self.settings(server_battery_threshold=91);self.assertFalse(self.feed());self.a.battery(91);self.assertEqual(self.feed()[0]['threshold'],91)
 def test_old_settings_migrate(self):
  self.a.path.write_text(json.dumps({'alice|client':{'settings':{'server_battery_threshold':92},'states':{},'events':[],'grants':['inverter']}}));a=PushAlerts(self.a.path);self.assertFalse(a.rows['alice|client']['settings']['storage']);a.battery(92);self.assertEqual(len(a.feed('alice','client',['inverter'])),1)
 def test_inverter_outage_delay_restore(self):
  self.settings(inverter_connection=True);self.a.observe('inverter',{'stale':True});self.t[0]+=89;self.a.observe('inverter',{'stale':True});self.assertFalse(self.feed());self.t[0]+=1;self.a.observe('inverter',{'stale':True});self.assertEqual(self.feed()[0]['kind'],'inverter_lost');self.observe();self.assertEqual(self.feed()[-1]['kind'],'inverter_restored')
 def test_grid_voltage_debounce_missing(self):
  self.settings(grid_voltage=True);self.observe(grid_v=170);self.t[0]+=30;self.observe(grid_v=170);self.assertEqual(self.feed()[-1]['kind'],'grid_voltage_bad');self.observe(grid_v=0);self.t[0]+=40;self.observe(grid_v=190);self.t[0]+=30;self.observe(grid_v=190);self.assertEqual(self.feed()[-1]['kind'],'grid_voltage_ok')
 def test_high_load_and_temperature(self):
  self.settings(overload=True,over_temperature=True);self.observe(load_pct=95,temperature_c=70);self.t[0]+=30;self.observe(load_pct=95,temperature_c=70);self.assertEqual({x['kind'] for x in self.feed()},{'overload_high','temperature_high'});self.observe(load_pct=70,temperature_c=55);self.t[0]+=30;self.observe(load_pct=70,temperature_c=55);self.assertEqual(len(self.feed()),4)
 def test_critical_and_recovery(self):self.settings(critical_battery=True);self.observe(battery_pct=15);self.assertEqual(self.feed()[-1]['kind'],'battery_critical');self.observe(battery_pct=19);self.assertEqual(self.feed()[-1]['kind'],'battery_critical_ok')
 def test_power_and_space(self):
  self.settings(server_power=True,storage=True);self.a.phone(False,100*1024**2);self.t[0]+=60;self.a.phone(False,100*1024**2);self.assertEqual({x['kind'] for x in self.feed()},{'server_unplugged','storage_low'});self.a.phone(True,500*1024**2);self.t[0]+=30;self.a.phone(True,500*1024**2);self.assertEqual(len(self.feed()),4)
 def test_write_failure_and_disable(self):self.settings(storage=True);self.a.storage_failure(True);self.a.storage_failure(True);self.assertEqual(len(self.feed()),1);self.settings(storage=False);self.assertFalse(self.feed())
 def test_off_no_events(self):self.observe(load_pct=100,temperature_c=90,battery_pct=20);self.a.phone(False,0);self.a.storage_failure(True);self.t[0]+=1000;self.observe(load_pct=100,temperature_c=90,battery_pct=20);self.a.phone(False,0);self.assertFalse(self.feed())
 def test_dynamic_history_preserves_file(self):
  p=Path(self.tmp.name)/'events.jsonl';j=EventJournal(p);j.add('warnings.pi30.qpiws.1','old unknown','inverter',position=1,confidence='unknown');before=p.read_bytes();row=j.recent(['inverter'],profiles={'inverter':True})[0];self.assertEqual(row['original_message'],'old unknown');self.assertNotEqual(row['confidence'],'unknown');self.assertEqual(p.read_bytes(),before)
if __name__=='__main__':unittest.main(verbosity=2)

def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
