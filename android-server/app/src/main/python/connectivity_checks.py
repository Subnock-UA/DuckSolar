"""Offline checks: no physical logger or cloud connections."""
import json,threading
from types import SimpleNamespace
from unittest.mock import patch
from ducksolar.network_info import logger_route,wifi_snapshot
from ducksolar.adapters.native_route import NativeRoute
from ducksolar.adapters.eybond import EyeBondAdapter

def run():
    assert isinstance(wifi_snapshot()['wifi'],list)
    with patch('ducksolar.network_info.wifi_snapshot',return_value={'wifi':[{'id':'wifi','addresses':['192.0.2.10/24']}]}):
        assert logger_route('192.0.2.20')['source']=='192.0.2.10'
    route=NativeRoute.__new__(NativeRoute)
    route.lock=threading.RLock();route.record_lock=threading.RLock()
    route.record={'original_endpoint':'saved.example','original_port':502}
    route.cfg=SimpleNamespace(lwip_ip='192.0.2.20',logger_mac='',native_logger_port=18899,logger_management_port=8899)
    route.state='RETRYING';route.last_error=''
    route.lock.acquire();values=[]
    worker=threading.Thread(target=lambda:values.append(route.snapshot()));worker.start();worker.join(.5)
    try:assert not worker.is_alive() and values[0]['original_endpoint']=='saved.example'
    finally:route.lock.release();worker.join()
    adapter=EyeBondAdapter.__new__(EyeBondAdapter);adapter.cfg=SimpleNamespace(equipment_mode='relay_only')
    try:adapter.transact(b'QPIGS',1,1)
    except RuntimeError:pass
    else:raise AssertionError('Relay mode injected a local command')
    return json.dumps(dict(passed=True,tests=4))
