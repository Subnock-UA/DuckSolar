import copy
import json
import threading
import time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from ..grid_flow import select_grid_flows, flat_grid_fields
from ..grid_validation import GridMeasurementValidator
from ..protocol.dispatcher import ProtocolDispatcher, Priority
from ..storage import TelemetryRecord
from ..localization import text

class DeviceMonitor:
    """Generic polling lifecycle. Command bytes and decoding belong to a driver."""
    def __init__(self, cfg, writer, store, log_service, transport, driver, device_id):
        self.cfg=cfg; self.telemetry_writer=writer; self.runtime_store=store; self.log_service=log_service
        self.transport=transport; self.driver=driver; self.device_id=device_id
        self.dispatcher=ProtocolDispatcher(transport)
        self.grid_validator=GridMeasurementValidator(cfg,self._event)
        from ..display_retention import DisplayRetention
        self.display_retention=DisplayRetention()
        self._last_record_token=None; self._cloud_wait_updates=0; self._next_cloud_wait_log=0
        self.stop_event=threading.Event(); self.thread=None; self._state_lock=threading.RLock()
        self._state={'device_id':device_id,'connection':'DISCONNECTED','updated':'','mode':'—',
            'warnings':'','data':{},'lan_ip':'','last_error':'','error_code':None,'cloud':'DISCONNECTED','raw':{}}

    def _event(self, message, code='device.event', **details):
        item={'time':datetime.now().isoformat(sep=' ',timespec='seconds'),'code':code,
              'device_id':self.device_id,'message':message,'details':details}
        self.runtime_store.add_event(item)
        if self.log_service: self.log_service.event(message, code=code, device_id=self.device_id, **details)

    def set_cloud_state(self, state):
        with self._state_lock: self._state['cloud']=state

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear(); self.dispatcher.start()
        self.thread=threading.Thread(target=self._run,name='Device-'+self.device_id,daemon=True); self.thread.start()

    def cancel(self): self.stop_event.set()

    def stop(self):
        self.cancel(); self.dispatcher.stop()
        if self.thread: self.thread.join(timeout=4)

    def snapshot(self):
        with self._state_lock: return copy.deepcopy(self._state)

    def force_redirect(self):
        try:
            ip=self.transport.send_redirect()
            with self._state_lock: self._state['lan_ip']=ip
            return True
        except Exception as exc:
            self._event('Redirect failed: '+str(exc), 'logger.redirect_failed')
            return False

    def query_read(self, command, priority=Priority.SLOW):
        requests={name:request for request,name in self.driver.read_requests.items()}
        if command not in requests: raise ValueError('Unsupported local read')
        reply=self.dispatcher.transact_sync(requests[command],priority,name=command,
            timeout=max(15,self.cfg.socket_timeout_s+7))
        return self.driver.decode_response(reply,command)

    def query_text(self,command,priority=Priority.SLOW):
        return self.query_read(command,priority)

    def _apply_update(self, task, raw, values, requested, record_token, sample=None, native_values=None):
        # A synchronous read may finish after a newer cloud sample was published
        # while waiting. Never move the live timestamp/history backwards.
        if sample is not None and sample.connection != self.transport.connection_id:
            return False
        if task.telemetry and requested <= self._state.get('received_monotonic',float('-inf')):
            return False
        with self._state_lock:
            self._state['raw'][task.name]=raw
            if task.telemetry:
                if native_values is not None:
                    values=getattr(self.driver,'augment_native',lambda v,a,i:v)(values,getattr(self.transport,'native_auxiliary',{}),getattr(self.driver,'_grid_identity',({},None))[0] if getattr(self.driver,'_grid_identity',({},None))[1]==self.transport.connection_id else {})
                # Driver values remain authoritative. Missing readings stay missing.
                values['mode']=self._state['mode']; values['warnings']=self._state['warnings']
                now=datetime.now(ZoneInfo("Europe/Kyiv"))
                if sample is not None: now=datetime.fromtimestamp(now.timestamp()-max(0,time.monotonic()-sample.received),ZoneInfo("Europe/Kyiv"))
                elif native_values is not None and getattr(self.transport,'measurement_source','Local')=='ESS':
                    now=datetime.fromtimestamp(now.timestamp()-max(0,time.monotonic()-self.transport.measurement_received_monotonic),ZoneInfo("Europe/Kyiv"))
                stamp=now.isoformat(sep=' ',timespec='seconds')
                normalized=self.driver.normalized(values)
                for item in normalized.get('metrics',{}).values():
                    item.setdefault('timestamp', now.isoformat())
                normalized=self.grid_validator.process(normalized,now,time.monotonic(),self.transport.measurement_connection_id)
                normalized=select_grid_flows(normalized,now)
                receipt=values.pop('temperature_received_monotonic',None)
                if receipt is not None and 'temperature.inverter' in normalized.get('metrics',{}):
                    normalized['metrics']['temperature.inverter']['timestamp']=datetime.fromtimestamp(time.time()-max(0,time.monotonic()-receipt),ZoneInfo('Europe/Kyiv')).isoformat()
                self.display_retention.update(normalized.get("metrics",{}),self.transport.measurement_connection_id,now)
                values.update(flat_grid_fields(normalized,now))
                self._state.update(data=values,normalized=normalized,updated=stamp,last_error='',error_code=None,
                    measurement_connection_id=self.transport.measurement_connection_id,received_monotonic=requested)
                projector=getattr(self,'battery_projector',None)
                if projector is not None:
                    projector(self._state)
                    values=self._state['data'];normalized=self._state['normalized']
                stored={**values,"normalized_json":json.dumps(normalized,ensure_ascii=False,allow_nan=False)}
                self._state['sample_source']='ESS' if sample is not None else getattr(self.transport,'measurement_source','Local')
                self._state['sample_age_s']=round(time.monotonic()-requested,3)
                if record_token != self._last_record_token:
                    # A single consumer writes the canonical local history, irrespective of source.
                    self.telemetry_writer.submit(TelemetryRecord(now,'Local',stored,self.device_id))
                    self.runtime_store.add_live_point({'timestamp':stamp,'device_id':self.device_id,**values})
                    self._last_record_token=record_token
            else:
                self._state.update(values)
        return True

    def _refresh_cloud_telemetry(self):
        if self.stop_event.is_set() or not self.transport.connected:
            return
        for task in self.driver.poll_plan():
            if not task.telemetry:
                continue
            since=self._state.get('received_monotonic',float('-inf'))
            sample=getattr(self.transport,'take_cloud_sample',lambda *args:None)(task.name,since)
            if sample is None:
                continue
            getattr(self.driver,'prepare_grid_input',lambda *args:None)(self.transport.connection_id,self._state.get('mode_code'))
            if sample.values is not None:
                values=self.driver.decode_native_telemetry(sample.values)
                raw='ESS native bank4501'
            else:
                raw=self.driver.decode_response(sample.payload,task.name)
                values=self.driver.decode_update(task,raw)
            if self._apply_update(task,raw,values,sample.requested,sample.token,sample,sample.values):
                self._cloud_wait_updates+=1
                if time.monotonic()>=self._next_cloud_wait_log:
                    self._next_cloud_wait_log=time.monotonic()+60
                    self._event('Fresh ESS telemetry published independently of local polling',
                                'device.live_wait_refresh',updates=self._cloud_wait_updates)

    def _run(self):
        plan=self.driver.poll_plan(); now=time.monotonic(); due={task.name:now for task in plan}
        next_redirect=0
        last_read={task.name:float('-inf') for task in plan}
        self._last_record_token=None
        self._cloud_wait_updates=0
        failures={task.name:0 for task in plan}
        last_direct_telemetry=float('-inf')
        while not self.stop_event.is_set():
            self._refresh_cloud_telemetry()
            status=self.transport.snapshot_status()
            with self._state_lock:
                self._state.update(connection=status.state,lan_ip=status.lan_ip)
            if not self.transport.connected:
                # NativeRoute is the sole automatic recovery owner for this
                # logger. Manual requests still use force_redirect().
                if self.cfg.auto_redirect_enabled and not getattr(self.transport,'automatic_recovery_managed',False) and time.monotonic()>=next_redirect:
                    self.force_redirect(); next_redirect=time.monotonic()+self.cfg.redirect_retry_s
                self.stop_event.wait(.5); continue
            for task in plan:
                if self.stop_event.is_set(): break
                if time.monotonic()<due[task.name]: continue
                if task.telemetry and time.monotonic()-last_direct_telemetry<60:
                    latest=self._state.get('received_monotonic',float('-inf'))
                    if latest>last_read[task.name]:
                        last_read[task.name]=latest
                        due[task.name]=max(time.monotonic()+.1,latest+task.interval_s)
                        continue
                wait_updates_before=self._cloud_wait_updates
                sample=None;native_values=None
                used_ess_at_admission=False
                try:
                    if task.telemetry:
                        getattr(self.driver,'prepare_grid_input',lambda *args:None)(self.transport.connection_id,self._state.get('mode_code'))
                        # Give an already active ESS read a short chance to finish,
                        # then consume its actual reply instead of injecting a duplicate read.
                        getattr(self.transport,'wait_cloud_idle',lambda *args:None)(1)
                    # Periodic direct cross-check also refreshes PI30-only auxiliary fields.
                    if self.cfg.equipment_mode=='relay_only' or not task.telemetry or time.monotonic()-last_direct_telemetry<60:
                        sample=getattr(self.transport,'take_cloud_sample',lambda *args:None)(task.name,last_read[task.name])
                    if sample is None and self.cfg.equipment_mode=='relay_only':
                        continue
                    requested=time.monotonic()
                    if sample is not None:
                        requested=sample.requested
                        if sample.values is not None:
                            native_values=sample.values
                            raw='ESS native bank4501 (НП)'
                            values=self.driver.decode_native_telemetry(sample.values)
                        else:
                            raw=self.driver.decode_response(sample.payload,task.name)
                            values=self.driver.decode_update(task,raw)
                        record_token=sample.token
                    else:
                        native_values=None
                        if task.telemetry and getattr(self.transport,'native_ready',False) and time.monotonic()-last_direct_telemetry<60:
                            try:
                                from ..protocol.ess_shadow import decode_live
                                response=self.dispatcher.transact_sync(task.request,task.priority,'NATIVE4501',
                                    timeout=15,action=self.transport.read_native,
                                    on_wait=self._refresh_cloud_telemetry)
                                native_values=decode_live(response,45)
                            except Exception as exc:
                                if isinstance(exc,(TimeoutError,ConnectionError,OSError)) and self._cloud_wait_updates>wait_updates_before and time.monotonic()-self._state.get('received_monotonic',0)<=5:
                                    requested=self._state['received_monotonic']
                                    used_ess_at_admission=True
                                    failures[task.name]=0
                                    self._event('Native read deferred; fresh ESS telemetry already published','device.native_deferred')
                                    continue
                                self._event('Native read failed; falling back to PI30: '+str(exc),'device.native_fallback')
                        if native_values is not None:
                            origin=getattr(self.transport,'measurement_source','Local')
                            used_ess_at_admission=origin=='ESS'
                            raw=origin+' native bank4501'
                            values=self.driver.decode_native_telemetry(native_values,source=origin)
                        else:
                            response=self.dispatcher.transact_sync(task.request,task.priority,task.name,
                                timeout=max(15,self.cfg.socket_timeout_s+7),on_wait=self._refresh_cloud_telemetry)
                            raw=self.driver.decode_response(response,task.name)
                            values=self.driver.decode_update(task,raw)
                        if task.telemetry: requested=getattr(self.transport,'measurement_requested_monotonic',requested)
                        record_token=(self.transport.connection_id,task.name,requested)
                        if task.telemetry and native_values is None:
                            last_direct_telemetry=time.monotonic()
                            getattr(self.transport,'calibrate_cloud_sample',lambda *args:None)(values)
                    last_read[task.name]=max(requested,self._state.get('received_monotonic',float('-inf'))) if task.telemetry else requested
                    # A wait-time publication may have updated transport timing
                    # metadata too. Keep that newer cloud value rather than assign
                    # a delayed direct reply the cloud timestamp.
                    if not task.telemetry or sample is not None or self._cloud_wait_updates==wait_updates_before:
                        self._apply_update(task,raw,values,requested,record_token,sample,native_values)
                    failures[task.name]=0
                except Exception as exc:
                    if self.stop_event.is_set(): break
                    failures[task.name]=min(4,failures[task.name]+1)
                    code='device.protocol_error' if isinstance(exc,(ValueError,UnicodeError)) else 'device.connection_error'
                    with self._state_lock: self._state.update(last_error=str(exc),error_code=code)
                    self._event(str(exc),code,operation=task.name)
                    self.stop_event.wait(.5)
                finally:
                    if failures[task.name]:
                        # Do not retry a rejecting/busy inverter at every 5 s tick.
                        due[task.name]=time.monotonic()+min(60,task.interval_s*2**failures[task.name])
                    elif sample is not None or used_ess_at_admission:
                        # A reply read earlier in this window does not buy another full
                        # five seconds starting now: next read follows its request time.
                        due[task.name]=max(time.monotonic()+.1,requested+task.interval_s)
                    else:
                        due[task.name]+=task.interval_s
                        while due[task.name]<=time.monotonic(): due[task.name]+=task.interval_s
            self.stop_event.wait(.1)

