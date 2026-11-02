import io,json,time,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from ducksolar.config import AppConfig
from ducksolar.core.device import DeviceMonitor,ParameterReader
from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
from ducksolar.protocol.dispatcher import ProtocolDispatcher,Priority
from ducksolar.adapters.eybond import DeviceChannel
from ducksolar.protocol.ess_shadow import CloudSample,ESSShadow

class Connectivity30(unittest.TestCase):
 def monitor(self):
  cfg=AppConfig();transport=SimpleNamespace(connected=True,connection_id='connection',measurement_connection_id='connection',native_auxiliary={})
  driver=DaxtromnPI30Driver(cfg);writer=Mock();store=Mock()
  return DeviceMonitor(cfg,writer,store,None,transport,driver,'inverter-1')
 def test_live_samples_published_during_blocked_local_command(self):
  m=self.monitor();values=dict(grid_v=230,grid_hz=50,pv_v=300,pv_w=1000,battery_v=52,battery_pct=80,charge_a=10,discharge_a=0,output_v=230,output_hz=50,output_va=500,output_w=400,load_pct=10)
  used=set()
  def sample(op,since):
   now=time.monotonic();n=int((now-start)/.12)
   if n<1 or n in used:return None
   used.add(n);return CloudSample(b'',dict(values,pv_w=1000+n),now,now,('connection',n),'connection','QPIGS')
  m.transport.take_cloud_sample=sample
  release=threading.Event();began=threading.Event()
  transport=SimpleNamespace(transact=lambda request:(began.set(),release.wait(2),b'OK')[-1])
  d=ProtocolDispatcher(transport);d.start();start=time.monotonic()
  timer=threading.Timer(.55,release.set);timer.start()
  try:
   result=d.transact_sync(b'QMOD',Priority.CRITICAL,'QMOD',timeout=2,on_wait=m._refresh_cloud_telemetry)
   self.assertEqual(result,b'OK');self.assertTrue(began.is_set());self.assertGreaterEqual(m.telemetry_writer.submit.call_count,3)
   self.assertLess(time.monotonic()-m.snapshot()['received_monotonic'],.3)
   self.assertEqual(m.telemetry_writer.submit.call_count,m.runtime_store.add_live_point.call_count)
  finally:release.set();timer.cancel();d.stop()
 def test_late_direct_result_cannot_overwrite_new_cloud_or_duplicate_history(self):
  m=self.monitor();task=m.driver.poll_plan()[0];m._state['received_monotonic']=100
  self.assertFalse(m._apply_update(task,'old',{},99,('old',)))
  self.assertFalse(m._apply_update(task,'duplicate',{},100,('duplicate',)))
  m.telemetry_writer.submit.assert_not_called()
 def test_disconnected_transport_does_not_consume_cloud(self):
  m=self.monitor();m.transport.connected=False;m.transport.take_cloud_sample=Mock()
  m._refresh_cloud_telemetry();m.transport.take_cloud_sample.assert_not_called();m.telemetry_writer.submit.assert_not_called()
 def test_timeout_preserves_previously_calibrated_native_mapping(self):
  shadow=SimpleNamespace(lock=threading.RLock(),calibration={(0x994,1):3})
  adapter=SimpleNamespace(capabilities={"channels":[0]},shadow=shadow,targets={(0x994,1):{}},cfg=SimpleNamespace(socket_timeout_s=3),_wire_transact=Mock(side_effect=TimeoutError('NATIVE4501 timeout')))
  ch=DeviceChannel(adapter,SimpleNamespace(channel=0,device_code=0x994,address=1))
  with self.assertRaises(TimeoutError):ch.read_native()
  self.assertEqual(shadow.calibration[(0x994,1)],3)
 def test_invalid_response_revokes_native_mapping(self):
  shadow=SimpleNamespace(lock=threading.RLock(),calibration={(0x994,1):3})
  adapter=SimpleNamespace(capabilities={"channels":[0]},shadow=shadow,targets={(0x994,1):{}},cfg=SimpleNamespace(socket_timeout_s=3),_wire_transact=Mock(return_value=b'bad'))
  ch=DeviceChannel(adapter,SimpleNamespace(channel=0,device_code=0x994,address=1))
  with self.assertRaises(ValueError):ch.read_native()
  self.assertEqual(shadow.calibration[(0x994,1)],0)
 def test_no_fabricated_freshness_when_cloud_has_no_new_sample(self):
  m=self.monitor();m._state['received_monotonic']=10;m.transport.take_cloud_sample=lambda *args:None
  m._refresh_cloud_telemetry();self.assertEqual(m.snapshot()['received_monotonic'],10);m.telemetry_writer.submit.assert_not_called()
 def test_callback_failure_does_not_retry_transmitted_operation(self):
  calls=[];release=threading.Event()
  t=SimpleNamespace(transact=lambda r:(calls.append(r),release.wait(.22),b'OK')[-1]);d=ProtocolDispatcher(t);d.start()
  try:
   with self.assertLogs('ducksolar.protocol.dispatcher',level='ERROR'):
    self.assertEqual(d.transact_sync(b'WRITE',10,'WRITE',timeout=1,on_wait=Mock(side_effect=ValueError('observer failure'))),b'OK')
   self.assertEqual(calls,[b'WRITE'])
  finally:release.set();d.stop()
 def test_real_disconnect_remains_an_error_during_live_wait(self):
  d=ProtocolDispatcher(SimpleNamespace(transact=Mock(side_effect=ConnectionError('closed'))));d.start()
  try:
   with self.assertRaises(ConnectionError):d.transact_sync(b'Q',10,'Q',timeout=1,on_wait=Mock())
  finally:d.stop()
 def test_parameter_failures_back_off_and_manual_refresh_stays_available(self):
  m=self.monitor();r=ParameterReader(m.cfg,m);delays=[];clock=[0]
  r._refresh=Mock(return_value=False)
  def wait(delay):
   clock[0]+=.5
   if r._refresh.call_count>=4:r.stop_event.set()
   return r.stop_event.is_set()
  with patch('ducksolar.core.device.time.monotonic',side_effect=lambda:clock[0]),patch.object(r.stop_event,'wait',side_effect=wait):
   r._run()
  self.assertEqual(r._refresh.call_count,4);self.assertGreaterEqual(clock[0],140)
  r.request_refresh();self.assertTrue(r.refresh_event.is_set())
 def test_reconnect_still_clears_calibration_and_stale_samples(self):
  s=ESSShadow({(0x994,1):{}});s.calibration[(0x994,1)]=3;s.samples['old']='old';s.reset('new')
  self.assertEqual(s.calibration,{});self.assertEqual(s.samples,{})

def run():
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Connectivity30))
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
if __name__=='__main__':unittest.main()
