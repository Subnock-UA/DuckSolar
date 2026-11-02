"""Protocol-neutral grid measurements and explicitly marked fallback estimates.

Driver contract: W for powers, kWh for cumulative energy; quality good/missing/
invalid/stale, optional timestamp, source and meter_id. Signed net power requires
positive_direction='import' or 'export' supplied by the device driver.
"""
import copy
import math
from .energy_accounting import seconds
from datetime import datetime


LABELS = {
    'grid.measured_import_power': 'Виміряний імпорт',
    'grid.measured_export_power': 'Виміряна віддача',
    'grid.import_power': 'Імпорт з мережі',
    'grid.export_power': 'Віддача в мережу',
    'grid.import_energy_total': 'Накопичена енергія імпорту',
    'grid.export_energy_total': 'Накопичена енергія експорту',
}


def valid_metric(item, unit, now=None, max_age_s=30, signed=False):
    if not isinstance(item, dict) or item.get('unit') != unit:
        return False
    value = item.get('value')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    if not signed and value < 0:
        return False
    if item.get('stale') or item.get('quality', 'unknown') != 'good':
        return False
    if now is not None and item.get('timestamp'):
        try:
            stamp = datetime.fromisoformat(item['timestamp'])
            if stamp.tzinfo and not now.tzinfo:
                stamp = stamp.astimezone().replace(tzinfo=None)
            elif now.tzinfo and not stamp.tzinfo:
                stamp = stamp.astimezone()
            age = now.timestamp()-stamp.timestamp()
            if age < -5 or age > max_age_s:
                return False
        except (ValueError, TypeError):
            return False
    return True


def expand_signed_measurements(normalized, now=None, max_age_s=30, *, owned=False):
    # Accounting constructs a fresh projection for each CSV row. It owns that
    # object, while callers presenting live state still receive an isolated copy.
    result = normalized if owned else copy.deepcopy(normalized)
    metrics = result.setdefault('metrics', {})
    context = result.get('grid',{}).get('measurement_context',{})
    for key,item in metrics.items():
        is_sensor = key.startswith('grid.measured_') or key in ('grid.import_energy_total','grid.export_energy_total')
        if is_sensor and isinstance(item,dict):
            sensor = item.get('sensor_status',context.get('sensor_status'))
            if sensor in ('missing','fault','disabled','unknown','unconfirmed'):
                item.setdefault('driver_quality',item.get('quality','unknown'))
                item['quality'] = 'invalid'
                item['validation_reason'] = 'sensor_'+sensor
    net = metrics.get('grid.measured_net_power')
    if valid_metric(net, 'W', now, max_age_s, signed=True) and net.get('positive_direction') in ('import','export'):
        imported = net['value'] if net['positive_direction'] == 'import' else -net['value']
        for direction, value in (('import', max(0.0, imported)), ('export', max(0.0, -imported))):
            key = 'grid.measured_'+direction+'_power'
            previous = metrics.get(key)
            rejected = isinstance(previous,dict) and bool(previous.get('validation_reason'))
            if not valid_metric(previous, 'W', now, max_age_s) and not rejected:
                metrics[key] = {**net, 'value': value, 'derived_from': 'grid.measured_net_power'}
    return result


def select_grid_flows(normalized, now=None, max_age_s=30, *, owned=False):
    result = expand_signed_measurements(normalized, now, max_age_s, owned=owned)
    metrics = result.setdefault('metrics', {})
    for direction in ('import', 'export'):
        measured_key = 'grid.measured_'+direction+'_power'
        estimate_key = 'grid.estimated_'+direction+'_power'
        measured, estimate = metrics.get(measured_key), metrics.get(estimate_key)
        if valid_metric(measured, 'W', now, max_age_s):
            selected = {**measured, 'measurement_kind': 'measured', 'selected_from': measured_key}
        elif valid_metric(estimate, 'W', now, max_age_s):
            selected = {**estimate, 'measurement_kind': 'estimated', 'selected_from': estimate_key}
        else:
            selected = {'value': None, 'unit': 'W', 'quality': 'missing',
                        'measurement_kind': 'unavailable', 'source': None}
        reason = measured.get('validation_reason') if isinstance(measured,dict) else None
        if selected['measurement_kind'] != 'measured':
            if not reason:
                reason = 'measurement_missing' if measured is None else 'measurement_quality_unknown' if measured.get('quality','unknown') != 'good' else 'measurement_stale_or_invalid'
            selected['fallback_reason'] = reason
        metrics['grid.'+direction+'_power'] = selected
    return result


