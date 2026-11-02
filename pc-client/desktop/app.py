from ducksolar import ui_language as L
from ducksolar import tk_language
import json,math,queue,time,threading,sys,os,logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,colorchooser
from datetime import datetime,date
from .widgets import Scroll,DateInput,Table,Plot,Results,BG,INK,MUTED,ACCENT,COLORS
from .model import *
from .settings import atomic

class Flow(tk.Canvas):
 def __init__(self,parent):
  super().__init__(parent,height=355,bg='white',highlightthickness=0);self.metrics={};self.stale=True;self.model="—";self.phase=0.;self.equipment=[]
  from PIL import Image,ImageTk
  sprite=Image.open(Path(__file__).resolve().parents[1]/'assets/station_equipment.png')
  for left,right in [(0,.23),(.235,.39),(.40,.64),(.65,.79),(.83,.98)]:
   icon=sprite.crop((int(sprite.width*left),int(sprite.height*.12),int(sprite.width*right),int(sprite.height*.83)));icon.thumbnail((46,52));self.equipment.append(ImageTk.PhotoImage(icon))
  self.bind('<Configure>',lambda e:self.draw());self.after(120,self.animate)
 def update_state(self,metrics,stale,model="—"):self.metrics=metrics;self.stale=stale;self.model=model;self.draw()
 def animate(self):
  self.phase=(self.phase+.0132)%1
  if self.winfo_ismapped():self.draw()
  self.after(120,self.animate)
 def draw(self):
  self.delete('all');w=max(750,self.winfo_width());h=355;cx=w/2;cy=h/2
  nodes=[('PV','pv.total_power','pv.inputs.aggregate.voltage','pv.inputs.aggregate.current',cx,52,'#d79d13'),('Мережа','grid.import_power','grid.phases.L1.voltage','grid.phases.L1.current',130,cy,'#2385cb'),('Навантаження','output.active_power','output.phases.L1.voltage','output.phases.L1.current',w-130,cy,'#2a9d72'),('АКБ','battery.channels.main.soc','battery.channels.main.voltage','battery.channels.main.discharge_current',cx,h-53,'#9462ca')]
  for title,key,u,a,x,y,color in nodes:
   source=(x,y+40) if title=='PV' else (x+102,y) if title=='Мережа' else (x-102,y) if title=='Навантаження' else (x,y-40)
   end=(cx,cy-38) if title=='PV' else (cx-72,cy) if title=='Мережа' else (cx+72,cy) if title=='Навантаження' else (cx,cy+38)
   number_value=self.metrics.get(key,{}).get('value');active=valid(self.metrics.get(key),self.stale) and number(number_value) and number_value>(20 if title=='PV' else 0)
   if title=='АКБ':active=any(valid(self.metrics.get('battery.channels.main.'+d+'_current'),self.stale) and (self.metrics.get('battery.channels.main.'+d+'_current',{}).get('value') or 0)>0 for d in ['charge','discharge'])
   if title=='Мережа':active=any(valid(self.metrics.get('grid.'+d+'_power'),self.stale) and (self.metrics.get('grid.'+d+'_power',{}).get('value') or 0)>0 for d in ('import','export'))
   reverse=title=='Навантаження' or title=='АКБ' and (self.metrics.get('battery.channels.main.charge_current',{}).get('value') or 0)>0 or title=='Мережа' and (self.metrics.get('grid.export_power',{}).get('value') or 0)>0
   start,finish=(end,source) if reverse else (source,end)
   self.create_line(*start,*finish,fill=color if active else '#d9e3eb',width=3,smooth=True,capstyle=tk.ROUND)
   if active:
    rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
    for step in range(100):
     t=(step+.5)/100;distance=(t-self.phase)%1
     light=math.sin(distance/.32*math.pi)*.85 if distance<.32 else 0
     if light<=0:continue
     shade='#'+''.join(f'{round(v+(255-v)*light):02x}' for v in rgb)
     x1=start[0]+(finish[0]-start[0])*step/100;y1=start[1]+(finish[1]-start[1])*step/100
     x2=start[0]+(finish[0]-start[0])*(step+1)/100;y2=start[1]+(finish[1]-start[1])*(step+1)/100
     self.create_line(x1,y1,x2,y2,fill=shade,width=3)
   self.create_rectangle(x-104,y-39,x+104,y+39,fill='#f6f9fc',outline='#e2e9ef',width=1)
   self.create_image(x-78,y,image=self.equipment[{'PV':0,'Мережа':4,'Навантаження':2,'АКБ':3}[title]])
   self.create_text(x+18,y-22,text=title,fill=color,font=('Segoe UI Semibold',11))
   value=home_metric_text(self.metrics.get(key),self.stale)
   if title=='Мережа' and valid(self.metrics.get('grid.export_power'),self.stale) and (self.metrics['grid.export_power']['value'] or 0)>0:value='Експорт '+home_metric_text(self.metrics['grid.export_power'],self.stale)
   self.create_text(x+18,y,text=value,fill=INK,font=('Segoe UI Semibold',16));current_key='battery.channels.main.charge_current' if title=='АКБ' and (self.metrics.get('battery.channels.main.charge_current',{}).get('value') or 0)>0 else a
   self.create_text(x+18,y+24,text=home_metric_text(self.metrics.get(u),self.stale)+'  ·  '+(('↑ ' if current_key=='battery.channels.main.charge_current' else '↓ ') if title=='АКБ' else '')+home_metric_text(self.metrics.get(current_key),self.stale),fill=MUTED,font=('Segoe UI',10))
  self.create_image(cx,cy,image=self.equipment[1]);self.create_text(cx,cy+44,text=self.model,fill=MUTED,font=('Segoe UI',9))

