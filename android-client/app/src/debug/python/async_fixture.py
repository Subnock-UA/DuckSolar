"""Instrumentation adapter for the asynchronous client contract."""
import threading,uuid
def wrap(api):
 old=api.call;jobs={}
 def call(domain,method,*args,**kwargs):
  if method=='job_start':
   spec=args[0];query=spec['kwargs']['query_id']
   for job in jobs.values():
    if job['query']==query:return {'job_id':job['id'],'state':job['state']}
   ident=uuid.uuid4().hex;job=dict(id=ident,query=query,state='running');jobs[ident]=job
   def work():
    try:job['result']=old(spec['domain'],spec['method'],*spec.get('args',[]),**spec.get('kwargs',{}));job['state']='completed'
    except Exception as exc:job.update(state='cancelled',error=str(exc))
   threading.Thread(target=work,daemon=True).start();return {'job_id':ident,'state':'running'}
  if method=='job_status':
   job=jobs[args[0]];return dict(job_id=job['id'],state=job['state'],done=1,total=1,error=job.get('error',''))
  if method=='job_result':return {'result':jobs[args[0]]['result']}
  if method=='job_cancel':api.cancelled.set();jobs[args[0]]['state']='cancelled';return {'state':'cancelled'}
  return old(domain,method,*args,**kwargs)
 api.call=call
