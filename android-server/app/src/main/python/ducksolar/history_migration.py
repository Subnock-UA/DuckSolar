"""Recoverable compact-history activation. Destructive steps require PC receipts."""
import json,os,re,shutil,zipfile
import hashlib
from datetime import date
from pathlib import Path
from uuid import uuid4
from .prepared_history import digest,write_json,PreparedHistory,import_package
from .compact_history import schema_path,Codec

CONTRACT='ducksolar.history-migration.v2'
def safe_member(name):
    parts=name.split('/')
    if not parts or any(p in ('','.','..') or ':' in p or '\\' in p for p in parts):raise ValueError('Unsafe migration member')
    return name

def inventory(runtime):
    if not runtime.maintenance_mode:raise ValueError('Maintenance is required')
    root=Path(runtime.cfg.root_dir).resolve()
    plan_path=root/'Data/HistoryMigration/plan.json'
    if plan_path.exists():return json.loads(plan_path.read_text(encoding='utf-8'))
    reader=runtime.history
    files=[]
    selected=[]
    for day in reader.available_dates(refresh=True):
        for source,paths in zip(('Local','SmartESS'),reader.find_day_files(day)):
            for path in paths:
                selected.append((day,source,path))
    # Imported originals may be suppressed by the calculation reader because
    # a merged live copy exists. They still need their own immutable PC receipt.
    seen={str(path.resolve()) for day,source,path in selected}
    backup_only=set()
    if runtime.primary_id==runtime.cfg.legacy_device_id:
        for base in (root/'Data/ImportedArchive').glob('*/Originals'):
            for path in base.rglob('*.csv'):
                if path.is_symlink() or str(path.resolve()) in seen:continue
                try:day=date.fromisoformat(path.stem)
                except ValueError:continue
                selected.append((day,reader._classify(path),path));seen.add(str(path.resolve()));backup_only.add(str(path.resolve()))
    for day,source,path in selected:
                path=path.resolve();path.relative_to(root)
                sha=digest(path)
                row=dict(path=path.relative_to(root).as_posix(),source=source,day=day.isoformat(),sha256=sha,bytes=path.stat().st_size,name='migration_'+sha+'.csv')
                if str(path) in backup_only:row['backup_only']=True
                meta=schema_path(path)
                if meta.exists():row['schema']=dict(path=meta.relative_to(root).as_posix(),sha256=digest(meta),bytes=meta.stat().st_size,name='migration_'+digest(meta)+'.json')
                files.append(row)
    plan=dict(contract=CONTRACT,id=uuid4().hex,installation=runtime.cfg.installation_id,
              device_id=runtime.primary_id,pn=runtime.cfg.dtu_pn,model=dict(reader.model_signature()),files=files)
    from .wire import encode
    # JSONObject on Android serialises 1.0 as 1. Preserve original numeric types
    # for legacy calculation identities, and the exact meter snapshot text.
    from .preparation_model import model_types
    plan['model_types']=model_types(plan['model'])
    plan['readings_json']=json.dumps(encode(runtime.storage.list_meter_readings(limit=100000)),ensure_ascii=False,separators=(',',':'))
    write_json(plan_path,plan)
    return plan

