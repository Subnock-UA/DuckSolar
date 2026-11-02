"""Short polling API and disk-backed results; workers never own the API thread."""
import concurrent.futures
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4
from .wire import encode, decode

TERMINAL = {'completed', 'cancelled', 'error'}

class HistoryJobs:
    def __init__(self, root, logs, lease_seconds=180):
        self.root = Path(root)/'Data/HistoryJobs'
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs, self.lease_seconds = logs, lease_seconds
        self.lock = threading.RLock()
        self.jobs = {}
        from .concurrency import CPU_WORKERS
        self.executor=concurrent.futures.ThreadPoolExecutor(max_workers=CPU_WORKERS,thread_name_prefix='HistoryWorker')
        self.executors={kind:self.executor for kind in ('graph','balance')}
        self.stopping = threading.Event()
        # Restart cannot leave a job apparently running. No closures are replayed.
        for path in self.root.glob('*.state.json'):
            try:
                job = json.loads(path.read_text(encoding='utf-8'))
                if job['state'] not in TERMINAL:
                    job.update(state='cancelled', error_code='history.server_restarted', finished_at=time.time())
                    self._write(path, job)
                self.jobs[job['job_id']] = dict(job, flag=threading.Event(), touched=time.monotonic())
            except (OSError, ValueError, KeyError): continue
        self.reaper = threading.Thread(target=self._reap, name='HistoryJobLease', daemon=True)
        self.reaper.start()

    @staticmethod
    def _write(path, value):
        tmp = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
        try:
            with tmp.open('w', encoding='utf-8') as f:
                json.dump(encode(value), f, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, path)
        finally: tmp.unlink(missing_ok=True)

    def _public(self, job):
        return {k:v for k,v in job.items() if k not in ('flag','future','touched','owner','key')}

    def _save(self, job):
        self._write(self.root/(job['job_id']+'.state.json'), dict(self._public(job), owner=job['owner'], key=job['key']))

    def _event(self, job):
        fields=self._public(job)
        request=fields.get('request',{})
        if request.get('method')=='generation_sync':
            fields['request']=dict(request,args=[dict(known_revisions=len(request.get('args',[{}])[0]))])
        self.logs.event('History job '+job['state'], code='history.job.'+job['state'], **fields)

    def start(self, owner, device, kind, spec, producer, query_id=''):
        if kind not in self.executors: raise ValueError('Invalid history job type')
        key = hashlib.sha256(json.dumps(encode([device,kind,spec]), sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.stopping.is_set(): raise ValueError('Server is stopping')
            # Query id makes POST retry idempotent; it must not reuse another request.
            if query_id:
                for job in self.jobs.values():
                    if job['owner']==owner and job.get('query_id')==query_id:
                        if job['key']!=key: raise ValueError('Query ID belongs to another request')
                        if job['state']!='cancelled':
                            job['touched']=time.monotonic(); return self._public(job)
            ident=uuid4().hex
            job=dict(job_id=ident,owner=owner,device_id=device,kind=kind,key=key,query_id=query_id,
                     request=encode(spec),state='queued',created_at=time.time(),done=0,total=0,
                     flag=threading.Event(),touched=time.monotonic())
            self.jobs[ident]=job; self._save(job); self._event(job)
            job['future']=self.executors[kind].submit(self._run, job, producer)
            return self._public(job)

    def _run(self,job,producer):
        from .concurrency import heavy_slot,snapshot
        def cancelled():return self.stopping.is_set() or job['flag'].is_set()
        try:
            with self.lock:job['stage']='waiting_resources'
            with heavy_slot('history.'+job['kind'],cancelled):
                with self.lock:job['parallel']=snapshot();job['worker_thread']=threading.current_thread().name
                return self._execute(job,producer)
        except Exception as error:
            with self.lock:
                if job['state'] in TERMINAL:return
                job.update(state='cancelled' if cancelled() else 'error',error_code='history.cancelled' if cancelled() else 'history.worker_failed',error=str(error),finished_at=time.time())
                self._save(job);self._event(job)

    def _execute(self, job, producer):
        with self.lock:
            if job['flag'].is_set(): return
            job.update(state='running',stage='running',started_at=time.time(),queue_s=round(time.time()-job['created_at'],3))
            self._save(job); self._event(job)
        start=time.monotonic()
        def cancelled():
            return self.stopping.is_set() or job['flag'].is_set()
        def progress(done,total):
            with self.lock:
                job.update(done=done,total=total)
                if job['kind']=='graph' and job['request'].get('args',[None])[0]=='report' and total==3:job['stage']=('summary','statistics','events','complete')[min(3,done)]
                if job['kind']=='balance' and total==3:job['stage']=('discovery','projection','integration','complete')[min(3,done)]
        try:
            result=producer(cancelled,progress)
            from .cpu_energy import status as cpu_status
            self.logs.event('CPU kernel process lifetime counters',code='history.job.cpu',job_id=job['job_id'],kind=job['kind'],since_process_start=True,cpu=cpu_status())
            diagnostics=result.get('diagnostics',{}) if isinstance(result,dict) else {}
            if diagnostics:
                self.logs.event('History calculation measurements',code='history.job.measurements',job_id=job['job_id'],kind=job['kind'],input_count=result.get('input_count'),cache_hit=result.get('cache_hit'),portable_cache_hit=result.get('portable_cache_hit'),incremental=result.get('incremental'),measurements={k:v for k,v in diagnostics.items() if k not in ('files','archive_discovery')})
            with self.lock:
                if cancelled(): raise ValueError('History job cancelled')
                self._write(self.root/(job['job_id']+'.result.json'), result)
                job.update(state='completed',finished_at=time.time(),calculation_s=round(time.monotonic()-start,3))
        except Exception as error:
            diagnostics=getattr(error,'history_diagnostics',None)
            if diagnostics:
                self.logs.event('Interrupted history calculation measurements',code='history.job.measurements',job_id=job['job_id'],kind=job['kind'],interrupted=True,measurements={k:v for k,v in diagnostics.items() if k not in ('files','archive_discovery')})
            with self.lock:
                if cancelled():
                    job.update(state='cancelled',error_code=job.get('error_code','history.cancelled'))
                else:
                    job.update(state='error',error_code='history.calculation_failed',error=str(error),exception_class=type(error).__name__)
                job.update(finished_at=time.time(),calculation_s=round(time.monotonic()-start,3))
        finally:
            with self.lock: self._save(job); self._event(job)

    def _owned(self, owner, ident, device=None):
        job=self.jobs.get(ident)
        if not job or job['owner']!=owner or (device and job['device_id']!=device):
            raise ValueError('History job unavailable')
        return job

    def status(self, owner, ident, device=None):
        with self.lock:
            job=self._owned(owner,ident,device);job['touched']=time.monotonic()
            return self._public(job)

    def result(self, owner, ident, device=None):
        with self.lock:
            job=self._owned(owner,ident,device)
            job['touched']=time.monotonic()
            if job['state']!='completed': return dict(job=self._public(job),ready=False)
            path=self.root/(ident+'.result.json')
        return dict(job=self.status(owner,ident,device),ready=True,result=decode(json.loads(path.read_text(encoding='utf-8'))))

    def cancel(self, owner, ident, device=None, reason='history.cancelled'):
        with self.lock:
            job=self._owned(owner,ident,device)
            if job['state'] not in TERMINAL:
                job['flag'].set(); job['error_code']=reason
                if job['state']=='queued':
                    if job.get('future'): job['future'].cancel()
                    job.update(state='cancelled',finished_at=time.time())
                    self._save(job);self._event(job)
            return self._public(job)

    def cancel_query(self, owner, query):
        with self.lock:
            for job in self.jobs.values():
                if job['owner']==owner and job.get('query_id')==query:
                    self.cancel(owner,job['job_id']); return True
        return False

    def query_status(self, owner, query):
        with self.lock:
            for job in reversed(list(self.jobs.values())):
                if job['owner']==owner and job.get('query_id')==query:
                    return self.status(owner,job['job_id'])
        return {}

    def wait_legacy(self, owner, ident, timeout, disconnected=None):
        deadline=time.monotonic()+timeout
        while True:
            job=self.status(owner,ident)
            if job['state']=='completed': return self.result(owner,ident)['result']
            if job['state'] in TERMINAL: raise ValueError(job.get('error',job.get('error_code','History cancelled')))
            if time.monotonic()>=deadline or (disconnected and disconnected()):
                self.cancel(owner,ident,reason='history.legacy_transport_ended')
                raise ValueError('Тривалий запит скасовано. Для довгих періодів потрібен API history.job_start/status/result.')
            self.stopping.wait(.15)

    def _reap(self):
        while not self.stopping.wait(10):
            self._reap_once()

    def _reap_once(self):
        with self.lock:
            for ident,job in list(self.jobs.items()):
                if job['state'] not in TERMINAL and time.monotonic()-job['touched']>self.lease_seconds:
                    self.cancel(job['owner'],ident,reason='history.abandoned')
                elif job['state'] in TERMINAL and time.time()-job.get('finished_at',job['created_at'])>86400:
                    for suffix in ('.state.json','.result.json'): (self.root/(ident+suffix)).unlink(missing_ok=True)
                    del self.jobs[ident]

    def stop(self):
        self.stopping.set()
        with self.lock:
            for job in self.jobs.values():
                if job['state'] not in TERMINAL: self.cancel(job['owner'],job['job_id'],reason='history.server_stopping')
        self.executor.shutdown(wait=False,cancel_futures=True)
