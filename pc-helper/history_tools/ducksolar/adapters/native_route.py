"""Verified legacy EyeBond cloud routing, identity and bounded LAN recovery.

The management callback is temporary. Runtime data uses the logger's native
host-only cloud endpoint plus separate parameter24 port; UDP callbacks are
never a polling timer. Android listens on an unprivileged port.
"""
from __future__ import annotations
import ipaddress
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path


class DataChannelRecovered(Exception):
    """Data reconnected before management writes; no reprovision is needed."""

class NativeRoute:
    def __init__(self, adapter):
        self.adapter = adapter
        self.cfg = adapter.cfg
        name = ''.join(c for c in adapter.logger_id if c.isalnum() or c in '-_')
        self.path = Path(self.cfg.root_dir)/'Server'/'NativeRoutes'/(name+'.json')
        self.lock = threading.RLock()
        self.record_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.network_wake = threading.Event()
        self.thread = None
        self.listener = None
        self.lifecycle_lock = threading.RLock()
        self.record = {}
        self.state = 'WAITING'
        self.last_error = ''
        self.connected_at = 0.0
        self._tid = 0xc100
        if self.path.exists():
            self.record = json.loads(self.path.read_text(encoding='utf-8'))
            if self.record.get('pn') != self.cfg.dtu_pn:
                raise ValueError('Збережений маршрут належить іншому PN логера')
            endpoint = self.record.get('original_endpoint', '')
            if endpoint:
                self.cfg.cloud_host = endpoint
                self.cfg.cloud_port = int(self.record.get('original_port',502))
            saved_ip = self.record.get('logger_ip', '')
            if saved_ip and self._local_ip(saved_ip):
                self.cfg.lwip_ip = saved_ip

    @staticmethod
    def _local_ip(value):
        try:
            ip = ipaddress.ip_address(value)
            return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_multicast
        except ValueError:
            return False

    def _event(self, code, **fields):
        self.adapter._ess_event('ess.native_route.'+code, **fields)

    def _save(self, **fields):
        with self.record_lock:
            self.record.update(fields)
            self.record['pn'] = self.cfg.dtu_pn
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            with temp.open('w', encoding='utf-8') as out:
                json.dump(self.record, out, ensure_ascii=False, indent=2)
                out.flush(); os.fsync(out.fileno())
            os.replace(temp, self.path)

    def snapshot(self):
        with self.record_lock:
            return dict(state=self.state, logger_ip=self.cfg.lwip_ip,
                        logger_mac=self.cfg.logger_mac, original_endpoint=self.record.get('original_endpoint',''),
                        native_port=self.cfg.native_logger_port, management_port=self.cfg.logger_management_port,
                        original_port=self.record.get('original_port',502),
                        last_error=self.last_error, route_owned=self.record.get('active',False),
                        recovery_pending=self.state=='RESTORE_PENDING')

    def start(self):
        with self.lifecycle_lock:
            return self._start_locked()

    def _start_locked(self):
        # Bind both ports before any configuration of the physical logger.
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            self.listener.bind(('0.0.0.0',self.cfg.logger_management_port))
            self.listener.listen(4); self.listener.settimeout(.3)
        except BaseException:
            self.listener.close(); self.listener = None
            raise
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name='NativeRoute-'+self.adapter.logger_id, daemon=True)
        self.thread.start()

    def request(self):
        self.wake.set()
        return self.adapter.detect_lan_ip()

    def network_changed(self):
        # Only a newly usable/different route bypasses failure backoff.
        self.network_wake.set()
        self.wake.set()

    def _route_available(self):
        from ..network_info import logger_route
        try:
            logger_route(self.cfg.lwip_ip)
            return True
        except OSError:
            return False

    def _redirect(self, host, port, target=None):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            from ..network_info import bind_logger_socket
            bind_logger_socket(udp,self.cfg.lwip_ip)
            udp.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
            udp.sendto(f'set>server={host}:{port};'.encode('ascii'),
                       (target or self.cfg.lwip_ip,self.cfg.lwip_redirect_port))

    def _arp_candidate(self):
        expected = self.cfg.logger_mac.lower().replace('-',':')
        try:
            rows = Path('/proc/net/arp').read_text().splitlines()[1:]
        except OSError:
            return None
        for row in rows:
            parts = row.split()
            if len(parts)>=4 and parts[3].lower()==expected and self._local_ip(parts[0]):
                return parts[0]
        return None

    @staticmethod
    def _broadcast_address(lan):
        # Android interface prefix is authoritative; do not assume /24.
        try:
            from ..network_info import wifi_snapshot
            snapshot=wifi_snapshot()
            if snapshot is not None:
                for row in snapshot.get('wifi',[]):
                    for value in row.get('addresses',[]):
                        interface=ipaddress.ip_interface(value)
                        if interface.version==4 and str(interface.ip)==lan:
                            return str(interface.network.broadcast_address)
            from java import jclass
            interfaces = jclass('java.net.NetworkInterface').getNetworkInterfaces()
            while interfaces.hasMoreElements():
                addresses = interfaces.nextElement().getInterfaceAddresses().iterator()
                while addresses.hasNext():
                    item = addresses.next()
                    if str(item.getAddress().getHostAddress())==lan and item.getBroadcast() is not None:
                        return str(item.getBroadcast().getHostAddress())
        except Exception:
            pass
        return '255.255.255.255'

    def _session(self, discover=True, restoring=False):
        lan = self.adapter.detect_lan_ip()
        started = time.monotonic(); next_send = started+3; broadcast = False
        if not restoring and self.adapter.connected:
            raise DataChannelRecovered()
        self._redirect(lan,self.cfg.logger_management_port)
        while time.monotonic()-started<30:
            if self.stop_event.is_set() and not restoring:
                raise InterruptedError('Native route setup cancelled')
            if not restoring and self.adapter.connected:
                raise DataChannelRecovered()
            elapsed = time.monotonic()-started
            if time.monotonic()>=next_send:
                if discover and elapsed>=6 and not broadcast:
                    candidate = self._arp_candidate()
                    target = candidate or self._broadcast_address(lan)
                    self._redirect(lan,self.cfg.logger_management_port,target)
                    self._event('discovery_started', method='mac_arp' if candidate else 'udp_callback',target_ip=target,server_ip=lan,logger_ip=self.cfg.lwip_ip)
                    broadcast = True
                else:
                    self._redirect(lan,self.cfg.logger_management_port)
                next_send = time.monotonic()+3
            try:
                peer, address = self.listener.accept()
            except socket.timeout:
                continue
            peer.settimeout(3)
            try:
                if not restoring and self.adapter.connected:
                    peer.close();raise DataChannelRecovered()
                if not self._local_ip(address[0]):
                    raise ValueError('Non-LAN collector callback')
                pn = self.query(peer,2)
                if pn != self.cfg.dtu_pn:
                    # A broadcast may reach another collector. Return its
                    # temporary callback to its unchanged, verified endpoint.
                    endpoint = self.query(peer,21)
                    if endpoint and not self._local_ip(endpoint):
                        try:self._redirect(socket.gethostbyname(endpoint),502,address[0])
                        except OSError:pass
                    raise ValueError('Unexpected collector PN')
                self.adopt(address[0])
                return peer, lan
            except DataChannelRecovered:
                raise
            except Exception as exc:
                self._event('candidate_rejected',ip=address[0],error=str(exc)); peer.close()
        raise TimeoutError('Логер не відповідає; пошук буде повторено з паузою')

    def adopt(self, ip):
        old = self.cfg.lwip_ip
        self.cfg.lwip_ip = ip
        self._save(logger_ip=ip, mac=self.cfg.logger_mac)
        if old!=ip:
            self._event('logger_ip_changed',previous=old,current=ip,pn=self.cfg.dtu_pn)
            self.adapter._event(f'Адресу логера відновлено: {old} → {ip}')

    def _exchange(self, sock, function, payload):
        self._tid=(self._tid+1)&0xffff or 1
        tid=self._tid
        frame=struct.pack('>HHHBB',tid,1,len(payload)+2,255,function)+payload
        sock.sendall(frame)
        self._event('management_sent',function=function,parameter=payload[0],hex=frame.hex())
        deadline=time.monotonic()+5
        def exact(count):
            result=b''
            while len(result)<count:
                if time.monotonic()>deadline:raise TimeoutError('Management frame timed out')
                part=sock.recv(count-len(result))
                if not part:raise ConnectionError('Management socket closed')
                result+=part
            return result
        while time.monotonic()<deadline:
            head=exact(8)
            got,dev,length,addr,fc=struct.unpack('>HHHBB',head)
            if not 2<=length<=8192:raise ValueError('Invalid management frame')
            body=exact(length-2)
            self._event('management_received',hex=(head+body).hex())
            if got==tid and fc==function and dev in (1,0x0102) and addr==255:
                return body
        raise TimeoutError('Management response timed out')

    def query(self, sock, parameter):
        with self.lock:
            body=self._exchange(sock,2,bytes([parameter]))
            if len(body)<2 or body[:2]!=bytes([0,parameter]):
                raise ValueError(f'Collector query {parameter} unconfirmed')
            return body[2:].decode('ascii').strip('\x00')

    def _write(self,sock,parameter,value):
        with self.lock:
            body=self._exchange(sock,3,bytes([parameter])+value.encode('ascii'))
            if len(body)<2 or body[:2]!=bytes([0,parameter]):
                raise ValueError(f'Collector write {parameter} unconfirmed')

    def verify_new_peer(self, sock, ip):
        try:
            if not self._local_ip(ip) or self.query(sock,2)!=self.cfg.dtu_pn:return False
            self.adopt(ip)
            return True
        except Exception as exc:
            self._event('peer_identity_failed',ip=ip,error=str(exc));return False

    def connected(self):
        self.connected_at=time.monotonic()
        self.state='ACTIVE'; self.last_error=''

    def polling_allowed(self):
        age=time.monotonic()-self.connected_at
        if age<3:return False
        with self.adapter._cloud_lock: ready=self.adapter._cloud_ready
        if ready and self.adapter.shadow.snapshot()['cloud_reads']==0 and age<10:return False
        return True

    def _provision(self):
        if self.adapter.connected:
            return
        self.state='CONFIGURING'
        peer,lan=self._session()
        try:
            endpoint=self.query(peer,21)
            port=int(self.query(peer,24))
            if not 1<=port<=65535:raise ValueError('Invalid original cloud port')
            version=self.query(peer,5)
            if version!='3.6.7.6':
                raise ValueError('Native route requires verified EyeBond firmware 3.6.7.6')
            original=self.record.get('original_endpoint','')
            if not original:
                if self._local_ip(endpoint) or endpoint==lan:
                    raise ValueError('Не збережено штатний endpoint ESS; локальну адресу не можна прийняти за ESS')
                original=endpoint
            original_port=int(self.record.get('original_port',port))
            if self.adapter.connected:
                raise DataChannelRecovered()
            # Durable recovery record exists before the first write.
            self._save(original_endpoint=original,original_port=original_port,active=True,server_ip=lan,stage='prepared',firmware=version)
            self.cfg.cloud_host=original;self.cfg.cloud_port=original_port
            if self.stop_event.is_set():raise InterruptedError('Route setup cancelled before write')
            if port!=self.cfg.native_logger_port:self._write(peer,24,str(self.cfg.native_logger_port))
            if int(self.query(peer,24))!=self.cfg.native_logger_port:raise ValueError('Native port readback failed')
            if endpoint!=lan:self._write(peer,21,lan)
            if self.query(peer,21)!=lan:raise ValueError('Native endpoint readback failed')
            self._save(stage='applied')
            # Even an unchanged endpoint needs apply after temporary callback:
            # this switches the logger back to its native cloud connection.
            self._write(peer,29,'1')
        except DataChannelRecovered:
            raise
        except BaseException:
            # A failed metadata check must not leave an unsupported device in
            # the temporary callback. Persistent settings remain untouched
            # unless a durable recovery record already exists.
            if self.record.get('active') and self.record.get('original_endpoint'):
                try:
                    self._restore_peer(peer)
                    self._save(active=False,stage='restored_after_setup_failure')
                except Exception as exc:
                    self._event('setup_restore_failed',error=str(exc))
            try:self._redirect(socket.gethostbyname(self.cfg.cloud_host),self.cfg.cloud_port)
            except OSError:pass
            raise
        finally:
            peer.close()
        self.state='RECONNECTING'
        self._event('configured',server_ip=lan,native_port=self.cfg.native_logger_port,original_endpoint=original,original_port=original_port)
        self.stop_event.wait(45) if not self.adapter.connected else None

    def _run(self):
        # On app restart, first allow the saved native route to reconnect by
        # itself, rather than disrupting it with another management callback.
        if self.record.get('active'):self.stop_event.wait(20)
        failures=0
        waiting_network=False
        while not self.stop_event.is_set():
            if self.adapter.connected:
                failures=0
                self.wake.wait(3);self.wake.clear();continue
            if not self._route_available():
                if not waiting_network:
                    self.state='WAITING_NETWORK';self.last_error='Немає маршруту Wi-Fi до логера'
                    self._event('waiting_network',logger_ip=self.cfg.lwip_ip)
                waiting_network=True
                self.wake.wait(3);self.wake.clear();continue
            if waiting_network:
                waiting_network=False;failures=0;self.last_error=''
                self._event('network_restored',logger_ip=self.cfg.lwip_ip)
            self.network_wake.clear()
            try:
                # A saved working endpoint commonly reconnects by itself.
                # Never interrupt it with management takeover immediately.
                lan=self.adapter.detect_lan_ip()
                if self.record.get('active') and self.record.get('server_ip')==lan:
                    self._event('reconnect_grace',server_ip=lan,wait_s=12)
                    deadline=time.monotonic()+12
                    while not self.stop_event.is_set() and not self.adapter.connected and time.monotonic()<deadline:
                        self.stop_event.wait(.25)
                    if self.stop_event.is_set():break
                    if self.adapter.connected:raise DataChannelRecovered()
                self._provision();failures=0
            except DataChannelRecovered:
                failures=0;self.state='ACTIVE';self.last_error=''
                self._event('reconnected_without_setup')
                continue
            except Exception as exc:
                if not self.stop_event.is_set():
                    failures+=1;self.state='RETRYING';self.last_error=str(exc)
                    self._event('setup_failed',error=str(exc),retry_s=min(180,30*2**min(failures-1,3)))
            delay=min(180,30*2**min(max(0,failures-1),3))
            # Coalesce network/manual wakeups without defeating failure backoff.
            deadline=time.monotonic()+delay
            while not self.stop_event.is_set() and time.monotonic()<deadline:
                self.wake.wait(min(1,max(0,deadline-time.monotonic())));self.wake.clear()
                if self.network_wake.is_set():break

    def _restore_peer(self, peer):
        original=self.record['original_endpoint']
        port=int(self.record.get('original_port',502))
        self._write(peer,24,str(port))
        self._write(peer,21,original)
        if self.query(peer,21)!=original or int(self.query(peer,24))!=port:
            raise ValueError('Restore endpoint/port readback failed')
        self._write(peer,29,'1')

    def stop(self):
        with self.lifecycle_lock:
            if self.listener is None:
                return
            return self._stop_locked()

    def _stop_locked(self):
        self.stop_event.set();self.wake.set()
        # Allow the bounded setup exchange to finish before restoring its
        # endpoint and port; never race restoration against a partial write.
        if self.thread:self.thread.join(timeout=90)
        if self.thread and self.thread.is_alive():
            self.state='RESTORE_PENDING';self.last_error='Налаштування логера ще завершується; прямий ESS не підтверджено'
            self._event('restore_deferred',reason='setup still finishing; durable original retained')
        elif self.record.get('original_endpoint'):
            self.state='RESTORING'
            try:
                peer,_=self._session(restoring=True)
                with peer:
                    original=self.record['original_endpoint']
                    self._restore_peer(peer)
                # Write+readback+apply confirmed; do not take over the fresh
                # direct ESS connection for an extra callback verification.
                self._save(active=False,stage='restored')
                self.state='RESTORED';self._event('restored',endpoint=original)
            except Exception as exc:
                self.last_error=str(exc);self.state='RESTORE_PENDING'
                self._event('restore_failed',error=str(exc))
                try:self._redirect(socket.gethostbyname(self.record['original_endpoint']),int(self.record.get('original_port',502)))
                except OSError:pass
        elif self.record.get('active') or self.adapter.connected:
            self.state='RESTORE_PENDING';self.last_error='Немає підтвердженого збереженого endpoint ESS; пряму роботу не відновлено'
            self._event('restore_failed',error=self.last_error)
        if self.listener:
            self.listener.close();self.listener=None