def flat_grid_fields(normalized, now=None, max_age_s=30):
    metrics = normalized.get('metrics', {})
    fields = {}
    for direction in ('import', 'export'):
        selected = metrics.get('grid.'+direction+'_power', {})
        fields['grid_'+direction+'_w'] = selected.get('value')
        fields['grid_'+direction+'_source'] = selected.get('measurement_kind', 'unavailable')
        fields['grid_'+direction+'_origin'] = selected.get('source') or ''
        fields['grid_'+direction+'_reason'] = selected.get('fallback_reason') or ''
        measured = metrics.get('grid.measured_'+direction+'_power', {})
        fields['measured_grid_'+direction+'_w'] = measured.get('value')
        fields['measured_grid_'+direction+'_valid'] = int(valid_metric(measured,'W',now,max_age_s))
        counter = metrics.get('grid.'+direction+'_energy_total', {})
        fields['grid_'+direction+'_energy_total_kwh'] = counter.get('value') if valid_metric(counter,'kWh',now,max_age_s) else None
        fields['grid_'+direction+'_counter_id'] = str(counter.get('meter_id') or counter.get('source') or 'device')
    return fields


def decorate_descriptor(descriptor, normalized):
    result = copy.deepcopy(descriptor)
    metrics = normalized.get('metrics', {})
    result['available_metrics'] = list(dict.fromkeys([*result.get('available_metrics', []), *metrics]))
    specs = result.setdefault('metric_definitions', [])
    existing = {item['canonical_id'] for item in specs}
    for key, label in LABELS.items():
        if key in metrics and key not in existing:
            item = metrics[key]
            specs.append(dict(canonical_id=key, ui_name=label, unit=item.get('unit',''),
                              source=item.get('source'), confidence=item.get('confidence','unverified')))
    result['grid_flow_capabilities'] = {
        'measured_import_power': 'grid.measured_import_power' in metrics,
        'measured_export_power': 'grid.measured_export_power' in metrics,
        'signed_net_power': 'grid.measured_net_power' in metrics,
        'import_energy_counter': 'grid.import_energy_total' in metrics,
        'export_energy_counter': 'grid.export_energy_total' in metrics,
    }
    return result


def grid_energy(rows, direction, max_gap_s=900):
    """Counters first per interval, otherwise selected power; never add both."""
    total = 0.0
    sources = set()
    field = 'grid_'+direction+'_w'
    counter = 'grid_'+direction+'_energy_total_kwh'
    identity = 'grid_'+direction+'_counter_id'
    for a, b in zip(rows, rows[1:]):
        dt = seconds(a['timestamp'], b['timestamp'])
        if dt<=0:continue
        first, last = a.get(counter), b.get(counter)
        numeric = lambda v: isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
        if numeric(first) and numeric(last) and last >= first and a.get(identity) == b.get(identity):
            total += last-first
            sources.add('counter')
            continue
        if dt>max_gap_s:continue
        first, last = a.get(field), b.get(field)
        kind = a.get('grid_'+direction+'_source', 'unavailable')
        if numeric(first) and numeric(last) and kind == b.get('grid_'+direction+'_source') and a.get('grid_'+direction+'_origin') == b.get('grid_'+direction+'_origin'):
            total += (first+last)*0.5*dt/3_600_000.0
            sources.add(kind)
    source = next(iter(sources)) if len(sources) == 1 else 'mixed' if sources else 'unavailable'
    return total, source


def source_label(source):
    return {'measured':'виміряно', 'estimated':'розраховано', 'counter':'лічильник інвертора',
            'mixed':'змішані джерела', 'unavailable':'немає даних'}.get(source, source)


def reason_label(reason):
    return {
        'zero_balance_mismatch':'нуль суперечить балансу потужності',
        'sensor_missing':'датчик відсутній', 'sensor_fault':'помилка датчика',
        'sensor_disabled':'датчик вимкнений', 'sensor_unknown':'стан датчика невідомий',
        'sensor_unconfirmed':'датчик не підтверджений',
        'measurement_missing':'немає вимірювання',
        'measurement_quality_unknown':'якість вимірювання не підтверджена',
        'measurement_stale_or_invalid':'вимірювання застаріле або недійсне',
    }.get(reason,reason)
