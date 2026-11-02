import socket,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from test_ess import frame,targets,bank,wait_for
from test_priority import receive
from ducksolar.config import AppConfig
from ducksolar.adapters.eybond import EyeBondAdapter
from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
from ducksolar.drivers.parameter_library import valid_request
from ducksolar.protocol.ess_shadow import native_read
from ducksolar.protocol.pi30 import decode_packet,encode_response_text
from ducksolar.protocol.dispatcher import ProtocolDispatcher
from ducksolar.core.models import DeviceDefinition
from ducksolar.parameter_commands import ParameterCommands

class SettingsProxyTest(unittest.TestCase):
    def test_controlled_write_readback_keeps_ESS_flow_and_writes_only_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            ess_server=socket.socket();ess_server.bind(('127.0.0.1',0));ess_server.listen();ess_server.settimeout(3)
            reserve=socket.socket();reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1];reserve.close()
            cfg=AppConfig(root_dir=temporary,lwip_ip='127.0.0.1',local_server_port=port,cloud_host='127.0.0.1',cloud_port=ess_server.getsockname()[1])
            driver=DaxtromnPI30Driver(cfg);mapping=targets(driver);mapping[(0x994,1)]['write_validator']=valid_request
            adapter=EyeBondAdapter(cfg,targets=mapping);adapter.start()
            peer=socket.create_connection(('127.0.0.1',port));ess,_=ess_server.accept()
            channel=adapter.create_channel(DeviceDefinition('inverter-1','Fixture','logger-1',driver.id,0x994))
            dispatcher=ProtocolDispatcher(channel);dispatcher.start();stop=threading.Event();qid=threading.Event();send_lock=threading.Lock();writes=[]
            fields='230.0 26.9 230.0 50.0 26.9 6200 6200 48.0 46.0 40.0 55.2 54.0 2 070 120 1 1 2 1 01 0 0 57.0 0 1 46.0 22 44.0'.split()
            raw={'QID':'12345678901234','QPI':'PI30','QMN':'VMII-NXPW5KW','QVFW':'VERFW:00074.11','QPIRI':' '.join(fields),'QMOD':'L'}
            refreshed=[]
            params=SimpleNamespace(snapshot=lambda:dict(stale=False,raw=raw),request_refresh=lambda:refreshed.append(True))
            dev=SimpleNamespace(channel=channel,driver=driver,parameters=params,monitor=SimpleNamespace(dispatcher=dispatcher),definition=SimpleNamespace(logger_id='logger-1'))
            runtime=SimpleNamespace(cfg=cfg,active=True,logs=SimpleNamespace(event=lambda *args,**kwargs:None),adapters={'logger-1':adapter},device=lambda ident:dev)
            manager=ParameterCommands(runtime);manager.VERIFY_DELAYS=(.05,)
            authorizations=[];timers=[]
            def send(reply):
                with send_lock:peer.sendall(reply)
            def logger():
                peer.settimeout(.1);buffer=bytearray();first=True
                while not stop.is_set():
                    try:part=peer.recv(65536)
                    except socket.timeout:continue
                    if not part:break
                    buffer.extend(part)
                    while len(buffer)>=8:
                        size=6+int.from_bytes(buffer[4:6],'big')
                        if len(buffer)<size:break
                        request=bytes(buffer[:size]);del buffer[:size];tid=int.from_bytes(request[:2],'big')
                        if request[2:4]==b'\x00\x01':send(frame(tid,bank()));continue
                        name=decode_packet(request[8:]).decode()
                        if name=='PGR00':writes.append(name);fields[15]='0';value='ACK'
                        else:value=' '.join(fields) if name=='QPIRI' else raw[name]
                        reply=frame(tid,encode_response_text(value),0x994,1)
                        if name=='QID' and first:
                            first=False;timer=threading.Timer(.7,send,args=(reply,));timers.append(timer);timer.start();qid.set()
                        else:send(reply)
            worker=threading.Thread(target=logger);worker.start()
            try:
                wait_for(lambda:adapter._cloud_ready)
                result=manager.submit('inverter-1','grid.input_range',0,1,'fixture-user',lambda:authorizations.append(True))
                self.assertTrue(qid.wait(2));request=frame(33000,native_read());ess.sendall(request)
                self.assertEqual(receive(ess,.25),frame(33000,bank()))
                wait_for(lambda:manager.status(result['operation_id'],'fixture-user','inverter-1')['status']=='verified',timeout=5)
                self.assertEqual(writes,['PGR00']);self.assertGreaterEqual(len(authorizations),2);self.assertTrue(refreshed)
            finally:
                print('SETTINGS_STATE',manager.items,'WRITES',writes)
                runtime.active=False;stop.set()
                for timer in timers:timer.join(2)
                dispatcher.stop();adapter.stop();peer.close();ess.close();ess_server.close();worker.join(2)

if __name__=='__main__':unittest.main(verbosity=2)
