"""Debug-only checks: all files and sockets are isolated from real equipment."""
import csv,json,socket,tempfile,threading,time
from pathlib import Path
from datetime import datetime,timedelta

def wait_for(check,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if check():return
        time.sleep(.02)
    raise AssertionError('Timed out waiting for fixture state')

def run(root):
    from ducksolar.config import AppConfig
    from ducksolar.events import EventJournal,Transitions
    from ducksolar.storage import Storage,TelemetryRecord
    from ducksolar.telemetry_writer import TelemetryWriter
    from ducksolar.history_reader import HistoryReader
    from ducksolar.server_runtime import ServerRuntime
    from ducksolar.protocol.pi30 import _encode_packet,decode_packet
    from ducksolar.adapters.eybond import EyeBondAdapter
    output={}
    with tempfile.TemporaryDirectory(prefix='ducksolar-fixture-',dir=root) as temporary:
        folder=Path(temporary)
        journal_file=folder/'large-events.jsonl'
        with journal_file.open('w',encoding='utf-8') as f:
            for i in range(12000):f.write(json.dumps({'id':str(i),'device_id':'inverter-1','message':'x'*512})+'\n')
        journal=EventJournal(journal_file)
        assert len(journal.rows)==2000 and journal.rows[0]['id']=='10000'
        journal.add('fixture','test','inverter-1')
        assert len(EventJournal(journal_file).rows)==2000
        output['event_history_bounded']=True
        cfg=AppConfig(root_dir=str(folder),cloud_proxy_enabled=False,lwip_ip='127.0.0.1',
                      telemetry_queue_size=32,poll_interval_s=.5,socket_timeout_s=1,cloud_port=18899)
        store=Storage(cfg);writer=TelemetryWriter(cfg,store)
        base=datetime(2026,9,1,12)
        from unittest.mock import patch
        # Force available-memory pressure, rather than the obsolete config ceiling.
        with patch('ducksolar.resource_manager.budget',return_value=32*1024):
            for i in range(70):assert writer.submit(TelemetryRecord(base+timedelta(seconds=i),'Local',{'pv_w':100+i},'inverter-1'))
        assert writer.queue.qsize()==32 and writer.spool_path.exists()
        writer.start();wait_for(lambda: writer.queue.unfinished_tasks==0 and not writer.spool_path.exists())
        writer.stop()
        csv_path=store.paths['inverter_logs']/'2026-09-01.csv'
        with csv_path.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        assert len(rows)==70
        store.append_telemetry(TelemetryRecord(base,'Local',{'pv_w':100},'inverter-1'))
        # Restart and a replay of a previously committed record must not duplicate CSV.
        Storage(cfg).append_telemetry(TelemetryRecord(base,'Local',{'pv_w':100},'inverter-1'))
        with csv_path.open(encoding='utf-8-sig') as f:assert len(list(csv.DictReader(f)))==70
        assert len(HistoryReader(cfg).load_day(base.date(),'Local'))==70
        output['overflow_spooled_and_replayed']=70
        output['committed_replay_idempotent']=True
        for micros in (100000,600000):
            store.append_telemetry(TelemetryRecord(base+timedelta(microseconds=micros),'Local',{'pv_w':150},'inverter-1'))
        with csv_path.open(encoding='utf-8-sig') as f:assert len(list(csv.DictReader(f)))==72
        output['subsecond_records_preserved']=True
        # Real adapter, dispatcher, driver, writer and runtime over loopback TCP.
        # No UDP redirects are permitted in this fixture or Android defaults.
        probe=socket.socket();probe.bind(('127.0.0.1',0));cfg.local_server_port=probe.getsockname()[1];probe.close()
        cfg.api_port=0
        runtime=ServerRuntime(cfg);adapter=runtime.gateway
        for device in runtime.devices.values():
            for i in range(10000):device.store.add_live_point({'timestamp':str(i),'pv_w':1000})
            assert len(device.store.live_points)==0
            for i in range(1000):device.store.add_event({'message':str(i)})
            assert len(device.store.events)==256
            device.store.events.clear()
        output['android_runtime_history_not_duplicated_in_ram']=True
        adapter.send_redirect=lambda: (_ for _ in ()).throw(AssertionError('Unexpected redirect'))
        stop=threading.Event();threads=[];sockets=[]
        values={
         'QPIGS':'230.0 50.0 230.0 50.0 0500 0400 008 400 52.0 000 080 0030 05.0 300.0 52.0 000 00000000 00 00 1500 000',
         'QMOD':'L','QPIWS':'00000100000000000000000000000000','QPI':'PI30',
         'QID':'12345678901234','QMN':'VMII-NXPW5KW','QVFW':'VERFW:00074.11',
         'QVFW2':'VERFW2:00000.00',
         'QPIRI':'230.0 26.9 230.0 50.0 26.9 6200 6200 48.0 46.0 40.0 55.2 54.0 2 070 120 1 1 2 1 01 0 0 57.0 0 1 46.0 22 44.0'}
        def peer():
            conn=socket.create_connection(('127.0.0.1',cfg.local_server_port),timeout=2);sockets.append(conn);conn.settimeout(.2)
            def answer():
                buf=bytearray()
                try:
                    while not stop.is_set():
                        try:part=conn.recv(8192)
                        except socket.timeout:continue
                        if not part:break
                        buf.extend(part)
                        while len(buf)>=6:
                            size=6+int.from_bytes(buf[4:6],'big')
                            if len(buf)<size:break
                            frame=bytes(buf[:size]);del buf[:size]
                            command=decode_packet(frame[8:]).decode()
                            assert command in values,command # any unexpected write fails
                            reply=EyeBondAdapter.build_frame(int.from_bytes(frame[:2],'big'),0x0994,1,4,_encode_packet('('+values[command]))
                            conn.sendall(reply[:3]);conn.sendall(reply[3:])
                except OSError:pass
            thread=threading.Thread(target=answer,daemon=True);threads.append(thread);thread.start()
            return conn
        try:
            adapter.start();runtime.writer.start();runtime.monitor.start();runtime.parameters.start()
            first=peer()
            wait_for(lambda:runtime.device_snapshot(runtime.device()).get('statuses',{}).get('Inverter'))
            wait_for(lambda:runtime.parameters.snapshot()['status_code']=='parameter.current')
            wait_for(lambda:len(runtime.monitor.snapshot().get('warnings',''))==32)
            state=runtime.device_snapshot(runtime.device());assert not state['stale'] and state['data']['pv_w']==1500
            assert any(x['canonical_id']=='battery.bms_protocol_index' for x in state['parameters']['rows'])
            runtime.transitions.observe('inverter-1',state)
            first_id=adapter.connection_id;first.shutdown(socket.SHUT_RDWR);first.close()
            wait_for(lambda:not adapter.connected)
            stale=runtime.device_snapshot(runtime.device());assert stale['stale'] and stale['data']['pv_w']==1500
            runtime.transitions.observe('inverter-1',stale)
            peer();wait_for(lambda:adapter.connection_id!=first_id and not runtime.device_snapshot(runtime.device())['stale'])
            wait_for(lambda:runtime.parameters.snapshot()['status_code']=='parameter.current' and not runtime.parameters.snapshot()['stale'])
            output['fragmented_frames_telemetry_history_reconnect']=True
            output['stale_retains_last_measurement']=True
            output['parameter_identity_refresh']=True
            output['warning_decoding']=state['warnings_display']
        finally:
            stop.set()
            for conn in sockets:
                try:conn.close()
                except OSError:pass
            runtime.stop()
            for thread in threads:thread.join(timeout=1)
        assert not any(t.is_alive() for t in threads)
        output['clean_stop']=True
    return json.dumps(output,ensure_ascii=False)

if __name__=='__main__':
    import os
    with tempfile.TemporaryDirectory() as root:
        os.environ['DUCK_SOLAR_ROOT']=root
        print(run(root))
