"""Durable per-client alert subscriptions, transitions and bounded delivery queue."""
import copy,json,math,os,re,threading,time
from pathlib import Path
from uuid import uuid4

from .notification_settings import DEFAULTS, KIND_GROUP, validate
MESSAGES=dict(grid_lost='Відсутня напруга в мережі',grid_restored='Напруга в мережі відновлена',inverter_battery='Заряд АКБ не більше 30%',inverter_lost='Втрачено зв’язок з інвертором',inverter_restored='Зв’язок з інвертором відновлено',grid_voltage_bad='Неприйнятна напруга мережі',grid_voltage_ok='Напруга мережі нормалізувалася',overload_high='Високе навантаження інвертора',overload_ok='Навантаження інвертора нормалізувалося',temperature_high='Перегрів інвертора',temperature_ok='Температура інвертора нормалізувалася',battery_critical='Критичний заряд АКБ інвертора',battery_critical_ok='Заряд АКБ вище критичного рівня',server_unplugged='Телефон сервера від’єднаний від зарядки',server_plugged='Телефон сервера під’єднаний до зарядки',storage_low='Закінчується місце для історії',storage_ok='Вільне місце для історії відновлено',storage_error='Помилка запису історії')

def enabled(row,kind):return bool(row['settings'].get(KIND_GROUP.get(kind,kind),False))

def percent(value):
    return float(value) if type(value) in (int,float) and math.isfinite(value) and 0<=value<=100 else None

def mains_present(state):
    grid=state.get('normalized',{}).get('grid',{})
    phases=grid.get('phases')
    if isinstance(phases,list):
        voltages=[p.get('voltage') for p in phases if isinstance(p,dict)]
        values=[v for v in voltages if type(v) in (int,float) and math.isfinite(v) and 0<=v<=1000]
        # Low/out-of-range frequency is not absence of voltage. A missing
        # measurement must never inherit the driver's unavailable/zero flag.
        return any(v>20 for v in values) if values else None
    value=grid.get('available')
    return bool(value) if type(value) in (bool,int) and value in (0,1) else None

