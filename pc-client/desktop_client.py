"""Android Client transport; reuse verified PC SPAKE2/TLS/session code."""
import json,threading,time,uuid,os,zlib,ssl,http.client
from urllib.parse import urlsplit
from ducksolar.tls_transport import PinnedConnection
from pathlib import Path
from ducksolar.remote import ServerAPI,LiveConnection
from ducksolar.tls_transport import SecureTransport
from ducksolar.client_transport import TransportError
from ducksolar.pairing_client import pair_server
from ducksolar.wire import encode
from ducksolar.forecast_contract import has_server_analysis
_lock=threading.RLock();_log_lock=threading.Lock();_root=None;_api=None;_live=None;_last={};_cfg={};_error='';_auth_required=False
from ducksolar.route_policy import RoutePolicy
from ducksolar.config import VERSION, DISPLAY_VERSION
_routes=RoutePolicy();_route_attempt=0;_route_started=0.0
_network_available=True
_wifi_available=False;_network_id="";_lan_check_at=0.;_manual_until=0.;_snapshot_saved_at=0.
_repeat_lock=threading.Lock();_repeats={}
_foreground=False
notification_signal=threading.Event()
_health_lock=threading.Lock();_health={'disconnects':0,'route_failures':0}

def _repeat_note(code,details=None,message='',route=''):
 now=time.monotonic()
 with _repeat_lock:
  key=(code,(details or {}).get('error_code',''),message)
  count,last=_repeats.get(key,(0,0));count+=1
  emit=count<=3 or count&(count-1)==0 or now-last>=60
  if len(_repeats)>64:_repeats.clear()
  _repeats[key]=(count,now if emit else last)
 if emit:_note(code,route=route,details=dict(details or {},repeat_count=count),message=message)

class ClientLogs:
 def __init__(self,route=''):self.route=route
 def event(self,message='',code='client.event',**details):
  safe={k:v for k,v in details.items() if k in ('result','retry_s','error_code','failure_count','payload_bytes','json_position','server_session_id','client_id')}
  if code=='client.disconnected':
   _health_event(code,self.route,safe)
   _repeat_note(code,safe,message,route=self.route)
  else:_note(code,route=self.route,details=safe,message=message)
 def exception(self,message='',**details):self.event(message,code='client.exception',**details)

class DesktopTransport(SecureTransport):
 LIMIT=4*1024*1024
 def configure_live(self,session):
  self.live_delta='live.delta.v1' in session.get('capabilities',[])
  self.idle_live='live.idle.v1' in session.get('capabilities',[])
  self.live_mode='telemetry' if _foreground else 'notifications'
  self.live_stale_s=(75 if self.live_mode=='notifications' else 15) if self.idle_live else 5
 def network_available(self):return _network_available
 def request(self,path,body=None,headers=None,timeout=5):
  # Do not request compression; bound both normal and compressed responses.
  with self.open(path,body,headers,timeout) as reply:
   raw=reply.read(self.LIMIT+1)
   if len(raw)>self.LIMIT:raise ValueError('Відповідь Server перевищує ліміт клієнта')
   if reply.headers.get('Content-Encoding')=='gzip':
    inflater=zlib.decompressobj(16+zlib.MAX_WBITS);raw=inflater.decompress(raw,self.LIMIT+1)
    if len(raw)>self.LIMIT or inflater.unconsumed_tail or not inflater.eof:raise ValueError('Розпакована відповідь перевищує ліміт')
   return json.loads(raw)
 def frame_received(self,state):
  if state.get('notifications'):
   _repeat_note('notifications.frame.received',details={'count':len(state['notifications'])})
   notification_signal.set()
 def events(self,headers,stop_event,opened):
  from ducksolar.live_events import messages
  from ducksolar.live_delta import Decoder
  decoder=Decoder()
  path='events?format=delta1' if getattr(self,'live_delta',False) else 'events'
  if getattr(self,'idle_live',False):path+='&policy=idle1&mode='+self.live_mode
  with self.open(path,headers=headers,timeout=5) as response:
   opened(response)
   try:response.fp.raw._sock.settimeout(75 if getattr(self,"idle_live",False) else 15)
   except AttributeError:pass
   for obj in messages(response,stop_event,self.LIMIT):
    try:
     if obj.get('live')=='idle1':
      if not getattr(self,'idle_live',False) or obj.get('state',{}).get('live_mode')!='notifications':raise ValueError('Unexpected idle frame')
      yield obj['state']
     else:yield decoder.accept(obj)
    except (ValueError,KeyError,TypeError) as exc:
     raise TransportError('Потрібне повторне отримання повного стану',0,'live.invalid') from exc

def network_state(available,wifi=None,network_id=''):
 global _network_available,_wifi_available,_network_id
 changed=_network_available!=bool(available) or (wifi is not None and _wifi_available!=bool(wifi)) or (network_id and _network_id!=network_id)
 _network_available=bool(available)
 if wifi is not None:_wifi_available=bool(wifi)
 if network_id:_network_id=network_id
 if changed:
  _routes.network_changed();_note('network.available' if available else 'network.unavailable')
  live=_live
  if live and available:
   live.wake_event.set()
   if not live.connected:live.recover_stale()
 return _network_available

def network_changed():
 with _lock:
  _note('network.route_changed')
 # Keep a stream that is actually delivering data. Lost sockets are recovered
 # by the same owner, not by a second forced route selection.
 return resume()


DEFAULT_LAN=''
DEFAULT_REMOTE=''
PROBE_TIMEOUT=1.5

def _health_event(code,route,details):
 with _health_lock:
  if code=='client.disconnected':
   _health['disconnects']+=1;_health['last_failure']={'time':time.time(),'route':route,'code':details.get('error_code','live.closed'),'retry_s':details.get('retry_s')}
  elif code=='route.failed':
   _health['route_failures']+=1;_health['last_failure']={'time':time.time(),'route':route,'code':details.get('error_code','connection.unreachable'),'stage':details.get('stage')}
  elif code=='route.connected':_health['last_connection']={'time':time.time(),'route':route,'duration_ms':details.get('duration_ms')}
  elif code in ('network.available','network.unavailable'):_health['last_network']={'time':time.time(),'available':code=='network.available'}

