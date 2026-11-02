"""PC-only cross-plan reuse. Content and model identities, never row positions."""
import copy,hashlib,json,shutil,sqlite3,zipfile,gzip
from uuid import uuid4
from datetime import date,datetime,timedelta
from pathlib import Path
from ducksolar.prepared_history import digest,write_json,PreparedHistory
from ducksolar.compact_history import schema_path
from ducksolar.preparation_model import decode_model,apply_model
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader

class Reuse:
 def __init__(self,job,plan,cfg,cancelled):
  self.job=job;self.plan=plan;self.cfg=cfg;self.cancelled=cancelled
  self.previous=[];self.conversions={};self.stats=dict(conversions_reused=0,conversions_new=0,prepared_objects_reused=0,indices_reused=0,hourly_reused=0,months_reused=0,open_month_seeds_reused=0)
  from preparation_lock import running
  model=decode_model(plan['model'],plan.get('model_types'))
  scope=lambda p:(p.get('installation'),p.get('device_id'),p.get('pn'))
  for path in sorted(job.parent.glob('*/plan.json'),key=lambda p:p.stat().st_mtime,reverse=True):
   if path.parent==job or running(path.parent):continue
   try:
    old=json.loads(path.read_text('utf-8'))
    if scope(old)!=scope(plan) or decode_model(old['model'],old.get('model_types'))!=model:continue
    self.previous.append((path.parent,old))
   except (OSError,ValueError,KeyError):continue
  for folder,old in self.previous:
   originals={}
   for row in old['files']:originals.setdefault(row['sha256'],[]).append(row)
   for meta in (folder/'work/Data/CompactHistory'/plan['device_id']).rglob('*.verified.json'):
    try:
     proof=json.loads(meta.read_text('utf-8'));csv=meta.with_name(meta.name.removesuffix('.verified.json')+'.csv')
     origin=csv.parent.parent.name;day=csv.stem
     for row in originals.get(proof['original'],[]):
      if row['source']==origin and row['day']==day:
       self.conversions.setdefault((origin,day,row['sha256'],row.get('schema',{}).get('sha256')),(csv,proof))
     self.conversions.setdefault((origin,day,proof['csv'],proof['schema']),(csv,proof))
    except (OSError,ValueError,KeyError):continue
 def check(self):
  if self.cancelled():raise InterruptedError('Міграцію зупинено')
 def conversion(self,item,destination):
  self.check();key=(item['source'],item['day'],item['sha256'],item.get('schema',{}).get('sha256'))
  candidate=self.conversions.get(key)
  if not candidate:return None
  source,proof=candidate
  if not source.is_file() or not schema_path(source).is_file():return None
  if digest(source,self.cancelled)!=proof['csv'] or digest(schema_path(source),self.cancelled)!=proof['schema']:return None
  destination.parent.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(source,destination);shutil.copyfile(schema_path(source),schema_path(destination))
  if digest(destination,self.cancelled)!=proof['csv'] or digest(schema_path(destination),self.cancelled)!=proof['schema']:raise ValueError('Reused conversion changed')
  self.stats['conversions_reused']+=1
  return proof['result']
 def seed_objects(self,work):
  from ducksolar.projection_contract import folder as index_folder,validate
  for previous,old in self.previous:
   self.check();oldwork=previous/'work'
   for source in (oldwork/'Data/PreparedHistory/objects').glob('*.jsonl.gz'):
    self.check();target=work/'Data/PreparedHistory/objects'/source.name
    if target.exists():continue
    try:
     with gzip.open(source,'rb') as stream:
      metadata=json.loads(stream.readline(1024*1024))
      key=hashlib.sha256(json.dumps([metadata['contract'],metadata['model'],metadata['source'],metadata['day'],metadata['raw_sha256']]).encode()).hexdigest()
      if source.name!=key+'.jsonl.gz':continue
      while stream.read(1024*1024):self.check()
    except (OSError,ValueError,KeyError,EOFError):continue
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);self.stats['prepared_objects_reused']+=1
   for source in index_folder(oldwork).glob('*.db'):
    self.check();target=index_folder(work)/source.name
    if target.exists():continue
    try:validate(source)
    except (sqlite3.DatabaseError,ValueError):continue
    target.parent.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(target)
    try:src.backup(dst)
    finally:dst.close();src.close()
    validate(target);self.stats['indices_reused']+=1
 def seed_hourly(self,reader):
  from ducksolar.history_views import HistoryViews
  from ducksolar.hourly_projection import export_portable
  from ducksolar.wire import decode
  view=HistoryViews(reader,reader.cfg,self.plan['device_id'])
  stores={};file_keys={}
  oldviews=[]
  for previous,old in self.previous:
   cfg=copy.deepcopy(reader.cfg);cfg.root_dir=str(previous/'work');other=HistoryReader(cfg)
   other.available_dates(refresh=True);oldviews.append((other,HistoryViews(other,cfg,self.plan['device_id'])))
  def identities(r,day,source):
   store=stores.get(id(r))
   if store is None:store=stores[id(r)]=PreparedHistory(r)
   result=[];seen=set()
   for origin,paths in zip(('Local','SmartESS'),r.find_day_files(day)):
    if source not in ('Auto',origin):continue
    for path in paths:
     key=(id(r),str(path),origin,day)
     if key not in file_keys:file_keys[key]=store.identity(path,origin,day,self.cancelled)[0]
     identity=(origin,file_keys[key])
     if identity not in seen:result.append(identity);seen.add(identity)
   return tuple(result)
  for day in reader.available_dates(refresh=True):
   if day>=date.today():continue
   for source in ('Local','SmartESS','Auto'):
    self.check();key=('hourly-chunk',day,source);name='period-'+hashlib.sha256(repr(key).encode()).hexdigest()+'.json'
    current=identities(reader,day,source)
    if not current:continue
    for other,oldview in oldviews:
     path=oldview.view_path/name
     if not path.is_file() or identities(other,day,source)!=current:continue
     try:saved=decode(json.loads(path.read_text('utf-8')))
     except (OSError,ValueError,KeyError):continue
     revision=hashlib.sha256(repr(([(day,oldview._revision(day,source))],'period-v1-no-daily',key)).encode()).hexdigest()
     if saved.get('revision')!=revision or not isinstance(saved.get('value'),list):continue
     export_portable(view,day,source,saved['value']);self.stats['hourly_reused']+=1;break
 def month(self,reader,storage,anchor,source,destination):
  from ducksolar.energy_streaming import _files,ALGORITHM
  from ducksolar.energy_accounting import ZONE
  from ducksolar.balance_portable import revision
  start=datetime(anchor.year,anchor.month,1,tzinfo=ZONE);end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
  signature=dict(algorithm=ALGORITHM,start=start.isoformat(),end=end.isoformat(),device_id=self.plan['device_id'],source=source,model=reader.model_signature(),readings=storage.list_meter_readings())
  reader._balance_stats={};files=_files(reader,start,end,source,self.cancelled);expected=revision(reader,files,signature,self.cancelled)
  stem=f'{anchor.year}-{anchor.month:02d}-{source}'
  for previous,old in [(self.job,self.plan),*self.previous]:
   self.check();summary=previous/'balances'/(stem+'.json');audit=previous/'balances'/(stem+'.audit.jsonl.gz')
   if not summary.is_file() or not audit.is_file():continue
   try:value=json.loads(summary.read_text('utf-8'))
   except (OSError,ValueError):continue
   if value.get('revision')!=expected:continue
   proof=summary.with_suffix('.reuse.json')
   checks=None
   if proof.is_file():checks=json.loads(proof.read_text('utf-8'))
   elif (previous/'history.zip').is_file():
    with zipfile.ZipFile(previous/'history.zip') as archive:manifest=json.loads(archive.read('manifest.json'))
    checks={Path(row['name']).name:row['sha256'] for row in manifest['files'] if row['name'].startswith('balances/')}
   if not checks or any(checks.get(p.name)!=digest(p,self.cancelled) for p in (summary,audit)):continue
   destination.mkdir(exist_ok=True)
   if previous!=self.job:
    shutil.copyfile(summary,destination/summary.name);shutil.copyfile(audit,destination/audit.name)
   self.record_month(destination,stem);self.stats['months_reused']+=1;return True
  return False
 def seed_open_month(self,reader,stem):
  from ducksolar.energy_streaming import _audit_valid,_json
  from ducksolar.deferred_audit import part
  target=Path(reader.cfg.root_dir)/'Data/EnergyAudit'/self.plan['device_id'];target.mkdir(parents=True,exist_ok=True)
  current=target/(stem+'.summary.json')
  if current.exists():return False
  current_files=getattr(self,'_seed_files',None)
  if current_files is None:
   current_files={};self._seed_files=current_files
   for day in reader.available_dates(refresh=True):
    for origin,paths in zip(('Local','SmartESS'),reader.find_day_files(day)):
     for path in paths:
      self.check();current_files.setdefault(digest(path,self.cancelled),[]).append(path)
  for previous,old in self.previous:
   source=previous/'work/Data/EnergyAudit'/self.plan['device_id']/(stem+'.summary.json')
   if not source.exists():continue
   try:value=json.loads(source.read_text('utf-8'))
   except (OSError,ValueError):continue
   if not value.get('deferred_audit') or not value.get('checkpoint',{}).get('last_row') or not _audit_valid(value,source):continue
   mapping={};valid=True
   for row in value['checkpoint']['prefixes']:
    oldpath=Path(row['path']);choices=current_files.get(row['digest'],[])
    match=next((p for p in choices if p.name==oldpath.name and p.parent.parent.name==oldpath.parent.parent.name and p.stat().st_size==row['size'] and schema_path(p).is_file() and digest(schema_path(p),self.cancelled)==digest(schema_path(oldpath),self.cancelled)),None)
    if match is None:valid=False;break
    mapping[row['path']]=match
   if not valid:continue
   state=value['checkpoint'];signature=state['signature']
   for row in state['prefixes']:row.update(path=str(mapping[row['path']]),mtime=mapping[row['path']].stat().st_mtime_ns)
   signature['files']=[(str(mapping[p]),o,d,size,mapping[p].stat().st_mtime_ns) for p,o,d,size,mtime in signature['files']]
   signature['schemas']=[(str(mapping[p]),sha) for p,sha in signature.get('schemas',[])]
   signature['schema_contracts']={str(mapping[p]):v for p,v in signature.get('schema_contracts',{}).items()}
   parts=[]
   for item in value['input_parts']:
    self.check();src=Path(item['path']);dst=target/('.inputs-'+uuid4().hex+'.jsonl');shutil.copyfile(src,dst)
    if digest(src,self.cancelled)!=digest(dst,self.cancelled):raise ValueError('Reused checkpoint segment changed')
    parts.append(part(dst,item['start'],item['end']))
   value['input_parts']=parts;value['signature']=hashlib.sha256(_json(signature).encode()).hexdigest();value['created_at']=0
   value['audit_metadata'].update(signature);value['audit_metadata']['source_signature']=value['signature']
   write_json(current,value);self.stats['open_month_seeds_reused']+=1;return True
  return False
 def record_month(self,folder,stem):
  files=[folder/(stem+'.json'),folder/(stem+'.audit.jsonl.gz')]
  write_json(folder/(stem+'.reuse.json'),{p.name:digest(p,self.cancelled) for p in files})
