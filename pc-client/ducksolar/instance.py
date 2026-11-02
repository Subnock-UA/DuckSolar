import os
import tempfile
from pathlib import Path

class SingleInstanceGuard:
    def __init__(self, name="DuckSolar_Server"):
        self.name = name
        self.handle = None
        self.file = None
    def acquire(self):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            api = ctypes.windll.kernel32
            api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            api.CreateMutexW.restype = wintypes.HANDLE
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = api.CreateMutexW(None, False, ("Global\\" if self.name == "DuckSolar_Server" else "Local\\") + self.name)
            if not self.handle: return False
            if api.GetLastError() == 183:
                api.CloseHandle(self.handle); self.handle = None; return False
            return True
        import fcntl
        self.file = open(Path(tempfile.gettempdir()) / (self.name + ".lock"), "a")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self.file.close(); self.file = None; return False
    def release(self):
        if self.handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle); self.handle = None
        if self.file:
            self.file.close(); self.file = None
