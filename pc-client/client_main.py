import sys,os,argparse,logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path);parser.add_argument('--legacy-data',type=Path);parser.add_argument('--background',action='store_true');parser.add_argument('--self-check',type=Path)
 args=parser.parse_args()
 if args.self_check:
  from desktop.selfcheck import run
  return run(args.self_check)
 from desktop.settings import default_root,migrate_legacy
 root=(args.root or default_root()).resolve();root.mkdir(parents=True,exist_ok=True)
 handler=RotatingFileHandler(root/'desktop.log',maxBytes=1024*1024,backupCount=3,encoding='utf8');logging.basicConfig(handlers=[handler],level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
 from ducksolar.instance import SingleInstanceGuard
 guard=SingleInstanceGuard('DuckSolar_B2_Client')
 if not guard.acquire():
  import tkinter as tk
  from tkinter import messagebox
  window=tk.Tk();window.withdraw();messagebox.showinfo('Duck Solar','ПК-клієнт уже запущений. Перевірте системний трей b2.');window.destroy();return 0
 try:
  migrate_legacy(root,args.legacy_data)
  from desktop.controller import Controller
  from desktop.app import App
  controller=Controller(root);window=App(controller);controller.start()
  if args.background:window.withdraw();controller.set_visible(False)
  window.mainloop();return 0
 except Exception:
  logging.exception('Desktop launch failed');raise
 finally:guard.release()
if __name__=='__main__':raise SystemExit(main())
