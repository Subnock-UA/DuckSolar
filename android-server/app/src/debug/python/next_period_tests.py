import csv
import json
import sys
import tempfile
import unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import patch

from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_views import HistoryViews
from ducksolar.energy_streaming import MonthAccounting,_Summary
from ducksolar.energy_accounting import ZONE,month_report

class Storage:
    def list_meter_readings(self,**kwargs):return []

class PeriodOnly(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cfg=AppConfig(root_dir=self.temp.name,max_integration_gap_s=900)
        self.reader=HistoryReader(self.cfg)
        self.view=HistoryViews(self.reader,self.cfg,'inverter-1')
        self.folder=self.reader.paths['inverter_logs'];self.folder.mkdir(parents=True,exist_ok=True)
    def tearDown(self):self.temp.cleanup()
    def write(self,rows):
        groups={}
        for row in rows:groups.setdefault(row['time'][:10],[]).append(row)
        fields=list(dict.fromkeys(k for row in rows for k in row))
        for day,values in groups.items():
            with (self.folder/(day+'.csv')).open('w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fields);writer.writeheader();writer.writerows(values)
        self.reader.available_dates(refresh=True)
    def row(self,instant,pv=1000,output=500):
        return dict(time=instant.isoformat(),pv_w=pv,output_w=output,
                    grid_import_w=200,grid_import_source='measured',grid_import_origin='fixture',
                    grid_export_w=50,grid_export_source='measured',grid_export_origin='fixture')
    def test_balance_totals_no_daily_objects_and_cache(self):
        t=datetime(2026,9,1,23,55,tzinfo=ZONE)
        self.write([self.row(t+timedelta(minutes=i*5)) for i in range(5)])
        fixed=datetime(2026,10,1,tzinfo=ZONE)
        expected=month_report(HistoryReader(self.cfg),Storage(),self.cfg,date(2026,9,1),now=fixed)
        service=MonthAccounting()
        with patch('ducksolar.energy_streaming._Summary',wraps=_Summary) as construct:
            actual=service.report(self.reader,Storage(),self.cfg,'2026-09',now=fixed,source='Local')
            self.assertEqual(construct.call_count,3)
        self.assertEqual(actual['days'],[]);self.assertFalse(actual['daily_detail'])
        for field in ('pv','inverter_import','inverter_export'):
            for metric in ('kwh','coverage_pct','measured_pct','estimated_pct','missing_pct'):
                self.assertAlmostEqual(actual[field][metric],expected[field][metric])
        self.assertTrue(service.report(self.reader,Storage(),self.cfg,'2026-09',now=fixed,source='Local')['cache_hit'])
        summary=json.loads((Path(self.temp.name)/'Data/EnergyAudit/inverter-1/2026-09-Local.summary.json').read_text(encoding='utf-8'))
        self.assertNotIn('days',summary['checkpoint'])
    def test_month_graph_never_builds_daily_summary(self):
        t=datetime(2026,9,1,23,55,tzinfo=ZONE)
        self.write([self.row(t+timedelta(minutes=i*5)) for i in range(4)])
        with patch.object(self.view,'_daily',side_effect=AssertionError('Daily report forbidden')):
            result=self.view.graph_data('month',date(2026,9,1),'Local')
            self.assertEqual(result['kind'],'line');self.assertTrue(result['points'])
        self.assertEqual(list(self.view.view_path.glob('2026-*.json')),[])
    def test_year_graph_integrates_midnight_without_daily_or_hourly(self):
        t=datetime(2026,9,30,23,55,tzinfo=ZONE)
        self.write([self.row(t),self.row(t+timedelta(minutes=10))])
        with patch.object(self.view,'_daily',side_effect=AssertionError('Daily forbidden')),patch.object(self.view,'_hourly',side_effect=AssertionError('Hourly forbidden')):
            result=self.view.graph_data('year',date(2026,9,1),'Local')
        self.assertEqual([p['label'] for p in result['points']],['2026-09','2026-10'])
        for point in result['points']:
            self.assertAlmostEqual(point['pv_w'],1/12)
            self.assertAlmostEqual(point['output_w'],1/24)
            self.assertEqual(point['coverage_seconds']['pv_w'],300)
    def test_missing_zero_and_gaps(self):
        t=datetime(2026,9,1,tzinfo=ZONE)
        self.write([self.row(t,pv=0,output=''),self.row(t+timedelta(minutes=5),pv=0,output=''),self.row(t+timedelta(days=2),pv=1000,output='')])
        result=self.view.graph_data('year',date(2026,9,1),'Local')['points'][0]
        self.assertEqual(result['pv_w'],0)
        self.assertIsNone(result['output_w'])
        self.assertEqual(result['coverage_seconds']['pv_w'],300)
    def test_disk_cache_and_source_edit_invalidation(self):
        t=datetime(2026,9,1,tzinfo=ZONE)
        self.write([self.row(t),self.row(t+timedelta(minutes=5))])
        first=self.view.graph_data('year',date(2026,9,1),'Local')
        view=HistoryViews(self.reader,self.cfg,'inverter-1')
        with patch.object(self.reader,'graph_day_rows',side_effect=AssertionError('Warm cache must bypass CSV')):
            second=view.graph_data('year',date(2026,9,1),'Local')
            self.assertEqual({k:v for k,v in second.items() if k!='diagnostics'},{k:v for k,v in first.items() if k!='diagnostics'})
        self.write([self.row(t,pv=2000),self.row(t+timedelta(minutes=5),pv=2000)])
        second=view.graph_data('year',date(2026,9,1),'Local')
        self.assertAlmostEqual(second['points'][0]['pv_w'],2*first['points'][0]['pv_w'])
    def test_cancel_does_not_publish_incomplete_cache(self):
        t=datetime(2026,9,1,tzinfo=ZONE)
        self.write([self.row(t),self.row(t+timedelta(minutes=5))])
        with self.assertRaises(ValueError):self.view.graph_data('year',date(2026,9,1),'Local',cancelled=lambda:True)
        self.assertFalse(self.view.view_path.exists())
    def test_dst_fold_uses_elapsed_time(self):
        t=datetime(2026,10,25,3,10,tzinfo=ZONE,fold=0)
        u=datetime(2026,10,25,3,10,tzinfo=ZONE,fold=1)
        self.cfg.max_integration_gap_s=7200
        self.write([self.row(t),self.row(u)])
        result=self.view.graph_data('year',date(2026,10,1),'Local')['points'][0]
        self.assertAlmostEqual(result['pv_w'],1)
        self.assertEqual(result['coverage_seconds']['pv_w'],3600)

if __name__=='__main__':unittest.main(verbosity=2)
