import sys,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'main/python'),str(Path(__file__).resolve().parents[5])]
from ducksolar import weather_client as w

class Recovery(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.identity='fixture'
  self.saved=(w._job,w._active,w._pause,w._store,w._journal)
  w._job={'state':'idle'};w._active=False;w._cancel.clear();w._pause=False
  self.logs=[];w.configure(lambda code,**details:self.logs.append((code,details)))
  w.settings(self.root,self.identity,dict(location='Test',latitude=45,longitude=28,installed_kw=6,tilt_deg=30,azimuth_deg=180))
 def tearDown(self):
  w._cancel.set()
  end=time.monotonic()+3
  while w._active and time.monotonic()<end:time.sleep(.01)
  w._job,w._active,w._pause,w._store,w._journal=self.saved;w._cancel.clear();self.temp.cleanup()
 def wait(self,test):
  end=time.monotonic()+3
  while not test() and time.monotonic()<end:time.sleep(.01)
  self.assertTrue(test())
 def test_every_batch_is_saved_before_next_request(self):
  calls=[];path=self.root/'summaries.json'
  def sync(known):
   calls.append(known)
   if len(calls)==1:return dict(manifest={'a':'1','b':'2'},changed=[dict(day='a',revision='1',summary={})])
   self.assertEqual(json.loads(path.read_text())['a']['revision'],'1')
   raise ConnectionError('disconnected')
  with self.assertRaises(ConnectionError):w.History(sync,path).generation_summaries()
  def resumed(known):
   self.assertEqual(known,{'a':'1'})
   return dict(manifest={'a':'1','b':'2'},changed=[dict(day='b',revision='2',summary={})])
  self.assertEqual(2,len(w.History(resumed,path).generation_summaries()))
 def test_pause_cancel_checkpoint_and_resume(self):
  blocked=threading.Event();calls=[]
  def sync(known):
   calls.append(known)
   if not known:return dict(manifest={'a':'1','b':'2'},changed=[dict(day='a',revision='1',summary={})])
   blocked.set()
   while True:w.check();time.sleep(.01)
  def fetch(obj,location_name=None,reader=None):return reader.generation_summaries()
  with patch.object(w.Forecast,'fetch_10_day',fetch):
   w.start(self.root,self.identity,sync);self.assertTrue(blocked.wait(2))
   w.cancel(self.root,self.identity,pause=True)
   self.wait(lambda:not w._active)
   self.assertEqual('paused',w.status(self.root,self.identity)['state'])
   def resumed(known):
    self.assertEqual(known,{'a':'1'})
    return dict(manifest={'a':'1','b':'2'},changed=[dict(day='b',revision='2',summary={})])
   w.start(self.root,self.identity,resumed);self.wait(lambda:not w._active)
   self.assertEqual('complete',w.status(self.root,self.identity)['state'])
  self.assertTrue(any(code=='weather.paused' for code,_ in self.logs))
  self.assertTrue(any(code=='weather.complete' for code,_ in self.logs))
 def test_process_restart_exposes_resume_not_false_running(self):
  w.write_json(w.folder(self.root,self.identity)/'job.json',dict(state='running',identity=self.identity,training=True))
  state=w.status(self.root,self.identity)
  self.assertEqual('paused',state['state']);self.assertTrue(state['training'])
  w.cancel(self.root,self.identity)
  self.assertEqual('cancelled',w.status(self.root,self.identity)['state'])
 def test_one_owner_and_cancellation_without_history_loss(self):
  blocked=threading.Event()
  def fetch(obj,location_name=None,reader=None):
   blocked.set()
   while True:w.check();time.sleep(.01)
  with patch.object(w.Forecast,'fetch_10_day',fetch):
   w.start(self.root,self.identity);self.assertTrue(blocked.wait(2))
   with self.assertRaises(ValueError):w.start(self.root,self.identity)
   w.cancel(self.root,self.identity);self.wait(lambda:not w._active)
  self.assertEqual('cancelled',w.status(self.root,self.identity)['state'])
  self.assertTrue(w.settings(self.root,self.identity))
 def test_android_bridge_retries_only_abandoned_saved_job(self):
  import android_client as c
  saved=(c._root,c._api,c._cfg,c._live)
  class API:
   starts=0
   def call(inner,domain,method,*args,**kwargs):
    if method=='job_start':inner.starts+=1;return {'job_id':str(inner.starts)}
    if method=='job_status':return {'state':'cancelled','error_code':'history.abandoned'} if inner.starts==1 else {'state':'completed'}
    if method=='job_result':return {'result':{'manifest':{},'changed':[]}}
    raise AssertionError(method)
  api=API();c._root=self.root;c._api=api;c._live=None;c._cfg={'pin':'test','username':'fixture','serial':'fixture'}
  identity=c.weather_identity();w.settings(self.root,identity,w.settings(self.root,self.identity))
  try:
   with patch.object(w.Forecast,'fetch_10_day',lambda obj,location_name=None,reader=None:reader.generation_summaries()):
    c.weather_start(True);self.wait(lambda:not w._active)
   self.assertEqual('complete',w.status(self.root,identity)['state']);self.assertEqual(2,api.starts)
   self.assertFalse((self.root/'history-weather-pending.json').exists())
  finally:c._root,c._api,c._cfg,c._live=saved
 def test_android_bridge_pause_cancels_server_job(self):
  import android_client as c
  saved=(c._root,c._api,c._cfg,c._live);polled=threading.Event()
  class API:
   cancelled=False
   def call(inner,domain,method,*args,**kwargs):
    if method=='job_start':return {'job_id':'active'}
    if method=='job_status':polled.set();return {'state':'running','done':1,'total':40}
    if method=='job_cancel':inner.cancelled=True;return {}
    raise AssertionError(method)
  api=API();c._root=self.root;c._api=api;c._live=None;c._cfg={'pin':'test','username':'fixture','serial':'fixture'}
  identity=c.weather_identity();w.settings(self.root,identity,w.settings(self.root,self.identity))
  try:
   with patch.object(w.Forecast,'fetch_10_day',lambda obj,location_name=None,reader=None:reader.generation_summaries()):
    c.weather_start(True);self.assertTrue(polled.wait(2));c.weather_cancel(True);self.wait(lambda:not w._active)
   self.assertTrue(api.cancelled);self.assertEqual('paused',w.status(self.root,identity)['state'])
  finally:c._root,c._api,c._cfg,c._live=saved

if __name__=='__main__':unittest.main(verbosity=2)
