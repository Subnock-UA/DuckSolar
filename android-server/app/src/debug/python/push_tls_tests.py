import sys,tempfile,unittest,ssl,http.client,json
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[5]
sys.path[:0]=[str(ROOT/'android-server/app/src/main/python'),str(ROOT)]
from ducksolar.config import AppConfig
from ducksolar.server_runtime import ServerRuntime

class PushTLS(unittest.TestCase):
 def test_authenticated_settings_feed_ack_and_account_isolation(self):
  with tempfile.TemporaryDirectory() as temp:
   runtime=ServerRuntime(AppConfig(root_dir=temp,api_host='127.0.0.1',api_port=0,dtu_pn='push-test-pn'))
   runtime.api.start();runtime.active=True;api=runtime.api;client='a'*32
   try:
    def account(name):
     api.accounts.register(name,'test-password','fixture')
     token=api.accounts.login(name,'test-password','fixture',trusted=True)['token']
     api.accounts.bind('Bearer '+token,'push-test-pn',runtime,'fixture')
     return token
    token=account('alice');other=account('bob')
    def request(path,body=None,headers=None):
     context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE;context.minimum_version=ssl.TLSVersion.TLSv1_3
     conn=http.client.HTTPSConnection('127.0.0.1',api.http.server_port,context=context,timeout=5)
     try:
      conn.request('POST' if body is not None else 'GET','/api/v1/'+path,json.dumps(body).encode() if body is not None else None,headers or {})
      response=conn.getresponse();return response.status,json.loads(response.read())
     finally:conn.close()
    def session(token):
     status,data=request('session',dict(client_id=client,client_version='1.6.14',api_version=3),{'Authorization':'Bearer '+token})
     self.assertEqual(status,200)
     return {'Authorization':'Bearer '+token,'X-DX-Client-ID':client,'X-DX-Client-Session':data['client_session_id']}
    headers=session(token)
    def call(method,*args,headers=headers):return request('data',dict(domain='notifications',method=method,args=list(args),kwargs={}),headers)
    status,data=call('settings',dict(server_battery_threshold=65));self.assertEqual(status,200);self.assertEqual(data['result']['server_battery_threshold'],65)
    runtime.push_alerts.battery(60)
    status,data=request('state',headers=headers);self.assertEqual(status,200)
    self.assertEqual(data['notifications'][0]['threshold'],65);ident=data['notifications'][0]['id']
    # SSE carries the same durable queue using the authenticated client identity.
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    conn=http.client.HTTPSConnection('127.0.0.1',api.http.server_port,context=context,timeout=5)
    conn.request('GET','/api/v1/events',headers=headers);response=conn.getresponse()
    try:
     while True:
      line=response.readline()
      if line.startswith(b'data: '):
       self.assertEqual(json.loads(line[6:])['notifications'][0]['id'],ident);break
    finally:conn.close()
    self.assertEqual(call('settings',dict(server_battery_threshold=True))[0],400)
    self.assertEqual(request('state')[0],401)
    bob=session(other)
    self.assertEqual(request('state',headers=bob)[1]['notifications'],[])
    # Reusing the same client ID with another account cannot drain Alice's queue.
    self.assertEqual(call('ack',[ident],headers=bob)[0],200)
    headers=session(token)
    self.assertEqual(len(request('state',headers=headers)[1]['notifications']),1)
    self.assertEqual(call('ack',[ident],headers=headers)[0],200)
    self.assertEqual(request('state',headers=headers)[1]['notifications'],[])
   finally:runtime.stop()

if __name__=='__main__':unittest.main()
