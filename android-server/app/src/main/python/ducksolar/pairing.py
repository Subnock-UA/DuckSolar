"""One-use, locally enabled SPAKE2 pairing; authenticate the full TLS identity."""
import hashlib
import hmac
import secrets
import threading
import time
from spake2 import SPAKE2_B
from .client_sessions import SessionError


def proof(key, role, ident, pin):
    return hmac.new(key, ('DX-pair-v1|'+role+'|'+ident+'|'+pin).encode('ascii'), hashlib.sha256).hexdigest()


class Pairing:
    def __init__(self, pin, logs):
        self.pin,self.logs=pin,logs
        self.lock=threading.Lock();self.code='';self.deadline=0;self.attempts=0;self.pending={};self.tickets={}

    def generate(self):
        with self.lock:
            self.code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
            self.deadline=time.monotonic()+300;self.attempts=0;self.pending.clear()
            self.logs.event('Pairing enabled locally',code='pairing.enabled',expires_s=300)
            return self.code

    def status(self):
        with self.lock:
            return self.code if self.code and time.monotonic()<self.deadline and self.attempts<5 else ''

    def start(self, message, address):
        with self.lock:
            if not self.code or time.monotonic()>=self.deadline or self.attempts>=5:
                raise SessionError('Створіть новий код парування у Server',403,'pairing.closed')
            self.attempts+=1
            try:
                if not isinstance(message,str) or len(message)!=66:raise ValueError()
                exchange=SPAKE2_B(self.code.encode(),idA=b'DX_Client',idB=b'DX_Server')
                reply=exchange.start();key=exchange.finish(bytes.fromhex(message))
            except Exception:
                raise SessionError('Некоректний запит парування',400,'pairing.invalid') from None
            ident=secrets.token_hex(16)
            self.pending[ident]=(key,address,time.monotonic()+30)
            return dict(id=ident,message=reply.hex(),fingerprint=self.pin,
                        proof=proof(key,'server',ident,self.pin))

    def finish(self, ident, supplied, address):
        with self.lock:
            item=self.pending.pop(ident,None)
            if not self.code or time.monotonic()>=self.deadline or not item or item[1]!=address or time.monotonic()>item[2]:
                raise SessionError('Парування прострочене; повторіть із новим кодом',403,'pairing.closed')
            if not isinstance(supplied,str) or not hmac.compare_digest(supplied,proof(item[0],'client',ident,self.pin)):
                raise SessionError('Код парування не збігається',403,'pairing.denied')
            self.code='';self.pending.clear()
            self.logs.event('Client paired',code='pairing.completed',address=address)
            ticket=secrets.token_urlsafe(32)
            self.tickets[ticket]=(address,time.monotonic()+300)
            return dict(paired=True,trust_ticket=ticket,proof=proof(item[0],'complete',ident,self.pin))

    def ticket_valid(self,ticket,address,consume=False):
        with self.lock:
            self.tickets={k:v for k,v in self.tickets.items() if time.monotonic()<v[1]}
            item=self.tickets.get(ticket) if isinstance(ticket,str) else None
            valid=bool(item and item[0]==address)
            if valid and consume:self.tickets.pop(ticket,None)
            return valid
