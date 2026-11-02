import sys,tempfile,time,threading,json,csv,zipfile,hashlib,unittest
from pathlib import Path
from datetime import date,datetime,timedelta
from unittest.mock import patch
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.history_jobs import HistoryJobs
from ducksolar.prepared_history import PreparedHistory,export_package,import_package,digest
from ducksolar.energy_streaming import MonthAccounting
from ducksolar.services.official_tariffs import TariffService
from ducksolar.storage import Storage
class Logs:
    def event(self,*args,**kwargs):pass
class EmptyStorage:
    def list_meter_readings(self,**kw):return []
class NewServices(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def wait(self,jobs,owner,ident):
        end=time.monotonic()+5
        while time.monotonic()<end:
            job=jobs.status(owner,ident)
            if job['state'] in ('completed','cancelled','error'):return job
            time.sleep(.01)
        self.fail('Job did not finish')
    def test_independent_queues_ownership_retry_cancel_and_result(self):
        jobs=HistoryJobs(self.root,Logs());hold=threading.Event()
        try:
            def long(cancel,progress):
                while not hold.wait(.01):
                    if cancel():raise ValueError('cancelled')
                return {'date':date(2026,9,1)}
            a=jobs.start('alice','inverter-1','graph',{'period':'year'},long,'a'*32)
            b=jobs.start('alice','inverter-1','balance',{'period':'month'},lambda c,p:{'kwh':42})
            self.assertEqual(self.wait(jobs,'alice',b['job_id'])['state'],'completed')
            self.assertEqual(jobs.start('alice','inverter-1','graph',{'period':'year'},long,'a'*32)['job_id'],a['job_id'])
            with self.assertRaises(ValueError):jobs.status('bob',a['job_id'])
            with self.assertRaises(ValueError):jobs.status('alice',a['job_id'],'another')
            queued=jobs.start('alice','inverter-1','graph',{},long)
            self.assertEqual(jobs.cancel('alice',queued['job_id'])['state'],'cancelled')
            jobs.cancel('alice',a['job_id']);self.assertEqual(self.wait(jobs,'alice',a['job_id'])['state'],'cancelled')
            self.assertEqual(jobs.result('alice',b['job_id'])['result'],{'kwh':42})
        finally:hold.set();jobs.stop()
        restarted=HistoryJobs(self.root,Logs())
        try:self.assertEqual(restarted.result('alice',b['job_id'])['result'],{'kwh':42})
        finally:restarted.stop()
    def test_legacy_disconnect_cancels_running_job(self):
        jobs=HistoryJobs(self.root,Logs())
        try:
            def long(cancel,p):
                while not cancel():time.sleep(.01)
                raise ValueError('cancelled')
            a=jobs.start('alice','inverter-1','graph',{},long)
            with self.assertRaises(ValueError):jobs.wait_legacy('alice',a['job_id'],5,lambda:True)
            self.assertEqual(self.wait(jobs,'alice',a['job_id'])['state'],'cancelled')
            abandoned=jobs.start('alice','inverter-1','graph',{'abandoned':True},long)
            with jobs.lock:jobs.jobs[abandoned['job_id']]['touched']=time.monotonic()-181
            jobs._reap_once()
            self.assertEqual(self.wait(jobs,'alice',abandoned['job_id'])['error_code'],'history.abandoned')
        finally:jobs.stop()
    def reader(self,root):
        cfg=AppConfig(root_dir=str(root));reader=HistoryReader(cfg)
        folder=reader.paths['inverter_logs'];folder.mkdir(parents=True,exist_ok=True)
        with (folder/'2026-09-01.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f);w.writerow(['time','pv_w','output_w','normalized_json'])
            w.writerows([['2026-09-01T00:00:00+03:00',1000,500,'{}'],['2026-09-01T00:05:00+03:00',1000,500,'{}']])
        reader.available_dates(refresh=True);return reader
    def test_pc_package_portability_balance_and_invalidations(self):
        pc=self.reader(self.root/'pc');phone=self.reader(self.root/'phone')
        before=MonthAccounting().report(phone,EmptyStorage(),phone.cfg,'2026-09',source='Local')
        original=phone.find_day_files(date(2026,9,1))[0][0];original_sha=digest(original)
        archive=self.root/'history.zip';export_package(pc,archive)
        result=import_package(phone.cfg.root_dir,archive,digest(archive));self.assertEqual(result['state'],'activated')
        from ducksolar.history_views import HistoryViews
        with patch.object(phone,'graph_day_rows',side_effect=AssertionError('Must use PC period cache')):
            self.assertTrue(HistoryViews(phone,phone.cfg,'inverter-1').graph_data('year',date(2026,9,1),'Local')['points'])
        with patch.object(phone,'_canonical',side_effect=AssertionError('Must use portable projection')):
            rows=phone.graph_day_rows(date(2026,9,1),'Local');self.assertEqual(len(rows),2)
            # Force recomputation while retaining portable objects.
            summary=Path(phone.cfg.root_dir)/'Data/EnergyAudit/inverter-1/2026-09-Local.summary.json';summary.unlink()
            after=MonthAccounting().report(phone,EmptyStorage(),phone.cfg,'2026-09',source='Local')
            self.assertAlmostEqual(before['pv']['kwh'],after['pv']['kwh']);self.assertEqual(after['diagnostics']['prepared_hits'],1)
        self.assertEqual(digest(original),original_sha)
        phone.cfg.pv_correction_factor=1.04
        store=PreparedHistory(phone);self.assertIsNone(store.rows(original,'Local',date(2026,9,1),create=False))
    def test_corrupt_package_not_activated_and_cancel_no_object(self):
        reader=self.reader(self.root/'pc');archive=self.root/'history.zip';export_package(reader,archive)
        with self.assertRaises(ValueError):import_package(self.root/'phone',archive,'0'*64)
        self.assertFalse((self.root/'phone/Data/PreparedHistory/current.json').exists())
        store=PreparedHistory(self.reader(self.root/'other'));p=store.reader.find_day_files(date(2026,9,1))[0][0]
        with self.assertRaises(ValueError):store.prepare(p,'Local',date(2026,9,1),lambda:True)
        self.assertFalse(list((store.root/'objects').glob('*.jsonl.gz')))
    def test_tariff_document_date_band_and_manual_override(self):
        cfg=AppConfig(root_dir=str(self.root));storage=Storage(cfg);service=TariffService(cfg,storage)
        text='День оприлюднення на офіційному вебсайті Регулятора: 02.10.2026 29.09.2026 № 1613 1. Установити сонячний тариф з 01 січня 2025 року по 31 грудня 2025 року – 680,01 коп/кВт·год; з 01 січня 2026 року по 31 грудня 2029 року – 613,40 коп/кВт·год. 2. Установити інший тариф. Ця постанова набирає чинності з 01 жовтня 2026 року, але не раніше дня, наступного за днем оприлюднення.'
        self.assertEqual(service.parse(text)[:2],('2026-10-03',6.8001))
        cfg.green_tariff_commissioning_year=2027;self.assertAlmostEqual(service.parse(text)[1],6.134)
        cfg.green_tariff_commissioning_year=2015
        with self.assertRaises(ValueError):service.parse(text)
        cfg.green_tariff_commissioning_year=2025
        storage.upsert_tariff('2026-10-03',9,'manual',user_override=True)
        class Response:
            status=200
            def geturl(self):return 'https://www.nerc.gov.ua/acts/fixture'
            def read(self,n):return text.encode()
            def __enter__(self):return self
            def __exit__(self,*a):pass
        with patch('urllib.request.urlopen',return_value=Response()):
            result=service.check_for_updates();self.assertTrue(result.manual_override);self.assertFalse(result.changed)
        self.assertEqual(storage.tariff_for_date('2026-10-03')['uah_per_kwh'],9)
        with patch('urllib.request.urlopen',side_effect=OSError('offline')):
            with self.assertRaises(OSError):service.check_for_updates()
        self.assertEqual(service.status()['rate_uah'],6.8001)
if __name__=='__main__':unittest.main(verbosity=2)
