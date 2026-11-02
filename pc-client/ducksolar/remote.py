from __future__ import annotations

import json
import threading
import time
import socket
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4
from .wire import encode, decode
from .client_transport import TransportError
from .tls_transport import SecureTransport
from .config import VERSION


class ServerAPI:
    def __init__(self, url='https://127.0.0.1:8765', logs=None, access_key='', client_id=None, transport=None):
        self.logs = logs
        self.transport = transport or SecureTransport(url, '')
        self.url = self.transport.url
        self.access_key = access_key
        self.client_id = client_id or uuid4().hex
        self.session = None
        self.session_lock = threading.RLock()
        self.connection_timeout_s = 5
        self.generation=0
        self.auth_error=None
        self.request_metrics=threading.local()
        self.auth_codes={"auth.denied","auth.required","auth.serial_required","tls.trust_required","tls.identity_mismatch","api.incompatible"}

    def configure(self, url, key, transport=None):
        transport = transport or SecureTransport(url, '')
        with self.session_lock:
            self.transport, self.url, self.access_key = transport, transport.url, key
            self.session = None
            self.auth_error=None;self.generation+=1

    def ready(self):
        if self.auth_error:return False
        return bool(self.access_key and getattr(self.transport,"pin",True))

    def require_access(self):
        if self.auth_error:raise self.auth_error
        if not self.ready():raise TransportError("Увійдіть у свій акаунт і підтвердьте Server",401,"auth.required")

    def block_auth(self,exc):
        if isinstance(exc,TransportError) and exc.code in self.auth_codes:
            with self.session_lock:self.auth_error=exc;self.session=None

    def headers(self, operation_id=None):
        headers = {'Content-Type':'application/json', 'Authorization':'Bearer ' + self.access_key,
                   'X-DX-Client-ID':self.client_id, 'X-DX-Operation-ID':operation_id or uuid4().hex}
        if self.session: headers['X-DX-Client-Session'] = self.session['client_session_id']
        return headers

    def ensure_session(self):
        self.require_access()
        with self.session_lock:
            self.require_access()
            if self.session: return self.session
            body = json.dumps(dict(client_id=self.client_id, client_version=VERSION, api_version=3)).encode()
            session = self.transport.request('session', body, self.headers(), self.connection_timeout_s)
            if session.get('api_version') != 3: raise TransportError('Несумісна версія API', 409, 'api.incompatible')
            from . import clock
            from datetime import timezone
            clock.update(datetime.fromtimestamp(session.get('server_time',time.time()),timezone.utc))
            self.session = session
            if self.logs:
                self.logs.event('Client session ready', code='session.resumed' if session.get('resumed') else 'session.opened',
                    client_id=self.client_id, client_session_id=session['client_session_id'], server_version=session['server_version'], server_session_id=session['server_session_id'])
            return session

    def _request(self, path, body=None, timeout=3, operation='GET'):
        self.require_access()
        generation=self.generation
        request_id = uuid4().hex
        if self.logs: self.logs.event('API operation started', code='api.operation.started', operation=operation, operation_id=request_id)
        started = time.monotonic()
        try:
            for attempt in range(2):
                self.ensure_session()
                try:
                    raw=self.transport.request(path,body,self.headers(request_id),timeout)
                    decode_started=time.perf_counter();obj=decode(raw)
                    self.request_metrics.last=dict(getattr(getattr(self.transport,'metrics',None),'last',{}),wire_decode_s=round(time.perf_counter()-decode_started,4),operation=operation)
                    break
                except TransportError as exc:
                    if attempt == 0 and exc.code == 'session.expired':
                        with self.session_lock: self.session = None
                        continue
                    raise
            if generation!=self.generation:raise TransportError('Підключення змінено; результат попередньої сесії відкинуто',409,'client.changed')
            if self.logs: self.logs.event('API operation completed', code='api.operation.completed', operation=operation,
                operation_id=request_id, result='ok', duration_ms=round((time.monotonic()-started)*1000,1))
            return obj
        except Exception as exc:
            self.block_auth(exc)
            if self.logs: self.logs.exception('API operation failed', code='api.operation.failed', operation=operation,
                operation_id=request_id, result='error', duration_ms=round((time.monotonic()-started)*1000,1))
            raise

    def get(self, path, timeout=3):
        return self._request(path, timeout=timeout, operation='get.'+path)

    def call(self, domain, method, *args, **kwargs):
        body = json.dumps(encode(dict(domain=domain, method=method, args=args, kwargs=kwargs)), ensure_ascii=False, allow_nan=False).encode()
        timeout = 240 if (domain, method) == ('energy', 'month_compact') else 120 if domain in ('history','weather','tariffs','archive','energy') else 30
        if domain=='history' and method in ('job_start','job_status','job_cancel'):timeout=10
        if domain=='history' and method=='job_result':timeout=30
        return self._request('data', body, timeout=timeout, operation=domain+'.'+method)['result']


