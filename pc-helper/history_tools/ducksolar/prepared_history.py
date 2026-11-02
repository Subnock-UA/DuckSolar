"""Portable, lossless calculation rows. Original CSV is always authoritative."""
import csv
import gzip
import hashlib
import json
import os
import time
import threading
import zipfile
from datetime import date
from pathlib import Path
from uuid import uuid4
from .wire import encode,decode

FORMAT='ducksolar.prepared-history.v1'
ALGORITHM='canonical-v1'
LOCK=threading.RLock()

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,allow_nan=False,separators=(',',':'));f.flush();os.fsync(f.fileno())
        deadline=time.monotonic()+20
        while True:
            try:
                os.replace(temp,path)
                break
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(.1)
    finally:temp.unlink(missing_ok=True)

def digest(path,cancelled=None):
    result=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(1024*1024):
            if cancelled and cancelled():raise ValueError('History preparation cancelled')
            result.update(block)
    return result.hexdigest()

class PreparedHistory:
    def __init__(self,reader):
        self.reader=reader
        self.root=Path(reader.cfg.root_dir)/'Data/PreparedHistory'
        self.root.mkdir(parents=True,exist_ok=True)
        self.index_path=self.root/'index.json'
        try:self.index=json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.index={}
        self.model=hashlib.sha256(json.dumps([ALGORITHM,reader.model_signature()],sort_keys=True).encode()).hexdigest()

    def identity(self,path,origin,day,cancelled=None):
        path=Path(path);stat=path.stat()
        fingerprint=[stat.st_size,stat.st_mtime_ns,stat.st_ino]
        sidecar=Path(str(path)+'.schema.json')
        if sidecar.exists():
            meta_stat=sidecar.stat()
            fingerprint.extend([meta_stat.st_size,meta_stat.st_mtime_ns,meta_stat.st_ino])
        cache_key=str(path.resolve())
        saved=self.index.get(cache_key,{})
        if saved.get('fingerprint')==fingerprint:raw_sha=saved['raw_sha256']
        else:
            raw_sha=digest(path,cancelled)
            if sidecar.exists():
                raw_sha=hashlib.sha256((raw_sha+digest(sidecar,cancelled)).encode()).hexdigest()
            after=path.stat()
            checked=[after.st_size,after.st_mtime_ns,after.st_ino]
            if sidecar.exists():
                meta_stat=sidecar.stat();checked.extend([meta_stat.st_size,meta_stat.st_mtime_ns,meta_stat.st_ino])
            if fingerprint!=checked:raise ValueError('CSV changed during preparation')
            self.index[cache_key]=dict(fingerprint=fingerprint,raw_sha256=raw_sha)
            with LOCK:
                try:current=json.loads(self.index_path.read_text(encoding='utf-8'))
                except (OSError,ValueError):current={}
                current[cache_key]=self.index[cache_key];write_json(self.index_path,current)
        key=hashlib.sha256(json.dumps([FORMAT,self.model,origin,day.isoformat(),raw_sha]).encode()).hexdigest()
        return key,dict(contract=FORMAT,algorithm=ALGORITHM,model=self.model,source=origin,day=day.isoformat(),raw_sha256=raw_sha,raw_bytes=stat.st_size)

    def _object(self,key):
        name=key if key.startswith('period-') else key+'.jsonl.gz'
        local=self.root/'objects'/name
        if local.is_file():return local
        try:
            current=json.loads((self.root/'current.json').read_text(encoding='utf-8'))
            generation=current['generation']
            if len(generation)!=64 or any(c not in '0123456789abcdef' for c in generation):return None
            obj=self.root/'packages'/generation/name
            if obj.is_file():return obj
        except (OSError,ValueError,KeyError,TypeError):pass
        return None

    def prepare(self,path,origin,day,cancelled=None):
        if day>=date.today():return None # A live day keeps the existing append path.
        key,metadata=self.identity(path,origin,day,cancelled)
        obj=self._object(key)
        if obj:return obj
        from .energy_streaming import _snapshot_lines
        folder=self.root/'objects';folder.mkdir(parents=True,exist_ok=True)
        target=folder/(key+'.jsonl.gz');temp=folder/(key+'.'+uuid4().hex+'.tmp')
        try:
            with gzip.open(temp,'wt',encoding='utf-8',compresslevel=1) as out:
                out.write(json.dumps(metadata,separators=(',',':'))+'\n')
                for raw in csv.DictReader(_snapshot_lines(path,metadata['raw_bytes']),strict=True):
                    if cancelled and cancelled():raise ValueError('History preparation cancelled')
                    row=self.reader._canonical(self.reader.decode_compact(path,raw),origin,day)
                    if row:
                        row.pop('_raw',None);row.pop('normalized',None)
                        out.write(json.dumps(encode(row),ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
            # Do not activate a derivative of a file edited or appended mid-read.
            verified,after=self.identity(path,origin,day,cancelled)
            if verified!=key or after!=metadata:raise ValueError('CSV changed during preparation')
            with temp.open('r+b') as f:os.fsync(f.fileno())
            os.replace(temp,target)
            return target
        finally:temp.unlink(missing_ok=True)

    def rows(self,path,origin,day,cancelled=None,create=True):
        if day>=date.today():return None
        key,metadata=self.identity(path,origin,day,cancelled)
        obj=self._object(key)
        if not obj and create:obj=self.prepare(path,origin,day,cancelled)
        if not obj:return None
        def iterate():
            with gzip.open(obj,'rt',encoding='utf-8') as f:
                if json.loads(f.readline())!=metadata:raise ValueError('Prepared history metadata mismatch')
                for line in f:
                    if cancelled and cancelled():raise ValueError('History query cancelled')
                    yield decode(json.loads(line))
        return iterate()

def export_package(reader,destination,cancelled=None,progress=None):
    """Run on PC with the same model as the target server. Never changes CSV."""
    store=PreparedHistory(reader);objects={};manifest=dict(contract=FORMAT,algorithm=ALGORITHM,model=store.model,files=[])
    days=[d for d in reader.available_dates(refresh=True) if d<date.today()]
    for index,day in enumerate(days):
        local,smart=reader.find_day_files(day)
        for origin,paths in (('Local',local),('SmartESS',smart)):
            for path in paths:
                obj=store.prepare(path,origin,day,cancelled)
                key,metadata=store.identity(path,origin,day,cancelled)
                objects[obj.name]=obj
                manifest['files'].append(dict(metadata,key=key,name=obj.name,sha256=digest(obj,cancelled),bytes=obj.stat().st_size))
        if progress:progress(index+1,len(days))
    from .history_views import HistoryViews
    view=HistoryViews(reader,reader.cfg,reader.cfg.history_device_id or 'inverter-1')
    from .hourly_projection import day as hourly_day,columns,export_portable
    for source in ('Local','SmartESS','Auto'):
        for anchor in days:
            rows,_=hourly_day(view,anchor,source,list(columns()),cancelled or (lambda:False))
            export_portable(view,anchor,source,rows)
        for year,month in sorted({(d.year,d.month) for d in days}):
            view.month_series(date(year,month,1),source,cancelled)
        for year in sorted({d.year for d in days}):
            view.graph_data('year',date(year,1,1),source,cancelled=cancelled)
    manifest['views']=[]
    for obj in view.view_path.glob('period-*.json'):
        objects[obj.name]=obj
        manifest['views'].append(dict(name=obj.name,bytes=obj.stat().st_size,sha256=digest(obj,cancelled)))
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.'+uuid4().hex+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_STORED) as z:
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
            for name,obj in objects.items():
                if cancelled and cancelled():raise ValueError('History preparation cancelled')
                z.write(obj,name)
        os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)
    return dict(files=len(objects),bytes=destination.stat().st_size,sha256=digest(destination),model=store.model)

def import_package(root,archive,expected_sha256,expected_model=None):
    """Validate every immutable object before atomically selecting a generation."""
    archive=Path(archive)
    if digest(archive)!=expected_sha256:raise ValueError('Prepared package checksum mismatch')
    root=Path(root)/'Data/PreparedHistory'
    target=root/'packages'/expected_sha256;staging=root/'packages'/('.'+uuid4().hex)
    staging.mkdir(parents=True,exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as z:
            if z.getinfo('manifest.json').file_size>32*1024*1024:raise ValueError('Prepared manifest too large')
            raw=z.read('manifest.json')
            if len(raw)>32*1024*1024:raise ValueError('Prepared manifest too large')
            manifest=json.loads(raw)
            if manifest.get('contract')!=FORMAT or manifest.get('algorithm')!=ALGORITHM:raise ValueError('Unsupported prepared format')
            if expected_model and manifest.get('model')!=expected_model:raise ValueError('Налаштування моделі пакета відрізняються від сервера; підготуйте пакет із його параметрами')
            import shutil
            required=sum(row['bytes'] for row in manifest['files']+manifest.get('views',[]))
            if required<0 or shutil.disk_usage(staging).free<required+16*1024*1024:raise ValueError('Insufficient prepared history storage')
            expected={'manifest.json'}
            for row in manifest['files']:
                name=row['name'];key=row['key']
                if len(key)!=64 or any(c not in '0123456789abcdef' for c in key) or name!=key+'.jsonl.gz':raise ValueError('Invalid prepared object')
                expected.add(name)
                if z.getinfo(name).file_size!=row['bytes']:raise ValueError('Prepared object size mismatch')
                date.fromisoformat(row['day'])
                if row['source'] not in ('Local','SmartESS') or row['model']!=manifest['model']:raise ValueError('Prepared model mismatch')
                obj=staging/name
                if obj.exists():continue
                with z.open(name) as inp,obj.open('wb') as out:
                    import shutil
                    shutil.copyfileobj(inp,out,1024*1024)
                if obj.stat().st_size!=row['bytes'] or digest(obj)!=row['sha256']:raise ValueError('Prepared object checksum mismatch')
                metadata={k:row[k] for k in ('contract','algorithm','model','source','day','raw_sha256','raw_bytes')}
                computed=hashlib.sha256(json.dumps([FORMAT,row['model'],row['source'],row['day'],row['raw_sha256']]).encode()).hexdigest()
                if computed!=key:raise ValueError('Prepared identity mismatch')
                with gzip.open(obj,'rt',encoding='utf-8') as f:
                    if json.loads(f.readline())!=metadata:raise ValueError('Prepared header mismatch')
                    while line:=f.readline(1024*1024+1):
                        if len(line)>1024*1024:raise ValueError('Prepared record too large')
                        item=decode(json.loads(line))
                        if item['timestamp'].date().isoformat()!=row['day']:raise ValueError('Prepared row date mismatch')
            for row in manifest.get('views',[]):
                import re
                name=row['name']
                if not re.fullmatch(r'period-[0-9a-f]{64}\.json',name):raise ValueError('Invalid prepared view')
                expected.add(name);obj=staging/name
                if z.getinfo(name).file_size!=row['bytes']:raise ValueError('Prepared view size mismatch')
                with z.open(name) as inp,obj.open('wb') as out:
                    import shutil
                    shutil.copyfileobj(inp,out,1024*1024)
                if obj.stat().st_size!=row['bytes'] or digest(obj)!=row['sha256']:raise ValueError('Prepared view checksum mismatch')
                value=json.loads(obj.read_text(encoding='utf-8'))
                if set(value)!={'revision','value'}:raise ValueError('Prepared view format mismatch')
            if set(z.namelist())!=expected or len(z.namelist())!=len(expected):raise ValueError('Unexpected prepared members')
        write_json(staging/'manifest.json',manifest)
        with LOCK:
            if not target.exists():os.replace(staging,target)
            write_json(root/'current.json',dict(contract=FORMAT,generation=expected_sha256,files=len(manifest['files']),model=manifest['model']))
        return dict(state='activated',files=len(manifest['files']),generation=expected_sha256)
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging)
