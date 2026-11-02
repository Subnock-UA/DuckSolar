"""Pinned TLS 1.3: peer identity is checked before sending HTTP credentials."""
import hashlib
import hmac
import http.client
import re
import ssl
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener
from .client_transport import HTTPTransport, TransportError


def fingerprint(value):
    value = re.sub(r'[\s:-]', '', value or '').lower()
    if not re.fullmatch('[0-9a-f]{64}', value):
        raise TransportError('Скопіюйте код довіри з локального вікна Server', 0, 'tls.trust_required')
    return value


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host, pin, **kwargs):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        # Trust is the locally supplied certificate digest, checked immediately
        # after handshake. Never send HTTP until that check succeeds.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        kwargs.pop('context', None); kwargs.pop('check_hostname', None)
        super().__init__(host, context=context, **kwargs)
        self.pin = fingerprint(pin)

    def connect(self):
        super().connect()
        digest = hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(digest, self.pin):
            self.close()
            raise TransportError('Сертифікат Server не відповідає збереженому коду довіри. Перевірте Server.',
                                 0, 'tls.identity_mismatch')


class PinnedHandler(HTTPSHandler):
    def __init__(self, pin):
        super().__init__(); self.pin = pin

    def https_open(self, request):
        return self.do_open(lambda host, **kwargs: PinnedConnection(host, self.pin, **kwargs), request)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise TransportError('Перенаправлення Server заборонене', 0, 'tls.redirect_denied')


class SecureTransport(HTTPTransport):
    def __init__(self, url, pin):
        if not isinstance(url, str) or not url.startswith('https://'):
            raise ValueError('Duck Solar 0.3.4 потребує HTTPS')
        self.pin=pin
        super().__init__(url)
        self.opener = build_opener(ProxyHandler({}), PinnedHandler(pin), NoRedirects())
