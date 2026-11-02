from ducksolar import ui_language as L
from ducksolar import tk_language
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import calendar,csv,json,math
from datetime import datetime,date
from .model import display,clean,LABELS,FIELDS,ZONE,graph_energy,field_display,field_label
BG='#eff4f8';INK='#153047';MUTED='#65798b';ACCENT='#087e8b';COLORS=['#e6a11a','#2486c4','#32986b','#aa5d9b','#7963ce','#e37340','#2b9aa0']
class Scroll(ttk.Frame):
 def __init__(self,parent):
  super().__init__(parent);self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0);bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview);self.canvas.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');self.canvas.pack(fill='both',expand=True)
  self.body=ttk.Frame(self.canvas);self.window=self.canvas.create_window((0,0),window=self.body,anchor='nw')
  self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')));self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
  self.canvas.bind_all('<MouseWheel>',self._wheel,add='+')
 def _wheel(self,event):
  try:
   widget=self.winfo_containing(event.x_root,event.y_root)
   if widget and str(widget).startswith(str(self)):self.canvas.yview_scroll(-int(event.delta/120),'units')
  except tk.TclError:pass
class DateInput(ttk.Frame):
 def __init__(self,parent,value=None,mode='day'):
  super().__init__(parent);self.mode=mode;self.value=tk.StringVar(value=value or datetime.now(ZONE).date().isoformat());ttk.Entry(self,textvariable=self.value,width=13).pack(side='left');ttk.Button(self,text='▦',width=3,command=self.open).pack(side='left')
 def get(self):return self.value.get().strip()
 def anchor(self):
  text=self.get()
  if len(text)==4:text+='-01-01'
  if len(text)==7:text+='-01'
  return date.fromisoformat(text).isoformat()
 def open(self):
  popup=tk.Toplevel(self);popup.title('Оберіть дату');popup.transient(self.winfo_toplevel());popup.resizable(False,False)
  try:chosen=date.fromisoformat(self.anchor())
  except ValueError:chosen=datetime.now(ZONE).date()
  year=tk.IntVar(value=chosen.year);month=tk.IntVar(value=chosen.month);head=ttk.Frame(popup,padding=8);head.pack();grid=ttk.Frame(popup,padding=8);grid.pack()
  def use(day):self.value.set(date(year.get(),month.get(),day).isoformat());popup.destroy()
  def draw():
   for w in grid.winfo_children():w.destroy()
   for i,t in enumerate((['Пн','Вт','Ср','Чт','Пт','Сб','Нд'] if L.language()=='uk' else ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])):ttk.Label(grid,text=t,anchor='center').grid(row=0,column=i)
   for row,days in enumerate(calendar.monthcalendar(year.get(),month.get()),1):
    for col,d in enumerate(days):
     if d:ttk.Button(grid,text=str(d),width=3,command=lambda day=d:use(day)).grid(row=row,column=col,padx=1,pady=1)
  ttk.Spinbox(head,from_=2010,to=2100,textvariable=year,width=6,command=draw).pack(side='left');ttk.Spinbox(head,from_=1,to=12,textvariable=month,width=4,command=draw).pack(side='left');ttk.Button(head,text='Показати',command=draw).pack(side='left');ttk.Button(popup,text='Вибрати місяць',command=lambda:use(1)).pack(pady=6);draw()
