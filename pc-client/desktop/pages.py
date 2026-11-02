import tkinter as tk
from tkinter import ttk,messagebox,filedialog
import json,os,sys,subprocess,math
from datetime import datetime,date,timedelta
from pathlib import Path
from .widgets import Results,Table,DateInput
from .model import display,clean,validate_parameter,LABELS,ZONE
from .settings import migrate_legacy
ENTRIES=[('Налаштування підключення','connection','connection'),('Стан сервера','health','health'),('Місячний баланс','balance','balance'),('Фінанси будинку','finance','finance'),('Показники лічильника','meters','meters'),('Зелений тариф','tariff','tariff'),('Події інвертора','events','events'),('Історія вимірів','history','history'),('Параметри інвертора','parameters','parameters'),('Сповіщення Windows','notifications','notifications'),('Погода та прогноз','weather','weather'),('Генерація сьогодні','forecast_live','insight'),('Прогноз і факт','forecast','insight'),('Точність прогнозу','forecast_stats','insight'),('План нічного заряду','charge_plan','insight'),('Календар енергії','calendar','insight'),('Порівняння періодів','compare','insight'),('Добовий звіт','report','insight'),('Відключення мережі','outages','insight'),('Історія АКБ','battery_history','insight'),('Автономність АКБ','battery','battery'),('Нічний тариф','night','night'),('Коригування PV','pv','pv'),('Профілі налаштувань','profiles','profiles'),('Історія команд','commands','commands'),('Зв’язок із ПК-службою','support','support'),('Параметри ПК-клієнта','preferences','preferences')]
ENTRIES += [('Аналітика станції','analytics','station_menu'),('Налаштування','settings','station_menu'),('Прогноз і планування','planning','station_menu')]
TITLES=dict((k,t) for t,k,m in ENTRIES)
ROOT_ENTRIES={'analytics','battery','planning','balance','finance','meters','tariff','events','history','commands','health','settings','support'}
GROUP_ENTRIES={'analytics':['calendar','compare','report','outages','forecast'], 'settings':['connection','parameters','notifications','night','pv','profiles','battery','preferences'], 'planning':['weather','forecast_live','forecast_stats','charge_plan']}
def station_menu(app,parent):
 title(parent,TITLES[app.more_key])
 for key in GROUP_ENTRIES[app.more_key]:ttk.Button(parent,text=TITLES[key],command=lambda k=key:app.open_page(k)).pack(fill='x',padx=12,pady=4)

def arrange(parent):
 # Preserve widget identity and callbacks; leave the Additional menu untouched.
 def contains(widget,classes):
  return isinstance(widget,classes) or any(contains(c,classes) for c in widget.winfo_children())
 children=parent.pack_slaves();head=[];controls=[];information=[];settings=[]
 for child in children:
  info=child.pack_info()
  if isinstance(child,ttk.Label) and not head:head.append((child,info))
  elif contains(child,(ttk.Button,)) and not contains(child,(Results,Table)):controls.append((child,info))
  elif contains(child,(ttk.Entry,ttk.Combobox,ttk.Checkbutton)):settings.append((child,info))
  else:information.append((child,info))
 for child in children:child.pack_forget()
 for child,info in head+controls+information+settings:
  info.pop('in',None);child.pack(**info)
 # Short direct action buttons share one row. Long labels keep full width.
 pending=[]
 for child in parent.pack_slaves():
  if isinstance(child,ttk.Button) and len(str(child.cget('text')))<=24:pending.append(child)
  else:
   if len(pending)>=2:_button_row(parent,pending)
   pending=[]
 if len(pending)>=2:_button_row(parent,pending)
def _button_row(parent,buttons):
 for start in range(0,len(buttons)-1,2):
  pair=buttons[start:start+2];row=ttk.Frame(parent);row.pack(before=pair[0],fill='x',padx=10,pady=4)
  for button in pair:button.pack_forget();button.pack(in_=row,side='left',expand=True,fill='x',padx=3)

def title(parent,text,note=''):
 ttk.Label(parent,text=text,style='Heading.TLabel').pack(anchor='w',padx=12,pady=12)
 if note:ttk.Label(parent,text=note,wraplength=880,padding=12).pack(fill='x')
