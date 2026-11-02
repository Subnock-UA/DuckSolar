import sys,json,time,tempfile,ssl,http.client,unittest,concurrent.futures
from unittest.mock import patch
from ducksolar.config import AppConfig
from ducksolar.server_runtime import ServerRuntime
class IdleTLS(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.rt=ServerRuntime(AppConfig(root_dir=self.tmp.name,api_host='127.0.0.1',api_port=0,dtu_pn='fixture'));self.rt.api.start();self.rt.active=True
  api=self.rt.api;api.accounts.register('alice','test-password','fixture');token=api.accounts.login('alice','test-password','fixture',trusted=True)['token'];api.accounts.bind('Bearer '+token,'fixture',self.rt,'fixture')
  self.headers={'Authorization':'Bearer '+token,'X-DX-Client-ID':'a'*32}
  c=self.conn();c.request('POST','/api/v1/session',json.dumps(dict(client_id='a'*32,client_version='1.6.25',api_version=3)),self.headers);r=c.getresponse();session=json.loads(r.read());c.close();self.headers['X-DX-Client-Session']=session['client_session_id'];self.assertIn('live.idle.v1',session['capabilities'])
  self.rt.push_alerts.settings('alice','a'*32,[self.rt.primary_id])
 def tearDown(self):self.rt.stop();self.tmp.cleanup()
 def conn(self):
  context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
  return http.client.HTTPSConnection('127.0.0.1',self.rt.api.http.server_port,context=context,timeout=40)
 def stream(self,query):
  c=self.conn();c.request('GET','/api/v1/events'+query,headers=self.headers);r=c.getresponse();self.assertEqual(r.status,200);return c,r
 def frame(self,r):
  while True:
   line=r.readline()
   if not line:raise EOFError()
   if line.startswith(b'data: '):return json.loads(line[6:])
 def test_idle_heartbeat_events_ack_without_device_snapshot(self):
  with patch.object(self.rt.api,'account_snapshot',side_effect=AssertionError('Idle must not render device')):
   c,r=self.stream('?format=delta1&policy=idle1&mode=notifications')
   try:
    first=self.frame(r);self.assertEqual(first['live'],'idle1');self.assertNotIn('normalized',first['state']);self.assertEqual(first['state']['notifications'],[])
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
     f=pool.submit(self.frame,r);time.sleep(.5);self.assertFalse(f.done())
     t=time.monotonic();self.rt.push_alerts.battery(40);event=f.result(timeout=2);self.assertLess(time.monotonic()-t,2);ident=event['state']['notifications'][0]['id']
     self.rt.push_alerts.acknowledge('alice','a'*32,[ident]);ack=self.frame(r);self.assertEqual(ack['state']['notifications'],[])
     t=time.monotonic();heartbeat=self.frame(r);elapsed=time.monotonic()-t;self.assertGreater(elapsed,28);self.assertLess(elapsed,33);self.assertEqual(heartbeat['state']['notifications'],[])
   finally:c.close()
 def test_foreground_interval_and_legacy_compatibility(self):
  c,r=self.stream('?format=delta1&policy=idle1&mode=telemetry')
  try:
   first=self.frame(r);self.assertEqual(first['type'],'full');self.assertIn('normalized',first['state']);t=time.monotonic();second=self.frame(r);self.assertGreater(time.monotonic()-t,4.5);self.assertEqual(second['type'],'patch')
  finally:c.close()
  c,r=self.stream('')
  try:
   self.assertIn('normalized',self.frame(r));t=time.monotonic();self.frame(r);self.assertLess(time.monotonic()-t,2)
  finally:c.close()
 def test_stop_interrupts_idle_wait(self):
  c,r=self.stream('?format=delta1&policy=idle1&mode=notifications');self.frame(r)
  t=time.monotonic();self.rt.api.live_channels.stop();self.assertEqual(r.readline(),b'\n');self.assertEqual(r.readline(),b'');self.assertLess(time.monotonic()-t,1);c.close()
if __name__=='__main__':unittest.main(verbosity=2)
def run():
 import io
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
