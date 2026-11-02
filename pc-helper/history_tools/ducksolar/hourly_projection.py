"""Persistent hourly means from checked typed inputs, with an append checkpoint.

The unfinished hour retains sum/count, not just its previous mean. Native full
resolution energy accounting remains independent of these presentation rows.
"""
import copy,hashlib,json,math,time,sys
from array import array
from pathlib import Path
from datetime import datetime,timedelta
from .energy_accounting import ZONE,stamp
from .energy_streaming import FIELDS,_ordered_rows,_resume_checkpoint,_prefix_hash,_hash_context,_json
from .prepared_history import write_json,digest
from .compact_history import schema_path,schema_contract
from .concurrency import keyed_lock,path_key

SCALAR={'pv_w','output_w','grid_import_w','grid_export_w'}
META=('grid_import_source','grid_import_origin','grid_export_source','grid_export_origin')

def _finish(state):
 current=state['open']
 if current is None:return None
 row=dict(timestamp=current['first'],**current['meta'])
 row.update({k:total/current['counts'][k] for k,total in current['totals'].items()})
 return row

def _add(state,row,gap):
 moment=stamp(row['timestamp']);epoch=moment.timestamp()
 meta={k:row.get(k) for k in META};bucket=int(epoch//3600)
 current=state['open'];previous=state['last_epoch']
 broken=previous is not None and epoch-previous>gap
 if current is None or current['bucket']!=bucket or current['meta']!=meta or broken:
  if current is not None:state['closed'].append(_finish(state))
  if broken:state['closed'].append(dict(timestamp=moment.isoformat(),_gap=True))
  current=dict(first=moment.isoformat(),bucket=bucket,meta=meta,totals={},counts={});state['open']=current
 for key,value in row.items():
  if key.startswith('_') or isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):continue
  if key.endswith('_energy_total_kwh'):current['totals'][key]=value;current['counts'][key]=1
  else:current['totals'][key]=current['totals'].get(key,0)+value;current['counts'][key]=current['counts'].get(key,0)+1
 state['last_epoch']=epoch;state['records']+=1

def _result(state):
 rows=state['closed']+([_finish(state)] if state['open'] is not None else [])
 return [dict(row,timestamp=stamp(row['timestamp'])) for row in rows]

def columns():
 from .graph_projection import FIELDS as PLOT_FIELDS
 return tuple(dict.fromkeys(FIELDS+tuple(PLOT_FIELDS)))

def effective_source(source,local,smart):
 # Auto and the sole available origin describe the same ordered rows.
 if source in ('Auto','Local') and local and not smart:return 'Auto'
 if source in ('Auto','SmartESS') and smart and not local:return 'Auto'
 return source

def _load(path):
 try:
  value=json.loads(path.read_text('utf-8'))
  return value if isinstance(value,dict) and (isinstance(value.get('state'),dict) or isinstance(value.get('sealed'),list)) else None
 except (OSError,ValueError):return None

def _rows(cached):
 return _result(cached['state']) if 'state' in cached else [dict(row,timestamp=stamp(row['timestamp'])) for row in cached['sealed']]

def _normalise_alias(old,signature,aliases):
 if not old:return None
 prior=old.get('checkpoint',{}).get('signature')
 if prior and prior.get('source') in aliases:
  # Only aliases proven to select the same single origin can share a cache.
  if len({x[1] for x in prior.get('files',[])})>1:return old
  if old.get('signature')!=hashlib.sha256(_json(prior).encode()).hexdigest():return None
  old=copy.deepcopy(old);prior=old['checkpoint']['signature']
  prior['source']=signature['source']
  if signature['source']=='Local':prior.pop('history_semantics',None)
  else:prior['history_semantics']='smartess-missing-v2'
  old['signature']=hashlib.sha256(_json(prior).encode()).hexdigest()
 return old

def _legacy(view,anchor,source,aliases,files,cancelled):
 # Completed means are safe to adopt, but cannot reconstruct the unfinished
 # hour's counts. Never promote such a sealed result into today's live state.
 if anchor>=datetime.now(ZONE).date():return None
 from .wire import decode
 from .prepared_history import PreparedHistory
 for origin in aliases:
  key=('hourly-chunk',anchor,origin)
  revision=hashlib.sha256(repr(([(anchor,view._revision(anchor,origin))],'period-v1-no-daily',key)).encode()).hexdigest()
  name='period-'+hashlib.sha256(repr(key).encode()).hexdigest()+'.json'
  local=view.view_path/name;path=local if local.exists() else PreparedHistory(view.reader)._object(name)
  if path is None:continue
  try:cached=decode(json.loads(path.read_text('utf-8')))
  except (OSError,ValueError,KeyError,TypeError):continue
  if not isinstance(cached,dict) or cached.get('revision')!=revision or not isinstance(cached.get('value'),list):continue
  if cancelled():raise ValueError('Cache adoption cancelled')
  for p,_,_,size,mtime in files:
   stat=p.stat()
   if (stat.st_size,stat.st_mtime_ns)!=(size,mtime):raise ValueError('History changed during cache adoption')
  return cached['value']
 return None