def actions(parent):
 box=ttk.Frame(parent,padding=8);box.pack(fill='x');return box
def form(parent,spec):
 box=ttk.Frame(parent,padding=10);box.pack(fill='x');variables={};rules={}
 for index,(key,label,default,kind) in enumerate(spec):
  rules[key]=kind;ttk.Label(box,text=label).grid(row=index,column=0,sticky='w',pady=5,padx=(0,10))
  if kind is bool:
   var=tk.BooleanVar(value=bool(default));entry=ttk.Checkbutton(box,variable=var)
  else:
   var=tk.StringVar(value='' if default is None else str(default))
   if isinstance(kind,list):entry=ttk.Combobox(box,textvariable=var,values=kind,state='readonly',width=27)
   else:entry=ttk.Entry(box,textvariable=var,width=38,show='•' if key=='password' else '')
  variables[key]=var;entry.grid(row=index,column=1,sticky='ew',pady=5);box.columnconfigure(1,weight=1)
 def read():
  value={}
  for key,var in variables.items():
   raw=var.get();kind=rules[key]
   if kind is bool:value[key]=bool(raw)
   elif kind in (float,int,'optional_float'):
    if kind=='optional_float' and not raw.strip():value[key]=None;continue
    n=float(str(raw).replace(',','.'))
    if not math.isfinite(n) or kind is int and not n.is_integer():raise ValueError('Некоректне число: '+key)
    value[key]=int(n) if kind is int else n
   else:value[key]=str(raw).strip()
  return value
 def fill(value):
  for key,var in variables.items():
   if key in value:var.set('' if value[key] is None else value[key])
 return read,fill,variables
def result(parent):
 output=Results(parent);ttk.Button(parent,text='Експортувати / поділитися звітом',command=output.export).pack(anchor='e',padx=10,pady=4);output.pack(fill='both',expand=True,padx=10);return output
def safe(app,fn):
 try:fn()
 except Exception as exc:app.status.set(str(exc));messagebox.showerror('Duck Solar',str(exc),parent=app)
def connection(app,parent):
 title(parent,'Підключення до сервера','Захищений HTTPS із перевіркою ідентичності. Пароль не зберігається; токен захищений Windows DPAPI. Код парування потрібен лише для встановлення довіри.')
 cfg=app.controller.profile
 read,fill,vars=form(parent,[('lan','LAN HTTPS',cfg.get('lan',''),str),('remote','Віддалений HTTPS',cfg.get('remote',''),str),('username','Користувач',cfg.get('username',''),str),('password','Пароль','',str),('serial','Серійний номер логера',cfg.get('serial',''),str),('code','Код парування','',str),('register','Створити акаунт',False,bool)])
 buttons=actions(parent)
 def connect():
  v=read()
  def complete(value):vars['password'].set('');vars['code'].set('');app.controller.profile.update({k:v[k] for k in ['lan','remote','username','serial']});app.status.set('Підключено')
  app.submit('connect.login',lambda:app.call('connect',v['lan'],v['remote'],v['username'],v['password'],v['serial'],v['code'],v['register']),complete,mutating=True)
 ttk.Button(buttons,text='Підключитись',command=lambda:safe(app,connect)).pack(side='left',padx=4)
 for label,route in [('Примусово LAN','local'),('Примусово віддалено','remote')]:
  def switch(r=route):
   v=read();app.submit('route.switch',lambda:app.call('switch_route',r,v['lan'],v['remote']),lambda _:app.status.set('Пріоритет маршруту змінений; автоматичне перемикання працює'))
  ttk.Button(buttons,text=label,command=lambda f=switch:safe(app,f)).pack(side='left',padx=4)
 def import_profile():
  path=filedialog.askopenfilename(title='Конфігурація ПК-клієнта0.3.4',filetypes=[('Конфігурація','config.json')])
  if not path:return
  if migrate_legacy(app.root_path,path):
   app.controller.profile=app.call('initialize',str(app.root_path));fill(app.controller.profile);app.status.set('Профіль перенесено. Старий файл не змінений.')
  else:app.status.set('Поточний профіль уже існує; він не був перезаписаний. Для іншого сервера введіть дані вручну.')
 ttk.Button(parent,text='Перенести профіль ПК0.3.4',command=lambda:safe(app,import_profile)).pack(anchor='w',padx=12,pady=5)
 ttk.Button(parent,text='Стан і діагностика з’єднання',command=lambda:app.open_page('health')).pack(anchor='w',padx=12,pady=12)
