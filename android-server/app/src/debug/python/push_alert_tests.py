import sys,json,tempfile,unittest,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
sys.path[:0]=[str(ROOT/'android-server/app/src/main/python'),str(ROOT)]
from ducksolar.push_alerts import PushAlerts,DEFAULTS,validate

class PushTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.now=1000
  self.path=Path(self.temp.name)/'PushAlerts.json';self.hub=PushAlerts(self.path,lambda:self.now)
  self.hub.settings('alice','a'*32,['inverter-1'])
 def tearDown(self):self.temp.cleanup()
 def state(self,grid=True,pct=80,stamp='1',stale=False):
  return dict(stale=stale,updated=stamp,normalized={'grid':{'available':grid}},data={'battery_pct':pct})
 def sample(self,grid=True,pct=80,stamp='1',stale=False):self.hub.observe('inverter-1',self.state(grid,pct,stamp,stale))
 def feed(self,client='a'*32,account='alice',grants=('inverter-1',)):return self.hub.feed(account,client,grants)
 def kinds(self):return [x['kind'] for x in self.feed()]
 def test_grid_two_distinct_samples_and_recovery(self):
  self.sample(stamp='1');self.sample(stamp='2');self.assertEqual(self.feed(),[])
  self.sample(False,stamp='3');self.sample(False,stamp='3');self.assertEqual(self.feed(),[])
  self.sample(False,stamp='4');self.assertEqual(self.kinds(),['grid_lost'])
  self.sample(True,stamp='5');self.sample(True,stamp='6');self.assertEqual(self.kinds(),['grid_lost','grid_restored'])
 def test_stale_disconnect_never_means_mains_outage(self):
  self.sample(stamp='1');self.sample(stamp='2')
  for i in range(3,12):self.sample(False,10,str(i),True)
  self.assertEqual(self.feed(),[])
 def test_unknown_grid_and_missing_soc_are_not_zero(self):
  self.sample(None,None,'1');self.sample(None,None,'2');self.assertEqual(self.feed(),[])
 def test_transient_mains_dip_is_not_alerted(self):
  self.sample(stamp='1');self.sample(stamp='2');self.sample(False,stamp='3');self.sample(True,stamp='4');self.assertEqual(self.feed(),[])
 def test_server_battery_exact_threshold_hysteresis(self):
  for value in (50,49,48,50,52,49):self.hub.battery(value)
  self.assertEqual(self.kinds(),['server_battery'])
  self.hub.battery(53);self.hub.battery(49)
  self.assertEqual(self.kinds(),['server_battery','server_battery'])
 def test_inverter_battery_is_separate(self):
  for i,value in enumerate((30,29,28,31,32,29)):self.sample(pct=value,stamp=str(i))
  self.assertEqual(self.kinds(),['inverter_battery'])
  self.sample(pct=33,stamp='7');self.sample(pct=29,stamp='8');self.assertEqual(len(self.feed()),2)
 def test_restart_retains_queue_and_low_latch(self):
  self.hub.battery(49);self.hub=PushAlerts(self.path,lambda:self.now);self.hub.battery(40)
  self.assertEqual(self.kinds(),['server_battery'])
 def test_each_switch_independent(self):
  for kind in ('grid_lost','grid_restored','server_battery','inverter_battery'):
   settings={**DEFAULTS,kind:False};self.hub.settings('alice','a'*32,['inverter-1'],settings)
   self.sample(stamp='on1');self.sample(stamp='on2');self.sample(False,20,'off1');self.sample(False,20,'off2');self.sample(True,20,'back1');self.sample(True,20,'back2');self.hub.battery(20)
   self.assertNotIn(kind,self.kinds())
   self.hub.rows['alice|'+'a'*32]['states'].clear()
 def test_disable_removes_pending_events(self):
  self.hub.battery(20);self.hub.settings('alice','a'*32,['inverter-1'],{**DEFAULTS,'server_battery':False})
  self.assertEqual(self.feed(),[])
 def test_custom_threshold_message_and_change_rearms(self):
  self.hub.settings('alice','a'*32,['inverter-1'],{**DEFAULTS,'server_battery_threshold':60})
  self.hub.battery(59);self.assertIn('60%',self.feed()[0]['message'])
  self.hub.settings('alice','a'*32,['inverter-1'],{**DEFAULTS,'server_battery_threshold':70})
  self.hub.battery(65);self.assertEqual(self.feed()[0]['threshold'],70)
 def test_invalid_thresholds_and_switches(self):
  for invalid in (0,100,True,50.5,'50',None):
   with self.assertRaises(ValueError):validate(dict(server_battery_threshold=invalid))
  with self.assertRaises(ValueError):validate(dict(grid_lost=1))
  with self.assertRaises(ValueError):validate(dict(unknown=True))
 def test_ack_is_scoped_to_client_and_account(self):
  self.hub.settings('alice','b'*32,['inverter-1']);self.hub.battery(20)
  ident=self.feed()[0]['id'];self.hub.acknowledge('alice','b'*32,[ident]);self.hub.acknowledge('bob','a'*32,[ident])
  self.assertEqual(len(self.feed()),1)
  self.hub.acknowledge('alice','a'*32,[ident]);self.assertEqual(self.feed(),[])
 def test_delivery_filters_revoked_grants(self):
  self.sample(False,20,'1');self.sample(False,20,'2')
  self.assertTrue(self.feed());self.assertEqual(self.feed(grants=()),[])
 def test_old_queue_expires_after_24h(self):
  self.hub.battery(20);self.now+=86401;self.assertEqual(self.feed(),[])
 def test_queue_is_bounded(self):
  for i in range(140):self.hub.battery(100);self.hub.battery(20)
  self.assertEqual(len(self.feed()),128)
 def test_two_clients_have_independent_thresholds(self):
  self.hub.settings('alice','b'*32,['inverter-1'],{**DEFAULTS,'server_battery_threshold':70});self.hub.battery(65)
  self.assertEqual(self.feed(),[]);self.assertEqual(len(self.feed('b'*32)),1)
 def test_invalid_levels_ignored(self):
  for value in (None,False,float('nan'),-1,101,'20'):self.hub.battery(value)
  self.assertEqual(self.feed(),[])
 def test_actual_driver_voltage_and_integer_availability(self):
  from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
  from ducksolar.config import AppConfig
  driver=DaxtromnPI30Driver(AppConfig())
  for i,voltage in enumerate((230,230,140,140,0,0,230,230)):
   values=dict(grid_v=voltage,grid_hz=50,battery_pct=80,grid_available=int(voltage>=180))
   self.hub.observe('inverter-1',dict(stale=False,updated=str(i),normalized=driver.normalized(values),data=values))
   if i<4:self.assertEqual(self.feed(),[])
  self.assertEqual(self.kinds(),['grid_lost','grid_restored'])
 def test_missing_voltage_never_inherits_unavailable_flag(self):
  state=dict(stale=False,normalized={'grid':{'available':0,'phases':[{'voltage':None}]}},data={})
  for i in range(3):state['updated']=str(i);self.hub.observe('inverter-1',state)
  self.assertEqual(self.feed(),[])
 def test_legacy_integer_flags_are_supported(self):
  self.sample(0,stamp='1');self.sample(0,stamp='2');self.assertEqual(self.kinds(),['grid_lost'])
 def test_partial_settings_preserve_disabled_switches(self):
  self.hub.settings('alice','a'*32,['inverter-1'],dict(grid_lost=False))
  self.hub.settings('alice','a'*32,['inverter-1'],dict(server_battery_threshold=60))
  self.assertFalse(self.hub.settings('alice','a'*32,['inverter-1'])['grid_lost'])

if __name__=='__main__':unittest.main()
