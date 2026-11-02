"""Protect persisted bearer credentials with Windows DPAPI for the current user."""
import base64
import ctypes
import os
from ctypes import wintypes


def _transform(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,); kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function=crypt.CryptUnprotectData
        function.argtypes=(ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,
                           ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob))
        args=(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    else:
        function=crypt.CryptProtectData
        function.argtypes=(ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,
                           ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob))
        args=(ctypes.byref(source),'Duck Solar account',None,None,None,1,ctypes.byref(target))
    function.restype=wintypes.BOOL
    if not function(*args):raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)


def protect(value):
    if not value:return ''
    if os.name!='nt':return value
    return 'dpapi:'+base64.b64encode(_transform(value.encode())).decode('ascii')


def unprotect(value):
    if not value:return ''
    if value.startswith('dpapi:'):
        if os.name!='nt':return ''
        try:return _transform(base64.b64decode(value[6:],validate=True),True).decode()
        except (OSError,ValueError):return ''
    return value if os.name!='nt' else ''
