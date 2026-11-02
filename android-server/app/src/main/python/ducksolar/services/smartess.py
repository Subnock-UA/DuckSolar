from __future__ import annotations

import base64
import csv
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from ducksolar.config import AppConfig, app_paths

API_BASE = "https://api.dessmonitor.com/public/"
COMPANY_KEY_DEFAULT = "bnrl_frRFjEz8Mkn"
SOURCE = "1"
APP_CLIENT = "web"
APP_ID = "ha-dessmonitor"
APP_VERSION = "2.4.0"
I18N = "en_US"
PAGE_SIZE = 50
REQUEST_TIMEOUT = 90
MAX_RETRIES = 4
RETRY_DELAYS = (2, 5, 12, 25)
PAGE_DELAY = 0.20
DAY_DELAY = 0.30

# Read-only actions only.  This service intentionally has no generic "action" UI.
READ_ACTIONS = {"authSource", "queryCollectorDevices", "queryDeviceDataOneDayPaging"}

CLEAN_COLUMNS = [
    "id", "Timestamp", "Working State",
    "AC Input Voltage", "AC Input Frequency",
    "PV1 Input Voltage", "PV1 Input Power",
    "PV2 input voltage", "PV2 input power", "PV total Power",
    "Battery Voltage", "Battery Capacity",
    "Battery Charging Current", "Battery Discharge Current",
    "Output Voltage", "Output Frequency",
    "Output Apparent Power", "Output Active Power", "AC Output Load",
    "Battery Status", "PV Status", "Mains Status", "Load Status",
    "Record Fault Code", "_realtime",
]


class SmartESSError(RuntimeError):
    pass


class NoRecord(SmartESSError):
    pass


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest().lower()


def _now_ms() -> str:
    return str(int(time.time() * 1000))


def _encoded_action(action: str, params: list[tuple[str, Any]]) -> str:
    if action not in READ_ACTIONS:
        raise SmartESSError(f"SmartESS action blocked by read-only policy: {action}")
    result = f"&action={action}"
    for key, value in params:
        result += f"&{key}={quote_plus(str(value))}"
    return result


