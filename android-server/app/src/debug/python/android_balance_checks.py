"""Regression and resource checks against the legacy mathematical ledger."""
import csv,json,tempfile,threading,time,tracemalloc
from pathlib import Path
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo

def run(root,count=48000,trace=True):
    from ducksolar.config import AppConfig
    from ducksolar.storage import Storage
    from ducksolar.history_reader import HistoryReader
    from ducksolar.energy_accounting import month_report,interval_energy,ZONE
    from ducksolar.energy_streaming import MonthAccounting
    output={};fixed=datetime(2026,10,1,tzinfo=ZONE)
    with tempfile.TemporaryDirectory(prefix='balance-check-',dir=root) as temporary:
        cfg=AppConfig(root_dir=temporary)
        storage=Storage(cfg);folder=storage.paths['inverter_logs']
        rows=[]
        # Month boundaries, missing values and counter rollover/reset.
        stamps=[datetime(2026,8,31,23,55,tzinfo=ZONE),datetime(2026,9,1,0,5,tzinfo=ZONE),
                datetime(2026,9,1,0,10,tzinfo=ZONE),datetime(2026,9,1,0,15,tzinfo=ZONE),
                datetime(2026,9,1,23,55,tzinfo=ZONE),datetime(2026,9,2,0,5,tzinfo=ZONE),
                datetime(2026,9,30,23,55,tzinfo=ZONE),fixed+timedelta(minutes=5)]
        for i,stamp in enumerate(stamps):
            rows.append(dict(time=stamp.isoformat(),pv_w=1000+i*100,
              grid_import_w=200+i*10,grid_import_source='measured',grid_import_origin='test',
              grid_export_w='' if i==3 else 50,grid_export_source='estimated',grid_export_origin='test',
              grid_import_energy_total_kwh=[99,99.5,.1,.3,.5,.8,.9,1.0][i],grid_import_counter_id='fixture'))
        def write_rows(items):
            by_day={}
            for row in items:by_day.setdefault(row['time'][:10],[]).append(row)
            fields=list(dict.fromkeys(k for row in items for k in row))
            for day,records in by_day.items():
                with (folder/(day+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.DictWriter(f,fields);writer.writeheader();writer.writerows(records)
        write_rows(rows)
        legacy=month_report(HistoryReader(cfg),storage,cfg,date(2026,9,1),now=fixed)
        service=MonthAccounting();compact=service.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)
        for name in ('pv','inverter_import','inverter_export'):
            for metric in ('kwh','coverage_pct','measured_pct','estimated_pct','missing_pct'):
                a,b=legacy[name][metric],compact[name][metric]
                assert (a is b is None) or abs(a-b)<1e-9,(name,metric,a,b)
            assert 'intervals' not in compact[name]
        assert compact['days']==[] and compact['daily_detail'] is False
        assert compact['house_meter']==legacy['house_meter']
        assert service.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)['cache_hit']
        assert service.calculations==1
        page=service.audit_page(cfg,'2026-09',audit_id=compact['audit_id'],limit=2)
        assert len(page['records'])==2 and not page['done']
        next_page=service.audit_page(cfg,'2026-09',audit_id=compact['audit_id'],offset=page['next_offset'],limit=2)
        assert next_page['records'][0]['type'] in ('input','interval')

        # Config and source changes invalidate the persisted compact result.
        cfg.max_integration_gap_s=100
        assert not service.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)['cache_hit']
        cfg.max_integration_gap_s=900
        changed=dict(rows[2],pv_w=999)
        rows[2]=changed;write_rows(rows)
        assert not service.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)['cache_hit']
        # The original CSV rows stay intact, and no meter readings are created.
        assert storage.list_meter_readings()==[]
        output['legacy_totals_match_without_daily_calculation']=True
        output['cache_source_and_config_invalidation']=True
        # DST accounting: 23/25-hour days, one pair crossing the repeated hour.
        for start,hours in [(datetime(2026,3,29,tzinfo=ZONE),23),(datetime(2026,10,25,tzinfo=ZONE),25)]:
            end=start+timedelta(days=1)
            pair=[{'timestamp':start,'pv_w':1000},{'timestamp':end,'pv_w':1000}]
            value=interval_energy(pair,'pv',start,end,max_gap=100000)
            assert abs(value['kwh']-hours)<1e-9 and value['coverage_pct']==100
        folds=[{'timestamp':datetime(2026,10,25,3,10,tzinfo=ZONE,fold=0),'pv_w':1000},
               {'timestamp':datetime(2026,10,25,3,10,tzinfo=ZONE,fold=1),'pv_w':1000}]
        assert abs(interval_energy(folds,'pv',datetime(2026,10,25,tzinfo=ZONE),datetime(2026,10,26,tzinfo=ZONE),7200)['kwh']-1)<1e-9
        output['dst_23_25_hours_and_fold']=True
        # Separate constant-memory generator validates the sorting/accounting path at scale.
        fields=('time','pv_w','grid_import_w','grid_import_source','grid_import_origin','grid_export_w','grid_export_source','grid_export_origin')
        first=datetime(2026,9,1,tzinfo=ZONE)
        handles={}
        try:
            for i in range(count):
                stamp=first+timedelta(seconds=i*50)
                day=stamp.date().isoformat()
                if day not in handles:
                    f=(folder/(day+'.csv')).open('w',encoding='utf-8-sig',newline='');writer=csv.writer(f);writer.writerow(fields);handles[day]=(f,writer)
                handles[day][1].writerow((stamp.isoformat(),1000,200,'measured','fixture',50,'estimated','fixture'))
        finally:
            for f,writer in handles.values():f.close()
        # Existing edge-day files intentionally remain to exercise the preceding/following day.
        if trace:tracemalloc.start()
        started=time.monotonic()
        large=service.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)
        elapsed=time.monotonic()-started;current,peak=tracemalloc.get_traced_memory() if trace else (0,0)
        if trace:tracemalloc.stop()
        encoded=json.dumps(large,ensure_ascii=False).encode();assert len(encoded)<60000
        assert large['input_count']>=count
        assert peak<16*1024*1024,(peak,count)
        # Cached calculation replay after a service restart; 10 reads, no recalculation.
        new=MonthAccounting()
        if trace:tracemalloc.start()
        started=time.monotonic()
        for i in range(10):assert new.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)['cache_hit']
        current,replay_peak=tracemalloc.get_traced_memory() if trace else (0,0)
        if trace:tracemalloc.stop()
        assert new.calculations==0 and replay_peak<4*1024*1024
        output.update(input_count=large['input_count'],response_bytes=len(encoded),calculation_s=round(elapsed,3),
                      python_peak_bytes=peak,cached_10_reads_s=round(time.monotonic()-started,3),cached_peak_bytes=replay_peak)
        # Explicit cancellation and a bounded (zero waiting) heavy-job queue.
        entered=threading.Event();release=threading.Event();errors=[]
        class SlowReader(HistoryReader):
            def _canonical(self,*args,**kwargs):
                entered.set();release.wait(5)
                return super()._canonical(*args,**kwargs)
        cfg.max_integration_gap_s=901 # invalidate the prior summary
        def calculate():
            try:service.report(SlowReader(cfg),storage,cfg,'2026-09',now=fixed)
            except ValueError as exc:errors.append(str(exc))
        worker=threading.Thread(target=calculate);worker.start();assert entered.wait(5)
        try:
            try:service.report(HistoryReader(cfg),storage,cfg,'2026-09',now=fixed)
            except ValueError:pass
            else:raise AssertionError('Concurrent calculation admitted')
        finally:service.stop_event.set();release.set();worker.join(5)
        assert not worker.is_alive() and len(errors)==1
        assert not list((Path(temporary)/'Data'/'EnergyWork').glob('month-*'))
        assert not list((Path(temporary)/'Data'/'EnergyAudit'/'inverter-1').glob('.*.tmp'))
        output['bounded_jobs_and_cancel']=True
    return json.dumps(output,ensure_ascii=False)

if __name__=='__main__':
    import os,sys
    with tempfile.TemporaryDirectory() as root:
        os.environ['DUCK_SOLAR_ROOT']=root
        print(run(root,int(sys.argv[1]) if len(sys.argv)>1 else 48000))
