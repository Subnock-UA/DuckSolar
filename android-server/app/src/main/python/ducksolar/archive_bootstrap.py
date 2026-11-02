"""Checksummed history bootstrap; bounded disk merge, never overwrites phone rows."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
import zipfile


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(256*1024): result.update(block)
    return result.hexdigest()


def merge_on_disk(source, target, work):
    """Existing rows win conflicts. Missing historical timestamps are added atomically."""
    target=Path(target);source=Path(source);work=Path(work)
    target.parent.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True,exist_ok=True)
    existing_digest=digest(target) if target.exists() else None
    fd, database=tempfile.mkstemp(suffix='.sqlite',dir=work);os.close(fd)
    temporary=target.with_name('.'+target.name+'.archive-part')
    added=duplicates=conflicts=0;columns=[]
    try:
        con=sqlite3.connect(database)
        con.execute('PRAGMA cache_size=-2048');con.execute('PRAGMA temp_store=FILE')
        con.execute('CREATE TABLE rows (stamp TEXT PRIMARY KEY, data TEXT NOT NULL)')
        for path,original in ((target,True),(source,False)):
            if not path.exists(): continue
            with path.open(encoding='utf-8-sig',newline='') as stream:
                reader=csv.DictReader(stream)
                if not reader.fieldnames or len(reader.fieldnames)>256: raise ValueError('Invalid CSV header')
                columns=list(dict.fromkeys(columns+reader.fieldnames))
                for number,row in enumerate(reader):
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError('Incomplete archive CSV row')
                    stamp=row.get('time') or row.get('timestamp') or row.get('Timestamp')
                    instant=datetime.fromisoformat(stamp)
                    if instant.tzinfo is None: instant=instant.replace(tzinfo=ZoneInfo('Europe/Kyiv'))
                    if instant.astimezone(ZoneInfo('Europe/Kyiv')).date().isoformat()!=target.stem:
                        raise ValueError('Record date differs from archive filename')
                    key=instant.timestamp()
                    serial=json.dumps(row,ensure_ascii=False,separators=(',',':'),sort_keys=True)
                    prior=con.execute('SELECT data FROM rows WHERE stamp=?',(str(key),)).fetchone()
                    if prior:
                        if not original:
                            if prior[0]==serial: duplicates+=1
                            else: conflicts+=1
                        continue
                    con.execute('INSERT INTO rows VALUES (?,?)',(str(key),serial))
                    if not original: added+=1
                    if number%256==0: con.commit()
        con.commit()
        if added:
            with temporary.open('w',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
                for _,data in con.execute('SELECT stamp,data FROM rows ORDER BY CAST(stamp AS REAL)'):
                    writer.writerow(json.loads(data))
                stream.flush();os.fsync(stream.fileno())
            if (digest(target) if target.exists() else None)!=existing_digest:
                raise RuntimeError('Phone history changed while importing')
            os.replace(temporary,target)
        return dict(added=added,duplicates=duplicates,conflicts=conflicts)
    finally:
        if 'con' in locals(): con.close()
        Path(database).unlink(missing_ok=True);temporary.unlink(missing_ok=True)


def import_bundle(root, bundle):
    root=Path(root);bundle=Path(bundle)
    if not bundle.exists(): return dict(status='absent')
    with zipfile.ZipFile(bundle) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        base=root/'Data'/'ImportedArchive'/identity
        done=base/'complete.json'
        if done.exists(): return json.loads(done.read_text(encoding='utf-8'))
        base.mkdir(parents=True,exist_ok=True)
        free=shutil.disk_usage(root).free
        if free<manifest['bytes']*3+64*1024*1024: raise OSError('Insufficient space for complete history import')
        result=dict(status='complete',files=0,added=0,duplicates=0,conflicts=0,bytes=manifest['bytes'])
        for entry in manifest['files']:
            relative=Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts: raise ValueError('Unsafe archive path')
            original=base/'Originals'/relative
            original.parent.mkdir(parents=True,exist_ok=True)
            if not original.exists() or digest(original)!=entry['sha256']:
                temporary=original.with_suffix('.part')
                with archive.open(entry['member']) as source,temporary.open('wb') as target:
                    shutil.copyfileobj(source,target,256*1024)
                if temporary.stat().st_size!=entry['bytes'] or digest(temporary)!=entry['sha256']:
                    temporary.unlink(missing_ok=True);raise ValueError('Archive checksum mismatch')
                os.replace(temporary,original)
            if entry['kind']=='local':
                destination=root/'Logs'/'Inverter'/entry['day']
                merged=merge_on_disk(original,destination,base/'Work')
                for key in ('added','duplicates','conflicts'): result[key]+=merged[key]
            elif entry['kind']=='history':
                destination=root/relative
                if not destination.exists():
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    temporary=destination.with_suffix('.archive-part')
                    shutil.copyfile(original,temporary);os.replace(temporary,destination)
                elif digest(destination)!=entry['sha256']:
                    # Phone's existing file stays authoritative; entire incoming original is retained.
                    result['conflicts']+=1
            result['files']+=1
        temporary=done.with_suffix('.tmp')
        temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');os.replace(temporary,done)
        return result
