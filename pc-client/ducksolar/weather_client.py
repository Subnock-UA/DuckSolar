"""Android adapter for the PC 0.3.4 forecast engine. No inverter writes."""
import hashlib
import json
import math
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from .weather import WeatherService

_lock = threading.RLock()
_job = {'state': 'idle'}
_cancel=threading.Event()
_active=False
_pause=False
_store=None
_journal=None

def configure(journal):
    global _journal
    _journal=journal

def note(code,**details):
    if _journal:_journal(code,details=details)

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)

def update(phase=None,**fields):
    with _lock:
        if not _active:return
        changed=phase is not None and _job.get('phase')!=phase
        _job.update(fields)
        if phase is not None:_job['phase']=phase
        if _store:write_json(_store,_job)
        if changed:note('weather.stage',phase=phase)

def check():
    if _cancel.is_set():raise InterruptedError('Прогноз призупинено' if _pause else 'Прогноз скасовано')

def cancel(root,identity,pause=False):
    global _pause
    with _lock:
        if _active and _job.get('identity')==identity:
            _pause=bool(pause);_cancel.set();update('pausing' if pause else 'cancelling')
        elif not pause:
            prior=status(root,identity)
            if prior.get('state')=='paused':
                value=dict(state='cancelled',identity=identity,training=prior.get('training',False))
                write_json(folder(root,identity)/'job.json',value)
                if _job.get('identity')==identity:_job.update(value)
    return status(root,identity)

def validate_profile(value):
    result = {}
    for key, low, high in (('installed_kw', .1, 1000), ('tilt_deg', 0, 90), ('azimuth_deg', 0, 360)):
        v = value.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{key}: допустимо {low}–{high}')
        result[key] = float(v)
    result['azimuth_deg'] %= 360
    return result

def folder(root, identity):
    return Path(root) / 'weather' / hashlib.sha256(identity.encode()).hexdigest()[:20]

def settings(root, identity, value=None):
    path = folder(root, identity) / 'settings.json'
    if value is not None:
        with _lock:
            if _job.get('state') == 'running': raise ValueError('Дочекайтеся завершення поточного прогнозу')
        profile = validate_profile(value)
        name = str(value.get('location', '')).strip()
        if not 2 <= len(name) <= 100:
            raise ValueError('Вкажіть населений пункт (2–100 символів)')
        result = dict(profile, location=name)
        for key, low, high in (('latitude', -90, 90), ('longitude', -180, 180)):
            v = value.get(key)
            if v is None: result[key] = None
            elif type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
                raise ValueError('Некоректні координати')
            else: result[key] = float(v)
        if (result['latitude'] is None) != (result['longitude'] is None):
            raise ValueError('Вкажіть обидві координати або залиште обидва поля порожніми')
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temp.replace(path)
        return result
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}

class Forecast(WeatherService):
    def _get_json(self,host,path,params):
        if _active:check()
        phase='training_weather' if 'previous-runs' in host else ('location' if 'geocoding' in host else 'weather')
        update(phase)
        started=time.monotonic();note('weather.request.started',host=host,phase=phase)
        try:
            value=super()._get_json(host,path,params)
            if _active:check()
            note('weather.request.completed',host=host,duration_s=round(time.monotonic()-started,3))
            return value
        except Exception as exc:
            note('weather.request.failed',host=host,exception_class=type(exc).__name__,duration_s=round(time.monotonic()-started,3))
            raise

    def _generation_for_days(self,*args):
        if _active:check()
        update('forecast')
        return super()._generation_for_days(*args)

    def calibrate_generation(self,*args):
        result=super().calibrate_generation(*args)
        if _active:check()
        note('weather.calibration.completed',sample_count=result.get('sample_count',0),model=result.get('model'))
        return result
    def saved_calibration(self, location):
        obj = self._read_json_file(self.calibration_path)
        if (isinstance(obj, dict) and obj.get('geometry_key') == self._geometry_key()
            and abs(obj.get('latitude',999)-location['latitude']) < .01
            and abs(obj.get('longitude',999)-location['longitude']) < .01):
            return obj
        return self._fallback_calibration('Навчання за історією ще не виконано')

    def cached_forecast(self):
        obj = super().cached_forecast()
        if obj and obj.get('settings_key') == self.settings_key: return obj
        return None

    def fetch_10_day(self, location_name=None, reader=None):
        obj = super().fetch_10_day(location_name, reader)
        obj['settings_key'] = self.settings_key
        self._write_json_file(self.cache_path, obj)
        return obj

    def _fetch_forecast(self, latitude, longitude):
        # Include next midnight so the last displayed day's backward hourly
        # radiation has its closing interval, as required by Open-Meteo.
        old = self.cfg.weather_days
        self.cfg.weather_days = old + 1
        try: return super()._fetch_forecast(latitude, longitude)
        finally: self.cfg.weather_days = old

    def _normalise_days(self, obj):
        # Open-Meteo daily Unix dates use its response UTC offset, while
        # hourly intervals use actual timezone rules (including DST).
        # Converting daily date labels through ZoneInfo can duplicate Oct 25.
        from datetime import datetime, timezone
        obj = dict(obj)
        daily = dict(obj.get('daily') or {})
        offset = obj.get('utc_offset_seconds', 0)
        daily['time'] = [datetime.fromtimestamp(v + offset, timezone.utc).date().isoformat()
            if isinstance(v, (int,float)) else v for v in daily.get('time', [])]
        obj['daily'] = daily
        return super()._normalise_days(obj)[:10]