def connection_health():
 value=json.loads(snapshot())
 # Return only connection metadata. No addresses, identity, session or tokens.
 out={k:value.get(k) for k in ('connected','connection_state','connection_message','route','last_received_age_s')}
 state=value.get('state') or {}
 phone=state.get('server_phone') or {}
 out['server_phone']={k:phone[k] for k in ('battery_percent','external_power','wifi_connected','wifi_rssi_dbm','available','age_s') if k in phone}
 out['inverter_stale']=bool(state.get('stale',True));out['inverter_updated']=state.get('updated','')
 with _health_lock:out['history']=json.loads(json.dumps(_health))
 out.update(network_available=_network_available,wifi_available=_wifi_available,automatic=True,manual_priority_remaining_s=round(max(0,_manual_until-time.monotonic()),1))
 return json.dumps(out,ensure_ascii=False,allow_nan=False)

def _note(code,route='',details=None,message=''):
 if code!='client.disconnected':_health_event(code,route,details or {})
 if not _root:return
 try:
  with _log_lock:
   file=_root/'client-events.jsonl'
   if file.exists() and file.stat().st_size>=1024*1024:
    older=_root/'client-events.1.jsonl';file.replace(older)
   record={'time':time.time(),'code':code,'client_version':VERSION,'client_display_version':DISPLAY_VERSION,'route':route or ('local' if _api and getattr(_api,'url',None)==_cfg.get('lan') else 'remote' if _api else ''),'attempt_id':_route_attempt,**(details or {})}
   if message:record['message']=str(message)[:512]
   with file.open('a',encoding='utf-8') as out:out.write(json.dumps(record,ensure_ascii=False)+'\n')
 except OSError:pass

def initialize(path):
 global _root,_cfg
 with _lock:
  _root=Path(path);_root.mkdir(parents=True,exist_ok=True)
  from desktop.settings import load_connection
  _cfg=load_connection(_root,{'client_id':uuid.uuid4().hex,'lan':DEFAULT_LAN,'remote':DEFAULT_REMOTE})
 return json.dumps({'lan':_cfg.get('lan',''),'remote':_cfg.get('remote',''),'username':_cfg.get('username',''),'serial':_cfg.get('serial',''),'saved':bool(_cfg.get('token'))})

def _urls():return list(dict.fromkeys(u for u in (_cfg.get('lan',''),_cfg.get('remote','')) if u))

def _probe(url,pin):
 # A reachability/identity probe sends neither HTTP credentials nor pairing data.
 parts=urlsplit(url)
 DesktopTransport(url,pin) # validate URL even before unpaired TLS discovery
 if pin:conn=PinnedConnection(parts.netloc,pin,timeout=PROBE_TIMEOUT)
 else:
  context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.minimum_version=ssl.TLSVersion.TLSv1_3
  context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
  conn=http.client.HTTPSConnection(parts.netloc,context=context,timeout=PROBE_TIMEOUT)
 try:conn.connect()
 finally:conn.close()


def _save():
 from desktop.settings import save_connection
 save_connection(_root,_cfg)

