"""Stopped-Server CSV merge. Existing records win; conflicts stay outside graphs."""
import csv,hashlib,io,json,os,tempfile
from pathlib import Path
from datetime import datetime
from .config import app_paths

def merge_csv(source,target,conflict_dir):
    source=Path(source);target=Path(target);conflict_dir=Path(conflict_dir)
    if source.resolve()==target.resolve():return dict(added=0,duplicates=0,conflicts=0)
    data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
    def read(data):
        reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')));headers=reader.fieldnames or []
        if not any(k in headers for k in ('time','timestamp','Timestamp')):raise ValueError('CSV не містить часу записів')
        rows=list(reader)
        if any(None in r for r in rows):raise ValueError('Некоректна кількість колонок CSV')
        return headers,rows
    fields,incoming=read(data);previous=target.read_bytes() if target.exists() else None
    columns,existing=read(previous) if previous else (fields,[])
    def key(row):
        stamp=next((row.get(k) for k in ('time','timestamp','Timestamp') if row.get(k)),None)
        try:value=datetime.fromisoformat(stamp)
        except (ValueError,TypeError):raise ValueError('Некоректний час запису: '+str(stamp)) from None
        if value.year<2010 or value.date().isoformat()!=target.stem:raise ValueError('Дата запису не відповідає файлу або менша за 2010')
        return value.isoformat(),row.get('source','Local')
    index={}
    for row in existing:index.setdefault(key(row),row)
    result=dict(added=0,duplicates=0,conflicts=0);conflicts=[]
    for row in incoming:
        stamp=key(row);old=index.get(stamp)
        if old is None:existing.append(row);index[stamp]=row;result['added']+=1
        elif all((old.get(k) or '')==(row.get(k) or '') for k in set(old)|set(row)):result['duplicates']+=1
        else:
            result['conflicts']+=1;conflicts.append(dict(key=stamp,existing=old,incoming=row,source=str(source),sha256=digest))
    if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise ValueError('Джерело змінилося; закрийте стару програму')
    if target.exists() and target.read_bytes()!=previous:raise ValueError('Історія змінилася; зупиніть Server')
    def atomic(path,text):
        path.parent.mkdir(parents=True,exist_ok=True);fd,temp=tempfile.mkstemp(prefix='.merge-',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    if conflicts:atomic(conflict_dir/(target.stem+'_'+digest[:16]+'.jsonl'),'\n'.join(json.dumps(r,ensure_ascii=False) for r in conflicts)+'\n')
    if result['added']:
        columns=list(dict.fromkeys(columns+fields));out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=columns);writer.writeheader()
        writer.writerows(sorted(existing,key=key));atomic(target,out.getvalue())
    return result

def import_history(cfg,device_id,sources,logs=None):
    from .core.models import definitions,checked_id
    checked_id(device_id)
    if device_id not in {d.id for d in definitions(cfg)[1]}:raise ValueError('Невідомий пристрій')
    paths=app_paths(cfg);target=paths['inverter_logs']
    if device_id!=cfg.legacy_device_id:target=target/'Devices'/device_id
    conflicts=paths['data']/'HistoryConflicts'/device_id;totals=dict(files=0,added=0,duplicates=0,conflicts=0)
    for source in sources:
        source=Path(source)
        if source.is_symlink() or getattr(source,'is_junction',lambda:False)():raise ValueError('Посилання не підтримуються')
        try:day=datetime.strptime(source.stem,'%Y-%m-%d').date()
        except ValueError:continue
        if day.year<2010:raise ValueError('Мінімальний рік — 2010')
        result=merge_csv(source,target/source.name,conflicts);totals['files']+=1
        for k,v in result.items():totals[k]+=v
        if logs:logs.event('Local history merged',code='history.merged',device_id=device_id,source=str(source),**result)
    return totals
