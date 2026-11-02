"""Periodic public IP discovery outside GUI/polling threads. Never a reachability test."""
import ipaddress
import socket
import threading
import time
from datetime import datetime, timezone
from urllib.request import build_opener, ProxyHandler


def wifi_snapshot():
    """None on desktop; callback-owned Wi-Fi information on Android."""
    try:
        from java import jclass
    except ImportError:
        return None
    import json
    return json.loads(str(jclass('ua.ducksolar.b2.server.ServerNetwork').snapshot()))


def logger_route(target):
    native = wifi_snapshot()
    if native is not None:
        address = ipaddress.ip_address(target)
        matches = []
        for row in native.get('wifi', []):
            for value in row.get('addresses', []):
                interface = ipaddress.ip_interface(value)
                if interface.version == 4 and address in interface.network:
                    matches.append((interface.network.prefixlen, row['id'], str(interface.ip)))
        if not matches:
            raise OSError('No Wi-Fi route to logger')
        _, network, source = max(matches)
        return dict(network=network, source=source)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((target, 9))
        return dict(network='host', source=route.getsockname()[0])


def bind_logger_socket(sock, target):
    if wifi_snapshot() is not None:
        from java import jclass
        route = logger_route(target)
        jclass('ua.ducksolar.b2.server.ServerNetwork').bindSocket(sock.fileno(), route['network'])


def lan_addresses():
    native = wifi_snapshot()
    if native is not None:
        return sorted({str(ipaddress.ip_interface(value).ip)
                       for row in native.get('wifi', []) for value in row.get('addresses', [])
                       if ipaddress.ip_interface(value).version == 4})
    values = set()
    try:
        for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            values.add(row[4][0])
    except OSError:
        pass
    try:
        # UDP connect chooses the default interface; no packet is sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(('192.0.2.1', 9))
            values.add(route.getsockname()[0])
    except OSError:
        pass
    return sorted(v for v in values if not ipaddress.ip_address(v).is_loopback
                  and not ipaddress.ip_address(v).is_unspecified
                  and not ipaddress.ip_address(v).is_multicast)


class NetworkInfo:
    def __init__(self, logs, fetch=None):
        self.logs = logs
        self.fetch = fetch or self._fetch
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.value = dict(public_ip='', checked_at='', current=False, lan_ips=lan_addresses())
        self.thread = threading.Thread(target=self.run, name='PublicIP', daemon=True)

    @staticmethod
    def _fetch():
        opener=build_opener(ProxyHandler({}))
        for url in ('https://api.ipify.org', 'https://checkip.amazonaws.com'):
            try:
                with opener.open(url,timeout=4) as response: value=response.read(128).decode('ascii').strip()
                address=ipaddress.ip_address(value)
                if address.version != 4 or not address.is_global: raise ValueError('Not a public IPv4 address')
                return str(address)
            except Exception: continue
        raise ConnectionError('Public IP discovery unavailable')

    def refresh(self):
        with self.lock: self.value['lan_ips'] = lan_addresses()
        try:
            value=str(ipaddress.ip_address(self.fetch()))
            if ipaddress.ip_address(value).version != 4 or not ipaddress.ip_address(value).is_global: raise ValueError('Not a public IPv4 address')
            if self.stop_event.is_set(): return False
            with self.lock:
                changed=value!=self.value['public_ip']
                self.value.update(public_ip=value, checked_at=datetime.now(timezone.utc).isoformat(), current=True)
            if changed: self.logs.event('Public IP updated', code='network.public_ip.changed', public_ip=value)
            return True
        except Exception:
            with self.lock: self.value['current']=False
            return False

    def snapshot(self):
        with self.lock: return dict(self.value)
    def start(self): self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread.ident: self.thread.join(timeout=.2)
    def run(self):
        while not self.stop_event.is_set():
            ok=self.refresh()
            if self.stop_event.wait(600 if ok else 60): break
