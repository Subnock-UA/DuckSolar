"""Diagnostic export uses explicit allowlists, never configuration or raw logs."""
from datetime import datetime, timezone
import re

COMMANDS={'QPI','QMN','QVFW','QVFW2','QPIRI','QPIGS','QMOD','QPIWS'}

def build_bundle(states, server_version, client_version=None, events=()):
    devices=[]
    for state in states:
        desc=state.get('descriptor',{})
        raw=state.get('parameters',{}).get('raw',{})
        safe_raw={key:str(value)[:4096] for key,value in raw.items() if key in COMMANDS}
        warning_raw=str(state.get('warnings',''))
        if re.fullmatch(r'[01]{32}',warning_raw):safe_raw['QPIWS']=warning_raw
        events_decoded=state.get('warning_events',[])
        devices.append({'profile':desc.get('profile_id'),'manufacturer':desc.get('manufacturer'),
            'model':desc.get('model'),'protocol':desc.get('protocol'),
            'firmware':desc.get('firmware',{}).get('firmware'),
            'connection':state.get('connection'),'stale':state.get('stale'),
            'statuses':{k:bool(v) for k,v in state.get('statuses',{}).items() if k in ('LWIP','Inverter','Cloud','API')},
            'raw_responses':safe_raw,
            'active_positions':[x.get('position') for x in events_decoded if isinstance(x.get('position'),int)],
            'readable_parameters':desc.get('readable_parameters',[]),
            'writable_parameters':desc.get('writable_parameters',[])})
    safe_events=[]
    for item in list(events)[-100:]:
        code=str(item.get('code',''))
        if not re.fullmatch(r'(warnings|grid|connection)(\.[A-Za-z0-9_.]+)?',code):continue
        safe_events.append({k:item.get(k) for k in ('time','code','transition','position') if k in item})
    return {'format':'ducksolar.diagnostics.v1','created_utc':datetime.now(timezone.utc).isoformat(),
        'server_version':server_version,'client_version':client_version,
        'scope':'Daxtromn + EyBond','devices':devices,'recent_events':safe_events,
        'excluded':['passwords','tokens','accounts','private_keys','serial_numbers','addresses','configuration','unfiltered_logs']}