def activate(runtime,archive,expected_sha):
    if not runtime.maintenance_mode:raise ValueError('Maintenance is required')
    root=Path(runtime.cfg.root_dir).resolve();archive=Path(archive)
    if not re.fullmatch('[0-9a-f]{64}',expected_sha) or digest(archive)!=expected_sha:raise ValueError('Migration package checksum mismatch')
    plan=inventory(runtime)
    if dict(runtime.history.model_signature())!=plan['model'] or runtime.cfg.dtu_pn!=plan['pn']:raise ValueError('Server model changed after migration planning')
    folder=root/'Data/CompactHistory/packages';target=folder/expected_sha;staging=folder/('.'+uuid4().hex)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as z:
            if z.getinfo('manifest.json').file_size>32*1024*1024:raise ValueError('Migration manifest too large')
            manifest=json.loads(z.read('manifest.json'))
            for key in ('contract','id','installation','device_id','pn','model','model_types','readings_json'):
                if manifest.get(key)!=plan[key]:raise ValueError('Migration identity/model mismatch: '+key)
            receipts=manifest['originals']
            wanted=[{k:v for k,v in row.items() if k!='path' and k!='schema'} | ({'schema':{k:v for k,v in row['schema'].items() if k!='path'}} if 'schema' in row else {}) for row in plan['files']]
            if receipts!=wanted:raise ValueError('PC original archive receipts mismatch')
            expected={'manifest.json'}
            required=sum(row['bytes'] for row in manifest['files'])
            if required<0 or shutil.disk_usage(staging).free<required+16*1024*1024:raise ValueError('Insufficient migration storage')
            for row in manifest['files']:
                name=safe_member(row['name']);expected.add(name)
                if z.getinfo(name).file_size!=row['bytes']:raise ValueError('Migration member size mismatch')
                path=staging/name;path.parent.mkdir(parents=True,exist_ok=True)
                with z.open(name) as inp,path.open('wb') as out:
                    shutil.copyfileobj(inp,out,1024*1024);out.flush();os.fsync(out.fileno())
                if digest(path)!=row['sha256']:raise ValueError('Migration member checksum mismatch')
            if len(z.namelist())!=len(expected) or set(z.namelist())!=expected:raise ValueError('Unexpected migration members')
        for path in (staging/'history').rglob('*.csv'):
            if not schema_path(path).is_file():raise ValueError('Missing compact schema')
            Codec(path)
        write_json(staging/'manifest.json',manifest)
        if not target.exists():os.replace(staging,target)
        else:
            for row in manifest['files']:
                member=target/safe_member(row['name'])
                if not member.is_file() or member.stat().st_size!=row['bytes'] or digest(member)!=row['sha256']:raise ValueError('Existing migration generation corrupted')
        # Both publications are recoverable: maintenance persists until cleanup ends.
        import_package(root,target/'prepared.zip',manifest['prepared_sha256'],PreparedHistory(runtime.history).model)
        # Activation already verified every byte. Seed portable identities with
        # phone fingerprints, avoiding another full hash scan on the first plot.
        index={};members={row['name']:row for row in manifest['files']}
        for name,row in members.items():
            if not name.startswith('history/') or not name.endswith('.csv'):continue
            path=target/name;meta=schema_path(path);st=path.stat();ms=meta.stat()
            raw_sha=hashlib.sha256((row['sha256']+members[name+'.schema.json']['sha256']).encode()).hexdigest()
            index[str(path.resolve())]=dict(fingerprint=[st.st_size,st.st_mtime_ns,st.st_ino,ms.st_size,ms.st_mtime_ns,ms.st_ino],raw_sha256=raw_sha)
        write_json(root/'Data/PreparedHistory/index.json',index)
        from .projection_contract import install as install_indices
        installed_indices=install_indices(root,target,manifest)
        from .balance_seed import install as install_seeds
        installed_seeds=install_seeds(root,target,manifest,plan['device_id'])
        if getattr(runtime,'logs',None):runtime.logs.event('PC projections installed',code='history.migration.indices',indices=installed_indices,open_month_seeds=installed_seeds)
        write_json(root/'Data/CompactHistory/current.json',dict(contract=CONTRACT,generation=expected_sha,device_id=plan['device_id']))
        runtime.migration_state.update(active=True,stage='activated',generation=expected_sha)
        write_json(runtime.migration_path,runtime.migration_state)
        if runtime.migration_state.get('repair_only'):
            # Live originals may have grown since the original completed plan.
            # Refresh derivatives only; never delete or require stale receipts
            # for newly recorded live data. Retain the prior package for recovery.
            runtime.migration_state.update(active=False,stage='ready',repair_only=False)
            write_json(runtime.migration_path,runtime.migration_state)
        else:
            cleanup(runtime,manifest)
        if getattr(runtime,'logs',None):runtime.logs.event('Compact history activated',code='history.migration.activated',generation=expected_sha,files=len(plan['files']),collection_restart_pending=True)
        return dict(state='ready',files=len(plan['files']),original_bytes=sum(r['bytes'] for r in plan['files']),compact_bytes=sum(r['bytes'] for r in manifest['files']),generation=expected_sha)
    finally:
        if staging.exists():shutil.rmtree(staging)

