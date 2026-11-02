"""Verified archive imports: preserve live files, publish immutable revisions."""
import csv,hashlib,json,os,re,shutil,threading
from pathlib import Path
from datetime import date
LOCK=threading.RLock()
def import_status(root,row):
 if isinstance(row,str):row=json.loads(row)
 source=row.get('source_id','')
 if not re.fullmatch(r'(?:pc|[0-9a-f]{32})',source):raise ValueError('Invalid archive source')
 base=Path(root)/'Data/SynchronizedArchive'/source
 try:
  saved=json.loads((base/'manifest.json').read_text(encoding='utf-8'))['files'].get(row['key'])
  if not saved or saved['sha256']!=row['sha256'] or saved.get('schema')!=row.get('schema'):return False
  p=base/saved['path']
  if not p.resolve().is_relative_to(base.resolve()) or p.is_symlink() or not p.is_file() or p.stat().st_size!=row['bytes']:return False
  digest=hashlib.sha256()
  with p.open('rb') as f:
   for block in iter(lambda:f.read(256*1024),b''):digest.update(block)
  if digest.hexdigest()!=row['sha256']:return False
  if row.get('schema'):
   from .compact_history import schema_path
   from .prepared_history import digest as file_digest
   meta=schema_path(p)
   if not meta.is_file() or meta.stat().st_size!=row['schema']['bytes'] or file_digest(meta)!=row['schema']['sha256']:return False
  return True
 except (OSError,ValueError,KeyError,TypeError):return False
def import_file(root,download,metadata):
 root=Path(root).resolve();p=Path(download).resolve();row=json.loads(metadata) if isinstance(metadata,str) else metadata
 source=row['source_id'];kind=row['source'];sha=row['sha256'];name=row['name'];key=row['key']
 if not re.fullmatch(r'(?:pc|[0-9a-f]{32})',source) or kind not in ('Local','SmartESS'):raise ValueError('Invalid archive source')
 if row.get('device_id')!='inverter-1':raise ValueError('Archive belongs to another device')
 if not re.fullmatch('[0-9a-f]{64}',sha) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.csv',name):raise ValueError('Invalid archive metadata')
 date.fromisoformat(name[:-4])
 if not isinstance(key,str) or len(key)>512 or '..' in key or '\\' in key:raise ValueError('Invalid archive key')
 if not p.is_relative_to(root/'Data/ArchiveDownloads') or p.is_symlink():raise ValueError('Invalid staged archive')
 if p.stat().st_size!=int(row['bytes']) or not 0<p.stat().st_size<=128*1024*1024:raise ValueError('Archive size mismatch')
 digest=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(256*1024),b''):digest.update(block)
 if digest.hexdigest()!=sha:raise ValueError('Archive checksum mismatch')
 codec=None
 metadata=row.get('schema')
 if metadata:
  from .compact_history import Codec,schema_path
  from .prepared_history import digest as file_digest
  schema=schema_path(p)
  if schema.stat().st_size!=metadata['bytes'] or file_digest(schema)!=metadata['sha256']:raise ValueError('Compact archive schema mismatch')
  codec=Codec(p)
 with p.open('r',encoding='utf-8-sig',newline='') as f:
  reader=csv.DictReader(f,strict=True);fields=reader.fieldnames or []
  if not any(x in fields for x in ('timestamp','Timestamp','time')):raise ValueError('CSV has no supported time column')
  records=0
  from .history_reader import HistoryReader
  for item in reader:
   if None in item:raise ValueError('Invalid CSV row')
   if codec:item=codec.decode(item)
   timestamp=item.get('time') or item.get('Timestamp') or item.get('timestamp')
   parsed=HistoryReader._parse_dt(timestamp,date.fromisoformat(name[:-4]))
   if parsed is None or parsed.date()!=date.fromisoformat(name[:-4]):raise ValueError('CSV has invalid or out-of-day timestamp')
   records+=1
 if not records:raise ValueError('CSV has no history records')
 with LOCK:
  base=root/'Data/SynchronizedArchive'/source;base.mkdir(parents=True,exist_ok=True)
  if not base.resolve().is_relative_to(root):raise ValueError('Archive destination escaped storage')
  manifest=base/'manifest.json'
  try:state=json.loads(manifest.read_text(encoding='utf-8'))
  except FileNotFoundError:state={'contract':'ducksolar.history-sync.v1','files':{}}
  previous=state['files'].get(key);folder='History' if kind=='SmartESS' else 'Logs/Inverter'
  identity=hashlib.sha256((sha+metadata['sha256']).encode()).hexdigest() if metadata else sha
  relative=f'{folder}/{identity}/{name}';destination=base/relative
  if previous and previous['sha256']==sha and import_status(root,row):return {'state':'unchanged','records':records}
  destination.parent.mkdir(parents=True,exist_ok=True)
  if shutil.disk_usage(base).free<p.stat().st_size+16*1024*1024:raise ValueError('Insufficient history storage')
  temp=destination.with_suffix('.part')
  with p.open('rb') as inp,temp.open('wb') as out:shutil.copyfileobj(inp,out,256*1024);out.flush();os.fsync(out.fileno())
  if codec:
   schema_temp=Path(str(destination)+'.schema.tmp');shutil.copyfile(schema_path(p),schema_temp);os.replace(schema_temp,schema_path(destination))
  os.replace(temp,destination)
  # Keep old objects intact; the manifest selects the latest explicit revision.
  committed=destination.stat()
  state['files'][key]=dict(row,path=relative,records=records,mtime_ns=committed.st_mtime_ns,inode=committed.st_ino,previous_sha256=previous['sha256'] if previous else None)
  temporary=manifest.with_suffix('.tmp')
  with temporary.open('w',encoding='utf-8') as f:json.dump(state,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
  os.replace(temporary,manifest)
  return {'state':'revision' if previous else 'imported','records':records,'preserved_live':True}

def verified_paths(root):
 root=Path(root);paths=[];count=0
 with LOCK:
  for manifest in sorted((root/'Data/SynchronizedArchive').glob('*/manifest.json')):
   if manifest.is_symlink():continue
   try:
    state=json.loads(manifest.read_text(encoding='utf-8'))
    if state.get('contract')!='ducksolar.history-sync.v1':continue
    for row in state['files'].values():
     p=manifest.parent/row['path']
     if row.get('device_id')=='inverter-1' and p.resolve().is_relative_to(manifest.parent.resolve()) and not p.is_symlink() and p.is_file() and p.stat().st_size==row['bytes']:
      st=p.stat()
      if (st.st_mtime_ns,st.st_ino)!=(row.get('mtime_ns'),row.get('inode')):
       digest=hashlib.sha256()
       with p.open('rb') as f:
        for block in iter(lambda:f.read(256*1024),b''):digest.update(block)
       if digest.hexdigest()!=row['sha256']:continue
      paths.append(p);count+=1
   except (OSError,ValueError,KeyError,TypeError):continue
 return paths,count
