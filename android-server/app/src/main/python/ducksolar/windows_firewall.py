"""Windows-specific integration lives outside the monitoring/API core."""
from pathlib import Path
import subprocess
import sys


def ensure_firewall(logs):
    if sys.platform != 'win32':
        return {'state': 'NOT_APPLICABLE'}
    package = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    script = package / 'installer' / 'firewall.ps1'
    try:
        completed = subprocess.run(
            ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
             str(script), '-Directory', str(package)],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode:
            raise OSError('Firewall setup exit code ' + str(completed.returncode))
        logs.event('Windows Firewall rule ready', code='network.firewall.ready')
        return {'state': 'READY'}
    except (OSError, subprocess.SubprocessError) as exc:
        logs.event('Windows Firewall setup failed: ' + str(exc), code='network.firewall.failed')
        # Local API remains available even if UAC is declined or policy forbids a rule.
        return {'state': 'ERROR', 'message': 'Windows не дозволив налаштувати Firewall. LAN може бути недоступна.'}