class ParameterReader:
    def __init__(self, cfg, monitor, log_service=None):
        self.cfg=cfg; self.monitor=monitor; self.driver=monitor.driver; self.log_service=log_service
        self.stop_event=threading.Event(); self.refresh_event=threading.Event(); self.thread=None
        self._lock=threading.RLock()
        self._state={'status_code':'parameter.waiting','updated':'','error':'','error_code':None,
                     'raw':{},'qpiri_rows':[],'connection_id':None}

    def start(self):
        self.thread=threading.Thread(target=self._run,name='Parameters-'+self.monitor.device_id,daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set(); self.refresh_event.set()
        if self.thread: self.thread.join(timeout=4)

    def request_refresh(self): self.refresh_event.set()

    def snapshot(self):
        with self._lock:
            state=copy.deepcopy(self._state)
        state['status']=text(state['status_code'])
        state['stale']=state['status_code']!='parameter.current' or not self.monitor.transport.connected or state['connection_id']!=self.monitor.transport.connection_id
        return state

    def _refresh(self):
        if not self.monitor.transport.connected:
            with self._lock: self._state['status_code']='parameter.offline'
            return False
        connection=self.monitor.transport.connection_id
        with self._lock: self._state.update(status_code='parameter.reading',error='',error_code=None)
        try:
            raw={}
            for name in self.driver.identity_names:
                if self.stop_event.is_set(): return False
                raw[name]=self.monitor.query_read(name)
                if connection!=self.monitor.transport.connection_id: raise ConnectionError('Device connection changed during parameter read')
            try:
                raw['QFLAG']=self.monitor.query_read('QFLAG')
            except Exception:
                # Optional flags remain unavailable; never stamp old values as fresh.
                pass
            rows=self.driver.parameter_rows_from_raw(raw)
            getattr(self.driver,'set_grid_identity',lambda *args:None)(raw,connection)
            with self._lock:
                self._state.update(status_code='parameter.current',updated=datetime.now().isoformat(sep=' ',timespec='seconds'),
                    raw=raw,qpiri_rows=rows,error='',error_code=None,connection_id=connection)
            self.monitor._event('Inverter parameters refreshed','device.parameters_refreshed')
            return True
        except Exception as exc:
            if self.stop_event.is_set(): return False
            with self._lock: self._state.update(status_code='parameter.error',error=str(exc),error_code='device.parameter_read_failed')
            self.monitor._event(str(exc),'device.parameter_read_failed')
            return False

    def _run(self):
        due=0; previous=None; failures=0
        while not self.stop_event.is_set():
            conn=self.monitor.transport.connection_id if self.monitor.transport.connected else None
            forced=self.refresh_event.is_set() or conn is not None and conn!=previous
            if conn!=previous: failures=0
            previous=conn
            if forced or time.monotonic()>=due:
                self.refresh_event.clear()
                if self._refresh():
                    failures=0
                    delay=max(60,self.cfg.parameter_refresh_s)
                else:
                    failures=min(5,failures+1)
                    delay=min(300,10*2**failures)
                due=time.monotonic()+delay
            self.stop_event.wait(.5)
