import sys, socket, threading, unittest, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path[:0]=[str(Path(__file__).resolve().parents[5]),str(Path(__file__).resolve().parents[5])]
from ducksolar.live_channels import LiveChannels
from ducksolar.adapters.native_route import NativeRoute
from ducksolar.adapters.eybond import DeviceChannel
import android_bridge
from ducksolar import network_info

class FinalAlpha(unittest.TestCase):
    def test_reconnect_replaces_only_same_account_client(self):
        registry=LiveChannels()
        a,b,c=Mock(),Mock(),Mock()
        key,old=registry.open('alice','phone',a)
        _,other=registry.open('bob','phone',b)
        _,new=registry.open('alice','phone',c)
        self.assertTrue(old['cancelled'].is_set())
        a.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        b.shutdown.assert_not_called()
        registry.release(key,old)
        self.assertIs(registry.channels[key],new)
        registry.stop()
        self.assertTrue(other['cancelled'].is_set())
        self.assertEqual(registry.channels,{})
        with self.assertRaises(ConnectionAbortedError):registry.open('alice','phone',Mock())

    def test_shutdown_unblocks_actual_reader(self):
        a,b=socket.socketpair()
        registry=LiveChannels(); registry.open('alice','phone',a)
        result=[]
        worker=threading.Thread(target=lambda:result.append(b.recv(1)))
        try:
            worker.start();registry.stop();worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(result,[b''])
        finally:a.close();b.close()

    def test_no_provision_without_route_then_automatic_recovery(self):
        route=NativeRoute.__new__(NativeRoute)
        route.adapter=SimpleNamespace(connected=False,detect_lan_ip=lambda:'192.0.2.10')
        route.cfg=SimpleNamespace(lwip_ip='192.0.2.20')
        route.record={};route.stop_event=threading.Event();route.network_wake=threading.Event()
        route.wake=Mock();route._event=Mock()
        route._route_available=Mock(side_effect=[False,False,True])
        route._provision=Mock(side_effect=route.stop_event.set)
        route._run()
        route._provision.assert_called_once()
        self.assertEqual([c.args[0] for c in route._event.call_args_list],['waiting_network','network_restored'])

    def test_new_network_bypasses_failure_backoff(self):
        route=NativeRoute.__new__(NativeRoute)
        route.adapter=SimpleNamespace(connected=False,detect_lan_ip=lambda:'192.0.2.10')
        route.cfg=SimpleNamespace(lwip_ip='192.0.2.20')
        route.record={};route.stop_event=threading.Event();route.network_wake=threading.Event()
        route.wake=threading.Event();route._event=Mock();route._route_available=lambda:True
        calls=[]
        def provision():
            calls.append(True)
            if len(calls)==1:
                route.network_changed()
                raise OSError('test route interrupted')
            route.stop_event.set()
        route._provision=provision
        worker=threading.Thread(target=route._run,daemon=True)
        worker.start();worker.join(2)
        try:self.assertFalse(worker.is_alive());self.assertEqual(len(calls),2)
        finally:route.stop_event.set();route.wake.set();worker.join(2)

    def test_missing_then_same_route_wakes_without_closing_socket(self):
        binding=dict(network='613',source='192.0.2.10')
        route=SimpleNamespace(network_changed=Mock())
        gateway=SimpleNamespace(cfg=SimpleNamespace(lwip_ip='192.0.2.20'),native_route=route,
                                _logger_network_binding=binding,close_active=Mock())
        runtime=SimpleNamespace(gateway=gateway,network=SimpleNamespace(lock=threading.Lock(),value={}),logs=SimpleNamespace(event=Mock()))
        with patch.object(android_bridge,'_runtime',runtime),patch.object(network_info,'lan_addresses',return_value=[]),patch.object(network_info,'wifi_snapshot',return_value={'wifi':[]}):
            with patch.object(network_info,'logger_route',side_effect=OSError('offline')):android_bridge.network_changed()
            route.network_changed.assert_not_called()
            with patch.object(network_info,'logger_route',return_value=binding):
                android_bridge.network_changed();android_bridge.network_changed()
            route.network_changed.assert_called_once();gateway.close_active.assert_not_called()

    def test_native_route_has_single_automatic_owner(self):
        transport=DeviceChannel.__new__(DeviceChannel)
        transport.adapter=SimpleNamespace(native_route=object())
        self.assertTrue(transport.automatic_recovery_managed)
        transport.adapter.native_route=None
        self.assertFalse(transport.automatic_recovery_managed)

    def test_tls_live_replacement_preserves_push_and_complete_large_json(self):
        import tempfile, ssl, http.client, json
        from ducksolar.config import AppConfig
        from ducksolar.server_runtime import ServerRuntime
        with tempfile.TemporaryDirectory() as temp:
            runtime=ServerRuntime(AppConfig(root_dir=temp,api_host='127.0.0.1',api_port=0,dtu_pn='final-alpha-test'))
            api=runtime.api;api.start();runtime.active=True
            connections=[]
            try:
                api.accounts.register('alice','test-password','fixture')
                token=api.accounts.login('alice','test-password','fixture',trusted=True)['token']
                api.accounts.bind('Bearer '+token,'final-alpha-test',runtime,'fixture')
                def connect():
                    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
                    context.minimum_version=ssl.TLSVersion.TLSv1_3
                    c=http.client.HTTPSConnection('127.0.0.1',api.http.server_port,context=context,timeout=5)
                    connections.append(c);return c
                c=connect();c.request('POST','/api/v1/session',json.dumps(dict(client_id='f'*32,client_version='1.6.14',api_version=3)),{'Authorization':'Bearer '+token})
                reply=c.getresponse();self.assertEqual(reply.status,200);session=json.loads(reply.read())
                headers={'Authorization':'Bearer '+token,'X-DX-Client-ID':'f'*32,'X-DX-Client-Session':session['client_session_id']}
                api.runtime.push_alerts.settings('alice','f'*32,['inverter-1'],dict(server_battery_threshold=50))
                api.runtime.push_alerts.battery(49)
                original=api.account_snapshot
                def large(*args):
                    state=original(*args);state['test_utf8']='Україна'*20000;return state
                api.account_snapshot=large
                logs=[];original_event=runtime.logs.event
                def event(*args,**kwargs):logs.append(kwargs);return original_event(*args,**kwargs)
                runtime.logs.event=event
                def stream():
                    conn=connect();conn.request('GET','/api/v1/events',headers=headers)
                    response=conn.getresponse();self.assertEqual(response.status,200)
                    while True:
                        line=response.readline()
                        if line.startswith(b'data: '):return response,json.loads(line[6:])
                first,state=stream();self.assertEqual(len(state['test_utf8']),140000)
                self.assertEqual(len(state['notifications']),1)
                second,state2=stream();self.assertEqual(state['notifications'],state2['notifications'])
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and not any(x.get('reason')=='replaced' for x in logs):time.sleep(.01)
                self.assertTrue(any(x.get('code')=='api.live.disconnected' and x.get('reason')=='replaced' for x in logs))
                self.assertEqual(len(api.live_channels.channels),1)
                self.assertEqual(len(api.runtime.push_alerts.feed('alice','f'*32,['inverter-1'])),1)
                api.stop();self.assertEqual(api.live_channels.channels,{})
            finally:
                for c in connections:c.close()
                runtime.stop()

if __name__=='__main__':unittest.main()
