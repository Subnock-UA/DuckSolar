"""Offline, redacted audit of the publication tree. Never prints matched values."""
from pathlib import Path
import argparse
import ast
import base64
import ipaddress
import json
import re
import sys
import zipfile

SKIP={'.git','.gradle','.kotlin','build','dist','__pycache__','.venv','venv'}
FORBIDDEN={'ui-language.json','.env','local.properties','connection.json','config.json','pc_meter_snapshot.json',
           'BUILD_SIGNATURE.json','PAYLOAD_SHA256.json'}
BINARY={'.keystore','.jks','.pfx','.p12','.pem','.key','.db','.sqlite','.sqlite3','.log','.jsonl','.pyc','.exe','.apk','.zip'}
PRIVATE_KEY=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\r\n]+(?:[A-Za-z0-9+/]{32,}[\r\n]+){2,}')
PROVIDER_TOKEN=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-proj-[A-Za-z0-9_-]{30,})')
DRIVE=re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]')
USER_PATH=re.compile(r'(?i)(?:/home/[^/\s]+/|/Users/[^/\s]+/|\\Users\\[^\\\s]+\\)')
IPV4=re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
DOC_NETS=[ipaddress.ip_network(n) for n in ('192.0.2.0/24','198.51.100.0/24','203.0.113.0/24')]


def audit(root, denied=()):
    root=Path(root).resolve();findings=[];files=0;python=0
    def add(p,kind,line=None):
        item=dict(file=p.relative_to(root).as_posix(),kind=kind)
        if line:item['line']=line
        findings.append(item)
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if any(part in SKIP for part in rel.parts):continue
        if p.is_symlink():add(p,'symlink');continue
        if not p.is_file():continue
        files+=1;data=p.read_bytes()
        if p.name in FORBIDDEN or p.suffix.lower() in BINARY:add(p,'runtime-or-secret-file')
        if PRIVATE_KEY.search(data):add(p,'private-key')
        if PROVIDER_TOKEN.search(data):add(p,'provider-token')
        if any(value and value in data for value in denied):add(p,'private-denylist-match')
        if p.suffix=='.png':
            # Text/EXIF chunks are not needed for application graphics.
            pos=8
            while pos+12<=len(data):
                n=int.from_bytes(data[pos:pos+4],'big');kind=data[pos+4:pos+8]
                if kind in (b'tEXt',b'zTXt',b'iTXt',b'eXIf'):add(p,'image-metadata')
                pos+=12+n
        try:text=data.decode('utf-8-sig')
        except UnicodeError:continue
        if p.suffix=='.py':
            python+=1
            try:ast.parse(text,filename=rel.as_posix())
            except SyntaxError as e:add(p,'python-syntax',e.lineno)
        for no,line in enumerate(text.splitlines(),1):
            if not (p.name=='audit_public.py' and line.startswith('USER_PATH=')) and (DRIVE.search(line) or USER_PATH.search(line)):add(p,'machine-specific-path',no)
            for match in IPV4.finditer(line):
                if rel.parts[0]=='third_party':continue # Upstream license references; private denylist still applies to all bytes.
                value=match.group()
                try:ip=ipaddress.ip_address(value)
                except ValueError:continue
                # Local binds, documentation fixtures and protocol network ranges.
                if ip.is_loopback or ip.is_unspecified or ip==ipaddress.ip_address('255.255.255.255'):continue
                if any(ip in net for net in DOC_NETS):continue
                if value in ('10.0.2.2','8.8.8.8'):continue # emulator fixture / DNS route probe
                if line[match.end():].startswith('/'):continue # network classification, not a host default
                if p.name in ('version_info.txt','ducksolar.manifest'):continue
                if value in ('0.2.6.1','3.6.7.6'):continue # legacy version / platform format
                add(p,'literal-network-host',no)
    return dict(files=files,python_sources=python,passed=not findings,findings=findings)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--denylist-file',type=Path,help='External private JSON list; never copy into the repository')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();denied=[]
    if args.denylist_file:
        for value in json.loads(args.denylist_file.read_text('utf8')):
            raw=value.encode();denied.extend((raw,value.encode('utf-16le'),raw.hex().encode(),base64.b64encode(raw)))
    result=audit(args.root,denied)
    rendered=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:args.report.write_text(rendered,'utf8')
    print(rendered)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