def cleanup(runtime,manifest):
    root=Path(runtime.cfg.root_dir).resolve();plan=inventory(runtime)
    current=json.loads((root/'Data/CompactHistory/current.json').read_text())
    generation=current['generation'];active=root/'Data/CompactHistory/packages'/generation
    if current['device_id']!=plan['device_id'] or not (active/'manifest.json').is_file():raise ValueError('No active migration generation')
    # Preflight the entire set before deleting a single original. A changed file
    # must be backed up by a new plan, never silently removed.
    candidates=[]
    for row in plan['files']:
        for item in (row,row.get('schema')):
            if item is None:continue
            path=root/safe_member(item['path']);path.resolve().relative_to(root)
            if path.is_symlink() or path.resolve().is_relative_to(active.resolve()):raise ValueError('Unsafe original cleanup')
            if path.exists():
                if path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:raise ValueError('Original changed after PC backup')
                candidates.append(path)
    runtime.migration_state.update(stage='cleaning');write_json(runtime.migration_path,runtime.migration_state)
    for path in candidates:path.unlink(missing_ok=True)
    if getattr(runtime,'logs',None):runtime.logs.event('Verified phone originals removed',code='history.migration.cleanup',files=len(candidates),generation=generation)
    runtime.storage._compact_codecs={}
    runtime.history._dates_cache=None
    # The PC has prepared these completed days. Record only their file/model
    # fingerprints so charging does not reprocess the entire imported archive.
    from .history_reader import HistoryReader
    prepared_reader=HistoryReader(runtime.cfg);revisions={}
    for day in prepared_reader.available_dates(refresh=True):
        if day>=date.today():continue
        files=[p for group in prepared_reader.find_day_files(day) for p in group]
        revisions[day.isoformat()]=[prepared_reader._files_signature(files),prepared_reader.model_signature()]
    background=root/'Data/PreparedHistory/background-revisions.json'
    try:state=json.loads(background.read_text(encoding='utf-8'))
    except (OSError,ValueError):state={}
    state[plan['device_id']]=revisions;write_json(background,state)
    # Delete only explicitly disposable generations after both new pointers are
    # committed. Current objects, user DBs, auth and settings are excluded.
    prepared_root=root/'Data/PreparedHistory'
    prepared_current=json.loads((prepared_root/'current.json').read_text())['generation']
    for base,keep in ((root/'Data/CompactHistory/packages',generation),(prepared_root/'packages',prepared_current)):
        for folder in base.iterdir():
            if folder.is_dir() and not folder.is_symlink() and re.fullmatch('[0-9a-f]{64}',folder.name) and folder.name!=keep:
                folder.resolve().relative_to(base.resolve());shutil.rmtree(folder)
    for base,pattern in ((prepared_root/'objects','*.jsonl.gz'),(prepared_root/'objects','period-*.json'),(root/'Data/HistoryViews','period-*.json')):
        for path in base.glob(pattern):
            if path.is_file() and not path.is_symlink():path.unlink()
    runtime.migration_state.update(active=False,stage='ready');write_json(runtime.migration_path,runtime.migration_state)

def active_folder(root,device_id):
    sync=Path(root)/'Data/HistorySync/current.json'
    try:
        current=json.loads(sync.read_text(encoding='utf-8'))
        path=Path(root)/'Data/HistorySync/active/history'
        if current.get('device_id')==device_id and path.is_dir():return path
    except (OSError,ValueError):pass
    base=Path(root)/'Data/CompactHistory'
    try:
        current=json.loads((base/'current.json').read_text(encoding='utf-8'))
        if current['device_id']!=device_id or not re.fullmatch('[0-9a-f]{64}',current['generation']):return None
        path=base/'packages'/current['generation']/'history'
        if path.is_dir() and not path.is_symlink():return path
    except (OSError,ValueError,KeyError,TypeError):pass
    return None
