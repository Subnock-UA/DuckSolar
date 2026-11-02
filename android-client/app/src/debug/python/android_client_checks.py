from android_client import AndroidTransport
from ducksolar.client_transport import TransportError
def bad_pin_check(url):
 try:AndroidTransport(url,'0'*64).request('state',headers={'Authorization':'Bearer TEST-MUST-NOT-BE-SENT'})
 except TransportError as exc:return exc.code=='tls.identity_mismatch'
 return False


def route_failover_check():
 import android_client as c,json,time
 with c._lock:
  original=dict(c._cfg);client_id=c._cfg['client_id'];valid=c._api.url
  try:
   c._cfg.update(lan='https://127.0.0.1:9',remote=valid)
   out=json.loads(c.resume(True));assert out['url']==valid and c._cfg['client_id']==client_id
   c._cfg.update(lan=valid,remote='https://127.0.0.1:9')
   out=json.loads(c.resume(True));assert out['url']==valid and c._cfg['client_id']==client_id
   return True
  finally:c._cfg=original;c._save()


def saved_session_connect_failover_check():
 import android_client as c,json,time
 with c._lock:
  original=dict(c._cfg);auth=c._auth;valid=c._api.url;token=c._cfg['token'];identity=c._cfg['client_id']
  def forbidden(*a,**k):raise AssertionError('Network routing must not call login/bind/register')
  c._auth=forbidden
  try:
   started=time.monotonic()
   out=json.loads(c.connect('https://127.0.0.1:9',valid,c._cfg['username'],'',c._cfg['serial'],'',False))
   assert out['url']==valid and c._cfg['token']==token and c._cfg['client_id']==identity
   assert time.monotonic()-started<8
   out=json.loads(c.connect(valid,'https://127.0.0.1:9',c._cfg['username'],'',c._cfg['serial'],'',False))
   assert out['url']==valid and c._cfg['token']==token
   return True
  finally:c._auth=auth;c._cfg=original;c._save()

def reconnect_keeps_live_channel():
 import android_client as c,time,json
 live=c._live;assert live and live.connected
 live.interrupt()
 end=time.monotonic()+8
 while live.connected and time.monotonic()<end:time.sleep(.02)
 assert not live.connected
 c.resume(True)
 assert c._live is live,'Route probe replaced a recovering connection'
 end=time.monotonic()+15
 while not live.connected and time.monotonic()<end:time.sleep(.05)
 assert live.connected,'Live channel failed to recover'
 return True

def live_identity():
 import android_client as c
 return id(c._live) if c._live else 0