def _auth(transport,method,body,token=''):
 headers={'Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 return transport.request('auth/'+method,json.dumps(body).encode(),headers,10)

def stop(reason="user_or_service_stop"):
 global _live,_last
 with _lock:
  live,_live=_live,None
  if live:
   _note('route.stream_closed',details={'reason':reason,'connection_state':getattr(live,'connection_state','unknown'),'age_s':round(max(0,time.monotonic()-live.last_received),1) if getattr(live,'last_received',0) else None})
   _last=live.snapshot();live.stop()
 return True

def lifecycle_event(event):
 global _foreground
 if event in ('foreground','background'):
  _foreground=event=='foreground';_note('lifecycle.'+event)
  with _lock:live=_live
  if live:live.change_mode('telemetry' if _foreground else 'notifications')

def _begin(url):
 global _api,_live,_error,_auth_required,_route_attempt,_route_started
 _route_attempt+=1;_route_started=time.monotonic();started=_route_started
 route='local' if url==_cfg.get('lan') else 'remote'
 _note('route.attempt',route,details={'stage':'session'})
 transport=DesktopTransport(url,_cfg['pin'])
 api=ServerAPI(url,access_key=_cfg['token'],client_id=_cfg['client_id'],transport=transport)
 api.connection_timeout_s=5
 candidate=None
 try:
  session=api.ensure_session()
  _note('route.stage',route,details={'stage':'first_frame','duration_ms':round((time.monotonic()-started)*1000,1)})
  if 'api.v3' not in session.get('capabilities',[]):raise ValueError('Server не підтримує потрібний API')
  # Never select a route based on a TCP/TLS-only probe. A valid fresh envelope
  # proves both session and live delivery. One lock owns all route attempts.
  candidate=LiveConnection(api,ClientLogs(route));candidate.state=dict(_last);candidate.start()
  deadline=started+12
  while not candidate.connected and time.monotonic()<deadline:
   if api.auth_error:raise api.auth_error
   if not _network_available:raise TransportError('Немає мережі',0,'connection.unreachable')
   candidate.stop_event.wait(.05)
  if not candidate.connected:raise TransportError('Не отримано актуальних даних від сервера',0,'connection.first_frame_timeout')
  stop('verified_route_switch')
  _api=api;_live=candidate;_error='';_auth_required=False;_routes.success(url)
  _cfg['notifications_pending']=True;_save()
  _note('route.connected',route,details={'stage':'first_frame','duration_ms':round((time.monotonic()-started)*1000,1)})
  return json.dumps({'connected':True,'url':url,'server_version':session['server_version']})
 except Exception as exc:
  if candidate:candidate.stop()
  _routes.failed(url)
  _note('route.failed',route,details={'stage':'first_frame' if candidate else 'session','duration_ms':round((time.monotonic()-started)*1000,1),'error_code':getattr(exc,'code',type(exc).__name__)})
  raise


def connect(lan,remote,username,password,serial,code,register=False):
 global _cfg,_error
 with _lock:
  urls=list(dict.fromkeys(u.strip() for u in (lan,remote) if u.strip()))
  if not urls:raise ValueError('Вкажіть HTTPS адресу Server')
  reuse=bool(_cfg.get('token')) and not password and not code.strip() and not register and username==_cfg.get('username') and serial==_cfg.get('serial')
  original=dict(_cfg);_cfg.update(lan=lan.strip(),remote=remote.strip())
  if reuse:
   try:out=resume(True);_save();return out
   except Exception:_save();raise
  if not password:raise ValueError('Для першого входу або завершеної сесії введіть пароль')
  failures=[]
  for url in urls:
   try:
    pin='' if code.strip() else _cfg.get('pin','')
    _probe(url,pin)
    ticket=''
    if code.strip():pin,ticket=pair_server(url,code,timeout=5)
    if not pin:raise ValueError('Створіть код підключення у Server')
    transport=DesktopTransport(url,pin)
    if register:_auth(transport,'register',dict(username=username,password=password,trust_ticket=ticket))
    login=_auth(transport,'login',dict(username=username,password=password,trust_ticket=ticket))
    token=login['token'];_auth(transport,'bind',dict(serial=serial),token)
    _cfg.update(username=username,serial=serial,pin=pin,token=token)
    out=_begin(url);_save();return out
   except TransportError as exc:
    failures.append(str(exc))
    if exc.status in (401,403):break
   except Exception as exc:failures.append(str(exc))
  _cfg=original;_error=failures[-1];raise ValueError(_error)

def resume(force=False):
 global _error,_auth_required
 with _lock:
  if not _network_available:return json.dumps({'connected':False,'waiting_network':True})
  if _live:_live.recover_stale()
  if not force and _live and _live.connected:
   _prefer_lan()
   _routes.success(_api.url)
   return json.dumps({'connected':True,'url':_api.url,'server_version':(_api.session or {}).get('server_version','')})
  if not _cfg.get('token'):return json.dumps({'connected':False})
  if _live and _api and _live.api.auth_error:
   _auth_required=True;raise ValueError(str(_live.api.auth_error))
  # Let the current stream finish its bounded recovery first. Repeated probes
  # must not create a second live owner or continually reset its retry delay.
  if not force and _live and _live.thread.is_alive() and _live.connection_state not in ('AUTH_REQUIRED','INCOMPATIBLE','STOPPED'):
   age=time.monotonic()-(_live.last_received or _route_started)
   if age<12:return json.dumps({'connected':False,'reconnecting':True,'url':_api.url})
   # Retry the last authenticated endpoint before assigning a real failure.
   # A mode transition or paused Android reader is not a failed remote route.
   stop("recovery_grace_expired")
  failures=[]
  if force:_routes.network_changed()
  urls=_routes.ordered(_urls())
  if not urls:return json.dumps({'connected':False,'reconnecting':True,'cooldown':True})
  for url in urls:
   try:return _begin(url)
   except TransportError as exc:
    if exc.status in (401,403) or exc.code in ('tls.identity_mismatch','tls.trust_required','api.incompatible'):
     _auth_required=True;_error='Авторизацію або довіру до сервера потрібно перевірити.'
     _note('auth.required',details={'status':exc.status,'reason':exc.code})
     raise ValueError(_error) from exc
    failures.append(str(exc))
   except Exception as exc:failures.append(str(exc))
  _auth_required=False;_error=failures[-1] if failures else 'Немає адреси Server'
  _repeat_note('route.unavailable',message=_error);raise ValueError(_error)


def snapshot():
 with _lock:
  live=_live
  if live:
   with live.lock:
    state=live.snapshot();connected=live.connected;connection_state=live.connection_state;error=live.last_error
  else:
   state=dict(_last);state.update(stale=True,connection='SERVER_DISCONNECTED')
   connected=False;connection_state='STOPPED';error=_error
  auth_required=_auth_required or connection_state=='AUTH_REQUIRED'
  if not _network_available:connected=False;connection_state='WAITING_NETWORK'
  elif live and time.monotonic()-live.last_received>live.fresh_limit():connected=False
  if auth_required:connection_state='AUTH_REQUIRED'
  if connection_state=='AUTH_REQUIRED':message='Потрібен вхід у свій акаунт'
  elif not _network_available:message='Немає мережевого підключення ПК. Очікування мережі…'
  elif not connected:message='Сервер недоступний. Автоматичне перепідключення…'
  elif state.get('stale') and state.get('telemetry_status') in ('delayed','awaiting'):message='Сервер підключено; очікування свіжих даних інвертора'
  elif state.get('stale'):message='Сервер підключено; дані інвертора недоступні або застарілі'
  else:message='Сервер підключено; дані актуальні'
  if connected and not state.get('stale'): _save_last_snapshot(state)
  return json.dumps(encode({'state':state,'connected':connected,'connection_state':connection_state,'connection_message':message,'last_received_age_s':round(max(0,time.monotonic()-live.last_received),1) if live and live.last_received else None,'error':_error if _auth_required else error,'route':'local' if _api and getattr(_api,'url',None)==_cfg.get('lan') else 'remote'}),ensure_ascii=False,allow_nan=False)

def _history_job(api,spec,query,kind,cancelled=lambda:False):
 with _lock:live=_live
 if live:
  with live.lock:
   maintenance=live.connected and live.snapshot().get('maintenance',{}).get('active')
  if maintenance:raise ValueError('Сервер обслуговує історію. Побудова стане доступною після завершення міграції.')
 from ducksolar.client_transport import TransportError
 profile=connection_profile();ident=None;missing_since=None;polls=0;fetches=0;received_started=time.monotonic()
 marker=_root/('history-'+kind+'-pending.json')
 request=encode(spec)
 try:
  saved=json.loads(marker.read_text(encoding='utf-8'))
  if saved.get('profile')==profile and saved.get('request')==request and time.time()-saved.get('at',0)<86400:
   query=saved['query'];ident=saved.get('job_id')
 except (OSError,ValueError,KeyError):pass
 def save():
  temp=marker.with_suffix('.tmp');temp.write_text(json.dumps(dict(profile=profile,request=request,query=query,job_id=ident,at=time.time())),encoding='utf-8');temp.replace(marker)
 save()
 while True:
  if kind=='weather' and cancelled():
   try:
    with _lock:active_api=_api
    if active_api is not None and ident:active_api.call('history','job_cancel',ident)
   except Exception:pass
   raise InterruptedError('Прогноз призупинено або скасовано')
  if profile!=connection_profile():raise ValueError('Сервер або акаунт змінився; отримання результату припинено')
  with _lock:current=_api
  try:
   if current is None:raise ConnectionError('Сервер недоступний')
   if ident is None:
    options=dict(spec.get('kwargs',{}));options['query_id']=query
    job=current.call('history','job_start',dict(spec,kwargs=options));ident=job['job_id'];save()
   if cancelled():
    current.call('history','job_cancel',ident);marker.unlink(missing_ok=True)
    raise InterruptedError('Розрахунок скасовано')
   job=current.call('history','job_status',ident);polls+=1;missing_since=None
   lock,value=(_graph_lock,_graph_job) if kind=='graph' else ((_weather_history_lock,_weather_history_job) if kind=='weather' else ((_feature_lock,_feature_state) if kind=='insights' else (_balance_lock,_balance_job)))
   with lock:value.update(job_id=ident,phase=job.get('stage',job['state']),done=job.get('done',0),total=job.get('total',0),queue_s=job.get('queue_s',0))
   if kind=='weather':
    from ducksolar import weather_client as weather
    weather.update('history',server_done=job.get('done',0),server_total=job.get('total',0))
   if job['state']=='completed':
    fetches+=1;result=current.call('history','job_result',ident)['result'];marker.unlink(missing_ok=True)
    timing=dict(getattr(getattr(current,'request_metrics',None),'last',{}),polls=polls,result_fetches=fetches,server_calculation_s=job.get('calculation_s'),server_queue_s=job.get('queue_s'),receive_total_s=round(time.monotonic()-received_started,3))
    with lock:value['client_diagnostics']=timing
    _note('history.received',details=dict(kind=kind,query_id=query,**timing));return result
   if job['state'] in ('cancelled','error'):
    marker.unlink(missing_ok=True);raise ValueError(job.get('error',job.get('error_code','Завдання припинено сервером')))
  except InterruptedError:
   raise
  except (ConnectionError,OSError) as exc:
   if isinstance(exc,TransportError) and getattr(exc,'code','')=='history.maintenance':
    raise ValueError('Сервер обслуговує історію; повторіть після завершення міграції') from exc
   if isinstance(exc,TransportError) and exc.status and exc.status<500:
    if exc.status==400:marker.unlink(missing_ok=True)
    raise
   missing_since=missing_since or time.monotonic()
   if time.monotonic()-missing_since>150:raise ConnectionError('Зв’язок не відновлено протягом 150 с; повторіть запит для перевірки збереженого завдання')
   lock,value=(_graph_lock,_graph_job) if kind=='graph' else ((_weather_history_lock,_weather_history_job) if kind=='weather' else ((_feature_lock,_feature_state) if kind=='insights' else (_balance_lock,_balance_job)))
   with lock:value.update(phase='reconnecting')
  time.sleep(1)

def compact_month(month,query_id='',api=None,source='Local'):
 from datetime import date
 anchor=date.fromisoformat(month+'-01')
 with _lock:
  api=api or _api
  if api is None:raise ValueError('Спочатку підключіть сервер')
 if 'energy.month.compact.v1' not in api.ensure_session().get('capabilities',[]):
  raise ValueError('Цей сервер ще не підтримує компактний місячний баланс')
 if source not in ('Local','SmartESS','Auto'):raise ValueError('Некоректне джерело історії')
 options={'source':source}
 if query_id:options['query_id']=query_id
 result=_history_job(api,dict(domain='energy',method='month_compact',args=[anchor],kwargs={'source':source}),query_id or uuid.uuid4().hex,'balance',lambda:_balance_job.get('state')=='cancelling')
 with _lock:
  if _balance_job.get('profile',connection_profile())!=connection_profile():raise ValueError('Сервер змінився; повторіть запит балансу')
 if result.get('schema')!='energy.month.compact.v1' or len(result.get('days',[]))>31:raise ValueError('Некоректний компактний баланс')
 if result.get('history_source',source)!=source:raise ValueError('Сервер повернув баланс іншого джерела')
 if not str(result.get('start','')).startswith(month+'-01') or any(not str(day.get('date','')).startswith(month+'-') for day in result.get('days',[])):
  raise ValueError('Сервер повернув баланс іншого періоду')
 return json.dumps(encode(result),ensure_ascii=False,allow_nan=False)

def meter_readings():
 with _lock:
  api=_api
  if api is None:raise ValueError('Спочатку підключіть сервер')
 rows=api.call('storage','list_meter_readings',limit=200)
 with _lock:
  if api is not _api:raise ValueError('Сервер змінився; повторіть запит')
 return json.dumps(encode(rows),ensure_ascii=False,allow_nan=False)

# One process-owned job survives Activity recreation without retaining any UI.
# A timeout never retries the expensive operation automatically.
_balance_lock=threading.RLock()
_balance_job={}
_balance_api=None

def balance_start(month,source='Local'):
 from datetime import date
 date.fromisoformat(month+'-01')
 if source not in ('Local','SmartESS','Auto'):raise ValueError('Некоректне джерело історії')
 global _balance_job,_balance_api
 with _balance_lock:
  if _balance_job.get('state') in ('running','cancelling'):return balance_status()
  with _lock:api=_api
  if api is None:raise ValueError('Спочатку підключіть сервер')
  query=uuid.uuid4().hex
  _balance_api=api
  _balance_job=dict(query_id=query,month=month,source=source,state='running',started=time.monotonic(),profile=connection_profile())
  _note('balance.started',details={'month':month,'source':source,'query_id':query})
  def run():
   try:
    result=json.loads(compact_month(month,query,api,source))
    with _balance_lock:
     if _balance_job.get('query_id')!=query:return
     if _balance_job.get('state')=='cancelling':_balance_job.update(state='cancelled')
     else:_balance_job.update(state='complete',report=result)
   except Exception as exc:
    with _balance_lock:
     if _balance_job.get('query_id')!=query:return
     cancelled=_balance_job.get('state')=='cancelling'
     _balance_job.update(state='cancelled' if cancelled else 'error',error=str(exc)[:512])
   finally:
    with _balance_lock:
     if _balance_job.get('query_id')!=query:return
     _balance_job['elapsed_s']=round(time.monotonic()-_balance_job['started'],2)
     _note('balance.finished',details={'month':month,'query_id':query,'state':_balance_job['state'],'elapsed_s':_balance_job['elapsed_s']})
  threading.Thread(target=run,name='ClientBalance',daemon=True).start()
  return balance_status()

def balance_status():
 with _balance_lock:
  job=dict(_balance_job)
  if job.get('state') in ('running','cancelling'):job['elapsed_s']=round(time.monotonic()-job['started'],2)
  if job and job.get('profile')!=connection_profile():
   job.pop('report',None)
   job.update(active=job.get('state') in ('running','cancelling'),state='error',error='Баланс належить попередньому серверу або акаунту. Дочекайтеся завершення попереднього запиту й оновіть баланс.')
  job.pop('started',None)
  job.pop('profile',None)
  return json.dumps(job,ensure_ascii=False,allow_nan=False)

def balance_cancel():
 with _balance_lock:
  if _balance_job.get('state')!='running':return balance_status()
  _balance_job['state']='cancelling';api=_balance_api;query=_balance_job['query_id']
 def cancel():
  try:
   api.call('history','job_cancel',_balance_job['job_id']) if _balance_job.get('job_id') else None
   _note('balance.cancel_requested',details={'query_id':query})
  except Exception:
   # Keep the job busy until the original request actually finishes.
   _note('balance.cancel_failed',details={'query_id':query})
 threading.Thread(target=cancel,name='ClientBalanceCancel',daemon=True).start()
 return balance_status()

def _read_api(domain,method,*args,**kwargs):
 with _lock:api=_api
 if api is None:raise ValueError('Спочатку підключіть сервер')
 result=api.call(domain,method,*args,**kwargs)
 with _lock:
  if api is not _api:raise ValueError('Підключення змінилося; повторіть запит')
 return result

def event_rows():
 rows=_read_api('events','list')
 if not isinstance(rows,list) or len(rows)>500:raise ValueError('Некоректний журнал подій')
 from ducksolar.event_details import enrich
 state=json.loads(snapshot()).get('state',{})
 active={(state.get('device_id'),'warnings.'+e['id']) for e in state.get('warning_events',[]) if 'id' in e} if not state.get('stale',True) and state.get('warnings_valid') else None
 return json.dumps(encode(enrich(rows,active)[-100:][::-1]),ensure_ascii=False,allow_nan=False)

_graph_lock=threading.RLock();_graph_job={'state':'idle'};_graph_cancel=threading.Event()
def graph_status(known_query=''):
 with _graph_lock:
  value=_graph_job
  if value.get('profile') and value['profile']!=connection_profile():return json.dumps(dict(state='idle'))
  if known_query and known_query==value.get('query_id') and value.get('state')=='complete':value={k:v for k,v in value.items() if k!='result'}
  return json.dumps(value,ensure_ascii=False,allow_nan=False)
def graph_start(period,anchor,source,fields_json,mode=None,window_start="",window_end=""):
 from datetime import date
 fields=json.loads(fields_json)
 if period not in ('day','month','year','all') or source not in ('Auto','Local','SmartESS') or not isinstance(fields,list) or not 1<=len(fields)<=18:raise ValueError('Некоректний запит графіка')
 mode=mode or ('energy' if period in ('year','all') else 'power')
 if mode not in ('energy','power') or (period in ('year','all') and mode!='energy'):raise ValueError('Некоректний режим графіка')
 day=date.fromisoformat(anchor)
 if window_start or window_end:
  import re
  valid=lambda t: isinstance(t,str) and bool(re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',t))
  if period!='day' or not valid(window_start) or not (valid(window_end) or window_end=='24:00') or window_end<=window_start:raise ValueError('Некоректний часовий проміжок')
 if not 2010<=day.year<=2100:raise ValueError('Некоректна дата')
 with _lock:api=_api
 if api is None:raise ValueError('Спочатку підключіть сервер')
 with _graph_lock:
  if _graph_job.get('state')=='running':return graph_status()
  _graph_cancel.clear();query=uuid.uuid4().hex
  _graph_job.clear();_graph_job.update(state='running',profile=connection_profile(),period=period,anchor=anchor,source=source,fields=fields,mode=mode,window_start=window_start,window_end=window_end,query_id=query,done=0,total=0)
 def work():
  done=threading.Event();started=time.monotonic()
  try:
   options=dict(fields=fields,max_points=2000)
   if mode=='energy' and period in ('day','month'):options['mode']=mode
   if window_start or window_end:options.update(window_start=window_start,window_end=window_end)
   result=_history_job(api,dict(domain='history',method='graph_data',args=[period,day,source],kwargs=options),query,'graph',_graph_cancel.is_set)
   if window_start or window_end:
    window=result.get('window') if isinstance(result,dict) else None
    if not isinstance(window,dict):raise ValueError('Для часового проміжку потрібен Server a1.4.31 або новіший')
    from datetime import datetime,timedelta
    a,b=datetime.fromisoformat(window['start']),datetime.fromisoformat(window['end'])
    expected_end=day+timedelta(days=1) if window_end=='24:00' else day
    if a.date()!=day or b.date()!=expected_end or a.strftime('%H:%M')!=window_start or b.strftime('%H:%M')!=('00:00' if window_end=='24:00' else window_end):raise ValueError('Сервер повернув інший часовий проміжок')
   if _graph_cancel.is_set():raise InterruptedError('Графік скасовано')
   if not isinstance(result,dict) or result.get('contract')!='ducksolar.graph.v1' or result.get('source')!=source or result.get('period')!=period or result.get('anchor')!=anchor or len(result.get('points',[]))>2000:raise ValueError('Некоректна відповідь графіка')
   with _graph_lock:_graph_job.update(state='complete',result=result,elapsed_s=round(time.monotonic()-started,2))
  except Exception as exc:
   with _graph_lock:_graph_job.update(state='cancelled' if _graph_cancel.is_set() else 'error',error=str(exc),elapsed_s=round(time.monotonic()-started,2))
  finally:
   done.set();_note('graph.finished',details={'query_id':query,'anchor':anchor,'fields':fields,'mode':mode,'period':period,'source':source,'state':_graph_job['state'],'elapsed_s':_graph_job.get('elapsed_s'),'error':_graph_job.get('error','')})
 _note('graph.started',details={'query_id':query,'anchor':anchor,'fields':fields,'mode':mode,'period':period,'source':source,'window_start':window_start,'window_end':window_end})
 threading.Thread(target=work,daemon=True,name='GraphLoader').start()
 return graph_status()
def graph_cancel():
 with _graph_lock:
  query=_graph_job.get('query_id');running=_graph_job.get('state')=='running';_graph_cancel.set()
 return graph_status()

def history_dates():
 from datetime import date
 dates=_read_api('history','available_dates',True)
 if not isinstance(dates,list) or len(dates)>5000:raise ValueError('Завеликий перелік дат історії')
 values=sorted(set(d.isoformat() if isinstance(d,date) else date.fromisoformat(d).isoformat() for d in dates))
 return json.dumps({'count':len(values),'first':values[0] if values else None,'last':values[-1] if values else None,'dates':values[-90:][::-1]},ensure_ascii=False)

def finance_month(month):
 from datetime import date
 anchor=date.fromisoformat(month+'-01')
 result=_read_api('finance','view',anchor.year,anchor.month)
 selected=result.get('selected')
 if selected and (selected.get('year'),selected.get('month'))!=(anchor.year,anchor.month):raise ValueError('Сервер повернув фінанси іншого періоду')
 # The server also returns history; the screen only needs the selected month.
 return json.dumps(encode({'month':month,'selected':selected}),ensure_ascii=False,allow_nan=False)

def add_meter_reading(stamp,values_json,confirmed=False):
 from datetime import datetime
 import math
 if not confirmed:raise ValueError('Потрібне підтвердження показників')
 instant=datetime.fromisoformat(stamp)
 if instant.tzinfo is not None:raise ValueError('Вкажіть місцевий час без часового поясу')
 values=json.loads(values_json)
 keys={'import_day','import_night','export_day','export_night'}
 if set(values)!=keys or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values.values()):raise ValueError('Усі чотири показники мають бути невід’ємними числами')
 # Capture the current meter and connection; mutations must never fail over/retry.
 with _lock:api=_api
 if api is None:raise ValueError('Спочатку підключіть сервер')
 meter_id=api.call('storage','get_current_meter_id')
 with _lock:
  if api is not _api:raise ValueError('Підключення змінилося; підтвердьте показники знову')
 result=api.call('storage','add_meter_reading',instant.isoformat(sep=' ',timespec='seconds'),values,meter_id=meter_id)
 _note('meter.saved',details={'meter_id':meter_id})
 return json.dumps({'id':result,'meter_id':meter_id},ensure_ascii=False)

_command_lock=threading.RLock()

def parameter_snapshot():
 envelope=json.loads(snapshot());state=envelope.get('state',{});params=dict(state.get('parameters',{}))
 params['stale']=params.get('stale',True) or state.get('stale',True) or not envelope.get('connected')
 params['device_id']=state.get('device_id','')
 params['server_profile']=connection_profile()
 params.pop('raw',None);params.pop('raw_text',None)
 if len(params.get('rows',[]))>128:raise ValueError('Завеликий каталог параметрів')
 return json.dumps(params,ensure_ascii=False,allow_nan=False)

def connection_profile():
 import hashlib
 with _lock:return hashlib.sha256((_cfg.get('pin','')+'|'+_cfg.get('username','')).encode()).hexdigest()

_weather_history_lock=threading.RLock();_weather_history_job={}

def weather_identity():
 return connection_profile()+'|'+str(_cfg.get('serial',''))

_remote_weather_cache={};_remote_weather_at=0.;_remote_weather_identity=None
def weather_status():
 global _remote_weather_cache,_remote_weather_at,_remote_weather_identity
 identity=weather_identity()
 if identity!=_remote_weather_identity:_remote_weather_cache={};_remote_weather_at=0.;_remote_weather_identity=identity
 if time.monotonic()-_remote_weather_at>=5:
  try:_remote_weather_cache=_read_api('insights','forecast_status');_remote_weather_at=time.monotonic()
  except Exception:
   if not _remote_weather_cache:
    from ducksolar import weather_client as w
    return json.dumps(w.status(_root,weather_identity()),ensure_ascii=False,allow_nan=False)
 return json.dumps(_remote_weather_cache,ensure_ascii=False,allow_nan=False)

def weather_settings(value):
 global _remote_weather_at
 obj=json.loads(value)
 from ducksolar import weather_client as w
 w.settings(_root,weather_identity(),obj)
 _read_api('insights','forecast_settings',obj);_remote_weather_at=0
 return weather_status()

def weather_start(train=False):
 global _remote_weather_at
 from ducksolar import weather_client as w
 settings=w.settings(_root,weather_identity())
 if settings:_read_api('insights','forecast_settings',settings)
 result=_read_api('insights','forecast_start',bool(train));_remote_weather_at=0
 return json.dumps(result,ensure_ascii=False,allow_nan=False)

def weather_cancel(pause=False):
 if pause:return weather_status()
 return json.dumps(_read_api('insights','forecast_cancel'),ensure_ascii=False,allow_nan=False)

def weather_resume():return weather_status()

def weather_profile():
 return json.dumps(_read_api('pv','get'),ensure_ascii=False,allow_nan=False)

def refresh_parameters():
 params=json.loads(parameter_snapshot())
 if not params.get('device_id'):raise ValueError('Інвертор ще не визначений')
 _read_api('monitor','refresh_parameters',device_id=params['device_id'])
 return True

def _save_command(row):
 file=_root/'parameter-command.tmp';file.write_text(json.dumps(row,ensure_ascii=False,allow_nan=False),encoding='utf-8');file.chmod(0o600);file.replace(_root/'parameter-command.json')

def _load_command():
 try:return json.loads((_root/'parameter-command.json').read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}

def submit_parameter(parameter,value,expected,device_id,confirmed=False,server_profile=''):
 from decimal import Decimal
 if not confirmed:raise ValueError('Підтвердьте зміну параметра')
 if server_profile!=connection_profile():raise ValueError('Сервер або акаунт змінився; підтвердьте параметр знову')
 if len(value)>32 or not Decimal(value).is_finite():raise ValueError('Некоректне нове значення')
 with _command_lock:
  old=_load_command()
  if old.get('status') in ('queued','writing','verifying','sending'):raise ValueError('Дочекайтеся результату попередньої команди')
  params=json.loads(parameter_snapshot())
  if params.get('stale') or params.get('device_id')!=device_id:raise ValueError('Оновіть актуальні параметри інвертора')
  row=next((r for r in params.get('rows',[]) if r.get('canonical_id')==parameter),None)
  if not row or not row.get('writable') or not row.get('present'):raise ValueError('Запис цього параметра не підтверджений сервером')
  if Decimal(str(row.get('raw_value')))!=Decimal(expected):raise ValueError('Поточне значення змінилося; перевірте параметри знову')
  with _lock:api=_api;pin=_cfg.get('pin');user=_cfg.get('username')
  if api is None:raise ValueError('Спочатку підключіть сервер')
  identity={'pin':pin,'username':user,'device_id':device_id}
  _save_command(dict(identity,parameter=parameter,new=value,old=expected,status='sending'))
  try:
   result=api.call('parameters','submit',parameter,value,expected,device_id=device_id)
   _save_command(dict(result,**identity))
   _note('parameter.submitted',details={'operation_id':result.get('operation_id'),'device_id':device_id})
   return json.dumps(result,ensure_ascii=False,allow_nan=False)
  except Exception:
   _save_command(dict(identity,parameter=parameter,new=value,old=expected,status='unknown',message='Відповідь на запис не отримано. Автоматичного повтору немає; перевірте фактичне значення.'))
   raise

def parameter_command_status():
 with _command_lock:
  row=_load_command()
  if not row:return '{}'
  with _lock:
   if row.get('pin')!=_cfg.get('pin') or row.get('username')!=_cfg.get('username'):raise ValueError('Команда належить іншому серверу або акаунту')
  if row.get('operation_id'):
   result=_read_api('parameters','status',row['operation_id'],device_id=row['device_id'])
   row.update(result);_save_command(row)
  elif row.get('status')=='sending':
   row.update(status='unknown',message='Клієнт перезапущено до отримання відповіді; запис не повторюється. Перевірте фактичне значення.');_save_command(row)
  return json.dumps({k:v for k,v in row.items() if k not in ('pin','username')},ensure_ascii=False,allow_nan=False)


def tariff_status():
 result=dict(_read_api('tariffs','status'))
 result['history']=_read_api('tariffs','history')
 return json.dumps(encode(result),ensure_ascii=False)

def tariff_check():
 try:_read_api('tariffs','check_for_updates')
 except Exception:
  # The server records the failed official fetch without discarding cached rates.
  # A failed server connection still raises when reading its status below.
  return tariff_status()
 return tariff_status()


_notification_sync_at=0

def _notification_sync():
 global _notification_sync_at
 from ducksolar.notification_settings import validate
 with _lock:
  api=_api;settings=validate(_cfg.get('notifications',{}))
  _cfg['notifications_pending']=True;_save()
 if api is None:raise ValueError('Підключіть сервер')
 _notification_sync_at=time.monotonic()
 extended='notifications.extended.v1' in (api.ensure_session().get('capabilities') or [])
 from ducksolar.notification_settings import LEGACY,GROUPS
 if not extended and any(settings[g] for g in GROUPS if g!='server_connection'):raise ValueError('Для нових сповіщень оновіть сервер до b1.0.1')
 sent=settings if extended else {k:settings[k] for k in LEGACY}
 result=api.call('notifications','settings',sent)
 if any(result.get(k)!=v for k,v in sent.items()):raise ValueError('Сервер не підтвердив налаштування сповіщень')
 _note('notifications.settings.applied',details={'settings':sent,'extended':extended})
 with _lock:
  if api is _api and settings==validate(_cfg.get('notifications',{})):
   _cfg['notifications_pending']=False;_save()
 return result

def notification_settings(value=''):
 from ducksolar.notification_settings import validate
 with _lock:
  if value:
   _cfg['notifications']=validate(json.loads(value));_cfg['notifications_pending']=True;_save()
  settings=validate(_cfg.get('notifications',{}))
 if value:
  try:_notification_sync()
  except Exception as exc:_note('notifications.sync.pending',message=str(exc))
 with _lock:return json.dumps(dict(settings=settings,pending=_cfg.get('notifications_pending',False)))

def notification_batch():
 if _cfg.get('notifications_pending') and time.monotonic()-_notification_sync_at>30:
  try:_notification_sync()
  except Exception as exc:_note('notifications.sync.pending',message=str(exc))
 with _lock:
  live=_live
  state=live.snapshot() if live else {}
  connected=bool(live and live.connected and state.get('statuses',{}).get('API',False))
  from ducksolar.local_alerts import update
  before=json.dumps({k:v for k,v in _cfg.items() if k.startswith('local_alert') or k=='server_outage'},sort_keys=True)
  local=update(_cfg,connected,time.time())
  after=json.dumps({k:v for k,v in _cfg.items() if k.startswith('local_alert') or k=='server_outage'},sort_keys=True)
  if before!=after:_save()
 events=list(state.get('notifications',[])) if connected else []
 return json.dumps(dict(events=events+local,connected=connected,supported='notifications' in state),ensure_ascii=False)

def notification_ack(ids):
 with _lock:api=_api
 values=json.loads(ids)
 with _lock:
  local_ids={e['id'] for e in _cfg.get('local_alert_events',[])}
  _cfg['local_alert_events']=[e for e in _cfg.get('local_alert_events',[]) if e['id'] not in values];_save()
 remote=[i for i in values if i not in local_ids]
 result=api.call('notifications','ack',remote) if remote and api else True
 _note('notifications.ack.sent',details={'count':len(values)})
 return result

def delivery_event(result,kind,ident):
 from ducksolar.notification_settings import KIND_GROUP
 if result not in ('posted','disabled','duplicate','persist_failed','not_visible') or kind not in KIND_GROUP:return
 _repeat_note('notifications.delivery',details={'result':result,'kind':kind,'notification_id':ident},message=result+':'+ident)


def background_event(kind,details='{}'):
 try:
  data=json.loads(details)
  safe={k:v for k,v in data.items() if k in ('gap_s','previous_work_s','idle_gap_s','battery_exempt','permitted','channel_enabled','service_channel_enabled','level','scale','plugged','screen_on','wakelock_active','channel_importance','channel_sound','interruption_filter') and isinstance(v,(bool,int,float))}
 except (ValueError,TypeError):safe={}
 if kind in ('health','resume_gap','energy'):_note('background.'+kind,details=safe)
 return True


def _prefer_lan():
 global _lan_check_at
 now=time.monotonic();lan=_cfg.get('lan');old_url=_api.url if _api else None
 if not (_wifi_available and lan and old_url and old_url!=lan) or now<_manual_until or now<_lan_check_at or _routes.until.get(lan,0)>now:return False
 _lan_check_at=now+60
 try:
  # Probe only on Wi-Fi, without destroying the healthy stream on unreachable LAN.
  _probe(lan,_cfg['pin'])
  _begin(lan)
  _note('route.auto_lan',details={'reason':'wifi_lan_verified'})
  return True
 except Exception as exc:
  _note('route.lan_deferred',details={'reason':getattr(exc,'code',type(exc).__name__)})
  if not _live or not _live.connected:
   try:_begin(old_url)
   except Exception:pass
  return False


def switch_route(route,lan='',remote=''):
 global _manual_until,_lan_check_at
 if route not in ('local','remote'):raise ValueError('Невідомий маршрут')
 with _lock:
  if not _cfg.get('token'):raise ValueError('Спочатку увійдіть у свій акаунт')
  for key,value in (('lan',lan),('remote',remote)):
   if value.strip():DesktopTransport(value.strip(),_cfg['pin']);_cfg[key]=value.strip().rstrip('/')
  target=_cfg.get('lan' if route=='local' else 'remote')
  if not target:raise ValueError('Не задана адреса обраного підключення')
  old_url=_api.url if _api else None
  _manual_until=time.monotonic()+120;_lan_check_at=_manual_until
  _note('route.manual',route,details={'automatic':True,'prefer_for_s':120})
  try:return _begin(target)
  except Exception:
   if old_url and (not _live or not _live.connected):
    try:_begin(old_url)
    except Exception:pass
   raise


def _snapshot_scope():return (_cfg.get('serial',''),_cfg.get('pin',''),_cfg.get('username',''),_cfg.get('client_id',''))


def _save_last_snapshot(state):
 global _snapshot_saved_at
 if not _root or time.monotonic()-_snapshot_saved_at<30:return
 try:
  value=dict(scope=list(_snapshot_scope()),saved_at=time.time(),state=state)
  raw=json.dumps(encode(value),ensure_ascii=False,allow_nan=False)
  if len(raw.encode())>2*1024*1024:return
  tmp=_root/'last-snapshot.tmp';tmp.write_text(raw,encoding='utf-8');tmp.replace(_root/'last-snapshot.json');_snapshot_saved_at=time.monotonic()
 except (OSError,ValueError,TypeError):pass


def last_snapshot():
 with _lock:
  try:
   p=_root/'last-snapshot.json'
   if p.stat().st_size>2*1024*1024:raise ValueError('Snapshot too large')
   obj=json.loads(p.read_text(encoding='utf-8'))
   if tuple(obj.get('scope',()))!=_snapshot_scope():raise ValueError('Other inverter/account')
   return json.dumps(obj,ensure_ascii=False)
  except (OSError,ValueError,TypeError):raise ValueError('Збереженого знімка цього інвертора ще немає')

_feature_lock=threading.RLock()
_feature_state={'state':'idle'}
_feature_active=False

def feature_call(method,value='[]'):
 args=json.loads(value)
 if not isinstance(args,list):raise ValueError('Invalid feature arguments')
 with _lock:api=_api
 if api is None:raise ValueError('Спочатку підключіть сервер')
 # Mutations are intentionally never retried after an ambiguous response.
 identity=connection_profile()
 result=api.call('insights',method,*args)
 if identity!=connection_profile():raise ValueError('Сервер змінився')
 return json.dumps(result,ensure_ascii=False,allow_nan=False)

def feature_status():
 with _feature_lock:return json.dumps(_feature_state,ensure_ascii=False,allow_nan=False)

def feature_start(kind,anchor,other='',period='day',metric='pv_w'):
 global _feature_active,_feature_state
 from datetime import date
 request=dict(domain='history',method='insights_data',args=[kind,date.fromisoformat(anchor),'Auto'],kwargs=dict(other=date.fromisoformat(other) if other else None,period=period,metric=metric))
 with _lock:api=_api
 if api is None:raise ValueError('Спочатку підключіть сервер')
 identity=connection_profile()
 with _feature_lock:
  if _feature_active:raise ValueError('Попередній запит аналітики ще виконується')
  _feature_active=True;_feature_state=dict(state='running',kind=kind)
 def work():
  global _feature_active,_feature_state
  try:
   result=_history_job(api,request,uuid.uuid4().hex,'insights',lambda:identity!=connection_profile())
   if identity!=connection_profile():raise ValueError('Сервер змінився')
   if kind in ('report','forecast') and not has_server_analysis(result):
    weather=json.loads(weather_status()).get('result') or {}
    forecast=weather.get('forecast_archive',{}).get(anchor)
    result['forecast']=forecast
    actual=result.get('summary',{}).get('generation',{}).get('kwh')
    covered=result.get('summary',{}).get('generation',{}).get('coverage_seconds',0)/max(1,result.get('summary',{}).get('duration_seconds',1))
    prediction=(forecast or {}).get('expected_kwh')
    result['forecast_error_pct']=(actual-prediction)/prediction*100 if prediction and actual is not None and covered>=.95 and forecast.get('basis')=='day_ahead' else None
   if kind=='forecast' and not has_server_analysis(result):
    result['forecast_note']='Немає збереженого прогнозу; оновіть погоду. Показаний лише факт.' if not (result.get('forecast') or weather.get('hourly')) else 'Прогноз і факт'
    from datetime import datetime
    from zoneinfo import ZoneInfo
    by_time={}
    for point in result.pop('hourly_actual',[]):
     at=datetime.fromisoformat(point['label']).timestamp()
     covered=point.get('coverage_seconds',{}).get('pv_w',0)
     value=point.get('pv_w')
     by_time[at]=dict(x=at*1000,label=point['label'],actual=value*1000 if value is not None and covered>=3420 else None)
    predicted=(result.get('forecast') or {}).get('hourly',[])
    if not predicted:predicted=[r for r in weather.get('hourly',[]) if r.get('day')==anchor]
    for point in predicted:
     at=datetime.fromisoformat(point['time']).timestamp()
     by_time.setdefault(at,dict(x=at*1000,label=point['time']))['forecast']=point['power_w']
    result['graph']=dict(kind='line',mode='power',points=[by_time[k] for k in sorted(by_time)],fields=[dict(key='actual',label='Факт (середня за повну годину)',unit='Вт'),dict(key='forecast',label='Прогноз',unit='Вт')])
   if kind=='forecast':
    graph=result.get('graph',{});points=graph.get('points',[])
    _note('forecast.graph_ready',details=dict(analysis_version=result.get('forecast_analysis_version'),graph_kind=graph.get('kind'),actual_points=sum(p.get('actual') is not None for p in points),forecast_points=sum(p.get('forecast') is not None for p in points),legacy_fallback=not has_server_analysis(result)))
   with _feature_lock:_feature_state=dict(state='complete',kind=kind,result=result)
  except Exception as exc:
   with _feature_lock:_feature_state=dict(state='error',error=str(exc))
  finally:
   with _feature_lock:_feature_active=False
 threading.Thread(target=work,name='ClientInsights',daemon=True).start()
 return feature_status()

_widget_fetch_lock=threading.Lock()
def widget_snapshot():
 if not _widget_fetch_lock.acquire(False):raise ValueError('Оновлення віджета вже триває')
 try:
  with _lock:api=_api;cfg=dict(_cfg)
  urls=[cfg.get('lan'),cfg.get('remote')] if _wifi_available else [cfg.get('remote'),cfg.get('lan')]
  if api is not None:urls=[api.url]+urls
  error=None
  for url in dict.fromkeys(url for url in urls if url):
   try:
    candidate=api if api is not None and api.url==url else ServerAPI(url,access_key=cfg.get('token',''),client_id=cfg.get('client_id'),transport=DesktopTransport(url,cfg.get('pin','')))
    candidate.connection_timeout_s=5
    state=candidate.get('state',timeout=5)
    return json.dumps(dict(state=state,connected=True),ensure_ascii=False,allow_nan=False)
   except Exception as exc:
    error=exc
    if isinstance(exc,TransportError) and exc.code in candidate.auth_codes:break
  raise error or ValueError('Немає збереженого підключення')
 finally:_widget_fetch_lock.release()