class PushAlerts:
    def __init__(self,path,clock=time.time,logs=None):
        self.path=Path(path);self.clock=clock;self.lock=threading.RLock()
        self.rows=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.logs=logs;self.listeners=set();self.pending={}
        for row in self.rows.values():row['settings']=validate(row.get('settings',{}))

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as stream:
            json.dump(self.rows,stream,ensure_ascii=False,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,self.path)
        for event in tuple(self.listeners):event.set()

    def subscribe(self,event):
        with self.lock:self.listeners.add(event)
    def unsubscribe(self,event):
        with self.lock:self.listeners.discard(event)

    @staticmethod
    def key(account,client):
        if not isinstance(client,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',client):raise ValueError('Invalid client ID')
        return account+'|'+client

    def settings(self,account,client,grants,changes=None):
        key=self.key(account,client)
        with self.lock:
            old=self.rows.get(key)
            previous=(old or {}).get('settings',{})
            if changes is not None:
                validate(changes)
                previous={**previous,**changes}
            settings=validate(previous)
            before_settings=dict((old or {}).get('settings',{}))
            if old:old['settings']=validate(old.get('settings',{}))
            row=old or dict(settings=settings,grants=[],states={},events=[])
            if settings!=row['settings']:
                changed={k for k in DEFAULTS if settings[k]!=row['settings'][k]}
                row['states']={k:v for k,v in row['states'].items() if not any(k.endswith(':'+c) for c in changed) and not ('server_battery_threshold' in changed and k.endswith(':server_battery'))}
                row['events']=[e for e in row['events'] if settings.get(KIND_GROUP.get(e['kind'],e['kind']),False) and KIND_GROUP.get(e['kind'],e['kind']) not in changed and not ('server_battery_threshold' in changed and e['kind']=='server_battery')]
            if settings!=row['settings']:
                dependencies={'connection_delay_s':{'inverter_connection'},'grid_voltage_min':{'grid_voltage'},'grid_voltage_max':{'grid_voltage'},'condition_delay_s':{'grid_voltage','overload','over_temperature'},'overload_pct':{'overload'},'temperature_c':{'over_temperature'},'critical_battery_pct':{'critical_battery'},'power_delay_s':{'server_power'},'storage_min_mb':{'storage'}}
                reset={c for c in changed if c in KIND_GROUP.values()}
                for c in changed:reset.update(dependencies.get(c,set()))
                row['states']={k:v for k,v in row['states'].items() if not any(k.endswith(':condition:'+g) for g in reset)}
                row['events']=[e for e in row['events'] if KIND_GROUP.get(e['kind']) not in reset]
                self.pending={k:v for k,v in self.pending.items() if k[0]!=key or not any(k[1].endswith(':condition:'+g) for g in reset)}
            row.update(settings=settings,grants=list(grants))
            if old is None and len(self.rows)>=256:raise ValueError('Too many notification subscriptions')
            self.rows[key]=row
            if changes is not None and self.logs:
                self.logs.event('Notification settings applied',code='notifications.settings.applied',client_id=client,settings=settings,changed=[k for k in DEFAULTS if settings.get(k)!=before_settings.get(k)])
            self._save()
            return dict(settings)

    def _add(self,row,kind,device,**details):
        if not enabled(row,kind):return
        message=MESSAGES.get(kind) or f"Заряд батареї сервера не більше {row['settings']['server_battery_threshold']}%"
        if 'detail' not in details:
            if type(details.get('voltage')) in (int,float):details['detail']=f"Напруга: {details['voltage']:g} В"
            elif type(details.get('value')) in (int,float):details['detail']=f"Показник: {details['value']:g}; поріг: {details.get('threshold')}"
            elif type(details.get('free_mb')) in (int,float):details['detail']=f"Вільне місце: {details['free_mb']} МіБ"
        event=dict(id=uuid4().hex,kind=kind,message=message,device_id=device,created=self.clock(),**details)
        row['events']=[e for e in row['events'] if self.clock()-e['created']<86400][-127:]+[event]
        if self.logs:self.logs.event('Notification queued',code='notifications.queued',notification_id=event['id'],kind=kind,device_id=device,**details)

    def _low(self,row,device,kind,value,threshold):
        if value is None or not enabled(row,kind):return
        key=device+':'+kind;old=row['states'].get(key,False)
        if value<=threshold and not old:
            row['states'][key]=True;self._add(row,kind,device,percent=value,threshold=threshold)
        elif value>=min(100,threshold+3):row['states'][key]=False

    def _condition(self,row,device,group,bad,delay,raised,cleared,**details):
        if not row['settings'].get(group,False):return
        ident=next(k for k,v in self.rows.items() if v is row)
        key=device+':condition:'+group; pending_key=(ident,key)
        if bad is None:self.pending.pop(pending_key,None);return
        old=row['states'].get(key,False)
        if bool(bad)==old:self.pending.pop(pending_key,None);return
        since,value=self.pending.get(pending_key,(self.clock(),bool(bad)))
        if value!=bool(bad):since=self.clock()
        self.pending[pending_key]=(since,bool(bad))
        if self.clock()-since>=delay:
            row['states'][key]=bool(bad);self.pending.pop(pending_key,None)
            self._add(row,raised if bad else cleared,device,**details)

    def storage_failure(self,failed):
        with self.lock:
            before=copy.deepcopy(self.rows)
            for row in self.rows.values():
                if not row['grants'] or not row['settings'].get('storage'):continue
                if failed and not row['states'].get(':write_error'):
                    row['states'][':write_error']=True;self._add(row,'storage_error','')
                elif not failed:row['states'].pop(':write_error',None)
            if before!=self.rows:self._save()

    def phone(self,plugged,free_bytes=None,write_error=False):
        with self.lock:
            before=copy.deepcopy(self.rows)
            for row in self.rows.values():
                if not row['grants']:continue
                self._condition(row,'','server_power',not plugged,row['settings']['power_delay_s'] if not plugged else 0,'server_unplugged','server_plugged')
                if free_bytes is not None:
                    limit=row['settings']['storage_min_mb']*1024*1024
                    old=row['states'].get(':condition:storage',False)
                    self._condition(row,'','storage',free_bytes<limit+(64*1024*1024 if old else 0),30,'storage_low','storage_ok',free_mb=round(free_bytes/1024/1024))
            if before!=self.rows:self._save()

    def observe(self,device,state):
        with self.lock:
            before=copy.deepcopy(self.rows)
            for row in self.rows.values():
                if device not in row['grants']:continue
                settings=row['settings']
                self._condition(row,device,'inverter_connection',bool(state.get('stale',True)),settings['connection_delay_s'] if state.get('stale',True) else 0,'inverter_lost','inverter_restored')
                if not state.get('stale',True):
                    data=state.get('data',{});grid_data=state.get('normalized',{}).get('grid',{})
                    volts=data.get('grid_v')
                    if volts is None:
                        phases=grid_data.get('phases') or [];volts=phases[0].get('voltage') if phases else None
                    old=row['states'].get(device+':condition:grid_voltage',False)
                    bad=None if type(volts) not in (int,float) or not math.isfinite(volts) or volts<=20 else (volts<settings['grid_voltage_min']+(3 if old else 0) or volts>settings['grid_voltage_max']-(3 if old else 0))
                    self._condition(row,device,'grid_voltage',bad,settings['condition_delay_s'],'grid_voltage_bad','grid_voltage_ok',voltage=volts)
                    for group,field,limit,hyst,up,down in [('overload','load_pct',settings['overload_pct'],5,'overload_high','overload_ok'),('over_temperature','temperature_c',settings['temperature_c'],3,'temperature_high','temperature_ok')]:
                        value=data.get(field);active=row['states'].get(device+':condition:'+group,False)
                        self._condition(row,device,group,None if type(value) not in (int,float) or not math.isfinite(value) else value>=limit-(hyst if active else 0),settings['condition_delay_s'],up,down,value=value,threshold=limit)
                    value=percent(state.get('battery',{}).get('values',{}).get('soc'));active=row['states'].get(device+':condition:critical_battery',False)
                    self._condition(row,device,'critical_battery',None if value is None else value<=settings['critical_battery_pct']+(3 if active else 0),0,'battery_critical','battery_critical_ok',percent=value,threshold=settings['critical_battery_pct'])
                else:
                    # Never count missing measurements as a continuous threshold breach.
                    ident=next(k for k,v in self.rows.items() if v is row)
                    self.pending={k:v for k,v in self.pending.items() if k[0]!=ident or not any(k[1]==device+':condition:'+g for g in ('grid_voltage','overload','over_temperature','critical_battery'))}
                key=device+':grid';states=row['states']
                value=mains_present(state)
                if state.get('stale',True) or type(value) is not bool:
                    states.pop(key+':pending',None);continue
                # Two distinct telemetry samples confirm mains changes. Repeated
                # API/observer snapshots cannot manufacture a second sample.
                sample=state.get('updated')
                pending=states.get(key+':pending')
                if sample and states.get(key)!=value:
                    if pending and pending['value']==value and pending['sample']!=sample:
                        previous=states.get(key);states[key]=value;states.pop(key+':pending',None)
                        if not value or previous is False:self._add(row,'grid_restored' if value else 'grid_lost',device)
                    elif not pending or pending['value']!=value:states[key+':pending']=dict(value=value,sample=sample)
                else:states.pop(key+':pending',None)
                self._low(row,device,'inverter_battery',percent(state.get('battery',{}).get('values',{}).get('soc')),30)
            if before!=self.rows:self._save()

    def battery(self,value):
        value=percent(value)
        with self.lock:
            before=copy.deepcopy(self.rows)
            for row in self.rows.values():
                if row['grants']:self._low(row,'','server_battery',value,row['settings']['server_battery_threshold'])
            if before!=self.rows:self._save()

    def feed(self,account,client,grants):
        if not grants:return []
        with self.lock:
            row=self.rows.get(self.key(account,client))
            if not row:return []
            return [dict(e) for e in row['events'] if self.clock()-e['created']<86400 and enabled(row,e['kind']) and (not e['device_id'] or e['device_id'] in grants)]

    def acknowledge(self,account,client,ids):
        if not isinstance(ids,list) or len(ids)>128 or any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{32}',x) for x in ids):raise ValueError('Invalid alert acknowledgement')
        with self.lock:
            row=self.rows.get(self.key(account,client))
            if row:
                removed=sum(e['id'] in ids for e in row['events'])
                row['events']=[e for e in row['events'] if e['id'] not in ids];self._save()
                if removed and self.logs:self.logs.event('Notifications acknowledged',code='notifications.acknowledged',client_id=client,count=removed)
        return True
