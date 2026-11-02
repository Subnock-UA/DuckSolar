"""Proven-equivalent input aliases and lossless physical archive deduplication."""
import json,hashlib,os
from pathlib import Path
from .sync_store import atomic,fingerprint
from .compact_history import schema_path,schema_contract

def semantic(path):
 value=json.loads(Path(path).read_text('utf-8'))
 return schema_contract(value)

def schema_equal(a,b):
 return json.dumps(semantic(a),sort_keys=True,separators=(',',':'))==json.dumps(semantic(b),sort_keys=True,separators=(',',':'))

def equivalent(a,b):
 return a['source']==b['source'] and a['day']==b['day'] and a['csv']['sha256']==b['csv']['sha256'] and schema_equal(schema_path(a['work_path']),schema_path(b['work_path']))

def schema_extends(short,long):
 # Types/defaults and every existing template definition must remain identical.
 a,b=semantic(short),semantic(long)
 exact=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))
 return all(exact(a.get(k))==exact(b.get(k)) for k in ('format','fields','defaults')) and all(b['templates'].get(k)==v for k,v in a['templates'].items())

def extends(short,long,cancelled=lambda:False):
 if short['source']!=long['source'] or short['day']!=long['day'] or short['csv']['bytes']>long['csv']['bytes']:return False
 if not schema_extends(schema_path(short['work_path']),schema_path(long['work_path'])):return False
 size=short['csv']['bytes'];remaining=size;sha=hashlib.sha256()
 # A descriptor, not the first block/timestamp, proves the entire prior prefix.
 with Path(long['work_path']).open('rb') as f:
  while remaining:
   if cancelled():raise InterruptedError('Синхронізацію зупинено')
   block=f.read(min(256*1024,remaining))
   if not block:return False
   sha.update(block);remaining-=len(block)
 return sha.hexdigest()==short['csv']['sha256']

def reconcile(dataset,aliases,work,store,cancelled=lambda:False,persist=lambda:None,conversions=None):
 # Work is exclusively owned by preparation_lock. Prefer the legacy input so
 # existing portable identities remain byte-for-byte stable.
 journal=Path(work)/'Data/sync-reconcile.json'
 if journal.exists():
  pending=json.loads(journal.read_text('utf-8')).get('mapping',{})
  retained={v['work_path'] for v in dataset.values()}
  for old,new in pending.items():
   old,new=Path(old),Path(new)
   if str(old) in retained or not old.exists():continue
   if not new.is_file():raise ValueError('Incomplete duplicate reconciliation')
   a=store.snapshot(old,immutable=True);b=store.snapshot(new,immutable=True)
   short=dict(source='Local',day='recovery',csv=a,work_path=str(old));long=dict(source='Local',day='recovery',csv=b,work_path=str(new))
   if not extends(short,long,cancelled):raise ValueError('Duplicate changed during recovery')
   store.snapshot(schema_path(old),immutable=True);store.save();old.unlink();schema_path(old).unlink(missing_ok=True)
 groups={};replace={};removed=[];promoted=0
 for key,row in sorted(list(dataset.items()),key=lambda x:('/sync-' in x[1]['member'],x[1]['csv']['bytes'],x[1]['member'])):
  if cancelled():raise InterruptedError('Синхронізацію зупинено')
  token=(row['source'],row['day']);targets=groups.setdefault(token,[]);target=None
  for candidate in targets:
   prior=dataset[candidate]
   if extends(row,prior,cancelled):target=candidate;break
   if extends(prior,row,cancelled):
    target=candidate
    # Keep the established work path/identity. The old bytes are already in CAS.
    for path in [Path(prior['work_path']),schema_path(prior['work_path'])]:store.snapshot(path,immutable=True)
    store.materialize(row['csv'],Path(prior['work_path']))
    store.materialize(row['schema'],schema_path(prior['work_path']))
    prior.update(csv=row['csv'],schema=row['schema']);promoted+=1;replace[prior['work_path']]=prior
    break
  if target is None:targets.append(key);continue
  replace[row['work_path']]=dataset[target];removed.append((key,target,row))
 if not removed:return dict(merged=0,removed_bytes=0,prefixes_promoted=0)
 # Transaction journal makes recovery idempotent if a file rename is interrupted.
 journal=Path(work)/'Data/sync-reconcile.json';atomic(journal,dict(mapping={k:v['work_path'] for k,v in replace.items()}))
 for folder,pattern in [(Path(work)/'Data/EnergyAudit','**/*.summary.json'),(Path(work)/'Data/HistoryViews','**/*.json')]:
  for path in folder.glob(pattern):
   if cancelled():raise InterruptedError('Синхронізацію зупинено')
   value=json.loads(path.read_text('utf-8'));checkpoint=value.get('checkpoint',{});sig=checkpoint.get('signature',{})
   if not any(row[0] in replace for row in sig.get('files',[])):continue
   selected={}
   for old,origin,day,size,mtime in sig['files']:
    target=replace.get(old);new=target['work_path'] if target else old
    # A checkpoint that only saw the short file must keep its old prefix size;
    # promoting it to the current full size would silently lose the appended tail.
    if new not in selected or size>selected[new][1][3]:selected[new]=(old,[new,origin,day,size,mtime])
   prefixes={}
   for prefix in checkpoint.get('prefixes',[]):
    target=replace.get(prefix['path']);new=target['work_path'] if target else prefix['path'];prefix=dict(prefix,path=new)
    if target and prefix['size']==target['csv']['bytes'] and prefix['digest']==target['csv']['sha256']:prefix['mtime']=Path(new).stat().st_mtime_ns
    if new not in prefixes or prefix['size']>prefixes[new]['size']:prefixes[new]=prefix
   sig['files']=[row for old,row in selected.values()]
   for row in sig['files']:
    saved=prefixes.get(row[0])
    if saved and saved['size']==row[3]:row[4]=saved['mtime']
   schemas=dict(sig.get('schemas',[]));contracts=sig.get('schema_contracts',{})
   sig['schemas']=[(new,replace[old]['schema']['sha256'] if old in replace else schemas[old]) for new,(old,row) in selected.items() if old in schemas]
   sig['schema_contracts']={new:semantic(schema_path(new)) if old in replace else contracts[old] for new,(old,row) in selected.items() if old in contracts}
   checkpoint['prefixes']=list(prefixes.values())
   from .energy_streaming import _json
   value['signature']=hashlib.sha256(_json(sig).encode()).hexdigest()
   if value.get('audit_metadata'):
    value['audit_metadata'].update(sig);value['audit_metadata']['source_signature']=value['signature']
   atomic(path,value)
 total=0
 for key,target,row in removed:
  for references in [aliases,conversions or {}]:
   for alias,prior in list(references.items()):
    if prior==key:references[alias]=target
  for path in [Path(row['work_path']),schema_path(row['work_path'])]:
   if path.exists():store.snapshot(path,immutable=True)
  dataset.pop(key,None)
 store.save();persist()
 for key,target,row in removed:
  for path in [Path(row['work_path']),schema_path(row['work_path'])]:
   if path.exists():total+=path.stat().st_size;path.unlink()
 journal.unlink(missing_ok=True)
 return dict(merged=len(removed),removed_bytes=total,prefixes_promoted=promoted)

