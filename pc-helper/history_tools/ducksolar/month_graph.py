"""Independent, restartable month contributions; no daily balance reports."""
import hashlib
import json
from datetime import date, datetime, timedelta

from .energy_accounting import ZONE, stamp
from .energy_streaming import (_files, _ordered_rows, _resume_checkpoint,
                               _prefix_hash, _json, _hash_context)
from .prepared_history import write_json


def add_pair(sums, coverage, previous, row, cfg, grid, daily=None, daily_coverage=None):
    from .graph_energy import accumulate
    accumulate(sums, coverage, previous, row, cfg, grid, daily, daily_coverage)


def month(view, anchor, source, grid, cancelled):
    from .concurrency import keyed_lock,path_key
    target=view.view_path/f'month-energy-v4-{anchor:%Y-%m}-{source}-{int(grid)}.json'
    with keyed_lock(path_key('month-graph',target),cancelled):
        return _month(view,anchor,source,grid,cancelled)

def _month(view, anchor, source, grid, cancelled):
    reader, cfg = view.reader, view.cfg
    start = datetime(anchor.year, anchor.month, 1, tzinfo=ZONE)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    stats = dict(range_start=start.timestamp(), range_end=end.timestamp(),
                 used_records=0, opened_files=0, read_records=0, projection_hits=0)
    reader._balance_stats = stats
    token = _hash_context.set(({}, stats))
    try:
        files = [entry for entry in _files(reader, start, end, source, cancelled)
                 if (entry[2].year, entry[2].month) == (anchor.year, anchor.month)]
        from .compact_history import schema_path
        schemas = [(str(p), _prefix_hash(schema_path(p), schema_path(p).stat().st_size, cancelled))
                   for p, origin, day, size, mtime in files if schema_path(p).exists()]
        reader._balance_schemas = dict(schemas)
        signature = dict(algorithm='graph.month.v4', start=start.isoformat(),
                         device_id=view.device_id, source=source,
                         model=reader.model_signature(), readings=[], end=None,
                         files=[(str(p), o, d.isoformat(), size, mtime) for p, o, d, size, mtime in files],
                         schemas=schemas, grid=grid)
        from .compact_history import schema_contract
        signature['schema_contracts']={key:schema_contract(json.loads(schema_path(key).read_text(encoding='utf-8'))) for key,_ in schemas}
        if source != 'Local':
            signature['history_semantics'] = 'smartess-missing-v2'
        digest = hashlib.sha256(_json(signature).encode()).hexdigest()
        cache = view.view_path / f'month-energy-v4-{anchor:%Y-%m}-{source}-{int(grid)}.json'
        old = None
        try:
            old = json.loads(cache.read_text(encoding='utf-8'))
            if old['signature'] == digest:
                return old['value'], dict(cache_hit=True, incremental=False, new_rows=0)
        except (OSError, ValueError, KeyError):
            old = None
        resume = _resume_checkpoint(old, files, reader, signature, end, cancelled) if old else None
        value = json.loads(_json(old['value'])) if resume else dict(sums={}, coverage={}, daily={}, daily_coverage={}, records=0, first=None, last=None)
        previous = resume['last_row'] if resume else None
        after = stamp(previous['timestamp']).timestamp() if previous else None
        work = files
        if resume:
            sizes = {p['path']: p['size'] for p in resume['prefixes']}
            work = [e for e in files if str(e[0]) not in sizes or e[3] > sizes[str(e[0])]]
        fields = ('pv_w', 'output_w', 'grid_import_w', 'grid_export_w') if grid else ('pv_w', 'output_w')
        captured={str(p):_prefix_hash(p,size,cancelled) for p,origin,day,size,mtime in work}
        from .cpu_energy import graph as cpu_graph,BLOCK
        pending=[];batch_previous=previous
        with _ordered_rows(reader, work, source, cancelled, after,
                           resume.get('merge_last_local') if resume else None) as rows:
            for row in rows:
                if cancelled():
                    raise ValueError('History query cancelled')
                key = stamp(row['timestamp']).strftime('%Y-%m')
                value['sums'].setdefault(key, {k: None for k in fields})
                value['coverage'].setdefault(key, {k: 0. for k in fields})
                pending.append(row)
                if len(pending)>=BLOCK:
                    cpu_graph(value['sums'],value['coverage'],batch_previous,pending,cfg,grid,value['daily'],value['daily_coverage'],cancelled=cancelled)
                    batch_previous=row;pending=[]
                if value['first'] is None:
                    value['first'] = row
                previous = row
                value['records'] += 1
                stats['used_records'] += 1
        if pending:cpu_graph(value['sums'],value['coverage'],batch_previous,pending,cfg,grid,value['daily'],value['daily_coverage'],cancelled=cancelled)
        value['last'] = previous
        prior = {p['path']: p for p in resume['prefixes']} if resume else {}
        prefixes = []
        for p, origin, day, size, mtime in files:
            saved = prior.get(str(p))
            sha = saved['digest'] if saved and saved['size'] == size and saved['mtime'] == mtime else _prefix_hash(p, size, cancelled)
            if str(p) in captured and sha!=captured[str(p)]:
                raise ValueError('Graph source prefix changed during calculation')
            prefixes.append(dict(path=str(p), size=size, mtime=mtime, digest=sha))
        checkpoint = dict(signature=signature, last_row=previous, count=value['records'], prefixes=prefixes,
                          merge_last_local=stats.get('merge_last_local', resume.get('merge_last_local') if resume else None))
        # Save the captured prefix even if new rows arrived during calculation.
        # Prefix validation will prove append-only reuse on the next request.
        write_json(cache, dict(signature=digest, checkpoint=checkpoint,
                              report=dict(end=end.isoformat()), value=value))
        return value, dict(cache_hit=False, incremental=bool(resume),
                           new_rows=stats['used_records'],
                           checkpoint_rejected=stats.get('checkpoint_rejected'))
    finally:
        reader._balance_schemas={}
        _hash_context.reset(token)


def period(view, days, source, grid, cancelled, progress):
    sums, coverage, records, previous = {}, {}, 0, None
    details = []
    months = sorted({(d.year, d.month) for d in days})
    if progress:
        progress(0, len(months))
    for index, (year, month_number) in enumerate(months):
        if cancelled():
            raise ValueError('History query cancelled')
        value, diagnostics = month(view, date(year, month_number, 1), source, grid, cancelled)
        add_pair(sums, coverage, previous, value['first'], view.cfg, grid) if value['first'] else None
        for key, values in value['sums'].items():
            target = sums.setdefault(key, {k: None for k in values})
            covered = coverage.setdefault(key, {k: 0. for k in values})
            for field, amount in values.items():
                if amount is not None:
                    target[field] = (target[field] or 0) + amount
                covered[field] += value['coverage'][key][field]
        records += value['records']
        if value['last']:
            previous = value['last']
        details.append(dict(period=f'{year:04d}-{month_number:02d}', **diagnostics))
        if progress:
            progress(index + 1, len(months))
    view._month_graph_diagnostics = details
    return dict(months=[dict(year=int(key[:4]), month=int(key[5:]), energy=values,
                            coverage=coverage[key]) for key, values in sorted(sums.items())], records=records)
