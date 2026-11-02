from __future__ import annotations

import bisect
import io
from collections import OrderedDict
import csv
import json
import math
import re
import time
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import AppConfig, app_paths
from .energy_model import FlowInput, calculate_flows
from .grid_flow import select_grid_flows, flat_grid_fields

FIELD_META = {
    'output_pf': ('Коефіцієнт потужності PF', ''),
    'grid_import_w': ('Імпорт', 'W'),
    'measured_grid_import_w': ('Імпорт', 'W'),
    'grid_import_energy_total_kwh': ('Імпорт', 'kWh'),
    'measured_grid_import_valid': ('Імпорт', 'bool'),
    'grid_import_source': ('Джерело Імпорт', ""),
    'grid_import_origin': ('Джерело Імпорт', ""),
    'grid_import_counter_id': ('Джерело Імпорт', ""),
    'grid_export_w': ('Віддача', 'W'),
    'measured_grid_export_w': ('Віддача', 'W'),
    'grid_export_energy_total_kwh': ('Віддача', 'kWh'),
    'measured_grid_export_valid': ('Віддача', 'bool'),
    'grid_export_source': ('Джерело Віддача', ""),
    'grid_export_origin': ('Джерело Віддача', ""),
    'grid_export_counter_id': ('Джерело Віддача', ""),
    "grid_import_reason": ("Причина джерела імпорту", ""),
    "grid_export_reason": ("Причина джерела експорту", ""),
    "timestamp": ("Час", ""), "source": ("Джерело", ""),
    "pv_w": ("PV потужність", "W"), "pv_corrected_w": ("PV скоригована", "W"),
    "pv_v": ("PV напруга", "V"), "pv_a": ("PV струм", "A"),
    "output_w": ("Споживання будинку", "W"), "output_va": ("Вихідна повна потужність", "VA"),
    "output_v": ("Вихідна напруга", "V"), "output_hz": ("Вихідна частота", "Hz"),
    "load_pct": ("Навантаження", "%"), "grid_v": ("Напруга мережі", "V"),
    "grid_hz": ("Частота мережі", "Hz"), "grid_available": ("Мережа присутня", "bool"),
    "estimated_grid_import_w": ("Орієнтовний імпорт", "W"),
    "estimated_export_w": ("Орієнтовна віддача", "W"),
    "battery_v": ("Напруга АКБ", "V"), "battery_pct": ("SOC, переданий інвертором", "%"),
    "battery_estimated_pct": ("Заряд АКБ (джерело у записі)", "%"),
    "battery_remaining_kwh": ("Розрахунковий залишок енергії АКБ", "кВт·год"),
    "battery_inverter_pct": ("SOC, переданий інвертором", "%"),
    "charge_a": ("Струм заряду АКБ", "A"), "discharge_a": ("Струм розряду АКБ", "A"),
    "battery_charge_w": ("Потужність заряду АКБ", "W"),
    "temperature_c": ("Температура", "°C"), "bus_v": ("DC Bus", "V"),
    "scc_battery_v": ("SCC Battery Voltage", "V"), "mode": ("Режим", ""),
    "warnings": ("Попередження", ""), "device_status": ("Device Status", ""),
    "service_field": ("Service Field", ""), "eeprom_version": ("EEPROM Version", ""),
    "extra_status": ("Extra Status", ""),
}

SMARTESS_MAP = {
    "PV total Power": "pv_w", "PV1 Input Voltage": "pv_v", "PV1 Input Power": "pv1_w",
    "PV2 input voltage": "pv2_v", "PV2 input power": "pv2_w",
    "Output Active Power": "output_w", "Output Apparent Power": "output_va",
    "Output Voltage": "output_v", "AC Output Load": "load_pct",
    "AC Input Voltage": "grid_v", "AC Input Frequency": "grid_hz",
    "Battery Voltage": "battery_v", "Battery Capacity": "battery_pct",
    "Battery Charging Current": "charge_a", "Battery Discharge Current": "discharge_a",
    "Working State": "mode", "Fault Code": "warnings",
}

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$", re.I)
COMPACT_GRID_FIELDS = frozenset(('grid_import_w','grid_export_w','grid_import_source','grid_export_source',
    'grid_import_origin','grid_export_origin','grid_import_reason','grid_export_reason',
    'grid_import_energy_total_kwh','grid_export_energy_total_kwh','grid_import_counter_id','grid_export_counter_id',
    'measured_grid_import_w','measured_grid_export_w','measured_grid_import_valid','measured_grid_export_valid'))
