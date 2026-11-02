"""No login/password travels over the temporary, untrusted pairing channel."""
import hashlib
import hmac
import http.client
import json
import re
import ssl
from urllib.parse import urlsplit
from spake2 import SPAKE2_A


def proof(key,role,ident,pin):
    return hmac.new(key,('DX-pair-v1|'+role+'|'+ident+'|'+pin).encode('ascii'),hashlib.sha256).hexdigest()


def pair_server(url, code, timeout=10):
    code=code.strip().upper()
    if not re.fullmatch('[A-HJ-NP-Z2-9]{8}',code):raise ValueError('Код парування: 8 символів із локального вікна Server')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password:raise ValueError('Потрібна адреса HTTPS')
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);ctx.minimum_version=ssl.TLSVersion.TLSv1_3
    ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    conn=http.client.HTTPSConnection(parsed.hostname,parsed.port or 443,context=ctx,timeout=timeout)
    def request(path,obj):
        conn.request('POST','/api/v1/auth/pair/'+path,body=json.dumps(obj).encode(),headers={'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(8193)
        if len(raw)>8192:raise ValueError('Завелика відповідь парування')
        data=json.loads(raw)
        if response.status!=200:raise ValueError(data.get('error','Парування не виконано'))
        return data
    try:
        conn.connect();observed=hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        exchange=SPAKE2_A(code.encode(),idA=b'DX_Client',idB=b'DX_Server')
        reply=request('start',{'message':exchange.start().hex()})
        if reply.get('fingerprint')!=observed:raise ValueError('Ідентичність Server під час парування не збігається')
        key=exchange.finish(bytes.fromhex(reply['message']));ident=reply['id']
        if not hmac.compare_digest(reply['proof'],proof(key,'server',ident,observed)):
            raise ValueError('Неправильний код або непідтверджений Server')
        done=request('finish',{'id':ident,'proof':proof(key,'client',ident,observed)})
        if not done.get('paired') or not hmac.compare_digest(done['proof'],proof(key,'complete',ident,observed)):
            raise ValueError('Server не підтвердив завершення парування')
        return observed,done['trust_ticket']
    finally:conn.close()
