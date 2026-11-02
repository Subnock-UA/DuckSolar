from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("DUCK_SOLAR_ROOT", str(Path.home() / ".ducksolar-b2")))
ROLE = os.environ.get("DUCK_SOLAR_ROLE", "Server")
VERSION = "0.3.4"
COMPONENT = f"DS_{ROLE}_Beta_2"
CONFIG_FILE = ROOT / ROLE / COMPONENT / "config.json"
_SAVE_LOCK = threading.RLock()

DEFAULT_GRAPH_COLORS = {
    "pv": "#0072B2",
    "load": "#E69F00",
    "grid_import": "#CC79A7",
    "grid_export": "#009E73",
    "battery": "#56B4E9",
    "soc": "#D55E00",
    "voltage": "#332288",
    "temperature": "#AA4499",
}

@dataclass
class AppConfig:
    installation_id: str = ""
    root_dir: str = str(ROOT)
    # Configuration schemas are platform independent; no language selector yet.
    config_schema: int = 2
    primary_device_id: str = 'inverter-1'
    legacy_device_id: str = 'inverter-1'
    dataloggers: list[dict] | None = None
    devices: list[dict] | None = None
    history_device_id: str = ''
    pv_profiles: dict | None = None

    notifications_enabled: bool = True
    notification_grid: bool = True
    notification_connection: bool = True
    notification_warnings: bool = True
    notification_battery: bool = True
    battery_alert_pct: float = 20.0
    archive_dir: str = ""
    account_username: str = ""
    server_fingerprint: str = ""
    auth_token: str = ""
    registration_enabled: bool = True
    api_access_key: str = ""
    client_id: str = ""
    connection_mode: str = "lan"
    connection_timeout_s: float = 5.0
    api_port: int = 8765
    api_host: str = "0.0.0.0"
    server_url: str = ""
    log_max_bytes: int = 8 * 1024 * 1024
    log_backups: int = 20

    # Network / monitoring
    lwip_ip: str = ""
    lwip_redirect_port: int = 58899
    local_server_port: int = 8899
    web_port: int = 8080
    cloud_host: str = "iot.eybond.com"
    cloud_port: int = 18899
    cloud_proxy_enabled: bool = True
    dtu_pn: str = ""
    poll_interval_s: float = 5.0
    socket_timeout_s: float = 8.0
    local_retries: int = 3
    redirect_retry_s: float = 8.0
    long_reconnect_s: float = 30.0
    grid_present_min_v: float = 180.0
    grid_present_max_v: float = 270.0
    grid_present_min_hz: float = 45.0
    grid_present_max_hz: float = 55.0
    telemetry_queue_size: int = 512
    parameter_refresh_s: int = 600

    # Security
    allow_write_commands: bool = False
    web_lan_only: bool = True
    web_read_only: bool = True

    # Logs
    protocol_logging: bool = True
    protocol_retention_days: int = 30

    # Energy model
    pv_correction_factor: float = 1.0
    inverter_self_consumption_w: float = 0.0
    max_integration_gap_s: int = 900

    # Taxes
    personal_income_tax_pct: float = 0.0
    military_tax_pct: float = 0.0
    retail_day_tariff_uah: float = 0.0
    retail_night_factor: float = 1.0
    green_tariff_commissioning_year: int = 0

    # Weather
    weather_location_name: str = ""
    weather_latitude: float | None = None
    weather_longitude: float | None = None
    weather_days: int = 10
    weather_timeout_s: float = 12.0
    pv_installed_kw: float = 1.0
    pv_forecast_fallback_pr: float = 0.80
    pv_forecast_max_training_days: int = 400

    # Windows integration
    autostart_windows: bool = False
    start_minimized: bool = False
    minimize_to_tray: bool = False

    # UI
    graph_colors: dict[str, str] | None = None
    graph_line_width: float = 1.8
    log_columns: list[str] | None = None
    show_raw_parameters: bool = True

    def __post_init__(self):
        if self.graph_colors is None:
            self.graph_colors = dict(DEFAULT_GRAPH_COLORS)
        if self.log_columns is None:
            self.log_columns = [
                "timestamp", "pv_w", "pv_v", "output_w", "grid_v",
                "battery_v", "battery_pct", "charge_a", "discharge_a",
                "temperature_c", "load_pct", "mode", "estimated_export_w", "source"
            ]

    def default_registry(self):
        return ([{'id':'logger-1','name':'Основний datalogger'}],
                [{'id':'inverter-1','name':'Інвертор Daxtromn','logger_id':'logger-1',
                  'driver':'daxtromn.pi30.0994','device_code':0x0994}])


def ensure_root() -> Path:
    root = Path(load_config().root_dir) if CONFIG_FILE.exists() else ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_config() -> AppConfig:
    cfg = AppConfig()
    from .migration import server_migrate
    server_migrate(ROOT,CONFIG_FILE,ROLE)
    if CONFIG_FILE.exists():
        raw=json.loads(CONFIG_FILE.read_text(encoding='utf-8-sig'))
        if not isinstance(raw,dict):raise ValueError('Некоректна конфігурація')
        for key,value in raw.items():
            if hasattr(cfg,key):setattr(cfg,key,value)

    cfg.root_dir = str(ROOT)
    # Only the Server generates read queries. External cloud bytes pass unchanged.
    cfg.allow_write_commands = False
    cfg.web_read_only = True
    cfg.protocol_logging = True
    cfg.autostart_windows = False
    cfg.config_schema = 2
    # This revision serves localhost and every LAN IPv4 interface.
    cfg.api_host = "0.0.0.0"

    if not isinstance(cfg.graph_colors, dict):
        cfg.graph_colors = dict(DEFAULT_GRAPH_COLORS)
    else:
        merged = dict(DEFAULT_GRAPH_COLORS)
        merged.update(cfg.graph_colors)
        cfg.graph_colors = merged

    return cfg


def save_config(cfg: AppConfig) -> None:
    if hasattr(cfg, '_api'):
        from .api_contract import CLIENT_CONFIG_FIELDS
        cfg._api.call('config', 'update', {k: getattr(cfg,k) for k in CLIENT_CONFIG_FIELDS})
    target_file = Path(cfg.root_dir) / ROLE / COMPONENT / "config.json"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with _SAVE_LOCK:
        temp = target_file.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(target_file)


def app_paths(cfg: AppConfig) -> dict[str, Path]:
    root = Path(cfg.root_dir)
    component = root / ROLE / COMPONENT
    logs = root / "Logs" / COMPONENT
    return {
        "component": component,
        "component_logs": logs,
        "root": root,
        "logs": root / "Logs",
        "inverter_logs": root / "Logs" / "Inverter",
        "protocol_logs": logs / "Protocol",
        "event_logs": logs / "System",
        "history": root / "History",
        "data": root / "Data",
        "cache": component / "Cache",
        "spool": root / "Logs" / "Inverter" / "Spool",
        "db": root / "Data" / "energy.db",
    }


def ensure_dirs(cfg: AppConfig) -> dict[str, Path]:
    paths = app_paths(cfg)
    for key, p in paths.items():
        if key == "db":
            continue
        p.mkdir(parents=True, exist_ok=True)
    return paths
