"""Durable client-owned server outage events; no server round trip is needed."""
from uuid import uuid4
from .notification_settings import validate

def update(cfg,connected,now):
    settings=validate(cfg.get('notifications',{}))
    rows=[e for e in cfg.get('local_alert_events',[]) if 0<=now-e['created']<86400]
    if not settings['server_connection']:
        cfg.pop('server_outage',None);cfg['local_alert_events']=[];return []
    state=cfg.setdefault('server_outage',dict(since=now,announced=False))
    if connected:
        if state.get('announced'):rows.append(dict(id=uuid4().hex,kind='server_restored',message='З’єднання із сервером відновлено',device_id='',created=now))
        cfg['server_outage']=dict(since=now,announced=False,was_connected=True)
    else:
        # A backwards wall-clock adjustment cannot manufacture a long outage.
        if now<state.get('since',now):state['since']=now
        if now-state.get('since',now)>=settings['connection_delay_s'] and not state.get('announced'):
            state['announced']=True;rows.append(dict(id=uuid4().hex,kind='server_lost',message='Сервер недоступний',device_id='',created=now))
    cfg['local_alert_events']=rows[-128:]
    return list(cfg['local_alert_events'])
