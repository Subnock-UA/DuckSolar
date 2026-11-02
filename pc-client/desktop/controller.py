import json,threading,time,socket,logging,collections,hashlib
from pathlib import Path
import desktop_client as api
from .settings import atomic,migrate_legacy
from ducksolar.notification_settings import validate,KIND_GROUP

def decoded(value):
 if isinstance(value,str):
  try:return json.loads(value)
  except (ValueError,TypeError):pass
 return value
class Controller:
 def __init__(self,root,notify=None,backend=api):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.backend=backend;self.notify=notify
  self.stop_event=threading.Event();self.state_lock=threading.Lock();self.state={};self.visible=True;self.error='';self.threads=[];self.last_route=0.
  self.widget_enabled=False;self.widget_state={};self.last_widget=0.;self.active_scope=None
  self.profile=decoded(backend.initialize(str(self.root)));self.seen_path=self.root/'notifications-seen.json'
  try:self.seen=json.loads(self.seen_path.read_text())
  except (OSError,ValueError):self.seen={}
  self.alert_history=collections.deque(maxlen=200)
 def call(self,name,*args):return decoded(getattr(self.backend,name)(*args))
 def feature(self,method,*args):return self.call('feature_call',method,json.dumps(args,ensure_ascii=False))
 def set_visible(self,visible):
  if self.visible!=visible:
   self.visible=visible;self.backend.lifecycle_event('foreground' if visible else 'background')
 def start(self):
  self.backend.lifecycle_event('foreground')
  for target in (self._connection_loop,self._notifications_loop,self._support_loop):
   thread=threading.Thread(target=target,daemon=True);self.threads.append(thread);thread.start()
 def _connection_loop(self):
  while not self.stop_event.is_set():
   try:
    now=time.monotonic()
    if now-self.last_route>=15:
     self.last_route=now
     try:
      import ipaddress
      addresses=socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)
      private=any(ipaddress.ip_address(x[4][0]).is_private and not ipaddress.ip_address(x[4][0]).is_loopback for x in addresses)
     except OSError:private=False
     self.backend.network_state(True,private,'desktop')
     self.call('resume')
    value=self.call('snapshot');value['_captured_at']=time.time();scope=self.backend.connection_profile()
    if self.active_scope!=scope:self.widget_state={};self.last_widget=0.;self.active_scope=scope
    value['_profile']=scope
    if self.widget_enabled and not self.visible and now-self.last_widget>=300:
     self.last_widget=now
     try:self.widget_state=self.call('widget_snapshot');self.widget_state['_captured_at']=time.time()
     except Exception as exc:self.error=str(exc)
    with self.state_lock:self.state=value
   except Exception as exc:self.error=str(exc)
   self.stop_event.wait(1 if self.visible else 5)
 def snapshot(self):
  with self.state_lock:return dict(self.state)
 def _notifications_loop(self):
  while not self.stop_event.is_set():
   try:self.deliver(self.call('notification_batch'))
   except Exception as exc:self.error=str(exc)
   signal=getattr(self.backend,'notification_signal',self.stop_event);signal.wait(30);signal.clear()
 def deliver(self,batch):
  settings=validate(self.call('notification_settings').get('settings',{}));scope=self.backend.connection_profile();seen=self.seen.get(scope,[]);ack=[]
  for event in batch.get('events',[]):
   ident=event.get('id','');kind=event.get('kind','');group=KIND_GROUP.get(kind)
   if not group or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):continue
   if not settings.get(group,False):ack.append(ident);continue
   if ident not in seen:
    if self.notify is None or not self.notify(event):continue
    seen=(seen+[ident])[-512:];self.seen[scope]=seen;atomic(self.seen_path,self.seen)
    self.alert_history.appendleft(event);self.backend.delivery_event('posted',kind,ident)
   ack.append(ident)
  if ack:self.backend.notification_ack(json.dumps(ack))
  return ack
 def _support_loop(self):
  path=self.root/'support-state.json'
  try:saved=json.loads(path.read_text())
  except (OSError,ValueError):saved={}
  while not self.stop_event.is_set():
   try:
    options=json.loads((self.root/'desktop.json').read_text())
    if options.get('helper_id') and options.get('auto_upload',True) and time.time()-saved.get('last_upload',0)>=900:
     from .support import Support
     service=Support(options.get('support_url','http://127.0.0.1:28765'),self.root,options['helper_id'])
     service.upload_diagnostics(self.backend._cfg['client_id']);saved['last_upload']=time.time();saved['last_error']=''
     manifest=service.desktop_manifest()
     if manifest.get('version_code',0)>20000 and manifest.get('version')!=saved.get('notified_version') and self.notify:
      if self.notify(dict(message='Доступне оновлення Duck Solar для ПК',detail=manifest['version']+' · Додатково → Зв’язок із ПК-службою',created=time.time())):saved['notified_version']=manifest['version']
     atomic(path,saved)
   except FileNotFoundError:pass
   except Exception as exc:
    saved['last_error']=str(exc);logging.info('PC support waiting: %s',type(exc).__name__)
   self.stop_event.wait(60)
 def close(self):
  self.stop_event.set();getattr(self.backend,'notification_signal',self.stop_event).set();self.backend.stop('desktop_exit')
