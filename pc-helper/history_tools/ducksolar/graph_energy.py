"""Graph energy from full-resolution input, never from reduced plot points."""
from datetime import datetime, timedelta, timezone
from .energy_accounting import ZONE, stamp, number
from .energy_pair import Pair

FIELDS = ('pv_w', 'output_w', 'grid_import_w', 'grid_export_w')


def boundary(view, day, source, cancelled,edge=None):
    """Cache only two boundary samples, not another daily balance/report."""
    from .day_energy_index import cached_boundary
    cached=cached_boundary(view,day,source,edge,cancelled)
    if cached is not None:return cached
    def calculate():
        if hasattr(view.reader,'graph_endpoints'):
            return view.reader.graph_endpoints(day,source,cancelled)
        rows=view.reader.graph_day_rows(day,source,cancelled)
        return dict(first=rows[0] if rows else None,last=rows[-1] if rows else None)
    return view._cached_period(('graph-boundary-v1', day, source, str(view.reader.model_signature())),
                               [day], source, calculate, cancelled)


def accumulate(sums, coverage, previous, row, cfg, grid=True, daily=None,
               daily_coverage=None, start=None, end=None, hourly=False):
    if previous is None:
        return
    pair = Pair(previous, row, cfg.max_integration_gap_s)
    if pair.dt <= 0:
        return
    left = max((pair.x, start), key=lambda t:t.timestamp()) if start else pair.x
    stop = min((pair.y, end), key=lambda t:t.timestamp()) if end else pair.y
    fields = FIELDS if grid else FIELDS[:2]
    left_ts=left.timestamp();stop_ts=stop.timestamp()
    while left_ts < stop_ts:
        midnight = datetime(left.year, left.month, left.day, tzinfo=ZONE)
        # Use calendar boundaries, including DST days of 23/25 hours.
        if hourly:
            boundary = datetime.fromtimestamp((int(left_ts) // 3600 + 1) * 3600, ZONE)
            key = left.isoformat()
        elif daily is not None:
            boundary = midnight + timedelta(days=1)
            key = left.strftime('%Y-%m')
        else:
            boundary = (datetime(left.year + 1, 1, 1, tzinfo=ZONE) if left.month == 12
                        else datetime(left.year, left.month + 1, 1, tzinfo=ZONE))
            key = left.strftime('%Y-%m')
        right = min((stop, boundary), key=lambda t:t.timestamp())
        if hourly:
            key = datetime.fromtimestamp(int(left_ts) // 3600 * 3600, ZONE).isoformat()
        targets = [(sums.setdefault(key, {k: None for k in fields}),
                    coverage.setdefault(key, {k: 0. for k in fields}))]
        if daily is not None:
            day = left.date().isoformat()
            targets.append((daily.setdefault(day, {k: None for k in fields}),
                            daily_coverage.setdefault(day, {k: 0. for k in fields})))
        right_ts=right.timestamp();duration=right_ts-left_ts
        # Prepare the shared clipped UTC boundary once for both grid directions.
        grid_left=left.astimezone(timezone.utc) if grid else None
        grid_right=right.astimezone(timezone.utc) if grid else None
        for field in fields:
            value = None
            if field in FIELDS[:2]:
                av, bv = previous.get(field), row.get(field)
                if pair.dt <= cfg.max_integration_gap_s and number(av) and number(bv):
                    f = (left_ts - pair.xt) / pair.dt
                    g = (right_ts - pair.xt) / pair.dt
                    value = ((av + (bv-av)*f) + (av + (bv-av)*g)) * .5 * duration / 3600000
            else:
                calculated = pair._value('import' if field == 'grid_import_w' else 'export',
                                         grid_left, grid_right)
                if calculated:
                    value = calculated[0]
            if value is not None:
                for values, covered in targets:
                    values[field] = (values[field] or 0.) + value
                    covered[field] += duration
        left = right;left_ts=right_ts


def summary(points, start, end):
    """Missing intervals remain unknown; numeric values describe covered data only."""
    result = dict(unit='кВт·год', start=start.isoformat(), end=end.isoformat(),
                  basis='full_resolution', duration_seconds=end.timestamp()-start.timestamp())
    for name, field in (('generation', 'pv_w'), ('consumption', 'output_w'),
                        ('export', 'grid_export_w'), ('import', 'grid_import_w')):
        values = [p[field] for p in points if number(p.get(field))]
        covered = sum(p.get('coverage_seconds', {}).get(field, 0.) for p in points)
        result[name] = dict(kwh=sum(values) if values else None, coverage_seconds=covered,
                            partial=covered + .001 < result['duration_seconds'])
    imp, exp = result['import'], result['export']
    result['balance'] = dict(kwh=exp['kwh']-imp['kwh'] if exp['kwh'] is not None and imp['kwh'] is not None else None,
                             coverage_seconds=min(imp['coverage_seconds'], exp['coverage_seconds']),
                             partial=imp['partial'] or exp['partial'])
    result['coverage_note'] = 'Підсумки лише за наявними даними; пропуски не прирівнюються до нуля.'
    return result