def health(app,parent):
 title(parent,'Стан сервера','Заряд телефона, джерело живлення та Wi-Fi доступні, коли сервер передає свіжі дані.');out=result(parent)
 ttk.Button(parent,text='Оновити стан',command=lambda:app.submit('health',lambda:app.call('connection_health'),out.show)).pack(anchor='w',padx=12)
 app.submit('health',lambda:app.call('connection_health'),out.show)
def balance(app,parent):
 title(parent,'Місячний баланс','Лічильник будинку й облік інвертора показуються окремо; пропуски не замінюються нулями.');row=actions(parent);anchor=DateInput(row,datetime.now(ZONE).strftime('%Y-%m-01'));anchor.pack(side='left');source=tk.StringVar(value='Auto');ttk.Combobox(row,textvariable=source,values=['Auto','Local','SmartESS'],width=12,state='readonly').pack(side='left',padx=7);out=result(parent)
 def start():
  month=anchor.anchor()[:7];s=source.get();app.submit('balance.start',lambda:app.call('balance_start',month,s),lambda _:app.set_watch('balance',out.show))
 ttk.Button(row,text='Розрахувати',command=lambda:safe(app,start)).pack(side='left');ttk.Button(row,text='Скасувати',command=lambda:app.submit('balance.cancel',lambda:app.call('balance_cancel'))).pack(side='left',padx=5)
def finance(app,parent):
 title(parent,'Фінанси будинку','За показниками лічильника будинку. Сальдо = експорт − імпорт, у кВт·год і грн. Немає даних — це не нуль.');row=actions(parent);anchor=DateInput(row,datetime.now(ZONE).strftime('%Y-%m-01'));anchor.pack(side='left');out=result(parent)
 def start():
  month=anchor.anchor()[:7]
  def complete(value):
   selected=value.get('selected')
   if selected:
    f=selected.get('finance') or {};d=selected.get('delta') or {};a=f.get('export_day_kwh');b=f.get('export_night_kwh');c=f.get('import_day_kwh');e=f.get('import_night_kwh')
    if all(isinstance(v,(int,float)) for v in [a,b,c,e]):f['saldo_kwh']=a+b-c-e
    out.show(value)
   else:out.show('Недостатньо показників лічильника для цього місяця')
  app.submit('finance',lambda:app.call('finance_month',month),complete)
 ttk.Button(row,text='Отримати фінанси',command=lambda:safe(app,start)).pack(side='left',padx=8)
def meters(app,parent):
 title(parent,'Показники лічильника','Чотири накопичувальні регістри. Час — місцевий час Києва; збереження тільки після підтвердження.')
 date_box=actions(parent);anchor=DateInput(date_box);anchor.pack(side='left');time_var=tk.StringVar(value=datetime.now(ZONE).strftime('%H:%M'));ttk.Entry(date_box,textvariable=time_var,width=7).pack(side='left',padx=8)
 read,fill,vars=form(parent,[(k,t,0.,float) for k,t in [('import_day','Імпорт день, кВт·год'),('import_night','Імпорт ніч, кВт·год'),('export_day','Експорт день, кВт·год'),('export_night','Експорт ніч, кВт·год')]])
 out=result(parent);buttons=actions(parent)
 def save():
  values=read();stamp=anchor.anchor()+'T'+time_var.get()+':00';datetime.fromisoformat(stamp)
  if min(values.values())<0:raise ValueError('Показники не можуть бути від’ємними')
  if messagebox.askyesno('Зберегти показники?',stamp+'\n'+'\n'.join(k+': '+str(v) for k,v in values.items()),parent=app):app.submit('meters.save',lambda:app.call('add_meter_reading',stamp,json.dumps(values),True),out.show,mutating=True)
 ttk.Button(buttons,text='Зберегти показники',command=lambda:safe(app,save)).pack(side='left');ttk.Button(buttons,text='Показати збережені',command=lambda:app.submit('meters.list',lambda:app.call('meter_readings'),out.show)).pack(side='left',padx=7)
