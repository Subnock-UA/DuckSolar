import os,sys,subprocess
from pathlib import Path

def set_autostart(enabled):
 if os.name!='nt':raise ValueError('Автозапуск доступний у Windows')
 if not getattr(sys,'frozen',False):raise ValueError('Автозапуск налаштовується у зібраному EXE')
 import winreg
 with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
  if enabled:winreg.SetValueEx(key,'DuckSolarB2PC',0,winreg.REG_SZ,subprocess.list2cmdline([sys.executable,'--background']))
  else:
   try:winreg.DeleteValue(key,'DuckSolarB2PC')
   except FileNotFoundError:pass

def capture_window(window,destination):
 """Render our own HWND even when another application covers it; never grab desktop."""
 import ctypes
 from ctypes import wintypes
 from PIL import Image
 user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
 user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
 hwnd=user.GetParent(window.winfo_id()) or window.winfo_id();rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect));width=rect.right-rect.left;height=rect.bottom-rect.top
 user.GetWindowDC.argtypes=[wintypes.HWND];user.GetWindowDC.restype=wintypes.HDC
 gdi.CreateCompatibleDC.argtypes=[wintypes.HDC];gdi.CreateCompatibleDC.restype=wintypes.HDC
 gdi.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=wintypes.HBITMAP
 gdi.SelectObject.argtypes=[wintypes.HDC,wintypes.HGDIOBJ];gdi.SelectObject.restype=wintypes.HGDIOBJ
 user.PrintWindow.argtypes=[wintypes.HWND,wintypes.HDC,wintypes.UINT]
 gdi.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
 gdi.DeleteObject.argtypes=[wintypes.HGDIOBJ];gdi.DeleteDC.argtypes=[wintypes.HDC];user.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
 dc=user.GetWindowDC(hwnd);memory=gdi.CreateCompatibleDC(dc);bitmap=gdi.CreateCompatibleBitmap(dc,width,height);previous=gdi.SelectObject(memory,bitmap)
 class Header(ctypes.Structure):
  _fields_=[('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),('planes',wintypes.WORD),('bits',wintypes.WORD),('compression',wintypes.DWORD),('image_size',wintypes.DWORD),('xppm',wintypes.LONG),('yppm',wintypes.LONG),('used',wintypes.DWORD),('important',wintypes.DWORD)]
 try:
  if not user.PrintWindow(hwnd,memory,2):raise ctypes.WinError(ctypes.get_last_error())
  header=Header(ctypes.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0);buffer=ctypes.create_string_buffer(width*height*4)
  if not gdi.GetDIBits(memory,bitmap,0,height,buffer,ctypes.byref(header),0):raise ctypes.WinError(ctypes.get_last_error())
  Image.frombuffer('RGB',(width,height),buffer,'raw','BGRX',0,1).save(destination)
 finally:gdi.SelectObject(memory,previous);gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(hwnd,dc)
