"""Lightweight authenticated notifications: no device snapshot construction."""
from datetime import datetime,timezone
from .config import VERSION

def snapshot(owner,account,client_id):
    runtime=owner.runtime
    with runtime._lock:
        runtime.sequence+=1;sequence=runtime.sequence
    return dict(api_version=3,state_schema=2,session_id=runtime.session_id,sequence=sequence,
        server_version=VERSION,
        server_time=datetime.now().isoformat(timespec='microseconds'),
        server_utc=datetime.now(timezone.utc).isoformat(timespec='microseconds'),
        live_mode='notifications',heartbeat_s=30,statuses={'API':True},
        notifications=runtime.push_alerts.feed(account['username'],client_id,account['grants']))
