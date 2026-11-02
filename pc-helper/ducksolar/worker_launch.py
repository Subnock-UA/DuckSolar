"""Explicit worker handles: safe for GUI, detached and headless hosts."""
import subprocess,traceback
from pathlib import Path
class WorkerLaunchError(ValueError):
 def __init__(self,error):
  self.details=dict(error_code='history.worker_launch_failed',exception_class=type(error).__name__,errno=getattr(error,'errno',None),winerror=getattr(error,'winerror',None),filename=str(getattr(error,'filename',None)),details=traceback.format_exc())
  super().__init__('Не вдалося запустити підготовку на ПК: '+str(error))
def launch_worker(arguments,log_path):
 stream=None
 try:
  stream=Path(log_path).open('ab')
  startup=None
  if hasattr(subprocess,'STARTUPINFO'):
   startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
  process=subprocess.Popen([str(x) for x in arguments],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),startupinfo=startup)
  return process,stream
 except Exception as error:
  if stream is not None:
   try:stream.write(traceback.format_exc().encode('utf-8'));stream.flush()
   finally:stream.close()
  raise WorkerLaunchError(error) from error
