from __future__ import annotations
from .clock import today as server_today, now as server_now

import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
from pathlib import Path
from typing import Any

from types import SimpleNamespace as AppConfig
def app_paths(cfg):
    return {"data": Path(cfg.root_dir)}
def safe_json_loads(raw, max_size):
    if len(raw)>max_size: raise ValueError("Weather response is too large")
    return json.loads(raw)


FORECAST_HOST = "api.open-meteo.com"
GEOCODING_HOST = "geocoding-api.open-meteo.com"
PREVIOUS_RUNS_HOST = "previous-runs-api.open-meteo.com"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


WMO_UK = {
    0: "Ясно",
    1: "Переважно ясно",
    2: "Мінлива хмарність",
    3: "Хмарно",
    45: "Туман",
    48: "Паморозь / туман",
    51: "Слабка мряка",
    53: "Мряка",
    55: "Сильна мряка",
    56: "Слабка крижана мряка",
    57: "Крижана мряка",
    61: "Слабкий дощ",
    63: "Дощ",
    65: "Сильний дощ",
    66: "Слабкий крижаний дощ",
    67: "Крижаний дощ",
    71: "Слабкий сніг",
    73: "Сніг",
    75: "Сильний сніг",
    77: "Сніжні зерна",
    80: "Слабкі зливи",
    81: "Зливи",
    82: "Сильні зливи",
    85: "Слабкі снігові заряди",
    86: "Сильні снігові заряди",
    95: "Гроза",
    96: "Гроза з градом",
    99: "Сильна гроза з градом",
}


@dataclass(frozen=True)
class GenerationForecast:
    day: str
    expected_kwh: float
    low_kwh: float
    high_kwh: float
    confidence: str
    sample_count: int
    radiation_mj_m2: float
    model: str
    median_error_pct: float | None = None


