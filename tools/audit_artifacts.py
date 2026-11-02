"""Scan release bytes and nested ZIP/PyInstaller payloads for external private values.

Run using the same Python version which built a PyInstaller executable and install
PyInstaller. No extracted code is executed. Results never include matched values.
"""
from pathlib import Path
import argparse
import base64
import io
import json
import re
import types
import zipfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('paths',nargs='+',type=Path)
    parser.add_argument('--denylist-file',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    denied=[]
    for value in json.loads(args.denylist_file.read_text('utf8')):
        raw=value.encode();denied.extend([raw,value.encode('utf-16le'),raw.hex().encode(),base64.b64encode(raw)])
    denied=[value.lower() for value in denied if value]
    findings=[];counts=dict(files=0,zip_members=0,pyinstaller_members=0,code_objects=0)
    def check(label,data):
        data_lower=data.lower()
        if any(value in data_lower for value in denied):findings.append(dict(file=label,kind='private-value'))
        if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\r\n]+(?:[A-Za-z0-9+/]{32,}[\r\n]+){2,}',data):
            findings.append(dict(file=label,kind='private-key'))
    def content(label,data,depth=0):
        check(label,data)
        if depth>5:raise ValueError('Nested archive depth exceeds audit limit')
        stream=io.BytesIO(data)
        if zipfile.is_zipfile(stream):
            with zipfile.ZipFile(stream) as archive:
                for item in archive.infolist():
                    if item.is_dir():continue
                    if item.file_size>512*1024*1024:raise ValueError('Archive member too large to audit')
                    counts['zip_members']+=1
                    content(label+'!'+item.filename,archive.read(item),depth+1)
    def code(label,value):
        if isinstance(value,types.CodeType):
            counts['code_objects']+=1;check(label+':filename',value.co_filename.encode())
            for item in value.co_consts:code(label,item)
        elif isinstance(value,str):check(label,value.encode())
        elif isinstance(value,bytes):check(label,value)
        elif isinstance(value,(tuple,list,frozenset)):
            for item in value:code(label,item)
    for selected in args.paths:
        paths=[selected] if selected.is_file() else sorted(p for p in selected.rglob('*') if p.is_file())
        for path in paths:
            counts['files']+=1;label=path.name if selected.is_file() else path.relative_to(selected).as_posix()
            data=path.read_bytes();content(label,data)
            if path.suffix.lower()=='.exe':
                from PyInstaller.archive.readers import CArchiveReader,NotAnArchiveError
                try:archive=CArchiveReader(str(path))
                except NotAnArchiveError:continue # native dependency executable
                for name in archive.toc:
                    if name.endswith('.pyz'):
                        embedded=archive.open_embedded_archive(name)
                        for module in embedded.toc:
                            counts['pyinstaller_members']+=1
                            code(label+'!'+module,embedded.extract(module))
                    else:
                        payload=archive.extract(name)
                        if payload is not None:content(label+'!'+name,payload)
    result=dict(passed=not findings,counts=counts,findings=findings)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
