import sys,json,unittest,time,threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
import android_client as c
from ducksolar.remote import LiveConnection
class IdleClient(unittest.TestCase):
 def api(self):return SimpleNamespace(auth_error=None,transport=SimpleNamespace(idle_live=True,live_mode='notifications',live_stale_s=75))
 def test_control_keeps_transport_but_not_acquisition_fresh(self):
  live=LiveConnection(self.api(),Mock());full=dict(api_version=3,session_id='test',sequence=1,server_time='2026-10-22T12:00:00',normalized={'metrics':{'fixture':1}},updated='old',statuses={'API':True},server_phone=dict(available=True,age_s=2,battery_percent=80),stale=False)
  live.accept(full);old=live.last_telemetry_received;live.last_telemetry_received=time.monotonic()-100
  live.accept(dict(api_version=3,session_id='test',sequence=2,server_time='2026-10-22T12:00:30',live_mode='notifications',notifications=[],statuses={'API':True}))
  self.assertTrue(live.connected);self.assertEqual(live.state['normalized'],full['normalized']);self.assertEqual(live.state['updated'],'old');self.assertTrue(live.snapshot()['stale']);self.assertFalse(live.recover_stale());self.assertFalse(live.snapshot()['server_phone']['available'])
 def test_new_session_drops_old_device_state(self):
  live=LiveConnection(self.api(),Mock());live.state={'normalized':{'secret_previous_server':1}};live.server_session='old'
  live.accept(dict(api_version=3,session_id='new',sequence=1,server_time='2026-10-22T12:00:00',live_mode='notifications',notifications=[]))
  self.assertNotIn('normalized',live.state)
 def test_mode_change_interrupts_once_without_destroying_session(self):
  api=self.api();live=LiveConnection(api,Mock());live.interrupt=Mock();live.change_mode('telemetry');self.assertEqual(api.transport.live_stale_s,15);live.interrupt.assert_called_once();live.change_mode('telemetry');live.interrupt.assert_called_once()
 def test_new_capability_and_legacy_fallback(self):
  fake=SimpleNamespace();old=c._foreground
  try:
   c._foreground=False;c.AndroidTransport.configure_live(fake,dict(capabilities=['live.delta.v1','live.idle.v1']));self.assertEqual(fake.live_stale_s,75)
   c._foreground=True;c.AndroidTransport.configure_live(fake,dict(capabilities=['live.delta.v1','live.idle.v1']));self.assertEqual(fake.live_stale_s,15)
   c.AndroidTransport.configure_live(fake,dict(capabilities=['live.delta.v1']));self.assertEqual(fake.live_stale_s,5);self.assertFalse(fake.idle_live)
  finally:c._foreground=old
 def test_idle_channel_expires_without_heartbeats(self):
  live=LiveConnection(self.api(),Mock());live.last_received=time.monotonic()-80;live.state={'statuses':{'API':True}};self.assertEqual(live.snapshot()['connection'],'SERVER_DISCONNECTED')
 def test_energy_diagnostics_whitelist(self):
  with patch.object(c,'_note') as note:
   c.background_event('energy',json.dumps(dict(level=50,scale=100,plugged=0,screen_on=False,wakelock_active=False,token='NO')));self.assertEqual(note.call_args.kwargs['details']['level'],50);self.assertNotIn('token',note.call_args.kwargs['details'])
if __name__=='__main__':unittest.main(verbosity=2)
def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