def tariff(app,parent):
 title(parent,'Зелений тариф','Офіційне джерело — НКРЕКП. Збережені ставки доступні без повторного завантаження.');buttons=actions(parent);out=result(parent)
 for text,method in [('Збережені ставки','tariff_status'),('Перевірити НКРЕКП','tariff_check')]:ttk.Button(buttons,text=text,command=lambda m=method:app.submit('tariff',lambda:app.call(m),out.show)).pack(side='left',padx=4)
 app.submit('tariff',lambda:app.call('tariff_status'),out.show)
def events(app,parent):
 title(parent,'Події інвертора','Опис, джерело й ознаки активності повертає сервер. Невідомі події не видаються за встановлені.');out=result(parent);ttk.Button(parent,text='Оновити події',command=lambda:app.submit('events',lambda:app.call('event_rows'),out.show)).pack(anchor='w',padx=12);app.submit('events',lambda:app.call('event_rows'),out.show)
def history(app,parent):
 title(parent,'Історія вимірів','Сервер зберігає й обробляє історію. Для повного графіка відкрийте розділ «Графіки» й оберіть дату.');out=result(parent)
 def show(value):
  out.show(value)
  dates=value.get('dates',[])
  if dates:
   chosen=tk.StringVar(value=dates[0]);row=actions(parent);ttk.Combobox(row,values=dates,textvariable=chosen,state='readonly').pack(side='left')
   def graph():app.graph_date.value.set(chosen.get());app.book.select(app.pages['Графіки']);app.start_graph()
   ttk.Button(row,text='Графік вибраного дня',command=graph).pack(side='left',padx=6)
 ttk.Button(parent,text='Оновити перелік дат',command=lambda:app.submit('history',lambda:app.call('history_dates'),show)).pack(anchor='w',padx=12);app.submit('history',lambda:app.call('history_dates'),show)
def insight(app,parent):
 key=app.more_key;kind={'battery_history':'battery'}.get(key,key);title(parent,TITLES[key]);controls=actions(parent);anchor=DateInput(controls);anchor.pack(side='left');mode=tk.StringVar(value='month' if kind=='calendar' else 'day');ttk.Combobox(controls,textvariable=mode,values=['day','month'],state='readonly',width=9).pack(side='left',padx=5)
 other=DateInput(controls,(datetime.now(ZONE).date()-timedelta(days=1)).isoformat())
 if kind=='compare':other.pack(side='left',padx=5)
 metric=tk.StringVar(value='Генерація');choices={'Генерація':'pv_w','Споживання':'output_w','Імпорт':'grid_import_w','Експорт':'grid_export_w','Сальдо':'saldo'}
 if kind in ('calendar','compare'):ttk.Combobox(controls,textvariable=metric,values=list(choices),state='readonly',width=14).pack(side='left',padx=4)
 out=result(parent)
 def open_day(day):
  app.graph_date.value.set(day);app.graph_vars['period'].set('День');app.book.select(app.pages['Графіки']);app.start_graph()
 out.on_date=open_day
 def start():
  first=anchor.anchor();second=other.anchor() if kind=='compare' else '';period='month' if kind=='calendar' else mode.get();m=choices[metric.get()]
  app.submit('feature.start',lambda:app.call('feature_start',kind,first,second,period,m),lambda _:app.set_watch('feature',out.show))
 ttk.Button(controls,text='Отримати дані',command=lambda:safe(app,start)).pack(side='left',padx=5)
 if kind=='charge_plan':ttk.Button(parent,text='Налаштувати нічний заряд',command=lambda:app.open_page('night')).pack(anchor='w',padx=12)
def battery(app,parent):
 title(parent,'Автономність АКБ','Вкажіть власну корисну ємність АКБ. SOC БМС надходить через інвертор. Залишок енергії й автономність оцінюються за заданою ємністю. Розрахунковий SOC не підставляється.')
 read,fill,vars=form(parent,[('usable_kwh','Корисна ємність, кВт·год',None,'optional_float'),('reserve_pct','Резерв, %',10.,float),('charge_efficiency','ККД заряду',.95,float)]);buttons=actions(parent);out=result(parent)
 def save():
  values=read();app.submit('battery.save',lambda:(app.feature('battery_config',values),app.feature('battery'))[1],out.show,mutating=True)
 ttk.Button(buttons,text='Зберегти й оновити',command=lambda:safe(app,save)).pack(side='left');ttk.Button(buttons,text='Історія АКБ',command=lambda:app.open_page('battery_history')).pack(side='left')
 app.submit('battery.load',lambda:(app.feature('battery_config'),app.feature('battery')),lambda value:(fill(value[0]),out.show(value[1])))
