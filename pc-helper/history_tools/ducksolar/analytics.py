from __future__ import annotations

from collections import defaultdict
import math
from .grid_flow import grid_energy
from .energy_accounting import seconds
from datetime import date, timedelta

POWER_FIELDS = ("pv_w", "output_w")


def integrate_kwh(rows, field: str, max_gap_s: int = 900) -> float:
    total_ws = 0.0
    prev = None
    for row in rows:
        value = row.get(field)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            prev = None
            continue
        if prev is not None:
            dt = seconds(prev[0], row["timestamp"])
            if 0 < dt <= max_gap_s:
                total_ws += (prev[1] + float(value)) * 0.5 * dt
        prev = (row["timestamp"], float(value))
    return total_ws / 3_600_000.0


def daily_energy(rows, max_gap_s=900):
    result = {field: integrate_kwh(rows, field, max_gap_s) for field in POWER_FIELDS}
    result['grid_import_w'] = grid_energy(rows, 'import', max_gap_s)[0]
    result['grid_export_w'] = grid_energy(rows, 'export', max_gap_s)[0]
    return result


def month_days(anchor: date):
    first = anchor.replace(day=1)
    if first.month == 12: nxt = date(first.year+1, 1, 1)
    else: nxt = date(first.year, first.month+1, 1)
    d = first
    while d < nxt:
        yield d
        d += timedelta(days=1)


def aggregate_month(reader, anchor: date, source: str, max_gap_s=900):
    out = []
    for d in month_days(anchor):
        rows = reader.load_day(d, source)
        if rows:
            out.append((d, daily_energy(rows, max_gap_s)))
    return out


def aggregate_year(reader, year: int, source: str, max_gap_s=900):
    sums = defaultdict(lambda: defaultdict(float))
    for d in reader.available_dates():
        if d.year != year: continue
        rows = reader.load_day(d, source)
        if not rows: continue
        e = daily_energy(rows, max_gap_s)
        for k, v in e.items(): sums[d.month][k] += v
    return [(month, dict(sums[month])) for month in sorted(sums)]


def aggregate_all(reader, source: str, max_gap_s=900):
    sums = defaultdict(lambda: defaultdict(float))
    for d in reader.available_dates():
        rows = reader.load_day(d, source)
        if not rows: continue
        e = daily_energy(rows, max_gap_s)
        key = (d.year, d.month)
        for k, v in e.items(): sums[key][k] += v
    return [(key, dict(sums[key])) for key in sorted(sums)]


def derive_events(rows):
    events = []
    prev = None
    prev_pv_on = None
    prev_bat = None
    for row in rows:
        ts = row["timestamp"]
        source = row.get("source", "")
        if prev is not None:
            if row.get("mode") != prev.get("mode") and row.get("mode"):
                events.append((ts, "Режим", f"{prev.get('mode','—')} → {row.get('mode')}", source))
            if row.get("grid_available") != prev.get("grid_available"):
                events.append((ts, "Мережа", "Відновлена" if row.get("grid_available") else "Відсутня", source))
            warning = str(row.get("warnings") or "").strip()
            old_warning = str(prev.get("warnings") or "").strip()
            if warning != old_warning and warning and set(warning) != {"0"}:
                events.append((ts, "Попередження", warning, source))
        pv_on = (float(row.get("pv_w") or 0) >= 50)
        if prev_pv_on is not None and pv_on != prev_pv_on:
            events.append((ts, "PV", "Генерація почалась" if pv_on else "Генерація завершилась", source))
        prev_pv_on = pv_on
        ch = float(row.get("charge_a") or 0)
        dis = float(row.get("discharge_a") or 0)
        bat = "Заряд" if ch >= 1 else "Розряд" if dis >= 1 else "Очікування"
        if prev_bat is not None and bat != prev_bat:
            events.append((ts, "АКБ", bat, source))
        prev_bat = bat
        prev = row
    return events
