"""Necessary recovery/identity regressions using local socket pairs only."""
import json,socket,struct,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ducksolar.config import AppConfig
from ducksolar.adapters.native_route import NativeRoute

class Collector:
    def __init__(self,endpoint='vip1.eybond.com',pn='Q0000000000000',on_write=None):
        self.endpoint=endpoint;self.port='502';self.pn=pn;self.writes=[];self.on_write=on_write
    def connect(self):
        client,server=socket.socketpair();client.settimeout(2)
        def exact(n):
            data=b''
            while len(data)<n:
                p=server.recv(n-len(data))
                if not p:raise EOFError()
                data+=p
            return data
        def serve():
            with server:
                try:
                    while True:
                        h=exact(8);tid,dev,length,addr,fc=struct.unpack('>HHHBB',h);p=exact(length-2);param=p[0]
                        assert dev==1 and addr==255
                        if fc==2:
                            value={2:self.pn,5:'3.6.7.6',21:self.endpoint,24:self.port}.get(param)
                            body=(bytes([0,param])+value.encode()) if value is not None else bytes([1,param])
                        elif fc==3:
                            if self.on_write:self.on_write(param,p[1:])
                            self.writes.append((param,p[1:].decode()))
                            if param==21:self.endpoint=p[1:].decode()
                            if param==24:self.port=p[1:].decode()
                            body=bytes([0,param])
                        else:raise AssertionError('Unexpected device command')
                        response=struct.pack('>HHHBB',tid,0x0102,len(body)+2,255,fc)+body
                        # Force partial TCP reads rather than assuming chunks=frames.
                        server.sendall(response[:5]);server.sendall(response[5:])
                except (EOFError,OSError):pass
        threading.Thread(target=serve,daemon=True).start()
        return client

class Adapter:
    def __init__(self,root):
        self.cfg=AppConfig(root_dir=str(root));self.logger_id='logger-1'
        self.connected=True;self.events=[]
    def _ess_event(self,code,**fields):self.events.append((code,fields))
    def _event(self,message):pass
    def detect_lan_ip(self):return '192.0.2.10'

class NativeRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.adapter=Adapter(Path(self.temp.name));self.route=NativeRoute(self.adapter)

    def test_native_cloud_route_backup_precedes_write_and_stop_restores(self):
        def before_write(param,value):
            if param in (21,24):
                record=json.loads(self.route.path.read_text())
                self.assertEqual(record['original_endpoint'],'vip1.eybond.com')
                self.assertTrue(record['active'])
                self.assertEqual(record['original_port'],502)
        collector=Collector(on_write=before_write)
        self.route._session=lambda **kw:(collector.connect(),'192.0.2.10')
        self.route._provision()
        self.assertEqual(collector.endpoint,'192.0.2.10')
        self.assertEqual(collector.writes,[(24,'18899'),(21,'192.0.2.10'),(29,'1')])
        self.route.stop()
        self.assertEqual(collector.endpoint,'vip1.eybond.com')
        self.assertEqual(collector.writes[-3:],[(24,'502'),(21,'vip1.eybond.com'),(29,'1')])
        self.assertEqual(collector.port,'502')
        self.assertFalse(json.loads(self.route.path.read_text())['active'])

    def test_changed_address_requires_pn_and_persists_verified_ip(self):
        with Collector(pn='FOREIGN').connect() as sock:
            self.assertFalse(self.route.verify_new_peer(sock,'192.0.2.22'))
        self.assertEqual(self.adapter.cfg.lwip_ip,'192.0.2.20')
        with Collector().connect() as sock:
            self.assertTrue(self.route.verify_new_peer(sock,'192.0.2.22'))
        self.assertEqual(self.adapter.cfg.lwip_ip,'192.0.2.22')
        restored=NativeRoute(Adapter(Path(self.temp.name)))
        self.assertEqual(restored.cfg.lwip_ip,'192.0.2.22')

    def test_existing_recovery_record_never_overwritten_with_phone_ip(self):
        self.route._save(original_endpoint='vip1.eybond.com',active=True,logger_ip='192.0.2.20')
        collector=Collector(endpoint='192.0.2.10')
        self.route._session=lambda **kw:(collector.connect(),'192.0.2.10')
        self.route._provision()
        self.assertEqual(self.route.record['original_endpoint'],'vip1.eybond.com')
        self.assertEqual(collector.writes,[(24,'18899'),(29,'1')])

    def test_unsupported_firmware_never_writes_endpoint(self):
        collector=Collector()
        self.route._session=lambda **kw:(collector.connect(),'192.0.2.10')
        real_query=self.route.query
        self.route.query=lambda sock,param:'9.9.9' if param==5 else real_query(sock,param)
        with patch.object(self.route,'_redirect'):
            with self.assertRaises(ValueError):self.route._provision()
        self.assertEqual(collector.writes,[])

    def test_mac_arp_unavailable_uses_no_guessed_identity(self):
        with patch.object(Path,'read_text',side_effect=PermissionError()):
            self.assertIsNone(self.route._arp_candidate())

    def test_partial_setup_failure_restores_endpoint_and_port(self):
        collector=Collector()
        self.route._session=lambda **kw:(collector.connect(),'192.0.2.10')
        write=self.route._write
        def failing_write(sock,param,value):
            if param==21 and value=='192.0.2.10':raise OSError('simulated write failure')
            return write(sock,param,value)
        self.route._write=failing_write
        with patch.object(self.route,'_redirect'):
            with self.assertRaises(OSError):self.route._provision()
        self.assertEqual(collector.endpoint,'vip1.eybond.com')
        self.assertEqual(collector.port,'502')
        self.assertEqual(collector.writes,[(24,'18899'),(24,'502'),(21,'vip1.eybond.com'),(29,'1')])
        self.assertFalse(self.route.record['active'])

if __name__=='__main__':unittest.main(verbosity=2)
