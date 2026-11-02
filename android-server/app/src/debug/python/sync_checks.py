import json
from datetime import date,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.energy_streaming import MonthAccounting
def verify(root):
 cfg=AppConfig(root_dir=root);reader=HistoryReader(cfg);day=date(2026,9,1)
 local=reader.load_day(day,'Local');smart=reader.load_day(day,'SmartESS');auto=reader.load_day(day,'Auto')
 assert len(local)==2 and len(smart)==2 and len(auto)==2
 assert local[0]['pv_w']==1000 and smart[0]['pv_w']==2000 and auto[0]['pv_w']==1000
 class Storage:
  def list_meter_readings(self,**kw):return []
 report=MonthAccounting().report(reader,Storage(),cfg,day,now=datetime(2026,10,1,tzinfo=ZoneInfo('Europe/Kyiv')),source='SmartESS')
 assert abs(report['pv']['kwh']-2000*300/3600000)<1e-8
 assert report['history_source']=='SmartESS' and report['diagnostics']['archive_discovery']['synchronized_files']==2
 return json.dumps({'local':len(local),'ess':len(smart),'auto':len(auto),'ess_pv_kwh':report['pv']['kwh'],'dedup':True})

def ess_download_fixture(root):
 import tempfile,time
 from ducksolar.services import smartess as service
 original=service.DessMonitorAPI
 class FakeAPI:
  def __init__(self,*a):pass
  def devices(self,pn):return [{'sn':'ESS-FIXTURE','devcode':'0994','devaddr':'1'}]
  def day_page(self,pn,code,addr,sn,day,page):
   if day=='2026-09-02':raise service.NoRecord('fixture no data')
   return {'dat':{'title':['Timestamp','PV total Power'],'row':[[day+' 00:00:00','1000'],[day+' 00:05:00','1000']],'total':2}}
 try:
  service.DessMonitorAPI=FakeAPI
  with tempfile.TemporaryDirectory(dir=root) as folder:
   cfg=AppConfig(root_dir=folder);archive=service.SmartESSArchiveService(cfg)
   creds={'username':'fixture','password':'not-a-real-password','pn':'ESS-FIXTURE'}
   archive.start_download(creds,date(2026,9,1),date(2026,9,2))
   end=time.monotonic()+10
   while archive.status().running and time.monotonic()<end:time.sleep(.05)
   state=archive.status();assert not state.running and state.downloaded_days==1 and state.no_data_days==1 and state.failed_days==0
   assert creds['password']=='not-a-real-password' # only worker's credential copy is cleared
   rows=HistoryReader(cfg).load_day(date(2026,9,1),'SmartESS');assert len(rows)==2 and rows[0]['pv_w']==1000
   sparse=HistoryReader(cfg)._canonical({'time':'2026-09-01 00:00:00','PV total Power':''},'SmartESS',date(2026,9,1))
   assert sparse['pv_w'] is None
   return json.dumps({'downloaded':1,'no_data':1,'missing_not_zero':True,'no_real_cloud_requests':True})
 finally:service.DessMonitorAPI=original

def bridge_history_validation():
 import android_bridge as bridge
 try:bridge.ess_history_start('fixture','unused','WRONG-PN','2026-09-01','2026-09-02')
 except ValueError:pass
 else:raise AssertionError('Wrong PN accepted')
 try:bridge.ess_history_start('fixture','unused','SYNC-FIXTURE','2026-01-01','2026-09-02')
 except ValueError:pass
 else:raise AssertionError('Unbounded day range accepted')
 return True

def recovery_fixture():
 import android_bridge as bridge
 cfg=__import__('ducksolar.config',fromlist=['load_config']).load_config()
 path=bridge._root/'Server/NativeRoutes/logger-1.json';before=path.read_bytes() if path.exists() else None
 row={'pn':cfg.dtu_pn,'original_endpoint':'vip1.eybond.com','original_port':502,'source_id':'b'*32,'recorded_at':'2026-10-11T09:45:06+00:00'}
 try:
  if path.exists():path.unlink() # isolated emulator fixture only; restore in finally
  result=json.loads(bridge.recover_ess_route(json.dumps(row)))
  assert result['hardware_changed'] is False and path.exists()
  for bad in (dict(row,pn='WRONG-PN'),dict(row,original_endpoint='192.0.2.10')):
   try:bridge.recover_ess_route(json.dumps(bad))
   except ValueError:pass
   else:raise AssertionError('Unsafe recovery accepted')
  return json.dumps({'matching_pn':True,'private_endpoint_rejected':True,'hardware_changed':False})
 finally:
  if before is not None:path.write_bytes(before)
  else:path.unlink(missing_ok=True)
