"""Run the installed PC preparation utility, without touching original CSV."""
import json,math,subprocess,threading
from pathlib import Path
from .preparation_lock import running
from .worker_launch import launch_worker,WorkerLaunchError
from .tool_paths import worker_python,history_tool
from .sync_store import atomic

KEYS={'pv_correction_factor','inverter_self_consumption_w','max_integration_gap_s','poll_interval_s','grid_present_min_v','grid_present_max_v','grid_present_min_hz','grid_present_max_hz'}
class PreparationService:
 def __init__(self,root):
  self.root=Path(root);self.lock=threading.Lock();self.process=None;self.stream=None
  self.folder=self.root/'Data/AndroidSupport/Preparation';self.folder.mkdir(parents=True,exist_ok=True)
 def start(self,model):
  from .preparation_model import decode_model
  decode_model(model)
  with self.lock:
   if (self.process and self.process.poll() is None) or running(self.root):
    if json.loads((self.folder/'model.json').read_text())!=model:raise ValueError('Another preparation model is running')
    return self.status()
   python=worker_python()
   script=history_tool('prepare.py')
   if 'generation_basis' in model:
    from .tool_paths import history_tool
    script=history_tool('prepare.py')
   if not python.is_file() or not script.is_file():raise ValueError('Configure DS_WORKER_PYTHON with a Python 3.11 interpreter and install pc-helper requirements')
   path=self.folder/'model.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(model),encoding='utf-8');temporary.replace(path)
   if self.stream:self.stream.close()
   self.stream=None
   (self.folder/'result.json').unlink(missing_ok=True)
   error_path=self.folder/'launch-error.json'
   try:self.process,self.stream=launch_worker([python,script,'--root',self.root,'--model',path],self.folder/'progress.log')
   except WorkerLaunchError as error:
    self.process=None;atomic(error_path,dict(state='error',error=str(error),**error.details));raise
   error_path.unlink(missing_ok=True)
   return self.status()
 def status(self):
  error_path=self.folder/'launch-error.json'
  if error_path.exists() and not (self.process and self.process.poll() is None):return json.loads(error_path.read_text('utf-8'))
  state='idle';code=None
  if self.process:
   code=self.process.poll();state='running' if code is None else 'completed' if code==0 else 'error'
  elif running(self.root):state='running'
  elif (self.folder/'result.json').is_file():state='completed'
  elif (self.folder/'progress.log').is_file():state='interrupted'
  log=self.folder/'progress.log';tail=''
  if log.is_file():
   with log.open('rb') as stream:
    stream.seek(max(0,log.stat().st_size-4096));tail=stream.read().decode('utf-8',errors='replace')
  return dict(state=state,exit_code=code,progress=tail)
