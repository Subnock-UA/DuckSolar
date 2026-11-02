"""Immutable input segments; expand the existing audit contract only on demand."""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4


def valid_parts(parts):
    try:
        for part in parts:
            stat = Path(part['path']).stat()
            if stat.st_size != part['size'] or stat.st_mtime_ns != part['mtime']:
                return False
            if not 0 <= part['start'] <= part['end'] <= stat.st_size:
                return False
        return bool(parts)
    except (OSError, KeyError, TypeError):
        return False


def part(path, start, end):
    stat = path.stat()
    return dict(path=str(path), start=start, end=end,
                size=stat.st_size, mtime=stat.st_mtime_ns)


def collect_unused(folder):
    """Collect only our orphaned derivatives, with a grace period for writers."""
    referenced=set()
    try:
        for manifest in folder.glob('*.summary.json'):
            value=json.loads(manifest.read_text(encoding='utf-8'))
            referenced.update(str(Path(item['path']).resolve()) for item in value.get('input_parts',[]))
    except (OSError,ValueError,KeyError,TypeError):
        return # A damaged manifest must not cause loss of its input segments.
    for path in folder.glob('.inputs-*.jsonl'):
        if path.is_symlink() or not re.fullmatch(r'\.inputs-[0-9a-f]{32}\.jsonl',path.name):continue
        try:
            if str(path.resolve()) not in referenced and time.time()-path.stat().st_mtime>3600:
                path.unlink()
        except OSError:
            pass


def inputs(parts, cancelled=lambda: False):
    from .audit_codec import expand
    if not valid_parts(parts):
        raise ValueError('Audit inputs changed; request the latest balance')
    for item in parts:
        with Path(item['path']).open('rb') as stream:
            stream.seek(item['start'])
            while stream.tell() < item['end']:
                if cancelled():
                    raise ValueError('Audit preparation cancelled')
                line = stream.readline(min(256 * 1024 + 1, item['end'] - stream.tell()))
                if not line or not line.endswith(b'\n') or len(line) > 256 * 1024:
                    raise ValueError('Invalid audit input boundary')
                value = expand(json.loads(line))
                if value.get('type') == 'input':
                    yield value['row']
    if not valid_parts(parts):
        raise ValueError('Audit inputs changed during preparation')


def materialize(summary, destination, cancelled=lambda: False):
    """Current clients get their usual synchronous, paginated object audit."""
    from .energy_streaming import _json
    from .audit_codec import compact
    from .energy_pair import Pair
    from .energy_accounting import stamp
    from .prepared_history import write_json
    if (summary.get('materialized_audit_id') == summary['report']['audit_id']
            and destination.exists()
            and destination.stat().st_size == summary.get('audit_bytes')
            and destination.stat().st_mtime_ns == summary.get('audit_mtime_ns')):
        return
    temp = destination.with_name('.audit-' + uuid4().hex + '.tmp')
    try:
        with temp.open('wb') as out:
            def write(value):
                out.write((_json(compact(value)) + '\n').encode('utf-8'))
            write(summary['audit_metadata'])
            for row in summary['checkpoint']['signature']['readings']:
                write(dict(type='meter_reading', row=row))
            previous = None
            report = summary['report']
            start, end = stamp(report['start']), stamp(report['end'])
            for row in inputs(summary['input_parts'], cancelled):
                write(dict(type='input', row=row))
                if previous is not None:
                    engine = Pair(previous, row, report['max_gap_s'])
                    for direction in ('pv', 'import', 'export'):
                        result = engine.energy(direction, start, end)
                        if result['intervals'] or result['resets']:
                            write(dict(type='interval', direction=direction, **result))
                previous = row
            write(dict(type='summary', report=report))
            out.flush()
            os.fsync(out.fileno())
        temp.replace(destination)
        stat = destination.stat()
        summary.update(materialized_audit_id=report['audit_id'],
                       audit_bytes=stat.st_size, audit_mtime_ns=stat.st_mtime_ns)
        write_json(destination.with_name(destination.name.replace('.audit.jsonl', '.summary.json')), summary)
    finally:
        temp.unlink(missing_ok=True)
