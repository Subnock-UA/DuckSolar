from __future__ import annotations

import json
import re
import threading
import time
from uuid import uuid4
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .wire import encode, decode
from .config import save_config
from .client_sessions import ClientSessions, SessionError

STORAGE_METHODS = frozenset('get_current_meter_id list_meter_readings latest_meter_reading add_meter_reading replace_meter delete_meter_reading get_app_state set_app_state tariff_for_date upsert_tariff retail_tariff_for_date tax_rates_for_date upsert_retail_tariff_rates upsert_tax_rates finance_rates_for_date meter_month_delta available_finance_months'.split())
CONFIG_FIELDS = frozenset('lwip_ip local_server_port cloud_host cloud_port dtu_pn poll_interval_s socket_timeout_s local_retries cloud_proxy_enabled pv_correction_factor inverter_self_consumption_w max_integration_gap_s graph_line_width pv_installed_kw weather_location_name weather_latitude weather_longitude weather_days weather_timeout_s graph_colors log_columns show_raw_parameters'.split())


class APIServer:
    def __init__(self, runtime):
        self.runtime = runtime
        self.sessions = ClientSessions(runtime)
        from .accounts import Accounts
        self.accounts = Accounts(runtime.cfg, runtime.logs)
        from .pairing import Pairing
        from .secure_channel import server_identity
        self.pairing=Pairing(server_identity(runtime.cfg)[2],runtime.logs)
        from .account_trust import AccountTrust
        self.account_trust=AccountTrust(self.accounts,self.pairing.pin)
        self.http = None
        self.thread = None
        self.stop_event = threading.Event()
        from .live_channels import LiveChannels
        self.live_channels = LiveChannels()
        self.history_lock = threading.RLock()
        self.job_contexts = {}
        self.job_context_lock = threading.Lock()
        from .history_jobs import HistoryJobs
        self.jobs = HistoryJobs(runtime.cfg.root_dir, runtime.logs)
        from .energy_streaming import MonthAccounting
        self.month_accounting = MonthAccounting()
        self.history_views = {}
        self.cache_lock = threading.Lock()
        self.cache = {}
        self.queries = {}
        self.query_progress = {}
        self.query_lock = threading.Lock()
        from .history_reader import HistoryReader

    def call(self, domain, method, args, kwargs, client_id="", disconnected=None):
        r = self.runtime
        args=list(args); kwargs=dict(kwargs)
        if getattr(r,'maintenance_mode',False) and (domain in ('history','energy','archive','parameters','commands') or (domain=='storage' and method in ('add_meter_reading','replace_meter','delete_meter_reading'))):
            raise SessionError('Сервер обслуговує історію; поточні значення застарілі',503,'history.maintenance')
        if domain == 'devices':
            if method == 'list': return r.descriptors()
            if method == 'dictionary': return r.dictionary(args[0] if args else None)
            if method == 'state': return r.device_snapshot(r.device(args[0] if args else None))
        if domain=='energy' and method=='audit_page':
            device=r.device(kwargs.pop('device_id',None))
            if len(args)!=1 or set(kwargs)-{'source','audit_id','offset','limit'}:raise ValueError('Invalid audit arguments')
            return self.month_accounting.audit_page(device.cfg,*args,device_id=device.definition.id,**kwargs)
        if (domain == 'energy' and method == 'month_compact') or (domain == 'history' and method in ('graph_data','graph_day','generation_sync','month_series','energy_period','insights_data','job_start','job_status','job_result','job_cancel')):
            device = r.device(kwargs.pop('device_id',None))
            if method in ('job_status','job_result','job_cancel'):
                if len(args)!=1 or kwargs: raise ValueError('Invalid job arguments')
                action={'job_status':self.jobs.status,'job_result':self.jobs.result,'job_cancel':self.jobs.cancel}[method]
                return action(client_id,args[0],device.definition.id)
            asynchronous = method=='job_start'
            if asynchronous:
                if len(args)!=1 or not isinstance(args[0],dict) or kwargs: raise ValueError('Invalid job request')
                spec=dict(args[0]); domain=spec.get('domain','history');method=spec.get('method','graph_data')
                args=spec.get('args',[]);kwargs=dict(spec.get('kwargs',{}))
                if 'device_id' in kwargs: raise ValueError('Device must be selected outside job specification')
            query_id=kwargs.pop('query_id','')
            if query_id and (not isinstance(query_id,str) or not re.fullmatch('[0-9a-f]{32}',query_id)): raise ValueError('Invalid query ID')
            if domain=='energy' and method=='month_compact':
                if len(args)!=1 or set(kwargs)-{'source','now'}:raise ValueError('Invalid balance arguments')
                kind='balance'
            elif domain=='history' and method in ('graph_data','graph_day','generation_sync','month_series','energy_period','insights_data'):
                import inspect
                from .history_views import HistoryViews
                bound=inspect.signature(getattr(HistoryViews,method)).bind(None,*args,**kwargs)
                if set(bound.arguments)&{'cancelled','progress'}:raise ValueError('Reserved job arguments')
                kind='graph'
            else:raise ValueError('Unsupported history job')
            spec=dict(domain=domain,method=method,args=args,kwargs=kwargs)
            def calculate(cancelled,progress):
                from .history_reader import HistoryReader
                from .history_views import HistoryViews
                from .resource_manager import operation
                # Graphs and balances have independent readers and mutable caches.
                import copy
                snapshot_cfg=copy.deepcopy(device.cfg)
                context_key=(device.definition.id,kind,threading.get_ident(),HistoryReader(snapshot_cfg).model_signature())
                with self.job_context_lock:
                    context=self.job_contexts.get(context_key)
                    if context is None:
                        # A worker owns its reader/view; no mutable state crosses threads.
                        context=(HistoryReader(snapshot_cfg),None)
                        context=(context[0],HistoryViews(context[0],snapshot_cfg,device.definition.id,r.logs))
                        self.job_contexts={k:v for k,v in self.job_contexts.items() if k[2]!=context_key[2]}
                        self.job_contexts[context_key]=context
                    reader,view=context
                    reader.cfg=snapshot_cfg;view.cfg=snapshot_cfg
                with operation(None,{device.definition.id:view},domain+'.'+method,logs=r.logs,keep_cache=True):
                    if cancelled():raise ValueError('History query cancelled')
                    if method=='insights_data' and args and args[0] in ('forecast_stats','forecast_live','charge_plan','battery'):
                        feature=args[0];anchor=args[1];analytics=r.forecast.analytics
                        if feature=='forecast_stats':return analytics.accuracy(device.definition.id,reader,cancelled,progress,anchor)
                        if feature=='forecast_live':return analytics.live(device.definition.id,reader,cancelled)
                        if feature=='charge_plan':return analytics.plan(device.definition.id,reader,cancelled,refresh=True)
                        return r.battery_ledger.history.query(device.definition.id,anchor,kwargs.get('period','day'),cancelled)
                    if kind=='balance':
                        from .energy_streaming import MonthAccounting
                        return MonthAccounting(self.stop_event).report(reader,r.storage,snapshot_cfg,*args,
                            device_id=device.definition.id,cancelled=cancelled,progress=progress,**kwargs)
                    options=dict(kwargs)
                    options.update(cancelled=cancelled,progress=progress)
                    if method=='insights_data' and args and args[0] in ('report','forecast'):
                        location=r.forecast.analytics.weather(device.definition.id).get('location',{})
                        reader._forecast_location=(location.get('latitude',snapshot_cfg.weather_latitude),location.get('longitude',snapshot_cfg.weather_longitude))
                    started=time.perf_counter()
                    result=getattr(view,method)(*args,**options)
                    stages={'history_s':round(time.perf_counter()-started,4)}
                    started=time.perf_counter()
                    if method=='insights_data' and args and args[0] in ('report','forecast'):
                        if result.get('period')=='day':r.forecast.analytics.attach_day(device.definition.id,reader,result,args[1],args[2] if len(args)>2 else 'Auto',cancelled)
                        else:result.update(forecast_analysis_version=2,forecast_note='Похибка прогнозу оцінюється за окремими завершеними добами у статистиці7/30днів')
                    stages['forecast_s']=round(time.perf_counter()-started,4)
                    started=time.perf_counter()
                    from .energy_accounting import meter_segments,stamp
                    summary=(result.get('energy_summary') or result.get('summary')) if isinstance(result,dict) else None
                    if summary and summary.get('start'):
                        readings=r.storage.list_meter_readings(limit=100000)
                        result['house_meter']=meter_segments(readings,stamp(summary['start']),stamp(summary['end']))
                        if result.get('other_summary'):
                            other=result['other_summary'];result['other_house_meter']=meter_segments(readings,stamp(other['start']),stamp(other['end']))
                    stages['meter_s']=round(time.perf_counter()-started,4)
                    result.setdefault('diagnostics',{}).update(stages)
                    return result
            job=self.jobs.start(client_id,device.definition.id,kind,spec,calculate,query_id)
            if asynchronous:return job
            return self.jobs.wait_legacy(client_id,job['job_id'],230 if kind=='balance' else 110,disconnected)
        if domain == 'finance' and method == 'view':
            return r.finance.view(*args, **kwargs)
        if domain == 'storage' and method in STORAGE_METHODS:
            from .meter import MeterValues
            if method == 'add_meter_reading':
                if len(args) > 1: args[1] = MeterValues(**args[1])
                if 'values' in kwargs: kwargs['values'] = MeterValues(**kwargs['values'])
            if method == 'replace_meter':
                for i in (1,2):
                    if len(args)>i: args[i] = MeterValues(**args[i])
                for key in ('old_final', 'new_initial'):
                    if key in kwargs: kwargs[key] = MeterValues(**kwargs[key])
            return getattr(r.storage, method)(*args, **kwargs)
        if domain == 'history' and method == 'record':
            device_id=kwargs.pop('device_id',None)
            stamp=args[0]
            with self.history_lock:
                rows=r.device(device_id).history.load_day(stamp.date(), args[1] if len(args)>1 else 'Auto')
                return next((row for row in rows if row['timestamp']==stamp), {})
        if domain == 'history' and method in ('load_day', 'available_dates'):
            device_id=kwargs.pop('device_id',None)
            with self.history_lock: return getattr(r.device(device_id).history, method)(*args, **kwargs)
        if domain == 'history' and method == 'query_status':
            return self.jobs.query_status(client_id,args[0] if args else '')
        if domain == 'history' and method == 'cancel':
            ident = args[0] if args else ''
            with self.query_lock:
                flag = self.queries.get((client_id, ident))
                if flag: flag.set()
            self.jobs.cancel_query(client_id,ident)
            return True
        if domain == 'tariffs' and method in ('check_for_updates','status','history'):
            return getattr(r.tariffs, method)(*args, **kwargs)
        if domain == 'archive':
            if method == 'inventory':
                return self.cached('archive.inventory',30,lambda:r.archive.inventory(*args,**kwargs))
            if method in ('inventory','status','save_credentials','test_credentials','start_download','stop'):
                return getattr(r.archive, method)(*args, **kwargs)
            if method == 'load_credentials': return r.archive.credentials.load()
            if method == 'clear_credentials': return r.archive.credentials.clear()
        if domain == 'monitor' and method == 'refresh_parameters':
            r.device(kwargs.pop('device_id',None)).parameters.request_refresh(); return True
        if domain == 'monitor' and method == 'redirect':
            raise SessionError('Перезапуск з’єднання доступний лише локально', 403, 'auth.local_only')
        if domain == 'config' and method == 'update':
            raise SessionError('Налаштування Server змінюються лише в його локальній оболонці', 403, 'auth.local_only')
        raise ValueError('Unsupported API operation')

    def allowed_device(self, account, ident=None):
        grants = [d for d in account['grants'] if d in self.runtime.devices]
        ident = ident or (self.runtime.primary_id if self.runtime.primary_id in grants else (grants[0] if grants else None))
        if ident not in grants:
            raise SessionError('Акаунт не має доступу до цього інвертора', 403, 'auth.device_denied')
        return ident

    def account_snapshot(self, account, client_id=''):
        state = self.runtime.snapshot()
        state['devices'] = {k:v for k,v in state['devices'].items() if k in account['grants']}
        primary = self.allowed_device(account)
        state.update(state['devices'][primary])
        state['primary_device_id'] = primary
        loggers = {dev['descriptor']['logger_id'] for dev in state['devices'].values()}
        state['loggers'] = {k:v for k,v in state['loggers'].items() if k in loggers}
        state.pop('firewall', None); state.pop('network', None)
        if client_id:
            state['notifications']=self.runtime.push_alerts.feed(account['username'],client_id,account['grants'])
        return state

    def cached(self,key,ttl,producer):
        with self.cache_lock:
            cached=self.cache.get(key)
            if cached and time.monotonic()-cached[0]<ttl: return cached[1]
            value=producer(); self.cache[key]=(time.monotonic(),value)
            return value

    @staticmethod
    def validate_config(changes):
        import math
        ranges = {'local_server_port':(1,65535), 'cloud_port':(1,65535),
                  'poll_interval_s':(5,5), 'socket_timeout_s':(1,60), 'local_retries':(1,10),
                  'pv_correction_factor':(.5,1.5), 'inverter_self_consumption_w':(0,1000),
                  'max_integration_gap_s':(30,86400), 'graph_line_width':(.5,6),
                  'pv_installed_kw':(.1,1000), 'weather_days':(1,10), 'weather_timeout_s':(2,60),
                  'weather_latitude':(-90,90), 'weather_longitude':(-180,180)}
        for k,v in changes.items():
            if k in ranges:
                if v is None and k in ('weather_latitude','weather_longitude'): continue
                lo,hi = ranges[k]
                if k in ("local_server_port","cloud_port","local_retries","weather_days","max_integration_gap_s") and not isinstance(v,int):
                    raise ValueError("Expected integer: "+k)
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo <= v <= hi:
                    raise ValueError('Invalid value for ' + k)
            elif k in ('cloud_proxy_enabled','show_raw_parameters'):
                if not isinstance(v,bool): raise ValueError('Expected boolean: '+k)
            elif k == 'graph_colors':
                if not isinstance(v,dict) or any(not isinstance(c,str) or len(c)!=7 or c[0]!='#' or any(x not in '0123456789abcdefABCDEF' for x in c[1:]) for c in v.values()):
                    raise ValueError('Invalid graph colors')
            elif k == 'log_columns':
                if not isinstance(v,list) or len(v)>100 or any(not isinstance(x,str) for x in v): raise ValueError('Invalid columns')
            elif not isinstance(v,str) or not v or len(v)>255:
                raise ValueError('Invalid text: '+k)

    def start(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args): pass
            def setup(self):
                super().setup(); self.connection.settimeout(30)
            def output(self, status, data):
                raw = json.dumps(encode(data), ensure_ascii=False, allow_nan=False).encode('utf-8')
                compressed='gzip' in self.headers.get('Accept-Encoding','') and len(raw)>2048
                if compressed:
                    import gzip
                    raw=gzip.compress(raw,compresslevel=3)
                self.send_response(status)
                if compressed:self.send_header('Content-Encoding','gzip')
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store')
                self.end_headers(); self.wfile.write(raw); self.wfile.flush()
            def safe_output(self, status, data, context):
                try:
                    self.output(status, data)
                    return str(status)
                except OSError as exc:
                    self.close_connection = True
                    owner.runtime.logs.event(f'API client disconnected {context} error={type(exc).__name__}: {exc}')
                    return 'client_disconnected' 
            def client_address_label(self):
                return self.client_address[0]
            def authenticate(self, session=True):
                self.account = owner.accounts.authorize(self.headers.get('Authorization', ''))
                if session:
                    row = owner.sessions.touch(self.headers.get('X-DX-Client-ID', ''), self.headers.get('X-DX-Client-Session', ''))
                    if row.get('username') != self.account['username']:
                        raise SessionError('Сесія належить іншому акаунту', code='auth.denied')
                    return row
            def reject(self, exc):
                self.close_connection = True
                owner.runtime.logs.event('API authorization/session rejected', code=exc.code, address=self.client_address[0])
                self.safe_output(exc.status, dict(error=str(exc), error_code=exc.code), 'authorization')
            def do_GET(self):
                path = urlsplit(self.path).path
                supplied_id = self.headers.get('X-DX-Operation-ID', '')
                request_id = supplied_id if re.fullmatch(r'[0-9a-f]{32}', supplied_id) else uuid4().hex
                if path != '/api/v1/events':
                    owner.runtime.logs.event('API GET ' + path, code='api.operation.started', operation_id=request_id)
                started = time.monotonic()
                outcome = '200'
                try:
                    self.authenticate()
                    if path == '/api/v1/state': self.output(200, owner.account_snapshot(self.account,self.headers.get('X-DX-Client-ID','')))
                    elif path == '/api/v1/config':
                        values = {k:v for k,v in asdict(owner.runtime.cfg).items() if k in CONFIG_FIELDS}
                        values = {k:v for k,v in values.items() if k not in ('dtu_pn','lwip_ip','local_server_port','cloud_host','cloud_port','cloud_proxy_enabled')}
                        self.output(200, values)
                    elif path == '/api/v1/devices': self.output(200,[d for d in owner.runtime.descriptors() if d['device_id'] in self.account['grants']])
                    elif path == '/api/v1/dictionary':
                        ident=parse_qs(urlsplit(self.path).query).get('device_id',[None])[0]
                        ident = owner.allowed_device(self.account, ident)
                        self.output(200,owner.runtime.dictionary(ident))
                    elif path == '/api/v1/events': self.stream()
                    else:
                        outcome = '404'
                        self.output(404, {'error':'Unknown endpoint'})
                except SessionError as exc:
                    outcome = str(exc.status); self.reject(exc)
                except OSError as exc:
                    self.close_connection = True
                    outcome = 'client_disconnected'
                    owner.runtime.logs.event(f'API client disconnected GET {path} error={type(exc).__name__}: {exc}')
                except (ValueError,KeyError) as exc:
                    outcome = self.safe_output(400,{'error':str(exc),'error_code':'api.invalid_request'},path)
                except Exception:
                    owner.runtime.logs.exception('API GET failed',operation_id=request_id,operation='get.'+path)
                    outcome = self.safe_output(500,{'error':'Internal server error'},path)
                finally:
                    if path != '/api/v1/events':
                        owner.runtime.logs.event('API GET completed',code='api.operation.completed',operation_id=request_id,
                            operation='get.'+path,result=outcome,duration_ms=round((time.monotonic()-started)*1000,1))
            def stream(self):
                self.close_connection = True
                client_id=self.headers.get('X-DX-Client-ID','')
                key,channel=owner.live_channels.open(self.account['username'],client_id,self.connection)
                stream_id=uuid4().hex
                from .live_delta import Encoder
                delta=Encoder() if parse_qs(urlsplit(self.path).query).get('format')==['delta1'] else None
                policy=parse_qs(urlsplit(self.path).query).get('policy')==['idle1']
                mode='notifications' if policy and parse_qs(urlsplit(self.path).query).get('mode')==['notifications'] else 'telemetry'
                interval=5 if policy else 1
                last_sent=0.;previous_events=None;last_metrics=time.monotonic()
                if policy:owner.runtime.push_alerts.subscribe(channel['wake'])
                started=time.monotonic(); frames=0; sent_bytes=0; reason='server_stopping'; stage='headers'
                owner.runtime.logs.event('Client live channel connected',code='api.live.connected',stream_id=stream_id,client_id=client_id,live_format='delta1' if delta else 'full',mode=mode,interval_s=30 if mode=='notifications' else interval)
                try:
                    self.send_response(200); self.send_header('Content-Type','text/event-stream')
                    self.send_header('Cache-Control','no-cache'); self.send_header('Connection','close'); self.end_headers()
                    while not owner.stop_event.is_set() and not channel['cancelled'].is_set():
                        stage='authenticate'
                        self.authenticate()
                        sample_started=time.monotonic()
                        stage='snapshot'
                        channel['wake'].clear()
                        if mode=='notifications':
                            events=owner.runtime.push_alerts.feed(self.account['username'],client_id,self.account['grants'])
                            if frames and events==previous_events and time.monotonic()-last_sent<30:
                                channel['wake'].wait(max(0,30-(time.monotonic()-last_sent)));continue
                            from .live_idle import snapshot as idle_snapshot
                            state=idle_snapshot(owner,self.account,client_id)
                            previous_events=state['notifications']
                        else:state = owner.account_snapshot(self.account,client_id)
                        if policy:state['live_mode']=mode
                        snapshot_done=time.monotonic(); stage='serialize'
                        encoded=encode(state)
                        body = json.dumps({'live':'idle1','state':encoded} if mode=='notifications' else delta.packet(encoded) if delta else encoded, ensure_ascii=False, allow_nan=False,separators=(',',':'))
                        frame=('id: '+str(state['sequence'])+'\nevent: telemetry\ndata: '+body+'\n\n').encode('utf-8')
                        serialized=time.monotonic(); stage='write'
                        if channel['cancelled'].is_set() or owner.stop_event.is_set():break
                        self.wfile.write(frame)
                        self.wfile.flush()
                        finished=time.monotonic(); duration=finished-sample_started
                        frames+=1; sent_bytes+=len(frame);last_sent=time.monotonic()
                        if last_sent-last_metrics>=300:
                            last_metrics=last_sent
                            owner.runtime.logs.event('Live channel counters',code='api.live.metrics',stream_id=stream_id,mode=mode,frames=frames,sent_bytes=sent_bytes,duration_ms=round((last_sent-started)*1000,1))
                        if duration>2:owner.runtime.logs.event('Live sample delayed',code='api.live.delayed',stream_id=stream_id,
                            duration_ms=round(duration*1000,1),snapshot_ms=round((snapshot_done-sample_started)*1000,1),
                            serialize_ms=round((serialized-snapshot_done)*1000,1),write_ms=round((finished-serialized)*1000,1),frame_bytes=len(frame))
                        if mode!='notifications':channel['wake'].wait(interval)
                except (OSError, TimeoutError, SessionError) as error:
                    reason='authorization' if isinstance(error,SessionError) else 'transport'
                    owner.runtime.logs.event('Live channel ended',code='api.live.interrupted',stream_id=stream_id,stage=stage,
                        reason=channel['reason'] or reason,exception_class=type(error).__name__,errno=getattr(error,'errno',None))
                except (ValueError,TypeError) as error:
                    reason='serialization'
                    owner.runtime.logs.event('Live snapshot could not be serialized',code='api.live.serialization.failed',stream_id=stream_id,stage=stage,exception_class=type(error).__name__)
                finally:
                    if policy:owner.runtime.push_alerts.unsubscribe(channel['wake'])
                    owner.live_channels.release(key,channel)
                    owner.runtime.logs.event('Client live channel disconnected',code='api.live.disconnected',stream_id=stream_id,
                        reason=channel['reason'] or reason,mode=mode,frames=frames,sent_bytes=sent_bytes,duration_ms=round((time.monotonic()-started)*1000,1))
            def do_POST(self):
                supplied_id = self.headers.get('X-DX-Operation-ID', '')
                request_id = supplied_id if re.fullmatch(r'[0-9a-f]{32}', supplied_id) else uuid4().hex
                supplied_session = self.headers.get('X-DX-Client-Session', '')
                client_session = supplied_session if re.fullmatch(r'[0-9a-f]{32}', supplied_session) else ''
                started = time.monotonic()
                domain = method = '?'
                outcome = '500'
                balance_diagnostics=None
                context = f'id={request_id} POST {urlsplit(self.path).path}'
                owner.runtime.logs.event('API request ' + context, code='api.operation.started', operation_id=request_id, client_session_id=client_session)
                try:
                    auth_path = self.path.startswith('/api/v1/auth/')
                    if not auth_path: self.authenticate(session=self.path != '/api/v1/session')
                    if self.path not in ('/api/v1/data', '/api/v1/session', '/api/v1/auth/register', '/api/v1/auth/login', '/api/v1/auth/bind', '/api/v1/auth/logout', '/api/v1/auth/pair/start', '/api/v1/auth/pair/finish', '/api/v1/auth/trust/parameters', '/api/v1/auth/trust/start', '/api/v1/auth/trust/finish'):
                        status, response = 404, {'error':'Unknown endpoint'}
                    else:
                        try:
                            size = int(self.headers.get('Content-Length','0'))
                            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:raise ValueError('Unsupported request framing')
                            if not 0 < size <= (4096 if auth_path else 2*1024*1024): raise ValueError('Invalid request size')
                            raw = self.rfile.read(size)
                            if len(raw) != size: raise ConnectionAbortedError('Incomplete request body')
                        except OSError as exc:
                            outcome = 'client_disconnected'
                            self.close_connection = True
                            owner.runtime.logs.event(f'API client disconnected {context} error={exc}')
                            return
                        obj = decode(json.loads(raw))
                        if not isinstance(obj, dict): raise ValueError('Expected request object')
                        if auth_path:
                            if self.path.endswith('/trust/parameters'):
                                result=owner.account_trust.parameters(obj.get('username'),self.client_address_label())
                            elif self.path.endswith('/trust/start'):
                                result=owner.account_trust.start(obj.get('username'),obj.get('message'),self.client_address_label())
                            elif self.path.endswith('/trust/finish'):
                                result=owner.account_trust.finish(obj.get('id'),obj.get('proof'),self.client_address_label())
                            elif self.path.endswith('/pair/start'):
                                result=owner.pairing.start(obj.get('message'),self.client_address_label())
                            elif self.path.endswith('/pair/finish'):
                                result=owner.pairing.finish(obj.get('id'),obj.get('proof'),self.client_address_label())
                            elif self.path.endswith('/register'):
                                if not owner.runtime.cfg.registration_enabled:raise SessionError('Реєстрацію вимкнено власником Server',403,'auth.registration_disabled')
                                if not owner.pairing.ticket_valid(obj.get('trust_ticket'),self.client_address_label()):
                                    raise SessionError('Для реєстрації потрібен код Server',403,'auth.first_trust_required')
                                result = owner.accounts.register(obj.get('username'), obj.get('password'), self.client_address_label())
                            elif self.path.endswith('/login'):
                                ticket=obj.get('trust_ticket')
                                trusted=owner.pairing.ticket_valid(ticket,self.client_address_label())
                                result=owner.accounts.login(obj.get('username'),obj.get('password'),self.client_address_label(),trusted=trusted)
                                if trusted:owner.pairing.ticket_valid(ticket,self.client_address_label(),consume=True)
                            elif self.path.endswith('/logout'): result = owner.accounts.logout(self.headers.get('Authorization',''))
                            else: result = owner.accounts.bind(self.headers.get('Authorization',''), obj.get('serial'), owner.runtime, self.client_address_label())
                            status, response = 200, result
                            return
                        if self.path == '/api/v1/session':
                            obj['username'] = self.account['username']
                            status, response = 200, owner.sessions.open(obj, self.client_address_label())
                            return
                        domain, method = obj.get('domain'), obj.get('method')
                        if not isinstance(domain,str) or not isinstance(method,str) or len(domain)>64 or len(method)>64:
                            raise ValueError('Invalid operation name')
                        context += f' operation={domain}.{method}'
                        targets = {}
                        args = obj.get('args',[])
                        if domain == 'finance' and method == 'view' and len(args)>=2:
                            targets = dict(year=args[0],month=args[1])
                        elif domain == 'storage' and method in ('add_meter_reading','replace_meter','upsert_tariff','upsert_retail_tariff_rates','upsert_tax_rates') and args:
                            targets = dict(effective_date=str(args[0]))
                        elif domain == 'storage' and method == 'delete_meter_reading' and args:
                            targets = dict(reading_id=args[0])
                        elif domain == 'history' and method == 'load_day' and args:
                            targets = dict(day=str(args[0]),source=str(args[1]) if len(args)>1 else 'Auto')
                        if targets:
                            owner.runtime.logs.event('API operation target',code='api.operation.target',operation_id=request_id,
                                operation=domain+'.'+method,**targets)
                        kwargs = obj.get('kwargs', {})
                        if not isinstance(args, list) or not isinstance(kwargs, dict): raise ValueError('Invalid arguments')
                        if domain=='diagnostics' and method=='preview':
                            if args or kwargs:raise ValueError('Invalid diagnostics arguments')
                            from .diagnostics import build_bundle
                            grants=self.account['grants']
                            states=[owner.runtime.device_snapshot(dev) for ident,dev in owner.runtime.devices.items() if ident in grants]
                            from .config import VERSION
                            status,response=200,{'result':build_bundle(states,VERSION,events=owner.runtime.event_journal.recent(grants))}
                            return
                        if domain=='insights':
                            ident=owner.allowed_device(self.account,kwargs.pop('device_id',None));user=self.account['username']
                            if kwargs:raise ValueError('Invalid insights arguments')
                            service=owner.runtime.insights
                            if method=='battery_config' and len(args)<=1:invoke=lambda:service.config(ident,*args)
                            elif method=='battery' and not args:invoke=lambda:owner.runtime.device_snapshot(owner.runtime.device(ident))['battery']
                            elif method=='battery_anchor' and not args:raise ValueError('SOC надходить від БМС. Ручне встановлення заряду не використовується.')
                            elif method=='forecast_status' and not args:invoke=lambda:owner.runtime.forecast.status(ident)
                            elif method=='forecast_settings' and len(args)<=1:invoke=lambda:owner.runtime.forecast.settings(ident,*args)
                            elif method=='forecast_start' and len(args)<=1:invoke=lambda:owner.runtime.forecast.start(ident,*args)
                            elif method=='forecast_cancel' and not args:invoke=lambda:owner.runtime.forecast.cancel(ident)
                            elif method=='pv_correction' and len(args)<=1:invoke=lambda:service.pv_config(ident,*args)
                            elif method=='night_charge' and len(args)<=1:invoke=lambda:owner.runtime.night_charge.config(ident,user,*args)
                            elif method=='commands' and not args:invoke=lambda:service.commands(ident,user)
                            elif method=='profiles' and len(args)<=3:invoke=lambda:service.profiles(ident,user,*args)
                            elif method=='delete_profile' and len(args)==1:invoke=lambda:service.profiles(ident,user,args[0],delete=True)
                            elif method=='preview_profile' and len(args)==1:invoke=lambda:service.preview(ident,user,args[0])
                            elif method=='profile_status' and len(args)==1:invoke=lambda:service.job(ident,user,args[0])
                            elif method=='apply_profile' and len(args)==2:
                                header=self.headers.get('Authorization')
                                def authorize_profile():owner.allowed_device(owner.accounts.authorize(header),ident)
                                invoke=lambda:service.apply(ident,user,*args,authorize_profile)
                            else:raise ValueError('Unsupported insights operation')
                            mutation=method in ('apply_profile','delete_profile','battery_anchor','forecast_start','forecast_cancel') or method in ('battery_config','profiles','night_charge','pv_correction','forecast_settings') and bool(args)
                            result=owner.sessions.perform(self.headers.get('X-DX-Client-ID',''),request_id,raw,invoke) if mutation else invoke()
                            status,response=200,{'result':result};return
                        if domain in ('parameters','pv'):
                            ident=owner.allowed_device(self.account,kwargs.pop('device_id',None))
                            if domain=='pv':
                                from .pv_profiles import profile,update
                                identity=owner.runtime.device(ident).driver.identity(owner.runtime.device(ident).parameters.snapshot()['raw'])
                                if method=='get':invoke=lambda:profile(owner.runtime.cfg,ident,identity)
                                elif method=='update':
                                    if len(args)!=2 or kwargs:raise ValueError('Invalid PV arguments')
                                    invoke=lambda:update(owner.runtime.cfg,ident,args[0],args[1],identity,owner.runtime.logs,self.account['username'])
                                else:raise ValueError('Unsupported PV operation')
                            elif method=='submit':
                                if len(args)!=3 or kwargs:raise ValueError('Invalid command arguments')
                                header=self.headers.get('Authorization')
                                def authorize_write():owner.allowed_device(owner.accounts.authorize(header),ident)
                                invoke=lambda:owner.runtime.commands.submit(ident,*args,self.account['username'],authorize_write)
                            elif method=='status':
                                if len(args)!=1 or kwargs:raise ValueError('Invalid command arguments')
                                invoke=lambda:owner.runtime.commands.status(args[0],self.account['username'],ident)
                            else:raise ValueError('Unsupported command operation')
                            if method in ('submit','update'):
                                result=owner.sessions.perform(self.headers.get('X-DX-Client-ID',''),request_id,raw,invoke)
                            else:result=invoke()
                            status,response=200,{'result':result}
                            return
                        if domain=='energy' and method=='month':
                            raise ValueError('Місячний баланс тимчасово недоступний у a1.0.1 до оптимізації пам’яті')
                        if domain in ('history','monitor','devices','energy'):
                            ident = kwargs.get('device_id')
                            if domain == 'devices': ident = args[0] if args else None
                            ident = owner.allowed_device(self.account, ident)
                            if domain == 'devices': args = [ident] if method in ('dictionary','state') else args
                            else: kwargs['device_id'] = ident
                        if domain == 'notifications':
                            owner.allowed_device(self.account)
                            if kwargs:raise ValueError('Invalid notification arguments')
                            identity=self.headers.get('X-DX-Client-ID','')
                            if method=='settings' and len(args)<=1:
                                result=owner.runtime.push_alerts.settings(self.account['username'],identity,self.account['grants'],args[0] if args else None)
                            elif method=='ack' and len(args)==1:
                                result=owner.runtime.push_alerts.acknowledge(self.account['username'],identity,args[0])
                            else:raise ValueError('Unsupported notification operation')
                            status,response=200,{'result':result}
                            return
                        if domain == 'events' and method == 'list':
                            status,response=200,{'result':owner.runtime.event_journal.recent(self.account['grants'],profiles={k:owner.runtime.device_snapshot(v).get('descriptor',{}).get('profile_confirmed',False) for k,v in owner.runtime.devices.items() if k in self.account['grants']})}
                            return
                        if domain == 'devices' and method == 'list':
                            status, response = 200, {'result':[d for d in owner.runtime.descriptors() if d['device_id'] in self.account['grants']]}
                            return
                        mutation = (domain == 'config' or (domain == 'storage' and method.startswith(('add_', 'replace_', 'delete_', 'upsert_', 'set_'))) or (domain == 'archive' and method in ('save_credentials', 'clear_credentials', 'start_download', 'stop')))
                        def disconnected():
                            import select,socket
                            if not select.select([self.connection],[],[],0)[0]:return False
                            timeout=self.connection.gettimeout()
                            try:
                                self.connection.settimeout(.001)
                                return self.connection.recv(1)==b''
                            except (socket.timeout,BlockingIOError):return False
                            except OSError:return True
                            finally:self.connection.settimeout(timeout)
                        job_owner=self.account['username']+'|'+self.headers.get('X-DX-Client-ID','')
                        invoke = lambda: owner.call(domain, method, args, kwargs, job_owner,disconnected)
                        result = owner.sessions.perform(self.headers.get('X-DX-Client-ID', ''), request_id, raw, invoke) if mutation else invoke()
                        if domain=='energy' and method=='month_compact' and isinstance(result,dict):balance_diagnostics=result.get('diagnostics')
                        status, response = 200, {'result':result}
                except SessionError as exc:
                    status, response = exc.status, dict(error=str(exc), error_code=exc.code)
                    self.close_connection = True
                except (ValueError, TypeError, KeyError) as exc:
                    status, response = 400, {'error':str(exc)}
                except Exception as exc:
                    owner.runtime.logs.exception(f'API operation error {context}', operation_id=request_id, operation=domain+'.'+method)
                    status, response = 500, {'error':'Внутрішня помилка Server','error_code':'api.internal'}
                finally:
                    # The response must remain outside the operation exception
                    # handler: an aborted write is not a second API operation.
                    if outcome != 'client_disconnected':
                        try: outcome = self.safe_output(status, response, context)
                        except Exception as exc:
                            self.close_connection = True
                            outcome = 'response_error'
                            owner.runtime.logs.event(f'API response error {context}: {exc}')
                    elapsed = (time.monotonic()-started)*1000
                    owner.runtime.logs.event(f'API completed {context} result={outcome} duration_ms={elapsed:.1f}', code='api.operation.completed', operation_id=request_id, client_session_id=client_session, operation=domain+'.'+method, result=outcome, duration_ms=round(elapsed,1),balance=balance_diagnostics,error_code=response.get('error_code'))
            def do_PUT(self): self.output(405, {'error':'Method not allowed'})
            def do_DELETE(self): self.output(405, {'error':'Method not allowed'})
        import ipaddress
        ipaddress.ip_address(self.runtime.cfg.api_host)
        from .secure_channel import server_context
        context, self.fingerprint = server_context(self.runtime.cfg)
        slots = threading.BoundedSemaphore(64)
        class SecureHTTPServer(ThreadingHTTPServer):
            def handle_error(server, request, address):
                owner.runtime.logs.event('HTTP connection aborted', code='api.connection.closed', address=address[0])
            def process_request(server, request, address):
                if not slots.acquire(blocking=False):
                    server.shutdown_request(request); return
                try: super().process_request(request, address)
                except Exception:
                    slots.release(); raise
            def process_request_thread(server, request, address):
                secured = request
                handshake_started=time.monotonic();transport_id=uuid4().hex
                try:
                    request.settimeout(5)
                    secured = context.wrap_socket(request, server_side=True)
                    owner.runtime.logs.event('TLS connected',code='api.tls.connected',connection_id=transport_id,stage='tls',address=address[0],duration_ms=round((time.monotonic()-handshake_started)*1000,1),tls=secured.version())
                    super().process_request_thread(secured, address)
                except OSError as error:
                    owner.runtime.logs.event('TLS/transport disconnected',code='api.tls.failed',connection_id=transport_id,stage='tls',address=address[0],exception_class=type(error).__name__,errno=getattr(error,'errno',None),duration_ms=round((time.monotonic()-handshake_started)*1000,1))
                    server.shutdown_request(secured)
                finally: slots.release()
        self.http = SecureHTTPServer((self.runtime.cfg.api_host, self.runtime.cfg.api_port), Handler)
        self.http.daemon_threads = True
        self.thread = threading.Thread(target=self.http.serve_forever, name='LocalAPI', daemon=True)
        self.thread.start()
        self.runtime.logs.event(f'API started: {self.runtime.cfg.api_host}:{self.http.server_port}', code='api.started', tls='TLSv1.3')

    def stop(self):
        self.stop_event.set()
        self.live_channels.stop()
        self.jobs.stop()
        with self.job_context_lock:
            self.job_contexts.clear()
        if self.http:
            self.http.shutdown(); self.http.server_close()
            self.runtime.logs.event('API stopped')
        if self.thread: self.thread.join(timeout=3)
