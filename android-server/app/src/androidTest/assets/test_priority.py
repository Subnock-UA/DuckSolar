"""Regression for ESS deadlines while a local inverter read is slow."""
import socket,threading,time,unittest,json
from test_ess import frame,targets,bank,DATA,wait_for
from ducksolar.adapters.eybond import EyeBondAdapter
from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
from ducksolar.config import AppConfig
from ducksolar.protocol.pi30 import encode_command,encode_response_text
from ducksolar.protocol.ess_shadow import ESSShadow,native_read

def receive(peer,deadline=.4):
    peer.settimeout(deadline);data=bytearray()
    while len(data)<8 or len(data)<6+int.from_bytes(data[4:6],'big'):
        part=peer.recv(65536)
        if not part:raise AssertionError('Unexpected EOF')
        data.extend(part)
    return bytes(data)

class PriorityTests(unittest.TestCase):
    def test_partial_ess_header_prevents_local_injection(self):
        driver=DaxtromnPI30Driver(AppConfig());shadow=ESSShadow(targets(driver));shadow.reset('A')
        request=frame(77,native_read())
        shadow.feed('request',request[:3]);self.assertTrue(shadow.in_flight())
        shadow.feed('request',request[3:]);self.assertTrue(shadow.in_flight())
        shadow.feed('response',frame(77,bank()));self.assertFalse(shadow.in_flight())

    def test_predicts_observed_five_or_sixty_second_cadence_and_resets(self):
        for period in (5,60):
            now=[100.];driver=DaxtromnPI30Driver(AppConfig());shadow=ESSShadow(targets(driver),lambda:now[0]);shadow.reset('A')
            for tid in range(3):
                shadow.feed('request',frame(tid,native_read()));shadow.feed('response',frame(tid,bank()));now[0]+=period
            now[0]-=period
            self.assertFalse(shadow.approaching_live_read(.8))
            now[0]+=period-.5;self.assertTrue(shadow.approaching_live_read(.8))
            shadow.cloud_reconnected();self.assertFalse(shadow.approaching_live_read(.8))

    def test_native_queued_job_uses_fresh_ess_without_wire_request(self):
        now=time.monotonic();cfg=AppConfig(cloud_proxy_enabled=False);driver=DaxtromnPI30Driver(cfg)
        adapter=EyeBondAdapter(cfg,targets=targets(driver));adapter.connection_id='A';adapter.shadow.reset('A')
        adapter._cloud_ready=True
        route=(0x994,1)
        for tid in range(3):
            adapter.shadow.feed('request',frame(tid,native_read()));adapter.shadow.feed('response',frame(tid,bank()))
            adapter.shadow.calibrate(route,driver.decode_telemetry(DATA))
        # No logger socket exists: any attempted local send would fail.
        body=adapter._wire_transact(native_read(),1,255,4,(1,0x102),'NATIVE4501',route=route,target=targets(driver)[route])
        self.assertEqual(body,bank());self.assertEqual(adapter.measurement_sources[route],'ESS')
        self.assertEqual(adapter.shadow.snapshot()['reuse'],1)

    def test_ess_round_trip_during_delayed_local_response(self):
        cloud=socket.socket();cloud.bind(('127.0.0.1',0));cloud.listen();cloud.settimeout(3)
        reserve=socket.socket();reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1];reserve.close()
        cfg=AppConfig(lwip_ip='127.0.0.1',local_server_port=port,cloud_host='127.0.0.1',cloud_port=cloud.getsockname()[1],socket_timeout_s=2)
        driver=DaxtromnPI30Driver(cfg);adapter=EyeBondAdapter(cfg,targets=targets(driver));adapter.start()
        logger=socket.create_connection(('127.0.0.1',port));ess,_=cloud.accept();results=[];errors=[]
        def local():
            try:
                # Settings' identity/write/readback sequence holds this lock.
                # It must be reentrant and must never hold the ESS forwarding gate.
                with adapter._local_transaction:
                    results.append(adapter.transact(encode_command('QPIGS'),0x994,1))
            except Exception as error:errors.append(repr(error))
        worker=threading.Thread(target=local)
        try:
            wait_for(lambda:adapter._cloud_ready)
            time.sleep(1.1)
            worker.start();local_request=receive(logger)
            self.assertEqual(local_request[2:4],bytes.fromhex('0994'))
            request=frame(31000,native_read());started=time.monotonic();ess.sendall(request)
            self.assertEqual(receive(logger,.25),request)
            response=frame(31000,bank());logger.sendall(response)
            self.assertEqual(receive(ess,.25),response)
            elapsed=time.monotonic()-started
            self.assertLess(elapsed,.25);self.assertFalse(results)
            # The original local response remains correctly correlated after ESS.
            time.sleep(.8)
            local_reply=encode_response_text(DATA)
            logger.sendall(frame(int.from_bytes(local_request[:2],'big'),local_reply,0x994,1))
            worker.join(2);self.assertEqual(results,[local_reply]);self.assertFalse(errors)
            print(json.dumps(dict(ESS_roundtrip_ms=round(elapsed*1000,3),local_wait_did_not_block_ESS=True)))
        finally:
            adapter.stop();logger.close();ess.close();cloud.close()
            if worker.ident:worker.join(3)

    def test_metadata_multiple_replies_extend_admission_quiet_window(self):
        now=[100.];driver=DaxtromnPI30Driver(AppConfig())
        shadow=ESSShadow(targets(driver),lambda:now[0]);shadow.reset('A')
        shadow.feed('request',frame(8,b'\x01\x02\x04',function=2))
        self.assertTrue(shadow.in_flight())
        shadow.feed('response',frame(8,b'\x00\x02PN',0x102,function=2))
        now[0]+=.2;self.assertTrue(shadow.in_flight())
        shadow.feed('response',frame(8,b'\x00\x041.2',0x102,function=2))
        now[0]+=.2;self.assertTrue(shadow.in_flight())
        now[0]+=.06;self.assertFalse(shadow.in_flight())
        self.assertFalse(shadow.samples)

    def test_calibration_accepts_slow_direct_reply_but_rejects_stale_bank(self):
        now=[100.];driver=DaxtromnPI30Driver(AppConfig())
        shadow=ESSShadow(targets(driver),lambda:now[0]);shadow.reset('A')
        for tid in range(3):
            shadow.feed('request',frame(tid,native_read()));now[0]+=.8
            shadow.feed('response',frame(tid,bank()));now[0]+=1.3
            shadow.calibrate((0x994,1),driver.decode_telemetry(DATA))
        self.assertTrue(shadow.snapshot()['calibrated'])
        shadow.feed('request',frame(8,native_read()));now[0]+=.8
        shadow.feed('response',frame(8,bank()));now[0]+=3.1
        before=shadow.snapshot()['calibration_matches']
        shadow.calibrate((0x994,1),driver.decode_telemetry(DATA))
        self.assertEqual(before,shadow.snapshot()['calibration_matches'])

if __name__=='__main__':unittest.main(verbosity=2)
