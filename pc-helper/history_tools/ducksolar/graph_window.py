"""An optional local-clock window within one calendar day."""
from datetime import datetime,timedelta,timezone
from .energy_accounting import ZONE,stamp,number

def bounds(period,anchor,start,end):
 if start is None and end is None:return None
 if period!='day' or not isinstance(start,str) or not isinstance(end,str):raise ValueError('Часовий проміжок доступний лише для дня')
 def instant(text):
  if text=='24:00':return datetime(anchor.year,anchor.month,anchor.day,tzinfo=ZONE)+timedelta(days=1)
  if len(text)!=5 or text[2]!=':':raise ValueError('Вкажіть час ГГ:ХХ')
  try:h,m=map(int,text.split(':'));naive=datetime(anchor.year,anchor.month,anchor.day,h,m)
  except ValueError:raise ValueError('Некоректний час')
  a=naive.replace(tzinfo=ZONE,fold=0);b=naive.replace(tzinfo=ZONE,fold=1)
  if a.utcoffset()!=b.utcoffset() or a.astimezone(timezone.utc).astimezone(ZONE).replace(tzinfo=None)!=naive:raise ValueError('Неоднозначний або відсутній час переходу годинника; оберіть іншу межу')
  return a
 a,b=instant(start),instant(end)
 if start=='24:00' or b.timestamp()<=a.timestamp():raise ValueError('Кінець проміжку має бути після початку')
 return a,b

def clip(rows,start,end,max_gap):
 # Only interpolate a continuous numeric segment; missing values and source
 # changes remain missing/broken. Accounting always uses original input rows.
 a,b=start.timestamp(),end.timestamp();out=[]
 times=[stamp(r['timestamp']).timestamp() for r in rows]
 def edge(t):
  import bisect
  i=bisect.bisect_left(times,t)
  if i<len(rows) and times[i]==t:return dict(rows[i])
  if not 0<i<len(rows) or not 0<times[i]-times[i-1]<=max_gap:return None
  left,right=rows[i-1],rows[i];f=(t-times[i-1])/(times[i]-times[i-1]);r={'timestamp':datetime.fromtimestamp(t,ZONE)}
  for k in left.keys()|right.keys():
   if k=='timestamp':continue
   x,y=left.get(k),right.get(k)
   if k in ('grid_import_w','grid_export_w'):
    pre=k[:-1]
    if any(left.get(pre+s)!=right.get(pre+s) for s in ('source','origin')):r[k]=None;continue
   if number(x) and number(y):r[k]=x+(y-x)*f
   elif x==y:r[k]=x
  return r
 first,last=edge(a),edge(b)
 if first is not None:out.append(first)
 out.extend(r for r,t in zip(rows,times) if a<t<b)
 if last is not None:out.append(last)
 return out
