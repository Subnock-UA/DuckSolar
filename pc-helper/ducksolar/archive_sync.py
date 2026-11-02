"""Read-only LAN archive discovery and immutable, resumable CSV downloads."""
import hashlib,json,os,re,shutil,threading,uuid,ipaddress
from pathlib import Path
DATE=re.compile(r'^\d{4}-\d{2}-\d{2}\.csv$')
CHUNK=256*1024
class ArchiveExport:
 def __init__(self,root):
  self.root=Path(root).resolve();self.objects=self.root/'Data/AndroidSupport/ArchiveObjects';self.objects.mkdir(parents=True,exist_ok=True)
  self.lock=threading.Lock();self.cache={}
 def sources(self):
  ids=set()
  for job in (self.root/'Data/AndroidSupport/Migrations').glob('*/result.json'):
   try:
    plan=json.loads(job.with_name('plan.json').read_text(encoding='utf-8'));installation=plan['installation']
    if re.fullmatch('[0-9a-f]{32}',installation):ids.add(installation)
   except (OSError,ValueError,KeyError,TypeError):pass
  for parent in (self.root/'Logs/Inverter/AndroidBackups',self.root/'Data/AndroidSupport/Received'):
   if parent.exists():ids.update(p.name for p in parent.iterdir() if p.is_dir() and re.fullmatch('[0-9a-f]{32}',p.name))
  return [{'id':'pc','label':'Архів ПК (Local та SmartESS)','device_id':'inverter-1'}]+[{'id':i,'label':'Android '+i[:8],'device_id':'inverter-1'} for i in sorted(ids) if self._candidates(i)]
 def _safe(self,p):
  return p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(self.root) and not any(x.lower() in ('clean','devices') for x in p.parts)
 def _candidates(self,source):
  found={}
  if source=='pc':
   for kind,base in [('Local',self.root/'Logs/Inverter'),('SmartESS',self.root/'History')]:
    for p in base.rglob('*.csv'):
     if self._safe(p) and DATE.fullmatch(p.name) and 'AndroidBackups' not in p.parts:
      found[kind+'/'+p.relative_to(base).as_posix()]=(p,kind,p.name)
  elif re.fullmatch('[0-9a-f]{32}',source):
   # Prefer append backups, then completed legacy uploads, never old revision copies.
   base=self.root/'Logs/Inverter/AndroidBackups'/source
   for p in base.glob('*/Live/current.csv'):
    name=p.parents[1].name;kind='SmartESS' if name.startswith('History_') else 'Local';day=name[-14:]
    if self._safe(p) and DATE.fullmatch(day):found[kind+'/'+name]=(p,kind,day)
   for p in (self.root/'Data/AndroidSupport/Received'/source/'inverter').glob('*/latest.log'):
    name=p.parent.name;kind='SmartESS' if name.startswith('History_') else 'Local';day=name[-14:]
    if self._safe(p) and DATE.fullmatch(day) and kind+'/'+name not in found:
     try:
      meta=json.loads(p.with_suffix('.revision.json').read_text());valid=meta['bytes']==p.stat().st_size
     except (OSError,ValueError,KeyError):valid=False
     if valid:found[kind+'/'+name]=(p,kind,day)
  else:raise ValueError('Invalid archive source')
  if source!='pc':
   for result in sorted((self.root/'Data/AndroidSupport/Migrations').glob('*/result.json')):
    try:
     plan=json.loads(result.with_name('plan.json').read_text(encoding='utf-8'))
     if plan['installation']!=source or json.loads(result.read_text())['state']!='ready':continue
     base=result.parent/'work/Data/CompactHistory'/plan['device_id']
     for kind in ('Local','SmartESS'):
      for p in sorted((base/kind).glob('*/*.csv')):
       if self._safe(p) and DATE.fullmatch(p.name):found[kind+'/prepared/'+result.parent.name+'/'+p.parent.name+'/'+p.name]=(p,kind,p.name)
    except (OSError,ValueError,KeyError,TypeError):continue
  return found
 def _object(self,p):
  st=p.stat();key=(str(p),st.st_size,st.st_mtime_ns)
  cached=self.cache.get(key)
  if cached and (self.objects/(cached['sha256']+'.csv')).is_file():return cached
  if not 0<st.st_size<=128*1024*1024:raise ValueError('Archive file exceeds 128 MiB budget')
  if shutil.disk_usage(self.objects).free<st.st_size+16*1024*1024:raise ValueError('Insufficient snapshot space')
  temporary=self.objects/(uuid.uuid4().hex+'.part');digest=hashlib.sha256();size=0
  try:
   with p.open('rb') as inp,temporary.open('wb') as out:
    remaining=st.st_size
    while remaining:
     line=inp.readline(min(remaining,1024*1024));remaining-=len(line)
     if not line:raise ValueError('Archive changed during snapshot')
     if len(line)==1024*1024 and not line.endswith(b'\n'):raise ValueError('CSV record exceeds 1 MiB budget')
     if not line.endswith(b'\n'):break # active writer's uncommitted final row
     digest.update(line);out.write(line);size+=len(line)
    out.flush();os.fsync(out.fileno())
   after=p.stat()
   if (after.st_size,after.st_mtime_ns)!=(st.st_size,st.st_mtime_ns):raise ValueError('Archive changed; retry catalog')
   if not size:raise ValueError('No complete CSV records')
   sha=digest.hexdigest();dest=self.objects/(sha+'.csv')
   if dest.exists():temporary.unlink()
   else:os.replace(temporary,dest)
   result={'sha256':sha,'bytes':size};self.cache[key]=result
   if len(self.cache)>4096:self.cache.clear()
   return result
  finally:temporary.unlink(missing_ok=True)
 def catalog(self,source,cursor=0,limit=32):
  if not 0<=cursor or not 1<=limit<=32:raise ValueError('Invalid archive page')
  with self.lock:
   candidates=sorted(self._candidates(source).items());items=[]
   generation=hashlib.sha256(json.dumps([k for k,v in candidates],separators=(',',':')).encode()).hexdigest()
   for key,(p,kind,name) in candidates[cursor:cursor+limit]:
    row=dict(self._object(p),key=key,name=name,source=kind,device_id='inverter-1')
    if Path(str(p)+'.schema.json').is_file():schema=Path(str(p)+'.schema.json')
    elif source!='pc':
     backup_name=p.parents[1].name if p.name=='current.csv' else p.parent.name
     schema=self.root/'Data/AndroidSupport/Received'/source/'inverter'/(backup_name+'.schema.json')/'latest.log'
    else:schema=Path(str(p)+'.schema.json')
    if schema.is_file() and self._safe(schema):
     raw=schema.read_bytes();value=json.loads(raw)
     if value.get('format')!='ducksolar.compact-history.v2':raise ValueError('Unknown compact history schema')
     sha=hashlib.sha256(raw).hexdigest();target=self.objects/(sha+'.csv')
     if not target.exists():
      temporary=target.with_suffix('.tmp');temporary.write_bytes(raw);os.replace(temporary,target)
     row['schema']=dict(sha256=sha,bytes=len(raw))
    items.append(row)
   return {'source_id':source,'generation':generation,'items':items,'total':len(candidates),'next_cursor':cursor+len(items) if cursor+len(items)<len(candidates) else None}
 def chunk(self,sha,offset,length):
  if not re.fullmatch('[0-9a-f]{64}',sha) or not 0<=offset or not 1<=length<=CHUNK:raise ValueError('Invalid archive chunk')
  p=self.objects/(sha+'.csv');size=p.stat().st_size
  if offset+length>size:raise ValueError('Archive range outside object')
  with p.open('rb') as f:f.seek(offset);data=f.read(length)
  if len(data)!=length:raise ValueError('Archive object truncated')
  return data
 def routes(self,source):
  if not re.fullmatch('[0-9a-f]{32}',source):raise ValueError('Select previous Android installation')
  identities={};routes={}
  base=self.root/'Data/AndroidSupport/Received'/source/'diagnostic'
  for p in sorted(base.glob('*ESS_Events*/latest.log')):
   if not self._safe(p):continue
   with p.open(encoding='utf-8-sig') as f:
    for line in f:
     if len(line)>65536:continue
     try:
      row=json.loads(line);key=(row.get('session_id'),row.get('logger_id'))
      if row.get('code')=='ess.native_route.management_received':
       frame=bytes.fromhex(row.get('hex',''))
       if len(frame)>=10 and int.from_bytes(frame[4:6],'big')+6==len(frame) and frame[6:10]==b'\xff\x02\x00\x02':
        pn=frame[10:].decode('ascii').strip('\0')
        if re.fullmatch('[A-Za-z0-9_-]{1,64}',pn):identities[key]=pn
      elif row.get('code')=='ess.native_route.configured' and key in identities:
       host=row['original_endpoint'];port=int(row['original_port'])
       if not re.fullmatch('[A-Za-z0-9.-]{1,253}',host) or '.' not in host or not 1<=port<=65535:continue
       try:
        if not ipaddress.ip_address(host).is_global:continue
       except ValueError:pass
       routes[identities[key]]={'pn':identities[key],'original_endpoint':host,'original_port':port,'source_id':source,'recorded_at':row['timestamp']}
     except (ValueError,KeyError,TypeError,UnicodeError):continue
  return {'routes':list(routes.values())}
