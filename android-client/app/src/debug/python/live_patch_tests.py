import io,json,sys,threading,unittest
from ducksolar.live_events import messages
from ducksolar.client_transport import TransportError
class LiveEvents(unittest.TestCase):
 def test_large_complete_event_and_multiline(self):
  obj={'text':'x'*70000,'zero':0};stop=threading.Event();stream=messages(io.BytesIO(b'id: 1\nevent: telemetry\ndata: '+json.dumps(obj).encode()+b'\n\n'),stop)
  self.assertEqual(next(stream),obj);stop.set();self.assertEqual(list(stream),[])
  stream=messages(io.BytesIO(b'data: {\n'+b'data: "valid": true}\n\n'),threading.Event());self.assertEqual(next(stream),{'valid':True})
 def test_partial_event_does_not_reach_json(self):
  for raw in (b'data: {"secret":',b'data: {"valid":1}\n'):
   with self.assertRaises(TransportError) as error:list(messages(io.BytesIO(raw),threading.Event()))
   self.assertEqual(error.exception.code,'live.incomplete');self.assertNotIn('secret',str(error.exception))
 def test_complete_invalid_event_is_distinct_without_payload(self):
  with self.assertRaises(TransportError) as error:list(messages(io.BytesIO(b'data: {"secret": invalid}\n\n'),threading.Event()))
  self.assertEqual(error.exception.code,'live.invalid');self.assertGreater(error.exception.payload_bytes,0);self.assertNotIn('secret',str(error.exception))
 def test_valid_event_followed_by_partial_reconnect(self):
  stream=messages(io.BytesIO(b'data: {"sequence":1}\n\ndata: {"seq'),threading.Event());self.assertEqual(next(stream),{'sequence':1})
  with self.assertRaises(TransportError) as error:next(stream)
  self.assertEqual(error.exception.code,'live.incomplete')
  self.assertEqual(next(messages(io.BytesIO(b'data: {"sequence":2}\n\n'),threading.Event())),{'sequence':2})
if __name__=='__main__':unittest.main()