class LiveConnection:
    def __init__(self, api, logs):
        self.api, self.logs = api, logs
        self.state = {}
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.connected = False
        self.last_error = ''
        self.connection_state = 'CONNECTING'
        self.last_received = 0
        self.response = None
        self.server_session = None
        self.sequence = -1
        self.wake_event=threading.Event()
        self.recovery_requested=threading.Event()
        self.last_recovery=0.0
        self.mode_changed=threading.Event();self.last_telemetry_received=0.;self.mode_transition_until=0.
        self.thread = threading.Thread(target=self._run, name='ClientLive', daemon=True)

    def start(self): self.thread.start()
    def interrupt(self):
        if self.response:
            try: self.response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError): pass
    def fresh_limit(self):
        # The previous notifications frame remains a valid liveness proof while
        # the first foreground frame is in flight. Acquisition age is separate.
        if self.mode_transition_until>time.monotonic():return max(75,getattr(self.api.transport,'live_stale_s',5))
        return getattr(self.api.transport,'live_stale_s',5)
    def change_mode(self,mode):
        transport=self.api.transport
        if not getattr(transport,'idle_live',False) or getattr(transport,'live_mode','telemetry')==mode:return
        self.mode_transition_until=time.monotonic()+20
        transport.live_mode=mode;transport.live_stale_s=75 if mode=='notifications' else 15
        self.mode_changed.set();self.interrupt();self.wake_event.set()

    def recover_stale(self):
        """Wake a stale reader after Android resumes; a healthy stream is untouched."""
        now=time.monotonic()
        with self.lock:
            if self.stop_event.is_set() or self.api.auth_error or self.connection_state in ('AUTH_REQUIRED','INCOMPATIBLE','STOPPED') or not self.last_received or now-self.last_received<=self.fresh_limit() or now-self.last_recovery<5:return False
            self.last_recovery=now;self.connected=False;self.connection_state='RECONNECTING'
            self.recovery_requested.set()
        self.interrupt();self.wake_event.set()
        return True

    def stop(self):
        self.stop_event.set();self.wake_event.set();self.interrupt();self.thread.join(timeout=6)

    def snapshot(self):
        import copy
        with self.lock:
            state = copy.deepcopy(self.state)
            if not self.connected or time.monotonic()-self.last_received > self.fresh_limit():
                state.update(connection='SERVER_DISCONNECTED', stale=True, client_connection_state=self.connection_state)
                state['statuses'] = dict(LWIP=False, Inverter=False, Cloud=False, API=False)
            if state.get('live_mode')=='notifications':
                elapsed=max(0,time.monotonic()-self.last_telemetry_received)
                if elapsed>15:state['stale']=True
                phone=state.get('server_phone')
                if isinstance(phone,dict):
                    age=phone.get('age_s',0)+elapsed
                    state['server_phone']=dict(phone,age_s=round(age,1),available=bool(phone.get('available')) and age<=45)
            return state

    def accept(self, state):
        if state.get('api_version') != 3: raise TransportError('Несумісна версія API', 409, 'api.incompatible')
        session, sequence = state.get('session_id'), state.get('sequence')
        if not isinstance(sequence, int) or not isinstance(session, str): raise ValueError('Invalid telemetry envelope')
        with self.lock:
            if session == self.server_session and sequence <= self.sequence: return False
            if session != self.server_session: self.sequence = -1
            if state.get('live_mode')=='notifications':
                # Control frames renew transport liveness, never acquisition age.
                state={**(self.state if session==self.server_session else {}),**state}
            else:self.last_telemetry_received=time.monotonic()
            if state.get('live_mode','telemetry')==getattr(self.api.transport,'live_mode','telemetry'):self.mode_transition_until=0.
            self.server_session, self.sequence = session, sequence
            from . import clock
            clock.update(state.get('server_time'),state.get('server_utc'))
            self.state, self.connected, self.last_received = state, True, time.monotonic()
            self.connection_state = 'CONNECTED'
            self.last_error = ''
        return True

    def _run(self):
        retry = 1
        failures=0
        blocked_announced=False
        session_retried=False
        while not self.stop_event.is_set():
            if not getattr(self.api.transport,'network_available',lambda:True)():
                with self.lock:
                    self.connected=False;self.connection_state='WAITING_NETWORK';self.last_error='Немає мережевого підключення телефона'
                self.wake_event.wait(1);self.wake_event.clear();retry=1;continue
            if not self.api.ready():
                with self.lock:
                    self.connected=False;self.connection_state='AUTH_REQUIRED'
                    self.last_error=str(self.api.auth_error or 'Увійдіть у свій акаунт і підтвердьте Server')
                if not blocked_announced:
                    self.logs.event('Client awaiting login',code='client.auth_required');blocked_announced=True
                self.stop_event.wait(.25);continue
            blocked_announced=False
            try:
                self.mode_changed.clear()
                self.connection_state = 'CONNECTING' if not self.state else 'RECONNECTING'
                generation=self.api.generation
                session=self.api.ensure_session()
                announced = False
                transport = self.api.transport
                getattr(transport,'configure_live',lambda session:None)(session)
                for obj in transport.events(self.api.headers(), self.stop_event, lambda response:setattr(self,'response',response)):
                    if transport is not self.api.transport or generation!=self.api.generation: break
                    if self.accept(decode(obj)):
                        getattr(transport,'frame_received',lambda state:None)(self.state)
                        retry = 1
                        failures=0
                        session_retried=False
                        self.recovery_requested.clear()
                        if not announced:
                            self.logs.event('Client connected to Server', code='client.connected', server_session_id=self.server_session, client_id=self.api.client_id)
                            announced = True
            except Exception as exc:
                if self.mode_changed.is_set():
                    self.mode_changed.clear();continue
                if generation!=self.api.generation:continue
                session_error=isinstance(exc,TransportError) and exc.code in ('session.expired','session.required')
                recovering=self.recovery_requested.is_set()
                stale_transport=(isinstance(exc,TransportError) and exc.code in ('live.closed','live.incomplete') and self.last_received and time.monotonic()-self.last_received>max(5,(self.api.session or {}).get('session_timeout_s',90)-5))
                self.recovery_requested.clear()
                if (session_error or (recovering and not (isinstance(exc,TransportError) and exc.code in self.api.auth_codes)) or stale_transport) and not session_retried and not self.stop_event.is_set():
                    # One immediate authenticated session retry; actual auth denial still blocks.
                    session_retried=True
                    with self.api.session_lock:self.api.session=None
                    with self.lock:
                        self.connected=False;self.connection_state='RECONNECTING';self.last_error='Відновлення підключення після паузи'
                    self.logs.event('Refreshing live session after pause',code='client.session_recovering',error_code=getattr(exc,'code','transport.interrupted'))
                    continue
                failures+=1
                self.api.block_auth(exc)
                with self.lock:
                    self.connected = False
                    self.last_error = str(exc)
                    self.connection_state = 'AUTH_REQUIRED' if isinstance(exc,TransportError) and exc.code in ('auth.denied','auth.required','auth.serial_required','tls.trust_required','tls.identity_mismatch') else 'INCOMPATIBLE' if isinstance(exc,TransportError) and exc.code=='api.incompatible' else 'RECONNECTING'
                if isinstance(exc,TransportError) and exc.code in ('session.expired','session.required'):
                    with self.api.session_lock:self.api.session=None
                if not self.stop_event.is_set():self.logs.event('Client disconnected: '+str(exc),code='client.disconnected',result=self.connection_state,retry_s=retry,failure_count=failures,error_code=getattr(exc,'code','connection.error'),payload_bytes=getattr(exc,'payload_bytes',None),json_position=getattr(exc,'json_position',None))
            finally:
                self.response = None
            self.wake_event.wait(retry);self.wake_event.clear()
            retry = min(10, retry*2)
        self.connection_state = 'STOPPED'


