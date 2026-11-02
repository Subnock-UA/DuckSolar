"""Instrumentation-only temporary connection; always restores original bytes."""
import json
import android_client as client
_saved=None

def install(root,url,pin,token):
 global _saved
 from pathlib import Path
 client.stop();path=Path(root)/'connection.json'
 _saved=(path,path.read_bytes() if path.exists() else None)
 value=dict(client_id='c'*32,lan=url,remote=url,username='pushtest',serial='push-test-pn',pin=pin,token=token,
            notifications=dict(grid_lost=True,grid_restored=True,server_battery=True,inverter_battery=True,server_battery_threshold=55))
 from ducksolar.notification_settings import GROUPS
 value['notifications'].update(dict.fromkeys(GROUPS,True))
 path.write_text(json.dumps(value),encoding='utf-8');client.initialize(root)
 return True

def restore():
 global _saved
 client.stop()
 if _saved:
  path,content=_saved
  if content is None:path.unlink(missing_ok=True)
  else:path.write_bytes(content)
  client.initialize(str(path.parent));_saved=None
 return True


def check_routes(local_url,remote_url):
 import time
 from unittest.mock import patch
 with client._lock:
  client._cfg['lan']=local_url;client._cfg['remote']=remote_url
  client.switch_route('remote')
  assert json.loads(client.snapshot())['route']=='remote'
  client.network_state(True,True,'route-test')
  client._manual_until=0;client._lan_check_at=0
  assert client._prefer_lan()
  assert json.loads(client.snapshot())['route']=='local'
  client.switch_route('remote')
  assert json.loads(client.snapshot())['route']=='remote'
  client._cfg['lan']='https://10.0.2.2:1';client._manual_until=0;client._lan_check_at=0
  assert not client._prefer_lan()
  assert json.loads(client.snapshot())['connected']
  assert json.loads(client.snapshot())['route']=='remote'
  client._cfg['lan']=local_url
 return True
