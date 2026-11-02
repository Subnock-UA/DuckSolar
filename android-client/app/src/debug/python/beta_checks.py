import sys,time,json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[5];sys.path[:0]=[str(ROOT/'android-client/app/src/main/python'),str(ROOT)]
import android_client as c
from ducksolar.remote import LiveConnection
from ducksolar.local_alerts import update
from ducksolar.route_policy import RoutePolicy
class ClientBeta(unittest.TestCase):
 def live(self):
  a=SimpleNamespace(auth_error=None,transport=SimpleNamespace(idle_live=True,live_mode='notifications',live_stale_s=75));l=LiveConnection(a,Mock());l.last_received=time.monotonic()-22;l.connected=True;l.connection_state='CONNECTED';return l
 def test_transition_keeps_healthy_idle(self):
  l=self.live();l.change_mode('telemetry');self.assertFalse(l.recover_stale());self.assertTrue(l.connected);self.assertEqual(l.fresh_limit(),75)
 def test_delayed_idle_frame_keeps_transition_grace(self):
  l=self.live();l.change_mode('telemetry');l.accept(dict(api_version=3,session_id='s',sequence=1,server_time='2026-10-23T10:00:00',live_mode='notifications',notifications=[]));self.assertEqual(l.fresh_limit(),75)
 def test_transition_expires(self):
  l=self.live();l.change_mode('telemetry');l.mode_transition_until=time.monotonic()-1;self.assertTrue(l.recover_stale())
 def test_first_frame_completes_transition(self):
  l=self.live();l.change_mode('telemetry');l.accept(dict(api_version=3,session_id='s',sequence=1,server_time='2026-10-23T10:00:00'));self.assertEqual(l.fresh_limit(),15);self.assertEqual(l.mode_transition_until,0)
 def test_last_remote_retried_before_lan(self):
  p=RoutePolicy();p.success('remote');self.assertEqual(p.ordered(['local','remote']),['remote','local']);p.failed('remote');self.assertEqual(p.ordered(['local','remote']),['local'])
 def test_resume_does_not_stop_mode_transition(self):
  l=self.live();l.change_mode('telemetry');api=l.api;api.url='remote';api.session={}
  with patch.multiple(c,_live=l,_api=api,_network_available=True,_cfg={'token':'saved'}),patch.object(c,'_prefer_lan',return_value=False),patch.object(c,'stop') as stop:
   self.assertTrue(json.loads(c.resume())['connected']);stop.assert_not_called()
 def test_resume_retries_failed_owner(self):
  l=self.live();l.connected=False;l.last_received=time.monotonic()-100;l.thread=SimpleNamespace(is_alive=lambda:True);api=l.api;api.url='remote'
  with patch.multiple(c,_live=l,_api=api,_network_available=True,_cfg={'token':'saved','lan':'local','remote':'remote'},_routes=RoutePolicy()),patch.object(c,'stop'),patch.object(c,'_begin',return_value='connected') as begin:
   c._routes.success('remote');self.assertEqual(c.resume(),'connected');begin.assert_called_once_with('remote')
 def test_local_alert_defaults_off(self):
  cfg={};self.assertFalse(update(cfg,False,100));self.assertFalse(update(cfg,False,10000))
 def test_local_outage_recovery_and_restart(self):
  cfg={'notifications':{'server_connection':True}};update(cfg,True,100);self.assertFalse(update(cfg,False,189));self.assertEqual(update(cfg,False,190)[0]['kind'],'server_lost');cfg=json.loads(json.dumps(cfg));self.assertEqual(len(update(cfg,False,500)),1);self.assertEqual(update(cfg,True,501)[-1]['kind'],'server_restored')
 def test_local_ack_without_api(self):
  cfg={'local_alert_events':[{'id':'a'*32,'kind':'server_lost'}]}
  with patch.multiple(c,_api=None,_cfg=cfg),patch.object(c,'_save'),patch.object(c,'_note'):
   c.notification_ack(json.dumps(['a'*32]));self.assertFalse(cfg['local_alert_events'])
if __name__=='__main__':unittest.main(verbosity=2)

def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