def night(app,parent):
 title(parent,'Заряд по нічному тарифу','07:00–23:00 — лише сонце, 23:00–07:00 — сонце та мережа. Час Києва. Зміни застосовуються одразу. Вимкнення відновлює початкові джерело та струм заряду; пов’язані ручні зміни заблоковані до завершення відновлення.')
 read,fill,vars=form(parent,[('enabled','Автоматичний розклад',False,bool),('day_a','Денний ліміт, А (лише сонце)',10,int),('night_a','Ніч / максимум плану, А',60,int),('adaptive_enabled','Адаптивний нічний план',False,bool),('night_battery_share_pct','Нічне споживання від АКБ, %',100.,float)]);out=result(parent)
 def save():
  value=read()
  if value['enabled'] and not messagebox.askyesno('Дозволити автоматичні зміни інвертора?',f"День {value['day_a']} А, ніч до {value['night_a']} А.\nВдень — лише сонце, вночі — сонце та мережа. Вимкнення відновить початкові налаштування. Пов’язані ручні зміни заблоковані.",parent=app):return
  app.submit('night.save',lambda:app.feature('night_charge',value),out.show,mutating=True)
 ttk.Button(parent,text='Зберегти розклад',command=lambda:safe(app,save)).pack(anchor='w',padx=12);ttk.Button(parent,text='Оновити стан',command=lambda:app.submit('night.load',lambda:app.feature('night_charge'),lambda value:(fill(value),out.show(value)))).pack(anchor='w',padx=12,pady=5)
 app.submit('night.load',lambda:app.feature('night_charge'),lambda value:(fill(value),out.show(value)))
def pv(app,parent):
 title(parent,'Коригування генерації PV','Поправка спільна для головної, графіків і обліку. Оригінальні виміри зберігаються. Нічний нуль застосовується лише до малих показів при сонці нижче −6° та відомих координатах.')
 read,fill,vars=form(parent,[('pv_correction_factor','Коефіцієнт (1 = без корекції)',1.0,float),('pv_night_noise_w','Нічний нуль до, Вт',0.,float),('weather_latitude','Широта',None,'optional_float'),('weather_longitude','Довгота',None,'optional_float')]);out=result(parent)
 def save():
  value=read();app.submit('pv.save',lambda:app.feature('pv_correction',value),out.show,mutating=True)
 ttk.Button(parent,text='Зберегти коригування',command=lambda:safe(app,save)).pack(anchor='w',padx=12);app.submit('pv.load',lambda:app.feature('pv_correction'),fill)
