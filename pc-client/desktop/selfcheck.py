import json,tempfile,time,traceback,sys,unittest,hashlib,ast
from pathlib import Path
from unittest.mock import patch

def run(destination):
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);report=dict(version='b2.0.0',frozen=getattr(sys,'frozen',False),passed=False)
 try:
  from .model import valid,metric_text,with_currents,validate_parameter
  from .settings import save_connection,load_connection,migrate_legacy
  from ducksolar.credential_store import protect
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);save_connection(root,dict(token='test-secret-token',password='never-save',username='test'))
   raw=(root/'connection.json').read_text();assert 'test-secret-token' not in raw and 'never-save' not in raw;assert load_connection(root,{})['token']=='test-secret-token';report['DPAPI']='passed'
   old=root/'legacy';old.mkdir();legacy=dict(auth_token=protect('legacy-token'),server_url='https://127.0.0.1:8765',server_fingerprint='oldpin',account_username='test',client_id='b'*32,dtu_pn='serial',connection_mode='lan');file=old/'config.json';file.write_text(json.dumps(legacy));before=file.read_bytes();assert migrate_legacy(root/'migrated',old);assert file.read_bytes()==before;assert load_connection(root/'migrated',{})['token']=='legacy-token';report['legacy_preserved']='passed'
  m=lambda v,u,**kw:dict(value=v,unit=u,quality='good',**kw)
  metrics={'pv.total_power':m(1600,'W'),'pv.inputs.aggregate.voltage':m(320,'V'),'pv.inputs.aggregate.current':m(2,'A',stale=True),'output.active_power':m(460,'W'),'output.apparent_power':m(575,'VA'),'output.phases.L1.voltage':m(230,'V')}
  v=with_currents(metrics);assert v['pv.inputs.aggregate.current']['value']==5;assert v['output.phases.L1.current']['value']==2.5;assert metric_text(m(0,'A'))=='0 А';assert metric_text(m(9,'A',stale=True))=='—';assert metric_text(m(9,'A',age_s=20,valid_for_s=10))=='—';assert 'НП' not in metric_text(m('НП',''))
  metrics['pv.inputs.mppt1.voltage']=m(320,'V');assert with_currents(metrics)['pv.inputs.aggregate.current']['value']==2
  for bad in ['nan','90']:
   try:validate_parameter(dict(writable=True,present=True,write_rule=dict(minimum=0,maximum=80)),bad);raise AssertionError('Invalid parameter accepted')
   except ValueError:pass
  report['freshness_zero_fallbacks_parameter_guards']='passed'
  from .app import App
  from .fixtures import FixtureController,envelope,graph
  from .pages import ENTRIES
  with tempfile.TemporaryDirectory() as tmp:
   ctrl=FixtureController(tmp);app=App(ctrl,fixture=True);errors=[];app.report_callback_exception=lambda *exc:errors.append(''.join(traceback.format_exception(*exc)))
   def pump(seconds=.15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.update();time.sleep(.015)
   app.render_live(envelope());pump()
   discharge=envelope();discharge['state']['normalized']['metrics']['battery.channels.main.charge_current']['value']=0;discharge['state']['normalized']['metrics']['battery.channels.main.discharge_current']['value']=5;app.render_live(discharge)
   assert any(__import__('ducksolar.ui_language',fromlist=['text']).text('↓ 5 А') in app.flow.itemcget(item,'text') for item in app.flow.find_all() if app.flow.type(item)=='text')
   app.render_live(envelope());app.book.select(app.pages['Моніторинг']);pump();app.render_live(envelope());assert app.monitor.rows
   for title,key,method in ENTRIES:app.open_page(key);pump(.10)
   pump(.35);assert not errors,errors
   app.book.select(app.pages['Графіки']);app.render_graph(graph());pump();assert app.graph_plot.axes[0].lines
   app.render_graph(graph('energy','year'));pump();assert app.graph_plot.categorical;assert app.graph_plot.axes[0].patches
   ctrl.jobs['graph_status']=dict(state='complete',result=graph());ctrl.jobs['balance_status']=dict(state='complete',result=dict(month='2026-10'));app.set_watch('graph',app.render_graph);app.set_watch('balance',lambda value:None);app.tick();pump(.2);assert not app.watches
   app.graph_plot.figure.savefig(destination/'GRAPH_ENERGY.png',dpi=100)
   app.book.select(app.pages['Головна']);app.render_live(envelope());app.show_widget();pump();assert app.widget_canvas.find_all();app.widget.destroy();app.widget=None
   app.open_page('battery');pump();app.book.select(app.pages['Додатково']);pump()
   if not getattr(sys,'frozen',False):
    try:
     from .windows import capture_window
     app.update();capture_window(app,destination/'DESKTOP_BATTERY.png')
     app.book.select(app.pages['Головна']);pump();capture_window(app,destination/'DESKTOP_HOME.png')
    except Exception as exc:report['screenshot_note']=str(exc)
   app.open_page('connection');pump();assert not errors,errors;report['desktop_pages']=len(ENTRIES);report['graphs_zoom_units_energy_widget']='passed';report['no_live_mutations']=not any(name in ('submit_parameter','add_meter_reading','feature.battery_anchor','feature.apply_profile') for name,args in ctrl.calls)
   assert report['no_live_mutations'];app.shutdown()
  # Exercise the actual Python adapter, not just a prebuilt Plot fixture.
  import desktop_client as adapter,copy
  source=dict(kind='forecast',forecast_analysis_version=4,graph=dict(kind='bars',mode='energy',fields=[dict(key='actual',label='Факт',unit='кВт·год'),dict(key='forecast',label='Прогноз',unit='кВт·год')],points=[dict(x=0,label='2026-11-01T10:00:00+02:00',actual=1.7,forecast=2)]))
  class InlineThread:
   def __init__(self,target,**kwargs):self.target=target
   def start(self):self.target()
  saved=(adapter._api,adapter._feature_active,adapter._feature_state)
  try:
   adapter._api=object();adapter._feature_active=False
   with patch.object(adapter,'connection_profile',return_value='isolated-self-check'),patch.object(adapter,'_history_job',return_value=copy.deepcopy(source)),patch.object(adapter,'weather_status',side_effect=AssertionError('Unexpected legacy conversion')),patch.object(adapter.threading,'Thread',InlineThread),patch.object(adapter,'_note'):
    value=json.loads(adapter.feature_start('forecast','2026-11-01'))
   assert value['state']=='complete',value
   assert value['result']==source,value
   report['forecast_adapter_v4']='passed'
  finally:adapter._api,adapter._feature_active,adapter._feature_state=saved
  report['passed']=True
 except Exception:report['error']=traceback.format_exc()
 (destination/'SELF_CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False));return 0 if report['passed'] else 1
