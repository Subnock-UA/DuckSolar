"""Persistent bounded event history and transition detection independent of UI."""
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from uuid import uuid4


class EventJournal:
    def __init__(self,path):
        self.path=path;self.lock=threading.RLock();self.rows=deque(maxlen=2000)
        try:
            with path.open('r',encoding='utf-8') as stream:
                for line in stream:
                    try:self.rows.append(json.loads(line))
                    except ValueError:pass
        except OSError:pass

    def add(self,code,message,device_id='',**details):
        row=dict(id=uuid4().hex,time=datetime.now(timezone.utc).isoformat(),code=code,
                 message=message,device_id=device_id,**details)
        with self.lock:
            self.rows.append(row);self.path.parent.mkdir(parents=True,exist_ok=True)
            if self.path.exists() and self.path.stat().st_size>2*1024*1024:
                temp=self.path.with_suffix('.tmp')
                temp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in self.rows),encoding='utf-8');temp.replace(self.path)
            else:
                with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        return row

    def recent(self,grants=None,limit=500,profiles=None):
        with self.lock:rows=[dict(x) for x in self.rows if grants is None or x['device_id'] in grants][-limit:]
        from .event_codes import decode_warnings
        for row in rows:
            if not row.get('code','').startswith('warnings.pi30.qpiws.'):continue
            position=row.get('position')
            if type(position) is not int or not 1<=position<=32:continue
            confirmed=bool((profiles or {}).get(row.get('device_id')))
            decoded=decode_warnings('0'*(position-1)+'1'+'0'*(32-position),confirmed)
            item=decoded['events'][0]
            if item['confidence']=='unknown':continue
            row['original_message']=row.get('message','');row['original_confidence']=row.get('confidence','')
            if not confirmed and row.get('confidence') in ('user_confirmed','verified_current_device'):item['confidence']=row['confidence'];item['source']=row.get('source',item['source'])
            row.update(message='Інвертор: '+('знято — ' if row.get('transition')=='cleared' else '')+item['display'],confidence=item['confidence'],source=item['source'])
        return rows


class Transitions:
    def __init__(self,journal,clock=time.monotonic):
        self.journal=journal;self.previous={};self.outages={};self.clock=clock
        self.warning_previous={}
    def change(self,device,key,value,text):
        ident=(device,key);old=self.previous.get(ident)
        self.previous[ident]=value
        if old is not None and old!=value:self.journal.add(key,text,device)
    def observe(self,device,state):
        statuses=state.get('statuses',{})
        for key,label in [('LWIP','Datalogger'),('Inverter','Інвертор')]:
            val=bool(statuses.get(key));ident=(device,key);now=self.clock()
            old=self.previous.get(ident);self.previous[ident]=val
            if not val:
                if ident not in self.outages:self.outages[ident]=[now,False]
                if old is True:self.journal.add('connection.raw.'+key,label+': зв’язок втрачено',device,notify=False)
                outage=self.outages[ident]
                if not outage[1] and now-outage[0]>30:
                    outage[1]=True
                    self.journal.add('connection.'+key,label+': зв’язок відсутній понад 30 секунд',device,notify=True,outage_s=round(now-outage[0],1))
            else:
                outage=self.outages.pop(ident,None)
                if old is False:
                    self.journal.add('connection.'+key,label+': зв’язок відновлено',device,notify=bool(outage and outage[1]))
        if state.get('stale'):return
        grid_state=state.get('normalized',{}).get('grid',{})
        grid=grid_state.get('voltage_present',grid_state.get('available'))
        if isinstance(grid,bool):self.change(device,'grid',grid,'Мережа: '+('живлення відновлено' if grid else 'живлення відсутнє'))
        warning=str(state.get('warnings') or '')
        from .event_codes import decode_warnings
        decoded=decode_warnings(warning,state.get('descriptor',{}).get('profile_confirmed',False))
        if not decoded['valid']:return
        current={item['id']:item for item in decoded['events']}
        previous=self.warning_previous.get(device,{})
        initial=device not in self.warning_previous
        for ident,item in current.items():
            if ident not in previous:
                self.journal.add('warnings.'+ident,'Інвертор: '+item['display'],device,
                    transition='observed' if initial else 'raised',raw=warning,
                    position=item['position'],confidence=item['confidence'],source=item['source'])
        for ident,item in previous.items():
            if ident not in current:
                self.journal.add('warnings.'+ident,'Інвертор: знято — '+item['display'],device,
                    transition='cleared',raw=warning,position=item['position'],
                    confidence=item['confidence'],source=item['source'])
        self.warning_previous[device]=current
