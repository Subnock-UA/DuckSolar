from __future__ import annotations

import csv
from contextlib import contextmanager
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import AppConfig, ensure_dirs
from .meter import MeterValues, validate_monotonic


TELEMETRY_COLUMNS = [
    "time", "source", "device_id", "normalized_json",
    "grid_available",
    "grid_v", "grid_hz",
    "output_v", "output_hz", "output_va", "output_w", "load_pct",
    "bus_v",
    "battery_v", "battery_pct", "charge_a", "discharge_a",
    "battery_estimated_pct", "battery_remaining_kwh", "battery_inverter_pct", "battery_estimate_confidence",
    "battery_charge_w",
    "temperature_c",
    "pv_v", "pv_a", "pv_w", "pv_corrected_w",
    "estimated_grid_import_w", "estimated_export_w",
    'grid_import_w',
    'grid_import_source',
    'grid_import_origin',
    'measured_grid_import_w',
    'measured_grid_import_valid',
    'grid_import_energy_total_kwh',
    'grid_import_counter_id',
    'grid_export_w',
    'grid_export_source',
    'grid_export_origin',
    'measured_grid_export_w',
    'measured_grid_export_valid',
    'grid_export_energy_total_kwh',
    'grid_export_counter_id',
    "grid_import_reason", "grid_export_reason",
    "scc_battery_v",
    "mode", "warnings",
    "device_status", "service_field", "eeprom_version", "extra_status",
]


@dataclass
class TelemetryRecord:
    timestamp: datetime
    source: str
    values: dict[str, Any]
    device_id: str = ''


