from dataclasses import dataclass, field, asdict
import ipaddress
import re

def checked_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ValueError('Device/logger ID must contain 1–64 letters, digits, _ or -')
    return value

@dataclass(frozen=True)
class ParameterSpec:
    canonical_id: str
    label_key: str
    ui_name: str
    protocol_name: str
    command: str
    unit: str = ''
    data_type: str = 'number'
    access: str = 'read_only'
    device_access: str = 'unknown'
    valid_range: tuple | None = None
    enum_values: dict = field(default_factory=dict)
    enum_label_keys: dict = field(default_factory=dict)
    scope: str = 'system'
    topology: str = 'system'
    source: str = 'device_capture'
    confidence: str = 'unverified'
    field_index: int | None = None
    legacy_key: str | None = None

    def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class PollTask:
    name: str
    request: bytes
    interval_s: float
    priority: int = 20
    telemetry: bool = False

@dataclass
class DeviceDefinition:
    id: str
    name: str
    logger_id: str
    driver: str
    device_code: int
    address: int = 1
    channel: int = 0

    def __post_init__(self):
        checked_id(self.id); checked_id(self.logger_id)
        if not isinstance(self.name, str) or not self.name.strip(): raise ValueError('Device name is required')
        for value, lo, hi in ((self.address, 1, 255), (self.device_code, 0, 65535), (self.channel, 0, 255)):
            if type(value) is not int or not lo <= value <= hi: raise ValueError('Invalid device addressing')

@dataclass
class LoggerDefinition:
    id: str
    name: str
    adapter: str = 'eybond.lwip'
    settings: dict = field(default_factory=dict)

    def __post_init__(self):
        checked_id(self.id)
        if not isinstance(self.name,str) or not self.name.strip():raise ValueError('Logger name is required')
        if not isinstance(self.settings, dict): raise ValueError('Logger settings must be an object')
        allowed = {'lwip_ip', 'lwip_redirect_port', 'local_server_port', 'cloud_host', 'cloud_port',
                   'cloud_proxy_enabled', 'dtu_pn', 'socket_timeout_s', 'long_reconnect_s', 'redirect_retry_s'}
        if not set(self.settings) <= allowed: raise ValueError('Unsupported logger settings')
        if 'lwip_ip' in self.settings: ipaddress.IPv4Address(self.settings['lwip_ip'])
        for key in ('local_server_port', 'lwip_redirect_port', 'cloud_port'):
            if key in self.settings and (type(self.settings[key]) is not int or not 1 <= self.settings[key] <= 65535):
                raise ValueError('Invalid port: ' + key)
        for key in ('socket_timeout_s', 'long_reconnect_s', 'redirect_retry_s'):
            if key in self.settings:
                import math
                value = self.settings[key]
                if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                    raise ValueError('Invalid timeout: ' + key)
        if 'cloud_proxy_enabled' in self.settings and type(self.settings['cloud_proxy_enabled']) is not bool:
            raise ValueError('Invalid proxy flag')
        if 'dtu_pn' in self.settings and not re.fullmatch(r'[A-Za-z0-9]{1,64}', self.settings['dtu_pn']):
            raise ValueError('Invalid datalogger PN')

def definitions(cfg):
    default_loggers, default_devices = cfg.default_registry()
    loggers = [LoggerDefinition(**row) for row in (cfg.dataloggers if cfg.dataloggers is not None else default_loggers)]
    devices = [DeviceDefinition(**row) for row in (cfg.devices if cfg.devices is not None else default_devices)]
    if not loggers or not devices: raise ValueError('At least one logger and inverter are required')
    if len(loggers) > 32 or len(devices) > 128: raise ValueError('Device registry limit exceeded')
    if len({x.id for x in loggers}) != len(loggers) or len({x.id for x in devices}) != len(devices):
        raise ValueError('Duplicate device/logger ID')
    logger_ids = {x.id for x in loggers}
    addresses = set()
    for dev in devices:
        if dev.logger_id not in logger_ids: raise ValueError('Unknown logger: ' + dev.logger_id)
        route = (dev.logger_id, dev.channel, dev.address)
        if route in addresses: raise ValueError('Two devices cannot share the same logger channel/address')
        addresses.add(route)
    ports = [x.settings.get('local_server_port', cfg.local_server_port) for x in loggers]
    hosts = [x.settings.get('lwip_ip', cfg.lwip_ip) for x in loggers]
    if len(set(hosts)) != len(hosts): raise ValueError('A datalogger IP cannot belong to two logger sessions')
    if len(set(ports)) != len(ports): raise ValueError('Each datalogger needs its own local TCP port')
    if cfg.api_port and cfg.api_port in ports: raise ValueError('API port conflicts with datalogger port')
    primary = cfg.primary_device_id or devices[0].id
    if primary not in {x.id for x in devices}: raise ValueError('Unknown primary device')
    return loggers, devices, primary
