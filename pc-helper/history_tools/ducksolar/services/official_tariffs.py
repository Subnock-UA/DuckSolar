"""Document-derived effective dates, commissioning bands and protected overrides."""
import html,json,re,threading,urllib.request
from dataclasses import dataclass,asdict
from datetime import date,datetime,timedelta
CURRENT_OFFICIAL_URL='https://www.nerc.gov.ua/acts/pro-vstanovlennia-zelenykh-taryfiv-na-elektrychnu-enerhiiu-vyroblenu-heneruiuchymy-ustanovkamy-pryvatnykh-domohospodarstv-2'
MONTHS={n:i+1 for i,n in enumerate('січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня'.split())}
UA_DATE=r'(\d{1,2})\s+('+('|'.join(MONTHS))+r')\s+(\d{4})\s*(?:року|р\.)?'
def _date(g):return date(int(g[2]),MONTHS[g[1].lower()],int(g[0]))
@dataclass
class TariffUpdate:
    changed:bool
    effective_from:str
    rate_uah:float
    resolution_number:str
    resolution_date:str
    source_url:str
    manual_override:bool=False
class TariffService:
    def __init__(self,cfg,storage):self.cfg=cfg;self.storage=storage;self.lock=threading.Lock()
    def status(self):
        try:return json.loads(self.storage.get_app_state('official_tariff_status','{}'))
        except ValueError:return {}
    def history(self):
        with self.storage._db_lock,self.storage._connect() as con:
            cur=con.execute('SELECT effective_from,uah_per_kwh,source,resolution_number,resolution_date,downloaded_at,user_override FROM tariff_history ORDER BY effective_from')
            return [dict(zip([c[0] for c in cur.description],row)) for row in cur]
    def parse(self,raw):
        text=html.unescape(raw.decode('utf-8') if isinstance(raw,bytes) else raw)
        text=re.sub(r'<[^>]+>',' ',text);text=re.sub(r'\s+',' ',text)
        resolution=re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s*№\s*(\d+)',text)
        if not resolution:raise ValueError('Не визначено дату та номер постанови НКРЕКП')
        rd=date(int(resolution[3]),int(resolution[2]),int(resolution[1]))
        effective=re.search(r'набирає чинності з\s+'+UA_DATE,text,re.I)
        if not effective:raise ValueError('Не визначено дату чинності постанови')
        effective=_date(effective.groups())
        if 'не раніше' in text:
            published=re.search(r'День оприлюднення[^:]*:\s*(\d{2})\.(\d{2})\.(\d{4})',text,re.I)
            if not published:raise ValueError('Не визначено дату оприлюднення постанови')
            effective=max(effective,date(int(published[3]),int(published[2]),int(published[1]))+timedelta(days=1))
        section=re.search(r'1\.\s*Установити.*?(?=2\.\s*Установити)',text,re.I)
        if not section or float(self.cfg.pv_installed_kw)>30:raise ValueError('Потрібна перевірка категорії установки для цього тарифу')
        pattern=r'з\s+'+UA_DATE+r'\s+по\s+'+UA_DATE+r'\s*[–—-]\s*([\d]+[,.][\d]+)\s*коп/кВт'
        bands=[(_date(m.groups()[:3]),_date(m.groups()[3:6]),float(m[7].replace(',','.'))/100) for m in re.finditer(pattern,section.group(),re.I)]
        configured=getattr(self.cfg,'green_tariff_commissioning_date','')
        if configured:
            commissioned=date.fromisoformat(configured);matches=[b for b in bands if b[0]<=commissioned<=b[1]]
        else:
            year=int(self.cfg.green_tariff_commissioning_year)
            matches=[b for b in bands if b[0]<=date(year,1,1) and date(year,12,31)<=b[1]]
        if len(matches)!=1:raise ValueError('Для вибору ставки вкажіть точну дату введення СЕС в експлуатацію')
        return effective.isoformat(),matches[0][2],resolution[4],rd.isoformat()
    def check_for_updates(self):
        with self.lock:
            try:
                req=urllib.request.Request(CURRENT_OFFICIAL_URL,headers={'User-Agent':'DuckSolar/a1.4.29'})
                with urllib.request.urlopen(req,timeout=15) as response:
                    if response.status!=200:raise RuntimeError('НКРЕКП HTTP '+str(response.status))
                    if not response.geturl().startswith('https://www.nerc.gov.ua/'):raise ValueError('Неочікуване джерело тарифу')
                    raw=response.read(2_000_001)
                if len(raw)>2_000_000:raise ValueError('Документ НКРЕКП завеликий')
                effective,rate,number,rd=self.parse(raw)
                with self.storage._db_lock:
                    old=self.storage.tariff_for_date(effective);manual=bool(old and old.get('user_override'))
                    changed=not manual and (not old or old['effective_from']!=effective or abs(old['uah_per_kwh']-rate)>1e-9)
                    if changed:self.storage.upsert_tariff(effective,rate,'official',number,rd,False)
                result=TariffUpdate(changed,effective,rate,number,rd,CURRENT_OFFICIAL_URL,manual)
                self.storage.set_app_state('official_tariff_status',json.dumps(dict(asdict(result),state='ready',checked_at=datetime.now().isoformat()),ensure_ascii=False))
                return result
            except Exception as error:
                state=self.status();state.update(state='error',error=str(error),exception_class=type(error).__name__,checked_at=datetime.now().isoformat())
                self.storage.set_app_state('official_tariff_status',json.dumps(state,ensure_ascii=False));raise
