from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .analytics import integrate_kwh
from .energy_accounting import seconds


@dataclass(frozen=True)
class BalanceDay:
    day: date
    pv_kwh: float
    house_kwh: float
    battery_charge_kwh: float
    grid_import_kwh: float
    export_kwh: float
    coverage_pct: float
    records: int


def coverage_percent(rows, max_gap_s: int = 900) -> float:
    if len(rows) < 2:
        return 0.0
    covered = 0.0
    for a, b in zip(rows, rows[1:]):
        dt = seconds(a["timestamp"], b["timestamp"])
        if 0 < dt <= max_gap_s:
            covered += dt
    from zoneinfo import ZoneInfo
    zone=ZoneInfo('Europe/Kyiv');day=rows[0]['timestamp'].date()
    start=datetime.combine(day,datetime.min.time(),zone);end=start+timedelta(days=1)
    now=datetime.now(zone)
    elapsed=max(1,min(end.timestamp(),now.timestamp())-start.timestamp())
    return min(100.0, covered / elapsed * 100.0)


def summarize_day(reader, day: date, source: str, max_gap_s: int = 900) -> BalanceDay:
    rows = reader.load_day(day, source)
    return BalanceDay(
        day=day,
        pv_kwh=integrate_kwh(rows, "pv_corrected_w", max_gap_s),
        house_kwh=integrate_kwh(rows, "output_w", max_gap_s),
        battery_charge_kwh=integrate_kwh(rows, "battery_charge_w", max_gap_s),
        grid_import_kwh=integrate_kwh(rows, "estimated_grid_import_w", max_gap_s),
        export_kwh=integrate_kwh(rows, "estimated_export_w", max_gap_s),
        coverage_pct=coverage_percent(rows, max_gap_s),
        records=len(rows),
    )


def summarize_month(reader, anchor: date, source: str, max_gap_s: int = 900):
    count = calendar.monthrange(anchor.year, anchor.month)[1]
    return [
        summarize_day(reader, date(anchor.year, anchor.month, n), source, max_gap_s)
        for n in range(1, count + 1)
    ]


def totals(days: list[BalanceDay]):
    return {
        "pv_kwh": sum(d.pv_kwh for d in days),
        "house_kwh": sum(d.house_kwh for d in days),
        "battery_charge_kwh": sum(d.battery_charge_kwh for d in days),
        "grid_import_kwh": sum(d.grid_import_kwh for d in days),
        "export_kwh": sum(d.export_kwh for d in days),
        "coverage_pct": (sum(d.coverage_pct for d in days) / len(days)) if days else 0.0,
        "records": sum(d.records for d in days),
    }
