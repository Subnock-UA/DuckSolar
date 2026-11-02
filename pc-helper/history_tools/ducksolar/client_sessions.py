"""Authenticated, bounded client sessions and operation replay protection."""
import hashlib
import hmac
import re
import threading
import time
from collections import OrderedDict
from uuid import uuid4

API_VERSION = 3
SESSION_TIMEOUT = 90


class SessionError(ValueError):
    def __init__(self, message, status=401, code='session.required'):
        super().__init__(message)
        self.status, self.code = status, code


class ClientSessions:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.RLock()
        self.clients = {}
        self.replays = OrderedDict()

    def expire(self):
        now = time.monotonic()
        for ident, row in list(self.clients.items()):
            if now-row['touched'] > SESSION_TIMEOUT:
                del self.clients[ident]
                self.runtime.logs.event('Client session expired', code='session.expired', client_id=ident, client_session_id=row['session_id'])
        for key, row in list(self.replays.items()):
            if now-row[0] > 600:
                del self.replays[key]

    def open(self, obj, address):
        ident = obj.get('client_id', '')
        username = obj.get('username', '')
        version = obj.get('client_version', '')
        if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{32}', ident):
            raise ValueError('Invalid client identity')
        if obj.get('api_version') != API_VERSION or not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', version):
            raise SessionError('Несумісні версії Client/API', 409, 'api.incompatible')
        from .compatibility import check_required
        check_required(obj.get('required_capabilities',[]))
        with self.lock:
            self.expire()
            row = self.clients.get(ident)
            if row and row.get('username') != username:
                del self.clients[ident]; row = None
            resumed = row is not None
            if row is None:
                if len(self.clients) >= 128:
                    raise SessionError('Client session limit reached', 503, 'session.limit')
                row = dict(client_id=ident, session_id=uuid4().hex, connected_at=time.time())
                self.clients[ident] = row
            row.update(username=username, touched=time.monotonic(), last_activity=time.time(), address=address, client_version=version)
            self.runtime.logs.event('Client session resumed' if resumed else 'Client session opened', code='session.resumed' if resumed else 'session.opened', client_id=ident, client_session_id=row['session_id'], client_version=version, address=address)
            from .config import VERSION
            from .compatibility import CAPABILITIES, API_VERSIONS
            return dict(client_session_id=row['session_id'], client_id=ident, resumed=resumed,
                        server_session_id=self.runtime.session_id, api_version=API_VERSION,
                        server_version=VERSION, capabilities=list(CAPABILITIES), supported_api_versions=list(API_VERSIONS), server_time=time.time(), heartbeat_s=1, session_timeout_s=SESSION_TIMEOUT)

    def touch(self, ident, session):
        with self.lock:
            self.expire()
            row = self.clients.get(ident)
            if not row or row['session_id'] != session:
                raise SessionError('Сесія завершена; потрібне перепідключення', code='session.expired')
            row.update(touched=time.monotonic(), last_activity=time.time())
            return row

    def inventory(self):
        with self.lock:
            self.expire()
            return [{k:v for k,v in row.items() if k != 'touched'} for row in self.clients.values()]

    def perform(self, ident, operation_id, body, callback):
        """Serialize mutations and reuse a successful reply for the same request."""
        key = (ident, operation_id)
        digest = hashlib.sha256(body).hexdigest()
        with self.lock:
            self.expire()
            previous = self.replays.get(key)
            if previous:
                if previous[1] != digest:
                    raise SessionError('Operation ID reused with different data', 409, 'operation.conflict')
                self.runtime.logs.event('Duplicate operation reused', code='api.operation.replayed', operation_id=operation_id, client_id=ident)
                return previous[2]
            result = callback()
            self.replays[key] = (time.monotonic(), digest, result)
            while len(self.replays) > 256:
                self.replays.popitem(last=False)
            return result