def parameters(app,parent):
 title(parent,'Параметри інвертора','Усі доступні для запису параметри розблоковані. Зміна лише після підтвердження, зі звіркою поточного значення й контрольним читанням; без автоматичного повтору запису.');buttons=actions(parent);table=Table(parent,height=15);table.pack(fill='both',expand=True,padx=10);state={};out=result(parent)
 def show(value):
  state.clear();state.update(value);rows=[]
  for row in value.get('rows',[]):rows.append({**row,'Параметр':clean(row.get('name',row.get('ui_name',row.get('canonical_id','')))),'Значення':'—' if value.get('stale') or not row.get('present') else clean(str(row.get('display_value',row.get('value',row.get('raw_value','—')))))+' '+row.get('unit',''),'Дозволено':row.get('allowed_note',row.get('write_reason','')),'Запис':'Так' if row.get('writable') else 'Ні'})
  table.set(rows,['Параметр','Значення','Запис','Дозволено']);app.status.set('Параметри застарілі; запис недоступний' if value.get('stale') else 'Актуальні параметри')
 def edit():
  row=table.selected()
  if not row:raise ValueError('Виберіть параметр')
  if state.get('stale',True):raise ValueError('Перечитайте параметри; старе значення не можна змінювати')
  rule=row.get('write_rule') or {};window=tk.Toplevel(app);window.title(row['Параметр']);ttk.Label(window,text=row.get('allowed_note',''),wraplength=550,padding=12).pack();value=tk.StringVar(value=str(row.get('raw_value','')))
  choices=rule.get('enum') or {};allowed=[str(v) for v in rule.get('values',[])]
  if choices:
   mapping={str(k)+' · '+str(v):str(k) for k,v in choices.items()};chosen=tk.StringVar(value=next((k for k,v in mapping.items() if v==value.get()),next(iter(mapping))));ttk.Combobox(window,textvariable=chosen,values=list(mapping),state='readonly',width=50).pack(padx=12)
  elif allowed:chosen=value;ttk.Combobox(window,textvariable=value,values=allowed,state='readonly').pack(padx=12)
  else:chosen=value;ttk.Entry(window,textvariable=value).pack(padx=12)
  def send():
   raw=mapping[chosen.get()] if choices else chosen.get();raw=validate_parameter(row,raw)
   if not messagebox.askyesno('Надіслати команду?',row['Параметр']+'\n'+str(row.get('raw_value'))+' → '+raw,parent=window):return
   device=state.get('device_id','');profile=state.get('server_profile','');window.destroy();app.submit('parameter.write',lambda:app.call('submit_parameter',row['canonical_id'],raw,str(row.get('raw_value','')),device,True,profile),out.show,mutating=True)
  ttk.Button(window,text='Підтвердити зміну',command=lambda:safe(app,send)).pack(pady=12)
 ttk.Button(buttons,text='Показати параметри',command=lambda:app.submit('parameters',lambda:app.call('parameter_snapshot'),show)).pack(side='left');ttk.Button(buttons,text='Перечитати з інвертора',command=lambda:app.submit('parameters.refresh',lambda:app.call('refresh_parameters'))).pack(side='left',padx=5);ttk.Button(buttons,text='Змінити вибраний',command=lambda:safe(app,edit)).pack(side='left');ttk.Button(buttons,text='Результат команди',command=lambda:app.submit('parameters.command',lambda:app.call('parameter_command_status'),out.show)).pack(side='left',padx=5)
 app.submit('parameters',lambda:app.call('parameter_snapshot'),show)
def profiles(app,parent):
 title(parent,'Профілі налаштувань','Зберігаються лише відомі доступні для запису параметри. Перед застосуванням — перегляд змін; сервер виконує їх послідовно з контрольним читанням.');row=actions(parent);name=tk.StringVar();choice=tk.StringVar();ttk.Entry(row,textvariable=name,width=25).pack(side='left');selector=ttk.Combobox(row,textvariable=choice,state='readonly',width=25);selector.pack(side='left',padx=5);out=result(parent);job={}
 def reload():app.submit('profiles.list',lambda:app.feature('profiles'),lambda value:selector.configure(values=list(value)))
 def save():
  title_text=name.get().strip()
  if not title_text:raise ValueError('Задайте назву профілю')
  def work():
   snapshot=app.call('parameter_snapshot')
   if snapshot.get('stale',True):raise ValueError('Перечитайте параметри інвертора')
   values={r['canonical_id']:r['raw_value'] for r in snapshot.get('rows',[]) if r.get('writable') and r.get('present')};return app.feature('profiles',title_text,values)
  app.submit('profiles.save',work,lambda value:(out.show(value),reload()),mutating=True)
 def apply():
  selected=choice.get()
  if not selected:raise ValueError('Виберіть профіль')
  def preview(value):
   out.show(value,'Попередній перегляд')
   if value and messagebox.askyesno('Застосувати профіль?',selected+'\n'+'\n'.join(str(v.get('parameter'))+': '+str(v.get('old'))+' → '+str(v.get('new')) for v in value),parent=app):
    def started(result):job['id']=result['id'];poll()
    app.submit('profiles.apply',lambda:app.feature('apply_profile',selected,value),started,mutating=True)
  app.submit('profiles.preview',lambda:app.feature('preview_profile',selected),preview)
 def poll():
  if not out.winfo_exists() or not job.get('id'):return
  def done(value):
   out.show(value)
   if value.get('status')=='running':app.after(1500,poll)
  app.submit('profiles.status',lambda:app.feature('profile_status',job['id']),done)
 def delete():
  selected=choice.get()
  if selected and messagebox.askyesno('Видалити профіль?',selected,parent=app):app.submit('profiles.delete',lambda:app.feature('delete_profile',selected),lambda value:(out.show(value),reload()),mutating=True)
 for text,fn in [('Зберегти поточні',save),('Оновити список',reload),('Переглянути / застосувати',apply),('Видалити',delete)]:ttk.Button(parent,text=text,command=lambda f=fn:safe(app,f)).pack(anchor='w',padx=12,pady=3)
 reload()