def export_portable(view,anchor,source,rows):
 """Keep the established portable period contract for PC packages/readers."""
 from .wire import encode
 key=('hourly-chunk',anchor,source)
 revision=hashlib.sha256(repr(([(anchor,view._revision(anchor,source))],'period-v1-no-daily',key)).encode()).hexdigest()
 target=view.view_path/('period-'+hashlib.sha256(repr(key).encode()).hexdigest()+'.json')
 write_json(target,encode(dict(revision=revision,value=rows)))

def _merge_seed(state,seed):
 if state['records']!=seed['records'] or len(state['closed'])!=len(seed['closed']):raise ValueError('Scalar extension source boundary changed')
 def identity(row):return row['timestamp'],bool(row.get('_gap')),tuple(row.get(k) for k in META)
 for i,(extra,core) in enumerate(zip(state['closed'],seed['closed'])):
  if identity(extra)!=identity(core):raise ValueError('Scalar extension hourly groups changed')
  state['closed'][i]=dict(core,**extra)
 if state['open'] and seed['open']:
  extra,core=state['open'],seed['open']
  if (extra['first'],extra['bucket'],extra['meta'])!=(core['first'],core['bucket'],core['meta']):raise ValueError('Scalar extension open group changed')
  extra['totals']={**core['totals'],**extra['totals']};extra['counts']={**core['counts'],**extra['counts']}

