"""One-way copy of legacy data. Originals are never removed or overwritten."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile

def copy_missing(source,target):
    source=Path(source);target=Path(target)
    if not source.exists() or source.resolve()==target.resolve():return 0
    count=0
    for item in sorted(source.rglob('*')):
        if item.is_symlink() or getattr(item,'is_junction',lambda:False)():
            raise ValueError('Міграцію зупинено: посилання у папці старих даних')
        dest=target/item.relative_to(source)
        if item.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
        if dest.exists():continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.migrate-',dir=dest.parent)
        os.close(fd)
        try:
            shutil.copy2(item,temp)
            def digest(path):
                h=hashlib.sha256()
                with open(path,'rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
                return h.digest()
            if digest(item)!=digest(temp):raise OSError('Дані змінилися під час міграції; закрийте стару програму')
            os.replace(temp,dest);count+=1
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return count

def server_migrate(root,config_file,role):
    if os.environ.get('DUCK_SOLAR_B2_ALLOW_LEGACY_IMPORT') != '1':return
    root=Path(root)
    if role=='Server':
        previous_events=root/'Logs'/'DS_Server_Alpha_0.3.3'/'Events.jsonl'
        current_events=root/'Logs'/'DS_Server_Alpha_0.3.4'/'Events.jsonl'
        if previous_events.is_file() and not current_events.exists():
            if previous_events.is_symlink():raise ValueError('Event journal must be a regular file')
            current_events.parent.mkdir(parents=True,exist_ok=True)
            fd,temp=tempfile.mkstemp(prefix='.events-migrate-',dir=current_events.parent);os.close(fd)
            try:
                shutil.copy2(previous_events,temp);os.replace(temp,current_events)
            finally:
                if os.path.exists(temp):os.unlink(temp)
    if Path(config_file).exists():return
    previous=root/role/f'DS_{role}_Alpha_0.3.3'/'config.json'
    if not previous.exists():previous=root/role/f'DS_{role}_Alpha_0.3.2'/'config.json'
    if not previous.exists():previous=root/role/f'DS_{role}_Alpha_0.3.1'/'config.json'
    if previous.is_file():
        raw=json.loads(previous.read_text(encoding='utf-8-sig'));raw['root_dir']=str(root)
        target=Path(config_file);target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_suffix('.migration.tmp');temp.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
        return
    legacy_value=os.environ.get('DUCK_SOLAR_LEGACY_ROOT')
    if not legacy_value:return
    legacy=Path(legacy_value)
    if legacy.resolve()==root.resolve():return
    source=None
    for version in ('0.2.8','0.2.7','0.2.6.1','0.2.6','0.2.5'):
        for parent in (legacy/'DX_Monitor'/role,legacy/'DX_Monitor',legacy):
            candidate=parent/f'DX_Monitor_{role}_Alpha_{version}'/'config.json'
            if candidate.is_file():source=candidate;break
        if source:break
    if not source and not (legacy/'Data'/'DX_Security').is_dir() and not (legacy/'Data'/'energy.db').is_file():return
    raw=json.loads(source.read_text(encoding='utf-8-sig')) if source else {}
    if not isinstance(raw,dict):raise ValueError('Некоректна стара конфігурація')
    count=0
    for folder in ('Data','History','Logs'):
        count+=copy_missing(legacy/folder,root/folder)
    security=root/'Data'/'DX_Security';newsecurity=root/'Data'/'DS_Security'
    if security.exists() and not newsecurity.exists():security.rename(newsecurity)
    count+=copy_missing(legacy/'DX_Monitor'/'Logs',root/'Logs'/'Archive'/'Legacy_DX_Monitor')
    raw['root_dir']=str(root)
    target=Path(config_file);target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.migration.tmp')
    temp.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.chmod(0o600);temp.replace(target)
    receipt=root/'Data'/'migration_0.3.1.json'
    receipt.write_text(json.dumps(dict(source=str(legacy),destination=str(root),copied_files=count,originals_preserved=True),ensure_ascii=False,indent=2),encoding='utf-8')

def client_migrate(data_dir,package_dir,config_file):
    if os.environ.get('DUCK_SOLAR_B2_ALLOW_LEGACY_IMPORT') != '1':return
    data_dir=Path(data_dir)
    if Path(config_file).exists():return
    candidates=[Path(package_dir).parent/f'DS_Client_Alpha_{v}'/'UserData' for v in ('0.3.3','0.3.2','0.3.1')]
    previous_appdata=os.environ.get('LOCALAPPDATA')
    if previous_appdata:
        app_root=Path(previous_appdata)/'DuckSolar'/'Client'
        for version in ('0.3.3','0.3.2','0.3.1'):
            if data_dir.name.startswith('0.3.4_'):candidates.append(app_root/(version+'_'+data_dir.name[len('0.3.4_'):]))
            candidates.append(app_root/version)
            matches=[p for p in app_root.glob(version+'_*') if (p/'config.json').is_file()]
            if len(matches)==1:candidates.extend(matches)
    appdata=os.environ.get('LOCALAPPDATA')
    for version in ('0.2.8','0.2.7','0.2.6.1','0.2.6'):
        candidates.append(Path(package_dir).parent/f'DX_Monitor_Client_Alpha_{version}'/'UserData')
        if appdata:candidates.append(Path(appdata)/'DX_Monitor'/'Client'/version)
    if appdata:
        archive=Path(appdata)/'DX_Monitor'/'Logs'/'Archive'
        if archive.is_dir():
            candidates.extend(sorted((p for p in archive.glob('DX_Monitor_Client_Alpha_0.2.*') if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True))
    source=next((p for p in candidates if (p/'config.json').is_file()),None)
    if source is None:return
    raw=json.loads((source/'config.json').read_text(encoding='utf-8-sig'))
    if not isinstance(raw,dict):raise ValueError('Некоректна стара конфігурація Client')
    copy_missing(source,data_dir)
    receipt=data_dir/'migration_0.3.4.json'
    receipt.write_text(json.dumps(dict(source=str(source),destination=str(data_dir),originals_preserved=True),ensure_ascii=False,indent=2),encoding='utf-8')
