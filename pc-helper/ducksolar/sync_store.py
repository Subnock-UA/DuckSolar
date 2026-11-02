"""Content addressed snapshots. Transfer blocks, retain unchanged files by reference."""
import hashlib,json,os,re,shutil,time,copy,threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
BLOCK=256*1024
HEX=re.compile(r'^[0-9a-f]{64}$')
CONTRACT='ducksolar.history-sync.v1'
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def hashed(value):return hashlib.sha256(canonical(value)).hexdigest()
def atomic(path,value):
 path=Path(path);payload=canonical(value)
 try:
  if path.read_bytes()==payload:return
 except OSError:pass
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
 try:
  with tmp.open('wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
  deadline=time.monotonic()+20
  while True:
   try:os.replace(tmp,path);break
   except PermissionError:
    if time.monotonic()>=deadline:raise
    time.sleep(.1)
 finally:tmp.unlink(missing_ok=True)
def fingerprint(path):
 s=Path(path).stat();return [s.st_size,s.st_mtime_ns,s.st_ino]
def checked(desc):
 if not isinstance(desc,dict) or not HEX.fullmatch(desc.get('sha256','')) or type(desc.get('bytes')) is not int or not 0<=desc['bytes']<=2*1024**3:raise ValueError('Invalid snapshot')
 blocks=desc.get('blocks')
 if not isinstance(blocks,list) or len(blocks)>8192:raise ValueError('Invalid blocks')
 total=0
 for b in blocks:
  if set(b)!={'sha256','bytes'} or not HEX.fullmatch(b['sha256']) or type(b['bytes']) is not int or not 0<b['bytes']<=BLOCK:raise ValueError('Invalid block')
  total+=b['bytes']
 if total!=desc['bytes']:raise ValueError('Snapshot size mismatch')
 return desc
@contextmanager
def index_lock(root):
 path=Path(root)/'index.lock';path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a+b') as f:
  if path.stat().st_size==0:f.write(b'0');f.flush()
  deadline=time.monotonic()+30
  while True:
   try:
    f.seek(0)
    if os.name=='nt':
     import msvcrt
     msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    else:
     import fcntl
     fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    break
   except OSError:
    if time.monotonic()>deadline:raise
    time.sleep(.05)
  try:yield
  finally:
   f.seek(0)
   if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
   else:fcntl.flock(f,fcntl.LOCK_UN)

class Changes(dict):
 """Entries are replaced, never edited in place. Capture only changed keys."""
 def __init__(self,value):super().__init__(value);self.before={}
 def __setitem__(self,key,value):
  if key in self and self[key]==value:return
  if key not in self.before:self.before[key]=self.get(key)
  super().__setitem__(key,value)
 def __delitem__(self,key):
  if key not in self.before:self.before[key]=self[key]
  super().__delitem__(key)
 def pop(self,key,*default):
  if key in self:value=self[key];del self[key];return value
  if default:return default[0]
  raise KeyError(key)
 def setdefault(self,key,value=None):
  if key not in self:self[key]=value
  return self[key]

class Store:
 GROUPS=('sources','files','blocks','verified','descriptors')
 def __init__(self,root):
  self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'index.json'
  with index_lock(self.root):
   try:self.index=json.loads(self.path.read_text('utf-8'))
   except (OSError,ValueError):self.index={}
   try:self._disk_stamp=fingerprint(self.path)
   except OSError:self._disk_stamp=None
  self._epoch=self.index.get('gc_epoch',0);self._owners=None;self._source_owners=None
  self._wrap()
  for group in ('sources','files'):
   for entry in self.index[group].values():
    desc=entry.get('snapshot')
    if isinstance(desc,dict) and HEX.fullmatch(desc.get('sha256','')):self.index['descriptors'].setdefault(desc['sha256'],desc)
  self.stats=dict(new_blocks=0,new_bytes=0,linked_files=0,written_files=0,repaired_objects=0)
 def _wrap(self):
  for group in self.GROUPS:self.index[group]=Changes(self.index.get(group,{}))
 def save(self):
  changes={g:dict(self.index[g].before) for g in self.GROUPS}
  if not any(changes.values()) and self.index.get('gc_epoch',0)==self._epoch:return False
  with index_lock(self.root):
   try:current=json.loads(self.path.read_text('utf-8'))
   except (OSError,ValueError):current={}
   current_epoch=current.get('gc_epoch',0)
   for group in self.GROUPS:
    merged=current.setdefault(group,{})
    for key,old in changes[group].items():
     if key not in self.index[group]:
      if merged.get(key)==old:merged.pop(key,None)
      continue
     value=self.index[group][key]
     if current_epoch>self._epoch and old is not None and key not in merged:continue
     if key in merged and merged[key]!=old and merged[key]!=value:
      if group=='descriptors':raise ValueError('Conflicting snapshot descriptor')
      existing=merged[key]
      try:valid=existing.get('fingerprint')==fingerprint(existing['path'])
      except (OSError,KeyError,TypeError):valid=False
      if valid:continue
     merged[key]=value
   current['gc_epoch']=max(current_epoch,self.index.get('gc_epoch',0))
   atomic(self.path,current);self._disk_stamp=fingerprint(self.path);self.index=current;self._epoch=current['gc_epoch'];self._wrap();self._owners=None;self._source_owners=None
  return True
 def block_path(self,sha):
  if not HEX.fullmatch(sha):raise ValueError('Invalid block SHA')
  return self.root/'blocks'/sha[:2]/sha
 def _register(self,desc):
  checked(desc);old=self.index['descriptors'].get(desc['sha256'])
  if old is not None and old!=desc:raise ValueError('Snapshot descriptor mismatch')
  if old is None:self.index['descriptors'][desc['sha256']]=desc;self._owners=None
 def _quarantine(self,path):
  try:path.rename(path.with_name(path.name+'.damaged-'+uuid4().hex))
  except FileNotFoundError:pass
 def _describe(self,path,cancelled=lambda:False):
  path=Path(path).resolve();before=fingerprint(path);full=hashlib.sha256();blocks=[]
  with path.open('rb') as f:
   while data:=f.read(BLOCK):
    if cancelled():raise InterruptedError('Синхронізацію зупинено')
    full.update(data);blocks.append(dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
  if fingerprint(path)!=before:raise ValueError('File changed during sync snapshot')
  return dict(sha256=full.hexdigest(),bytes=before[0],blocks=blocks)
 def _valid_full(self,path,desc):
  try:
   if not path.is_file() or path.stat().st_size!=desc['bytes']:return False
   known=self.index['files'].get(desc['sha256'],{})
   if known.get('version')==2 and known.get('path')==str(path.resolve()) and known.get('fingerprint')==fingerprint(path) and known.get('snapshot')==desc:return True
   return self._describe(path)==desc
  except (OSError,ValueError):return False
 def _canonical(self,path,desc,cancelled=lambda:False):
  stable=self.root/'files'/desc['sha256'];stable.parent.mkdir(parents=True,exist_ok=True)
  known=self.index['files'].get(desc['sha256'],{})
  try:
   if known.get('version')==2 and known.get('path')==str(stable) and known.get('fingerprint')==fingerprint(stable) and known.get('snapshot')==desc:return stable
  except OSError:pass
  # Legacy canonical objects might be hardlinked to appendable originals.
  # Copy once into a sealed v2 object, also when hardlinks are unavailable.
  if stable.exists() and not self._valid_full(stable,desc):self._quarantine(stable)
  source=stable if stable.exists() else Path(path)
  tmp=stable.with_name(stable.name+'.'+uuid4().hex+'.tmp')
  try:
   full=hashlib.sha256();blocks=[];count=0
   with source.open('rb') as inp,tmp.open('wb') as out:
    while data:=inp.read(BLOCK):
     if cancelled():raise InterruptedError('Синхронізацію зупинено')
     full.update(data);count+=len(data);blocks.append(dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)));out.write(data)
    out.flush();os.fsync(out.fileno())
   if dict(sha256=full.hexdigest(),bytes=count,blocks=blocks)!=desc:raise ValueError('Canonical snapshot checksum mismatch')
   os.replace(tmp,stable);self.stats['written_files']+=1
  finally:tmp.unlink(missing_ok=True)
  self.index['files'][desc['sha256']]=dict(path=str(stable),fingerprint=fingerprint(stable),snapshot=desc,version=2)
  return stable
 def _bind(self,desc,path,full=False):
  self._register(desc);path=Path(path).resolve();fp=fingerprint(path);offset=0
  for block in desc['blocks']:
   ref=dict(path=str(path),offset=offset,bytes=block['bytes'],fingerprint=fp)
   self.index['blocks'][block['sha256']]=ref
   self.index['verified'][block['sha256']]=dict(ref,version=2)
   offset+=block['bytes']
  self.index['sources'][str(path)]=dict(fingerprint=fp,snapshot=desc)
  if full:self.index['files'][desc['sha256']]=dict(path=str(path),fingerprint=fp,snapshot=desc,version=2)
 def existing(self,desc):
  checked(desc);self._register(desc);sha=desc['sha256'];entry=self.index['files'].get(sha,{})
  stable=self.root/'files'/sha
  # Hot path must not enumerate every source for every retained object.
  if self._valid_full(stable,desc):
   stable=self._canonical(stable,desc);self._bind(desc,stable,full=True);return stable
  if self._source_owners is None:
   self._source_owners={}
   for path,value in self.index['sources'].items():self._source_owners.setdefault(value.get('snapshot',{}).get('sha256'),[]).append(path)
  candidates=[stable]
  if entry.get('path'):candidates.append(Path(entry['path']))
  candidates.extend(Path(p) for p in self._source_owners.get(sha,[]))
  candidates.extend([self.root.parent/'inputs'/(sha+'.csv'),self.root.parent/'inputs'/(sha+'.json')])
  seen=set()
  for path in candidates:
   key=str(path.resolve())
   if key in seen:continue
   seen.add(key)
   if self._valid_full(path,desc):
    stable=self._canonical(path,desc);self._bind(desc,stable,full=True);self.stats['repaired_objects']+=1;return stable
  return None
 def _block_candidates(self,sha):
  physical=self.block_path(sha)
  if physical.is_file():yield physical,0,physical.stat().st_size
  for group in ('blocks','verified'):
   ref=self.index[group].get(sha)
   if ref:yield Path(ref['path']),ref.get('offset',0),ref['bytes']
 def _locate(self,sha,size=None):
  seen=set()
  for path,offset,length in self._block_candidates(sha):
   key=(str(path),offset,length)
   if key in seen:continue
   seen.add(key)
   try:
    if not 0<length<=BLOCK:raise ValueError('Invalid block length')
    if size is not None and length!=size:raise ValueError('Block size mismatch')
    fp=fingerprint(path);proof=self.index['verified'].get(sha,{})
    if proof.get('version')==2 and proof.get('path')==str(path) and proof.get('offset')==offset and proof.get('bytes')==length and proof.get('fingerprint')==fp:return path,offset,length
    with path.open('rb') as f:f.seek(offset);data=f.read(length)
    if not 0<len(data)<=BLOCK or len(data)!=length or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Block checksum mismatch')
    self.index['verified'][sha]=dict(path=str(path),offset=offset,bytes=length,fingerprint=fp,version=2)
    return path,offset,length
   except (OSError,ValueError):
    if path==self.block_path(sha) and path.is_file():self._quarantine(path)
  # Locate an owner descriptor only on a miss; ordinary reads stay constant-time.
  if self._owners is None:
   self._owners={}
   for full,desc in self.index['descriptors'].items():
    for block in desc.get('blocks',[]):self._owners.setdefault(block['sha256'],[]).append(full)
  owners=list(self._owners.get(sha,[]))
  for full in owners:
   desc=self.index['descriptors'][full];path=self.existing(desc)
   if path is None:continue
   ref=self.index['blocks'].get(sha)
   if ref and (size is None or ref['bytes']==size):return Path(ref['path']),ref['offset'],ref['bytes']
  raise FileNotFoundError('Missing verified sync block '+sha)
 def read(self,sha):
  path,offset,length=self._locate(sha)
  with path.open('rb') as f:f.seek(offset);data=f.read(length)
  if len(data)!=length or hashlib.sha256(data).hexdigest()!=sha:
   self.index['verified'].pop(sha,None)
   if path==self.block_path(sha):self._quarantine(path)
   # Re-resolve once after a concurrent edit; never return unchecked bytes.
   path,offset,length=self._locate(sha)
   with path.open('rb') as f:f.seek(offset);data=f.read(length)
   if len(data)!=length or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Sync block changed '+sha)
  return data
 def has(self,block):
  try:self._locate(block['sha256'],block['bytes']);return True
  except (OSError,ValueError,KeyError):return False
 def put(self,sha,data):
  if not 0<len(data)<=BLOCK or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Block checksum mismatch')
  path=self.block_path(sha);path.parent.mkdir(parents=True,exist_ok=True)
  if path.exists() and path.read_bytes()!=data:self._quarantine(path)
  if not path.exists():
   tmp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
   try:
    with tmp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
   finally:tmp.unlink(missing_ok=True)
   self.stats['new_blocks']+=1;self.stats['new_bytes']+=len(data)
  ref=dict(path=str(path),offset=0,bytes=len(data),fingerprint=fingerprint(path))
  self.index['blocks'][sha]=ref;self.index['verified'][sha]=dict(ref,version=2)
 def snapshot(self,path,immutable=False,copy_blocks=False,cancelled=lambda:False):
  path=Path(path).resolve();fp=fingerprint(path);old=self.index['sources'].get(str(path),{})
  desc=old.get('snapshot') if old.get('fingerprint')==fp else None
  if desc is None:desc=self._describe(path,cancelled)
  checked(desc);self._register(desc)
  if immutable:
   stable=self._canonical(path,desc,cancelled);self._bind(desc,stable,full=True)
  else:
   stable=self.existing(desc)
   self._bind(desc,stable or path,full=stable is not None)
  self.index['sources'][str(path)]=dict(fingerprint=fp,snapshot=desc);self._source_owners=None
  if copy_blocks:
   with (stable or path).open('rb') as f:
    for block in desc['blocks']:
     if cancelled():raise InterruptedError('Синхронізацію зупинено')
     self.put(block['sha256'],f.read(block['bytes']))
  return desc
 def materialize(self,desc,destination,mutable=False,cancelled=lambda:False):
  checked(desc);self._register(desc);destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
  old=self.index['sources'].get(str(destination),{})
  if destination.is_file() and old.get('snapshot')==desc and old.get('fingerprint')==fingerprint(destination):
   if not mutable:self.snapshot(destination,immutable=True,cancelled=cancelled)
   return False
  existing=self.existing(desc)
  if existing is not None and existing==destination:return False
  tmp=destination.with_name(destination.name+'.'+uuid4().hex+'.sync')
  try:
   linked=False
   if existing is not None and not mutable:
    try:os.link(existing,tmp);linked=True;self.stats['linked_files']+=1
    except OSError:pass
   if not linked:
    full=hashlib.sha256();count=0
    with tmp.open('wb') as f:
     for block in desc['blocks']:
      if cancelled():raise InterruptedError('Синхронізацію зупинено')
      data=self.read(block['sha256']);f.write(data);full.update(data);count+=len(data)
     f.flush();os.fsync(f.fileno())
    if count!=desc['bytes'] or full.hexdigest()!=desc['sha256']:raise ValueError('Snapshot checksum mismatch')
    self.stats['written_files']+=1
   os.replace(tmp,destination);self.index['sources'][str(destination)]=dict(fingerprint=fingerprint(destination),snapshot=desc)
   if not mutable:self.snapshot(destination,immutable=True,cancelled=cancelled)
   return True
  finally:tmp.unlink(missing_ok=True)
 def prune(self,descriptors):
  descriptors=list(descriptors)
  # Refuse cleanup unless every retained byte is actually readable.
  for desc in descriptors:
   checked(desc)
   if self.existing(desc) is None and not all(self.has(block) for block in desc['blocks']):raise ValueError('Cannot prune: retained snapshot unavailable')
  result=dict(removed_files=0,freed_bytes=0)
  def remove(path):
   st=path.stat()
   if st.st_nlink==1:result['freed_bytes']+=getattr(st,'st_blocks',0)*512 if hasattr(st,'st_blocks') else st.st_size
   path.unlink();result['removed_files']+=1
  full={d['sha256'] for d in descriptors};blocks={b['sha256'] for d in descriptors for b in d['blocks']}
  for group,keep in [('files',full),('descriptors',full),('blocks',blocks),('verified',blocks)]:
   for key in list(self.index[group]):
    if key not in keep:del self.index[group][key]
  for key,value in list(self.index['sources'].items()):
   if value.get('snapshot',{}).get('sha256') not in full:del self.index['sources'][key]
  self.index['gc_epoch']=self.index.get('gc_epoch',0)+1;self._owners=None
  for path in (self.root/'files').glob('*'):
   if path.is_file() and HEX.fullmatch(path.name) and path.name not in full:remove(path)
  for path in (self.root/'blocks').glob('*/*'):
   if path.is_file() and HEX.fullmatch(path.name) and path.name not in blocks:remove(path)
  return result
 def rebase(self,old,new):
  old=str(Path(old).resolve());new=str(Path(new).resolve())
  for group in ('files','blocks','verified'):
   for key,value in list(self.index[group].items()):
    if value['path'].startswith(old+os.sep):self.index[group][key]=dict(value,path=new+value['path'][len(old):])
  for key,value in list(self.index['sources'].items()):
   if key.startswith(old+os.sep):self.index['sources'][new+key[len(old):]]=value;del self.index['sources'][key]

_sessions={}
_sessions_lock=threading.RLock()
@contextmanager
def session_store(root):
 """One serialized Store per root, refreshed when another process commits."""
 root=Path(root).resolve();key=str(root)
 with _sessions_lock:
  entry=_sessions.setdefault(key,dict(lock=threading.RLock(),store=None,stamp=None))
 with entry['lock']:
  path=root/'index.json'
  try:stamp=fingerprint(path)
  except OSError:stamp=None
  if entry['store'] is None or stamp!=entry['stamp']:
   # Physical accepted blocks are durable independently of metadata.
   if entry['store'] is not None:entry['store'].save()
   entry['store']=Store(root)
  try:yield entry['store']
  finally:entry['stamp']=entry['store']._disk_stamp

def release_store(root):
 key=str(Path(root).resolve())
 with _sessions_lock:entry=_sessions.get(key)
 if entry:
  with entry['lock']:
   if entry['store']:entry['store'].save()
   with _sessions_lock:_sessions.pop(key,None)
