"""Compact, cached historical views; no weather requests or forecast models."""
import calendar
import copy
import hashlib
import json
import math
from dataclasses import asdict
from datetime import date, timedelta
from .config import app_paths
from .analytics import daily_energy
from .wire import encode, decode
from collections import OrderedDict, defaultdict
import time
from .balance import summarize_day


class HistoryViews:
    def __init__(self, reader, cfg, device_id, logs=None):
        self.reader, self.cfg, self.device_id = reader, cfg, device_id
        self.logs = logs
        self.daily_memory = OrderedDict()
        self.graph_memory = OrderedDict()
        self.period_memory = OrderedDict()
        self.view_path = app_paths(cfg)["data"] / "HistoryViews" / device_id
        self.path = app_paths(cfg)['data'] / 'DailySummaries' / (device_id+'.json')
        try: self.cache = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): self.cache = {}

    def _trim_cache(self, cache):
        from .resource_manager import budget
        import sys
        def size(value):
            if isinstance(value,dict):return sys.getsizeof(value)+sum(size(k)+size(v) for k,v in value.items())
            if isinstance(value,(tuple,list)):return sys.getsizeof(value)+sum(size(v) for v in value)
            return sys.getsizeof(value)
        # Caches share the current usable memory, rather than fixed entry counts.
        from .concurrency import active_count
        used=sum(size(value) for value in cache.values());limit=budget()//max(3,active_count()*3)
        while cache and used>limit:
            _,value=cache.popitem(last=False);used-=size(value)

    def generation_sync(self, known=None, cancelled=None, progress=None):
        from .concurrency import keyed_lock,path_key
        with keyed_lock(path_key('daily-summaries',self.path),cancelled):
            try:self.cache=json.loads(self.path.read_text('utf-8'))
            except (OSError,ValueError):self.cache={}
            return self._generation_sync(known,cancelled,progress)

    def _generation_sync(self, known=None, cancelled=None, progress=None):
        from .generation_summary import summarize,release_inputs
        from .prepared_history import write_json
        known = known or {}
        if not isinstance(known, dict) or len(known) > 400:
            raise ValueError('Invalid daily-summary revision map')
        cancelled=cancelled or (lambda:False)
        days=[d for d in self.reader.available_dates() if d<date.today()][-400:]
        changed,manifest=[],{}
        index=getattr(self.reader,'_file_index',None)
        if progress:progress(0,len(days))
        try:
            for i,day in enumerate(days):
                if cancelled():raise ValueError('History query cancelled')
                local,smart=index.get(day,([],[])) if index is not None else self.reader.find_day_files(day)
                signature=(self.reader._files_signature(local+smart),self.reader.model_signature(),'generation-v3-timezone')
                revision=hashlib.sha256(repr(signature).encode()).hexdigest()
                key=day.isoformat();manifest[key]=revision
                if known.get(key)!=revision and len(changed)<40:
                    cached=self.cache.get(key,{})
                    if cached.get('revision')!=revision:
                        def rows_progress(count):
                            if progress:progress(i,len(days))
                        summary=summarize(self.reader,day,cancelled,rows_progress)
                        summary['quality']='good' if summary['records']>=20 and summary['coverage_pct']>=50 else 'partial'
                        # A complete day is a checkpoint, including on cancellation.
                        cached=dict(revision=revision,summary=summary);self.cache[key]=cached
                        self.cache={k:v for k,v in self.cache.items() if k in {d.isoformat() for d in days}}
                        write_json(self.path,self.cache)
                    changed.append(dict(day=key,**cached))
                if progress:progress(i+1,len(days))
            return dict(device_id=self.device_id,manifest=manifest,changed=changed)
        finally:release_inputs(self.reader)

    def _revision(self, day, source):
        if source not in ('Auto', 'Local', 'SmartESS'): raise ValueError('Invalid history source')
        local, smart = self.reader.find_day_files(day)
        paths = local if source == 'Local' else smart if source == 'SmartESS' else local+smart
        from .prepared_history import PreparedHistory
        store=PreparedHistory(self.reader)
        files=[]
        for origin,group in (('Local',local),('SmartESS',smart)):
            if source not in ('Auto',origin):continue
            for path in group:
                identity=store.identity(path,origin,day)[0] if day<date.today() else self.reader._files_signature([path])
                files.append((origin,identity))
        signature = (files, self.reader.model_signature(), 'views-v5-portable', self.device_id)
        return hashlib.sha256(repr(signature).encode()).hexdigest()

    def _daily(self, day, source, cancelled=None):
        revision = self._revision(day, source)
        key = day.isoformat()+'_'+source
        cached = self.daily_memory.get(key)
        hit = 'memory'
        if not cached or cached['revision'] != revision:
            path = self.view_path / (key+'.json')
            try: cached = decode(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError, KeyError): cached = None
            hit = 'disk'
            if not cached or cached.get('revision') != revision:
                hit = 'miss'
                started = time.monotonic()
                rows = self.reader.graph_day_rows(day, source, cancelled)
                from .energy_accounting import number,seconds
                coverage={k:sum(seconds(a['timestamp'],b['timestamp']) for a,b in zip(rows,rows[1:]) if number(a.get(k)) and number(b.get(k)) and 0<seconds(a['timestamp'],b['timestamp'])<=self.cfg.max_integration_gap_s) for k in ('pv_w','output_w')}
                cached = dict(revision=revision, records=len(rows), first=rows[0]['timestamp'] if rows else None, last=rows[-1]['timestamp'] if rows else None, energy=daily_energy(rows, self.cfg.max_integration_gap_s),
                              hourly=self._hourly(day, source, rows),coverage=coverage)
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(encode(cached), ensure_ascii=False, allow_nan=False), encoding='utf-8')
                temp.replace(path)
                if self.logs: self.logs.event('History day calculated', code='history.day.calculated', day=day.isoformat(),
                    device_id=self.device_id, source=source, records=len(rows), duration_ms=round((time.monotonic()-started)*1000,1))
        self.daily_memory[key] = cached
        self.daily_memory.move_to_end(key)
        self._trim_cache(self.daily_memory)
        return cached, hit

    def _period_rows(self, days, source, cancelled=None, progress=None):
        """Read daily storage files without calculating separate daily reports."""
        if progress: progress(0,len(days))
        for index,day in enumerate(days):
            if cancelled and cancelled():raise ValueError('History query cancelled')
            yield from self.reader.graph_day_rows(day,source,cancelled)
            if progress:progress(index+1,len(days))

    def _cached_period(self, key, days, source, calculate, cancelled=None):
        from .concurrency import keyed_lock,path_key
        with keyed_lock(path_key('period',self.view_path/str(key)),cancelled):
            return self._cached_period_locked(key,days,source,calculate,cancelled)

    def _cached_period_locked(self,key,days,source,calculate,cancelled=None):
        from uuid import uuid4
        revision=hashlib.sha256(repr(([(d,self._revision(d,source)) for d in days],
            'period-v1-no-daily',key)).encode()).hexdigest()
        path=self.view_path/('period-'+hashlib.sha256(repr(key).encode()).hexdigest()+'.json')
        cached=self.period_memory.get(key)
        if cancelled and cancelled():raise ValueError('History query cancelled')
        if not cached:
            from .prepared_history import PreparedHistory
            imported=PreparedHistory(self.reader)._object(path.name)
            candidate=path if path.exists() else imported
            try:cached=decode(json.loads(candidate.read_text(encoding='utf-8')))
            except (OSError,ValueError,KeyError):cached=None
            except AttributeError:cached=None
        if isinstance(cached,dict) and cached.get('revision')==revision:
            self.period_memory[key]=cached
            return copy.deepcopy(cached['value'])
        value=calculate()
        if cancelled and cancelled():raise ValueError('History query cancelled')
        # A live file or an ESS revision may change while the rows are read.
        after=hashlib.sha256(repr(([(d,self._revision(d,source)) for d in days],
            'period-v1-no-daily',key)).encode()).hexdigest()
        if after==revision:
            cached=dict(revision=revision,value=value)
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
            try:
                temp.write_text(json.dumps(encode(cached),ensure_ascii=False,allow_nan=False),encoding='utf-8')
                temp.replace(path)
            finally:temp.unlink(missing_ok=True)
            self.period_memory[key]=cached
            self._trim_cache(self.period_memory)
        return value

    def _monthly_energy(self, period, anchor, source, cancelled=None, progress=None, grid=False):
        """One pass through the period; split intervals only at month boundaries."""
        if period not in ('year','all') or source not in ('Auto','Local','SmartESS'):raise ValueError('Invalid energy period')
        if period=='year' and (not isinstance(anchor,date) or not 2010<=anchor.year<=2100):raise ValueError('Invalid year')
        days=[d for d in self.reader.available_dates() if period!='year' or d.year==anchor.year]
        self._month_graph_diagnostics=[]
        def serializable():
            from .month_graph import period as calculate_period
            return calculate_period(self,days,source,grid,cancelled or (lambda:False),progress)
        result=self._cached_period(('monthly-energy-v4',period,anchor.year if anchor else None,source,grid),days,source,serializable,cancelled)
        if progress:progress(len(days),len(days))
        return result

    def energy_period(self, period, anchor=None, source='Auto', cancelled=None, progress=None):
        result=self._monthly_energy(period,anchor,source,cancelled,progress,grid=True)
        return [(m['month'] if period=='year' else (m['year'],m['month']),
                 {k:v if v is not None else 0. for k,v in m['energy'].items()}) for m in result['months']]

    def month_series(self, anchor, source='Auto', cancelled=None, progress=None, fields=None):
        if not isinstance(anchor,date) or not 2010<=anchor.year<=2100 or source not in ('Auto','Local','SmartESS'):raise ValueError('Invalid month')
        days=[d for d in self.reader.available_dates() if (d.year,d.month)==(anchor.year,anchor.month)]
        from .hourly_projection import period,columns
        return period(self,days,source,fields if fields is not None else list(columns()),cancelled,progress)

    def _month_hourly(self,days,source,cancelled,progress):
        from .energy_accounting import seconds
        output=[]
        if progress:progress(0,len(days))
        for index,day in enumerate(days):
            if cancelled and cancelled():raise ValueError('History query cancelled')
            rows=self._cached_period(('hourly-chunk',day,source),[day],source,
                lambda:self._hourly(None,source,self.reader.graph_day_rows(day,source,cancelled)),cancelled)
            # Preserve gaps across storage boundaries as in the period pass.
            if output and rows and seconds(output[-1]['timestamp'],rows[0]['timestamp'])>self.cfg.max_integration_gap_s:
                output.append(dict(timestamp=rows[0]['timestamp'],_gap=True))
            output.extend(rows)
            if progress:progress(index+1,len(days))
        return output

    def _day_energy(self,rows,anchor,source,cancelled,start=None,end=None):
        from datetime import timedelta
        if rows is None and start is None and end is None:
            from .day_energy_index import day
            return day(self,anchor,source,cancelled)
        return self._cached_period(('day-energy-v2',anchor,source,str(start),str(end),self.cfg.max_integration_gap_s),
            [anchor-timedelta(days=1),anchor,anchor+timedelta(days=1)],source,
            lambda:self._calculate_day_energy(rows,anchor,source,cancelled,start,end),cancelled)

    def _calculate_day_energy(self,rows,anchor,source,cancelled,start=None,end=None):
        from datetime import datetime,timedelta
        from .energy_accounting import ZONE
        from .graph_energy import accumulate,boundary,summary
        if rows is None and start is None and end is None:
            from .day_energy_index import day
            return day(self,anchor,source,cancelled)
        rows=self.reader.energy_graph_rows(anchor,source,cancelled) if rows is None else rows
        start=start or datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE);end=end or datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE)+timedelta(days=1)
        sums,coverage={},{};previous=None
        before=boundary(self,anchor-timedelta(days=1),source,cancelled)['last']
        after=boundary(self,anchor+timedelta(days=1),source,cancelled)['first']
        full_rows=([before] if before else [])+rows+([after] if after else [])
        from .cpu_energy import graph as cpu_graph,BLOCK
        for offset in range(0,len(full_rows),BLOCK):
            block=full_rows[offset:offset+BLOCK]
            cpu_graph(sums,coverage,previous,block,self.cfg,start=start,end=end,hourly=True,cancelled=cancelled)
            if block:previous=block[-1]
        points=[dict(x=i,label=key,coverage_seconds=coverage[key],**values)
                for i,(key,values) in enumerate(sorted(sums.items()))]
        return dict(kind='bars',points=points,records=len(rows),reduced=False,energy_summary=summary(points,start,end))

    def graph_data(self, period, anchor, source='Auto', fields=None, max_points=2000, cancelled=None, progress=None, mode=None, window_start=None, window_end=None):
        import time
        started=time.perf_counter()
        from .graph_projection import project,FIELDS
        if period not in ('day','month','year','all') or source not in ('Local','SmartESS','Auto'):raise ValueError('Invalid graph request')
        if not isinstance(anchor,date) or not 2010<=anchor.year<=2100:raise ValueError('Invalid graph date')
        from .graph_window import bounds, clip
        window=bounds(period,anchor,window_start,window_end)
        def day_rows():
            scalar=mode=='energy'
            if scalar and hasattr(self.reader,'energy_graph_rows'):
                return self.reader.energy_graph_rows(anchor,source,cancelled)
            return self.reader.graph_day_rows(anchor,source,cancelled)
        fields=fields or ['pv_w','output_w']
        project([],fields,max_points,max_gap=self.cfg.max_integration_gap_s)
        if cancelled and cancelled():raise ValueError('History query cancelled')
        mode = mode or ('energy' if period in ('year','all') else 'power')
        if mode not in ('power','energy') or (mode == 'power' and period in ('year','all')):
            raise ValueError('Invalid graph mode for period')
        if mode == 'energy':
            from datetime import datetime, timedelta
            from .energy_accounting import ZONE
            from .graph_energy import accumulate, summary, boundary
            if period in ('year','all'):
                monthly=self._monthly_energy(period,anchor,source,cancelled,progress,grid=True)
                points=[dict(x=i,label=f"{m['year']}-{m['month']:02d}",coverage_seconds=m['coverage'],**m['energy'])
                        for i,m in enumerate(monthly['months'])]
                records=monthly['records']
                years=[int(p['label'][:4]) for p in points]
                start=datetime(anchor.year if period=='year' or not years else min(years),1,1,tzinfo=ZONE)
                end=datetime((anchor.year if period=='year' or not years else max(years))+1,1,1,tzinfo=ZONE)
                if period=='all' and points:
                    y,m=map(int,points[0]['label'].split('-'));start=datetime(y,m,1,tzinfo=ZONE)
                    y,m=map(int,points[-1]['label'].split('-'));end=datetime(y+1,1,1,tzinfo=ZONE) if m==12 else datetime(y,m+1,1,tzinfo=ZONE)
            elif period == 'month':
                from .month_graph import month
                value,diagnostics=month(self,anchor,source,True,cancelled or (lambda:False))
                self._month_graph_diagnostics=[dict(period=anchor.strftime('%Y-%m'),**diagnostics)]
                start=datetime(anchor.year,anchor.month,1,tzinfo=ZONE)
                end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
                # Add only the clipped boundary intervals, using cached endpoint samples.
                # The month checkpoint remains independent of next month's growing file.
                if value['first']:
                    before=boundary(self,start.date()-timedelta(days=1),source,cancelled)['last']
                    if before:
                        accumulate({}, {}, before,value['first'],self.cfg,daily=value['daily'],
                                   daily_coverage=value['daily_coverage'],start=start,end=end)
                    after=boundary(self,end.date(),source,cancelled)['first']
                    if after:
                        accumulate({}, {}, value['last'],after,self.cfg,daily=value['daily'],
                                   daily_coverage=value['daily_coverage'],start=start,end=end)
                points=[]
                if value['records']:
                    from .graph_energy import FIELDS as energy_fields
                    day=start
                    while day<end:
                        key=day.date().isoformat()
                        points.append(dict(x=day.day-1,label=key,
                                           coverage_seconds=value['daily_coverage'].get(key,{}),
                                           **value['daily'].get(key,{k:None for k in energy_fields})))
                        day+=timedelta(days=1)
                records=value['records']
            else:
                value=self._day_energy(None,anchor,source,cancelled,*(window or (None,None)))
                points=value['points'];records=value['records']
                if window:start,end=window
                else:
                    start=datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE);end=start+timedelta(days=1)
            read_done=time.perf_counter()
            result=dict(kind='bars',points=points,records=records,reduced=False,
                        energy_summary=summary(points,start,end))
            fields=[k for k in fields if k in ('pv_w','output_w','grid_import_w','grid_export_w')] or ['pv_w','output_w']
            result['bucket']='hour' if period=='day' else 'day' if period=='month' else 'month'
        else:
            rows=day_rows() if period=='day' else self.month_series(anchor,source,cancelled,progress,fields=fields)
            read_done=time.perf_counter()
            project_started=time.perf_counter()
            plot_rows=clip(rows,*window,self.cfg.max_integration_gap_s) if window else rows
            result=project(plot_rows,fields,max_points,period=='month',self.cfg.max_integration_gap_s)
            plot_projection_s=time.perf_counter()-project_started;summary_started=time.perf_counter()
            result['kind']='line'
            if 'pv_w' in fields and 'output_w' in fields:
                # Same full-resolution accounting and cached month contributions
                # as the energy chart; never integrate decimated plot points.
                totals=self._day_energy(rows,anchor,source,cancelled,*(window or (None,None))) if period=='day' else self.graph_data(period,anchor,source,['pv_w','output_w','grid_import_w','grid_export_w'],max_points,cancelled,progress,mode='energy')
                result['energy_summary']=totals['energy_summary']
        if cancelled and cancelled():raise ValueError('History query cancelled')
        result.update(contract='ducksolar.graph.v1',mode=mode,period=period,anchor=anchor.isoformat(),source=source,fields=[dict(key=k,label=FIELDS[k][0],unit='кВт·год' if result['kind']=='bars' else FIELDS[k][1]) for k in fields])
        if window is not None:result['window']={'start':window[0].isoformat(),'end':window[1].isoformat()}
        from .insight_history import markers
        result['events']=markers(self.cfg,self.device_id,result)
        result['diagnostics']=dict(field_statistics=result.get('field_statistics',{}),scalar_index=getattr(self.reader,'_last_graph_index_stats',{}) if period=='day' and hasattr(self.reader,'energy_graph_rows') else {},plot_projection_s=round(locals().get('plot_projection_s',0),4),energy_summary_s=round(time.perf_counter()-summary_started,4) if 'summary_started' in locals() else 0,hourly_projection=getattr(self,'_hourly_projection_diagnostics',[]) if mode!='energy' and period=='month' else [],month_chunks=getattr(self,'_month_graph_diagnostics',[]) if mode=='energy' and period!='day' else [],read_s=round(read_done-started,4),projection_s=round(time.perf_counter()-read_done,4),total_s=round(time.perf_counter()-started,4),input_records=result.get('records'),output_points=len(result['points']),period=period,source=source)
        return result

    def insights_data(self,kind,anchor,source='Auto',other=None,period='day',metric='pv_w',cancelled=None,progress=None):
        from .insight_history import data
        return data(self,kind,anchor,source,other,period,metric,cancelled,progress)

    def graph_day(self, day, source='Auto', cancelled=None, progress=None):
        """Only graph fields: no repeated protocol JSON or raw CSV copy in HTTP."""
        revision=self._revision(day,source)
        key=(day,source)
        cached=self.graph_memory.get(key)
        if cached and cached[0]==revision:
            self.graph_memory.move_to_end(key)
            return cached[1]
        rows=[{k:v for k,v in row.items() if k not in ('_raw','normalized')}
              for row in self.reader.graph_day_rows(day,source,cancelled)]
        self.graph_memory[key]=(revision,rows)
        self.graph_memory.move_to_end(key)
        self._trim_cache(self.graph_memory)
        return rows

    def _hourly(self, day, source, rows_override=None):
        """Hourly means for every numeric telemetry field, with explicit gaps.

        Each continuous source segment is separate; averages never bridge
        outages or import/export source changes. Counters use their last value.
        """
        output, bucket, totals, counts = [], None, {}, {}
        first = last = previous = None
        source_fields = ('grid_import_source', 'grid_import_origin', 'grid_export_source', 'grid_export_origin')
        metadata = {}
        def flush():
            if first is None: return
            row = dict(timestamp=first, **metadata)
            row.update({k: totals[k]/counts[k] for k in totals})
            output.append(row)
        for rows in (rows_override if rows_override is not None else self.reader.load_day(day, source),):
            for row in rows:
                stamp = row['timestamp']
                from .energy_accounting import stamp as normalize_stamp, seconds
                key = (int(normalize_stamp(stamp).timestamp() // 3600), tuple(row.get(k) for k in source_fields))
                gap = previous is not None and seconds(previous, stamp) > self.cfg.max_integration_gap_s
                if key != bucket or gap:
                    flush()
                    if gap: output.append(dict(timestamp=stamp, _gap=True))
                    bucket, totals, counts = key, {}, {}
                    first = stamp
                    metadata = {k:row.get(k) for k in source_fields}
                for k, value in row.items():
                    if k.startswith('_') or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value): continue
                    if k.endswith('_energy_total_kwh'):
                        totals[k], counts[k] = value, 1
                    else:
                        totals[k] = totals.get(k, 0)+value
                        counts[k] = counts.get(k, 0)+1
                last = previous = stamp
        flush()
        return output
