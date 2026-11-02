"""Authenticate the TLS pin using an already verified account's SPAKE2 secret.
No password or scrypt digest is transmitted on the provisional connection.
"""
import secrets
import time
import threading
from spake2 import SPAKE2_B
from .pairing import proof
from .client_sessions import SessionError

class AccountTrust:
    def __init__(self,accounts,pin):
        self.accounts=accounts;self.pin=pin;self.pending={};self.lock=threading.Lock()
    def record(self,username):
        with self.accounts.database() as db:
            return db.execute('SELECT * FROM accounts WHERE username=?',(username,)).fetchone()
    def parameters(self,username,address):
        username=self.accounts.username(username)
        self.accounts.rate_limit(address,username,'trust_parameters')
        row=self.record(username)
        stored=row['password'] if row else self.accounts.dummy_hash
        return {'salt':stored.split(':')[0]}
    def start(self,username,message,address):
        username=self.accounts.username(username)
        self.accounts.rate_limit(address,username,'trust')
        row=self.record(username)
        valid=bool(row and row['verified'] and not row['blocked'])
        stored=row['password'] if valid else self.accounts.dummy_hash
        if not isinstance(message,str) or len(message)!=66:
            raise ValueError('Некоректне повідомлення входу')
        exchange=SPAKE2_B(stored.encode('ascii'),idA=('DS_Client|'+username).encode(),idB=b'DS_Server_account_v1')
        reply=exchange.start();key=exchange.finish(bytes.fromhex(message));ident=secrets.token_hex(16)
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if time.monotonic()<v[2]}
            if len(self.pending)>=128:raise SessionError('Server зайнятий',503,'auth.busy')
            self.pending[ident]=(key,address,time.monotonic()+30,username,stored,valid)
        return dict(id=ident,message=reply.hex(),fingerprint=self.pin,proof=proof(key,'server-account',ident,self.pin))
    def finish(self,ident,supplied,address):
        import hmac
        with self.lock:item=self.pending.pop(ident,None)
        if not item or item[1]!=address or time.monotonic()>=item[2] or not item[5]:
            raise SessionError('Невірний логін/пароль, акаунт заблокований або ще не перевірений',403,'auth.denied')
        row=self.record(item[3])
        if not row or row['blocked'] or not row['verified'] or row['password']!=item[4] or not isinstance(supplied,str) or not hmac.compare_digest(supplied,proof(item[0],'client-account',ident,self.pin)):
            raise SessionError('Не вдалося підтвердити акаунт',403,'auth.denied')
        return dict(trusted=True,proof=proof(item[0],'complete-account',ident,self.pin))
