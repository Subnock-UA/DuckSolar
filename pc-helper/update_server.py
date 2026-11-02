"""Standalone LAN updates/log viewer: no inverter or main monitoring runtime."""
import argparse,json,sys,threading,hashlib,zipfile,urllib.request
from pathlib import Path
from ducksolar.pc_support import LanSupport

def project_root():
    return Path.home()/'.ducksolar-b2-helper'

def publish(root,release_dir=None):
    """Publish only explicitly prepared b2 files from the selected release folder."""
    directory=Path(release_dir) if release_dir else Path(root)/'Releases'
    metadata=directory/'release.json'
    value=json.loads(metadata.read_text('utf8')) if metadata.is_file() else {'artifacts':[]}
    updates=[];desktop=None
    packages={'server':'ua.ducksolar.b2.server','client':'ua.ducksolar.b2.client'}
    for entry in value.get('artifacts',[]):
        file=(directory/entry['file']).resolve()
        if not file.is_relative_to(directory.resolve()) or not file.is_file():raise ValueError('Invalid release path')
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Release SHA256 mismatch')
        component=entry['component']
        if component in packages:
            if entry['package']!=packages[component] or not entry['version'].startswith('b2.') or type(entry['version_code']) is not int:raise ValueError('Expected a public b2 package')
            with zipfile.ZipFile(file) as archive:abis=sorted({name.split('/')[1] for name in archive.namelist() if name.startswith('lib/')})
            updates.append(dict(component=component,version=entry['version'],version_code=entry['version_code'],package=entry['package'],path=str(file),sha256=entry['sha256'],abis=abis))
        elif component=='desktop_client':
            desktop=dict(contract='ducksolar.desktop-client.v1',component=component,version=entry['version'],version_code=entry['version_code'],path=str(file),bytes=file.stat().st_size,sha256=entry['sha256'])
    folder=Path(root)/'Data/AndroidSupport';folder.mkdir(parents=True,exist_ok=True)
    temp=folder/'catalog.tmp';temp.write_text(json.dumps({'updates':updates},indent=2),'utf8');temp.replace(folder/'catalog.json')
    if desktop:
        temp=folder/'desktop-client.tmp';temp.write_text(json.dumps(desktop,indent=2),'utf8');temp.replace(folder/'desktop-client.json')
    return updates


def self_test(root):
    import tempfile
    import tkinter as tk
    window=tk.Tk();window.withdraw();window.update();window.destroy()
    with tempfile.TemporaryDirectory(prefix='ds-helper-check-') as temporary:
        helper=LanSupport(temporary,'127.0.0.1',0);helper.start()
        try:
            url='http://127.0.0.1:'+str(helper.http.server_port)+'/v1/status'
            data=json.load(urllib.request.urlopen(url,timeout=5))
            assert data['contract']=='ducksolar.lan-support.v1'
            assert data['prepared_history']==1
            catalog=json.load(urllib.request.urlopen('http://127.0.0.1:'+str(helper.http.server_port)+'/v1/prepared/catalog',timeout=5))
            assert catalog['packages']==[]
            print(json.dumps({'gui_runtime':True,'lan_api':True,'port':helper.http.server_port}),flush=True)
        finally:helper.stop()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--headless',action='store_true');parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=28765);parser.add_argument('--root',type=Path);parser.add_argument('--release-dir',type=Path)
    args=parser.parse_args();root=(args.root or project_root()).resolve()
    if args.self_test:return self_test(root)
    if args.headless:
        helper=LanSupport(root,args.host,args.port,release_root=args.release_dir);helper.start();publish(root,args.release_dir)
        print('READY '+str(helper.http.server_port),flush=True)
        try:threading.Event().wait()
        except KeyboardInterrupt:pass
        finally:helper.stop()
        return
    if sys.platform=='win32':
        import ctypes
        ctypes.WinDLL('kernel32').FreeConsole()
    import tkinter as tk
    from tkinter import ttk,messagebox
    from ducksolar import ui_language as L,tk_language
    L.configure(root);tk_language.install()
    window=tk.Tk();window.title('Duck Solar — оновлення та журнали b2.0.0');window.geometry('880x620')
    tk_language.selector(window,window).pack(anchor='e',padx=12,pady=6)
    helper=None;status=tk.StringVar(value='Запуск…');files={}
    ttk.Label(window,textvariable=status).pack(anchor='w',padx=12,pady=8)
    buttons=ttk.Frame(window);buttons.pack(fill='x',padx=12)
    def start():
        nonlocal helper
        if helper:return
        try:
            helper=LanSupport(root,args.host,args.port,release_root=args.release_dir);helper.start();updates=publish(root,args.release_dir)
            address='LAN-адреса цього ПК' if args.host=='0.0.0.0' else args.host
            status.set('Працює: http://'+address+':'+str(args.port)+' • APK: '+', '.join(x['component']+' '+x['version'] for x in updates))
        except Exception as exc:helper=None;status.set('Помилка: '+str(exc))
    def stop():
        nonlocal helper
        if helper:helper.stop();helper=None
        status.set('Сервер зупинено')
    def refresh_catalog():
        try:publish(root,args.release_dir);status.set('Каталог APK оновлено • порт '+str(args.port))
        except Exception as exc:messagebox.showerror('Оновлення',str(exc))
    for text,action in [('Запустити',start),('Зупинити',stop),('Оновити каталог APK',refresh_catalog)]:
        ttk.Button(buttons,text=text,command=action).pack(side='left',padx=4)
    pane=ttk.Panedwindow(window,orient='horizontal');pane.pack(fill='both',expand=True,padx=12,pady=8)
    listing=tk.Listbox(pane,width=38);viewer=ttk.Frame(pane);text=tk.Text(viewer,wrap='none',state='disabled')
    vertical=ttk.Scrollbar(viewer,orient='vertical',command=text.yview)
    horizontal=ttk.Scrollbar(viewer,orient='horizontal',command=text.xview)
    text.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    text.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
    viewer.rowconfigure(0,weight=1);viewer.columnconfigure(0,weight=1)
    pane.add(listing,weight=1);pane.add(viewer,weight=2)
    def physical_copy(event):
        if sys.platform=='win32' and event.keycode==67:text.event_generate('<<Copy>>');return 'break'
    text.bind('<Control-KeyPress>',physical_copy)
    ttk.Label(window,text='Журнали отримуються від застосунків. Оригінали на телефонах зберігаються.').pack(anchor='w',padx=12,pady=6)
    def scan():
        selected=listing.get(listing.curselection()[0]) if listing.curselection() else None
        paths=sorted((root/'Data/AndroidSupport/Received').glob('*/*/*/latest.log'))
        listing.delete(0,'end');files.clear()
        for file in paths:
            parts=file.relative_to(root/'Data/AndroidSupport/Received').parts
            name=parts[0][:8]+' / '+parts[1]+' / '+parts[2];files[name]=file;listing.insert('end',name)
            if name==selected:listing.selection_set(listing.size()-1)
        if selected is not None:show()
        window.after(5000,scan)
    def show(_=None):
        if not listing.curselection():return
        file=files[listing.get(listing.curselection()[0])]
        with file.open('rb') as f:f.seek(max(0,file.stat().st_size-65536));data=f.read(65536)
        text.configure(state='normal');text.delete('1.0','end');text.insert('end',data.decode('utf-8-sig',errors='replace'));text.configure(state='disabled')
    listing.bind('<<ListboxSelect>>',show)
    def close():stop();window.destroy()
    window.protocol('WM_DELETE_WINDOW',close);start();scan();window.mainloop()

if __name__=='__main__':main()