class Table(ttk.Frame):
 def __init__(self,parent,rows=None,columns=None,height=10):
  super().__init__(parent);self.rows=[];self.columns=columns or [];self.tree=ttk.Treeview(self,show='headings',height=height)
  y=ttk.Scrollbar(self,orient='vertical',command=self.tree.yview);x=ttk.Scrollbar(self,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);self.tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew');self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
  self.set(rows or [],columns);tk_language.register(self,"_retranslate")
 def set(self,rows,columns=None):
  self.rows=rows;self.columns=columns or list(dict.fromkeys(k for row in rows if isinstance(row,dict) for k in row if not k.startswith('_')))[:18]
  self.tree.configure(columns=self.columns);self.tree.delete(*self.tree.get_children())
  for key in self.columns:self.tree.heading(key,text=field_label(key));self.tree.column(key,width=165,minwidth=90,stretch=True)
  for index,row in enumerate(rows):
   if isinstance(row,dict):self.tree.insert('', 'end',iid=str(index),values=[L.text(field_display(k,row.get(k)) if not isinstance(row.get(k),(list,dict)) else clean(json.dumps(row[k],ensure_ascii=False))) for k in self.columns])
 def _retranslate(self):self.set(self.rows,self.columns)
 def selected(self):
  selected=self.tree.selection();return self.rows[int(selected[0])] if selected else None
 def export(self):
  file=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')])
  if file:
   with open(file,'w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.writer(stream);writer.writerow([L.text(LABELS.get(k,k)) for k in self.columns]);writer.writerows([[json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else row.get(k) for k in self.columns] for row in self.rows])
class Plot(ttk.Frame):
 def __init__(self,parent,result,colors=None,line_width=1.6):
  super().__init__(parent);self.result=result
  self.categorical=result.get('kind') in ('bar','bars') and all(not isinstance(row.get('x'),(int,float)) or abs(row['x'])<10000000000 for row in result.get('points',[]))
  from matplotlib.figure import Figure
  from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg,NavigationToolbar2Tk
  from matplotlib.ticker import MaxNLocator
  from matplotlib import dates as md
  points=result.get('points',[]);fields=result.get('fields',[])
  fields=[{'key':v,'label':FIELDS.get(v,v),'unit':''} if isinstance(v,str) else v for v in fields]
  pf=[f for f in fields if f['key']=='output_pf'];base=[f for f in fields if f['key']!='output_pf']
  units=list(dict.fromkeys(v.get('unit','') for v in base)) if base else ['PF'] if pf else [''];figure=Figure(figsize=(10,max(3.7,2.5*len(units))),dpi=100,facecolor='white');self.figure=figure;self.axes=[];self.axes_data={}
  for i,unit in enumerate(units):
   ax=figure.add_subplot(len(units),1,i+1);self.axes.append(ax);ax.set_facecolor('#fbfdff');ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False);ax.yaxis.set_major_locator(MaxNLocator(nbins=6,steps=[1,2,2.5,5,10]));ax.set_ylabel(unit or 'Безрозмірні')
   selected=[f for f in base if f.get('unit','')==unit]+pf
   pf_axis=ax.twinx() if pf and base else None
   if pf_axis is not None:
    pf_axis.set_ylim(0,1);pf_axis.set_ylabel('PF');pf_axis.yaxis.set_major_locator(MaxNLocator(nbins=5));self.axes.append(pf_axis);self.axes_data[pf_axis]=selected
   elif pf:ax.set_ylim(0,1);ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
   self.axes_data[ax]=selected
   for j,f in enumerate(selected):
    key=f['key'];x=[];y=[];target=pf_axis if key=='output_pf' and pf_axis is not None else ax
    for row in points:
     try:
      at=row.get('x');label=row.get('label','')
      instant=float(at) if self.categorical else datetime.fromtimestamp(float(at)/1000,ZONE) if isinstance(at,(int,float)) else datetime.fromisoformat(str(label).replace('Z','+00:00'))
      value=row.get(key)
      if key=='output_pf' and value is not None and not 0<=float(value)<=1:value=None
      if key in row.get('breaks',[]):x.append(instant);y.append(math.nan)
      if key=='pv_a' and value is None and not row.get('_gap'):continue
      x.append(instant);y.append(float(value) if value is not None and math.isfinite(float(value)) and not row.get('_gap') else math.nan)
     except (ValueError,TypeError,OverflowError):continue
    color=(colors or {}).get(key,COLORS[fields.index(f)%len(COLORS)])
    if result.get('kind') in ('bar','bars'):
     width=.8/max(1,len(selected)) if self.categorical else (x[1]-x[0]).total_seconds()/86400*.75/max(1,len(selected)) if len(x)>1 else .02
     target.bar([(t if self.categorical else md.date2num(t))+j*width for t in x],y,width=width,label=clean(f.get('label',FIELDS.get(key,key))),color=color,alpha=.85)
    else:target.plot(x,y,label=clean(f.get('label',FIELDS.get(key,key))),color=color,linewidth=line_width)
   if selected:
    handles,labels=ax.get_legend_handles_labels()
    if pf_axis is not None:
     h,l=pf_axis.get_legend_handles_labels();handles+=h;labels+=l
    ax.legend(handles,labels,loc='upper left',ncol=min(4,len(selected)),fontsize=8)
   if self.categorical:
    from matplotlib.ticker import FuncFormatter
    labels={p['x']:p.get('label',str(p['x'])) for p in points if isinstance(p.get('x'),(int,float))}
    ax.xaxis.set_major_locator(MaxNLocator(nbins=9,integer=True));ax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:L.text(labels.get(round(x),''))))
   else:
    locator=md.AutoDateLocator(minticks=3,maxticks=9,tz=ZONE);ax.xaxis.set_major_locator(locator);ax.xaxis.set_major_formatter(md.ConciseDateFormatter(locator,tz=ZONE))
   for event in result.get('events',[]):
    try:
     moment=event.get('x');moment=float(moment) if self.categorical and isinstance(moment,(int,float)) else datetime.fromtimestamp(moment/1000,ZONE) if isinstance(moment,(int,float)) else datetime.fromisoformat(event.get('time',event.get('timestamp','')).replace('Z','+00:00'));ax.axvline(moment,color='#bd6b42',alpha=.3,linestyle='--')
    except (ValueError,TypeError):pass
  figure.tight_layout(pad=1.5);self.canvas=FigureCanvasTkAgg(figure,self);self.canvas.get_tk_widget().pack(fill='both',expand=True);NavigationToolbar2Tk(self.canvas,self).update();self.detail=tk.StringVar(value='Наведіть курсор на точку · масштаб і переміщення на панелі');ttk.Label(self,textvariable=self.detail).pack(fill='x')
  self.canvas.mpl_connect('motion_notify_event',self.hover);self._language_axes=[(a,a.get_xlabel(),a.get_ylabel(),a.get_title(),[(v,v.get_label()) for v in list(a.lines)+list(a.containers)],[(v,v.get_text()) for v in a.get_legend().get_texts()] if a.get_legend() else []) for a in self.axes];tk_language.register(self,'_retranslate');self._retranslate()
  if result.get('energy_summary') and not result.get('suppress_summary'):ttk.Label(self,text=graph_energy(result),wraplength=1100,style='Summary.TLabel').pack(fill='x',padx=8,pady=10)
 def _retranslate(self):
  for axis,x,y,title,artists,legend in self._language_axes:
   axis.set_xlabel(L.text(x));axis.set_ylabel(L.text(y));axis.set_title(L.text(title))
   for artist,label in artists:artist.set_label(L.text(label))
   for item,label in legend:item.set_text(L.text(label))
  self.canvas.draw_idle()
 def hover(self,event):
  if event.inaxes is None or event.xdata is None:return
  points=self.result.get('points',[])
  candidates=[p for p in points if isinstance(p.get('x'),(int,float))]
  if not candidates:return
  from matplotlib import dates as md
  row=min(candidates,key=lambda p:abs((p['x'] if self.categorical else md.date2num(datetime.fromtimestamp(p['x']/1000,ZONE)))-event.xdata));parts=[row.get('label','')]
  for field in self.axes_data.get(event.inaxes,[]):parts.append(clean(field.get('label',field['key']))+': '+display(row.get(field['key']),field.get('unit','')))
  self.detail.set('    ·    '.join(parts))
