"""Rewind one clipped support pair without trusting or changing source history."""
import copy,json
from pathlib import Path
from .energy_accounting import stamp

def rewind(old,reader,aborted):
 # Auto with both sources needs a wider merge look-behind. Retain a full rebuild.
 saved=old['checkpoint']
 if not old.get('deferred_audit') or any(row[1]!='Local' for row in saved['signature']['files']):return None
 from .deferred_audit import valid_parts
 from .audit_codec import expand
 parts=old.get('input_parts',[])
 if not valid_parts(parts):return None
 found=[]
 for index in range(len(parts)-1,-1,-1):
  if aborted():raise ValueError('Розрахунок балансу скасовано')
  item=parts[index];start=item['start'];end=item['end']
  with Path(item['path']).open('rb') as stream:
   offset=max(start,end-512*1024);stream.seek(offset)
   if offset>start:stream.readline();offset=stream.tell()
   data=stream.read(end-offset)
  records=[];position=offset
  for line in data.splitlines(keepends=True):
   if not line.endswith(b'\n'):return None
   record=expand(json.loads(line))
   if record.get('type')=='input':records.append((record['row'],index,position))
   position+=len(line)
  found.extend(reversed(records))
  if len(found)>=2:break
 if len(found)<2:return None
 last,part_index,last_offset=found[0];previous=found[1][0]
 if stamp(last['timestamp']).timestamp()!=stamp(saved['last_row']['timestamp']).timestamp():return None
 end=stamp(old['report']['end'])
 if not stamp(previous['timestamp']).timestamp()<=end.timestamp()<stamp(last['timestamp']).timestamp():return None
 # Subtract exactly the clipped pair which will now be replayed for the new end.
 from .energy_streaming import _Summary
 from .cpu_energy import BalanceBatch
 start=stamp(old['report']['start']);buckets={key:_Summary(start,end) for key in ('pv','import','export')}
 batch=BalanceBatch(buckets,start,end,old['report']['max_gap_s'],previous,aborted)
 batch.add(last);batch.flush()
 state=copy.deepcopy(saved)
 for key,bucket in buckets.items():
  for name,value in bucket.state().items():
   restored=state['totals'][key][name]-value
   if restored < -1e-8:return None
   state['totals'][key][name]=max(0,restored)
 state.update(last_row=previous,count=saved['count']-1,merge_last_local=stamp(previous['timestamp']).timestamp(),rewound_support_pair=True)
 selected=copy.deepcopy(parts[:part_index+1]);selected[-1]['end']=last_offset
 if selected[-1]['end']==selected[-1]['start']:selected.pop()
 state['input_parts']=selected
 reader._balance_stats['boundary_pair_replayed']=True
 return state