def engine(root, identity):
    s = settings(root, identity)
    if not s: raise ValueError('Спочатку налаштуйте місце та параметри панелей')
    profile = dict(validate_profile(s), device_id=identity, revision=0)
    cfg = SimpleNamespace(root_dir=str(folder(root, identity)), history_device_id=identity,
        legacy_device_id='', installation_id=identity, server_url='', pv_installed_kw=s['installed_kw'],
        weather_location_name=s['location'], weather_latitude=s.get('latitude'), weather_longitude=s.get('longitude'),
        weather_timeout_s=15, weather_days=10, pv_forecast_max_training_days=180, pv_forecast_fallback_pr=.8)
    obj = Forecast(cfg, profile_provider=lambda: profile)
    obj.settings_key = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
    return obj

class History:
    def __init__(self, sync, path): self.sync, self.path = sync, path
    def generation_summaries(self):
        try: cached = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): cached = {}
        for _ in range(11):
            result = self.sync({k: v['revision'] for k,v in cached.items()})
            manifest = result['manifest']
            cached = {k:v for k,v in cached.items() if k in manifest}
            for row in result['changed']:
                cached[row['day']] = dict(revision=row['revision'], summary=row['summary'])
            # Persist every completed batch, before requesting the next one.
            write_json(self.path,cached)
            complete=sum(cached.get(k,{}).get('revision')==v for k,v in manifest.items())
            update('history',done=complete,total=len(manifest),batch=_+1)
            note('weather.history.checkpoint',done=complete,total=len(manifest),batch=_+1)
            if all(cached.get(k,{}).get('revision') == v for k,v in manifest.items()):
                return cached
        raise ValueError('Історія ще не синхронізована повністю. Повторіть навчання пізніше')

def status(root, identity):
    with _lock: result = dict(_job) if _job.get('identity') == identity else {'state':'idle'}
    if result['state']=='idle':
        try:result=json.loads((folder(root,identity)/'job.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
    if result.get('state')=='running' and not _active:
        result.update(state='paused',phase='interrupted')
    try:
        obj = engine(root, identity)
        cached = obj.cached_forecast()
        if cached: result['result'] = cached
    except ValueError: pass
    result['settings'] = settings(root, identity)
    return result

def start(root, identity, sync=None):
    global _job,_active,_pause,_store
    obj = engine(root, identity)
    with _lock:
        if _active: raise ValueError('Попередній прогноз ще обробляється')
        _pause=False;_cancel.clear()
        _store=folder(root,identity)/'job.json'
        _job = dict(state='running', identity=identity, training=bool(sync),phase='starting')
        write_json(_store,_job)
        _active=True
    note('weather.started',training=bool(sync))
    def work():
        global _job,_active
        started=time.monotonic()
        try:
            reader = History(sync, folder(root,identity)/'summaries.json') if sync else None
            check()
            obj.fetch_10_day(reader=reader)
            check()
            value = dict(state='complete', identity=identity,training=bool(sync))
        except Exception as exc:
            value = dict(state=('paused' if _pause else 'cancelled') if _cancel.is_set() else 'error', identity=identity,training=bool(sync),error=str(exc)[:512])
        with _lock:
            _job=value;_active=False
            try:write_json(_store,value)
            except OSError:note('weather.checkpoint.failed',phase='job_result')
        note('weather.'+value['state'],training=bool(sync),duration_s=round(time.monotonic()-started,3))
    threading.Thread(target=work, name='ClientWeather', daemon=True).start()
    return status(root, identity)
