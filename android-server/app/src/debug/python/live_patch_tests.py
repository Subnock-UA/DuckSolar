import sys,copy,json,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[5]),str(Path(__file__).resolve().parents[5])]
from ducksolar.live_delta import Encoder,Decoder
from ducksolar.adapters.native_route import NativeRoute,DataChannelRecovered

class LivePatch(unittest.TestCase):
    def test_lossless_null_delete_lists_nested_and_session_reset(self):
        encoder=Encoder();decoder=Decoder()
        state=dict(session_id='s',sequence=1,api_version=3,device={'a':1,'b':None,'c':[1,2]},notifications=[])
        self.assertEqual(decoder.accept(encoder.packet(copy.deepcopy(state))),state)
        for i in range(2,30):
            state['sequence']=i;state['device']['a']=None if i%2 else i
            state['device']['c']=[i];state['notifications']=[{'id':str(i)}] if i%2 else []
            if i%3:state['device']['new']={'value':i}
            else:state['device'].pop('new',None)
            result=decoder.accept(json.loads(json.dumps(encoder.packet(copy.deepcopy(state)))))
            self.assertEqual(result,state)
            result['device']['c'].append('consumer changed')
        state['session_id']='new';state['sequence']=1
        packet=encoder.packet(state);self.assertEqual(packet['type'],'full');self.assertEqual(decoder.accept(packet),state)

    def test_missing_or_wrong_baseline_forces_resync(self):
        decoder=Decoder()
        with self.assertRaises(ValueError):decoder.accept(dict(live='delta1',type='patch',base=0,session_id='s'))
        decoder.accept(dict(live='delta1',type='full',state=dict(session_id='s',sequence=1)))
        with self.assertRaises(ValueError):decoder.accept(dict(live='delta1',type='patch',base=2,session_id='s'))

    def test_repeated_catalog_does_not_cross_wire_again(self):
        encoder=Encoder()
        state=dict(api_version=3,session_id='s',sequence=1,parameters=[dict(name=str(i),raw='Україна'*100) for i in range(100)],notifications=[],data={'watts':123})
        full=json.dumps(encoder.packet(copy.deepcopy(state)),ensure_ascii=False).encode()
        state['sequence']=2;state['data']['watts']=124
        delta=json.dumps(encoder.packet(state),ensure_ascii=False).encode()
        self.assertLess(len(delta),len(full)/100)

    def test_legacy_state_still_accepted(self):
        state=dict(api_version=3,session_id='old',sequence=1)
        self.assertEqual(Decoder().accept(state),state)

    def test_directed_broadcast_respects_actual_prefix(self):
        with patch('ducksolar.network_info.wifi_snapshot',return_value={'wifi':[{'addresses':['192.0.2.23/23']}]}):
            self.assertEqual(NativeRoute._broadcast_address('192.0.2.23'),'192.0.2.255')

    def test_recovered_data_cancels_session_without_management_writes(self):
        route=NativeRoute.__new__(NativeRoute)
        route.adapter=SimpleNamespace(connected=False,detect_lan_ip=lambda:'192.0.2.10')
        route.cfg=SimpleNamespace(logger_management_port=8899)
        route.stop_event=threading.Event();route.listener=Mock()
        route._redirect=Mock(side_effect=lambda *a:setattr(route.adapter,'connected',True))
        with self.assertRaises(DataChannelRecovered):route._session()
        route.listener.accept.assert_not_called()
        route._redirect.reset_mock()
        with self.assertRaises(DataChannelRecovered):route._session()
        route._redirect.assert_not_called()

    def test_reconnected_during_metadata_does_not_apply_or_restore(self):
        route=NativeRoute.__new__(NativeRoute)
        route.adapter=SimpleNamespace(connected=False)
        peer=Mock();route._session=Mock(return_value=(peer,'192.0.2.10'))
        route.record={'active':True,'original_endpoint':'saved.example','original_port':502}
        route.cfg=SimpleNamespace(native_logger_port=18899)
        def query(peer,parameter):
            if parameter==5:route.adapter.connected=True;return '3.6.7.6'
            return 'saved.example' if parameter==21 else '502'
        route.query=query;route._write=Mock();route._save=Mock();route._restore_peer=Mock()
        with self.assertRaises(DataChannelRecovered):route._provision()
        route._write.assert_not_called();route._save.assert_not_called();route._restore_peer.assert_not_called();peer.close.assert_called_once()

if __name__=='__main__':unittest.main()