class Results(ttk.Frame):
 def __init__(self,parent):super().__init__(parent);self.value=None;self.on_date=None
 def clear(self):
  for child in self.winfo_children():child.destroy()
 def show(self,value,title=''):
  self.clear();self.value=value
  if title:ttk.Label(self,text=title,style='Heading.TLabel').pack(anchor='w',pady=8)
  self.render(self,value)
 def render(self,parent,value,depth=0):
  if isinstance(value,dict):
   from .presentation import visible,TECHNICAL,DETAILS
   value=visible(value)
   if value.get('points') is not None and value.get('fields'):
    Plot(parent,value).pack(fill='both',expand=True,pady=8);return
   hourly=value.get('hourly') or []
   if hourly and all(isinstance(row,dict) and 'time' in row and 'power_w' in row for row in hourly):
    points=[]
    for row in hourly:
     try:points.append(dict(x=datetime.fromisoformat(row['time']).timestamp()*1000,label=row['time'],forecast=row['power_w']))
     except (ValueError,TypeError):pass
    if points:Plot(parent,dict(kind='line',fields=[dict(key='forecast',label='Прогноз PV',unit='Вт')],points=points)).pack(fill='both',expand=True,pady=6)
   scalars=[{'Показник':field_label(k),'Значення':field_display(k,v)} for k,v in value.items() if not isinstance(v,(dict,list)) and k not in TECHNICAL and not k.startswith('_')]
   if scalars:Table(parent,scalars,['Показник','Значення'],height=min(16,len(scalars))).pack(fill='x',pady=5)
   for key,child in value.items():
    if not isinstance(child,(dict,list)) or key in TECHNICAL:continue
    holder=parent
    if key in DETAILS:
     holder=ttk.Frame(parent);toggle=ttk.Button(parent,text='Показати деталі: '+LABELS.get(key,{'hourly':'погодинні значення','segments':'інтервали','reference_intervals':'підтверджені інтервали','calendar_estimate':'календарна оцінка','delta':'показники періоду'}.get(key,key)))
     toggle.configure(command=lambda box=holder:box.pack_forget() if box.winfo_manager() else box.pack(fill='both',expand=True,pady=4));toggle.pack(anchor='w',pady=4)
    box=ttk.LabelFrame(holder,text=LABELS.get(key,{'summary':'Енергетичний підсумок','graph':'Графік','points':'Показники','house_meter':'Лічильник будинку','finance':'Фінанси','delta':'Період обліку','days':'Дні','rows':'Записи','outages':'Відключення','events':'Події','battery_summary':'Підсумок АКБ','statistics':'Статистика','forecast':'Прогноз','windows':'Статистика за періоди','excluded':'Виключені дні','readings':'Показники лічильника'}.get(key,key)),padding=8);box.pack(fill='both',expand=True,pady=6);self.render(box,child,depth+1)
  elif isinstance(value,list):
   if value and all(isinstance(row,dict) for row in value):
    table=Table(parent,value,height=min(15,len(value)));table.pack(fill='both',expand=True)
    if self.on_date:
     def open_date(event):
      row=table.selected() or {};day=row.get('day',row.get('date',''))
      if isinstance(day,str) and len(day)==10:self.on_date(day)
     table.tree.bind('<Double-1>',open_date)
   else:ttk.Label(parent,text='\n'.join(display(row) for row in value) if value else 'Немає записів',wraplength=950).pack(anchor='w')
  else:ttk.Label(parent,text=display(value),wraplength=950).pack(anchor='w')
 def export(self):
  if self.value is None:return
  path=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=[('Звіт UTF-8','*.txt'),('JSON','*.json')])
  if path:
   def lines(value,level=0,key=""):
    if isinstance(value,dict):
     for key,child in value.items():
      if key not in ('diagnostics','raw','checkpoint'):yield '  '*level+field_label(key)+':';yield from lines(child,level+1,key)
    elif isinstance(value,list):
     for child in value:yield from lines(child,level)
    else:yield '  '*level+field_display(key,value)
   with open(path,'w',encoding='utf8') as stream:stream.write(json.dumps(self.value,ensure_ascii=False,indent=2) if path.endswith('.json') else 'Duck Solar\n'+'\n'.join(lines(self.value)))