ACCOUNTING_FIELDS = frozenset(('pv_w','output_w','battery_v','charge_a','grid_v','grid_hz','grid_available',
    'pv_corrected_w','battery_charge_w','estimated_grid_import_w','estimated_export_w'))


def field_label(key: str) -> str:
    return FIELD_META.get(key, (key, ""))[0]


def field_unit(key: str) -> str:
    return FIELD_META.get(key, (key, ""))[1]


class HistoryReader:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.paths = app_paths(cfg)
        if cfg.history_device_id and cfg.history_device_id!=cfg.legacy_device_id:
            from .core.models import checked_id
            device_id=checked_id(cfg.history_device_id)
            self.paths['inverter_logs']=self.paths['inverter_logs']/'Devices'/device_id
            self.paths['history']=self.paths['history']/'Devices'/device_id
        self._cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._cache_signatures: dict[tuple[str, str], tuple] = {}
        self._cache_order = deque(maxlen=2)
        self._dates_cache: list[date] | None = None
        self._dates_cache_at: float = 0.0
        self._file_index = None
        self._append_cache=OrderedDict()

    @staticmethod
    def _float(value):
        if value is None: return None
        if isinstance(value, (int,float)) and not isinstance(value,bool):
            try:return float(value) if math.isfinite(value) else None
            except OverflowError:return None
        s = str(value).strip().replace(",", ".")
        if not s: return None
        try:
            number = float(s)
            return number if math.isfinite(number) else None
        except ValueError: return None

    @staticmethod
    def _parse_dt(value: str, fallback_day: date | None = None):
        s = (value or "").strip()
        try:
            return datetime.fromisoformat(s)
        except ValueError: pass
        formats = (
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
            "%d.%m.%Y %H:%M:%S", "%H:%M:%S", "%H:%M:%S.%f",
        )
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                if fmt.startswith("%H") and fallback_day:
                    dt = datetime.combine(fallback_day, dt.time())
                return dt
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    def _classify(self, path: Path):
        try:
            rel = path.resolve().relative_to(Path(self.cfg.root_dir).resolve())
            parts = [x.lower() for x in rel.parts]
        except Exception:
            parts = [x.lower() for x in path.parts]
        if "historysync" in parts and "local" in parts:return "Local"
        if "historysync" in parts and "smartess" in parts:return "SmartESS"
        if "history" in parts:
            return "SmartESS"
        return "Local"

    def find_day_files(self, day: date):
        self.available_dates()
        local, smart = self._file_index.get(day, ([], []))
        local = list(local)
        # A live writer may create today's file after the last index refresh.
        direct = self.paths['inverter_logs'] / (day.isoformat()+'.csv')
        if direct.is_file() and direct not in local: local.insert(0, direct)
        return local, list(smart)

    def _compact_normalized(self,row,ts):
        # Modern writer rows already contain authoritative grid metrics. Avoid
        # reconstructing unrelated battery/output/voltage fields for accounting.
        # Legacy or incomplete records still take the original canonical path.
        from .csv_codec import unpack
        try:normalized=unpack(row.get('normalized_json'))
        except (ValueError,TypeError):return None
        if not isinstance(normalized,dict) or not isinstance(normalized.get('metrics'),dict):return None
        metrics=normalized['metrics']
        for direction in ('import','export'):
            estimate=metrics.get('grid.estimated_'+direction+'_power')
            if not isinstance(estimate,dict) or 'quality' not in estimate:return None
            if self._float(row.get('estimated_grid_'+direction+'_w')) is not None:
                estimate.setdefault('quality','good')
            if 'grid.measured_'+direction+'_power' not in metrics and self._float(row.get('measured_grid_'+direction+'_w')) is not None:return None
            if 'grid.'+direction+'_energy_total' not in metrics and self._float(row.get('grid_'+direction+'_energy_total_kwh')) is not None:return None
        normalized={'metrics':{k:v for k,v in metrics.items() if k.startswith('grid.')},'grid':normalized.get('grid',{})}
        normalized=select_grid_flows(normalized,ts,owned=True)
        out={'timestamp':ts,'source':'Local','normalized':normalized}
        for key in ('pv_w','output_w','battery_v','charge_a','grid_available'):
            if key in row:
                value=self._float(row[key]);out[key]=value if value is not None else row[key]
        out.update(flat_grid_fields(normalized,ts))
        stats=getattr(self,'_balance_stats',None)
        if stats is not None:stats['compact_fast_records']=stats.get('compact_fast_records',0)+1
        from .pv_accounting import project
        return project(out,self.cfg)

    def decode_compact(self,path,row,compact=False):
        from .compact_history import MARKER,Codec,schema_path
        if MARKER not in row:return row
        if not hasattr(self,'_compact_codecs'):self._compact_codecs={}
        meta=schema_path(path);stat=meta.stat();key=(str(meta),stat.st_size,stat.st_mtime_ns)
        codec=self._compact_codecs.get(key)
        if codec is None:
            codec=Codec(path);self._compact_codecs[key]=codec
            while len(self._compact_codecs)>64:self._compact_codecs.pop(next(iter(self._compact_codecs)))
        return codec.decode(row,grid_only=bool(compact))

    def compact_decoder(self,path,compact=False):
        """Capture immutable metadata once per file snapshot, not per CSV row."""
        from .compact_history import Codec,schema_path
        codec=Codec(path) if schema_path(path).exists() else None
        expected=getattr(self,'_balance_schemas',{}).get(str(path))
        if codec and expected and codec.schema_sha256!=expected:raise ValueError('Compact schema changed; repeat the query')
        decoder=(lambda row:codec.decode(row,grid_only=bool(compact))) if codec else (lambda row:row)
        decoder.schema_sha256=codec.schema_sha256 if codec else None
        return decoder

    def timestamp_decoder(self,path):
        """Resolve only scalar time defaults; no grid template reconstruction."""
        from .compact_history import Codec,schema_path,MARKER
        codec=Codec(path) if schema_path(path).exists() else None
        def decode(raw):
            if codec is None:return raw.get('time') or raw.get('Timestamp') or raw.get('timestamp') or ''
            if raw.get(MARKER) not in codec.schema['templates']:raise ValueError('Unknown compact template')
            for key in ('time','Timestamp','timestamp'):
                if key not in codec.schema['fields']:continue
                value=raw.get(key,'')
                value=codec.schema['defaults'].get(key,'') if value=='' else value[1:] if value.startswith('~') else value
                if value:return value
            return ''
        return decode

    def _canonical(self, row: dict[str, str], source: str, fallback_day: date, compact=False, parsed_time=None):
        ts = parsed_time if parsed_time is not None else self._parse_dt(row.get("time") or row.get("Timestamp") or row.get("timestamp") or "", fallback_day)
        if not ts: return None
        if compact and source=='Local':
            fast=self._compact_normalized(row,ts)
            if fast is not None:
                if compact=='graph':
                    for k in FIELD_META:
                        if k in row and k not in fast:
                            v=self._float(row[k]);fast[k]=v if v is not None else row[k]
                return fast
        out: dict[str, Any] = {"timestamp": ts, "source": source}
        if not compact:out['_raw']=dict(row)
        if source == "Local":
            entries=((k,row[k]) for k in ACCOUNTING_FIELDS|COMPACT_GRID_FIELDS if k in row) if compact is True else row.items()
            for k, v in entries:
                if k in ("time", "timestamp", "Timestamp", "source"): continue
                if compact is True and k not in ACCOUNTING_FIELDS and not k.startswith(('grid_','measured_grid_')):continue
                if k in FIELD_META or k in ("pv_corrected_w", "estimated_grid_import_w", "estimated_export_w", "battery_charge_w"):
                    fv = self._float(v)
                    out[k] = fv if fv is not None else v
        else:
            for src_key, dest in SMARTESS_MAP.items():
                if src_key in row:
                    fv = self._float(row.get(src_key))
                    out[dest] = fv if fv is not None else row.get(src_key, "")
            # Fall back to second PV tracker if first voltage is absent.
            if self._float(out.get("pv_v")) is None:
                out["pv_v"] = self._float(row.get("PV2 input voltage"))
            if self._float(out.get("pv_w")) is None:
                first,second=self._float(row.get("PV1 Input Power")),self._float(row.get("PV2 input power"))
                # Only derive a sum when both tracker columns are present and valid.
                # Missing ESS samples are unavailable, never fabricated zero power.
                out["pv_w"] = first+second if first is not None and second is not None else None
            # Some SmartESS exports have output frequency under varying names.
            for candidate in ("Output Frequency", "AC Output Frequency"):
                if candidate in row:
                    out["output_hz"] = self._float(row.get(candidate))
                    break
            for candidate in ("Temperature", "Inverter Temperature", "Machine Temperature"):
                if candidate in row:
                    out["temperature_c"] = self._float(row.get(candidate))
                    break

        gv = self._float(out.get("grid_v")) or 0.0
        gh = self._float(out.get("grid_hz")) or 0.0
        from .grid_input import classify
        grid_ok=classify(out,self.cfg,allow_low=True)['available']
        if self._float(out.get("grid_available")) in (0, 1):
            grid_ok = bool(out["grid_available"])
        out["grid_available"] = 1 if grid_ok else 0

        pv = self._float(out.get("pv_w")) or 0.0
        load = self._float(out.get("output_w")) or 0.0
        bv = self._float(out.get("battery_v")) or 0.0
        ca = self._float(out.get("charge_a")) or 0.0
        derived_names=('pv_corrected_w','battery_charge_w','estimated_grid_import_w','estimated_export_w')
        need_flow=any(self._float(out.get(key)) is None for key in derived_names)
        flow = calculate_flows(
            FlowInput(pv_w=pv, load_w=load, battery_v=bv, battery_charge_a=ca, grid_available=grid_ok),
            pv_factor=self.cfg.pv_correction_factor,
            inverter_self_w=self.cfg.inverter_self_consumption_w,
        ) if need_flow else None
        # Older CSV rows can already contain the new columns but with empty
        # values after a schema upgrade.  setdefault() is not enough in that
        # case, so backfill every missing/non-numeric derived value.
        derived = {
            "pv_corrected_w": flow.pv_corrected_w,
            "battery_charge_w": flow.battery_charge_w,
            "estimated_grid_import_w": flow.grid_import_w,
            "estimated_export_w": flow.export_w,
        } if flow is not None else {}
        legacy_complete = all(self._float(out.get(k)) is not None for k in ("pv_w", "output_w", "battery_v", "charge_a", "grid_v", "grid_hz"))
        for key, value in derived.items():
            if self._float(out.get(key)) is None and legacy_complete:
                out[key] = value
        try:
            from .csv_codec import unpack
            normalized = unpack(row.get('normalized_json'))
            if not isinstance(normalized, dict) or not isinstance(normalized.get('metrics', {}), dict):
                normalized = {}
        except (ValueError, TypeError):
            normalized = {}
        if compact:
            # Accounting only consumes grid flows; copying the entire device
            # descriptor and all live metrics for every row dominated CPU time.
            normalized={'metrics':{k:v for k,v in normalized.get('metrics',{}).items() if k.startswith('grid.')},
                        'grid':normalized.get('grid',{})}
        metrics = normalized.setdefault('metrics', {})
        if not compact:
            for column,key in [('battery_estimated_pct','battery.channels.main.soc'),('battery_remaining_kwh','battery.channels.main.remaining_energy'),('battery_inverter_pct','battery.channels.main.inverter_soc')]:
                if key in normalized['metrics']:out[column]=self._float(normalized['metrics'][key].get('value'))
        for direction, old in (('import', 'estimated_grid_import_w'), ('export', 'estimated_export_w')):
            estimate = self._float(out.get(old))
            if 'grid.estimated_'+direction+'_power' not in metrics and estimate is not None:
                metrics['grid.estimated_'+direction+'_power'] = dict(value=estimate,unit='W',source='energy_model',quality='good')
            if estimate is not None:
                metrics['grid.estimated_'+direction+'_power'].setdefault('quality','good')
            # Flattened CSV supports measured records even when JSON was omitted by an exporter.
            measured = self._float(out.get('measured_grid_'+direction+'_w'))
            if 'grid.measured_'+direction+'_power' not in metrics and measured is not None:
                metrics['grid.measured_'+direction+'_power'] = dict(value=measured,unit='W',source=out.get('grid_'+direction+'_origin'),
                    quality='good' if out.get('measured_grid_'+direction+'_valid') == 1 else 'invalid',validation_reason=out.get('grid_'+direction+'_reason') or None)
            energy = self._float(out.get('grid_'+direction+'_energy_total_kwh'))
            if 'grid.'+direction+'_energy_total' not in metrics and energy is not None:
                metrics['grid.'+direction+'_energy_total'] = dict(value=energy,unit='kWh',meter_id=out.get('grid_'+direction+'_counter_id'),quality='good')
        normalized = select_grid_flows(normalized, ts, owned=compact)
        out.update(flat_grid_fields(normalized, ts))
        out['normalized'] = normalized
        from .pv_accounting import project
        return project(out,self.cfg)

    def graph_endpoints(self,day,source='Auto',cancelled=None):
        """Decode only two canonical endpoint rows, preserving file/Auto priority.

        Scan all timestamp cells (including compact defaults), so unsorted files
        and ESS points suppressed by a nearby Local point remain correct.
        """
        from .energy_streaming import _snapshot_lines
        from .energy_accounting import stamp
        from .compact_history import Codec,schema_path,MARKER
        cancelled=cancelled or (lambda:False)
        local,smart=self.find_day_files(day);local_times=[];chosen={}
        gap=max(15.,self.cfg.poll_interval_s*3.)
        for origin,paths in [('Local',local),('SmartESS',smart)]:
            if source not in ('Auto',origin):continue
            seen=set()
            for path in paths:
                codec=Codec(path) if schema_path(path).exists() else None
                for raw in csv.DictReader(_snapshot_lines(path,path.stat().st_size),strict=True):
                    if cancelled():raise ValueError('History query cancelled')
                    if None in raw or any(v is None for v in raw.values()):continue
                    def cell(key):
                        value=raw.get(key,'')
                        if codec is not None:
                            value=codec.schema['defaults'].get(key,'') if value=='' else value[1:] if value.startswith('~') else value
                        return value
                    parsed=self._parse_dt(cell('time') or cell('Timestamp') or cell('timestamp'),day)
                    if parsed is None:continue
                    instant=stamp(parsed).timestamp()
                    if instant in seen:continue
                    seen.add(instant)
                    if origin=='Local':local_times.append(instant)
                    elif source=='Auto':
                        k=bisect.bisect_left(local_times,instant)
                        if any(0<=j<len(local_times) and abs(local_times[j]-instant)<=gap for j in (k-1,k)):continue
                    if codec is not None and raw.get(MARKER) not in codec.schema['templates']:raise ValueError('Unknown compact template')
                    candidate=(instant,raw,codec,origin)
                    for name,compare in [('first',lambda a,b:a<b),('last',lambda a,b:a>b)]:
                        if name not in chosen or compare(instant,chosen[name][0]):chosen[name]=candidate
            if origin=='Local':local_times.sort()
        result={}
        for name in ('first','last'):
            if name not in chosen:result[name]=None;continue
            _,raw,codec,origin=chosen[name]
            row=self._canonical(codec.decode(raw,grid_only=True) if codec else raw,origin,day,compact=True)
            if row:row.pop('_raw',None);row.pop('normalized',None)
            result[name]=row
        return result

    def energy_graph_rows(self, day, source='Auto', cancelled=None, columns=None):
        """Use the checked scalar SQLite projection shared with accounting.

        Private reader stats avoid interfering with a concurrent balance job.
        CSV/prefix/schema validation remains in _projected_file.
        """
        import copy
        from .energy_streaming import _ordered_rows
        from .compact_history import schema_path
        from .prepared_history import digest
        cancelled=cancelled or (lambda:False)
        local,smart=self.find_day_files(day)
        files=[]
        for origin,paths in [('Local',local),('SmartESS',smart)]:
            if source not in ('Auto',origin):continue
            for path in paths:
                stat=path.stat();files.append((path,origin,day,stat.st_size,stat.st_mtime_ns))
        reader=copy.copy(self)
        reader._compact_codecs={}
        if columns is not None:reader._projection_columns=columns
        reader._balance_stats=dict(opened_files=0,read_records=0,used_records=0,files=[],range_start=0.,range_end=7258118400.)
        reader._balance_schemas={str(p):digest(schema_path(p),cancelled) for p,_,_,_,_ in files if schema_path(p).exists()}
        with _ordered_rows(reader,files,source,cancelled) as rows:
            result=list(rows)
        self._last_graph_index_stats={k:v for k,v in reader._balance_stats.items() if k not in ('files',)}
        return result

    def graph_day_rows(self,day,source='Auto',cancelled=None):
        """Full-resolution typed rows shared with the existing hourly cache builder.

        The same field order, source revision, model, prefix/schema validation
        and range identity reuse its SQLite files, including after restart.
        Energy-only projections and their checkpoints remain unchanged.
        """
        from .hourly_projection import columns
        return self.energy_graph_rows(day,source,cancelled,columns=columns())

    def _read_file(self,path,source,day,compact=False,cancelled=None):
        # TelemetryWriter appends complete CSV records. Retain parsed rows and
        # parse only newly appended bytes instead of every previous JSON blob.
        stat=path.stat()
        from .compact_history import schema_path
        meta=schema_path(path);ms=meta.stat() if meta.exists() else None
        key=(str(path),source,self.model_signature(),compact,(ms.st_size,ms.st_mtime_ns) if ms else None)
        cached=self._append_cache.get(key) if source=='Local' else None
        with path.open('rb') as f:
            prefix=f.read(min(512,stat.st_size))
            append=bool(cached and stat.st_size>cached['size'] and cached['prefix']==prefix[:len(cached['prefix'])]
                        and cached['inode']==stat.st_ino and cached['offset']==cached['size'])
            if cached and stat.st_size==cached['size'] and stat.st_mtime_ns==cached['mtime']:
                return cached['rows']
            if append:
                import hashlib
                f.seek(0);remaining=cached['offset'];digest=hashlib.sha256()
                while remaining:
                    if cancelled and cancelled():raise ValueError('History query cancelled')
                    block=f.read(min(1024*1024,remaining))
                    if not block:break
                    digest.update(block);remaining-=len(block)
                append=remaining==0 and digest.hexdigest()==cached.get('digest')
            if append:
                f.seek(cached['offset']);raw=f.read(stat.st_size-cached['offset'])
                # A live writer may be in the middle of its last record.
                if raw and not raw.endswith(b'\n'):raw=raw[:raw.rfind(b'\n')+1]
                reader=csv.DictReader(io.StringIO(raw.decode('utf-8',errors='replace'),newline=''),fieldnames=cached['fields'],strict=True)
                rows=dict(cached['rows']);offset=cached['offset']+len(raw);fields=cached['fields']
            else:
                f.seek(0);raw=f.read(stat.st_size)
                if raw and not raw.endswith(b'\n'):raw=raw[:raw.rfind(b'\n')+1]
                reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig',errors='replace'),newline=''),strict=True)
                rows={};offset=len(raw);fields=reader.fieldnames
            decode=self.compact_decoder(path,compact)
            for row in reader:
                if cancelled and cancelled():raise ValueError('History query cancelled')
                item=self._canonical(decode(row),source,day,compact=compact)
                if item and compact:item.pop('_raw',None);item.pop('normalized',None)
                if item:
                    from .energy_accounting import stamp
                    instant=stamp(item['timestamp']).timestamp()
                    if instant not in rows:rows[instant]=item
        if source=='Local':
            import hashlib
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                remaining=offset
                while remaining:
                    if cancelled and cancelled():raise ValueError('History query cancelled')
                    block=stream.read(min(1024*1024,remaining))
                    if not block:raise ValueError('CSV changed during graph read')
                    digest.update(block);remaining-=len(block)
            after=path.stat()
            if after.st_ino!=stat.st_ino or after.st_size<offset:return rows
            self._append_cache[key]=dict(rows=rows,fields=fields,offset=offset,size=offset,
                                         mtime=stat.st_mtime_ns,prefix=prefix,inode=stat.st_ino,digest=digest.hexdigest())
            self._append_cache.move_to_end(key)
            from .resource_manager import budget
            retained=sum(v['size']*4 for v in self._append_cache.values())
            while self._append_cache and retained>budget():
                _,discarded=self._append_cache.popitem(last=False);retained-=discarded['size']*4
        return rows

    def _load_files(self, paths: list[Path], source: str, day: date):
        by_ts={}
        for path in paths:
            try:
                for stamp,item in self._read_file(path,source,day).items():
                    if stamp not in by_ts:by_ts[stamp]=item
            except (OSError,csv.Error):continue
        return [by_ts[k] for k in sorted(by_ts)]

    @staticmethod
    def _files_signature(paths: list[Path]) -> tuple:
        signature = []
        for path in sorted(paths, key=lambda x: str(x).lower()):
            try:
                st = path.stat()
                signature.append((str(path), int(st.st_size), int(st.st_mtime_ns)))
                sidecar=Path(str(path)+'.schema.json')
                if sidecar.exists():
                    st=sidecar.stat();signature.append((str(sidecar),int(st.st_size),int(st.st_mtime_ns)))
            except OSError:
                signature.append((str(path), -1, -1))
        return tuple(signature)

    def _cache_put(self, key, rows, signature):
        if key in self._cache:
            try: self._cache_order.remove(key)
            except ValueError: pass
        while len(self._cache) >= 2 and self._cache_order:
            old_key = self._cache_order.popleft()
            self._cache.pop(old_key, None)
            self._cache_signatures.pop(old_key, None)
        self._cache[key] = rows
        self._cache_signatures[key] = signature
        self._cache_order.append(key)

    def load_day(self, day: date, source: str = "Auto"):
        key = (day.isoformat(), source)
        local_paths, smart_paths = self.find_day_files(day)
        selected_paths = (
            local_paths if source == "Local" else
            smart_paths if source == "SmartESS" else
            local_paths + smart_paths
        )
        signature = (self._files_signature(selected_paths), self.model_signature())
        if key in self._cache and self._cache_signatures.get(key) == signature:
            return self._cache[key]
        local = self._load_files(local_paths, "Local", day) if source in ("Auto", "Local") else []
        smart = self._load_files(smart_paths, "SmartESS", day) if source in ("Auto", "SmartESS") else []
        if source == "Local": rows = local
        elif source == "SmartESS": rows = smart
        else:
            if not local: rows = smart
            elif not smart: rows = local
            else:
                from .energy_accounting import stamp
                local_ts = [stamp(r["timestamp"]).timestamp() for r in local]
                merged = list(local)
                # SmartESS only fills periods not covered by nearby local measurements.
                threshold = max(15.0, self.cfg.poll_interval_s * 3.0)
                for r in smart:
                    x = stamp(r["timestamp"]).timestamp()
                    i = bisect.bisect_left(local_ts, x)
                    near = []
                    if i < len(local_ts): near.append(abs(local_ts[i] - x))
                    if i: near.append(abs(local_ts[i-1] - x))
                    if not near or min(near) > threshold:
                        merged.append(r)
                rows = sorted(merged, key=lambda r: stamp(r["timestamp"]).timestamp())
        self._cache_put(key, rows, signature)
        return rows

    def available_dates(self, refresh=False):
        now = time.monotonic()
        if self._dates_cache is not None and not refresh and (now - self._dates_cache_at) < 60.0:
            return list(self._dates_cache)
        root = Path(self.cfg.root_dir)
        index = {}
        compact_root=root/'Data/CompactHistory'/(self.cfg.history_device_id or self.cfg.legacy_device_id)
        folders = [compact_root,self.paths['inverter_logs'], self.paths['history']]
        from .history_migration import active_folder
        activated=active_folder(root,self.cfg.history_device_id or self.cfg.legacy_device_id)
        if activated:folders.insert(1,activated)
        paths = []
        for folder in folders:
            if folder.exists():
                paths.extend(p for p in folder.rglob('*.csv') if 'Devices' not in p.relative_to(folder).parts)
        self._archive_diagnostics={'complete_imports':0,'original_files':0,'invalid_markers':0}
        if not self.cfg.history_device_id or self.cfg.history_device_id == self.cfg.legacy_device_id:
            from .synchronized_history import verified_paths
            synchronized,count=verified_paths(root)
            self._archive_diagnostics['synchronized_files']=count
            paths.extend(synchronized)
            paths.extend(root.glob('*.csv'))
            # One-time imports retain authoritative originals outside the live
            # folders. Read them last, without changing or reimporting phone data.
            for base in sorted((root/'Data'/'ImportedArchive').glob('*')):
                marker=base/'complete.json'
                if not marker.is_file() or base.is_symlink():continue
                try:
                    if json.loads(marker.read_text(encoding='utf-8')).get('status')!='complete':continue
                except (OSError,ValueError,AttributeError):
                    self._archive_diagnostics['invalid_markers']+=1;continue
                self._archive_diagnostics['complete_imports']+=1
                originals=base/'Originals'
                if originals.is_symlink():continue
                for relative in ('Logs/Inverter','History'):
                    folder=originals/relative
                    if not folder.is_dir() or folder.is_symlink():continue
                    for candidate in folder.rglob('*.csv'):
                        if candidate.is_symlink() or 'Devices' in candidate.relative_to(folder).parts:continue
                        try:candidate.resolve().relative_to(originals.resolve())
                        except ValueError:continue
                        self._archive_diagnostics['original_files']+=1
                        # A completed import already merged/copied this exact
                        # destination. Its live phone file remains authoritative.
                        if (root/candidate.relative_to(originals)).is_file():continue
                        paths.append(candidate)
        for p in paths:
            if not p.is_file() or p.is_symlink(): continue
            if any(part.lower() == 'clean' for part in p.parts) or 'merged' in p.name.lower(): continue
            m = DATE_RE.match(p.name)
            if m:
                try: day = date.fromisoformat(m.group(1))
                except ValueError: continue
                pair = index.setdefault(day, ([], []))
                pair[1 if ('SmartESS' in p.parts if 'CompactHistory' in p.parts else self._classify(p)=='SmartESS') else 0].append(p)
        for local, smart in index.values():
            local.sort(key=lambda p: ('CompactHistory' not in p.parts,'SynchronizedArchive' in p.parts,'ImportedArchive' in p.parts,p.parent != self.paths['inverter_logs'], str(p)))
            smart.sort(key=lambda p: ('CompactHistory' not in p.parts,'SynchronizedArchive' in p.parts,'ImportedArchive' in p.parts,str(p)))
        self._file_index = index
        self._dates_cache = sorted(index)
        self._dates_cache_at = now
        return list(self._dates_cache)

    def model_signature(self):
        keys = ('pv_correction_factor', 'inverter_self_consumption_w', 'max_integration_gap_s',
                'poll_interval_s', 'grid_present_min_v', 'grid_present_max_v', 'grid_present_min_hz', 'grid_present_max_hz')
        return tuple((k, getattr(self.cfg, k)) for k in keys)+(('generation_basis','pv.accounted.v2'),('pv_night_noise_w',getattr(self.cfg,'pv_night_noise_w',6.)),('latitude',self.cfg.weather_latitude),('longitude',self.cfg.weather_longitude))

    @staticmethod
    def numeric_fields(rows):
        found = set()
        for row in rows[:5000]:
            for k, v in row.items():
                if k.startswith("_") or k in ("timestamp", "source", "mode", "warnings", "device_status", "service_field", "extra_status"):
                    continue
                if isinstance(v, (int, float)):
                    found.add(k)
        return sorted(found, key=lambda k: field_label(k))

    @staticmethod
    def coverage_percent(rows, max_gap_s=900):
        if len(rows) < 2: return 0.0
        covered = 0.0
        for a, b in zip(rows, rows[1:]):
            from .energy_accounting import stamp
            dt = stamp(b["timestamp"]).timestamp()-stamp(a["timestamp"]).timestamp()
            if 0 < dt <= max_gap_s: covered += dt
        from .energy_accounting import ZONE
        from datetime import datetime, timedelta
        day = stamp(rows[0]['timestamp']).date()
        start = datetime(day.year, day.month, day.day, tzinfo=ZONE)
        duration = (start + timedelta(days=1)).timestamp() - start.timestamp()
        return min(100.0, covered / duration * 100.0)
