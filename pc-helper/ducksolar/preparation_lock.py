"""Process-wide exclusion for manual and helper history preparation."""
from contextlib import contextmanager
from pathlib import Path
import os

@contextmanager
def preparation_lock(root):
 folder=Path(root)/'Data/AndroidSupport/Preparation';folder.mkdir(parents=True,exist_ok=True)
 with (folder/'preparation.lock').open('a+b') as stream:
  stream.seek(0)
  if os.name=='nt':
   import msvcrt
   if not stream.read(1):stream.write(b'0');stream.flush()
   stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
  else:
   import fcntl
   fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:yield
  finally:
   stream.seek(0)
   if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
   else:fcntl.flock(stream,fcntl.LOCK_UN)

def running(root):
 try:
  with preparation_lock(root):return False
 except OSError:return True
