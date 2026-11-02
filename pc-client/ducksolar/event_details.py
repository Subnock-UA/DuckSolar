"""Bounded journal episodes, with explicit unknown initial boundary."""
from datetime import datetime

def enrich(rows, active=None):
    current_known=active is not None;active=set(active or ());opened={};out=[]
    for raw in rows:
        row=dict(raw);key=(row.get('device_id'),row.get('code'))
        transition=row.get('transition')
        if str(row.get('code','')).startswith('warnings.'):
            if transition in ('raised','observed'):
                opened[key]=(row.get('time'),transition=='raised')
            begin,known=opened.get(key,(None,False))
            end=row.get('time') if transition=='cleared' else None
            duration=None
            if begin and end:
                try:duration=max(0,(datetime.fromisoformat(end)-datetime.fromisoformat(begin)).total_seconds())
                except (ValueError,TypeError):pass
            row['event_detail']=dict(first_seen=begin,last_seen=row.get('time'),ended=end,duration_s=duration,start_confirmed=known,status='Завершена' if end else 'Активність підтверджена поточним станом' if key in active else 'Не активна; час завершення не отримано' if current_known else 'Стан на момент запису; поточний стан невідомий')
            if end:opened.pop(key,None)
        out.append(row)
    return out
