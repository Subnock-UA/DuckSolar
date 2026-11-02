"""One-time, non-destructive import explicitly requested by the owner."""
import hashlib
import json
import math
from pathlib import Path
from .config import AppConfig
from .storage import Storage


def import_snapshot(root, snapshot=None):
    if snapshot is None:
        return dict(imported=0, source_count=0, skipped='No snapshot selected')
    path = Path(snapshot)
    data = path.read_bytes()
    payload = json.loads(data)
    if payload.get('schema') != 'ducksolar.pc-meter-transfer.v1':
        raise ValueError('Unsupported meter snapshot')
    marker = 'pc_meter_transfer_' + hashlib.sha256(data).hexdigest()
    storage = Storage(AppConfig(root_dir=str(root)))
    imported = 0
    conflicts = []
    columns = ('meter_id', 'reading_date', 'import_day', 'import_night', 'export_day', 'export_night')
    with storage._db_lock, storage._connect() as con:
        if con.execute('SELECT 1 FROM app_state WHERE key=?', (marker,)).fetchone():
            return dict(imported=0, already_imported=True, source_count=len(payload['readings']))
        for row in payload['readings']:
            if not isinstance(row['meter_id'], int) or row['meter_id'] < 1:
                raise ValueError('Invalid meter ID')
            values = tuple(row[k] for k in columns)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values[2:]):
                raise ValueError('Invalid cumulative reading')
            current = con.execute('SELECT import_day,import_night,export_day,export_night FROM meter_readings WHERE meter_id=? AND reading_date=?', values[:2]).fetchone()
            if current is not None:
                if tuple(current) != values[2:]:
                    conflicts.append(dict(meter_id=values[0], reading_date=values[1], retained='phone'))
                continue
            # Transfer source values verbatim, including all historic meter IDs.
            con.execute('INSERT INTO meter_readings(meter_id,reading_date,import_day,import_night,export_day,export_night) VALUES(?,?,?,?,?,?)', values)
            imported += 1
        for row in payload.get('replacements', []):
            keys = ('replacement_date', 'old_meter_id', 'new_meter_id', 'old_final_json', 'new_initial_json')
            values = tuple(row[k] for k in keys)
            if not con.execute('SELECT 1 FROM meter_replacements WHERE replacement_date=? AND old_meter_id=? AND new_meter_id=?', values[:3]).fetchone():
                con.execute('INSERT INTO meter_replacements(replacement_date,old_meter_id,new_meter_id,old_final_json,new_initial_json) VALUES(?,?,?,?,?)', values)
        if payload.get('current_meter_id') is not None:
            con.execute("INSERT INTO app_state(key,value) VALUES('current_meter_id',?) ON CONFLICT(key) DO NOTHING", (str(payload['current_meter_id']),))
        result = dict(imported=imported, conflicts=conflicts, source_count=len(payload['readings']), source_version=payload['source_version'])
        con.execute('INSERT INTO app_state(key,value) VALUES(?,?)', (marker, json.dumps(result)))
    report = Path(root) / 'Data' / 'PC_METER_TRANSFER.json'
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