class WeatherService:
    """Open-Meteo network layer + local day-ahead PV calibration."""

    def __init__(self, cfg: AppConfig, profile_provider=None):
        self.profile_provider=profile_provider
        self._active_profile=dict(device_id=cfg.history_device_id or cfg.legacy_device_id,installed_kw=cfg.pv_installed_kw,tilt_deg=0,azimuth_deg=180,revision=0)
        self.cfg = cfg
        self.paths = app_paths(cfg)
        import hashlib
        identity = str(cfg.installation_id or cfg.server_url)+'|'+str(cfg.history_device_id or cfg.legacy_device_id)
        self.paths['cache'] = self.paths['data'] / 'ClientWeather' / hashlib.sha256(identity.encode()).hexdigest()[:20]
        self.cache_path = self.paths["cache"] / "weather_forecast.json"
        self.calibration_path = self.paths["cache"] / "pv_forecast_calibration.json"
        self.daily_snapshot_path = self.paths["cache"] / "pv_forecast_daily_snapshots.json"

    def _refresh_profile(self):
        if self.profile_provider:
            value=self.profile_provider()
            if value:
                from .weather_client import validate_profile
                self._active_profile={**value,**validate_profile({k:value[k] for k in ('installed_kw','tilt_deg','azimuth_deg')})}

    def _geometry_key(self):
        return hashlib.sha256(json.dumps(dict(model='gti-v1',**self._active_profile),sort_keys=True).encode()).hexdigest()

    def _geometry_params(self):
        return {'tilt':self._active_profile['tilt_deg'],'azimuth':self._active_profile['azimuth_deg']-180}

    @staticmethod
    def _plane_radiation(obj,field):
        """Hourly backward averages: attribute interval ending midnight to preceding day.
        UTC epoch timestamps remove ambiguity on daylight-saving transitions.
        Incomplete days are excluded, never treated as measured zeros.
        """
        hourly=obj.get('hourly') or {};zone=ZoneInfo(obj.get('timezone') or 'UTC')
        sums=defaultdict(float);counts=defaultdict(int);seen=set()
        for stamp,value in zip(hourly.get('time') or [],hourly.get(field) or []):
            try:
                end=datetime.fromtimestamp(float(stamp),timezone.utc) if isinstance(stamp,(int,float)) else datetime.fromisoformat(stamp).replace(tzinfo=zone).astimezone(timezone.utc)
                if end in seen:continue
                seen.add(end);v=float(value)
                if not math.isfinite(v):continue
                day=(end-timedelta(seconds=1)).astimezone(zone).date()
                sums[day.isoformat()]+=max(0,v)*.0036;counts[day.isoformat()]+=1
            except (ValueError,TypeError):continue
        result={}
        for key,value in sums.items():
            d=date.fromisoformat(key)
            start=datetime.combine(d,datetime.min.time(),zone).astimezone(timezone.utc)
            end=datetime.combine(d+timedelta(days=1),datetime.min.time(),zone).astimezone(timezone.utc)
            if counts[key]==int((end-start).total_seconds()/3600):result[key]=value
        return result

    def _get_json(self, host: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        logs=getattr(self.cfg,'_logs',None)
        started=time.monotonic()
        if logs: logs.event('Weather request started',code='weather.request.started',host=host,path=path)
        result='error'
        try:
            response=self._request_json(host,path,params)
            result='ok'
            return response
        except Exception:
            if logs: logs.exception('Weather request failed',code='weather.request.failed',host=host,path=path)
            raise
        finally:
            if logs: logs.event('Weather request completed',code='weather.request.completed',host=host,path=path,
                result=result,duration_ms=round((time.monotonic()-started)*1000,1))

    def _request_json(self, host: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if host not in {FORECAST_HOST, GEOCODING_HOST, PREVIOUS_RUNS_HOST}:
            raise ValueError("Weather host is not allowlisted")
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"https://{host}{path}?{query}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DuckSolar-Client/a1.6.18"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=float(self.cfg.weather_timeout_s)) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise ValueError("Weather response is too large")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Weather response is too large")
        obj = safe_json_loads(raw, max_size=MAX_RESPONSE_BYTES)
        if not isinstance(obj, dict):
            raise ValueError("Unexpected weather response")
        if obj.get("error"):
            raise ValueError(str(obj.get("reason") or "Open-Meteo error"))
        return obj

    def resolve_location(self, location_name: str | None = None) -> dict[str, Any]:
        name = (location_name or self.cfg.weather_location_name or "").strip()
        if not name:
            raise ValueError("Спочатку налаштуйте населений пункт або координати")
        if (
            name.casefold() == (self.cfg.weather_location_name or "").strip().casefold()
            and self.cfg.weather_latitude is not None
            and self.cfg.weather_longitude is not None
        ):
            return {
                "name": self.cfg.weather_location_name,
                "latitude": float(self.cfg.weather_latitude),
                "longitude": float(self.cfg.weather_longitude),
                "country": "Ukraine",
            }

        obj = self._get_json(
            GEOCODING_HOST,
            "/v1/search",
            {"name": name, "count": 10, "language": "uk", "format": "json", "countryCode": "UA"},
        )
        results = obj.get("results") or []
        if not results:
            obj = self._get_json(
                GEOCODING_HOST,
                "/v1/search",
                {"name": name, "count": 10, "language": "uk", "format": "json"},
            )
            results = obj.get("results") or []
        if not results:
            raise ValueError(f"Не знайдено населений пункт «{name}»")

        item = results[0]
        return {
            "name": item.get("name") or name,
            "latitude": float(item["latitude"]),
            "longitude": float(item["longitude"]),
            "country": item.get("country") or "",
            "admin1": item.get("admin1") or "",
        }

    @staticmethod
    def _cloud_mean_by_day(hourly: dict[str, Any]) -> dict[str, float]:
        out: dict[str, list[float]] = defaultdict(list)
        times = hourly.get("time") or []
        clouds = hourly.get("cloud_cover") or []
        for ts, value in zip(times, clouds):
            try:
                if value is not None:
                    out[str(ts)[:10]].append(float(value))
            except (TypeError, ValueError):
                continue
        return {day: sum(vals) / len(vals) for day, vals in out.items() if vals}

    def _fetch_forecast(self, latitude: float, longitude: float) -> dict[str, Any]:
        return self._get_json(
            FORECAST_HOST,
            "/v1/forecast",
            {
                "latitude": f"{latitude:.6f}",
                "longitude": f"{longitude:.6f}",
                "timezone": "auto",
                "forecast_days": max(2, min(16, int(self.cfg.weather_days))),
                "daily": ",".join((
                    "weather_code", "temperature_2m_max", "temperature_2m_min",
                    "precipitation_probability_max", "precipitation_sum",
                    "wind_speed_10m_max", "sunrise", "sunset",
                    "sunshine_duration", "shortwave_radiation_sum",
                )),
                "hourly": "cloud_cover,global_tilted_irradiance",
                "timeformat": "unixtime",
                **self._geometry_params(),
            },
        )

    @staticmethod
    def _idx(values, i, default=None):
        try:
            return values[i]
        except (IndexError, TypeError):
            return default

    def _normalise_days(self, obj: dict[str, Any]) -> list[dict[str, Any]]:
        obj=dict(obj);zone=ZoneInfo(obj.get('timezone') or 'UTC')
        radiation=self._plane_radiation(obj,'global_tilted_irradiance')
        def iso(v):
            return datetime.fromtimestamp(v,zone).isoformat() if isinstance(v,(int,float)) else v
        hourly=dict(obj.get('hourly') or {});hourly['time']=[iso(v) for v in hourly.get('time',[])]
        obj['hourly']=hourly
        daily=dict(obj.get('daily') or {})
        daily['time']=[str(iso(v))[:10] for v in daily.get('time',[])]
        for key in ('sunrise','sunset'):daily[key]=[iso(v) for v in daily.get(key,[])]
        clouds = self._cloud_mean_by_day(obj.get("hourly") or {})
        times = daily.get("time") or []
        out = []
        for i, day in enumerate(times):
            code = self._idx(daily.get("weather_code"), i)
            try:
                code_i = int(code)
            except (TypeError, ValueError):
                code_i = -1
            sunshine_s = self._idx(daily.get("sunshine_duration"), i, 0) or 0
            out.append({
                "date": str(day),
                "weather_code": code_i,
                "condition": WMO_UK.get(code_i, f"Код {code_i}" if code_i >= 0 else "—"),
                "temp_max_c": self._idx(daily.get("temperature_2m_max"), i),
                "temp_min_c": self._idx(daily.get("temperature_2m_min"), i),
                "precip_probability_pct": self._idx(daily.get("precipitation_probability_max"), i),
                "precip_mm": self._idx(daily.get("precipitation_sum"), i),
                "wind_max_kmh": self._idx(daily.get("wind_speed_10m_max"), i),
                "sunrise": self._idx(daily.get("sunrise"), i),
                "sunset": self._idx(daily.get("sunset"), i),
                "sunshine_h": float(sunshine_s) / 3600.0,
                "radiation_mj_m2": radiation.get(str(day)),
                "cloud_mean_pct": clouds.get(str(day)),
            })
        return out

    def _read_json_file(self, path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _write_json_file(path: Path, data: dict[str, Any]):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _previous_day_radiation(self, latitude: float, longitude: float, start: date, end: date):
        result={};chunk_start=start
        while chunk_start<=end:
            chunk_end=min(end,chunk_start+timedelta(days=89))
            obj=self._get_json(PREVIOUS_RUNS_HOST,'/v1/forecast',{
                'latitude':f'{latitude:.6f}','longitude':f'{longitude:.6f}','timezone':'auto',
                'start_date':chunk_start.isoformat(),'end_date':(chunk_end+timedelta(days=1)).isoformat(),
                'timeformat':'unixtime','hourly':'global_tilted_irradiance_previous_day1',**self._geometry_params()})
            result.update({k:v for k,v in self._plane_radiation(obj,'global_tilted_irradiance_previous_day1').items()
                if chunk_start.isoformat()<=k<=chunk_end.isoformat()})
            chunk_start=chunk_end+timedelta(days=1)
        return result

    @staticmethod
    def _month_distance(a: int, b: int) -> int:
        d = abs(a - b)
        return min(d, 12 - d)

    @staticmethod
    def _median(values: list[float], default=0.0):
        return statistics.median(values) if values else default

    def calibrate_generation(self, reader, latitude: float, longitude: float) -> dict[str, Any]:
        summaries = reader.generation_summaries()
        dates = sorted(date.fromisoformat(key) for key in summaries if date.fromisoformat(key) < server_today())
        if not dates:
            return self._fallback_calibration("Немає історії генерації")

        max_days = max(30, int(self.cfg.pv_forecast_max_training_days))
        dates = dates[-max_days:]
        last_date = dates[-1].isoformat()
        history_revision = 'solar95.walkforward.v2|'+'|'.join(summaries[d.isoformat()]['revision'] for d in dates)
        cached = self._read_json_file(self.calibration_path)
        if isinstance(cached, dict):
            same = (
                cached.get("history_last") == last_date
                and cached.get('history_revision') == history_revision
                and cached.get('geometry_key') == self._geometry_key()
                and abs(float(cached.get("latitude", 999)) - latitude) < 0.01
                and abs(float(cached.get("longitude", 999)) - longitude) < 0.01
            )
            if same:
                return cached

        try:
            radiation = self._previous_day_radiation(latitude, longitude, dates[0], dates[-1])
        except Exception as exc:
            if isinstance(cached, dict) and str(cached.get('history_revision','')).startswith('solar95.walkforward.v2|') and cached.get("sample_count", 0) and cached.get("geometry_key")==self._geometry_key() and abs(float(cached.get("latitude",999))-latitude)<.01 and abs(float(cached.get("longitude",999))-longitude)<.01:
                cached = dict(cached)
                cached["cache_note"] = f"Архів прогнозів недоступний: {exc}"
                return cached
            return self._fallback_calibration(f"Архів day-ahead недоступний: {exc}")

        samples = []
        for d in dates:
            x = radiation.get(d.isoformat())
            if not x or x <= 0.2:
                continue
            try:
                from types import SimpleNamespace
                summary = SimpleNamespace(**summaries[d.isoformat()]['summary'])
            except Exception:
                continue
            if summary.records < 2 or getattr(summary,'solar_coverage_pct',0) < 95.0:
                continue
            y = max(0.0, float(summary.pv_kwh))
            ratio = y / x
            if .02*self._active_profile["installed_kw"] <= ratio <= self._active_profile["installed_kw"]:
                samples.append({"date": d.isoformat(), "month": d.month, "x": x, "y": y, "ratio": ratio})

        if len(samples) < 6:
            return self._fallback_calibration(f"Недостатньо валідних пар для навчання: {len(samples)}")

        validation_samples = list(samples)
        ratios = [s["ratio"] for s in samples]
        median_ratio = self._median(ratios)
        deviations = [abs(r - median_ratio) for r in ratios]
        mad = self._median(deviations)
        if mad > 0:
            filtered = [s for s in samples if abs(s["ratio"] - median_ratio) <= 3.5 * mad]
            if len(filtered) >= 6:
                samples = filtered

        global_coeff = self._median([s["ratio"] for s in samples])
        month_coeff = {}
        for m in range(1, 13):
            local = [s["ratio"] for s in samples if self._month_distance(s["month"], m) <= 1]
            if len(local) >= 6:
                month_coeff[str(m)] = 0.75 * self._median(local) + 0.25 * global_coeff
            else:
                month_coeff[str(m)] = global_coeff

        # Walk forward: each validation day is predicted using earlier samples only.
        errors=[]
        for i,s in enumerate(validation_samples):
            prior=validation_samples[:i]
            if len(prior)<6:continue
            local=[p['ratio'] for p in prior if self._month_distance(p['month'],s['month'])<=1]
            global_prior=self._median([p['ratio'] for p in prior])
            coefficient=.75*self._median(local)+.25*global_prior if len(local)>=6 else global_prior
            if s['y']>.3:errors.append(abs(s['x']*coefficient-s['y'])/s['y'])
        med_error=self._median(errors) if errors else None
        result = {
            "model": "Open-Meteo: площина панелей + локальна калібровка",
            "sample_count": len(samples),
            "global_coeff": global_coeff,
            "month_coeff": month_coeff,
            "median_error_pct": med_error * 100.0 if med_error is not None else None,
            "validation_count":len(errors),"validation":"walk_forward",
            "eligibility":"solar_coverage>=95%",
            "history_last": last_date,
            "history_revision": history_revision, "geometry_key": self._geometry_key(), "installed_kw": self._active_profile["installed_kw"],
            "latitude": latitude,
            "longitude": longitude,
            "max_observed_kwh": max((s["y"] for s in samples), default=0.0),
            "updated": server_now().isoformat(timespec="seconds"),
        }
        self._write_json_file(self.calibration_path, result)
        return result

    def _fallback_calibration(self, note: str) -> dict[str, Any]:
        coeff = max(0.1, float(self._active_profile["installed_kw"])) * max(0.1, float(self.cfg.pv_forecast_fallback_pr)) / 3.6
        return {
            "model": "базова фізична оцінка (ще без навчання)",
            "sample_count": 0,
            "global_coeff": coeff,
            "month_coeff": {str(i): coeff for i in range(1, 13)},
            "median_error_pct": None,
            "max_observed_kwh": 0.0,
            "note": note,
        }

    def _generation_forecast(self, tomorrow: dict[str, Any], calibration: dict[str, Any]) -> GenerationForecast | None:
        try:
            target = date.fromisoformat(tomorrow["date"])
            radiation = float(tomorrow.get("radiation_mj_m2") or 0.0)
        except Exception:
            return None
        if radiation <= 0:
            return None

        month_coeff = calibration.get("month_coeff") or {}
        coeff = float(month_coeff.get(str(target.month), calibration.get("global_coeff", 0.0)) or 0.0)
        expected = max(0.0, radiation * coeff)

        # Short winter history must not cap a later summer forecast.
        hours=24.0
        try:
            sunrise=datetime.fromisoformat(tomorrow['sunrise']);sunset=datetime.fromisoformat(tomorrow['sunset'])
            hours=max(0,min(24,(sunset-sunrise).total_seconds()/3600))
        except (KeyError,ValueError,TypeError):pass
        expected=min(expected,self._active_profile['installed_kw']*hours)

        n = int(calibration.get("sample_count") or 0)
        med_err = calibration.get("median_error_pct")
        if med_err is None:
            band = 0.35
            confidence = "низька"
        else:
            err = max(0.08, min(0.45, float(med_err) / 100.0))
            band = min(0.45, max(0.15, err * 1.35))
            if n >= 40 and err <= 0.20:
                confidence = "висока"
            elif n >= 15 and err <= 0.32:
                confidence = "середня"
            else:
                confidence = "низька"

        return GenerationForecast(
            day=target.isoformat(),
            expected_kwh=expected,
            low_kwh=max(0.0, expected * (1.0 - band)),
            high_kwh=expected * (1.0 + band),
            confidence=confidence,
            sample_count=n,
            radiation_mj_m2=radiation,
            model=str(calibration.get("model") or "—"),
            median_error_pct=(None if med_err is None else float(med_err)),
        )

    def _freeze_today_generation(self, location: dict[str, Any], forecast: dict[str, Any] | None):
        """Keep the first PV forecast stored for the current date until midnight.

        This makes the displayed 'today' forecast an actual forecast snapshot
        instead of a moving estimate that silently changes during the day.
        Historical snapshots are kept as useful future calibration material.
        """
        if not forecast:
            return forecast
        today_iso = server_today().isoformat()
        if str(forecast.get("day")) != today_iso:
            return forecast
        lat = float(location.get("latitude") or 0.0)
        lon = float(location.get("longitude") or 0.0)
        key = f"{today_iso}|{lat:.4f}|{lon:.4f}|{self._geometry_key()}"
        obj = self._read_json_file(self.daily_snapshot_path)
        if not isinstance(obj, dict):
            obj = {"entries": {}}
        entries = obj.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        existing = entries.get(key)
        if isinstance(existing, dict) and isinstance(existing.get("forecast"), dict):
            return dict(existing["forecast"])
        entries[key] = {
            "saved_at": server_now().isoformat(timespec="seconds"),
            "location": {"name": location.get("name"), "latitude": lat, "longitude": lon},
            "forecast": dict(forecast),
        }
        # Bound the cache while retaining several seasons of daily snapshots.
        if len(entries) > 500:
            ordered = sorted(entries.items(), key=lambda kv: str((kv[1] or {}).get("saved_at", "")))
            entries = dict(ordered[-500:])
        obj["entries"] = entries
        self._write_json_file(self.daily_snapshot_path, obj)
        return dict(forecast)

    def _generation_for_days(self, days: list[dict[str, Any]], calibration: dict[str, Any], location: dict[str, Any]):
        forecasts: dict[str, dict[str, Any]] = {}
        today_iso = server_today().isoformat()
        for day in days:
            generation = self._generation_forecast(day, calibration)
            if not generation:
                day["generation_expected_kwh"] = None
                continue
            item = dict(generation.__dict__,issued_at=server_now().isoformat(timespec="seconds"),pv_profile=dict(self._active_profile))
            if item.get("day") == today_iso:
                item = self._freeze_today_generation(location, item) or item
            forecasts[str(day.get("date"))] = item
            day["generation_expected_kwh"] = float(item.get("expected_kwh") or 0.0)
        return forecasts

    def fetch_10_day(self, location_name: str | None = None, reader=None) -> dict[str, Any]:
        self._refresh_profile()
        location = self.resolve_location(location_name)
        forecast_obj = self._fetch_forecast(location["latitude"], location["longitude"])
        days = self._normalise_days(forecast_obj)

        calibration = self.calibrate_generation(reader, location["latitude"], location["longitude"]) if reader else self.saved_calibration(location)
        generation_by_day = self._generation_for_days(days, calibration, location)
        tomorrow_iso = (server_today() + timedelta(days=1)).isoformat()
        generation = generation_by_day.get(tomorrow_iso)
        if generation is None and len(days) > 1:
            generation = generation_by_day.get(str(days[1].get("date")))
        if generation is None and days:
            generation = generation_by_day.get(str(days[0].get("date")))

        result = {
            "location": location,
            "geometry_key": self._geometry_key(),
            "pv_profile": dict(self._active_profile),
            "timezone": forecast_obj.get("timezone") or "",
            "updated": server_now().isoformat(timespec="seconds"),
            "days": days,
            "generation": generation,
            "generation_by_day": generation_by_day,
            "calibration": calibration,
            "from_cache": False,
        }
        from .forecast_views import enrich
        enrich(result,forecast_obj,self._active_profile,self.cache_path.with_name("HourlyForecasts.json"))
        self._write_json_file(self.cache_path, result)
        return result

    def cached_forecast(self):
        self._refresh_profile()
        obj = self._read_json_file(self.cache_path)
        if isinstance(obj, dict) and obj.get("geometry_key")==self._geometry_key():
            obj = dict(obj)
            obj["from_cache"] = True
            return obj
        return None