def _safe_name(value: Any) -> str:
    text = str(value or "device")
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip() or "device"


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        if current == end:
            break
        current += timedelta(days=1)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob_from_bytes(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buf


def dpapi_encrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise SmartESSError("Захищене збереження SmartESS доступне лише у Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, _buf = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), "Duck Solar SmartESS", None, None, None, 0x1, ctypes.byref(out_blob)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def dpapi_decrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise SmartESSError("Захищене збереження SmartESS доступне лише у Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, _buf = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class CredentialStore:
    def __init__(self, cfg: AppConfig):
        self.path = app_paths(cfg)["history"] / ".smartess_credentials.bin"

    def save(self, creds: dict[str, str]) -> None:
        raw = json.dumps(creds, ensure_ascii=False).encode("utf-8")
        encrypted = dpapi_encrypt(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(base64.b64encode(encrypted))

    def load(self) -> dict[str, str] | None:
        if not self.path.exists():
            return None
        try:
            encrypted = base64.b64decode(self.path.read_bytes())
            raw = dpapi_decrypt(encrypted)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or not data.get("username") or not data.get("password"):
                return None
            return {
                "username": str(data.get("username") or ""),
                "password": str(data.get("password") or ""),
                "company_key": str(data.get("company_key") or COMPANY_KEY_DEFAULT),
                "pn": str(data.get("pn") or ""),
            }
        except Exception:
            return None

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except TypeError:
            if self.path.exists():
                self.path.unlink()


class DessMonitorAPI:
    def __init__(self, username: str, password: str, company_key: str):
        self.username = username
        self.password = password
        self.company_key = company_key
        self.token: str | None = None
        self.secret: str | None = None
        self.expires_at = 0.0

    def _get_json(self, url: str) -> dict[str, Any]:
        req = Request(url, headers={
            "User-Agent": "DuckSolar/0.3.4",
            "Accept": "application/json",
            "Connection": "close",
        })
        try:
            with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise SmartESSError("SmartESS response is unexpectedly large")
        except HTTPError as exc:
            raise SmartESSError(f"HTTP {exc.code}") from None
        except (TimeoutError, socket.timeout):
            raise SmartESSError(f"Таймаут SmartESS ({REQUEST_TIMEOUT} с)") from None
        except URLError as exc:
            raise SmartESSError(f"Мережева помилка SmartESS: {getattr(exc, 'reason', exc)}") from None
        except OSError as exc:
            raise SmartESSError(f"Мережева помилка SmartESS: {exc}") from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise SmartESSError("SmartESS повернув некоректний JSON") from None
        if not isinstance(data, dict):
            raise SmartESSError("Некоректна структура відповіді SmartESS")
        err = data.get("err", 0)
        try:
            err_int = int(err)
        except Exception:
            err_int = -1 if err else 0
        if err_int != 0:
            desc = str(data.get("desc", f"API error {err}"))
            if err_int == 12 or "NO_RECORD" in desc.upper():
                raise NoRecord(desc)
            raise SmartESSError(f"{desc} (err={err})")
        return data

    def authenticate(self) -> None:
        salt = _now_ms()
        params = [
            ("usr", self.username), ("company-key", self.company_key), ("source", SOURCE),
            ("_app_client_", APP_CLIENT), ("_app_id_", APP_ID), ("_app_version_", APP_VERSION),
        ]
        action_string = _encoded_action("authSource", params)
        sign = _sha1(salt + _sha1(self.password) + action_string)
        data = self._get_json(f"{API_BASE}?sign={sign}&salt={salt}{action_string}")
        dat = data.get("dat")
        if not isinstance(dat, dict) or not dat.get("token") or not dat.get("secret"):
            raise SmartESSError("SmartESS authentication response has no token/secret")
        self.token = str(dat["token"])
        self.secret = str(dat["secret"])
        try:
            expire = int(dat.get("expire") or 604800)
        except Exception:
            expire = 604800
        self.expires_at = time.time() + expire

    def request(self, action: str, params: list[tuple[str, Any]] | None = None):
        if action not in READ_ACTIONS:
            raise SmartESSError(f"SmartESS action blocked: {action}")
        if not self.token or not self.secret or time.time() >= self.expires_at - 300:
            self.authenticate()
        params = params or []
        salt = _now_ms()
        action_string = _encoded_action(action, params)
        sign = _sha1(salt + str(self.secret) + str(self.token) + action_string)
        url = f"{API_BASE}?sign={sign}&salt={salt}&token={self.token}{action_string}"
        try:
            return self._get_json(url)
        except SmartESSError as exc:
            msg = str(exc).upper()
            if "AUTH" in msg or "TOKEN" in msg or "LOGIN" in msg:
                self.token = None
                self.secret = None
                self.authenticate()
                salt = _now_ms()
                action_string = _encoded_action(action, params)
                sign = _sha1(salt + str(self.secret) + str(self.token) + action_string)
                return self._get_json(f"{API_BASE}?sign={sign}&salt={salt}&token={self.token}{action_string}")
            raise

    def devices(self, pn: str) -> list[dict[str, Any]]:
        data = self.request("queryCollectorDevices", [("pn", pn)])
        dat = data.get("dat", {})
        devices = dat.get("dev", []) if isinstance(dat, dict) else []
        return devices if isinstance(devices, list) else []

    def day_page(self, pn: str, devcode: int, devaddr: int, sn: str, day: str, page: int):
        return self.request("queryDeviceDataOneDayPaging", [
            ("i18n", I18N), ("pn", pn), ("devcode", devcode), ("devaddr", devaddr),
            ("sn", sn), ("date", day), ("page", page), ("pagesize", PAGE_SIZE),
            ("source", SOURCE), ("_app_client_", APP_CLIENT), ("_app_id_", APP_ID),
            ("_app_version_", APP_VERSION),
        ])


def _title_names(title_obj: Any) -> tuple[list[str], list[str]]:
    names, units = [], []
    if not isinstance(title_obj, list):
        return names, units
    seen: dict[str, int] = {}
    for i, item in enumerate(title_obj):
        if isinstance(item, dict):
            name = str(item.get("title") or item.get("name") or item.get("par") or f"field_{i}")
            unit = str(item.get("unit") or "")
        else:
            name, unit = str(item), ""
        base = name.strip() or f"field_{i}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count:
            base = f"{base}_{count + 1}"
        names.append(base)
        units.append(unit)
    return names, units


def _row_values(row: Any) -> list[Any]:
    if isinstance(row, dict):
        for key in ("filed", "field", "values"):
            values = row.get(key)
            if isinstance(values, list):
                return values
    return row if isinstance(row, list) else []


def valid_csv(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        if path.stat().st_size < 20:
            return False
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as f:
            reader = csv.reader(f)
            return bool(next(reader, None)) and bool(next(reader, None))
    except Exception:
        return False


def _make_clean_csv(raw_path: Path, clean_path: Path) -> None:
    try:
        with raw_path.open("r", encoding="utf-8-sig", newline="", errors="replace") as src:
            reader = csv.DictReader(src)
            selected = [c for c in CLEAN_COLUMNS if reader.fieldnames and c in reader.fieldnames]
            if not selected:
                return
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = clean_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8-sig", newline="") as dst:
                writer = csv.DictWriter(dst, fieldnames=selected, extrasaction="ignore")
                writer.writeheader()
                for row in reader:
                    writer.writerow(row)
            tmp.replace(clean_path)
    except Exception:
        return


@dataclass
class ArchiveStatus:
    running: bool = False
    done: int = 0
    total: int = 0
    downloaded_days: int = 0
    skipped_days: int = 0
    no_data_days: int = 0
    failed_days: int = 0
    message: str = "Готово"


class SmartESSArchiveService:
    def __init__(self, cfg: AppConfig, log_service=None):
        self.cfg = cfg
        self.paths = app_paths(cfg)
        self.history = self.paths["history"]
        self.history.mkdir(parents=True, exist_ok=True)
        self.credentials = CredentialStore(cfg)
        self.log_service = log_service
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._status = ArchiveStatus()
        self._listeners: list[Callable[[ArchiveStatus], None]] = []

    def _log(self, message: str):
        if self.log_service:
            try:
                self.log_service.event(f"SmartESS archive: {message}")
            except Exception:
                pass

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _set_status(self, **changes):
        with self._lock:
            for k, v in changes.items():
                if hasattr(self._status, k):
                    setattr(self._status, k, v)
            snapshot = ArchiveStatus(**self._status.__dict__)
        for cb in list(self._listeners):
            try:
                cb(snapshot)
            except Exception:
                pass

    def status(self) -> ArchiveStatus:
        with self._lock:
            return ArchiveStatus(**self._status.__dict__)

    def save_credentials(self, username: str, password: str, company_key: str, pn: str):
        if not username.strip() or not password or not pn.strip():
            raise SmartESSError("Вкажіть логін, пароль і PN логера.")
        self.credentials.save({
            "username": username.strip(), "password": password,
            "company_key": company_key.strip() or COMPANY_KEY_DEFAULT, "pn": pn.strip(),
        })

    def test_credentials(self, creds: dict[str, str]) -> list[dict[str, Any]]:
        api = DessMonitorAPI(creds["username"], creds["password"], creds.get("company_key") or COMPANY_KEY_DEFAULT)
        devices = api.devices(creds["pn"])
        if not devices:
            raise SmartESSError("SmartESS не повернув пристроїв для цього PN.")
        return devices

    def stop(self):
        self._stop.set()
        self._set_status(message="Зупинка після поточного запиту…")

    def start_download(self, creds: dict[str, str], start: date, end: date):
        if start > end:
            raise SmartESSError("Початкова дата більша за кінцеву.")
        if self.status().running:
            raise SmartESSError("Завантаження SmartESS уже виконується.")
        self._stop.clear()
        days = (end - start).days + 1
        self._set_status(running=True, done=0, total=days, downloaded_days=0, skipped_days=0,
                         no_data_days=0, failed_days=0, message="Підключення до SmartESS…")
        threading.Thread(target=self._download_worker, args=(dict(creds), start, end), daemon=True,
                         name="SmartESSArchive").start()

    def _retry_page(self, api, pn, devcode, devaddr, sn, day_s, page):
        last = None
        for attempt in range(MAX_RETRIES):
            if self._stop.is_set():
                raise InterruptedError
            try:
                return api.day_page(pn, devcode, devaddr, sn, day_s, page)
            except NoRecord:
                raise
            except SmartESSError as exc:
                last = exc
                if attempt + 1 >= MAX_RETRIES:
                    break
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)-1)]
                self._set_status(message=f"{day_s}: повтор {attempt+2}/{MAX_RETRIES} через {delay} с")
                if self._stop.wait(delay):
                    raise InterruptedError
        raise SmartESSError(str(last or "SmartESS request failed"))

    def _download_device_day(self, api, pn: str, dev: dict[str, Any], day: date):
        devcode = int(dev.get("devcode"))
        devaddr = int(dev.get("devaddr"))
        sn = str(dev.get("sn") or "device")
        day_s = day.isoformat()
        device_dir = self.history / _safe_name(sn)
        raw_path = device_dir / f"{day_s}.csv"
        meta_path = device_dir / f"{day_s}.meta.json"
        clean_path = device_dir / "Clean" / f"{day_s}.csv"
        nodata_path = device_dir / f"{day_s}.nodata"

        if valid_csv(raw_path):
            if not valid_csv(clean_path):
                _make_clean_csv(raw_path, clean_path)
            try: nodata_path.unlink(missing_ok=True)
            except Exception: pass
            return "skipped", 0
        if nodata_path.exists() and time.time()-nodata_path.stat().st_mtime<86400:
            return "no_data", 0

        names: list[str] = []
        units: list[str] = []
        rows_out: list[dict[str, Any]] = []
        row_bytes=0
        total = None
        page = 0
        while True:
            try:
                payload = self._retry_page(api, pn, devcode, devaddr, sn, day_s, page)
            except NoRecord:
                device_dir.mkdir(parents=True, exist_ok=True)
                nodata_path.write_text("ERR_NO_RECORD\n", encoding="ascii")
                return "no_data", 0
            dat = payload.get("dat", {})
            if not isinstance(dat, dict):
                raise SmartESSError(f"{day_s}: invalid SmartESS data object")
            if not names:
                names, units = _title_names(dat.get("title", []))
            rows = dat.get("row", [])
            if not isinstance(rows, list):
                rows = []
            if total is None:
                try: total = int(dat.get("total", len(rows)))
                except Exception: total = len(rows)
            for row in rows:
                values = _row_values(row)
                rec: dict[str, Any] = {}
                for i, value in enumerate(values):
                    rec[names[i] if i < len(names) else f"field_{i}"] = value
                if isinstance(row, dict):
                    if "id" in row and "id" not in rec: rec["id"] = row.get("id")
                    if "realtime" in row: rec["_realtime"] = row.get("realtime")
                row_bytes+=len(json.dumps(rec,ensure_ascii=False).encode('utf-8'))
                from ..resource_manager import budget
                if row_bytes*4>budget():raise SmartESSError('Недостатньо вільної ОЗП для цього дня ESS; повторіть після вивільнення пам’яті')
                rows_out.append(rec)
            if not rows or (total is not None and len(rows_out) >= total) or len(rows) < PAGE_SIZE:
                break
            page += 1
            if self._stop.wait(PAGE_DELAY):
                raise InterruptedError

        if not rows_out:
            device_dir.mkdir(parents=True, exist_ok=True)
            nodata_path.write_text("EMPTY_RESULT\n", encoding="ascii")
            return "no_data", 0

        device_dir.mkdir(parents=True, exist_ok=True)
        fields = list(names)
        extras: list[str] = []
        for rec in rows_out:
            for key in rec:
                if key not in fields and key not in extras:
                    extras.append(key)
        if "id" in extras:
            extras.remove("id"); fields.insert(0, "id")
        fields.extend([x for x in extras if x != "_realtime"])
        if "_realtime" in extras:
            fields.append("_realtime")
        tmp = raw_path.with_suffix(".csv.part")
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows_out)
        if raw_path.exists():
            # Retain a malformed original before an explicit re-download publishes a replacement.
            revision=raw_path.with_name(raw_path.stem+'.invalid-'+str(time.time_ns())+'.csv')
            raw_path.replace(revision)
        tmp.replace(raw_path)
        meta_path.write_text(json.dumps({
            "date": day_s, "pn": pn, "sn": sn, "devcode": devcode, "devaddr": devaddr,
            "rows": len(rows_out), "downloaded_at": datetime.now().isoformat(timespec="seconds"),
            "columns": [{"name": names[i], "unit": units[i] if i < len(units) else ""} for i in range(len(names))],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _make_clean_csv(raw_path, clean_path)
        try: nodata_path.unlink(missing_ok=True)
        except Exception: pass
        return "downloaded", len(rows_out)

    def _download_worker(self, creds, start, end):
        try:
            api = DessMonitorAPI(creds["username"], creds["password"], creds.get("company_key") or COMPANY_KEY_DEFAULT)
            devices = api.devices(creds["pn"])
            if not devices:
                raise SmartESSError("SmartESS не повернув пристроїв для цього PN.")
            dev_summary = ", ".join(str(d.get("sn") or "?") for d in devices)
            self._log(f"devices: {dev_summary}")
            total_days = (end - start).days + 1
            downloaded = skipped = no_data = failed = 0
            for idx, day in enumerate(_daterange(start, end), start=1):
                if self._stop.is_set():
                    break
                self._set_status(done=idx-1, total=total_days, downloaded_days=downloaded,
                                 skipped_days=skipped, no_data_days=no_data, failed_days=failed,
                                 message=f"{day.isoformat()}…")
                # One logical day counts once in the UI, even if the collector exposes >1 devices.
                day_results = []
                for dev in devices:
                    try:
                        state, rows = self._download_device_day(api, creds["pn"], dev, day)
                        day_results.append(state)
                        if state == "downloaded":
                            self._log(f"{day.isoformat()} {dev.get('sn')}: downloaded {rows} rows")
                    except InterruptedError:
                        raise
                    except Exception as exc:
                        day_results.append("failed")
                        self._log(f"{day.isoformat()} {dev.get('sn')}: ERROR {exc}")
                if "downloaded" in day_results: downloaded += 1
                elif day_results and all(x == "no_data" for x in day_results): no_data += 1
                elif "failed" in day_results: failed += 1
                else: skipped += 1
                self._set_status(done=idx, downloaded_days=downloaded, skipped_days=skipped,
                                 no_data_days=no_data, failed_days=failed,
                                 message=f"Готово {idx}/{total_days}: {day.isoformat()}")
                if self._stop.wait(DAY_DELAY):
                    break
            stopped = self._stop.is_set()
            self._set_status(running=False, message=("Зупинено користувачем" if stopped else
                f"Завершено: завантажено {downloaded}, пропущено {skipped}, без даних {no_data}, помилок {failed}"))
        except InterruptedError:
            self._set_status(running=False, message="Зупинено користувачем")
        except Exception as exc:
            self._log(f"ERROR {exc}")
            self._set_status(running=False, failed_days=self.status().failed_days + 1, message=f"Помилка: {exc}")
        finally:
            creds.clear()
            api=None;devices=None
            from ..resource_manager import release
            release()

    def inventory(self):
        """Return daily raw archive entries. Clean copies are deliberately excluded."""
        rows = []
        if not self.history.exists():
            return rows
        for p in self.history.rglob("*.csv"):
            if any(part.lower() == "clean" for part in p.parts):
                continue
            if p.name.lower().endswith("merged.csv") or "merged" in p.name.lower():
                continue
            stem = p.stem
            try:
                d = date.fromisoformat(stem)
            except ValueError:
                continue
            device = p.parent.name
            count = None
            meta = p.with_suffix(".meta.json")
            if meta.exists():
                try:
                    count = int(json.loads(meta.read_text(encoding="utf-8")).get("rows"))
                except Exception:
                    count = None
            if count is None:
                try:
                    with p.open("r", encoding="utf-8-sig", newline="", errors="replace") as f:
                        count = max(0, sum(1 for _ in f) - 1)
                except Exception:
                    count = 0
            rows.append({"date": d.isoformat(), "device": device, "status": "CSV", "rows": count, "path": str(p)})
        for p in self.history.rglob("*.nodata"):
            if any(part.lower() == "clean" for part in p.parts):
                continue
            try:
                d = date.fromisoformat(p.stem)
            except ValueError:
                continue
            rows.append({"date": d.isoformat(), "device": p.parent.name, "status": "Немає даних", "rows": 0, "path": str(p)})
        rows.sort(key=lambda r: (r["date"], r["device"]), reverse=True)
        return rows
