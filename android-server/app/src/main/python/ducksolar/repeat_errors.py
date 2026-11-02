"""Keep the first error and emit bounded repeat totals, including reason changes."""
import json,threading,time
class RepeatErrors:
 def __init__(self):self.lock=threading.Lock();self.pending={}
 def accept(self,channel,code,message,details,stamp):
  if not code or not code.endswith(('.failed','.error')):return [(channel,code,message,details,stamp)]
  identity=json.dumps([message,{k:v for k,v in details.items() if k not in ('duration_ms','duration_s','elapsed_s','timestamp')}],sort_keys=True,default=str)
  key=(channel,code);out=[];now=time.monotonic()
  with self.lock:
   old=self.pending.get(key)
   if old and (old['identity']!=identity or now-old['emitted']>=60):
    if old['count']:out.append((channel,code,old['message'],dict(old['details'],repeat_count=old['count'],first_at=old['first'],last_at=old['last']),stamp))
    self.pending.pop(key,None);old=None
   if old:
    old.update(count=old['count']+1,last=stamp);return out
   self.pending[key]=dict(identity=identity,message=message,details=dict(details),first=stamp,last=stamp,count=0,emitted=now)
   out.append((channel,code,message,details,stamp))
  return out
 def flush(self):
  with self.lock:
   result=[(channel,code,v['message'],dict(v['details'],repeat_count=v['count'],first_at=v['first'],last_at=v['last']),v['last']) for (channel,code),v in self.pending.items() if v['count']]
   self.pending.clear();return result
