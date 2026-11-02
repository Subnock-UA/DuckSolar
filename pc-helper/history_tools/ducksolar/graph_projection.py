"""Bounded graph points, retaining peaks and explicit discontinuities."""
import math
from .energy_accounting import stamp,seconds
FIELDS={
 'pv_w':('PV','Вт'),'output_w':('Навантаження','Вт'),'output_va':('Вихідна повна потужність','ВА'),
 'battery_v':('Напруга АКБ','В'),'battery_pct':('Заряд АКБ','%'),'charge_a':('Струм заряду','А'),'discharge_a':('Струм розряду','А'),
 'grid_v':('Напруга мережі','В'),'grid_hz':('Частота мережі','Гц'),'grid_import_w':('Імпорт','Вт'),'grid_export_w':('Експорт','Вт'),
 'pv_v':('Напруга PV','В'),'pv_a':('Струм PV','А'),'output_v':('Вихідна напруга','В'),'output_hz':('Вихідна частота','Гц'),
 'load_pct':('Навантаження','%'),'temperature_c':('Температура','°C'),'battery_charge_w':('Заряд АКБ','Вт')}
def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def project(rows,fields,maximum=2000,month=False,max_gap=900):
 if not isinstance(fields,list) or not 1<=len(fields)<=18 or len(set(fields))!=len(fields) or any(k not in FIELDS for k in fields):raise ValueError('Invalid graph fields')
 if not isinstance(maximum,int) or not 100<=maximum<=2000:raise ValueError('Invalid graph budget')
 times=[stamp(r['timestamp']) for r in rows]
 epochs=[t.timestamp() for t in times]
 deltas=sorted(dt for a,b in zip(epochs,epochs[1:]) if 0<(dt:=b-a)<=max_gap)
 gap=10800 if month else min(max_gap,max(12,deltas[(len(deltas)-1)//4]*2)) if deltas else max_gap
 if len(rows)<=maximum:indices=list(range(len(rows)))
 else:
  # Each bucket contributes first/last and each selected metric's min/max.
  capacity=2+2*len(fields);buckets=max(1,maximum//capacity);indices=[]
  for b in range(buckets):
   start=b*len(rows)//buckets;end=(b+1)*len(rows)//buckets;chosen={start,end-1}
   for k in fields:
    valid=[i for i in range(start,end) if number(rows[i].get(k))]
    if valid:chosen.update((min(valid,key=lambda i:rows[i][k]),max(valid,key=lambda i:rows[i][k])))
   indices.extend(sorted(chosen))
 output=[];previous=-1
 for i in indices:
  row=rows[i];broken=set()
  for j in range(max(0,previous),i+1):
   r=rows[j]
   if r.get('_gap') or j>0 and epochs[j]-epochs[j-1]>gap:broken.update(fields)
   for k in fields:
    if not number(r.get(k)):broken.add(k)
    if j>0 and k in ('grid_import_w','grid_export_w'):
     prefix=k[:-1]
     if tuple(r.get(prefix+x) for x in ('source','origin'))!=tuple(rows[j-1].get(prefix+x) for x in ('source','origin')):broken.add(k)
  label=times[i].strftime('%d.%m %H:%M:%S')
  if times[i].replace(fold=0).utcoffset()!=times[i].replace(fold=1).utcoffset():label+=' '+times[i].strftime('%z')
  p={'x':epochs[i]*1000,'label':label,'breaks':sorted(broken)}
  p.update({k:float(row[k]) if number(row.get(k)) else None for k in fields})
  for direction in ('import','export'):
   for suffix in ('source','origin','reason'):
    key='grid_'+direction+'_'+suffix
    if key in row:p[key]=row[key]
  output.append(p);previous=i
 return dict(points=output,records=len(rows),gap_s=gap,reduced=len(rows)>len(output))
