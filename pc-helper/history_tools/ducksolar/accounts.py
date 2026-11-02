"""Local accounts, equipment grants and expiring bearer credentials."""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from .client_sessions import SessionError
from .secure_channel import security_directory

TOKEN_IDLE_SECONDS = 30 * 86400


class Accounts:
    def __init__(self, cfg, logs):
        self.logs = logs
        self.path = security_directory(cfg) / 'accounts.db'
        self.lock = threading.RLock()
        self.hash_slots = threading.BoundedSemaphore(2)
        self.limits = OrderedDict()
        with self.database() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts (
                  username TEXT PRIMARY KEY, password TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0,
                  grants TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (
                  digest TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL);
            ''')
        with self.database() as db:
            columns={r['name'] for r in db.execute('PRAGMA table_info(accounts)')}
            if 'verified' not in columns:
                db.execute('ALTER TABLE accounts ADD COLUMN verified INTEGER NOT NULL DEFAULT 0')
                # Existing accounts with equipment grants were already paired.
                db.execute("UPDATE accounts SET verified=1 WHERE grants!='[]'")
            db.execute('CREATE TABLE IF NOT EXISTS auth_policy (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)')
            if db.execute('SELECT revision FROM auth_policy WHERE id=1').fetchone() is None:
                # One-time migration of credentials still present in the DB.
                # Deleted/revoked credentials and blocked accounts remain denied.
                now = time.time()
                db.execute('UPDATE tokens SET expires=? WHERE expires>=? AND username IN (SELECT username FROM accounts WHERE blocked=0)',
                           (now + TOKEN_IDLE_SECONDS, now - 7 * 86400))
                db.execute('INSERT INTO auth_policy VALUES(1,1)')
        self.path.chmod(0o600)
        self.dummy_hash = self.password_hash('nonexistent-account')

    @contextmanager
    def database(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally:
            db.close()

    @staticmethod
    def username(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value):
            raise ValueError('Логін: 1–64 латинських літери, цифри, крапка, дефіс або підкреслення')
        return value.casefold()

    @staticmethod
    def password(value):
        if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 512:
            raise ValueError('Пароль має містити від 1 до 512 байтів UTF-8')
        return value

    @classmethod
    def password_hash(cls, value, salt=None):
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.scrypt(cls.password(value).encode(), salt=salt, n=16384, r=8, p=5,
                                dklen=32, maxmem=32*1024*1024)
        return salt.hex() + ':' + digest.hex()

    def rate_limit(self, address, username, action):
        now = time.monotonic()
        with self.lock:
            for key in (('address', address, action), ('account', username, action)):
                row = self.limits.get(key)
                if not row or now-row[0] >= 60:
                    row = [now, 0]; self.limits[key] = row
                row[1] += 1
                if row[1] > (20 if key[0] == 'address' else 8):
                    raise SessionError('Забагато спроб. Спробуйте через хвилину.', 429, 'auth.rate_limited')
                self.limits.move_to_end(key)
            while len(self.limits) > 2048:
                self.limits.popitem(last=False)

    def register(self, username, password, address):
        username = self.username(username); self.rate_limit(address, username, 'register')
        if not self.hash_slots.acquire(blocking=False):
            raise SessionError('Сервер зайнятий; повторіть спробу.', 503, 'auth.busy')
        try:
            hashed = self.password_hash(password)
            with self.lock, self.database() as db:
                if db.execute('SELECT count(*) FROM accounts').fetchone()[0] >= 256:
                    raise SessionError('Досягнуто ліміту акаунтів', 503, 'auth.account_limit')
                try:
                    db.execute('INSERT INTO accounts(username,password,created) VALUES (?,?,?)',
                               (username, hashed, time.time()))
                except sqlite3.IntegrityError:
                    raise SessionError('Логін уже використовується', 409, 'auth.username_taken') from None
            self.logs.event('Account registered', code='auth.registered', username=username, address=address)
            return dict(registered=True, username=username)
        finally:
            self.hash_slots.release()

    def login(self, username, password, address, trusted=False):
        username = self.username(username); self.rate_limit(address, username, 'login')
        if not self.hash_slots.acquire(blocking=False):
            raise SessionError('Сервер зайнятий; повторіть спробу.', 503, 'auth.busy')
        try:
            with self.database() as db:
                row = db.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            stored = row['password'] if row else self.dummy_hash
            checked = self.password_hash(password, bytes.fromhex(stored.split(':')[0]))
            if not row or not hmac.compare_digest(checked, stored) or row['blocked']:
                self.logs.event('Account login denied', code='auth.denied', address=address, username=username,
                    reason='unknown_account' if not row else 'blocked' if row['blocked'] else 'wrong_password')
                raise SessionError('Невірний логін/пароль або акаунт заблокований', code='auth.denied')
            if not row['verified'] and not trusted:
                raise SessionError('Для першого входу в акаунт потрібен код Server',403,'auth.first_trust_required')
            token = secrets.token_urlsafe(32); expires = time.time()+TOKEN_IDLE_SECONDS
            with self.lock, self.database() as db:
                current = db.execute('SELECT password,blocked FROM accounts WHERE username=?', (username,)).fetchone()
                if not current or current['blocked'] or current['password'] != stored:
                    raise SessionError('Потрібен повторний вхід', code='auth.required')
                if trusted: db.execute('UPDATE accounts SET verified=1 WHERE username=?',(username,))
                db.execute('DELETE FROM tokens WHERE expires<?', (time.time(),))
                # Bound credentials per account; another PC remains independently connected.
                db.execute('DELETE FROM tokens WHERE digest IN (SELECT digest FROM tokens WHERE username=? ORDER BY expires DESC LIMIT -1 OFFSET 15)', (username,))
                db.execute('INSERT INTO tokens VALUES (?,?,?)', (self.digest(token), username, expires))
            self.logs.event('Account login accepted', code='auth.login', username=username, address=address)
            return dict(token=token, expires_at=expires, username=username, bound=bool(json.loads(row['grants'])))
        finally:
            self.hash_slots.release()

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authorize(self, header, require_bound=True):
        if not isinstance(header, str) or not header.startswith('Bearer ') or len(header) > 256:
            raise SessionError('Увійдіть у свій акаунт', code='auth.required')
        with self.database() as db:
            row = db.execute('SELECT a.*,t.expires FROM accounts a JOIN tokens t ON a.username=t.username WHERE t.digest=?',
                             (self.digest(header[7:]),)).fetchone()
        if not row or row['blocked'] or row['expires'] <= time.time():
            self.logs.event('Account authorization required',code='auth.required',
                            reason='unknown_token' if not row else 'blocked' if row['blocked'] else 'token_expired')
            raise SessionError('Потрібен повторний вхід у свій акаунт', code='auth.required')
        # Renew active credentials once per day, without storing a password.
        # Use a conditional update so concurrent logout cannot recreate a token.
        now = time.time()
        if row['expires'] < now + TOKEN_IDLE_SECONDS - 86400:
            with self.database() as db:
                db.execute('UPDATE tokens SET expires=? WHERE digest=? AND expires>?',
                           (now + TOKEN_IDLE_SECONDS, self.digest(header[7:]), now))
        grants = json.loads(row['grants'])
        if require_bound and not grants:
            raise SessionError('Вкажіть серійний номер Datalogger або інвертора', 403, 'auth.serial_required')
        return dict(username=row['username'], grants=grants)

    def bind(self, header, serial, runtime, address):
        account = self.authorize(header, require_bound=False)
        self.rate_limit(address, account['username'], 'bind')
        if not isinstance(serial, str) or not 1 <= len(serial.strip()) <= 128:
            raise ValueError('Вкажіть серійний номер обладнання')
        serial = serial.strip().casefold()
        granted = []
        for ident, dev in runtime.devices.items():
            adapter = runtime.adapters[dev.definition.logger_id]
            logger_serial = str(getattr(adapter.cfg, 'dtu_pn', '')).strip().casefold()
            identity = dev.driver.identity(dev.parameters.snapshot()['raw'])
            inverter_serial = str(identity.get('serial', '')).strip().casefold()
            if serial in (logger_serial, inverter_serial):
                granted.append(ident)
        if not granted:
            self.logs.event('Equipment binding denied', code='auth.serial_denied', username=account['username'], address=address)
            raise SessionError('Серійний номер не відповідає обладнанню цього Server', 403, 'auth.serial_denied')
        with self.lock, self.database() as db:
            db.execute('UPDATE accounts SET grants=? WHERE username=?', (json.dumps(granted), account['username']))
        self.logs.event('Equipment access granted', code='auth.bound', username=account['username'], device_ids=granted)
        return dict(bound=True, device_ids=granted)

    def logout(self, header):
        account = self.authorize(header, require_bound=False)
        with self.lock, self.database() as db:
            db.execute('DELETE FROM tokens WHERE digest=?', (self.digest(header[7:]),))
        self.logs.event('Account logged out', code='auth.logout', username=account['username'])
        return dict(logged_out=True)

    def inventory(self):
        with self.database() as db:
            return [dict(r) for r in db.execute('SELECT username,blocked,grants,created FROM accounts ORDER BY username')]

    def manage(self, username, action, password=None):
        """Local shell only; deliberately absent from the network API."""
        username = self.username(username)
        with self.lock, self.database() as db:
            if action == 'block': db.execute('UPDATE accounts SET blocked=1 WHERE username=?', (username,))
            elif action == 'unblock': db.execute('UPDATE accounts SET blocked=0 WHERE username=?', (username,))
            elif action == 'revoke': db.execute("UPDATE accounts SET grants='[]' WHERE username=?", (username,))
            elif action == 'password': db.execute('UPDATE accounts SET password=? WHERE username=?', (self.password_hash(password), username))
            elif action != 'disconnect': raise ValueError('Unknown account action')
            db.execute('DELETE FROM tokens WHERE username=?', (username,))
        self.logs.event('Account access changed locally', code='auth.local_change', username=username, action=action)