def commands(app,parent):
 title(parent,'Історія команд');out=result(parent);ttk.Button(parent,text='Оновити',command=lambda:app.submit('commands',lambda:app.feature('commands'),out.show)).pack(anchor='w',padx=12);app.submit('commands',lambda:app.feature('commands'),out.show)
def notifications(app,parent):
 from ducksolar.notification_settings import DEFAULTS,RANGES,validate
 title(parent,'Сповіщення Windows','Доставка через системний трей, поки ПК та клієнт працюють. Закриття у трей не зупиняє сповіщення. Сон Windows/вимкнений ПК/«Не турбувати» можуть затримувати показ. Перемикачі зберігаються для цього ПК-клієнта окремо від телефона.')
 titles={'grid_lost':'Відсутня напруга мережі','grid_restored':'Напруга відновлена','server_battery':'Низький заряд телефона сервера','inverter_battery':'Низький заряд АКБ (БМС)','inverter_connection':'Втрата / відновлення інвертора','server_connection':'Недоступність / відновлення сервера','grid_voltage':'Неприйнятна напруга','overload':'Перевантаження','over_temperature':'Перегрів','critical_battery':'Критичний заряд АКБ','server_power':'Зарядка телефона сервера','storage':'Сховище та запис','server_battery_threshold':'Поріг батареї сервера, %','connection_delay_s':'Затримка втрати зв’язку, с','grid_voltage_min':'Нижня напруга, В','grid_voltage_max':'Верхня напруга, В','condition_delay_s':'Затримка умови, с','overload_pct':'Навантаження, %','temperature_c':'Температура, °C','critical_battery_pct':'Критичний заряд, %','power_delay_s':'Затримка від’єднання зарядки, с','storage_min_mb':'Вільне місце, МіБ'}
 read,fill,vars=form(parent,[(k,titles[k],v,int if k in RANGES else bool) for k,v in DEFAULTS.items()]);out=result(parent)
 def save():
  value=validate(read());app.submit('notification.settings',lambda:app.call('notification_settings',json.dumps(value)),out.show,mutating=True)
 ttk.Button(parent,text='Зберегти сповіщення',command=lambda:safe(app,save)).pack(anchor='w',padx=12);ttk.Button(parent,text='Показані повідомлення цього запуску',command=lambda:out.show(list(app.controller.alert_history))).pack(anchor='w',padx=12,pady=5)
 app.submit('notification.load',lambda:app.call('notification_settings'),lambda value:fill(value['settings']))
def weather(app,parent):
 title(parent,'Погода й прогноз генерації','Open-Meteo · CC BY 4.0. Прогноз і навчання виконує сервер; закриття клієнта їх не перериває. Якість навчання не послаблюється.')
 read,fill,vars=form(parent,[('location','Населений пункт','',str),('latitude','Широта',None,'optional_float'),('longitude','Довгота',None,'optional_float'),('installed_kw','Панелі, кВт',1.0,float),('tilt_deg','Нахил, °',30.,float),('azimuth_deg','Азимут, °',180.,float)]);buttons=actions(parent);out=result(parent);polling={'on':True}
 def show(value):
  fill(value.get('settings') or {});out.show(value.get('result') or value)
  app.status.set('Прогноз: '+value.get('state','')+' · '+value.get('phase',''))
  if value.get('state')=='running' and out.winfo_exists():app.after(2000,poll)
 def poll():
  if out.winfo_exists():app.submit('weather.status',lambda:app.call('weather_status'),show)
 def start(train=False):
  value=read()
  if train and not messagebox.askyesno('Почати навчання?','Потрібно щонайменше 95% покриття сонячного часу. Завдання продовжується на сервері без відкритого клієнта.',parent=app):return
  app.submit('weather.start',lambda:(app.call('weather_settings',json.dumps(value)),app.call('weather_start',train))[1],show,mutating=True)
 ttk.Button(buttons,text='Оновити прогноз',command=lambda:safe(app,lambda:start(False))).pack(side='left');ttk.Button(buttons,text='Навчити',command=lambda:safe(app,lambda:start(True))).pack(side='left',padx=5);ttk.Button(buttons,text='Скасувати',command=lambda:app.submit('weather.cancel',lambda:app.call('weather_cancel'),show,mutating=True)).pack(side='left');ttk.Button(buttons,text='Параметри панелей із сервера',command=lambda:app.submit('weather.profile',lambda:app.call('weather_profile'),fill)).pack(side='left',padx=5)
 poll()