def deduplicate_files(paths,report_path,cancelled=lambda:False,preserve_mtime=True,proofs=None):
 # Physical exact duplicates only. Hardlinks preserve every archive receipt/path;
 # never link mutable SQLite or live CSV. Every candidate is fully hash checked.
 groups={};result=dict(examined=0,linked=0,freed_bytes=0,errors=0);proofs=proofs if proofs is not None else {}
 for path in paths:
  if cancelled():raise InterruptedError('Очищення скасовано')
  path=Path(path)
  try:
   if path.is_symlink() or not path.is_file():continue
   fp=fingerprint(path)
   proof=proofs.get(str(path),{})
   if proof.get('fingerprint')==fp:sha=proof['sha256']
   else:
    with path.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
   proofs[str(path)]=dict(fingerprint=fp,sha256=sha)
   if fingerprint(path)!=fp:continue
   result['examined']+=1;key=(fp[0],sha);prior=groups.get(key)
   if prior is None:groups[key]=path;continue
   if os.path.samefile(prior,path):continue
   # Preserve public fingerprints: mtime participates in existing readers.
   # Link only equal timestamps; otherwise archive paths stay stable and are
   # reported for canonicalization instead of silently invalidating caches.
   if preserve_mtime and prior.stat().st_mtime_ns!=fp[1]:
    result['different_mtime']=result.get('different_mtime',0)+1;continue
   tmp=path.with_name(path.name+'.dedup-link')
   try:
    os.link(prior,tmp)
    if fingerprint(path)!=fp:continue
    st=path.stat();last_link=st.st_nlink==1
    os.replace(tmp,path);result['linked']+=1
    proofs[str(path)]=dict(fingerprint=fingerprint(path),sha256=sha)
    if last_link:result['freed_bytes']+=getattr(st,'st_blocks',0)*512 if hasattr(st,'st_blocks') else st.st_size
   finally:tmp.unlink(missing_ok=True)
  except OSError:result['errors']+=1
 atomic(report_path,result);return result


def deduplicate_archives(root,store,cancelled=lambda:False,pn=None):
 root=Path(root);paths=[]
 # Only durable, completed originals plus content-named immutable objects.
 # Exclude work folders, live backup append files and in-flight receive files.
 for result in (root/'Data/AndroidSupport/Migrations').glob('*/result.json'):
  try:ready=json.loads(result.read_text('utf-8')).get('state')=='ready'
  except (OSError,ValueError):continue
  if ready and pn is not None:
   try:ready=json.loads(result.with_name('plan.json').read_text('utf-8')).get('pn')==pn
   except (OSError,ValueError):ready=False
  if ready:
   paths.extend(p for p in (result.parent/'originals').rglob('*') if p.is_file())
   paths.extend(result.parent.glob('*.zip'))
 for scope in [store.root.parent]:
  paths.extend(p for p in (scope/'inputs').glob('*') if len(p.stem)==64)
  paths.extend(p for p in (scope/'store/files').glob('*') if len(p.name)==64)
 paths.sort(key=lambda p:('store/files' not in p.as_posix(),p.as_posix()))
 proof_path=store.root.parent/'archive-dedup-index.json'
 try:proofs=json.loads(proof_path.read_text('utf-8'))
 except (OSError,ValueError):proofs={}
 result=deduplicate_files(paths,store.root.parent/'archive-dedup-report.json',cancelled,preserve_mtime=False,proofs=proofs)
 atomic(proof_path,proofs)
 # Refresh references after inode changes; content identity stays unchanged.
 if result['linked']:
  for p in paths:
   if p.is_file() and store.index['sources'].get(str(p.resolve()),{}).get('fingerprint')!=fingerprint(p):store.snapshot(p,immutable=True,cancelled=cancelled)
  store.save()
 return result
