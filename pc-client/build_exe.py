"""Build the public Windows client. Signing requires an explicitly selected key."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent

def sign(path,thumbprint):
    if not re.fullmatch(r'[0-9A-Fa-f]{40,64}',thumbprint):raise ValueError('Invalid DS_WINDOWS_SIGNING_THUMBPRINT')
    env=dict(os.environ,DS_SIGN_TARGET=str(path.resolve()),DS_SIGN_CERT=thumbprint)
    script="""$ErrorActionPreference='Stop'
$cert=Get-Item -LiteralPath ('Cert:\\CurrentUser\\My\\'+$env:DS_SIGN_CERT)
if (-not $cert.HasPrivateKey -or $cert.NotAfter -lt (Get-Date)) { throw 'Signing certificate unavailable' }
$sig=Set-AuthenticodeSignature -LiteralPath $env:DS_SIGN_TARGET -Certificate $cert -HashAlgorithm SHA256
if ($sig.Status -ne 'Valid') { throw $sig.StatusMessage }
"""
    subprocess.run(['powershell.exe','-NoProfile','-Command',script],env=env,check=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-signature',action='store_true');args=parser.parse_args()
    cert=os.environ.get('DS_WINDOWS_SIGNING_THUMBPRINT','')
    if args.require_signature and not cert:raise ValueError('Set DS_WINDOWS_SIGNING_THUMBPRINT to your release certificate')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--noupx','--onedir','--windowed','--name','DuckSolar_PC_Client','--icon',str(ROOT/'assets/duck_solar.ico'),'--manifest',str(ROOT/'ducksolar.manifest'),'--version-file',str(ROOT/'version_info.txt'),'--add-data',str(ROOT/'locale')+os.pathsep+'locale','--add-data',str(ROOT/'assets')+os.pathsep+'assets','--collect-all','tzdata','--hidden-import','matplotlib.backends.backend_tkagg','--hidden-import','pystray._win32',str(ROOT/'client_main.py')],cwd=ROOT,check=True)
    bundle=ROOT/'dist/DuckSolar_PC_Client'
    for name in ['Install.cmd','Install.ps1','Start.cmd']:shutil.copyfile(ROOT/name,bundle/name)
    if cert:
        sign(bundle/'DuckSolar_PC_Client.exe',cert);sign(bundle/'Install.ps1',cert)
    files={p.relative_to(bundle).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(bundle.rglob('*')) if p.is_file()}
    (bundle/'PAYLOAD_SHA256.json').write_text(json.dumps(dict(version='b2.0.0',signing_thumbprint=cert.upper(),files=files),indent=2),'utf8')
    print('Public client built ('+('signed' if cert else 'unsigned portable build')+')')
if __name__=='__main__':main()
