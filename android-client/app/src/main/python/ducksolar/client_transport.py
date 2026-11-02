"""Transport boundary: application API does not depend on HTTP/SSE internals."""
import json
import threading,time
import gzip
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler


class TransportError(ConnectionError):
    def __init__(self, message, status=0, code='transport.error'):
        super().__init__(message)
        self.status, self.code = status, code


class HTTPTransport:
    def __init__(self, url):
        if not isinstance(url,str) or any(c.isspace() for c in url): raise ValueError("Адреса Server не повинна містити пробіли")
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('Вкажіть адресу Server у форматі https://адреса:порт')
        try:
            if parts.port is not None and not 1 <= parts.port <= 65535: raise ValueError()
        except ValueError:
            raise ValueError('Невірний порт Server') from None
        self.url = url.rstrip('/')
        self.opener = build_opener(ProxyHandler({}))

    def open(self, path, body=None, headers=None, timeout=5):
        try:
            return self.opener.open(Request(self.url+'/api/v1/'+path, data=body, headers=headers or {}), timeout=timeout)
        except TransportError:
            raise
        except HTTPError as exc:
            try: data = json.loads(exc.read(65537))
            except (ValueError, OSError): data = {}
            finally: exc.close()
            raise TransportError(data.get('error', str(exc)), exc.code, data.get('error_code', 'api.error')) from None
        except (URLError, OSError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(reason, TransportError): raise reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                message, code = 'Server не відповів вчасно. Перевірте IP, порт і Firewall.', 'connection.timeout'
            elif isinstance(reason, ConnectionRefusedError):
                message, code = 'Порт Server не приймає з’єднання. Перевірте запуск API та номер порту.', 'connection.refused'
            else:
                message, code = 'Не вдалося дістатись Server. Перевірте IP, мережу та Firewall.', 'connection.unreachable'
            raise TransportError(message, 0, code) from exc

    def request(self, path, body=None, headers=None, timeout=5):
        if not hasattr(self,'metrics'):self.metrics=threading.local()
        started=time.perf_counter()
        headers=dict(headers or {}); headers['Accept-Encoding']='gzip'
        with self.open(path, body, headers, timeout) as reply:
            opened=time.perf_counter()
            raw=reply.read()
            downloaded=time.perf_counter();wire_bytes=len(raw)
            if reply.headers.get('Content-Encoding')=='gzip':raw=gzip.decompress(raw)
            inflated=time.perf_counter();result=json.loads(raw);parsed=time.perf_counter()
            self.metrics.last=dict(wire_bytes=wire_bytes,json_bytes=len(raw),connect_s=round(opened-started,4),download_s=round(downloaded-opened,4),inflate_s=round(inflated-downloaded,4),json_s=round(parsed-inflated,4),total_s=round(parsed-started,4))
            return result

    def events(self, headers, stop_event, opened):
        with self.open('events', headers=headers, timeout=5) as response:
            opened(response)
            from .live_events import messages
            yield from messages(response,stop_event)
