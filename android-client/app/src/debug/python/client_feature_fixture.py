"""Explicit instrumentation-only fixtures; never invoked by normal client UI."""
import json,time,threading
import android_client as c
_saved=None
class SlowAPI:
 url='https://127.0.0.1:28766'
 def __init__(self,delay):self.delay=delay;self.calls=0;self.cancelled=threading.Event()
 def ensure_session(self):return {'capabilities':['energy.month.compact.v1']}
 def call(self,domain,method,*args,**kwargs):
  if method=='cancel':self.cancelled.set();return True
  if method=='month_compact':
   self.calls+=1
   if self.cancelled.wait(self.delay):raise ValueError('Fixture query cancelled')
   return {'schema':'energy.month.compact.v1','start':args[0].isoformat()+'T00:00:00+03:00','end':'2026-11-01T00:00:00+03:00','days':[],
    'pv':{'kwh':None},'inverter_import':{'kwh':None},'inverter_export':{'kwh':None},'diagnostics':{'total_s':self.delay,'selected_files':0,'read_records':0,'opened_files':0}}
  raise AssertionError('Unexpected fixture operation')
def install(delay=4):
 global _saved
 if _saved is None:
  c.stop();_saved=(c._api,c.resume,c.snapshot,c._balance_job,c._balance_api)
 c._api=SlowAPI(delay);c._balance_job={};c._balance_api=None
 c.resume=lambda *a,**k:json.dumps({'connected':True})
 c.snapshot=lambda:json.dumps({'connected':True,'connection_state':'CONNECTED','route':'local','state':{'stale':True,'device_id':'inverter-1','parameters':{'stale':True,'rows':[]}}})
 from async_fixture import wrap
 wrap(c._api)
 return True
def calls():return c._api.calls
def restore():
 global _saved
 if _saved:
  c._api.cancelled.set();c._api,c.resume,c.snapshot,c._balance_job,c._balance_api=_saved;_saved=None
 return True
