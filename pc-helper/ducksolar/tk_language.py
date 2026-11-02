"""Tk presentation adapters which preserve source variables and selection values."""
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,colorchooser
import weakref
from . import ui_language as lang

_installed=False
_texts=weakref.WeakKeyDictionary()
_bindings=weakref.WeakKeyDictionary()
_tabs=weakref.WeakKeyDictionary()
_headings=weakref.WeakKeyDictionary()
_titles=weakref.WeakKeyDictionary()
_refreshers=weakref.WeakKeyDictionary()

def register(widget,method):_refreshers[widget]=method

class _VariableRef:
    def __init__(self,widget,name):self.widget=weakref.ref(widget);self.tk=widget.tk;self.name=name
    def get(self):return self.tk.globalgetvar(self.name)
    def set(self,value):self.tk.globalsetvar(self.name,value)
    def trace_add(self,mode,callback):
        token=self.widget()._register(callback);self.tk.call('trace','add','variable',self.name,mode,token);return token
    def trace_remove(self,mode,token):self.tk.call('trace','remove','variable',self.name,mode,token)

def _proxy(widget,variable,combo=False):
    name=str(variable)
    bindings=_bindings.setdefault(widget,{})
    if name in bindings:return bindings[name]['display']
    source=variable if isinstance(variable,tk.Variable) else _VariableRef(widget,name)
    display=tk.StringVar(master=widget,value=lang.text(source.get()))
    row=dict(source=source,display=display,busy=False,combo=combo,values=())
    def forward(*unused):
        if row['busy']:return
        row['busy']=True
        try:display.set(lang.text(source.get()))
        finally:row['busy']=False
    def backward(*unused):
        if row['busy'] or not row['combo']:return
        value=display.get();original=next((v for v in row['values'] if lang.text(v)==value),value)
        row['busy']=True
        try:source.set(original)
        finally:row['busy']=False
    source_trace=source.trace_add('write',forward);display_trace=display.trace_add('write',backward)
    def cleanup(event):
        if event.widget is not widget:return
        try:source.trace_remove('write',source_trace);display.trace_remove('write',display_trace)
        except tk.TclError:pass
    def attach_cleanup():
        try:
            if widget.winfo_exists():widget.bind('<Destroy>',cleanup,add='+')
            else:source.trace_remove('write',source_trace);display.trace_remove('write',display_trace)
        except tk.TclError:pass
    widget._root().after_idle(attach_cleanup)
    row['forward']=forward;row['traces']=(source,display);bindings[name]=row
    return display

def install():
    global _installed
    if _installed:return
    _installed=True
    original_options=tk.Misc._options
    def options(self,cnf,kw=None):
        config=tk._cnfmerge((cnf,kw)) if kw else tk._cnfmerge(cnf)
        if not isinstance(config,dict):return original_options(self,cnf,kw)
        config=dict(config)
        for key in ('text','label'):
            if key in config and isinstance(config[key],str):
                _texts.setdefault(self,{})[key]=config[key];config[key]=lang.text(config[key])
        combo=isinstance(self,ttk.Combobox)
        editable=isinstance(self,(tk.Entry,ttk.Entry,tk.Spinbox,ttk.Spinbox,tk.Text)) and not combo
        if 'textvariable' in config and not editable:
            config['textvariable']=_proxy(self,config['textvariable'],combo)
        if combo and 'values' in config:
            values=tuple(config['values']);_texts.setdefault(self,{})['values']=values
            for row in _bindings.get(self,{}).values():row['values']=values
            config['values']=tuple(lang.text(v) for v in values)
        return original_options(self,config)
    tk.Misc._options=options
    original_title=tk.Wm.wm_title
    def title(self,string=None):
        if string is not None:_titles[self]=string;string=lang.text(string)
        return original_title(self,string)
    tk.Wm.wm_title=title;tk.Wm.title=title
    original_tab=ttk.Notebook.tab
    original_add=ttk.Notebook.add
    def add(self,child,**kw):
        if 'text' in kw:_tabs.setdefault(self,{})[str(child)]=kw['text']
        return original_add(self,child,**kw)
    def tab(self,tab_id,option=None,**kw):
        if 'text' in kw:
            try:key=self.tabs()[self.index(tab_id)]
            except tk.TclError:key=str(tab_id)
            _tabs.setdefault(self,{})[key]=kw['text']
        return original_tab(self,tab_id,option,**kw)
    ttk.Notebook.add=add;ttk.Notebook.tab=tab
    original_heading=ttk.Treeview.heading
    def heading(self,column,option=None,**kw):
        if 'text' in kw:_headings.setdefault(self,{})[column]=kw['text']
        return original_heading(self,column,option,**kw)
    ttk.Treeview.heading=heading
    # Dialogs receive translated captions/messages; return values remain native.
    for module,names in [(messagebox,['showinfo','showwarning','showerror','askyesno','askokcancel','askretrycancel','askyesnocancel','askquestion']),
                         (filedialog,['askopenfilename','asksaveasfilename','askdirectory']),
                         (colorchooser,['askcolor'])]:
        for name in names:
            original=getattr(module,name)
            def call(*args,_original=original,**kw):
                args=tuple(lang.text(a) if isinstance(a,str) else a for a in args)
                for key in ('title','message','detail'):
                    if key in kw:kw[key]=lang.text(kw[key])
                if 'filetypes' in kw:kw['filetypes']=[(lang.text(label),pattern) for label,pattern in kw['filetypes']]
                return _original(*args,**kw)
            setattr(module,name,call)

def refresh(root):
    for widget,values in list(_texts.items()):
        try:
            if not widget.winfo_exists():continue
            config={k:v for k,v in values.items() if k in widget.keys()}
            # Canvas item text belongs to an item, not the Canvas widget.
            if config:widget.configure(**config)
        except tk.TclError:pass
    for notebook,tabs in list(_tabs.items()):
        for key,value in tabs.items():
            try:notebook.tab(key,text=value)
            except tk.TclError:pass
    for widget,headings in list(_headings.items()):
        for key,value in headings.items():
            try:widget.heading(key,text=value)
            except tk.TclError:pass
    for widget,value in list(_titles.items()):
        try:widget.title(value)
        except tk.TclError:pass
    for rows in list(_bindings.values()):
        for row in rows.values():
            try:row['forward']()
            except tk.TclError:pass
    for widget,method in list(_refreshers.items()):
        try:
            if widget.winfo_exists():getattr(widget,method)()
        except tk.TclError:pass
    root.event_generate('<<InterfaceLanguageChanged>>',when='tail')

def selector(parent,root):
    row=ttk.Frame(parent)
    ttk.Label(row,text='Мова').pack(side='left',padx=4)
    selected=tk.StringVar(value='English' if lang.language()=='en' else 'Українська')
    box=ttk.Combobox(row,textvariable=selected,values=('English','Українська'),state='readonly',width=12)
    box.pack(side='left')
    def change(unused=None):
        lang.set_language('uk' if selected.get()=='Українська' else 'en');refresh(root)
    box.bind('<<ComboboxSelected>>',change)
    return row

