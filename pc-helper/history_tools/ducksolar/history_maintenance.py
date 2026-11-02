"""Charging-only preparation; checkpoints are committed at safe boundaries."""
import threading
import time
import json
from datetime import date
from pathlib import Path
from .prepared_history import PreparedHistory,write_json
from .history_reader import HistoryReader
from .history_views import HistoryViews
from .energy_streaming import MonthAccounting

class HistoryMaintenance:
    def __init__(self,runtime):
        self.runtime=runtime;self.charging=threading.Event();self.stop_event=threading.Event()
        self.lock=threading.Lock();self.state=dict(state='waiting_for_charging',completed=0,total=0)
        self.path=Path(runtime.cfg.root_dir)/'Data/PreparedHistory/background.json'
        self.revision_path=self.path.with_name('background-revisions.json')
        try:self.revisions=json.loads(self.revision_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.revisions={}
        self.thread=threading.Thread(target=self._run,name='HistoryPreparation',daemon=True)
        from .graph_cache_job import GraphCacheJob
        self.graph_cache=GraphCacheJob(runtime,self.charging.is_set)
        self.last_tariff=0;self.last_current={};self.thread.start()
    def power(self,charging):
        if charging:self.charging.set()
        else:
            self.charging.clear()
            if hasattr(self.runtime,'forecast'):self.runtime.forecast.power_lost()
    def status(self):
        with self.lock:return dict(self.state,charging=self.charging.is_set())
    def _busy(self):
        with self.runtime.api.jobs.lock:
            return any(j['state'] not in ('completed','error','cancelled') for j in self.runtime.api.jobs.jobs.values())
    def _cancelled(self):return self.stop_event.is_set() or not self.charging.is_set() or self._busy() or self.graph_cache.manual_active()
    def _state(self,**values):
        with self.lock:self.state.update(values,updated_at=time.time());write_json(self.path,self.state)
    def _current(self,dev,reader):
        # One durable month checkpoint, updated at most once per five minutes.
        # No separate daily balance reports, no full-archive preparation.
        last=self.last_current.get(dev.definition.id)
        if self._cancelled() or (last is not None and time.monotonic()-last<300):return
        from .resource_manager import operation
        anchor=date.today().replace(day=1)
        for index,source in enumerate(('Auto','Local','SmartESS')):
            if self._cancelled():raise ValueError('Current month preparation paused')
            self._state(state='preparing',stage='current_month',period=anchor.isoformat(),source=source,completed=index,total=3)
            with operation(None,{},'history.current_month',logs=self.runtime.logs):
                report=MonthAccounting(self.stop_event).report(reader,self.runtime.storage,dev.cfg,anchor,source=source,device_id=dev.definition.id,cancelled=self._cancelled)
            d=report['diagnostics'];self.runtime.logs.event('Current month checkpoint updated',code='history.background.checkpoint',source=source,period=anchor.isoformat(),input_count=report['input_count'],new_rows=d.get('used_records',0),cached=report['cache_hit'],incremental=report.get('incremental',False),elapsed_s=d['total_s'])
            if self._cancelled():raise ValueError('Current month preparation paused')
            from .month_graph import month
            graph_started=time.monotonic()
            graph,measurements=month(HistoryViews(reader,dev.cfg,dev.definition.id),anchor,source,True,self._cancelled)
            self.runtime.logs.event('Current graph month checkpoint updated',code='history.background.graph_checkpoint',
                                    source=source,period=anchor.isoformat(),input_count=graph['records'],
                                    elapsed_s=round(time.monotonic()-graph_started,4),**measurements)
        self.last_current[dev.definition.id]=time.monotonic()
        self._state(state='ready',completed=3,total=3,stage='current_month')
    def _prepare(self):
        from .resource_manager import operation
        for dev in self.runtime.devices.values():
            reader=HistoryReader(dev.cfg);store=PreparedHistory(reader)
            all_days=[d for d in reader.available_dates(refresh=True) if d<date.today()]
            revision={}
            for day in all_days:
                files=[p for group in reader.find_day_files(day) for p in group]
                # One-time charging preparation of the new month contributions.
                # Existing prepared objects are reused, never migrated again.
                revision[day.isoformat()]=[reader._files_signature(files),reader.model_signature(),'graph.month.v3']
            # JSON normalisation makes stored lists comparable to in-memory tuples.
            revision=json.loads(json.dumps(revision))
            saved=self.revisions.get(dev.definition.id,{})
            changed={key for key in set(saved)|set(revision) if saved.get(key)!=revision.get(key)}
            days=[d for d in all_days if d.isoformat() in changed]
            if not changed:
                self._state(state='ready',completed=0,total=0,reason='no_changed_completed_days')
                self._current(dev,reader)
                self.graph_cache.request(manual=False)
                continue
            self._state(state='preparing',device_id=dev.definition.id,total=len(days),completed=0)
            with operation(None,{},'history.background',logs=self.runtime.logs):
                for index,day in enumerate(days):
                    if self._cancelled():raise ValueError('History preparation paused')
                    for origin,paths in zip(('Local','SmartESS'),reader.find_day_files(day)):
                        for path in paths:store.prepare(path,origin,day,self._cancelled)
                    self._state(completed=index+1,last_day=day.isoformat(),stage='numeric_projection')
                # Monthly/yearly caches; no separate daily calculations.
                view=HistoryViews(reader,dev.cfg,dev.definition.id,self.runtime.logs)
                for source in ('Local','SmartESS','Auto'):
                    months=sorted({(date.fromisoformat(d).year,date.fromisoformat(d).month) for d in changed})
                    for year,month in months:
                        if self._cancelled():raise ValueError('History preparation paused')
                        self.graph_cache.request(manual=False)
                        if (year,month)<(date.today().year,date.today().month):
                            MonthAccounting(self.stop_event).report(reader,self.runtime.storage,dev.cfg,date(year,month,1),
                                source=source,device_id=dev.definition.id,cancelled=self._cancelled)
                        self._state(stage='monthly',period=f'{year}-{month:02d}',source=source)
                    for year in sorted({date.fromisoformat(d).year for d in changed}):
                        if self._cancelled():raise ValueError('History preparation paused')
                        view.graph_data('year',date(year,1,1),source,cancelled=self._cancelled)
                        self._state(stage='yearly',period=str(year),source=source)
                view.daily_memory.clear();view.graph_memory.clear();view.period_memory.clear()
                self.revisions[dev.definition.id]=revision
                write_json(self.revision_path,self.revisions)
            self._current(dev,reader)
    def _run(self):
        while not self.stop_event.wait(5):
            if self._cancelled():continue
            try:
                from .concurrency import heavy_slot
                with heavy_slot('history.background',self._cancelled,priority=1):
                    self._prepare();self._state(state='ready')
                if self.charging.is_set() and time.time()-self.last_tariff>86400:
                    self.last_tariff=time.time()
                    try:self.runtime.tariffs.check_for_updates()
                    except Exception as error:self.runtime.logs.event('Scheduled tariff check failed',code='tariffs.background.failed',exception_class=type(error).__name__)
            except Exception as error:
                self._state(state='paused' if self._cancelled() else 'error',exception_class=type(error).__name__)
            self.stop_event.wait(55)
    def stop(self):
        self.stop_event.set();self.charging.clear();self.graph_cache.stop()
        if self.thread is not threading.current_thread():self.thread.join(timeout=3)
