"""Validated PC inverter totals, independently refreshed household meter data."""
import copy,hashlib,json,gzip,os,shutil
from pathlib import Path
from uuid import uuid4
from .prepared_history import PreparedHistory,write_json,digest
from .wire import encode,decode


def _json(value):return json.dumps(encode(value),sort_keys=True,separators=(',',':'),ensure_ascii=False)

def _revision_data(reader,files,signature,cancelled):
 store=PreparedHistory(reader)
 values=[(origin,day.isoformat(),store.identity(path,origin,day,cancelled)[0]) for path,origin,day,size,mtime in files]
 data={k:signature[k] for k in ('algorithm','start','device_id','source','model','readings','end')}
 data['files']=values
 return data

def _revision_hash(data):
 # Preserve the exact historical encoder for existing PC packages.
 return hashlib.sha256(json.dumps(encode(data),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def revision(reader,files,signature,cancelled):return _revision_hash(_revision_data(reader,files,signature,cancelled))

def load(reader,files,signature,target,stem,cancelled):
 from .history_migration import active_folder
 from .energy_accounting import stamp,meter_segments
 stats=getattr(reader,"_balance_stats",{})
 def miss(reason,**details):
  stats.update(portable_cache_miss=reason,**details);return None
 folder=active_folder(reader.cfg.root_dir,signature['device_id'])
 if folder is None:return miss('no_active_package')
 path=folder.parent/'balances'/(stem+'.json');audit=path.with_name(stem+'.audit.jsonl.gz')
 if not path.is_file():return miss('summary_missing')
 try:
  manifest_path=folder.parent/'manifest.json'
  if not manifest_path.is_file():return miss('manifest_missing')
  manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
  if manifest.get('device_id')!=signature['device_id']:return miss('device_changed')
  from .preparation_model import decode_model
  model=decode_model(manifest['model'],manifest['model_types'])
  current=dict(signature['model'])
  changed=[k for k in set(model)|set(current) if _json(model.get(k))!=_json(current.get(k))]
  if changed:return miss('model_changed',portable_model_changed_fields=sorted(changed))
  members={row['name']:row for row in manifest['files']}
  for member in (path,audit):
   name=member.relative_to(folder.parent).as_posix();entry=members.get(name)
   if not entry or not member.is_file():return miss('package_member_missing')
   if member.stat().st_size!=entry['bytes'] or digest(member,cancelled)!=entry['sha256']:return miss('package_member_checksum')
  value=json.loads(path.read_text(encoding='utf-8'));original=value['report']
  for key,report_key in [('algorithm','algorithm'),('start','start'),('end','end'),('device_id','device_id'),('source','history_source')]:
   if original.get(report_key)!=signature.get(key):return miss('changed_'+key)
  data=_revision_data(reader,files,signature,cancelled)
  same=_revision_hash(data)==value['revision']
  if not same:
   # Validate the ORIGINAL signed dependencies using current inverter files/model,
   # and only substitute the old household readings stored by the PC package.
   old_readings=decode(json.loads(manifest['readings_json']))
   if not isinstance(old_readings,list):return miss('invalid_original_readings')
   old_data=dict(data,readings=old_readings)
   if _revision_hash(old_data)!=value['revision']:return miss('inverter_revision_changed')
  report=copy.deepcopy(original)
  report.update(cache_hit=True,portable_cache_hit=True,incremental=False)
  report['house_meter']=meter_segments(signature['readings'],stamp(signature['start']),stamp(signature['end']))
  inverter_data={k:v for k,v in data.items() if k!='readings'}
  inverter_revision=_revision_hash(inverter_data);meter_revision=_revision_hash(signature['readings'])
  summary=dict(report=report,portable_audit=str(audit),audit_bytes=value['audit_bytes'],
               portable_original_bytes=value['audit_bytes'],portable_original_audit_id=original['audit_id'],
               portable_audit_sha256=members[audit.relative_to(folder.parent).as_posix()]['sha256'],
               inverter_revision=inverter_revision,meter_revision=meter_revision)
  if not same:
   report['audit_id']=_revision_hash(['portable-meter-rebased-v1',original['audit_id'],inverter_revision,meter_revision])
   report.update(audit_deferred=True,meter_recalculated=True)
   summary.update(portable_rebased=True,meter_readings=signature['readings'])
  cache=target/(stem+'.summary.json')
  try:
   saved=json.loads(cache.read_text(encoding='utf-8'))
   if saved['report']['audit_id']==report['audit_id'] and saved.get('portable_audit_sha256')==summary['portable_audit_sha256']:
    for key in ('materialized_audit_id','audit_bytes','audit_mtime_ns'):
     if key in saved:summary[key]=saved[key]
  except (OSError,ValueError,KeyError,TypeError):pass
  if cancelled():raise ValueError('History preparation cancelled')
  write_json(cache,summary)
  stats.update(portable_cache_reason='meter_rebased' if not same else 'exact_revision',
               inverter_totals_reused=True,meter_recalculated=not same,cache_reason='portable_inverter_totals')
  return report
 except (OSError,KeyError,TypeError,ValueError,AttributeError) as error:
  if cancelled():raise
  return miss('invalid_package_metadata',portable_error_type=type(error).__name__)


def expand_audit(summary,destination,cancelled=lambda:False):
 source=Path(summary['portable_audit']);rebased=summary.get('portable_rebased',False)
 if (rebased and summary.get('materialized_audit_id')==summary['report']['audit_id'] and destination.exists()
     and destination.stat().st_size==summary.get('audit_bytes') and destination.stat().st_mtime_ns==summary.get('audit_mtime_ns')):return
 original_bytes=summary.get('portable_original_bytes',summary['audit_bytes'])
 if shutil.disk_usage(destination.parent).free<original_bytes+16*1024*1024:raise ValueError('Insufficient audit storage')
 temp=destination.with_name('.audit-'+uuid4().hex+'.tmp')
 try:
  hasher=hashlib.sha256();count=0;metadata_seen=False;summary_seen=False
  with gzip.open(source,'rb') as inp,temp.open('wb') as out:
   if not rebased:
    while block:=inp.read(1024*1024):
     if cancelled():raise ValueError('Audit preparation cancelled')
     count+=len(block)
     if count>original_bytes:raise ValueError('Portable audit size mismatch')
     hasher.update(block);out.write(block)
   else:
    from .audit_codec import expand
    def write(obj):out.write((_json(obj)+'\n').encode('utf-8'))
    while line:=inp.readline(256*1024+1):
     if cancelled():raise ValueError('Audit preparation cancelled')
     if len(line)>256*1024 or not line.endswith(b'\n'):raise ValueError('Invalid portable audit record')
     count+=len(line);hasher.update(line)
     if count>original_bytes:raise ValueError('Portable audit size mismatch')
     obj=expand(json.loads(line));kind=obj.get('type')
     if kind=='metadata':
      if metadata_seen:raise ValueError('Duplicate audit metadata')
      metadata_seen=True;write(dict(obj,source_signature=summary['inverter_revision'],meter_revision=summary['meter_revision']))
      for row in summary['meter_readings']:write(dict(type='meter_reading',row=row))
     elif kind=='meter_reading':continue
     elif kind=='summary':summary_seen=True;write(dict(type='summary',report=summary['report']))
     else:out.write(line) # Exact original inverter inputs/intervals; no reintegration.
    if not metadata_seen or not summary_seen:raise ValueError('Incomplete portable audit')
   out.flush();os.fsync(out.fileno())
  expected=summary.get('portable_original_audit_id',summary['report']['audit_id'])
  compressed_expected=summary.get('portable_audit_sha256')
  if count!=original_bytes or (compressed_expected and digest(source,cancelled)!=compressed_expected) or (not compressed_expected and hasher.hexdigest()!=expected):raise ValueError('Portable audit checksum mismatch')
  if cancelled():raise ValueError('Audit preparation cancelled')
  os.replace(temp,destination)
  if rebased:
   stat=destination.stat();summary.update(materialized_audit_id=summary['report']['audit_id'],audit_bytes=stat.st_size,audit_mtime_ns=stat.st_mtime_ns)
   write_json(destination.with_name(destination.name.replace('.audit.jsonl','.summary.json')),summary)
 finally:temp.unlink(missing_ok=True)
