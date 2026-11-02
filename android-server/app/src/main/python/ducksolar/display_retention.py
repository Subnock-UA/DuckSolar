"""Live-only auxiliary readings; never used for historical integration."""
import copy,time,threading
from datetime import datetime,timezone

class DisplayRetention:
    def __init__(self,clock=time.monotonic):self.clock=clock;self.connection=None;self.values={};self.lock=threading.RLock()
    @staticmethod
    def lifetime(key):
        return 90 if key.startswith(('temperature.','dc.','device.','inverter.')) or key in ('battery.scc_voltage','output.apparent_power','output.load_percent') else 15
    def update(self,metrics,connection,instant):
        with self.lock:return self._update(metrics,connection,instant)
    def _update(self,metrics,connection,instant):
        if connection!=self.connection:self.values.clear();self.connection=connection
        now=self.clock()
        for key,item in metrics.items():
            if item.get('value') is not None and not item.get('stale') and item.get('quality','good') not in ('unavailable','invalid','inconsistent'):
                entry=copy.deepcopy(item);entry.setdefault('timestamp',instant.isoformat());entry['valid_for_s']=self.lifetime(key)
                try:age=max(0,instant.timestamp()-datetime.fromisoformat(entry['timestamp']).timestamp())
                except (ValueError,TypeError):age=0
                self.values[key]=(now-age,entry)
            elif item.get('invalidated') or item.get('quality') in ('invalid','inconsistent'):
                self.values.pop(key,None)
    def apply(self,metrics,connection,online):
        with self.lock:return self._apply(metrics,connection,online)
    def _apply(self,metrics,connection,online):
        out=copy.deepcopy(metrics);now=self.clock()
        if connection!=self.connection or not online:
            self.values.clear();self.connection=connection
            for item in out.values():item.update(stale=True,unavailable_reason='Немає актуального зв’язку з інвертором')
            return out
        for key,(received,saved) in list(self.values.items()):
            age=max(0,now-received);current=out.get(key,{})
            if age>saved['valid_for_s']:
                if current.get('value') is None:out[key]=dict(saved,value=None,quality='unavailable',stale=True,unavailable_reason='Минув строк актуальності виміру',age_s=round(age,1))
                continue
            if current.get('value') is None and current.get('quality') not in ('invalid','inconsistent'):
                out[key]=dict(saved,display_retained=True,age_s=round(age,1))
            elif current.get('value') is not None:
                # Snapshot cadence cannot refresh actual acquisition time.
                out[key]=dict(current,timestamp=saved['timestamp'],valid_for_s=saved['valid_for_s'],age_s=round(age,1))
        return out
