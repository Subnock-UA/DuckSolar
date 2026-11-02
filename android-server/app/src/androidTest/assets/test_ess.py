"""Real TCP fixtures, no access to logger, ESS, phone or production files."""
import csv,json,socket,tempfile,threading,time,unittest
from pathlib import Path
from ducksolar.config import AppConfig
from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
from ducksolar.adapters.eybond import EyeBondAdapter
from ducksolar.protocol.ess_shadow import ESSShadow,decode_live,native_read,modbus_crc,LIVE_FIELDS
from ducksolar.protocol.pi30 import encode_command,encode_response_text,decode_packet
from ducksolar.archive_bootstrap import merge_on_disk,import_bundle

DATA='230.0 50.0 230.0 50.0 0500 0400 008 400 52.0 000 080 0030 05.0 300.0 52.0 000 00000000 00 00 1500 000'
VALUES={'QPIGS':DATA,'QMOD':'L','QPIWS':'00000100000000000000000000000000'}

def frame(tid,body,code=1,address=255,function=4):
    return EyeBondAdapter.build_frame(tid,code,address,function,body)

def bank():
    words=[4]+[0]*44
    direct=DaxtromnPI30Driver(AppConfig()).decode_telemetry(DATA)
    for name,(index,scale) in LIVE_FIELDS.items():words[index]=round(direct[name]*scale)
    body=b'\x05\x03\x5a'+b''.join(v.to_bytes(2,'little') for v in words)
    return body+modbus_crc(body).to_bytes(2,'little')

def targets(driver):
    return {(0x994,1):dict(device_id='inverter-1',requests=driver.read_requests,
        valid_response=driver.valid_response,decode_response=driver.decode_response,
        telemetry_requests={encode_command('QPIGS')},write_validator=lambda r:False)}

class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.now=100.;self.driver=DaxtromnPI30Driver(AppConfig())
        self.shadow=ESSShadow(targets(self.driver),lambda:self.now);self.shadow.reset('logger-A')
    def sample(self,tid=1):
        request=frame(tid,native_read());reply=frame(tid,bank())
        for part in (request[:3],request[3:]):self.shadow.feed('request',part)
        for part in (reply[:1],reply[1:7],reply[7:]):self.shadow.feed('response',part)
    def calibrate(self):
        for tid in range(3):
            self.now+=.3;self.sample(tid)
            self.shadow.calibrate((0x994,1),self.driver.decode_telemetry(DATA))
    def test_native_crc_and_byte_order(self):
        values=decode_live(bank(),45)
        self.assertEqual(values['pv_w'],1500);self.assertEqual(values['battery_v'],52)
        self.assertNotIn('bus_v',values);self.assertNotIn('temperature_c',values)
        self.assertIsNone(decode_live(bank()[:-1]+b'\x00',45))
        self.assertIsNone(decode_live(bank()[:-2],45))
    def test_requires_calibration_then_reuses_once(self):
        self.sample();self.assertIsNone(self.shadow.take((0x994,1),'QPIGS',0))
        self.calibrate();sample=self.shadow.take((0x994,1),'QPIGS',0)
        self.assertEqual(sample.values['output_w'],400)
        self.assertIsNone(self.shadow.take((0x994,1),'QPIGS',0))
    def test_stale_wrong_device_invalid_crc_reset(self):
        self.calibrate();self.now+=6
        self.assertIsNone(self.shadow.take((0x994,1),'QPIGS',0))
        self.sample(5);self.shadow.reset('logger-B')
        self.assertIsNone(self.shadow.take((0x994,1),'QPIGS',0))
        self.shadow.feed('request',frame(9,native_read()))
        self.shadow.feed('response',frame(9,bank(),code=0x7777))
        self.assertFalse(self.shadow.samples)
    def test_mismatch_revokes_calibration(self):
        self.calibrate();self.now+=.5;self.sample(9)
        wrong=self.driver.decode_telemetry(DATA);wrong['battery_v']=40
        self.shadow.calibrate((0x994,1),wrong)
        self.assertIsNone(self.shadow.take((0x994,1),'QPIGS',0))
    def test_repeated_calibration_same_reply_does_not_count(self):
        self.sample()
        for _ in range(5):self.shadow.calibrate((0x994,1),self.driver.decode_telemetry(DATA))
        self.assertEqual(self.shadow.calibration[(0x994,1)],1)
    def test_pi30_cloud_complete_reply(self):
        request=frame(4,encode_command('QPIGS'),0x994,1)
        reply=frame(4,encode_response_text(DATA),0x994,1)
        self.shadow.feed('request',request);self.shadow.feed('response',reply)
        self.assertEqual(self.shadow.take((0x994,1),'QPIGS',0).payload,encode_response_text(DATA))
    def test_echo_not_measurement_and_memory_bounded(self):
        self.shadow.feed('request',frame(4,encode_command('QPIGS'),0x994,1))
        self.shadow.feed('response',frame(4,encode_response_text('ACK'),0x994,1))
        self.assertFalse(self.shadow.samples)
        for tid in range(2000):self.shadow.feed('request',frame(tid,native_read()))
        self.assertLessEqual(len(self.shadow.pending),128)
    def test_write_non_echo_invalidates_cache(self):
        self.calibrate();body=bytes.fromhex('0506138f0001')
        body+=modbus_crc(body).to_bytes(2,'little')
        self.shadow.feed('request',frame(30,body,address=5))
        response=bytes.fromhex('0506138f011c');response+=modbus_crc(response).to_bytes(2,'little')
        self.shadow.feed('response',frame(30,response,address=5))
        self.assertFalse(self.shadow.samples)
    def test_unknown_device_transaction_coordinated_without_decoding(self):
        self.shadow.feed('request',frame(123,b'unknown command',code=0x1234,function=17))
        self.assertTrue(self.shadow.in_flight())
        self.shadow.feed('response',frame(123,b'unknown response',code=0x1234,function=17))
        self.assertFalse(self.shadow.in_flight());self.assertFalse(self.shadow.samples)