def support(app,parent):
 from .support import Support
 title(parent,'Зв’язок із ПК-службою','Оновлення та журнали; служба не потрібна для основної роботи клієнта. Після підтвердження довіри журнали передаються автоматично приблизно раз на15хв; це можна вимкнути в параметрах ПК-клієнта. Передаються лише знімки діагностики, без профілів і токенів.');url=tk.StringVar(value=app.options.get('support_url','http://127.0.0.1:28765'));row=actions(parent);ttk.Entry(row,textvariable=url,width=48).pack(side='left');out=result(parent)
 def client():
  value=url.get().strip();app.options['support_url']=value;app.save_options();return Support(value,app.root_path,app.options.get('helper_id'))
 def status():
  service=client()
  def complete(value):
   if not app.options.get('helper_id'):
    if not messagebox.askyesno('Довіряти ПК-службі?',value['helper_id'],parent=app):return
    app.options['helper_id']=value['helper_id'];app.save_options()
   out.show(value)
  app.submit('pc.status',service.status,complete)
 def upload():
  service=client();app.submit('pc.upload',lambda:service.upload_diagnostics(app.controller.backend._cfg['client_id']),out.show)
 def updates():
  service=client();app.submit('pc.updates',service.desktop_manifest,out.show)
 def download():
  service=client();folder=filedialog.askdirectory(title='Куди зберегти перевірений пакет оновлення?')
  if folder:app.submit('pc.download',lambda:service.download(Path(folder)),out.show)
 for label,fn in [('Перевірити службу',status),('Передати журнали',upload),('Перевірити оновлення ПК-клієнта',updates),('Завантажити пакет',download)]:ttk.Button(parent,text=label,command=lambda f=fn:safe(app,f)).pack(anchor='w',padx=12,pady=4)
 ttk.Button(parent,text='Зберегти локальний звіт',command=lambda:save_diagnostics(app)).pack(anchor='w',padx=12,pady=4)
def save_diagnostics(app):
 from .support import export_diagnostics
 file=filedialog.asksaveasfilename(defaultextension='.zip',filetypes=[('Діагностика','*.zip')])
 if file:app.submit('pc.export',lambda:export_diagnostics(app.root_path,Path(file)),lambda value:app.status.set(str(value)))
def preferences(app,parent):
 title(parent,'Параметри ПК-клієнта','Вихід із меню трея повністю завершує процес. Автозапуск налаштовується лише для поточного користувача Windows.')
 read,fill,vars=form(parent,[('auto_upload','Автоматично передавати журнали довіреній ПК-службі',app.options.get('auto_upload',True),bool),('close_to_tray','Згортати в трей при закритті',app.options.get('close_to_tray',True),bool),('autostart','Запускати разом із Windows',app.options.get('autostart',False),bool)])
 def save():
  value=read()
  from .windows import set_autostart
  set_autostart(value['autostart']);app.options.update(value);app.save_options();app.status.set('Налаштування збережено')
 ttk.Button(parent,text='Зберегти',command=lambda:safe(app,save)).pack(anchor='w',padx=12);ttk.Button(parent,text='Відкрити віджет',command=app.show_widget).pack(anchor='w',padx=12,pady=5)
 ttk.Button(parent,text='Відкрити папку даних',command=lambda:os.startfile(str(app.root_path))).pack(anchor='w',padx=12,pady=5);ttk.Button(parent,text='Повністю вийти',command=app.shutdown).pack(anchor='w',padx=12,pady=5)
