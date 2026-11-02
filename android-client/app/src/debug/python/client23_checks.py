import io,json,time,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import android_client as c
class Client23(unittest.TestCase):
 def setUp(self):
  self.saved=(c._root,c._api,c._live,dict(c._cfg),dict(c._health),dict(c._repeats));c._root=None;c._api=SimpleNamespace(url='https://remote');c._live=None;c._cfg=dict(lan='https://lan',remote='https://remote');c._health={'disconnects':0,'route_failures':0};c._repeats.clear();c._graph_job.clear()
 def tearDown(self):c._root,c._api,c._live,c._cfg,c._health,c._repeats=self.saved
 def wait(self):
  until=time.monotonic()+2
  while c._graph_job.get('state')=='running' and time.monotonic()<until:time.sleep(.01)
  return dict(c._graph_job)
 def result(self,start='08:30'):
  return dict(contract='ducksolar.graph.v1',source='Auto',period='day',anchor='2026-10-19',points=[],window=dict(start='2026-10-19T'+start+':00+03:00',end='2026-10-19T09:30:00+03:00'))
 def test_window_is_forwarded_to_server_and_validated(self):
  with patch.object(c,'_history_job',return_value=self.result()) as call:
   c.graph_start('day','2026-10-19','Auto','["pv_w","output_w"]','power','08:30','09:30');r=self.wait();self.assertEqual(r['state'],'complete');self.assertEqual(call.call_args.args[1]['kwargs']['window_start'],'08:30')
 def test_wrong_window_response_rejected(self):
  with patch.object(c,'_history_job',return_value=self.result('08:00')):
   c.graph_start('day','2026-10-19','Auto','["pv_w"]','power','08:30','09:30');self.assertEqual(self.wait()['state'],'error')
 def test_older_server_cannot_silently_return_full_day(self):
  r=self.result();r.pop('window')
  with patch.object(c,'_history_job',return_value=r):
   c.graph_start('day','2026-10-19','Auto','["pv_w"]','power','08:30','09:30');self.assertIn('a1.4.31',self.wait()['error'])
 def test_invalid_window_rejected_before_network(self):
  with patch.object(c,'_history_job') as call:
   for period,a,b in [('day','10:00','08:00'),('month','08:00','09:00'),('day','24:00','24:00'),('day','8:00','09:00')]:
    with self.assertRaises(ValueError):c.graph_start(period,'2026-10-19','Auto','["pv_w"]','power',a,b)
   call.assert_not_called()
 def test_legacy_full_day_request_omits_window_kwargs(self):
  r=self.result();r.pop('window')
  with patch.object(c,'_history_job',return_value=r) as call:
   c.graph_start('day','2026-10-19','Auto','["pv_w"]');self.assertEqual(self.wait()['state'],'complete');self.assertNotIn('window_start',call.call_args.args[1]['kwargs'])
 def test_health_does_not_return_credentials_or_raw_device_state(self):
  snapshot=json.dumps(dict(connected=True,route='local',last_received_age_s=.3,state=dict(updated='now',stale=False,token='secret',normalized={'private':'secret'})))
  with patch.object(c,'snapshot',return_value=snapshot):
   r=c.connection_health();self.assertNotIn('secret',r);self.assertNotIn('normalized',r);self.assertEqual(json.loads(r)['route'],'local')
 def test_raw_disconnect_count_is_not_repeat_log_count(self):
  log=c.ClientLogs('local')
  for i in range(100):log.event('temporary',code='client.disconnected',error_code='connection.timeout')
  self.assertEqual(c._health['disconnects'],100);self.assertEqual(c._health['last_failure']['route'],'local')
 def test_connected_event_reports_candidate_route_not_previous_api(self):
  with tempfile.TemporaryDirectory() as td:
   c._root=Path(td);c.ClientLogs('local').event('connected',code='client.connected')
   row=json.loads((Path(td)/'client-events.jsonl').read_text(encoding='utf-8'));self.assertEqual(row['route'],'local')
  c._root=None
 def test_health_keeps_last_failure_after_success(self):
  c._health_event('route.failed','remote',dict(error_code='connection.timeout',stage='session'));c._health_event('route.connected','local',dict(duration_ms=200))
  self.assertEqual(c._health['last_failure']['code'],'connection.timeout');self.assertEqual(c._health['last_connection']['route'],'local')
def run():
 stream=io.StringIO();r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Client23))
 if not r.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=r.testsRun))
if __name__=='__main__':unittest.main()