class RemoteMonitor:
    def __init__(self, live): self.live=live
    def snapshot(self): return self.live.snapshot()
    def force_redirect(self):
        threading.Thread(target=self.live.api.call, args=('monitor','redirect'), daemon=True).start()


class RemoteParameters:
    def __init__(self, live): self.live=live
    def snapshot(self):
        state=self.live.snapshot();parameters=dict(state.get('parameters',{}))
        if state.get('stale') or state.get('connection')=='SERVER_DISCONNECTED':parameters['stale']=True
        return parameters
    def request_refresh(self):
        threading.Thread(target=self.live.api.call, args=('monitor','refresh_parameters'), daemon=True).start()


class RemoteStorage:
    def __init__(self, api): self.api=api
    def finance_view(self, year, month):
        return self.api.call('finance','view',year,month)
    def __getattr__(self, method):
        if method.startswith('_'): raise AttributeError(method)
        return lambda *a,**kw: self.api.call('storage',method,*a,**kw)


class RemoteHistory:
    def __init__(self, api): self.api=api
    def month_series(self, anchor, source='Auto', query_id=''):
        return self.api.call('history','month_series',anchor,source,query_id=query_id)
    def energy_period(self, period, anchor=None, source='Auto', query_id=''):
        return self.api.call('history','energy_period',period,anchor,source,query_id=query_id)
    def query_status(self, query_id): return self.api.call("history","query_status",query_id)
    def cancel(self, query_id):
        def work():
            try: self.api.call('history','cancel',query_id)
            except Exception: pass
        threading.Thread(target=work,name='HistoryCancel',daemon=True).start()

    def generation_summaries(self):
        path=self.summary_cache_path
        try: cached=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError): cached={}
        try:
            for _ in range(11):
                result=self.api.call('history','generation_sync',{k:v['revision'] for k,v in cached.items()})
                manifest=result['manifest']
                cached={k:v for k,v in cached.items() if k in manifest}
                for row in result['changed']: cached[row['day']]=dict(revision=row['revision'],summary=row['summary'])
                if all(cached.get(k,{}).get('revision')==v for k,v in manifest.items()): break
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(cached),encoding='utf-8');temp.replace(path)
        except Exception:
            if not cached: raise
        return cached
    def load_graph_day(self, day, source='Auto'): return self.api.call('history','graph_day',day,source)
    def month_accounting(self,anchor,source='Auto'):
        session=self.api.ensure_session()
        if 'energy.month.v1' not in session.get('capabilities',[]):return None
        return self.api.call('energy','month',anchor.isoformat(),source)
    def load_day(self, day, source='Auto'): return self.load_graph_day(day,source)
    def record(self, stamp, source='Auto'): return self.api.call('history','record',stamp,source)
    def available_dates(self, refresh=False): return self.api.call('history','available_dates',refresh)
    @staticmethod
    def numeric_fields(rows):
        from .history_reader import HistoryReader
        return HistoryReader.numeric_fields(rows)
    @staticmethod
    def coverage_percent(rows, max_gap_s=900):
        from .history_reader import HistoryReader
        return HistoryReader.coverage_percent(rows,max_gap_s)


class RemoteTariffs:
    def __init__(self, api): self.api=api
    def check_for_updates(self): return SimpleNamespace(**self.api.call('tariffs','check_for_updates'))


class RemoteArchive:
    def __init__(self, api):
        self.api=api; self.credentials=self
        self.history='server://history'
        self.listeners=[]
        self.running=False
        self._status_busy=False
    def add_listener(self, cb): self.listeners.append(cb)
    def load(self): return self.api.call('archive','load_credentials')
    def clear(self): return self.api.call('archive','clear_credentials')
    def status(self): return SimpleNamespace(**self.api.call('archive','status'))
    def publish_status(self):
        try:
            status=self.status()
            self.running=bool(status.running)
            for cb in self.listeners: cb(status)
        except Exception: pass
    def publish_status_async(self):
        if self._status_busy: return
        self._status_busy=True
        def work():
            try: self.publish_status()
            finally: self._status_busy=False
        threading.Thread(target=work, name='ArchiveStatus', daemon=True).start()
    def __getattr__(self, method):
        if method.startswith('_'): raise AttributeError(method)
        return lambda *a,**kw: self.api.call('archive',method,*a,**kw)
