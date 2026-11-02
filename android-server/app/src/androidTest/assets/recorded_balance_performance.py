import csv,json,shutil,tempfile,time
from pathlib import Path
from datetime import datetime,timedelta
from ducksolar.config import AppConfig
from ducksolar.storage import Storage
from ducksolar.history_reader import HistoryReader
from ducksolar.energy_streaming import MonthAccounting
from ducksolar.energy_accounting import ZONE,stamp

fixture=Path(performance_root)/'synthetic-history'
fixture.mkdir(parents=True,exist_ok=True)
for offset in range(4):
    day=datetime(2026,10,1,tzinfo=ZONE)+timedelta(days=offset)
    with (fixture/(day.date().isoformat()+'.csv')).open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,['time','pv_w','output_w','grid_v','grid_hz'])
        writer.writeheader()
        for i in range(288):writer.writerow(dict(time=(day+timedelta(minutes=5*i)).isoformat(),pv_w=500 if 72<=i<216 else 0,output_w=250,grid_v=230,grid_hz=50))
with tempfile.TemporaryDirectory(prefix='synthetic-balance-',dir=performance_root) as temporary:
    cfg=AppConfig(root_dir=temporary);storage=Storage(cfg)
    for path in fixture.glob('*.csv'):
        # SELinux labels belong to the destination, not the captured fixture.
        shutil.copyfile(path,storage.paths['inverter_logs']/path.name)
    now=datetime(2026,10,10,22,20,tzinfo=ZONE)
    service=MonthAccounting();started=time.monotonic()
    first=service.report(HistoryReader(cfg),storage,cfg,'2026-10',now=now,source='Local')
    cold=time.monotonic()-started
    started=time.monotonic()
    for _ in range(10):assert service.report(HistoryReader(cfg),storage,cfg,'2026-10',now=now,source='Local')['cache_hit']
    cached=time.monotonic()-started
    last_path=sorted(storage.paths['inverter_logs'].glob('*.csv'))[-1]
    with last_path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        for row in reader:last=row
        fields=reader.fieldnames
    last['time']=(stamp(last['time'])+timedelta(seconds=5)).isoformat()
    with last_path.open('a',encoding='utf-8',newline='') as stream:csv.DictWriter(stream,fields).writerow(last)
    started=time.monotonic()
    appended=service.report(HistoryReader(cfg),storage,cfg,'2026-10',now=now,source='Local')
    append=time.monotonic()-started
    assert appended['input_count']==first['input_count']+1
    performance_result=dict(algorithm=first['algorithm'],cold_s=cold,cached_10_s=cached,append_s=append,
        first_count=first['input_count'],appended_count=appended['input_count'],incremental=appended.get('incremental',False),
        reused_input_count=appended.get('reused_input_count',0),first=first,appended=appended)
