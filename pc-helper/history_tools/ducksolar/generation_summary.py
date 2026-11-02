"""Lossless legacy daily summary using disk ordered scalar rows, not day objects."""
import csv
import time
import math
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from .energy_accounting import ZONE, stamp

FIELDS=('pv_corrected_w','output_w','battery_charge_w','estimated_grid_import_w','estimated_export_w')

def release_inputs(reader):
    for name in ('_cache','_cache_signatures','_cache_order','_append_cache','_compact_codecs'):
        value=getattr(reader,name,None)
        if value is not None:value.clear()

def summarize(reader, day, cancelled=lambda:False, progress=None):
    from .energy_streaming import _snapshot_lines
    from .prepared_history import PreparedHistory
    from .resource_manager import configure
    work=Path(reader.cfg.root_dir)/'Data/EnergyWork/Generation'
    work.mkdir(parents=True,exist_ok=True)
    handle=tempfile.NamedTemporaryFile(prefix='generation-',suffix='.db',dir=work,delete=False)
    path=Path(handle.name);handle.close()
    con=None
    def check():
        if cancelled():raise ValueError('History query cancelled')
    try:
        con=sqlite3.connect(path);configure(con)
        con.execute('CREATE TABLE rows(origin INTEGER,ts REAL,pv REAL,load REAL,charge REAL,imp REAL,exp REAL,PRIMARY KEY(origin,ts)) WITHOUT ROWID')
        prepared=PreparedHistory(reader)
        local,smart=reader.find_day_files(day)
        seen=set();count=0;last_progress=time.monotonic()
        for origin,paths in [('Local',local),('SmartESS',smart)]:
            for source in paths:
                check()
                identity,metadata=prepared.identity(source,origin,day,cancelled)
                # File copies must not change the day result or duplicate records.
                if (origin,identity) in seen:continue
                seen.add((origin,identity))
                ready=prepared.rows(source,origin,day,cancelled,create=False)
                decode=reader.compact_decoder(source,True)
                if ready is None:
                    raw=csv.DictReader(_snapshot_lines(source,metadata['raw_bytes']),strict=True)
                    def canonical():
                        for row in raw:
                            check()
                            if None in row or any(v is None for v in row.values()):continue
                            # No normalized/raw dictionaries survive this iteration.
                            value=reader._canonical(decode(row),origin,day)
                            if value:yield value
                    records=canonical()
                else:records=ready
                batch=[]
                for row in records:
                    check();values=[]
                    for key in FIELDS:
                        v=row.get(key)
                        values.append(float(v) if isinstance(v,(int,float)) and math.isfinite(v) else None)
                    batch.append((0 if origin=='Local' else 1,stamp(row['timestamp']).timestamp(),*values))
                    count+=1
                    if len(batch)>=256:
                        con.executemany('INSERT OR IGNORE INTO rows VALUES(?,?,?,?,?,?,?)',batch);batch.clear()
                        if progress and time.monotonic()-last_progress>=1:
                            progress(count);last_progress=time.monotonic()
                if batch:con.executemany('INSERT OR IGNORE INTO rows VALUES(?,?,?,?,?,?,?)',batch)
                verified,after=prepared.identity(source,origin,day,cancelled)
                if verified!=identity or after!=metadata:raise ValueError('History changed during generation summary')
        con.commit();check()
        gap=max(15.,reader.cfg.poll_interval_s*3.)
        # Same nearest-Local Auto exclusion and first-file duplicate priority as
        # HistoryReader.load_day, with an indexed NOT EXISTS lookup.
        cursor=con.execute('SELECT ts,pv,load,charge,imp,exp FROM rows r WHERE origin=0 OR NOT EXISTS '
            '(SELECT 1 FROM rows l WHERE l.origin=0 AND l.ts BETWEEN r.ts-? AND r.ts+?) ORDER BY ts', (gap,gap))
        from .cpu_energy import generation as cpu_generation
        calculated=cpu_generation(cursor,reader.cfg.max_integration_gap_s,cancelled)
        if calculated is not None:
            sums=[v*3600000 for v in calculated['values']];covered=calculated['covered'];records=calculated['records']
        else:
            sums=[0.]*5;previous=[None]*5;last=None;covered=0.;records=0;first=None
            for row in cursor:
                check();ts=row[0];records+=1
                if first is None:first=ts
                if last is not None and 0<ts-last<=reader.cfg.max_integration_gap_s:covered+=ts-last
                last=ts
                for i,v in enumerate(row[1:]):
                    if v is None:previous[i]=None;continue
                    old=previous[i]
                    if old is not None and 0<ts-old[0]<=reader.cfg.max_integration_gap_s:
                        sums[i]+=(old[1]+v)*.5*(ts-old[0])
                    previous[i]=(ts,v)
        start=datetime.combine(day,datetime.min.time(),ZONE)
        duration=(start+timedelta(days=1)).timestamp()-start.timestamp()
        values=[v/3600000 for v in sums]
        return dict(day=day.isoformat(),pv_kwh=values[0],house_kwh=values[1],battery_charge_kwh=values[2],
                    grid_import_kwh=values[3],export_kwh=values[4],coverage_pct=min(100,covered/duration*100),records=records)
    finally:
        if con is not None:con.close()
        # Only our exact disposable index is removed. User CSV/archives untouched.
        assert path.resolve().parent==work.resolve() and path.name.startswith('generation-')
        path.unlink(missing_ok=True)
        release_inputs(reader)
