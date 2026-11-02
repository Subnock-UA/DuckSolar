"""Device-bound PV metadata; weather calculations stay in Client."""
import copy
import math
import threading
from datetime import datetime
from .config import save_config
_LOCK=threading.RLock()

def validate_profile(value):
    if not isinstance(value,dict) or set(value)-{'installed_kw','tilt_deg','azimuth_deg'}:
        raise ValueError('Невідомі параметри панелей')
    result={}
    for key,lo,hi in (('installed_kw',.1,1000),('tilt_deg',0,90),('azimuth_deg',0,360)):
        v=value.get(key)
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError(f'{key}: допустимо {lo}–{hi}')
        result[key]=float(v)
    result['azimuth_deg']%=360
    return result

def profile(cfg,device_id,identity=None):
    row=(cfg.pv_profiles or {}).get(device_id,{})
    serial=(identity or {}).get('serial','')
    if row.get('serial') and serial and row['serial']!=serial:row={}
    return dict(device_id=device_id,installed_kw=row.get('installed_kw',cfg.pv_installed_kw),
        tilt_deg=row.get('tilt_deg',0),azimuth_deg=row.get('azimuth_deg',180),
        configured=bool(row),revision=row.get('revision',0),serial=row.get('serial',''))

def update(cfg,device_id,values,expected_revision,identity=None,logs=None,username='local'):
    values=validate_profile(values)
    with _LOCK:
        old=profile(cfg,device_id,identity)
        if type(expected_revision) is not int or old['revision']!=expected_revision:
            raise ValueError('Параметри панелей вже змінено; оновіть дані')
        candidate=copy.deepcopy(cfg)
        candidate.pv_profiles=copy.deepcopy(cfg.pv_profiles or {})
        row=dict(values,revision=old['revision']+1,serial=(identity or {}).get('serial',''),updated=datetime.now().isoformat(timespec='seconds'))
        candidate.pv_profiles[device_id]=row
        save_config(candidate)
        cfg.pv_profiles=candidate.pv_profiles
        if logs:logs.event('PV profile updated',code='pv.profile.updated',device_id=device_id,username=username,old=old,new=row)
        return profile(cfg,device_id,identity)
