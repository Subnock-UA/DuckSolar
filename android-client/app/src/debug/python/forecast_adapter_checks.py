"""Offline test fixture around the real ClientBridge Python adapter, never a live API."""
import copy,json
from unittest.mock import patch
import android_client as client

class InlineThread:
 def __init__(self,target,**kwargs):self.target=target
 def start(self):self.target()

_patches=[];_saved={}
def prepare(source):
 restore()
 value=json.loads(source);value['forecast_analysis_version']=4
 for name in ('_api','_feature_active','_feature_state'):_saved[name]=getattr(client,name)
 client._api=object();client._feature_active=False
 for p in [patch.object(client,'connection_profile',return_value='isolated-fixture'),patch.object(client,'_history_job',return_value=copy.deepcopy(value)),patch.object(client,'weather_status',side_effect=AssertionError('Modern graph must not use legacy weather conversion')),patch.object(client.threading,'Thread',InlineThread),patch.object(client,'_note')]:
  p.start();_patches.append(p)
 return json.dumps(value,ensure_ascii=False)

def restore():
 while _patches:_patches.pop().stop()
 for name,value in _saved.items():setattr(client,name,value)
 _saved.clear()
