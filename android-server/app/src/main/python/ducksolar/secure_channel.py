"""Server identity and TLS policy, independent of the Windows shell."""
import datetime as dt
import os
from pathlib import Path
import ssl
import subprocess
import threading
_IDENTITY_LOCK=threading.RLock()
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def security_directory(cfg):
    path = Path(cfg.root_dir) / 'Data' / 'DS_Security'
    path.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        owner = os.environ.get('USERDOMAIN', '') + '\\' + os.environ['USERNAME']
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', owner + ':(OI)(CI)F'],
                                capture_output=True, creationflags=0x08000000)
        if result.returncode:
            raise OSError('Не вдалося захистити папку облікових даних Windows')
    else:
        path.chmod(0o700)
    return path


def server_identity(cfg):
    with _IDENTITY_LOCK:return _server_identity(cfg)

def _server_identity(cfg):
    directory = security_directory(cfg)
    cert_path, key_path = directory / 'server.pem', directory / 'server-key.pem'
    if cert_path.exists() != key_path.exists():
        raise ValueError('Неповна ідентичність Server; відновіть пару сертифікат/ключ')
    if not cert_path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Duck Solar Server')])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(minutes=5))
                .not_valid_after(now+dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        # Exclusive writes: never silently replace the identity already trusted by clients.
        with key_path.open('xb') as stream:
            stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        key_path.chmod(0o600)
        with cert_path.open('xb') as stream:
            stream.write(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    now = dt.datetime.now(dt.timezone.utc)
    if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
        raise ValueError('Сертифікат Server прострочений або ще не чинний')
    return cert_path, key_path, cert.fingerprint(hashes.SHA256()).hex()


def server_context(cfg):
    cert, key, fingerprint = server_identity(cfg)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert, key)
    context.options |= getattr(ssl, 'OP_NO_TICKET', 0)
    return context, fingerprint
