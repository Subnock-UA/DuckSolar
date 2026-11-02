"""Build an unsigned portable Helper. Worker Python is configured separately."""
from pathlib import Path
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
        '--noupx','--onedir','--windowed','--name','DuckSolar_B2_Helper',
        '--add-data',str(ROOT/'locale')+os.pathsep+'locale',
        '--add-data',str(ROOT/'history_tools')+os.pathsep+'history_tools',
        str(ROOT/'update_server.py')],cwd=ROOT,check=True)

