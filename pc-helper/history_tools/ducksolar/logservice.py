from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from uuid import uuid4
from .config import AppConfig, app_paths, COMPONENT, VERSION


class LogService:
    """Independent bounded system/protocol journals; protocol bytes are never truncated."""
    def __init__(self, cfg: AppConfig, event_filename="System.log", protocol=True):
        self.cfg = cfg
        self.paths = app_paths(cfg)
        self.session_id = uuid4().hex
        self.handlers = []
        from .repeat_errors import RepeatErrors
        self.repeats=RepeatErrors()
        self.event_logger = self._logger('System', event_filename)
        self.protocol_logger = self._logger('Protocol', 'Proxy_Traffic.jsonl') if protocol else None
        self.ess_event_logger = self._logger('ESS', 'ESS_Events.jsonl') if cfg.cloud_proxy_enabled else None
        self.ess_protocol_logger = self._logger('ESS', 'ESS_Traffic.jsonl') if cfg.cloud_proxy_enabled and protocol else None

    def _logger(self, folder, filename):
        path = self.paths['component_logs'] / folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger('dx.' + self.session_id + '.' + folder + '.' + filename)
        logger.setLevel(logging.INFO); logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=max(65536, self.cfg.log_max_bytes),
            backupCount=max(1, self.cfg.log_backups), encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler); self.handlers.append((logger, handler))
        return logger

    def event(self, message, code=None, **details):
        stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        for channel,event_code,event_message,values,at in self.repeats.accept('system',code or 'system.event',message,details,stamp):
            self._emit(channel,event_code,event_message,values,at)

    def _emit(self,channel,code,message,details,stamp):
        metadata = dict(code=code or 'system.event', component=COMPONENT, version=VERSION,
                        session_id=self.session_id, **details)
        if channel=='ess':
            if self.ess_event_logger:self.ess_event_logger.info(json.dumps(dict(metadata,timestamp=stamp),ensure_ascii=False,separators=(',',':')))
            return
        self.event_logger.info('%s %s %s', stamp, message,
            json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))

    def exception(self, message, code='operation.error', **details):
        import traceback
        self.event(message, code=code, traceback=traceback.format_exc(), **details)

    def ess_event(self, code, **details):
        if self.ess_event_logger is not None:
            stamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds')
            for channel,event_code,message,values,at in self.repeats.accept('ess',code,'',details,stamp):self._emit(channel,event_code,message,values,at)

    def traffic(self, direction, data, connection_id='', result='observed', forwarding='n/a', **extra):
        data = bytes(data)
        record = dict(timestamp=datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                      session_id=self.session_id, connection_id=connection_id,
                      direction=direction, raw_hex=data.hex(' '), byte_count=len(data),
                      ascii=''.join(chr(b) if 32 <= b < 127 else '.' for b in data),
                      protocol='unknown', command=None, pi30_command=None,
                      decoded_fields={}, result=result, forwarding=forwarding)
        # Decode observationally, never use a decoder decision to gate forwarding.
        try:
            if len(data) >= 8 and int.from_bytes(data[4:6], 'big') == len(data)-6:
                record['protocol'] = 'EyeBond'
                record['decoded_fields'] = dict(transaction_id=int.from_bytes(data[:2], 'big'),
                                                device=data[2:4].hex(), address=data[6], function=data[7])
                if data[7]==4 and len(data)==8:
                    record['decoded_fields']['packet_type']='empty_response'
                    record['error_code']='logger.empty_response'
                elif data[7]==4:
                    from .drivers.registry import inspect_payload
                    record.update(inspect_payload(data,extra.get('command')))
        except Exception as exc:
            record['decode_error'] = str(exc)
        record.update(extra)
        if self.protocol_logger is None:
            return
        record.update(component=COMPONENT, version=VERSION)
        self.protocol_logger.info(json.dumps(record, ensure_ascii=False, separators=(',', ':')))
        if self.ess_protocol_logger is not None and 'ESS' in direction:
            self.ess_protocol_logger.info(json.dumps(record, ensure_ascii=False, separators=(',', ':')))

    def protocol(self, direction, data):
        self.traffic(direction, data.encode() if isinstance(data, str) else data)

    def close(self):
        for channel,code,message,details,stamp in self.repeats.flush():self._emit(channel,code,message,details,stamp)
        for logger, handler in self.handlers:
            handler.flush(); handler.close(); logger.removeHandler(handler)