def wait_for(predicate,timeout=8):
    limit=time.monotonic()+timeout
    while time.monotonic()<limit:
        if predicate():return
        time.sleep(.025)
    raise AssertionError('Fixture timeout')

class SocketTests(unittest.TestCase):
    def test_late_local_reply_consumed_then_same_tid_ess_reply_forwarded(self):
        reserve=socket.socket();reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1];reserve.close()
        cfg=AppConfig(lwip_ip='127.0.0.1',local_server_port=port,cloud_proxy_enabled=False,cloud_port=18899,socket_timeout_s=.3)
        driver=DaxtromnPI30Driver(cfg);adapter=EyeBondAdapter(cfg,targets=targets(driver));adapter.start()
        peer=socket.create_connection(('127.0.0.1',port));cloud_sender,cloud_sink=socket.socketpair();cloud_sink.settimeout(.15)
        wait_for(lambda:adapter.connected)
        with adapter._cloud_lock:adapter._cloud=cloud_sender;adapter._cloud_ready=True
        errors=[]
        def query():
            try:adapter.transact(encode_command('QPIGS'),0x994,1)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=query);worker.start();request=peer.recv(4096);worker.join(2)
        try:
            self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],TimeoutError)
            reply=frame(int.from_bytes(request[:2],'big'),encode_response_text(DATA),0x994,1)
            peer.sendall(reply)
            with self.assertRaises(socket.timeout):cloud_sink.recv(4096)
            adapter._observe('SmartESS Server -> LWIP',request)
            peer.sendall(reply)
            cloud_sink.settimeout(2);received=cloud_sink.recv(4096)
            self.assertEqual(received,reply)
        finally:
            adapter.stop();peer.close();cloud_sender.close();cloud_sink.close()

    def test_offline_native_heartbeat_keeps_local_channel_usable(self):
        reserve=socket.socket();reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1];reserve.close()
        cfg=AppConfig(lwip_ip='127.0.0.1',local_server_port=port,cloud_proxy_enabled=False,cloud_port=502,socket_timeout_s=.5)
        driver=DaxtromnPI30Driver(cfg);adapter=EyeBondAdapter(cfg,targets=targets(driver));adapter.start()
        peer=socket.create_connection(('127.0.0.1',port));peer.settimeout(3)
        try:
            heartbeat=peer.recv(4096)
            self.assertEqual(heartbeat[6:8],bytes((255,1)))
            self.assertEqual(heartbeat[-2:],b'\x00\x23')
            peer.sendall(frame(int.from_bytes(heartbeat[:2],'big'),b'Q0000000000000',0x0102,function=1))
            wait_for(lambda:adapter._pending is None)
            response=[]
            worker=threading.Thread(target=lambda:response.append(adapter.transact(encode_command('QMOD'),0x994,1)))
            worker.start();request=peer.recv(4096)
            peer.sendall(frame(int.from_bytes(request[:2],'big'),encode_response_text('L'),0x994,1));worker.join(2)
            self.assertEqual(response,[encode_response_text('L')]);self.assertTrue(adapter.connected)
        finally:adapter.stop();peer.close()

    def test_full_proxy_local_reuse_and_cloud_loss(self):
        from ducksolar.core.device import DeviceMonitor
        from ducksolar.memory import BoundedRuntimeStore,MemoryLimits
        class Writer:
            def __init__(self):self.rows=[]
            def submit(self,row):self.rows.append(row);return True
        cloud_server=socket.socket();cloud_server.bind(('127.0.0.1',0));cloud_server.listen()
        local_port=socket.socket();local_port.bind(('127.0.0.1',0));port=local_port.getsockname()[1];local_port.close()
        cfg=AppConfig(lwip_ip='127.0.0.1',local_server_port=port,cloud_host='127.0.0.1',
            cloud_port=cloud_server.getsockname()[1],socket_timeout_s=1,auto_redirect_enabled=False)
        driver=DaxtromnPI30Driver(cfg);adapter=EyeBondAdapter(cfg,targets=targets(driver))
        from ducksolar.core.models import DeviceDefinition
        channel=adapter.create_channel(DeviceDefinition('inverter-1','Fixture','logger-1',driver.id,0x994))
        writer=Writer();monitor=DeviceMonitor(cfg,writer,BoundedRuntimeStore(MemoryLimits(live_points=0)),None,channel,driver,'inverter-1')
        stop=threading.Event();cloud_down=threading.Event();cloud_responses=[];logger_commands=[];errors=[]
        peers=[]
        def cloud():
            try:
                peer,_=cloud_server.accept();peers.append(peer);peer.settimeout(.05)
                tid=20000;due=0.;buffer=bytearray()
                # Multiple FC2 replies with one TID and an unknown frame must pass unchanged.
                metadata=frame(19000,b'\x02\x04',function=2)
                peer.sendall(metadata[:2]);peer.sendall(metadata[2:])
                while not stop.is_set() and not cloud_down.is_set():
                    if time.monotonic()>=due:
                        tid+=1;peer.sendall(frame(tid,native_read()));due=time.monotonic()+.7
                    try:part=peer.recv(65536)
                    except socket.timeout:continue
                    if not part:break
                    buffer.extend(part)
                    while len(buffer)>=8:
                        size=6+int.from_bytes(buffer[4:6],'big')
                        if len(buffer)<size:break
                        received=bytes(buffer[:size]);del buffer[:size];cloud_responses.append(received)
            except Exception as exc:
                if not stop.is_set():errors.append(repr(exc))
            finally:
                if peers:peers[0].close()
        def logger(peer):
            buffer=bytearray();peer.settimeout(.2)
            try:
                while not stop.is_set():
                    try:part=peer.recv(65536)
                    except socket.timeout:continue
                    if not part:break
                    buffer.extend(part)
                    while len(buffer)>=8:
                        size=6+int.from_bytes(buffer[4:6],'big')
                        if len(buffer)<size:break
                        request=bytes(buffer[:size]);del buffer[:size]
                        tid=int.from_bytes(request[:2],'big');code=int.from_bytes(request[2:4],'big')
                        if code==0x994:
                            command=decode_packet(request[8:]).decode();logger_commands.append((time.monotonic(),command))
                            reply=frame(tid,encode_response_text(VALUES[command]),code,1)
                        elif request[7]==2:
                            reply=frame(tid,b'\x00\x02Q0000000000000',0x0102,function=2)+frame(tid,b'\x00\x041.2',0x0102,function=2)
                            reply+=frame(18999,b'opaque\x00\x65\x09\x94\x00\x02\x01\x04',0x1234,function=17)
                        else:
                            if tid<10000:logger_commands.append((time.monotonic(),'NATIVE4501'))
                            reply=frame(tid,bank())
                        peer.sendall(reply[:5]);peer.sendall(reply[5:])
            except Exception as exc:
                if not stop.is_set():errors.append(repr(exc))
        worker=threading.Thread(target=cloud,daemon=True);worker.start()
        adapter.start();peer=socket.create_connection(('127.0.0.1',port));logger_worker=threading.Thread(target=logger,args=(peer,),daemon=True);logger_worker.start()
        monitor.start()
        try:
            wait_for(lambda:adapter.shadow.snapshot()['reuse']>=2 and len(writer.rows)>=5,timeout=28)
            self.assertEqual(len([f for f in cloud_responses if int.from_bytes(f[:2],'big')==19000]),2)
            self.assertTrue(any(f==frame(18999,b'opaque\x00\x65\x09\x94\x00\x02\x01\x04',0x1234,function=17) for f in cloud_responses))
            count_before=len([x for _,x in logger_commands if x=='QPIGS'])
            native_before=len([x for _,x in logger_commands if x=='NATIVE4501'])
            self.assertGreaterEqual(count_before,3)
            self.assertGreaterEqual(len(writer.rows),5)
            self.assertEqual(monitor.snapshot()['sample_source'],'ESS')
            cloud_down.set();wait_for(lambda:not adapter._cloud_ready,timeout=2)
            wait_for(lambda:len([x for _,x in logger_commands if x=='NATIVE4501'])>native_before,timeout=7)
            self.assertTrue(adapter.connected)
            # Seeing the outgoing request is earlier than receiving and
            # committing its reply in the independent monitor thread.
            wait_for(lambda:monitor.snapshot()['sample_source']=='Local',timeout=2)
            self.assertEqual(monitor.snapshot()['sample_source'],'Local')
            self.assertFalse(errors,errors)
            stamps=[r.timestamp for r in writer.rows]
            self.assertEqual(len(stamps),len(set(stamps)))
            print(json.dumps(dict(socket_reuse=adapter.shadow.snapshot(),rows=len(writer.rows),
                local_qpigs=count_before,cloud_frames=len(cloud_responses),cloud_loss_fallback=True)))
        finally:
            stop.set();monitor.stop();adapter.stop();peer.close();cloud_server.close()
            worker.join(1);logger_worker.join(1)
        self.assertFalse(monitor.thread.is_alive())
        self.assertFalse(adapter._tx_thread.is_alive())

class ArchiveTests(unittest.TestCase):
    def test_disk_merge_preserves_phone_deduplicates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.csv';target=root/'2026-10-10.csv'
            target.write_text('time,source,pv_w\n2026-10-10 12:00:00,Local,99\n',encoding='utf-8')
            source.write_text('time,source,pv_w\n2026-10-10 12:00:00,Local,100\n2026-10-10 12:00:05,Local,101\n2026-10-10 12:00:05,Local,101\n',encoding='utf-8')
            result=merge_on_disk(source,target,root/'work')
            self.assertEqual(result,dict(added=1,duplicates=1,conflicts=1))
            rows=list(csv.DictReader(target.open()))
            self.assertEqual(rows[0]['pv_w'],'99');self.assertEqual(len(rows),2)
            self.assertEqual(merge_on_disk(source,target,root/'work')['added'],0)

if __name__=='__main__':unittest.main(verbosity=2)
