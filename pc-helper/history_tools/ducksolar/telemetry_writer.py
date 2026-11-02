from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from .config import AppConfig, ensure_dirs
from .storage import Storage, TelemetryRecord


class TelemetryWriter:
    """
    Keeps disk I/O outside the monitoring/network thread.

    - bounded RAM queue;
    - CSV/SQLite error never disconnects LWIP;
    - failed records are spooled to JSONL on disk;
    - spool is replayed later in a streaming manner.
    """

    def __init__(self, cfg: AppConfig, storage: Storage, log_service=None):
        self.cfg = cfg
        self.storage = storage
        self.log_service = log_service
        self.paths = ensure_dirs(cfg)
        self.queue: queue.Queue[TelemetryRecord] = queue.Queue(
            maxsize=max(32, int(cfg.telemetry_queue_size))
        )
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._last_disk_error = ""
        self._spool_lock = threading.RLock()

    @property
    def spool_path(self) -> Path:
        folder=self.paths['spool']
        if self.cfg.history_device_id and self.cfg.history_device_id!=self.cfg.legacy_device_id:
            folder=folder/'Devices'/self.cfg.history_device_id
        folder.mkdir(parents=True,exist_ok=True)
        return folder / 'telemetry_spool.jsonl'

    def _event(self, text: str) -> None:
        if self.log_service:
            self.log_service.event(text)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run, name="TelemetryWriter", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)

    def submit(self, rec: TelemetryRecord) -> bool:
        from .resource_manager import budget
        # Expand only as the queue needs it; spool under actual memory pressure.
        size=max(1024,len(self._serialize(rec).encode('utf-8'))*3)
        self.queue.maxsize=max(1,budget()//size)
        try:
            self.queue.put_nowait(rec)
            return True
        except queue.Full:
            self._event("Telemetry writer queue full: persisting record to disk spool")
            return self._spool(rec)

    @staticmethod
    def _serialize(rec: TelemetryRecord) -> str:
        return json.dumps({
            "timestamp": rec.timestamp.isoformat(),
            "source": rec.source,
            "values": rec.values,
            "device_id": rec.device_id,
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _deserialize(line: str) -> TelemetryRecord:
        obj = json.loads(line)
        return TelemetryRecord(
            timestamp=datetime.fromisoformat(obj["timestamp"]),
            source=str(obj["source"]),
            values=dict(obj["values"]),
            device_id=obj.get('device_id',''),
        )

    def _spool(self, rec: TelemetryRecord) -> bool:
        try:
            with self._spool_lock, self.spool_path.open("a", encoding="utf-8") as f:
                f.write(self._serialize(rec) + "\n")
            return True
        except Exception as exc:
            self._last_disk_error=f"Spool: {type(exc).__name__}: {exc}"
            self._event(f"CRITICAL: telemetry spool failed: {exc}")
            return False

    def _try_write(self, rec: TelemetryRecord) -> bool:
        try:
            self.storage.append_telemetry(rec)
            if self._last_disk_error:
                self._event("Telemetry storage recovered")
                self._last_disk_error = ""
            return True
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            if msg != self._last_disk_error:
                self._event(f"Telemetry storage unavailable; using spool: {msg}")
                self._last_disk_error = msg
            return False

    def _flush_spool(self, limit: int = 100) -> None:
        with self._spool_lock:
            self._flush_spool_locked(limit)

    def _flush_spool_locked(self, limit: int) -> None:
        path = self.spool_path
        if not path.exists() or path.stat().st_size == 0:
            return

        tmp = path.with_suffix(".remaining.tmp")
        processed = 0
        failed = False

        try:
            with path.open("r", encoding="utf-8") as src, \
                 tmp.open("w", encoding="utf-8") as remaining:
                for line in src:
                    if not line.strip():
                        continue

                    if processed < limit and not failed:
                        try:
                            rec = self._deserialize(line)
                        except Exception:
                            self._event("Discarded malformed telemetry spool line")
                            processed += 1
                            continue

                        if self._try_write(rec):
                            processed += 1
                            continue

                        failed = True

                    remaining.write(line)

            tmp.replace(path)
            if path.exists() and path.stat().st_size == 0:
                path.unlink(missing_ok=True)

        except Exception as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            self._event(f"Telemetry spool replay error: {exc}")

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                rec = self.queue.get(timeout=0.5)
            except queue.Empty:
                self._flush_spool(limit=30)
                continue

            try:
                if not self._try_write(rec):
                    self._spool(rec)
                else:
                    self._flush_spool(limit=30)
            finally:
                self.queue.task_done()

        # Persist every accepted record when stopping, not only the first 100.
        for _ in range(self.queue.qsize()):
            try:
                rec = self.queue.get_nowait()
            except queue.Empty:
                break
            try:
                if not self._try_write(rec):
                    self._spool(rec)
            finally:
                self.queue.task_done()