class Storage:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.paths = ensure_dirs(cfg)
        self._db_lock = threading.RLock()
        self._csv_lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.paths["db"], timeout=30)
        try:
            with con:
                yield con
        finally:
            con.close()

    def _init_db(self):
        with self._db_lock, self._connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS device_telemetry_index (
                device_id TEXT NOT NULL, timestamp TEXT NOT NULL, source TEXT NOT NULL,
                csv_path TEXT NOT NULL, PRIMARY KEY(device_id,timestamp,source))''')
            con.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_index (
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    csv_path TEXT NOT NULL,
                    PRIMARY KEY(timestamp, source)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS meter_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meter_id INTEGER NOT NULL DEFAULT 1,
                    reading_date TEXT NOT NULL,
                    import_day REAL NOT NULL,
                    import_night REAL NOT NULL,
                    export_day REAL NOT NULL,
                    export_night REAL NOT NULL DEFAULT 0,
                    UNIQUE(meter_id, reading_date)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS meter_replacements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    replacement_date TEXT NOT NULL,
                    old_meter_id INTEGER NOT NULL,
                    new_meter_id INTEGER NOT NULL,
                    old_final_json TEXT NOT NULL,
                    new_initial_json TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS tariff_history (
                    effective_from TEXT PRIMARY KEY,
                    uah_per_kwh REAL NOT NULL,
                    source TEXT NOT NULL,
                    resolution_number TEXT,
                    resolution_date TEXT,
                    downloaded_at TEXT,
                    user_override INTEGER NOT NULL DEFAULT 0
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS finance_rate_history (
                    effective_from TEXT PRIMARY KEY,
                    retail_day_tariff_uah REAL NOT NULL,
                    retail_night_factor REAL NOT NULL,
                    pit_pct REAL NOT NULL,
                    military_pct REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS retail_tariff_history (
                    effective_from TEXT PRIMARY KEY,
                    retail_day_tariff_uah REAL NOT NULL,
                    retail_night_factor REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS tax_rate_history (
                    effective_from TEXT PRIMARY KEY,
                    pit_pct REAL NOT NULL,
                    military_pct REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL
                )
            """)
            # One-time-compatible migration from the combined history used in
            # early Alpha revisions. Separate histories let retail tariffs and
            # taxes change independently without overwriting each other's dates.
            con.execute(
                "INSERT OR IGNORE INTO retail_tariff_history(effective_from,retail_day_tariff_uah,retail_night_factor,source,created_at) "
                "SELECT effective_from,retail_day_tariff_uah,retail_night_factor,source,created_at FROM finance_rate_history"
            )
            con.execute(
                "INSERT OR IGNORE INTO tax_rate_history(effective_from,pit_pct,military_pct,source,created_at) "
                "SELECT effective_from,pit_pct,military_pct,source,created_at FROM finance_rate_history"
            )
            con.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            con.commit()

    def append_telemetry(self, rec: TelemetryRecord) -> None:
        from .core.models import checked_id
        device_id=checked_id(rec.device_id or self.cfg.legacy_device_id)
        day = rec.timestamp.date().isoformat()
        folder=Path(self.cfg.root_dir)/'Data/CompactHistory'/device_id/rec.source
        if rec.source not in ('Local','SmartESS'):raise ValueError('Unsupported telemetry source')
        folder.mkdir(parents=True,exist_ok=True)
        csv_path = folder / f"{day}.csv"

        row = {c: "" for c in TELEMETRY_COLUMNS}
        row.update({
            "time": rec.timestamp.isoformat(sep=" ", timespec="microseconds"),
            "source": rec.source,
            **rec.values,
            "device_id":device_id,
        })
        from .compact_history import Codec


        with self._csv_lock, self._db_lock, self._connect() as con:
            exists = con.execute('SELECT 1 FROM device_telemetry_index WHERE device_id=? AND timestamp=? AND source=?',
                                 (device_id,row['time'],rec.source)).fetchone()
            if exists:
                return
            codec=getattr(self,'_compact_codecs',{}).get(str(csv_path))
            if codec is None:
                codec=Codec(csv_path,TELEMETRY_COLUMNS)
                if not hasattr(self,'_compact_codecs'):self._compact_codecs={}
                self._compact_codecs={str(csv_path):codec}
            codec.append(row)

            con.execute('INSERT OR IGNORE INTO device_telemetry_index VALUES(?,?,?,?)',
                        (device_id,row['time'],rec.source,str(csv_path)))
            if device_id==self.cfg.legacy_device_id:
                con.execute('INSERT OR IGNORE INTO telemetry_index(timestamp, source, csv_path) VALUES (?, ?, ?)',
                            (row['time'],rec.source,str(csv_path)))
            con.commit()

    def get_current_meter_id(self) -> int:
        with self._db_lock, self._connect() as con:
            row = con.execute("SELECT value FROM app_state WHERE key='current_meter_id'").fetchone()
            if row:
                try:
                    return max(1, int(row[0]))
                except (TypeError, ValueError):
                    pass
            row = con.execute("SELECT MAX(meter_id) FROM meter_readings").fetchone()
            return max(1, int(row[0] or 1))

    def list_meter_readings(self, meter_id: int | None = None, limit: int = 1000):
        sql = "SELECT id,meter_id,reading_date,import_day,import_night,export_day,export_night FROM meter_readings"
        args: list[Any] = []
        if meter_id is not None:
            sql += " WHERE meter_id=?"
            args.append(int(meter_id))
        sql += " ORDER BY reading_date DESC, id DESC LIMIT ?"
        args.append(max(1, int(limit)))
        with self._db_lock, self._connect() as con:
            rows = con.execute(sql, args).fetchall()
        return [
            {
                "id": r[0], "meter_id": r[1], "reading_date": r[2],
                "import_day": r[3], "import_night": r[4],
                "export_day": r[5], "export_night": r[6],
            }
            for r in rows
        ]

    def latest_meter_reading(self, meter_id: int | None = None):
        mid = int(meter_id or self.get_current_meter_id())
        rows = self.list_meter_readings(mid, limit=1)
        return rows[0] if rows else None

    @staticmethod
    def _meter_values_from_row(row) -> MeterValues:
        return MeterValues(float(row[3]), float(row[4]), float(row[5]), float(row[6]))

    def _validate_meter_position(self, con, meter_id: int, reading_date: str, values: MeterValues) -> None:
        prev = con.execute(
            "SELECT id,meter_id,reading_date,import_day,import_night,export_day,export_night "
            "FROM meter_readings WHERE meter_id=? AND reading_date<? ORDER BY reading_date DESC LIMIT 1",
            (meter_id, reading_date),
        ).fetchone()
        nxt = con.execute(
            "SELECT id,meter_id,reading_date,import_day,import_night,export_day,export_night "
            "FROM meter_readings WHERE meter_id=? AND reading_date>? ORDER BY reading_date ASC LIMIT 1",
            (meter_id, reading_date),
        ).fetchone()
        if prev:
            validate_monotonic(self._meter_values_from_row(prev), values)
        if nxt:
            validate_monotonic(values, self._meter_values_from_row(nxt))

    def add_meter_reading(self, reading_date: str, values: MeterValues, meter_id: int | None = None) -> int:
        mid = int(meter_id or self.get_current_meter_id())
        with self._db_lock, self._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM meter_readings WHERE meter_id=? AND reading_date=?",
                (mid, reading_date),
            ).fetchone()
            if exists:
                raise ValueError("Для цього лічильника вже є показник з такою датою і часом.")
            self._validate_meter_position(con, mid, reading_date, values)
            cur = con.execute(
                "INSERT INTO meter_readings(meter_id,reading_date,import_day,import_night,export_day,export_night) VALUES(?,?,?,?,?,?)",
                (mid, reading_date, values.import_day, values.import_night, values.export_day, values.export_night),
            )
            con.commit()
            return int(cur.lastrowid)

    def replace_meter(self, replacement_date: str, old_final: MeterValues, new_initial: MeterValues) -> int:
        old_id = self.get_current_meter_id()
        with self._db_lock, self._connect() as con:
            duplicate = con.execute(
                "SELECT 1 FROM meter_readings WHERE meter_id=? AND reading_date=?",
                (old_id, replacement_date),
            ).fetchone()
            if duplicate:
                raise ValueError("На момент заміни вже існує запис старого лічильника. Змініть час на одну хвилину.")
            self._validate_meter_position(con, old_id, replacement_date, old_final)
            max_id = con.execute("SELECT MAX(meter_id) FROM meter_readings").fetchone()[0]
            new_id = max(old_id + 1, int(max_id or 0) + 1)
            con.execute(
                "INSERT INTO meter_readings(meter_id,reading_date,import_day,import_night,export_day,export_night) VALUES(?,?,?,?,?,?)",
                (old_id, replacement_date, old_final.import_day, old_final.import_night, old_final.export_day, old_final.export_night),
            )
            con.execute(
                "INSERT INTO meter_readings(meter_id,reading_date,import_day,import_night,export_day,export_night) VALUES(?,?,?,?,?,?)",
                (new_id, replacement_date, new_initial.import_day, new_initial.import_night, new_initial.export_day, new_initial.export_night),
            )
            con.execute(
                "INSERT INTO meter_replacements(replacement_date,old_meter_id,new_meter_id,old_final_json,new_initial_json) VALUES(?,?,?,?,?)",
                (replacement_date, old_id, new_id, json.dumps(old_final.__dict__, ensure_ascii=False), json.dumps(new_initial.__dict__, ensure_ascii=False)),
            )
            con.execute(
                "INSERT INTO app_state(key,value) VALUES('current_meter_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_id),),
            )
            con.commit()
            return new_id


    def delete_meter_reading(self, reading_id: int) -> None:
        rid = int(reading_id)
        with self._db_lock, self._connect() as con:
            row = con.execute(
                "SELECT id,meter_id,reading_date FROM meter_readings WHERE id=?",
                (rid,),
            ).fetchone()
            if not row:
                raise ValueError("Запис лічильника вже відсутній.")

            linked = con.execute(
                "SELECT 1 FROM meter_replacements "
                "WHERE replacement_date=? AND (old_meter_id=? OR new_meter_id=?) LIMIT 1",
                (row[2], row[1], row[1]),
            ).fetchone()
            if linked:
                raise ValueError(
                    "Цей запис є частиною процедури «Заміна лічильника» і не може бути видалений окремо."
                )

            con.execute("DELETE FROM meter_readings WHERE id=?", (rid,))
            con.commit()

    def seed_user_meter_readings(self) -> int:
        """Compatibility entry point: public builds never prefill meter history."""
        return 0

    def get_app_state(self, key: str, default: str | None = None):
        with self._db_lock, self._connect() as con:
            row = con.execute("SELECT value FROM app_state WHERE key=?", (str(key),)).fetchone()
        return row[0] if row else default

    def set_app_state(self, key: str, value: str) -> None:
        with self._db_lock, self._connect() as con:
            con.execute(
                "INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(key), str(value)),
            )
            con.commit()

    def seed_tariff_history(self) -> int:
        """Known official quarterly UAH/kWh rates for a 2025-commissioned household solar installation."""
        rows = [
            ("2025-10-01", 6.3916, "official", "1568", "2025-09-30"),
            ("2026-01-01", 6.5150, "official", "2263", "2025-12-30"),
            ("2026-04-01", 6.6944, "official", "498", "2026-03-31"),
            ("2026-07-01", 6.7991, "official", "1029", "2026-06-30"),
            ("2026-10-01", 6.8001, "official", "1613", "2026-09-29"),
        ]
        count = 0
        with self._db_lock, self._connect() as con:
            for effective, rate, source, number, rdate in rows:
                cur = con.execute(
                    "INSERT OR IGNORE INTO tariff_history("
                    "effective_from,uah_per_kwh,source,resolution_number,resolution_date,downloaded_at,user_override"
                    ") VALUES(?,?,?,?,?,?,0)",
                    (effective, rate, source, number, rdate, datetime.now().isoformat(timespec='seconds'))
                )
                count += int(cur.rowcount or 0)
            con.commit()
        return count

    def tariff_for_date(self, day_iso: str):
        with self._db_lock, self._connect() as con:
            row = con.execute(
                "SELECT effective_from,uah_per_kwh,source,resolution_number,resolution_date,downloaded_at,user_override "
                "FROM tariff_history WHERE effective_from<=? ORDER BY effective_from DESC LIMIT 1",
                (day_iso,),
            ).fetchone()
        if not row:
            return None
        return {
            "effective_from": row[0], "uah_per_kwh": float(row[1]), "source": row[2],
            "resolution_number": row[3], "resolution_date": row[4],
            "downloaded_at": row[5], "user_override": bool(row[6]),
        }

    def upsert_tariff(self, effective_from: str, uah_per_kwh: float, source: str,
                      resolution_number: str = "", resolution_date: str = "",
                      user_override: bool = False) -> None:
        with self._db_lock, self._connect() as con:
            con.execute(
                "INSERT INTO tariff_history(effective_from,uah_per_kwh,source,resolution_number,resolution_date,downloaded_at,user_override) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(effective_from) DO UPDATE SET "
                "uah_per_kwh=excluded.uah_per_kwh,source=excluded.source,resolution_number=excluded.resolution_number,"
                "resolution_date=excluded.resolution_date,downloaded_at=excluded.downloaded_at,user_override=excluded.user_override",
                (effective_from, float(uah_per_kwh), source, resolution_number, resolution_date,
                 datetime.now().isoformat(timespec='seconds'), int(bool(user_override))),
            )
            con.commit()

    @staticmethod
    def _validate_effective_date(effective_from: str) -> str:
        value = str(effective_from)
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Дата початку дії має формат РРРР-ММ-ДД.") from exc
        return value

    def seed_finance_rate_history(self) -> int:
        """Seed independent retail and tax histories for fresh databases."""
        effective = "2025-01-01"
        created = datetime.now().isoformat(timespec="seconds")
        inserted = 0
        with self._db_lock, self._connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO retail_tariff_history("
                "effective_from,retail_day_tariff_uah,retail_night_factor,source,created_at) VALUES(?,?,?,?,?)",
                (effective, float(self.cfg.retail_day_tariff_uah), float(self.cfg.retail_night_factor), "default", created),
            )
            inserted += int(cur.rowcount or 0)
            cur = con.execute(
                "INSERT OR IGNORE INTO tax_rate_history("
                "effective_from,pit_pct,military_pct,source,created_at) VALUES(?,?,?,?,?)",
                (effective, float(self.cfg.personal_income_tax_pct), float(self.cfg.military_tax_pct), "default", created),
            )
            inserted += int(cur.rowcount or 0)
            # Keep legacy table populated for backward compatibility with old
            # database tools, but calculations below use the split histories.
            con.execute(
                "INSERT OR IGNORE INTO finance_rate_history("
                "effective_from,retail_day_tariff_uah,retail_night_factor,pit_pct,military_pct,source,created_at"
                ") VALUES(?,?,?,?,?,?,?)",
                (effective, float(self.cfg.retail_day_tariff_uah), float(self.cfg.retail_night_factor),
                 float(self.cfg.personal_income_tax_pct), float(self.cfg.military_tax_pct), "default", created),
            )
            con.commit()
        return inserted

    def upsert_retail_tariff_rates(
        self, effective_from: str, retail_day_tariff_uah: float,
        retail_night_factor: float, source: str = "manual",
    ) -> None:
        effective_from = self._validate_effective_date(effective_from)
        vals = (max(0.0, float(retail_day_tariff_uah)), max(0.0, float(retail_night_factor)))
        with self._db_lock, self._connect() as con:
            con.execute(
                "INSERT INTO retail_tariff_history(effective_from,retail_day_tariff_uah,retail_night_factor,source,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(effective_from) DO UPDATE SET "
                "retail_day_tariff_uah=excluded.retail_day_tariff_uah,retail_night_factor=excluded.retail_night_factor,"
                "source=excluded.source,created_at=excluded.created_at",
                (effective_from, *vals, str(source), datetime.now().isoformat(timespec="seconds")),
            )
            con.commit()

    def upsert_tax_rates(
        self, effective_from: str, pit_pct: float, military_pct: float,
        source: str = "manual",
    ) -> None:
        effective_from = self._validate_effective_date(effective_from)
        vals = (max(0.0, float(pit_pct)), max(0.0, float(military_pct)))
        with self._db_lock, self._connect() as con:
            con.execute(
                "INSERT INTO tax_rate_history(effective_from,pit_pct,military_pct,source,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(effective_from) DO UPDATE SET "
                "pit_pct=excluded.pit_pct,military_pct=excluded.military_pct,source=excluded.source,created_at=excluded.created_at",
                (effective_from, *vals, str(source), datetime.now().isoformat(timespec="seconds")),
            )
            con.commit()

    def retail_tariff_for_date(self, day_iso: str):
        with self._db_lock, self._connect() as con:
            row = con.execute(
                "SELECT effective_from,retail_day_tariff_uah,retail_night_factor,source,created_at "
                "FROM retail_tariff_history WHERE effective_from<=? ORDER BY effective_from DESC LIMIT 1",
                (str(day_iso),),
            ).fetchone()
        if not row:
            return None
        return {
            "effective_from": row[0], "retail_day_tariff_uah": float(row[1]),
            "retail_night_factor": float(row[2]), "source": row[3], "created_at": row[4],
        }

    def tax_rates_for_date(self, day_iso: str):
        with self._db_lock, self._connect() as con:
            row = con.execute(
                "SELECT effective_from,pit_pct,military_pct,source,created_at "
                "FROM tax_rate_history WHERE effective_from<=? ORDER BY effective_from DESC LIMIT 1",
                (str(day_iso),),
            ).fetchone()
        if not row:
            return None
        return {
            "effective_from": row[0], "pit_pct": float(row[1]), "military_pct": float(row[2]),
            "source": row[3], "created_at": row[4],
        }

    def upsert_finance_rates(
        self, effective_from: str, retail_day_tariff_uah: float, retail_night_factor: float,
        pit_pct: float, military_pct: float, source: str = "manual",
    ) -> None:
        """Compatibility helper: update both independent histories at one date."""
        self.upsert_retail_tariff_rates(effective_from, retail_day_tariff_uah, retail_night_factor, source)
        self.upsert_tax_rates(effective_from, pit_pct, military_pct, source)
        with self._db_lock, self._connect() as con:
            con.execute(
                "INSERT INTO finance_rate_history("
                "effective_from,retail_day_tariff_uah,retail_night_factor,pit_pct,military_pct,source,created_at"
                ") VALUES(?,?,?,?,?,?,?) ON CONFLICT(effective_from) DO UPDATE SET "
                "retail_day_tariff_uah=excluded.retail_day_tariff_uah,retail_night_factor=excluded.retail_night_factor,"
                "pit_pct=excluded.pit_pct,military_pct=excluded.military_pct,source=excluded.source,created_at=excluded.created_at",
                (self._validate_effective_date(effective_from), max(0.0,float(retail_day_tariff_uah)),
                 max(0.0,float(retail_night_factor)), max(0.0,float(pit_pct)), max(0.0,float(military_pct)),
                 str(source), datetime.now().isoformat(timespec="seconds")),
            )
            con.commit()

    def finance_rates_for_date(self, day_iso: str):
        retail = self.retail_tariff_for_date(day_iso)
        taxes = self.tax_rates_for_date(day_iso)
        if not retail and not taxes:
            return None
        retail = retail or {
            "effective_from": "—", "retail_day_tariff_uah": float(self.cfg.retail_day_tariff_uah),
            "retail_night_factor": float(self.cfg.retail_night_factor), "source": "config", "created_at": "",
        }
        taxes = taxes or {
            "effective_from": "—", "pit_pct": float(self.cfg.personal_income_tax_pct),
            "military_pct": float(self.cfg.military_tax_pct), "source": "config", "created_at": "",
        }
        return {
            "effective_from": max(str(retail["effective_from"]), str(taxes["effective_from"])),
            "retail_effective_from": retail["effective_from"],
            "tax_effective_from": taxes["effective_from"],
            "retail_day_tariff_uah": retail["retail_day_tariff_uah"],
            "retail_night_factor": retail["retail_night_factor"],
            "pit_pct": taxes["pit_pct"], "military_pct": taxes["military_pct"],
            "source": f"{retail['source']}/{taxes['source']}",
            "created_at": max(str(retail.get("created_at", "")), str(taxes.get("created_at", ""))),
        }

    def meter_month_delta(self, year: int, month: int, now: datetime | None = None):
        """Return actual meter deltas for calendar month, across meter replacements."""
        from calendar import monthrange
        start = datetime(year, month, 1)
        if month == 12:
            next_start = datetime(year + 1, 1, 1)
        else:
            next_start = datetime(year, month + 1, 1)
        now = now or datetime.now()

        from .meter_boundary import boundary_window, choose_boundary
        lower, _ = boundary_window(start)
        _, upper = boundary_window(next_start)
        with self._db_lock, self._connect() as con:
            candidates = con.execute(
                "SELECT id,meter_id,reading_date,import_day,import_night,export_day,export_night "
                "FROM meter_readings WHERE reading_date>=? AND reading_date<? ORDER BY reading_date,id",
                (lower.strftime("%Y-%m-%d %H:%M:%S"), upper.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchall()
            actual_start = choose_boundary(candidates, start, now)
            if actual_start is None:
                return None
            is_current = start <= now < next_start
            if is_current:
                eligible = [datetime.fromisoformat(row[2]) for row in candidates
                            if actual_start < datetime.fromisoformat(row[2]) <= now]
                actual_end = max(eligible) if eligible else None
            else:
                actual_end = choose_boundary(candidates, next_start, now)
            if actual_end is None or actual_end <= actual_start:
                return None
            start_iso = actual_start.strftime("%Y-%m-%d %H:%M:%S")
            end_iso = actual_end.strftime("%Y-%m-%d %H:%M:%S")
            rows = con.execute(
                "SELECT id,meter_id,reading_date,import_day,import_night,export_day,export_night "
                "FROM meter_readings WHERE reading_date>=? AND reading_date<=? "
                "ORDER BY meter_id,reading_date,id",
                (start_iso, end_iso),
            ).fetchall()

        by_meter = {}
        for row in rows:
            by_meter.setdefault(int(row[1]), []).append(row)

        totals = dict(import_day=0.0, import_night=0.0, export_day=0.0, export_night=0.0)
        segments = []
        for meter_id in sorted(by_meter):
            group = by_meter[meter_id]
            if len(group) < 2:
                continue
            first, last = group[0], group[-1]
            vals = {
                "import_day": float(last[3]) - float(first[3]),
                "import_night": float(last[4]) - float(first[4]),
                "export_day": float(last[5]) - float(first[5]),
                "export_night": float(last[6]) - float(first[6]),
            }
            if any(v < -1e-9 for v in vals.values()):
                raise ValueError("Виявлено некоректне зменшення показів лічильника.")
            for k, v in vals.items():
                totals[k] += max(0.0, v)
            segments.append({
                "meter_id": meter_id, "from": first[2], "to": last[2], **vals
            })

        if not segments:
            return None
        chronological = sorted(segments, key=lambda segment: (segment['from'], segment['to']))
        if chronological[0]['from'] != start_iso or chronological[-1]['to'] != end_iso:
            return None
        if any(a['to'] != b['from'] for a, b in zip(chronological, chronological[1:])):
            return None
        return {
            "period_start": start_iso, "period_end": end_iso,
            "complete_month": not is_current,
            "interim": is_current, "boundary_adjusted": actual_start != start or (not is_current and actual_end != next_start),
            "calendar_month": start.strftime("%Y-%m"),
            "segments": segments, **totals,
        }

    def available_finance_months(self, limit: int = 36):
        rows = self.list_meter_readings(limit=5000)
        months_set = {str(r['reading_date'])[:7] for r in rows}
        # Boundary records can be in the preceding month; include that month too.
        for row in rows:
            stamp = datetime.fromisoformat(row['reading_date'])
            prior = stamp.replace(day=1) - timedelta(days=1)
            months_set.add(prior.strftime('%Y-%m'))
        months = sorted(months_set, reverse=True)
        out = []
        for ym in months:
            try:
                y, m = map(int, ym.split("-"))
                result = self.meter_month_delta(y, m)
                if result:
                    out.append((y, m, result))
            except Exception:
                continue
            if len(out) >= limit:
                break
        return out

    def find_daily_logs(self, day_iso: str) -> list[Path]:
        root = Path(self.cfg.root_dir)
        candidates: list[Path] = []

        direct = root / f"{day_iso}.csv"
        if direct.exists():
            candidates.append(direct)

        local = self.paths["inverter_logs"] / f"{day_iso}.csv"
        if local.exists():
            candidates.append(local)

        history = self.paths["history"]
        if history.exists():
            for p in history.rglob(f"{day_iso}.csv"):
                if any(part.lower() == "clean" for part in p.parts):
                    continue
                candidates.append(p)

        seen = set()
        out = []
        for p in candidates:
            rp = str(p.resolve())
            if rp not in seen:
                seen.add(rp)
                out.append(p)
        return out