class App(tk.Tk):
 def __init__(self,controller,fixture=False):
  L.configure(controller.root);tk_language.install()
  super().__init__();self.controller=controller;self.fixture=fixture;self.title('Duck Solar · ПК b2.0.0');self.geometry('1330x900');self.minsize(1024,700);self.configure(bg=BG)
  self.root_path=controller.root;self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='DesktopUI');self.events=queue.Queue();self.pending=set();self.stop_flag=False;self.page_generation=0;self.current='Головна';self.watch=None;self.watches={};self.last_result=None;self.widget=None;self.tray=None;self.graph_plot=None;self.monitor_signature='';self.latest={}
  self.options_path=self.root_path/'desktop.json'
  try:self.options=json.loads(self.options_path.read_text())
  except (OSError,ValueError):self.options={}
  style=ttk.Style(self);style.theme_use('clam');style.configure('.',font=('Segoe UI',10),foreground=INK);style.configure('TFrame',background=BG);style.configure('TLabel',background=BG);style.configure('TButton',padding=(12,8),background='#e2edf3',borderwidth=0);style.map('TButton',background=[('active','#cbe4e9')]);style.configure('Heading.TLabel',font=('Segoe UI Semibold',19));style.configure('Summary.TLabel',font=('Segoe UI Semibold',11),foreground=ACCENT);style.configure('Treeview',rowheight=29,font=('Segoe UI',10));style.configure('Treeview.Heading',font=('Segoe UI Semibold',10));style.configure('TNotebook.Tab',padding=(28,12),font=('Segoe UI Semibold',12),borderwidth=0);style.map('TNotebook.Tab',background=[('selected','white'),('!selected','#e1ebf1')],padding=[('selected',(28,12)),('!selected',(28,12))]);style.configure('TLabelframe',background='white',bordercolor='#dce7ee');style.configure('TLabelframe.Label',background='white',foreground=ACCENT,font=('Segoe UI Semibold',11));style.configure('Card.TLabel',background='white',padding=6)
  try:self.iconbitmap(str(Path(__file__).resolve().parents[1]/'assets/duck_solar.ico'))
  except tk.TclError:pass
  header=ttk.Frame(self,padding=(18,10));header.pack(fill='x');ttk.Label(header,text='Duck Solar',style='Heading.TLabel').pack(side='left');tk_language.selector(header,self).pack(side='left',padx=16);self.connection=tk.StringVar(value='Немає підключення');ttk.Label(header,textvariable=self.connection).pack(side='right')
  self.book=ttk.Notebook(self);self.book.pack(fill='both',expand=True,padx=14,pady=5);self.pages={}
  for title in ['Головна','Моніторинг','Графіки','Додатково']:
   frame=ttk.Frame(self.book);self.pages[title]=frame;self.book.add(frame,text=title)
  self.book.bind('<<NotebookTabChanged>>',self.tab_changed)
  self.build_home();self.monitor=Table(self.pages['Моніторинг'],columns=['Блок','Показник','Значення','Джерело','Якість'],height=22);self.monitor.pack(fill='both',expand=True,padx=10,pady=10)
  self.build_graphs();self.build_more();self.status=tk.StringVar(value='Готово');ttk.Label(self,textvariable=self.status,padding=(18,6)).pack(fill='x')
  self.protocol('WM_DELETE_WINDOW',self.on_close);self.bind('<Map>',lambda e:self.visible_event() if e.widget is self else None);self.bind('<Unmap>',lambda e:self.controller.set_visible(False) if e.widget is self else None)
  self.after(80,self.drain);self.after(500,self.tick)
  if not fixture:self.start_tray()
 def submit(self,key,work,done=None,mutating=False):
  if key in self.pending or mutating and 'mutation' in self.pending:self.status.set('Попередній запит ще виконується');return
  self.pending.add(key)
  if mutating:self.pending.add('mutation')
  generation=self.page_generation;self.status.set('Виконується…')
  def run():
   try:self.events.put(('done',key,generation,done,work(),mutating))
   except Exception as exc:self.events.put(('error',key,generation,None,str(exc),mutating));logging.exception('Desktop action failed: %s',key)
  self.pool.submit(run)
 def drain(self):
  if self.stop_flag:return
  for _ in range(50):
   try:item=self.events.get_nowait()
   except queue.Empty:break
   if item[0]=='show':self.show_window();continue
   if item[0]=='quit':self.shutdown();return
   if item[0]=='widget':self.show_widget();continue
   kind,key,generation,done,value,mutating=item;self.pending.discard(key)
   if mutating:self.pending.discard('mutation')
   if generation==self.page_generation or key.startswith(('connect','route','notification','pc.')):
    self.status.set('Готово' if kind=='done' else value)
    if kind=='done' and done:
     try:done(value)
     except Exception as exc:self.status.set(str(exc));logging.exception('Desktop rendering failed')
  self.after(80,self.drain)
 def call(self,name,*args):return self.controller.call(name,*args)
 def feature(self,method,*args):return self.controller.feature(method,*args)
 def visible_event(self):
  self.controller.set_visible(self.state()!='iconic')
 def tab_changed(self,event=None):
  self.current=next((title for title,page in self.pages.items() if str(page)==self.book.select()),'Головна')
 def build_home(self):
  area=Scroll(self.pages['Головна']);area.pack(fill='both',expand=True);ttk.Label(area.body,text='Стан станції',style='Heading.TLabel').pack(anchor='w',padx=12,pady=8);self.flow=Flow(area.body);self.flow.pack(fill='x',padx=12,pady=8)
  self.home_values={};cards=ttk.Frame(area.body);cards.pack(fill='x',padx=12,pady=10)
  for index,(key,title) in enumerate(GROUPS.items()):
   box=ttk.LabelFrame(cards,text=title,padding=14);box.grid(row=index//3,column=index%3,sticky='nsew',padx=6,pady=6);cards.columnconfigure(index%3,weight=1);var=tk.StringVar(value='—');ttk.Label(box,textvariable=var,wraplength=340,justify='left',style='Card.TLabel').pack(anchor='w');self.home_values[key]=var
  self.server_home=tk.StringVar(value='');ttk.Label(area.body,textvariable=self.server_home,padding=15,wraplength=1100).pack(fill='x')
 def build_graphs(self):
  frame=self.pages['Графіки'];controls=ttk.Frame(frame,padding=10);controls.pack(fill='x');self.graph_vars={}
  def combo(title,key,values,initial):
   ttk.Label(controls,text=title).pack(side='left',padx=(6,2));var=tk.StringVar(value=initial);box=ttk.Combobox(controls,textvariable=var,values=values,state='readonly',width=17);box.pack(side='left');self.graph_vars[key]=var;return box
  combo('Режим','mode',['Показники у часі','Енергія за період'],'Показники у часі');combo('Період','period',['День','Місяць','Рік','Весь час'],'День');combo('Джерело','source',['Auto','Local','SmartESS'],'Auto');self.graph_date=DateInput(controls);self.graph_date.pack(side='left',padx=7)
  line=ttk.Frame(frame,padding=(10,2));line.pack(fill='x');self.graph_group=tk.StringVar(value='PV і навантаження');group_box=ttk.Combobox(line,textvariable=self.graph_group,values=list(PRESETS),state='readonly',width=25);group_box.pack(side='left');group_box.bind('<<ComboboxSelected>>',lambda e:setattr(self,'graph_fields',None));ttk.Button(line,text='Показники та вигляд',command=self.graph_selection).pack(side='left',padx=5)
  self.graph_time_a=tk.StringVar(value='00:00');self.graph_time_b=tk.StringVar(value='24:00');ttk.Label(line,text='Інтервал доби').pack(side='left');ttk.Entry(line,textvariable=self.graph_time_a,width=6).pack(side='left');ttk.Label(line,text='—').pack(side='left');ttk.Entry(line,textvariable=self.graph_time_b,width=6).pack(side='left')
  ttk.Button(line,text='Побудувати',command=self.start_graph).pack(side='left',padx=5);ttk.Button(line,text='Скасувати',command=lambda:self.submit('graph.cancel',lambda:self.call('graph_cancel'))).pack(side='left');ttk.Button(line,text='CSV',command=self.export_graph).pack(side='left',padx=5)
  self.graph_auto=tk.BooleanVar(value=self.options.get('graph_auto',False));ttk.Checkbutton(line,text='Автооновлення',variable=self.graph_auto).pack(side='left');self.graph_next=0;self.graph_fields=self.options.get('graph_fields')
  saved=self.options.get('graph',{})
  for key,var in self.graph_vars.items():
   if key in saved:var.set(saved[key])
  if saved.get('group') in PRESETS:self.graph_group.set(saved['group'])
  self.graph_output=Scroll(frame);self.graph_output.pack(fill='both',expand=True,pady=5)
 def graph_selection(self):
  window=tk.Toplevel(self);window.title('Показники та вигляд');window.geometry('510x660');area=Scroll(window);area.pack(fill='both',expand=True);chosen=self.graph_fields or PRESETS[self.graph_group.get()];values={}
  for key,title in FIELDS.items():
   var=tk.BooleanVar(value=key in chosen);ttk.Checkbutton(area.body,text=title,variable=var).pack(anchor='w');values[key]=var
   ttk.Button(area.body,text='Колір',command=lambda k=key:self.set_color(k)).pack(anchor='e')
  width=tk.StringVar(value=str(self.options.get('line_width',1.6)));ttk.Label(area.body,text='Товщина ліній').pack();ttk.Spinbox(area.body,textvariable=width,from_=1,to=5,increment=.2,width=8).pack()
  def save():
   fields=[k for k,v in values.items() if v.get()]
   if not fields:messagebox.showerror('Графіки','Виберіть хоча б один показник');return
   self.graph_fields=fields;self.options['line_width']=float(width.get());self.save_options();window.destroy()
  ttk.Button(window,text='Зберегти',command=save).pack(pady=8)
 def set_color(self,key):
  color=colorchooser.askcolor(title=FIELDS.get(key,key))[1]
  if color:self.options.setdefault('colors',{})[key]=color;self.save_options()
 def start_graph(self):
  if self.watch and self.watch[0]=='graph':return
  try:
   anchor=self.graph_date.anchor();period={'День':'day','Місяць':'month','Рік':'year','Весь час':'all'}[self.graph_vars['period'].get()]
   if period=='month':anchor=anchor[:7]+'-01'
   if period=='year':anchor=anchor[:4]+'-01-01'
   mode='energy' if self.graph_vars['mode'].get()=='Енергія за період' or period in ('year','all') else 'power'
   fields=self.graph_fields or PRESETS[self.graph_group.get()]
   if mode=='energy':fields=[k for k in fields if k in ('pv_w','output_w','grid_import_w','grid_export_w')] or ['pv_w','output_w']
   a,b=(self.graph_time_a.get(),self.graph_time_b.get()) if period=='day' and (self.graph_time_a.get(),self.graph_time_b.get())!=('00:00','24:00') else ('','')
   source=self.graph_vars['source'].get();self.submit('graph.start',lambda:self.call('graph_start',period,anchor,source,json.dumps(fields),mode,a,b),lambda result:self.set_watch('graph',self.render_graph))
  except Exception as exc:self.status.set(str(exc))
 def render_graph(self,result):
  for w in self.graph_output.body.winfo_children():w.destroy()
  self.last_result=result;self.graph_plot=Plot(self.graph_output.body,result,self.options.get('colors'),self.options.get('line_width',1.6));self.graph_plot.pack(fill='both',expand=True)
  events=result.get('events') or []
  if events:ttk.Label(self.graph_output.body,text='Події цього графіка',style='Heading.TLabel').pack(anchor='w');Table(self.graph_output.body,events,height=min(8,len(events))).pack(fill='x')
  self.graph_next=time.monotonic()+60
 def export_graph(self):
  if not self.last_result:return
  table=Table(self.graph_output.body,self.last_result.get('points',[]));table.export();table.destroy()
 def build_more(self):
  frame=self.pages['Додатково'];menu=Scroll(frame);menu.pack(side='left',fill='y');menu.configure(width=245);menu.canvas.configure(width=245);self.more=Scroll(frame);self.more.pack(side='left',fill='both',expand=True);self.more_body=self.more.body
  from .pages import ENTRIES,ROOT_ENTRIES
  self.routes={}
  for title,key,method in ENTRIES:
   self.routes[key]=method
   if key in ROOT_ENTRIES:ttk.Button(menu.body,text=title,width=29,command=lambda k=key:self.open_page(k)).pack(fill='x',padx=5,pady=3)
  self.open_page('analytics')
 def open_page(self,key):
  self.page_generation+=1
  for child in self.more_body.winfo_children():child.destroy()
  self.more_key=key
  from . import pages
  getattr(pages,self.routes[key])(self,self.more_body)
  if key not in ('analytics','settings','planning'):pages.arrange(self.more_body)
 def set_watch(self,kind,render):self.watch=(kind,render);self.watches[kind]=(render,self.page_generation);self.status.set('Запит виконується на сервері…')
 def tick(self):
  if self.stop_flag:return
  value=self.controller.snapshot()
  if value:self.render_live(value)
  for kind,(render,render_generation) in list(self.watches.items()):
   def finish(result,kind=kind,render=render,render_generation=render_generation):
    state=result.get('state');self.status.set(f"{state} · {result.get('done',0)}/{result.get('total',0)} · {display(result.get('elapsed_s'),'s')}")
    if state in ('complete','completed','error','cancelled','idle'):
     self.watches.pop(kind,None);self.watch=next(((key,entry[0]) for key,entry in self.watches.items()),None)
     if state in ('complete','completed') and (kind=='graph' or render_generation==self.page_generation):render(result.get('result',result))
     elif state=='error':self.status.set(result.get('error','Запит не завершено'))
   app_method={'graph':'graph_status','balance':'balance_status','feature':'feature_status'}[kind]
   self.submit('watch.poll.'+kind,lambda method=app_method:self.call(method),finish)
  if self.current=='Графіки' and self.graph_auto.get() and self.graph_next and time.monotonic()>=self.graph_next and not self.watch:self.start_graph()
  self.after(1000,self.tick)
 def render_live(self,envelope):
  old_scope=self.latest.get('_profile');new_scope=envelope.get('_profile')
  if old_scope and new_scope and old_scope!=new_scope:
   self.last_result=None
   for widget in self.graph_output.body.winfo_children():widget.destroy()
  self.latest=envelope;state=envelope.get('state') or {};stale=state.get('stale',True) or not envelope.get('connected',False);metrics=with_currents((state.get('normalized') or {}).get('metrics') or {});defs=(state.get('descriptor') or {}).get('metric_definitions') or []
  self.connection.set(('● ' if envelope.get('connected') else '○ ')+('LAN' if envelope.get('route')=='local' else 'Віддалено')+' · '+envelope.get('connection_message',''))
  self.flow.update_state(metrics,stale,(state.get('descriptor') or {}).get('model') or ((state.get('parameters') or {}).get('identity') or {}).get('model') or '—');names={v['canonical_id']:clean(v.get('ui_name',v.get('name',v['canonical_id']))) for v in defs if v.get('canonical_id')};rows=[];home={k:[] for k in GROUPS}
  for key in dict.fromkeys([v.get('canonical_id') for v in defs if v.get('canonical_id')]+list(metrics)):
   m=metrics.get(key);block=group(key);title=names.get(key,key);text=metric_text(m,stale);home[block].append(title+': '+home_metric_text(m,stale));rows.append({'Блок':GROUPS[block],'Показник':title,'Значення':text,'Джерело':(m or {}).get('source',''),'Якість':(m or {}).get('quality','')})
  for key,var in self.home_values.items():var.set('\n'.join(home[key]) or '—')
  if self.current=='Моніторинг':self.monitor.set(rows,['Блок','Показник','Значення','Джерело','Якість'])
  phone=state.get('server_phone') or {};fresh=envelope.get('connected') and phone.get('available') and phone.get('age_s',999)<=45 and (envelope.get('last_received_age_s') or 0)<=15
  self.server_home.set('Стан телефона сервера · Заряд: '+(display(phone.get('battery_percent'),'%') if fresh else '—')+' · Живлення: '+(('від зарядки' if phone.get('external_power') else 'від батареї' if phone.get('external_power') is False else '—') if fresh else '—')+' · Wi-Fi: '+(display(phone.get('wifi_rssi_dbm'),'dBm') if fresh and phone.get('wifi_connected') else '—'))
  if self.widget and self.widget.winfo_exists():
   cached=getattr(self.controller,'widget_state',{})
   if not self.controller.visible and cached:
    widget_state=cached.get('state') or {};self.widget_update(with_currents((widget_state.get('normalized') or {}).get('metrics',{})),widget_state.get('stale',True) or time.time()-cached.get('_captured_at',0)>600,cached.get('_captured_at'))
   else:self.widget_update(metrics,stale)
 def save_options(self):
  if hasattr(self,'graph_auto'):
   self.options['graph_auto']=self.graph_auto.get();self.options['graph_fields']=self.graph_fields
   self.options['graph']={k:v.get() for k,v in self.graph_vars.items()};self.options['graph']['group']=self.graph_group.get()
  atomic(self.options_path,self.options)
 def show_window(self):self.deiconify();self.lift();self.controller.set_visible(True)
 def on_close(self):
  if self.tray and self.options.get('close_to_tray',True):self.withdraw();self.controller.set_visible(False);self.status.set('Робота у фоні')
  else:self.shutdown()
 def start_tray(self):
  try:
   import pystray
   from PIL import Image
   icon=Image.open(Path(__file__).resolve().parents[1]/'assets/duck_solar.ico')
   self.tray=pystray.Icon('DuckSolarPC',icon,'Duck Solar',pystray.Menu(pystray.MenuItem(lambda item:L.text('Відкрити'),lambda *args:self.events.put(('show',))),pystray.MenuItem(lambda item:L.text('Віджет'),lambda *args:self.events.put(('widget',))),pystray.MenuItem(lambda item:L.text('Вийти'),lambda *args:self.events.put(('quit',)))))
   threading.Thread(target=self.tray.run,name='DesktopTray',daemon=True).start();self.controller.notify=self.notify
  except Exception as exc:logging.exception('Tray unavailable');self.status.set('Системний трей недоступний: '+str(exc))
 def notify(self,event):
  if not self.tray or not self.tray.visible:return False
  try:self.tray.notify(L.text(clean(event.get('detail','Подія станції')))+' · '+datetime.fromtimestamp(event.get('created',time.time()),ZONE).strftime('%d.%m %H:%M'),L.text(clean(event.get('message','Duck Solar'))));return True
  except Exception:logging.exception('Windows notification failed');return False
 def show_widget(self):
  if self.widget and self.widget.winfo_exists():self.widget.lift();return
  self.controller.widget_enabled=True;self.widget=tk.Toplevel(self);self.widget.title('Duck Solar · віджет');self.widget.geometry('530x310');self.widget.minsize(480,300);self.widget.attributes('-topmost',True)
  self.widget_canvas=tk.Canvas(self.widget,bg='white',height=245,highlightthickness=0);self.widget_canvas.pack(fill='both',expand=True)
  def received(value):
   value['_captured_at']=time.time();self.controller.widget_state=value;self.controller.last_widget=time.monotonic();state=value.get('state') or {};self.widget_update(with_currents((state.get('normalized') or {}).get('metrics',{})),state.get('stale',True),value['_captured_at'])
  def close_widget():self.controller.widget_enabled=False;self.widget.destroy();self.widget=None
  self.widget.protocol('WM_DELETE_WINDOW',close_widget)
  ttk.Button(self.widget,text='↻ Оновити',command=lambda:self.submit('widget.refresh',lambda:self.call('widget_snapshot'),received)).pack(fill='x',padx=10,pady=6)
  self.widget_update({},True)
 def widget_update(self,metrics,stale,captured_at=None):
  c=self.widget_canvas;c.delete('all');w=max(480,c.winfo_width());keys=[('PV','pv.total_power','pv.inputs.aggregate.voltage','pv.inputs.aggregate.current','#d79d13'),('Навантаження','output.active_power','output.phases.L1.voltage','output.phases.L1.current','#2b8ac0'),('АКБ','battery.channels.main.soc','battery.channels.main.voltage','battery.channels.main.discharge_current','#9663cc')]
  for i,(title,key,u,a,color) in enumerate(keys):
   x=w*(i+.5)/3;y=80;m=metrics.get(key);raw=m.get('value') if m else None;fraction=max(0,min(1,(raw or 0)/(100 if i==2 else 6200))) if valid(m,stale) else 0
   c.create_oval(x-43,y-43,x+43,y+43,outline='#e5edf4',width=9)
   if fraction:c.create_arc(x-43,y-43,x+43,y+43,start=90,extent=-fraction*359,style='arc',outline=color,width=9)
   c.create_text(x,y-13,text=title,fill=color,font=('Segoe UI',10));c.create_text(x,y+10,text=metric_text(m,stale),fill=INK,font=('Segoe UI Semibold',11));c.create_text(x,145,text=metric_text(metrics.get(u),stale)+' / '+metric_text(metrics.get(a),stale),fill=MUTED,font=('Segoe UI',9))
  c.create_text(w/2,180,text='Заряд ↑ '+metric_text(metrics.get('battery.channels.main.charge_current'),stale)+' · Розряд ↓ '+metric_text(metrics.get('battery.channels.main.discharge_current'),stale)+' · Мережа '+metric_text(metrics.get('grid.phases.L1.voltage'),stale)+' / '+metric_text(metrics.get('grid.phases.L1.current'),stale),fill=MUTED,font=('Segoe UI',9));c.create_text(w/2,204,text='Імпорт '+metric_text(metrics.get('grid.import_power'),stale)+' · Експорт '+metric_text(metrics.get('grid.export_power'),stale),fill=MUTED,font=('Segoe UI',9));c.create_text(w/2,229,text=('Дані застарілі' if stale else 'Знімок о '+datetime.fromtimestamp(captured_at or time.time(),ZONE).strftime('%H:%M:%S')+(' · фон 5 хв' if captured_at else '')),fill=MUTED,font=('Segoe UI',9))
 def shutdown(self):
  if self.stop_flag:return
  self.stop_flag=True;self.save_options()
  if self.tray:self.tray.stop()
  self.controller.close();self.pool.shutdown(wait=False,cancel_futures=True);self.destroy()
