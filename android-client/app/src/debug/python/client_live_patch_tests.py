import sys,io,json,threading,unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[5]),str(Path(__file__).resolve().parents[5])]
import android_client as client
from ducksolar.client_transport import TransportError
from ducksolar.live_delta import Encoder
from ducksolar.remote import LiveConnection

class Response(io.BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class ClientPatch(unittest.TestCase):
    def transport(self,raw):
        transport=client.AndroidTransport('https://127.0.0.1:28766','a'*64)
        transport.open=Mock(side_effect=lambda *a,**k:Response(raw))
        return transport
    def test_actual_android_path_decodes_large_utf8_and_delta(self):
        encoder=Encoder();state=dict(session_id='s',sequence=1,api_version=3,text='Україна'*20000,notifications=[])
        full=encoder.packet(dict(state));state['sequence']=2;state['notifications']=[{'id':'b'*32}]
        delta=encoder.packet(dict(state))
        raw=b''.join(b'data: '+json.dumps(obj,ensure_ascii=False).encode()+b'\n\n' for obj in [full,delta])
        transport=self.transport(raw);transport.configure_live({'capabilities':['live.delta.v1']})
        stop=threading.Event();result=[]
        for obj in transport.events({},stop,lambda response:None):
            result.append(obj)
            if len(result)==2:stop.set()
        self.assertEqual(len(result[0]['text']),140000);self.assertEqual(result[-1],state)
        self.assertEqual(transport.open.call_args.args[0],'events?format=delta1')
    def test_truncated_json_line_never_reaches_parser(self):
        transport=self.transport(b'data: {"text":"cut')
        with self.assertRaises(TransportError) as error:list(transport.events({},threading.Event(),lambda response:None))
        self.assertEqual(error.exception.code,'live.incomplete')
    def test_missing_event_terminator_is_not_yielded(self):
        transport=self.transport(b'data: {"ok":true}\n')
        with self.assertRaises(TransportError) as error:list(transport.events({},threading.Event(),lambda response:None))
        self.assertEqual(error.exception.code,'live.incomplete')
    def test_event_total_limit_applies_to_multiple_lines(self):
        transport=self.transport(b'data: "'+b'a'*60+b'"\ndata: "'+b'b'*60+b'"\n\n');transport.LIMIT=100
        with self.assertRaises(TransportError) as error:list(transport.events({},threading.Event(),lambda response:None))
        self.assertEqual(error.exception.code,'live.too_large')
    def test_invalid_delta_reconnects_without_partial_state(self):
        transport=self.transport(b'data: {"live":"delta1","type":"patch","base":0}\n\n')
        with self.assertRaises(TransportError) as error:list(transport.events({},threading.Event(),lambda response:None))
        self.assertEqual(error.exception.code,'live.invalid')
    def test_legacy_server_negotiation_and_comments(self):
        transport=self.transport(b': heartbeat\n\ndata: {"ok":true}\n\n')
        transport.configure_live({'capabilities':['api.v3']});stop=threading.Event()
        result=next(transport.events({},stop,lambda response:None))
        self.assertEqual(result,{'ok':True});self.assertEqual(transport.open.call_args.args[0],'events')
    def test_error_metadata_and_deduplicated_retries_are_saved(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(client,'_root',Path(temp)):
            client._repeats.clear();logs=client.ClientLogs()
            for _ in range(20):logs.event('same',code='client.disconnected',error_code='live.invalid',payload_bytes=123,json_position=10,failure_count=5,secret='never-log')
            rows=[json.loads(l) for l in (Path(temp)/'client-events.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertLess(len(rows),10);self.assertEqual(rows[0]['payload_bytes'],123);self.assertNotIn('secret',rows[0])
    def test_no_network_avoids_connect_and_preserves_profile(self):
        with patch.object(client,'_network_available',False),patch.object(client,'_cfg',{'token':'saved','pin':'a'*64}),patch.object(client,'_probe') as probe:
            self.assertTrue(json.loads(client.resume(True))['waiting_network']);probe.assert_not_called()
    def test_transport_failure_keeps_valid_session(self):
        transport=Mock();transport.network_available=lambda:True
        api=SimpleNamespace(transport=transport,ready=lambda:True,generation=0,session={'saved':True},session_lock=threading.RLock(),block_auth=Mock(),headers=lambda:{},ensure_session=lambda:{})
        live=LiveConnection(api,Mock())
        def broken(*args):live.stop_event.set();raise TransportError('temporary',0,'connection.timeout')
        transport.events=broken;live._run();self.assertEqual(api.session,{'saved':True})

if __name__=='__main__':unittest.main()
