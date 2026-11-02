import unittest,tempfile,threading,time
from types import SimpleNamespace as NS
from ducksolar.drivers.parameter_library import RULES,FLAG_SETTINGS,command,current_value,validate_state,flag_values,valid_request
from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
from ducksolar.protocol.pi30 import decode_packet,encode_response_text
from ducksolar.parameter_commands import ParameterCommands
from ducksolar.config import AppConfig

def raw():
 return dict(QPI='PI30',QID='12345678901234',QMN='VMII-NXPW5KW',QVFW='VERFW:00074.11',QPIRI='230.0 26.9 230.0 50.0 26.9 6200 6200 48.0 51.0 40.0 55.2 54.0 2 040 120 1 1 1 1 01 0 0 57.0 0 1 51.0 22 44.0',QFLAG='EDabjkuvxyz',QMOD='L')

class SettingsBetaTests(unittest.TestCase):
 def test_catalog_and_optional_flags(self):
  d=DaxtromnPI30Driver(AppConfig());rows=d.parameter_catalog(raw())
  self.assertEqual(20,sum(x['writable'] for x in rows));self.assertIn('UPS',next(x for x in rows if x['canonical_id']=='grid.input_range')['display_value'])
  data=raw();data.pop('QFLAG');rows=d.parameter_catalog(data)
  self.assertEqual(11,sum(x['writable'] for x in rows))
  self.assertFalse(any(x['present'] for x in rows if x['canonical_id'].startswith('settings.')))
 def test_exact_wire_bytes(self):
  for key,value,wire in [('charging.total_current_limit',120,'MCHGC0120'),('charging.utility_current_limit',40,'MUCHGC040'),('charging.utility_current_limit',120,'MNCHGC0120'),('battery.recharge_voltage',51,'PBCV51.0'),('battery.redischarge_voltage',0,'PBDV0.0'),('settings.buzzer',1,'PEa'),('settings.buzzer',0,'PDa')]:
   with self.subTest(key=key,value=value):self.assertEqual(wire,decode_packet(command(key,value)).decode());self.assertTrue(valid_request(command(key,value)))
  self.assertFalse(valid_request(b'PEa\r'))
 def test_reject_invalid_states(self):
  for key,value in [('grid.input_range',.5),('charging.total_current_limit',125),('charging.utility_current_limit',41),('charging.bulk_voltage','NaN'),('settings.buzzer',2),('grid.tie_current',22),('battery.recharge_voltage',51.1)]:
   with self.subTest(key=key,value=value),self.assertRaises(ValueError):command(key,value)
  for text in ['EaDa','EA DA','x','EDaa']:
   with self.assertRaises(ValueError):flag_values(text)
  with self.assertRaises(ValueError):validate_state('charging.total_current_limit',10,raw(),'L')
  with self.assertRaises(ValueError):validate_state('charging.utility_current_limit',120,dict(raw(),QPIRI=raw()['QPIRI'].replace('040 120','040 060')),'L')
  with self.assertRaises(ValueError):validate_state('settings.buzzer',1,dict(raw(),QMN='other'),'L')
 def transaction(self,key,value,lost_ack=False,expected=None):
  with tempfile.TemporaryDirectory() as folder:
   cfg=AppConfig(root_dir=folder);data=raw();writes=[];refresh=[];driver=DaxtromnPI30Driver(cfg)
   expected=current_value(key,data) if expected is None else expected
   channel=NS(connected=True,connection_id='fixture')
   def transact(request):
    name=decode_packet(request).decode()
    if request==command(key,value):
     writes.append(name);rule=RULES[key]
     if rule.get('flag'):
      flags=flag_values(data['QFLAG']);flags[key]=str(value)
      data['QFLAG']='E'+''.join(letter for k,(letter,_) in FLAG_SETTINGS.items() if flags[k]=='1')+'D'+''.join(letter for k,(letter,_) in FLAG_SETTINGS.items() if flags[k]=='0')
     else:
      fields=data['QPIRI'].split();fields[rule['index']-1]=str(value);data['QPIRI']=' '.join(fields)
     if lost_ack:raise TimeoutError('Lost ACK after write')
     return encode_response_text('ACK')
    return encode_response_text(data[name])
   channel.transact=transact
   def submit(job):
    try:result=job.action();error=None
    except Exception as exc:result=None;error=exc
    if job.callback:job.callback(result,error)
    return True
   dispatcher=NS(stop_event=threading.Event(),submit=submit)
   dev=NS(channel=channel,driver=driver,parameters=NS(snapshot=lambda:dict(stale=False,raw=data.copy()),request_refresh=lambda:refresh.append(True)),monitor=NS(dispatcher=dispatcher),definition=NS(logger_id='fixture'))
   runtime=NS(cfg=cfg,active=True,logs=NS(event=lambda *a,**k:None),adapters={'fixture':NS(_local_transaction=threading.RLock())},device=lambda _:dev)
   manager=ParameterCommands(runtime);manager.VERIFY_DELAYS=(.001,.001)
   result=manager.submit('inverter',key,str(value),str(expected),'tester',lambda:None)
   until=time.monotonic()+3
   while manager.status(result['operation_id'],'tester','inverter')['status'] not in manager.TERMINAL and time.monotonic()<until:time.sleep(.005)
   final=manager.status(result['operation_id'],'tester','inverter');runtime.active=False;dispatcher.stop_event.set()
   return final,writes
 def test_every_control_readback_without_repeated_write(self):
  values={'output.source_priority':2,'grid.input_range':0,'output.rated_frequency':60,'battery.type':0,'charging.bulk_voltage':55.3,'charging.float_voltage':53.9,'battery.cutoff_voltage':40.1,'charging.total_current_limit':110,'charging.utility_current_limit':30,'battery.recharge_voltage':50,'battery.redischarge_voltage':56}
  values.update({key:1 for key in FLAG_SETTINGS});self.assertEqual(set(RULES),set(values))
  for key,value in values.items():
   with self.subTest(key=key):
    result,writes=self.transaction(key,value);self.assertEqual('verified',result['status'],result);self.assertEqual(1,len(writes))
 def test_lost_ack_readback_not_retry(self):
  result,writes=self.transaction('settings.buzzer',1,True);self.assertEqual('verified',result['status']);self.assertEqual(['PEa'],writes)
 def test_changed_expected_never_written(self):
  result,writes=self.transaction('settings.buzzer',1,expected=1);self.assertEqual('rejected',result['status']);self.assertEqual([],writes)

if __name__=='__main__':unittest.main(verbosity=2)
