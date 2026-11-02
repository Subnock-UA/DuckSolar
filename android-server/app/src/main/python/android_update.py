"""Private bounded-memory update checkpoints. Never touches original history/logs."""
import hashlib,json,os,shutil,sqlite3,time,uuid
from contextlib import closing
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):h.update(block)
    return h.hexdigest()

def checkpoint(root,target):
    root=Path(root).resolve();folder=root/'UpdateCheckpoints';folder.mkdir(exist_ok=True)
    sources=[]
    for base in (root/'Server',root/'Data'/'DS_Security'):
        if base.exists():
            sources.extend(x for x in base.rglob('*') if x.is_file() and not x.is_symlink()
                and 'Cache' not in x.relative_to(base).parts and x.suffix not in ('.tmp','.part')
                and not x.name.endswith(('-wal','-shm','-journal')))
    ledger=root/'Data'/'ParameterCommands.json'
    if ledger.exists():sources.append(ledger)
    database=root/'Data'/'energy.db'
    if database.exists():sources.append(database)
    sources=sorted(set(sources));needed=sum(x.stat().st_size for x in sources)
    if shutil.disk_usage(root).free<needed*2+32*1024*1024:raise RuntimeError('Недостатньо місця для резервної копії перед оновленням')
    temporary=folder/('pending-'+uuid.uuid4().hex);temporary.mkdir(mode=0o700)
    deadline=time.monotonic()+60
    try:
        entries=[]
        for source in sources:
            if time.monotonic()>deadline:raise TimeoutError('Резервування перевищило 60 секунд')
            destination=temporary/source.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True)
            if source.suffix=='.db':
                def progress(status,remaining,total):
                    if time.monotonic()>deadline:raise TimeoutError('Резервування бази перевищило 60 секунд')
                with closing(sqlite3.connect('file:'+source.as_posix()+'?mode=ro',uri=True,timeout=5)) as inp,closing(sqlite3.connect(destination)) as out:
                    inp.backup(out,pages=256,progress=progress,sleep=0.05)
                    out.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
                    if out.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Неповна резервна копія бази')
            else:
                with source.open('rb') as inp,destination.open('wb') as out:
                    shutil.copyfileobj(inp,out,65536);out.flush();os.fsync(out.fileno())
            if os.name!='nt':destination.chmod(0o600)
            entries.append({'path':source.relative_to(root).as_posix(),'bytes':destination.stat().st_size,'sha256':digest(destination)})
        manifest={'schema':1,'target':target,'created':time.time(),'files':entries}
        (temporary/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        complete=folder/('checkpoint-'+str(time.time_ns()));temporary.rename(complete)
        # Retain the latest two complete checkpoints; remove only our derived directories.
        for old in sorted(folder.glob('checkpoint-*'),reverse=True)[2:]:
            if old.is_dir() and old.resolve().parent==folder.resolve():shutil.rmtree(old)
        return json.dumps({'checkpoint':complete.name,'files':len(entries),'bytes':sum(x['bytes'] for x in entries)})
    except BaseException:
        if temporary.exists() and temporary.resolve().parent==folder.resolve():shutil.rmtree(temporary)
        raise

def verify_current(root):
    root=Path(root);deadline=time.monotonic()+15
    checked=[]
    for source in (root/'Data'/'energy.db',root/'Data'/'DS_Security'/'accounts.db'):
        if source.exists():
            with closing(sqlite3.connect('file:'+source.as_posix()+'?mode=ro',uri=True,timeout=5)) as db:
                db.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Перевірка бази після оновлення не пройшла')
            checked.append(source.name)
    return json.dumps({'integrity':'ok','databases':checked})
