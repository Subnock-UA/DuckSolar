from pathlib import Path
import sys
def history_tool(name):
 if name not in ('prepare.py','migrate.py','sync_worker.py'):raise ValueError('Unknown history utility')
 base=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
 return base/'history_tools'/name


def worker_python():
 import os,shutil
 value=os.environ.get('DS_WORKER_PYTHON')
 if not value and not getattr(sys,'frozen',False):value=sys.executable
 if not value:value=shutil.which('python3.11') or shutil.which('python')
 if not value:raise ValueError('Set DS_WORKER_PYTHON to your Python 3.11 interpreter')
 result=Path(value).resolve()
 if not result.is_file() or (getattr(sys,'frozen',False) and result==Path(sys.executable).resolve()):
  raise ValueError('DS_WORKER_PYTHON must point to a separate Python interpreter')
 return result
