"""Independent battery sources. JK-BMS BLE transport is deliberately deferred.
Adapters publish already decoded samples here; this module never scans/connects.
Inverter telemetry/history and its energy calculations are never overwritten.
"""
import math,time,threading
from dataclasses import dataclass,field
from typing import Protocol,Mapping
from collections import deque

def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

class BatteryAdapter(Protocol):
    source_id:str
    def start(self,sink): ...
    def stop(self): ...

@dataclass(frozen=True)
class BatterySample:
    device_id:str
    source_id:str
    values:Mapping[str,float]
    received_monotonic:float=field(default_factory=time.monotonic)
    max_age_s:float=30
    quality:str='measured'
    metadata:Mapping[str,str]=field(default_factory=dict)

class BatterySources:
    FIELDS={'soc':(0,100),'voltage_v':(0,1000),'charge_a':(0,10000),'discharge_a':(0,10000),'temperature_c':(-80,200),'cell_min_v':(0,10),'cell_max_v':(0,10)}
    def __init__(self,clock=time.monotonic,ledger=None):
        self.ledger=ledger;self.clock=clock;self.lock=threading.RLock();self.samples={};self.loads={};self.adapters={}
    def register(self,adapter:BatteryAdapter):
        if not adapter.source_id.startswith('bms.'):raise ValueError('Independent adapter must use bms.* source')
        with self.lock:
            if adapter.source_id in self.adapters:raise ValueError('Adapter already registered')
            self.adapters[adapter.source_id]=adapter
    def start(self):
        for adapter in list(self.adapters.values()):adapter.start(self.publish)
    def stop(self):
        for adapter in list(self.adapters.values()):adapter.stop()
        with self.lock:self.samples.clear();self.loads.clear()
    def publish(self,sample:BatterySample):
        if not sample.source_id.startswith('bms.') or sample.source_id not in self.adapters:raise ValueError('Unknown battery adapter')
        now=self.clock()
        if not 1<=sample.max_age_s<=300 or not 0<=now-sample.received_monotonic<=300:raise ValueError('Invalid sample age')
        clean={k:float(v) for k,v in sample.values.items() if k in self.FIELDS and number(v) and self.FIELDS[k][0]<=v<=self.FIELDS[k][1]}
        with self.lock:self.samples[(sample.device_id,sample.source_id)]=BatterySample(sample.device_id,sample.source_id,clean,sample.received_monotonic,sample.max_age_s,sample.quality,dict(sample.metadata))
    def view(self,device_id,state,settings):
        now=self.clock();data=state.get('data',{});fields={};origins={}
        if not state.get('stale',True):
            for key,raw in [('voltage_v','battery_v'),('charge_a','charge_a'),('discharge_a','discharge_a')]:
                value=data.get(raw)
                if number(value) and self.FIELDS[key][0]<=value<=self.FIELDS[key][1]:fields[key]=value;origins[key]='inverter'
        from .drivers.daxtromn import current_profile
        raw=state.get('parameters',{}).get('raw',{}) or state.get('raw',{})
        try:lithium=int(raw['QPIRI'].lstrip('(').split()[12])==6
        except (KeyError,IndexError,ValueError,TypeError):lithium=False
        if not state.get('stale',True) and current_profile(raw) and lithium:
            soc=data.get('battery_pct')
            if number(soc) and 0<=soc<=100:
                fields['soc']=soc;origins['soc']='bms.inverter'
        with self.lock:
            sources=[]
            for (device,source),sample in self.samples.items():
                if device!=device_id:continue
                age=now-sample.received_monotonic;fresh=0<=age<=sample.max_age_s
                sources.append(dict(source=source,fresh=fresh,age_s=round(age,1),quality=sample.quality))
                if fresh:
                    # Newest decoded BMS sample wins per field; missing BMS fields fall back to inverter.
                    for key,value in sample.values.items():
                        if key not in origins or origins[key] in ('inverter','bms.inverter') or sample.received_monotonic>origins.get('_'+key,-1):fields[key]=value;origins[key]=source;origins['_'+key]=sample.received_monotonic
            watts=fields.get('voltage_v',0)*fields.get('discharge_a',0) if all(k in fields for k in ('voltage_v','discharge_a')) else None
            charging=fields.get('charge_a',0)>0
            history=self.loads.setdefault(device_id,deque(maxlen=360));last=history[-1][0] if history else None
            if number(watts) and (last is None or now-last>=4):history.append((now,watts))
            while history and now-history[0][0]>300:history.popleft()
            average=sum(v for _,v in history)/len(history) if history and now-history[-1][0]<=30 else None
        cap=settings.get('usable_kwh');soc=fields.get('soc')
        remaining=cap*soc/100 if number(cap) and cap>0 and number(soc) else None
        energy=max(0,remaining-cap*settings.get('reserve_pct',20)/100) if remaining is not None else None
        estimate=dict(soc=soc,remaining_kwh=remaining,available_kwh=energy,
            source=origins.get('soc','unavailable'),confidence='measured' if soc is not None else 'unavailable',
            note='SOC БМС через інвертор; залишок енергії та автономність оцінено за заданою ємністю.' if soc is not None else 'Актуальний SOC БМС недоступний. Розрахунковий SOC не підставляється.')
        for key,power in [('current_hours',watts),('average_hours',average),('curve_hours',average)]:
            estimate[key]=energy*1000/power if energy is not None and number(power) and power>=10 and not charging else None
        if self.ledger:self.ledger.history.record_bms(device_id,time.time(),soc,remaining,origins.get('soc','unavailable'))
        return dict(contract='battery.sources.v2',values=fields,origins={k:v for k,v in origins.items() if not k.startswith('_')},sources=sources,bms_supported_future='JK-BMS BLE (transport not installed)',bms_connected=soc is not None,estimate=estimate)
