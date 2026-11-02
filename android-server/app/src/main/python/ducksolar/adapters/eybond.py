from __future__ import annotations

import socket
import threading
import time
import queue
from collections import OrderedDict
from datetime import datetime, timezone
from ..protocol.ess_shadow import ESSShadow,native_read,decode_live
from uuid import uuid4
from ..transport.tcp import TCPListenerTransport, LWIPDisconnected


class EyeBondAdapter(TCPListenerTransport):
    """One LWIP reader; transparent raw cloud stream and correlated local reads.

    TCP chunks are forwarded byte-for-byte, even if unknown/malformed. Only a
    reply correlated to an injected local read is consumed by the monitor.
    A short gate protects writes only. ESS never waits for a local reply;
    new local reads yield to ESS startup, requests and outstanding replies.
    """
    capabilities = {'channels':[0], 'multiple_devices':True, 'raw_proxy':True, 'polling':True, 'push':False, 'reconnect':True}

    def __init__(self, cfg, event_callback=None, cloud_callback=None, log_service=None, targets=None, logger_id='logger-1'):
        self.targets = {}
        for route,target in (targets or {}).items():
            if len(route)==3:
                channel,code,address=route
                if channel not in self.capabilities['channels']:raise ValueError('Unsupported EyeBond channel')
                route=(code,address)
            self.targets[route]=target
        self.logger_id = logger_id
        self.measurement_connections = {}
        self.measurement_times = {}
        self.measurement_sources = {}
        self.reply_times = {}
        self._local_durations = {}
        self._listening = threading.Event()
        self._startup_error = None
        super().__init__(cfg, event_callback)
        self.logs = log_service
        self.cloud_callback = cloud_callback
        self._gate = threading.RLock()
        self._local_transaction = threading.RLock()
        self._cloud_waiting = threading.Event()
        self._cloud_not_before = 0.0
        self._pending_lock = threading.RLock()
        self._pending = None
        self._retired = OrderedDict()
        self._cloud_lock = threading.RLock()
        self._cloud = None
        self._cloud_thread = None
        self._reader_thread = None
        self.connection_id = ''
        self.measurement_connection_id = ''
        self._last_cloud_data = 0.0
        self._cloud_state = 'DISCONNECTED'
        self._health_lock=threading.Lock()
        self._health={}
        self._cloud_seen_tids = OrderedDict()
        self.shadow = ESSShadow(self.targets)
        self._tx = queue.Queue(maxsize=64)
        self._tx_thread = None
        self._heartbeat_thread = None
        self._last_native_heartbeat = 0.0
        self._observe_buffers = {}
        self._observe_lock = threading.RLock()
        self._cloud_ready = False
        self._pending_at = {}
        self.native_route = None
        if getattr(cfg,'native_cloud_route',False):
            from .native_route import NativeRoute
            self.native_route = NativeRoute(self)

    def create_channel(self,definition):
        return DeviceChannel(self,definition)

    def _channel_activity(self,channel,size):
        with self._health_lock:
            self._health[channel+'_monotonic']=time.monotonic()
            self._health[channel+'_bytes']=self._health.get(channel+'_bytes',0)+size

    def health_snapshot(self):
        now=time.monotonic()
        with self._health_lock: result=dict(self._health)
        for key,value in list(result.items()):
            if key.endswith('_monotonic'):
                result[key.removesuffix('_monotonic')+'_age_s']=round(max(0,now-value),3)
                del result[key]
        result.update(cloud=('STALE' if self._cloud_state=='CONNECTED' and now-self._last_cloud_data>300 else self._cloud_state),cloud_transport=self._cloud_state,queued_cloud_bytes=self._tx.qsize()*4096,
                      logger_connection=self.connection_id,equipment_mode=self.cfg.equipment_mode)
        return result

    def _traffic(self, direction, data, forwarding, **details):
        if self.logs:
            try:
                self.logs.traffic(direction, data, self.connection_id, forwarding=forwarding, logger_id=self.logger_id, **details)
            except Exception as exc:
                self._event(f'Protocol log error: {exc}')

    def _observe(self, direction, data):
        try:
            previous=self.shadow.snapshot()['cloud_reads']
            self.shadow.feed('request' if direction == 'SmartESS Server -> LWIP' else 'response', data)
            if direction == 'LWIP -> SmartESS Server' and self.shadow.snapshot()['cloud_reads']>previous:
                self._cloud_status('CONNECTED')
            self._observe_frames(direction, data)
        except Exception as exc:
            self._ess_event('ess.shadow_error', error=str(exc))

    def _observe_frames(self, direction, data):
        # Packet reconstruction is diagnostic only: raw chunks have already
        # been logged and forwarded without waiting for this decoder.
        with self._observe_lock:
            buffer = self._observe_buffers.setdefault(direction, bytearray())
            buffer.extend(data)
            while buffer:
                if buffer.startswith(b'AT+'):
                    end = buffer.find(b'\r\n')
                    if end < 0:
                        if len(buffer)>8192: buffer.clear()
                        return
                    count = end+2
                elif len(buffer)<6: return
                else:
                    length = int.from_bytes(buffer[4:6], 'big')
                    if length<2 or length>8192:
                        del buffer[0]; continue
                    count = 6+length
                    if len(buffer)<count: return
                frame=bytes(buffer[:count]);del buffer[:count]
                if not frame.startswith(b'AT+') and direction.startswith('SmartESS'):
                    now = time.monotonic()
                    self._cloud_seen_tids[int.from_bytes(frame[:2],'big')] = now
                    if direction == 'SmartESS Server -> LWIP':
                        # Once ESS reuses a retired local ID, its real replies must pass.
                        codes=(1,0x0102) if int.from_bytes(frame[2:4],'big') in (1,0x0102) else (int.from_bytes(frame[2:4],'big'),)
                        with self._pending_lock:
                            for code in codes:
                                self._retired.pop(frame[:2]+code.to_bytes(2,'big')+frame[6:8],None)
                    for tid, stamp in list(self._cloud_seen_tids.items()):
                        if now-stamp > 30: self._cloud_seen_tids.pop(tid, None)
                    while len(self._cloud_seen_tids)>512: self._cloud_seen_tids.popitem(last=False)
                if direction == 'SmartESS Server -> LWIP' and frame in (b'AT+DTUPN?\r\n', b'AT+HTBT?\r\n'):
                    self._pending_at.setdefault(frame, time.monotonic() + 1.0)
                    if self._cloud_state != 'CONNECTED': self._cloud_status('HANDSHAKING')
                elif direction == 'LWIP -> SmartESS Server':
                    if frame.startswith(b'AT+DTUPN:'):
                        self._pending_at.pop(b'AT+DTUPN?\r\n', None)
                    elif frame == b'AT+HTBT\r\n':
                        self._pending_at.pop(b'AT+HTBT?\r\n', None)
                    elif len(frame)>8 and int.from_bytes(frame[:2], 'big') in self._cloud_seen_tids and frame[7]==4:
                        target = self.targets.get((int.from_bytes(frame[2:4], 'big'),frame[6]))
                        if target and target['valid_response'](frame[8:]): self._cloud_status('CONNECTED')
                self._traffic(direction,frame,'observed_packet',result='reassembled')

    def _handshake_fallback(self, sock):
        # Native ESS uses binary metadata; never invent an AT or binary reply.
        return

    def _cloud_status(self, state):
        if state != self._cloud_state:
            self._event(f'Cloud {state.lower()}')
            self._ess_event('ess.state_changed', previous=self._cloud_state, state=state)
        self._cloud_state = state
        if self.cloud_callback: self.cloud_callback(state)

    def _ess_event(self, code, **details):
        connection=details.pop('connection_id',self.connection_id)
        if self.logs:
            self.logs.ess_event(code, logger_id=self.logger_id, connection_id=connection,
                                host=self.cfg.cloud_host, port=self.cfg.cloud_port, **details)

    @staticmethod
    def _close(sock):
        if sock:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: sock.close()
            except OSError: pass

    def _close_cloud(self):
        with self._cloud_lock:
            sock, self._cloud = self._cloud, None
            self._cloud_ready = False
        self._close(sock)

    def close_active(self, reason=''):
        # Reader/send paths never hold the gate while waiting for this lock.
        super().close_active(reason)
        self._close_cloud()
        with self._pending_lock:
            if self._pending:
                self._pending['error'] = LWIPDisconnected(reason or 'LWIP disconnected')
                self._pending['done'].set()

    def start(self):
        if self._listener_thread and self._listener_thread.is_alive(): return
        super().start()
        if not self._listening.wait(3): raise TimeoutError('Logger listener startup timed out')
        if self._startup_error: raise OSError(self._startup_error)
        self._tx_thread = threading.Thread(target=self._cloud_sender, name='ESSSender', daemon=True)
        self._tx_thread.start()
        self._heartbeat_thread = threading.Thread(target=self._offline_heartbeat, name='LoggerHeartbeat', daemon=True)
        if self.cfg.equipment_mode!='relay_only':self._heartbeat_thread.start()
        if self.cfg.cloud_proxy_enabled:
            self._cloud_thread = threading.Thread(target=self._cloud_loop, name='TransparentCloud', daemon=True)
            self._cloud_thread.start()
        else: self._cloud_status('DISABLED')
        if self.native_route:
            self.native_route.start()

    def stop(self):
        if self.native_route:
            self.native_route.stop()
        super().stop()
        for worker in (self._reader_thread, self._cloud_thread, self._listener_thread, self._tx_thread, self._heartbeat_thread):
            if worker and worker.ident is not None and worker is not threading.current_thread(): worker.join(timeout=3)

    def _listener_loop(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener = srv
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            port=self.cfg.native_logger_port if self.native_route else self.cfg.local_server_port
            srv.bind(('0.0.0.0', port)); srv.listen(2); srv.settimeout(.5)
            self._set_state('WAITING'); self._listening.set()
            while not self._stop.is_set():
                try: sock, addr = srv.accept()
                except socket.timeout: continue
                except OSError:
                    if self._stop.is_set(): break
                    raise
                if addr[0] != self.cfg.lwip_ip:
                    if not self.native_route or not self.native_route.verify_new_peer(sock,addr[0]):
                        self._event(f'LWIP rejected unexpected peer: {addr[0]}'); self._close(sock); continue
                self.close_active('logger_replaced')
                if self._reader_thread: self._reader_thread.join(timeout=2)
                sock.settimeout(.5)
                with self._socket_lock: self._socket = sock
                self.connection_id = uuid4().hex
                self.shadow.reset(self.connection_id)
                self.measurement_connections.clear()
                self.measurement_times.clear()
                with self._pending_lock: self._retired.clear()
                with self._observe_lock:
                    self._observe_buffers.clear(); self._pending_at.clear(); self._cloud_seen_tids.clear()
                with self._status_lock:
                    self.status.state = 'CONNECTED'; self.status.peer = f'{addr[0]}:{addr[1]}'
                    self.status.last_error = ''; self.status.last_connected_at = time.time()
                self._event(f'LWIP connected: {addr[0]}:{addr[1]} connection={self.connection_id}')
                if self.native_route:self.native_route.connected()
                self._reader_thread = threading.Thread(target=self._read_lwip, args=(sock,), name='LWIPReader', daemon=True)
                self._reader_thread.start()
        except Exception as exc:
            self._startup_error=str(exc); self._listening.set()
            self._set_state('ERROR', str(exc)); self._event(f'LWIP listener error: {exc}')
        finally:
            self._close(srv); self._listener = None

    def _to_cloud(self, data):
        if not data: return
        with self._cloud_lock:
            cloud = self._cloud if self._cloud_ready else None
        if cloud is None:
            self._observe('LWIP -> SmartESS Server', data)
            self._traffic('LWIP -> SmartESS Server', data, 'cloud_unavailable'); return
        # Small chunks bound queue memory at 256KiB; never block the local reader.
        for offset in range(0, len(data), 4096):
            try: self._tx.put_nowait((cloud, data[offset:offset+4096]))
            except queue.Full:
                self._ess_event('ess.forward_backpressure', queued_bytes=self._tx.qsize()*4096)
                # Fail the cloud connection rather than silently corrupt its stream.
                self._close_cloud(); self._cloud_status('RETRYING'); return
        # Queue original bytes before diagnostic decoding/writes can delay ESS.
        self._observe('LWIP -> SmartESS Server', data)

    def _cloud_sender(self):
        while not self._stop.is_set():
            try: sock, data = self._tx.get(timeout=.25)
            except queue.Empty: continue
            try:
                with self._cloud_lock: current = self._cloud is sock and self._cloud_ready
                if not current: continue  # Never replay responses into a new cloud session.
                sock.sendall(data)
                self._channel_activity('cloud_tx',len(data))
                self._traffic('LWIP -> SmartESS Server', data, 'forwarded')
            except OSError as exc:
                self._ess_event('ess.forward_failed', direction='logger_to_ess', error=str(exc))
                with self._cloud_lock:
                    if self._cloud is sock: self._close_cloud()
            finally: self._tx.task_done()

    def _offline_heartbeat(self):
        while not self._stop.wait(1):
            if self.cfg.cloud_port != 502 or not self.connected: continue
            with self._cloud_lock: ready = self._cloud_ready
            if ready or time.monotonic()-self._last_native_heartbeat < 30: continue
            self._last_native_heartbeat = time.monotonic()
            now = datetime.now(timezone.utc)
            body = bytes((now.year-2000, now.month, now.day, now.hour, now.minute, now.second))+b'\x00\x23'
            try:
                self._wire_transact(body, 1, 255, 1, (1, 0x0102), 'HEARTBEAT', timeout=2)
                self._ess_event('ess.offline_logger_heartbeat', result='reply')
            except Exception as exc:
                if not self._stop.is_set(): self._ess_event('ess.offline_logger_heartbeat', result='failed', error=str(exc))

    def _read_lwip(self, sock):
        buffered=bytearray(); buffered_at=time.monotonic()
        try:
            while not self._stop.is_set():
                try: data=sock.recv(65536)
                except socket.timeout:
                    # Opaque/non-framed data must not wait indefinitely for a decoder.
                    with self._pending_lock: p=self._pending
                    possible_local=bool(p and any(buffered.startswith(prefix) for prefix in p['prefixes']))
                    if buffered and not possible_local and time.monotonic()-buffered_at>1:
                        self._to_cloud(bytes(buffered));buffered.clear()
                    continue
                if not data: raise LWIPDisconnected('LWIP closed TCP connection')
                self._channel_activity('logger_rx',len(data))
                self._traffic('LWIP -> Server',data,'received',result='tcp_chunk')
                if not buffered: buffered_at=time.monotonic()
                buffered.extend(data);forward=bytearray()
                while buffered:
                    if buffered.startswith(b'AT+'):
                        end=buffered.find(b'\r\n')
                        if end<0: break
                        count=end+2
                    elif len(buffered)<8: break
                    else:
                        length=int.from_bytes(buffered[4:6],'big')
                        if not 2<=length<=8192:
                            forward.append(buffered[0]);del buffered[0];continue
                        count=length+6
                        if len(buffered)<count: break
                    frame=bytes(buffered[:count]);del buffered[:count]
                    handled=False
                    with self._pending_lock:
                        p=self._pending
                        if p and not p['done'].is_set() and any(frame.startswith(prefix) for prefix in p['prefixes']) and frame[6:8]==p['address_function']:
                            p['response']=frame[8:]
                            if not p['response']: p['error']=ValueError('Empty EyeBond response')
                            elif p['telemetry']:
                                self.measurement_connections[p['route']]=p['connection_id']
                                self.measurement_times[p['route']]=(p['sent'],time.monotonic())
                                self.measurement_connection_id=p['connection_id']
                            for prefix in p['prefixes']: self._retired[prefix+p['address_function']]=time.monotonic()+30
                            while len(self._retired)>128: self._retired.popitem(last=False)
                            p['done'].set();handled=True
                            with self._status_lock: self.status.last_response_at=time.time()
                            self._traffic('LWIP -> Server',frame,'local_write_response' if p['command']=='WRITE' else 'local_read_response',
                                result='matched',command=p['command'],device_id=p['device_id'])
                        elif not frame.startswith(b'AT+'):
                            key=frame[:4]+frame[6:8]
                            expiry=self._retired.get(key,0)
                            if expiry>time.monotonic():
                                if key == getattr(self,'_local_recovery_key',None):
                                    self._local_not_before=0
                                    self._local_recovery_key=None
                                handled=True
                                self._traffic('LWIP -> Server',frame,'local_late_or_duplicate_response',result='consumed')
                    if not handled: forward.extend(frame)
                self._to_cloud(bytes(forward))
                if len(buffered)>16384:
                    self._to_cloud(bytes(buffered));buffered.clear()
        except Exception as exc:
            with self._socket_lock: expected_close=self._socket is not sock or self._stop.is_set()
            if not expected_close: self._event(f'LWIP read error: {exc}')
        finally:
            self._to_cloud(bytes(buffered))
            with self._socket_lock:
                if self._socket is sock: self.close_active('LWIP reader stopped')

    def transact(self, request, device_code, address):
        if self.cfg.equipment_mode=='relay_only':
            raise RuntimeError('Local commands disabled in cloud relay diagnostic mode')
        route=(device_code,address)
        target=self.targets.get(route)
        command=target['requests'].get(request) if target else None
        if command is None and target and target.get('write_validator',lambda r:False)(request):command='WRITE'
        if command is None: raise ValueError('Unsupported local command')
        return self._wire_transact(request, device_code, address, 4, (device_code,), command,
                                   route=route, target=target, timeout=min(10, max(3,self.cfg.socket_timeout_s)) if command in ('QPIGS','QMOD','QPIWS') else self.cfg.socket_timeout_s)

    def _wire_transact(self, request, device_code, address, function, response_codes, command,
                       route=None, target=None, timeout=3):
        with self._local_transaction:
            # Never hold the forwarding gate during waits. A pending ESS request
            # wins admission; an already sent local request remains correlated.
            from ..protocol.deadline import deadline as current_deadline,admission_end
            outer=current_deadline.get()
            deadline=admission_end(time.monotonic(),timeout,outer)
            while True:
                if self._stop.is_set(): raise LWIPDisconnected('Server stopping')
                if time.monotonic()>=deadline:raise TimeoutError('ESS admission deadline; request not sent')
                if self.native_route and not self.native_route.polling_allowed():
                    if time.monotonic()>=deadline:raise TimeoutError('Native ESS startup; local read deferred')
                    self._stop.wait(.025);continue
                if command=='NATIVE4501' and route:
                    with self._cloud_lock: ready=self._cloud_ready
                    with self.shadow.lock:
                        candidate=self.shadow.samples.get((route,'QPIGS'))
                        eligible=ready and candidate is not None and candidate.values is not None
                    sample=self.shadow.take(route,'QPIGS',self.measurement_times.get(route,(float('-inf'),0))[0]) if eligible else None
                    if sample is not None:
                        self.measurement_times[route]=(sample.requested,sample.received)
                        self.measurement_connections[route]=sample.connection
                        self.measurement_sources[route]='ESS'
                        self._ess_event('ess.local_sample_reused',device_id=target['device_id'],operation='QPIGS',native=True,at_admission=True)
                        return sample.payload
                with self._cloud_lock: ready = self._cloud_ready
                busy = time.monotonic()<getattr(self,'_local_not_before',0) or ready and (self._cloud_waiting.is_set() or
                    time.monotonic()<self._cloud_not_before or self.shadow.in_flight() or
                    self.shadow.approaching_live_read(self._local_durations.get(command,.8)))
                if busy:
                    if time.monotonic()>=deadline: raise TimeoutError('ESS busy; local read deferred')
                    self._stop.wait(.01); continue
                self._gate.acquire()
                with self._cloud_lock: ready = self._cloud_ready
                if time.monotonic()<getattr(self,'_local_not_before',0) or ready and (self._cloud_waiting.is_set() or
                    time.monotonic()<self._cloud_not_before or self.shadow.in_flight() or
                    self.shadow.approaching_live_read(self._local_durations.get(command,.8))):
                    self._gate.release(); continue
                break
            try:
                with self._socket_lock:
                    sock = self._socket
                    if sock is None: raise LWIPDisconnected('LWIP not connected')
                for _ in range(65535):
                    tid = self._next_tid()
                    with self._observe_lock, self._pending_lock:
                        if tid not in self._cloud_seen_tids and not any(key[:2]==tid.to_bytes(2,'big') and expiry>time.monotonic() for key,expiry in self._retired.items()): break
                else: raise TimeoutError('No free local transaction IDs')
                p = dict(prefixes=[tid.to_bytes(2,'big')+code.to_bytes(2,'big') for code in response_codes],
                         done=threading.Event(), command=command, connection_id=self.connection_id,
                         route=route, address_function=bytes((address,function)),
                         device_id=target['device_id'] if target else self.logger_id,
                         sent=time.monotonic(),telemetry=bool(target and (request in target['telemetry_requests'] or command=='NATIVE4501')))
                with self._pending_lock: self._pending = p
                frame = self.build_frame(tid,device_code,address,function,request)
                try:
                    sock.sendall(frame)
                    self._channel_activity('logger_tx',len(frame))
                except Exception:
                    with self._pending_lock: self._pending = None
                    raise
            finally:
                self._gate.release()
            self._traffic('Server -> LWIP', frame, 'local_write_sent' if command=='WRITE' else 'local_read_sent',
                          result='sent', command=command, device_id=p['device_id'])
            try:
                remaining=timeout if outer is None else min(timeout,max(0,outer-time.monotonic()))
                if not p['done'].wait(remaining):
                    # Do not immediately stack fallback/next commands on a
                    # logger which is still completing the timed-out request.
                    self._local_not_before=max(getattr(self,'_local_not_before',0),p['sent']+9)
                    self._local_recovery_key=p['prefixes'][0]+p['address_function']
                    raise TimeoutError(f'{command} timeout')
                if 'error' in p: raise p['error']
                from ..protocol.deadline import learned_duration
                elapsed=time.monotonic()-p['sent']
                self._local_durations[command]=min(10,max(.1,elapsed)) if command=='WRITE' else learned_duration(self._local_durations.get(command,.8),elapsed)
                if route and target and command!='WRITE':
                    # Connection health observes only validated replies from this
                    # exact route/connection. It never renews measurement age.
                    try:
                        valid=decode_live(p['response'],45) is not None if command=='NATIVE4501' else target['valid_response'](p['response'])
                        if valid and command!='NATIVE4501' and 'decode_response' in target:target['decode_response'](p['response'],command)
                    except Exception:valid=False
                    if valid:
                        with self._pending_lock:self.reply_times[route]=(p['connection_id'],time.monotonic())
                if route and p['telemetry']:self.measurement_sources[route]='Local'
                return p['response']
            finally:
                with self._pending_lock:
                    if self._pending is p: self._pending = None
                    for prefix in p['prefixes']: self._retired[prefix+p['address_function']]=time.monotonic()+30
                    while len(self._retired)>128: self._retired.popitem(last=False)

    def _cloud_loop(self):
        failures = 0
        while not self._stop.is_set():
            if not self.connected:
                self._cloud_status('DISCONNECTED'); self._stop.wait(.5); continue
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)
            for option,value in [('TCP_KEEPIDLE',60),('TCP_KEEPINTVL',20),('TCP_KEEPCNT',3)]:
                if hasattr(socket,option):
                    try:sock.setsockopt(socket.IPPROTO_TCP,getattr(socket,option),value)
                    except OSError:pass
            with self._cloud_lock:
                self._cloud = sock; self._cloud_ready = False
            attempt_connection=self.connection_id
            attempt_started = time.monotonic()
            received_bytes = 0
            close_reason = 'logger_disconnected'
            try:
                self._cloud_status('CONNECTING')
                self._ess_event('ess.connect_started', connection_id=attempt_connection, failure_count=failures)
                sock.connect((self.cfg.cloud_host, self.cfg.cloud_port)); sock.settimeout(.5)
                self._ess_event('ess.tcp_connected', connection_id=attempt_connection, peer_ip=sock.getpeername()[0],
                                connect_ms=round((time.monotonic()-attempt_started)*1000, 1))
                with self._cloud_lock: self._cloud_ready = True
                self._cloud_not_before = time.monotonic()+1
                self.shadow.cloud_reconnected()
                with self._observe_lock:
                    self._pending_at.clear(); self._observe_buffers.clear()
                self._cloud_status('TCP_CONNECTED'); started = time.monotonic();self._last_cloud_data=started
                while not self._stop.is_set() and self.connected:
                    try: data = sock.recv(65536)
                    except socket.timeout:
                        self._handshake_fallback(sock)
                        if time.monotonic()-self._last_cloud_data>600:raise TimeoutError('ESS idle for 600s; reconnecting cloud channel only')
                        continue
                    if not data: raise ConnectionError('SmartESS Server closed TCP connection')
                    self._channel_activity('cloud_rx',len(data))
                    received_bytes += len(data)
                    received_stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
                    self._cloud_waiting.set()
                    self._last_cloud_data = time.monotonic()
                    # Keep startup/burst quiet time: do not insert a local read
                    # between metadata and the next ESS register-bank request.
                    self._cloud_not_before = max(self._cloud_not_before,time.monotonic()+.35)
                    try:
                        self.shadow.feed('request', data)
                        with self._gate, self._socket_lock:
                            peer = self._socket
                            if peer is None: raise LWIPDisconnected('LWIP not connected')
                            peer.sendall(data)
                            self._channel_activity('logger_tx',len(data))
                    finally: self._cloud_waiting.clear()
                    self._traffic('SmartESS Server -> Server', data, 'received', result='tcp_chunk',timestamp=received_stamp)
                    self._traffic('SmartESS Server -> LWIP', data, 'forwarded', result='tcp_chunk')
                    self._observe_frames('SmartESS Server -> LWIP', data)
                    self._handshake_fallback(sock)
                if time.monotonic()-started > 300: failures = 0
            except Exception as exc:
                close_reason = str(exc)
                with self._cloud_lock: cloud_replaced=self._cloud is not sock
                if cloud_replaced or self.connection_id!=attempt_connection:close_reason='logger_replaced_or_locally_closed'
                expected_close=cloud_replaced or not self.connected
                if not self._stop.is_set() and not expected_close:
                    failures += 1; self._event(f'Cloud reconnect: {exc}')
                    self._ess_event('ess.connect_or_stream_failed', connection_id=attempt_connection, error=str(exc), failure_count=failures)
                    self._cloud_status('SERVER_UNAVAILABLE' if failures >= 3 else 'RETRYING')
            finally:
                with self._cloud_lock:
                    if self._cloud is sock:
                        self._cloud = None; self._cloud_ready = False
                self._close(sock)
                if (self._stop.is_set() or not self.connected) and self.connection_id==attempt_connection:
                    self._cloud_status('DISCONNECTED')
                self._ess_event('ess.connection_closed', connection_id=attempt_connection, reason='server_stopping' if self._stop.is_set() else close_reason,
                                duration_s=round(time.monotonic()-attempt_started, 3), received_bytes=received_bytes)
            delay = min(30, 2 * 2**min(failures, 4))
            if not self._stop.is_set(): self._ess_event('ess.retry_scheduled', connection_id=attempt_connection, retry_s=delay, failure_count=failures)
            self._stop.wait(delay)
        self._cloud_status('DISCONNECTED')

    def detect_lan_ip(self) -> str:
        from ..network_info import logger_route
        route=logger_route(self.cfg.lwip_ip)
        self._logger_network_binding=route
        with self._status_lock:
            self.status.lan_ip=route['source']
        return route['source']

    def send_redirect(self) -> str:
        if self.native_route:
            return self.native_route.request()
        lan_ip = self.detect_lan_ip()
        message = f"set>server={lan_ip}:{self.cfg.local_server_port};".encode("ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            from ..network_info import bind_logger_socket
            bind_logger_socket(s,self.cfg.lwip_ip)
            s.settimeout(2.0)
            s.sendto(message, (self.cfg.lwip_ip, self.cfg.lwip_redirect_port))
        self._set_state("WAITING")
        self._event(f"LWIP redirect → {lan_ip}:{self.cfg.local_server_port}")
        return lan_ip


    def _next_tid(self):
        self._tid=(self._tid+1)&0xffff
        self._tid = self._tid or 1
        return self._tid

    @staticmethod
    def build_frame(tid, device_code, address, function, payload):
        return tid.to_bytes(2,'big')+device_code.to_bytes(2,'big')+(len(payload)+2).to_bytes(2,'big')+bytes((address,function))+payload

class DeviceChannel:
    def __init__(self, adapter, definition):
        if definition.channel not in adapter.capabilities['channels']:
            raise ValueError('Unsupported channel for current datalogger adapter')
        self.adapter=adapter; self.definition=definition
    @property
    def connected(self): return self.adapter.connected
    @property
    def connection_id(self): return self.adapter.connection_id
    @property
    def measurement_connection_id(self):
        return self.adapter.measurement_connections.get((self.definition.device_code,self.definition.address),'')
    @property
    def inverter_reply_age(self):
        with self.adapter._pending_lock:item=self.adapter.reply_times.get((self.definition.device_code,self.definition.address))
        return max(0,time.monotonic()-item[1]) if item and item[0]==self.connection_id else None
    def transact(self, request): return self.adapter.transact(request,self.definition.device_code,self.definition.address)
    def take_cloud_sample(self, operation, since):
        with self.adapter._cloud_lock:
            if not self.adapter._cloud_ready: return None
        sample = self.adapter.shadow.take((self.definition.device_code,self.definition.address), operation, since)
        if sample:
            route=(self.definition.device_code,self.definition.address)
            self.adapter.measurement_connections[route]=sample.connection
            self.adapter.measurement_times[route]=(sample.requested,sample.received)
            self.adapter._ess_event('ess.local_sample_reused', device_id=self.definition.id,
                                   operation=operation, native=sample.values is not None,
                                   age_s=round(time.monotonic()-sample.requested,3))
        return sample
    @property
    def native_auxiliary(self):
        return self.adapter.shadow.auxiliary((self.definition.device_code,self.definition.address))
    def wait_cloud_idle(self, max_wait=1):
        with self.adapter._cloud_lock:
            if not self.adapter._cloud_ready: return
        deadline=time.monotonic()+max_wait
        while self.adapter.shadow.in_flight() and time.monotonic()<deadline:
            if self.adapter._stop.wait(.025): return
    @property
    def native_ready(self):
        with self.adapter.shadow.lock:
            return self.adapter.shadow.calibration.get((self.definition.device_code,self.definition.address),0)>=3
    @property
    def measurement_requested_monotonic(self):
        return self.adapter.measurement_times.get((self.definition.device_code,self.definition.address),(time.monotonic(),0))[0]
    @property
    def measurement_received_monotonic(self):
        return self.adapter.measurement_times.get((self.definition.device_code,self.definition.address),(0,time.monotonic()))[1]
    @property
    def measurement_source(self):
        return self.adapter.measurement_sources.get((self.definition.device_code,self.definition.address),'Local')
    def read_native(self):
        route=(self.definition.device_code,self.definition.address)
        target=self.adapter.targets[route]
        try:
            body=self.adapter._wire_transact(native_read(),1,255,4,(1,0x0102),'NATIVE4501',
                route=route,target=target,timeout=min(3,self.adapter.cfg.socket_timeout_s))
            if decode_live(body,45) is None: raise ValueError('Invalid local native telemetry')
            return body
        except (ValueError,UnicodeError):
            # A malformed native response invalidates the mapping. A timeout
            # says nothing about the mapping already checked on this connection.
            with self.adapter.shadow.lock: self.adapter.shadow.calibration[route]=0
            raise
    def calibrate_cloud_sample(self, values):
        before=self.adapter.shadow.snapshot()
        self.adapter.shadow.calibrate((self.definition.device_code,self.definition.address), values)
        after=self.adapter.shadow.snapshot()
        if after['calibration_matches']!=before['calibration_matches'] or after['calibrated']!=before['calibrated']:
            self.adapter._ess_event('ess.native_calibration',device_id=self.definition.id,
                matches=after['calibration_matches'],calibrated=after['calibrated'])
    def snapshot_status(self): return self.adapter.snapshot_status()
    @property
    def automatic_recovery_managed(self): return self.adapter.native_route is not None
    def send_redirect(self): return self.adapter.send_redirect()
