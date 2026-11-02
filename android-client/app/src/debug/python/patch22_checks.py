import sys,unittest,tempfile,json,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'main/python'),str(Path(__file__).resolve().parents[5])]
import android_client as c
from ducksolar.route_policy import RoutePolicy
from ducksolar.event_details import enrich
class Patch22(unittest.TestCase):
 def setUp(self):
  c._cfg={'token':'fixture','pin':'a'*64,'client_id':'b','username':'u','serial':'s','lan':'https://lan','remote':'https://remote'};c._api=SimpleNamespace(url='https://remote');c._live=SimpleNamespace(connected=True);c._routes=RoutePolicy();c._manual_until=0;c._lan_check_at=0;c._wifi_available=True;c._root=None
 def tearDown(self):c._live=None;c._api=None;c._wifi_available=False
 def test_healthy_remote_migrates_only_after_lan_probe(self):
  with patch.object(c,'_probe') as probe,patch.object(c,'_begin') as begin:
   self.assertTrue(c._prefer_lan());probe.assert_called_once_with('https://lan','a'*64);begin.assert_called_once_with('https://lan')
   self.assertFalse(c._prefer_lan())
 def test_lan_failure_keeps_healthy_remote_with_cooldown(self):
  with patch.object(c,'_probe',side_effect=OSError()),patch.object(c,'_begin') as begin:
   self.assertFalse(c._prefer_lan());begin.assert_not_called();self.assertGreater(c._routes.until['https://lan'],time.monotonic());self.assertTrue(c._live.connected)
 def test_no_wifi_or_manual_priority_does_not_probe(self):
  with patch.object(c,'_probe') as probe:
   c._wifi_available=False;self.assertFalse(c._prefer_lan());c._wifi_available=True;c._manual_until=time.monotonic()+100;self.assertFalse(c._prefer_lan());probe.assert_not_called()
 def test_manual_switch_keeps_automatic_recovery(self):
  with patch.object(c,'_begin',return_value='{}') as begin:
   c.switch_route('local');begin.assert_called_once_with('https://lan');self.assertGreater(c._manual_until,time.monotonic())
 def test_saved_snapshot_account_scope_and_no_credentials(self):
  with tempfile.TemporaryDirectory() as td:
   c._root=Path(td);c._snapshot_saved_at=0;c._save_last_snapshot({'updated':'test','normalized':{'metrics':{}}})
   self.assertEqual('test',json.loads(c.last_snapshot())['state']['updated']);self.assertNotIn('fixture',(Path(td)/'last-snapshot.json').read_text())
   c._cfg['serial']='other'
   with self.assertRaises(ValueError):c.last_snapshot()
   c._root=None
 def test_event_episode_has_real_duration_and_unknown_start(self):
  rows=enrich([dict(code='warnings.x',device_id='1',transition='raised',time='2026-10-19T00:00:00+00:00'),dict(code='warnings.x',device_id='1',transition='cleared',time='2026-10-19T00:01:00+00:00')])
  self.assertEqual(60,rows[-1]['event_detail']['duration_s']);self.assertTrue(rows[-1]['event_detail']['start_confirmed'])


def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Patch22))
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
