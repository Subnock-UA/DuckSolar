import sys,os,json,tempfile,threading,unittest,subprocess,socket,time,hashlib,zipfile,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desktop.controller import Controller
from desktop.support import Support,export_diagnostics
from ducksolar.notification_settings import DEFAULTS
class Checks(unittest.TestCase):
 def test_notification_dedup_and_no_ack_before_post(self):
  with tempfile.TemporaryDirectory() as tmp:
   backend=Mock();backend.initialize.return_value='{}';backend.connection_profile.return_value='scope';backend.notification_settings.return_value=json.dumps(dict(settings=DEFAULTS));backend.notification_ack.return_value=True
   ctrl=Controller(tmp,notify=lambda event:False,backend=backend);event=dict(id='a'*32,kind='grid_lost',message='Відсутня напруга',created=time.time());batch=dict(events=[event])
   self.assertEqual(ctrl.deliver(batch),[]);backend.notification_ack.assert_not_called()
   posted=[];ctrl.notify=lambda event:posted.append(event) or True
   self.assertEqual(ctrl.deliver(batch),['a'*32]);self.assertEqual(len(posted),1)
   ctrl.deliver(batch);self.assertEqual(len(posted),1)
   ctrl2=Controller(tmp,notify=lambda event:posted.append(event) or True,backend=backend);ctrl2.deliver(batch);self.assertEqual(len(posted),1)
 def test_backend_mutation_dispatched_once_and_profile_guard(self):
  import desktop_client as client
  original=client._api;cfg=client._cfg;fake=Mock();fake.call.return_value=dict(status='verified');client._api=fake;client._cfg=dict(pin='p',username='fixture')
  try:
   result=json.loads(client.feature_call('night_charge',json.dumps([dict(enabled=False)])));self.assertEqual(result['status'],'verified');fake.call.assert_called_once_with('insights','night_charge',dict(enabled=False))
   fake.call.side_effect=OSError('Ambiguous response')
   with self.assertRaises(OSError):client.feature_call('night_charge',json.dumps([dict(enabled=True)]))
   self.assertEqual(fake.call.call_count,2)
  finally:client._api=original;client._cfg=cfg
 def test_support_download_resume_logs_and_manifest_guards(self):
  helper=Path(__file__).resolve().parents[2]/'pc-helper/update_server.py'
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'Data/AndroidSupport';folder.mkdir(parents=True);bundle=root/'DS_PC_Client_ver.b1.0.1.zip'
   with zipfile.ZipFile(bundle,'w') as z:z.writestr('test.bin',b'x'*700000)
   data=bundle.read_bytes();metadata=dict(contract='ducksolar.desktop-client.v1',component='desktop_client',version='b1.0.1',version_code=10000,path=str(bundle),bytes=len(data),sha256=hashlib.sha256(data).hexdigest());manifest=folder/'desktop-client.json';manifest.write_text(json.dumps(metadata))
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   with (root/'helper.log').open('w') as log:
    command=[os.environ['PC_HELPER_EXE']] if os.environ.get('PC_HELPER_EXE') else [sys.executable,str(helper)]
    proc=subprocess.Popen(command+['--root',str(root),'--host','127.0.0.1','--port',str(port),'--headless'],stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
     deadline=time.monotonic()+15;status=None
     while time.monotonic()<deadline:
      try:status=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/status',timeout=1));break
      except Exception:time.sleep(.1)
     self.assertEqual(status['helper_version'],'b2.0.0');self.assertEqual(status['desktop_client'],1)
     local=root/'local';local.mkdir();(local/'client-events.jsonl').write_text('{"code":"fixture"}\n');(local/'connection.json').write_text('{"token":"excluded"}')
     support=Support(f'http://127.0.0.1:{port}',local,status['helper_id']);actual=support.desktop_manifest();self.assertEqual(actual['sha256'],metadata['sha256'])
     download=root/'download';download.mkdir();(download/'DS_PC_Client_ver.b1.0.1.zip.part').write_bytes(data[:125000]);result=support.download(download);self.assertEqual(Path(result['path']).read_bytes(),data)
     sent=support.upload_diagnostics('c'*32);self.assertEqual(len(sent['uploaded']),1)
     diag=root/'diagnostic.zip';export_diagnostics(local,diag)
     with zipfile.ZipFile(diag) as z:self.assertNotIn('connection.json',z.namelist())
     android=support.json('/v1/manifest');self.assertEqual(android['updates'],[])
     manifest.write_text(json.dumps(dict(metadata,path=str(root.parent/'outside.zip'))))
     with self.assertRaises(ValueError):support.desktop_manifest()
    finally:proc.terminate();proc.wait(timeout=10)
 def test_real_tls_pair_login_session_live_and_bad_pin_guard(self):
  import ssl,http.server,datetime
  from cryptography import x509
  from cryptography.x509.oid import NameOID
  from cryptography.hazmat.primitives import hashes,serialization
  from cryptography.hazmat.primitives.asymmetric import rsa
  from spake2 import SPAKE2_B
  from ducksolar.pairing_client import proof
  import desktop_client as client
  from desktop.fixtures import envelope
  from ducksolar.tls_transport import SecureTransport
  from ducksolar.client_transport import TransportError
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);key=rsa.generate_private_key(public_exponent=65537,key_size=2048);subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'DuckSolar isolated fixture')]);now=datetime.datetime.now(datetime.timezone.utc)
   cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).sign(key,hashes.SHA256());pin=hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
   (root/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM));(root/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));seen=[];exchange={}
   class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def reply(self,value):
     data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
     body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(self.path)
     if self.path.endswith('/pair/start'):
      spake=SPAKE2_B(b'ABCD2345',idA=b'DX_Client',idB=b'DX_Server');message=spake.start();secret=spake.finish(bytes.fromhex(body['message']));exchange['key']=secret;self.reply(dict(id='fixture-pair',message=message.hex(),fingerprint=pin,proof=proof(secret,'server','fixture-pair',pin)))
     elif self.path.endswith('/pair/finish'):
      assert body['proof']==proof(exchange['key'],'client','fixture-pair',pin);self.reply(dict(paired=True,trust_ticket='fixture-ticket',proof=proof(exchange['key'],'complete','fixture-pair',pin)))
     elif self.path.endswith('/auth/login'):
      assert body['username']=='fixture' and body['password']=='fixture-password';self.reply(dict(token='fixture-token'))
     elif self.path.endswith('/auth/bind'):
      assert self.headers['Authorization']=='Bearer fixture-token';self.reply(dict(bound=True))
     elif self.path.endswith('/session'):
      assert self.headers['Authorization']=='Bearer fixture-token';self.reply(dict(api_version=3,capabilities=['api.v3'],client_session_id='fixture-client-session',server_session_id='fixture-session',server_version='1.4.43',server_time=time.time()))
     else:self.reply(dict(result=True))
    def do_GET(self):
     seen.append(self.path);self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
     for i in range(8):
      state=envelope()['state'];state.update(api_version=3,session_id='fixture-session',sequence=i,server_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),statuses={'API':True,'Inverter':True})
      try:self.wfile.write(('data: '+json.dumps(state)+'\n\n').encode());self.wfile.flush()
      except OSError:break
      time.sleep(.08)
   server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_3;context.load_cert_chain(root/'cert.pem',root/'key.pem');server.socket=context.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    client.initialize(str(root/'profile'));url='https://127.0.0.1:'+str(server.server_port);reply=json.loads(client.connect(url,'','fixture','fixture-password','serial','ABCD2345'));self.assertTrue(reply['connected']);self.assertTrue(json.loads(client.snapshot())['connected'])
    raw=(root/'profile/connection.json').read_text();self.assertNotIn('fixture-token',raw);self.assertNotIn('fixture-password',raw)
    before=len(seen)
    with self.assertRaises(TransportError):SecureTransport(url,'0'*64).request('session',b'{}',{'Authorization':'Bearer must-not-send'})
    self.assertEqual(len(seen),before)
   finally:client.stop('fixture_end');server.shutdown();server.server_close();thread.join(timeout=3)
 def test_every_android_client_function_exposed_or_platform_adapted(self):
  import ast
  root=Path(__file__).resolve().parents[1];source=(root/'desktop/pages.py').read_text(encoding='utf-8');app=(root/'desktop/app.py').read_text(encoding='utf-8');combined=source+app
  for name in ['graph_start','graph_cancel','balance_start','balance_cancel','finance_month','add_meter_reading','event_rows','history_dates','parameter_snapshot','refresh_parameters','submit_parameter','parameter_command_status','tariff_status','tariff_check','weather_status','weather_settings','weather_start','weather_cancel','weather_profile','notification_settings','switch_route']:
   self.assertIn(name,combined)
  from desktop.pages import ENTRIES
  self.assertEqual(len(ENTRIES),30);self.assertTrue({'battery','night','pv','profiles','commands','calendar','forecast_stats','forecast_live','charge_plan','battery_history'}.issubset({k for t,k,m in ENTRIES}))
if __name__=='__main__':unittest.main(verbosity=2)
