"""Versioned interval ledger. House meter and inverter are separate boundaries."""
import math,json,hashlib,uuid
from datetime import datetime,date,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ALGORITHM='energy.intervals.v1'
ZONE=ZoneInfo('Europe/Kyiv')
def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def stamp(t):
    if isinstance(t,str):t=datetime.fromisoformat(t)
    return t.replace(tzinfo=ZONE) if t.tzinfo is None else t.astimezone(ZONE)
def seconds(a,b):return stamp(b).timestamp()-stamp(a).timestamp()
def interval_energy(rows,direction,start,end,max_gap=900):
    intervals=[];resets=[];covered=0.;total=0.
    for a,b in zip(rows,rows[1:]):
        x,y=stamp(a['timestamp']),stamp(b['timestamp']);dt=seconds(x,y)
        if dt<=0:continue
        left=max(x,stamp(start),key=lambda t:t.timestamp());right=min(y,stamp(end),key=lambda t:t.timestamp());duration=seconds(left,right)
        if duration<=0:continue
        value=None;kind=None;reason=''
        if direction=='pv':
            av,bv=a.get('pv_w'),b.get('pv_w')
            if dt<=max_gap and number(av) and number(bv):
                f=seconds(x,left)/dt;g=seconds(x,right)/dt
                value=((av+(bv-av)*f)+(av+(bv-av)*g))*.5*duration/3600000;kind='integrated'
        else:
            key='grid_'+direction+'_energy_total_kwh';identity='grid_'+direction+'_counter_id'
            av,bv=a.get(key),b.get(key);same=bool(a.get(identity)) and a.get(identity)==b.get(identity)
            # Cross-boundary counter interpolation is explicitly estimated.
            if same and number(av) and number(bv):
                if bv>=av:
                    value=(bv-av)*duration/dt;kind='counter' if duration==dt else 'counter_estimated_boundary'
                else:
                    limit=a.get('grid_'+direction+'_counter_modulus_kwh')
                    if number(limit) and limit==b.get('grid_'+direction+'_counter_modulus_kwh') and 0<=bv<av<limit:
                        value=(limit-av+bv)*duration/dt;kind='counter_rollover' if duration==dt else 'counter_estimated_boundary'
                    else:resets.append(dict(from_time=x.isoformat(),to_time=y.isoformat(),reason='counter_decreased'))
            if value is None and dt<=max_gap:
                key='grid_'+direction+'_w';av,bv=a.get(key),b.get(key)
                source=a.get('grid_'+direction+'_source')
                if number(av) and number(bv) and source in ('measured','estimated') and source==b.get('grid_'+direction+'_source') and a.get('grid_'+direction+'_origin')==b.get('grid_'+direction+'_origin'):
                    f=seconds(x,left)/dt;g=seconds(x,right)/dt
                    value=((av+(bv-av)*f)+(av+(bv-av)*g))*.5*duration/3600000;kind=source
                    reason=a.get('grid_'+direction+'_reason','')
        if value is not None:
            total+=value;covered+=duration
            intervals.append(dict(start=left.isoformat(),end=right.isoformat(),kwh=value,source=kind,reason=reason))
    period=max(0,seconds(start,end));by_source={}
    for i in intervals:by_source[i['source']]=by_source.get(i['source'],0)+seconds(i['start'],i['end'])
    measured=sum(v for k,v in by_source.items() if k in ('counter','counter_rollover','measured'))
    return dict(kwh=total if intervals else None,coverage_pct=min(100,covered/period*100) if period else 0,
        measured_pct=min(100,measured/period*100) if period else 0,estimated_pct=min(100,(covered-measured)/period*100) if period else 0,
        missing_pct=max(0,100-covered/period*100) if period else 0,intervals=intervals,resets=resets,boundary='inverter')
def meter_segments(readings,start,end):
    from .meter_intervals import report
    return report(readings,start,end)

def month_report(reader,storage,cfg,anchor,now=None,device_id='inverter-1',source='Auto'):
    if source not in ('Auto','Local','SmartESS'):raise ValueError('Некоректне джерело історії')
    now=stamp(now or datetime.now(ZONE));anchor=date.fromisoformat(anchor) if isinstance(anchor,str) else anchor
    start=datetime(anchor.year,anchor.month,1,tzinfo=ZONE)
    next_month=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    end=min(now,next_month)
    if end<=start:raise ValueError('Період ще не почався за часом Server')
    rows=[];day=(start-timedelta(days=1)).date()
    while day<=end.date():
        rows.extend(reader.load_day(day,source));day+=timedelta(days=1)
    rows=sorted(rows,key=lambda r:stamp(r['timestamp']).timestamp())
    # Include only fields that determine this algorithm; persist them for replay.
    names=('timestamp','pv_w','grid_import_w','grid_export_w','grid_import_source','grid_export_source','grid_import_origin','grid_export_origin','grid_import_reason','grid_export_reason','grid_import_energy_total_kwh','grid_export_energy_total_kwh','grid_import_counter_id','grid_export_counter_id','grid_import_counter_modulus_kwh','grid_export_counter_modulus_kwh')
    inputs=[{k:(v.isoformat() if isinstance(v,datetime) else v) for k in names if (v:=r.get(k)) is not None} for r in rows]
    readings=storage.list_meter_readings(limit=100000)
    result=dict(algorithm=ALGORITHM,start=start.isoformat(),end=end.isoformat(),device_id=device_id,
        max_gap_s=cfg.max_integration_gap_s,history_source=source,
        pv=interval_energy(rows,'pv',start,end,cfg.max_integration_gap_s),
        inverter_import=interval_energy(rows,'import',start,end,cfg.max_integration_gap_s),
        inverter_export=interval_energy(rows,'export',start,end,cfg.max_integration_gap_s),
        house_meter=meter_segments(readings,start,end),quality_note='Покриття і частки джерел — орієнтовна надійність, не метрологічна точність')
    payload=dict(report=result,inputs=inputs,meter_readings=readings)
    encoded=json.dumps(payload,ensure_ascii=False,default=str,allow_nan=False,sort_keys=True)
    digest=hashlib.sha256(encoded.encode()).hexdigest();result['audit_id']=digest
    target=Path(cfg.root_dir)/'Data'/'EnergyAudit'/device_id;target.mkdir(parents=True,exist_ok=True)
    f=target/(digest+'.json')
    if not f.exists():
        temp=f.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(encoded,encoding='utf-8');temp.replace(f)
    return result
