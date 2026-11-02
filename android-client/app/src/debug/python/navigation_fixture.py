import client_feature_fixture as base
import android_client as c
def install():
 base.install(.15)
 c._graph_job={'state':'idle'}
 api=c._api;old=api.call
 def call(domain,method,*args,**kwargs):
  if method=='query_status':return {'done':1,'total':1}
  if method=='graph_data':
   from datetime import datetime,timedelta
   c._api.calls+=1
   period,anchor,source=args
   if c._api.cancelled.wait(c._api.delay):raise ValueError('Fixture graph cancelled')
   fields=kwargs['fields'] if period in ('day','month') else ['pv_w','output_w']
   bars=period in ('year','all') or kwargs.get('mode')=='energy';start=datetime(2026,10,1)
   points=[dict(x=i if bars else (start+timedelta(minutes=i*5)).timestamp()*1000,label=f'2026-10-{i+1:02d}' if bars else f'01.10 00:{i*5:02d}:00',breaks=[],**{k:None if i==2 else float(i*10+20) for k in fields}) for i in range(4)]
   result=dict(contract='ducksolar.graph.v1',mode='energy' if bars else 'power',period=period,anchor=anchor.isoformat(),source=source,kind='bars' if bars else 'line',records=4,reduced=False,points=points,fields=[dict(key=k,label=k,unit='кВт·год' if bars else 'Вт') for k in fields])
   if bars or ('pv_w' in fields and 'output_w' in fields):result['energy_summary']=dict(unit='кВт·год',**{k:dict(kwh=v,partial=True) for k,v in [('generation',12.25),('consumption',8.5),('export',2.0),('import',3.5),('balance',-1.5)]})
   return result
  if method!='month_compact':return old(domain,method,*args,**kwargs)
  result=old(domain,method,*args,**kwargs);source=kwargs['source'];month=args[0].strftime('%Y-%m')
  result.update(history_source=source,quality_note='Ізольований тест графіка',days=[{'date':month+'-01','pv':{'kwh':2.5,'coverage_pct':50,'estimated_pct':50},'inverter_import':{'kwh':1.5,'coverage_pct':50,'estimated_pct':50},'inverter_export':{'kwh':None,'coverage_pct':0,'missing_pct':100}}])
  result['diagnostics'].update(selected_files=1,available_files_by_source={'Local':0,'SmartESS':1})
  return result
 api.call=call
 from async_fixture import wrap
 wrap(api)
 return True
def delay(value):c._api.delay=value;return True
def calls():return c._api.calls
def restore():return base.restore()