def _batch(state,rows,keys,gap,cancelled):
 from .cpu_energy import backend,_bytes
 from .concurrency import CPU_WORKERS,active_count
 engine=backend();ids={};values=array('d')
 def ident(value):
  if value not in ids:ids[value]=len(ids)+1
  return float(ids[value])
 unsafe=False
 for row in rows:
  if cancelled():raise ValueError('Hourly preparation cancelled')
  values.append(stamp(row['timestamp']).timestamp());values.extend(ident(row.get(k)) for k in META)
  for key in keys:
   value=row.get(key)
   valid=not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)
   if valid and isinstance(value,int) and abs(value)>2**53:unsafe=True
   values.append(float(value) if valid else math.nan)
 if engine is None or unsafe or not keys:
  for row in rows:
   if cancelled():raise ValueError('Hourly preparation cancelled')
   _add(state,{k:v for k,v in row.items() if k in keys or k in META or k=='timestamp'},gap)
  return
 if sys.byteorder!='little':values.byteswap()
 raw=engine.hourly(values.tobytes(),bytes(int(k.endswith('_energy_total_kwh')) for k in keys),float(gap),max(1,CPU_WORKERS//max(1,active_count())))
 data=array('d');data.frombytes(bytes(raw))
 if sys.byteorder!='little':data.byteswap()
 stride=4+len(keys)*2
 if len(data)%stride:raise ValueError('Hourly kernel result version mismatch')
 for offset in range(0,len(data),stride):
  if cancelled():raise ValueError('Hourly preparation cancelled')
  first,last=int(data[offset]),int(data[offset+1]);row=rows[first];moment=stamp(row['timestamp']);meta={k:row.get(k) for k in META}
  current=state['open'];broken=(state['last_epoch'] is not None and moment.timestamp()-state['last_epoch']>gap) or bool(data[offset+2]);bucket=int(data[offset+3])
  if current is None or current['bucket']!=bucket or current['meta']!=meta or broken:
   if current is not None:state['closed'].append(_finish(state))
   if broken:state['closed'].append(dict(timestamp=moment.isoformat(),_gap=True))
   current=dict(first=moment.isoformat(),bucket=bucket,meta=meta,totals={},counts={});state['open']=current
  for i,key in enumerate(keys):
   count=int(data[offset+4+len(keys)+i])
   if not count:continue
   total=data[offset+4+i]
   if key.endswith('_energy_total_kwh'):current['totals'][key]=total;current['counts'][key]=1
   else:current['totals'][key]=current['totals'].get(key,0)+total;current['counts'][key]=current['counts'].get(key,0)+count
  state['last_epoch']=stamp(rows[last]['timestamp']).timestamp();state['records']+=last-first+1

def day(view,anchor,source,fields,cancelled):
 local,smart=view.reader.find_day_files(anchor);requested=source;source=effective_source(source,local,smart)
 base=view.view_path/f'hourly-index-v1-{anchor.isoformat()}-{source}'
 primary=Path(str(base)+'-telemetry.json');scalar=Path(str(base)+'-scalar.json')
 aliases=[source]
 if source=='Auto' and not smart:aliases+=['Local']
 elif source=='Auto' and not local:aliases+=['SmartESS']
 scalar=next((view.view_path/f'hourly-index-v1-{anchor.isoformat()}-{alias}-scalar.json' for alias in aliases if _load(view.view_path/f'hourly-index-v1-{anchor.isoformat()}-{alias}-scalar.json')),scalar)
 # All modes for this day share one lock. A full projection serves every plot.
 if view.logs:view.logs.event('Hourly cache day started',code='history.hourly.started',day=anchor.isoformat(),source=source)
 with keyed_lock(path_key('hourly-unified',base),cancelled):
  complete=next((view.view_path/f'hourly-index-v1-{anchor.isoformat()}-{alias}-telemetry.json' for alias in aliases
    if _load(view.view_path/f'hourly-index-v1-{anchor.isoformat()}-{alias}-telemetry.json')),None)
  if complete is not None:
   rows,stats=_day(view,anchor,source,columns(),complete,cancelled,aliases=aliases)
  elif set(fields)<=SCALAR and _load(scalar):
   rows,stats=_day(view,anchor,source,FIELDS,scalar,cancelled,aliases=aliases)
  else:
   rows,stats=_day(view,anchor,source,columns(),primary,cancelled,seed_path=scalar,aliases=aliases)
  stats.update(source=requested,effective_source=source,mode='unified' if complete is not None or not set(fields)<=SCALAR or not _load(scalar) else 'existing_scalar')
  if view.logs:view.logs.event('Hourly cache day ready',code='history.hourly.day',**stats)
  return rows,stats

def _day(view,anchor,source,columns,target,cancelled,seed_path=None,aliases=None):
 started=time.perf_counter();reader=copy.copy(view.reader);reader._compact_codecs={};reader._projection_columns=columns
 start=datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE);end=start+timedelta(days=1)
 # Use the whole captured daily file, just as graph_day_rows did. UTC endpoints
 # remain authoritative even for an irregular legacy filename or DST hour.
 stats=dict(opened_files=0,read_records=0,used_records=0,files=[],range_start=0.,range_end=7258118400.)
 reader._balance_stats=stats;token=_hash_context.set(({},stats))
 try:
  local,smart=reader.find_day_files(anchor);files=[]
  for origin,paths in (('Local',local),('SmartESS',smart)):
   if source not in ('Auto',origin):continue
   for path in paths:
    stat=path.stat();files.append((path,origin,anchor,stat.st_size,stat.st_mtime_ns))
  schemas=[(str(p),digest(schema_path(p),cancelled)) for p,_,_,_,_ in files if schema_path(p).exists()]
  reader._balance_schemas=dict(schemas)
  signature=dict(algorithm='hourly.index.v1',start=start.isoformat(),device_id=view.device_id,source=source,
   model=reader.model_signature(),readings=[],end=None,columns=columns,
   files=[(str(p),o,d.isoformat(),size,mtime) for p,o,d,size,mtime in files],schemas=schemas,
   schema_contracts={key:schema_contract(json.loads(schema_path(key).read_text('utf-8'))) for key,_ in schemas})
  if source!='Local':signature['history_semantics']='smartess-missing-v2'
  fingerprint=hashlib.sha256(_json(signature).encode()).hexdigest()
  old=_load(target)
  old=_normalise_alias(old,signature,aliases or [source])
  if old and old.get('signature')==fingerprint:
   return _rows(old),dict(day=anchor.isoformat(),cache_hit=True,new_rows=0,total_s=round(time.perf_counter()-started,4))
  legacy=_legacy(view,anchor,source,aliases or [source],files,cancelled)
  if legacy is not None:
   sealed=[dict(row,timestamp=stamp(row['timestamp']).isoformat()) for row in legacy]
   write_json(target,dict(signature=fingerprint,sealed=sealed,origin='verified_legacy_hourly'))
   return _rows(dict(sealed=sealed)),dict(day=anchor.isoformat(),cache_hit=True,adopted_legacy=True,new_rows=0,total_s=round(time.perf_counter()-started,4))
  seed=None
  if not old and seed_path is not None and _load(seed_path):
   _day(view,anchor,source,FIELDS,seed_path,cancelled,aliases=aliases)
   candidate=_normalise_alias(_load(seed_path),dict(signature,columns=FIELDS),aliases or [source])
   expected=hashlib.sha256(_json(dict(signature,columns=FIELDS)).encode()).hexdigest()
   if candidate and isinstance(candidate.get('state'),dict):
    # The writer may append while the scalar checkpoint is brought up to date.
    # Extend its exact committed snapshot instead of discarding already computed
    # core columns merely because that snapshot is a few seconds newer.
    frozen=candidate.get('checkpoint',{}).get('signature')
    if candidate.get('signature')==expected or frozen and _json(frozen.get('model'))==_json(signature['model']):
     seed=candidate['state']
     if frozen:
      signature=dict(frozen,columns=columns);fingerprint=hashlib.sha256(_json(signature).encode()).hexdigest()
      files=[(Path(p),o,datetime.fromisoformat(d).date(),size,mtime) for p,o,d,size,mtime in frozen['files']]
      reader._balance_schemas=dict(frozen.get('schemas',[]))
  resume=_resume_checkpoint(old,files,reader,signature,end,cancelled) if old and 'state' in old else None
  if view.logs:view.logs.event('Hourly cache decision',code='history.hourly.decision',day=anchor.isoformat(),source=source,old_cache_found=old is not None,reused_scalar=seed is not None,incremental=bool(resume),checkpoint_rejected=stats.get('checkpoint_rejected'),cache_file=target.name,source_files=len(files))
  state=copy.deepcopy(old['state']) if resume else dict(closed=[],open=None,last_epoch=None,records=0)
  previous=resume['last_row'] if resume else None
  work=files
  if resume:
   sizes={p['path']:p['size'] for p in resume['prefixes']}
   work=[e for e in files if str(e[0]) not in sizes or e[3]>sizes[str(e[0])]]
  captured={str(p):_prefix_hash(p,size,cancelled) for p,_,_,size,_ in work}
  keys=[k for k in columns if k not in ('timestamp',*META)]
  if seed is not None:keys=[k for k in keys if k not in FIELDS]
  aggregate_s=0.;pending=[]
  with _ordered_rows(reader,work,source,cancelled,stamp(previous['timestamp']).timestamp() if previous else None,
    resume.get('merge_last_local') if resume else None) as rows:
   for row in rows:
    if cancelled():raise ValueError('History query cancelled')
    pending.append(row);previous=row;stats['used_records']+=1
    if len(pending)>=4096:
     phase=time.perf_counter();_batch(state,pending,keys,reader.cfg.max_integration_gap_s,cancelled);aggregate_s+=time.perf_counter()-phase;pending=[]
   if pending:
    phase=time.perf_counter();_batch(state,pending,keys,reader.cfg.max_integration_gap_s,cancelled);aggregate_s+=time.perf_counter()-phase
  if seed is not None:_merge_seed(state,seed)
  prior={p['path']:p for p in resume['prefixes']} if resume else {};prefixes=[]
  for path,origin,d,size,mtime in files:
   saved=prior.get(str(path))
   sha=saved['digest'] if saved and saved['size']==size and saved['mtime']==mtime else _prefix_hash(path,size,cancelled)
   if str(path) in captured and sha!=captured[str(path)]:raise ValueError('Hourly source prefix changed during calculation')
   prefixes.append(dict(path=str(path),size=size,mtime=mtime,digest=sha))
  if cancelled():raise ValueError('History query cancelled')
  if previous is not None:previous=dict(previous,timestamp=stamp(previous['timestamp']).isoformat())
  checkpoint=dict(signature=signature,last_row=previous,count=state['records'],prefixes=prefixes,
   merge_last_local=stats.get('merge_last_local',resume.get('merge_last_local') if resume else None))
  write_json(target,dict(signature=fingerprint,state=state,checkpoint=checkpoint,report=dict(end=end.isoformat())))
  return _result(state),dict(day=anchor.isoformat(),cache_hit=False,incremental=bool(resume),new_rows=stats['used_records'],
   reused_scalar=seed is not None,aggregate_s=round(aggregate_s,4),cache_miss_reason=stats.get('checkpoint_rejected') or ('missing_projection' if old is None else 'source_revision_changed'),
   projection_s=round(stats.get('projection_s',0),4),read_records=stats.get('read_records',0),
   scalar_decode_s=round(stats.get('scalar_decode_s',0),4),canonical_s=round(stats.get('canonical_s',0),4),
   checkpoint_rejected=stats.get('checkpoint_rejected'),total_s=round(time.perf_counter()-started,4))
 finally:_hash_context.reset(token)

def period(view,days,source,fields,cancelled=None,progress=None):
 cancelled=cancelled or (lambda:False);output=[];details=[]
 if progress:progress(0,len(days))
 for index,anchor in enumerate(days):
  if cancelled():raise ValueError('History query cancelled')
  rows,stats=day(view,anchor,source,fields,cancelled)
  if output and rows and rows[0]['timestamp'].timestamp()-output[-1]['timestamp'].timestamp()>view.cfg.max_integration_gap_s:
   output.append(dict(timestamp=rows[0]['timestamp'],_gap=True))
  output.extend(rows);details.append(stats)
  if progress:progress(index+1,len(days))
 view._hourly_projection_diagnostics=details
 return output
