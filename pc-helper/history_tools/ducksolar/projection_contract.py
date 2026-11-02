"""Portable scalar projection contract shared by PC export and Android import."""
import json
import re
import shutil
import sqlite3
from pathlib import Path

CONTRACT = 'ducksolar.scalar-inputs.v3'
DIRECTORY = 'PreparedInputs-v3'
USER_VERSION = 19


def folder(root):
    return Path(root)/'Data/EnergyWork'/DIRECTORY


def validate(path):
    if not re.fullmatch(r'[0-9a-f]{64}\.db', path.name):
        raise ValueError('Invalid scalar index name')
    con = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Damaged scalar index')
        if con.execute('PRAGMA user_version').fetchone()[0] != USER_VERSION:
            raise ValueError('Incompatible scalar index version')
        revision = con.execute('SELECT digest FROM revision WHERE id=1').fetchone()
        if not revision or revision[0] != path.stem:
            raise ValueError('Scalar index identity mismatch')
        columns = {row[1] for row in con.execute('PRAGMA table_info(scalar_inputs)')}
        if not {'ts', 'timestamp', 'pv_w', 'output_w'} <= columns:
            raise ValueError('Incomplete scalar index')
    finally:
        con.close()


def export(root, destination, cancelled=lambda:False):
    """SQLite backup includes committed WAL pages without copying live sidecars."""
    destination.mkdir(parents=True, exist_ok=True)
    members = []
    for path in sorted(folder(root).glob('*.db')):
        if cancelled():raise InterruptedError('Migration stopped')
        validate(path)
        target = destination/path.name
        source = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
        output = sqlite3.connect(str(target))
        try:
            source.backup(output)
            output.execute('PRAGMA journal_mode=DELETE')
        finally:
            output.close()
            source.close()
        validate(target)
        members.append((target, 'indices/'+path.name))
    return members


def install(root, package, manifest):
    rows = [row for row in manifest['files'] if row['name'].startswith('indices/')]
    if not rows:
        return 0  # Legacy packages remain readable; missing indexes rebuild safely.
    if manifest.get('projection_contract') != CONTRACT:
        raise ValueError('Unsupported scalar index contract')
    target = folder(root)
    target.mkdir(parents=True, exist_ok=True)
    for row in rows:
        source = package/row['name']
        if source.parent != package/'indices':
            raise ValueError('Invalid scalar index member')
        validate(source)
        destination = target/source.name
        # Maintenance has stopped all readers. Never leave an old WAL attached
        # to a newly installed main file with the same content identity.
        for suffix in ('-wal', '-shm'):
            Path(str(destination)+suffix).unlink(missing_ok=True)
        temporary = destination.with_suffix('.import.tmp')
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    return len(rows)
