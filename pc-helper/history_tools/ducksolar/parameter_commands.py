"""Queued, audited writes. Sent writes are never retried; ACK is not success."""
import copy
import json
import threading
import time
from datetime import datetime
from uuid import uuid4
from .config import app_paths
from .protocol.dispatcher import ProtocolJob, Priority
from .protocol.pi30 import encode_command
from .drivers.parameter_library import RULES, command, normalized, validate_state, current_value

class ParameterCommands:
    TERMINAL={'verified','rejected','unknown','cancelled'}
    VERIFY_DELAYS=(2,3,5,10,20,30)
    def __init__(self,runtime):
        self.runtime=runtime;self.lock=threading.RLock()
        self.path=app_paths(runtime.cfg)['data']/'ParameterCommands.json'
        try:self.items=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.items={}
        for item in self.items.values():
            if item['status'] not in self.TERMINAL:
                item.update(status='unknown' if item.get('sent') else 'cancelled',message='Server перезапущено; повторний запис не виконувався')
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.items,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(self.path)

    def _update(self,ident,**values):
        with self.lock:
            item=self.items[ident];item.update(values,updated=datetime.now().isoformat(timespec='seconds'))
            self._save()
            audit=copy.deepcopy(item);audit['result_message']=audit.pop('message','')
            try:self.runtime.logs.event('Parameter command '+item['status'],code='parameter.command.'+item['status'],**audit)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Command audit text log failed; durable ledger retained')

    def status(self,ident,username,device_id):
        with self.lock:
            item=self.items.get(ident)
            if not item or item['username']!=username or item['device_id']!=device_id:
                raise ValueError('Операцію не знайдено')
            return copy.deepcopy(item)

    def submit(self,device_id,parameter,value,expected,username,authorize,batch_id=None):
        active=getattr(self.runtime,"profile_batches",{}).get(device_id)
        if active and active!=batch_id:raise ValueError("Дочекайтеся завершення профілю")
        request=command(parameter,value)
        if len(str(expected))>32:raise ValueError('Некоректне поточне значення')
        normalized(expected)
        dev=self.runtime.device(device_id)
        if not self.runtime.active or not dev.channel.connected:raise ValueError('Інвертор не підключений')
        snapshot=dev.parameters.snapshot()
        if snapshot['stale']:raise ValueError('Оновіть параметри перед зміною')
        identity=dev.driver.identity(snapshot['raw']);serial=identity['serial']
        if not serial:raise ValueError('Серійний номер інвертора ще не отримано')
        # Reject invalid profiles/ranges before enqueuing; recheck actual state inside transaction.
        from .drivers.parameter_library import matches
        if not matches(snapshot['raw']):raise ValueError('Немає підтвердженої бібліотеки запису для цього firmware')
        ident=uuid4().hex
        with self.lock:
            active=getattr(self.runtime,'profile_batches',{}).get(device_id)
            if active and active!=batch_id:raise ValueError('Дочекайтеся завершення профілю')
            if any(i.get('device_id')==device_id and i['status'] not in self.TERMINAL for i in self.items.values()):raise ValueError('Дочекайтеся перевірки попередньої операції')
            if sum(i['status'] not in self.TERMINAL for i in self.items.values())>=32:raise ValueError('Черга команд заповнена')
            for key in list(self.items):
                if len(self.items)<500:break
                if self.items[key]['status'] in self.TERMINAL:del self.items[key]
            self.items[ident]=dict(operation_id=ident,device_id=device_id,parameter=parameter,username=username,
                old=str(expected),new=str(value),status='queued',sent=False,created=datetime.now().isoformat(timespec='seconds'))
            self._save()
        self._update(ident,status='queued')
        expires=time.monotonic()+60
        def action():
            with self.runtime.adapters[dev.definition.logger_id]._local_transaction:
                try:
                    if time.monotonic()>expires:raise TimeoutError('Queued operation expired before execution')
                    authorize()
                    if not self.runtime.active:raise ConnectionError('Server stopping')
                    connection=dev.channel.connection_id
                    def read(name):
                        result=dev.driver.decode_response(dev.channel.transact(encode_command(name)),name)
                        if dev.channel.connection_id!=connection:raise ConnectionError('З’єднання з інвертором змінилося')
                        return result
                    raw={name:read(name) for name in ('QPI','QID','QMN','QVFW','QPIRI')}
                    if RULES[parameter].get('query')=='QFLAG':raw['QFLAG']=read('QFLAG')
                    if dev.driver.identity(raw)['serial']!=serial:raise ValueError('Інвертор на каналі змінився')
                    mode=read('QMOD')
                    actual=validate_state(parameter,value,raw,mode)
                    if normalized(actual)!=normalized(expected):raise ValueError('Поточне значення змінилося; оновіть параметри')
                    authorize()
                    if not self.runtime.active or dev.monitor.dispatcher.stop_event.is_set():raise ConnectionError('Server stopping')
                    if time.monotonic()>expires:raise TimeoutError('Preflight expired before write')
                    if normalized(actual)==normalized(value):
                        self._update(ident,status='verified',message='Значення вже встановлено; запис не потрібний',actual=actual)
                        return True
                    self._update(ident,status='writing',sent=True)
                    ack=dev.driver.decode_text(dev.channel.transact(request))
                    if ack!='ACK':raise ValueError('Некоректне підтвердження запису')
                    self._update(ident,status='verifying',ack_at=datetime.now().isoformat(timespec='milliseconds'))
                    self._start_verification(ident,dev,serial,parameter,value,authorize)
                    return True
                except Exception as exc:
                    with self.lock:sent=self.items[ident]['sent']
                    # An explicit NAK proves rejection; timeout/invalid reply after send is unknown.
                    rejected='rejected' if not sent or 'rejected read command' in str(exc) else 'unknown'
                    if sent and rejected=='unknown':
                        self._update(ident,status='verifying',message=str(exc))
                        self._start_verification(ident,dev,serial,parameter,value,authorize)
                    else:self._update(ident,status=rejected,message=str(exc))
                    if sent:dev.parameters.request_refresh()
                    return False
        def callback(response,error):
            if error:
                with self.lock:sent=self.items[ident]['sent']
                self._update(ident,status='unknown' if sent else 'cancelled',message=str(error))
        job=ProtocolJob(priority=int(Priority.CRITICAL),name='write.'+parameter,action=action,
            deadline=expires,callback=callback)
        if not dev.monitor.dispatcher.submit(job):self._update(ident,status='cancelled',message='Черга команд заповнена')
        return self.status(ident,username,device_id)

    def _start_verification(self,ident,dev,serial,parameter,value,authorize):
        def worker():
            last=None
            for attempt,delay in enumerate(self.VERIFY_DELAYS,1):
                if dev.monitor.dispatcher.stop_event.wait(delay):break
                if not self.runtime.active:break
                done=threading.Event();result={}
                def action():
                    with self.runtime.adapters[dev.definition.logger_id]._local_transaction:
                        authorize()
                        connection=dev.channel.connection_id
                        identity=dev.driver.decode_response(dev.channel.transact(encode_command('QID')),'QID')
                        if identity!=serial or connection!=dev.channel.connection_id:
                            raise ValueError('Ідентичність інвертора змінилася; перевірку зупинено')
                        query=RULES[parameter].get('query','QPIRI')
                        raw=dev.driver.decode_response(dev.channel.transact(encode_command(query)),query)
                        if connection!=dev.channel.connection_id:raise ConnectionError('З’єднання змінилося під час читання')
                        return current_value(parameter,{query:raw})
                def callback(response,error,result=result,done=done):result.update(value=response,error=error);done.set()
                self._update(ident,status='verifying',verification_attempt=attempt,connection_id=dev.channel.connection_id)
                job=ProtocolJob(priority=int(Priority.CRITICAL),name='verify.'+parameter,action=action,
                    deadline=time.monotonic()+25,callback=callback)
                if not dev.monitor.dispatcher.submit(job):continue
                if not done.wait(25):job.cancelled.set();continue
                if result.get('error'):
                    self._update(ident,status='verifying',message=str(result['error']))
                    if 'Ідентичність інвертора змінилася' in str(result['error']):break
                    continue
                last=result['value']
                if normalized(last)==normalized(value):
                    self._update(ident,status='verified',actual=last,message='Значення підтверджено контрольним читанням')
                    dev.parameters.request_refresh();return
            self._update(ident,status='unknown',actual=last,message='Результат не підтверджено; автоматичного повтору запису немає')
            dev.parameters.request_refresh()
        threading.Thread(target=worker,name='ParameterVerification',daemon=True).start()
