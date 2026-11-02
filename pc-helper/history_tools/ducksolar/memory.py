from __future__ import annotations

import gc
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class MemoryLimits:
    live_points: int = 7200          # ~10 h at 5 s
    event_items: int = 5000
    protocol_preview_items: int = 1000
    analytics_cache_items: int = 64


class BoundedRuntimeStore:
    """
    Keeps only bounded live/runtime data in RAM.
    Historical data belongs on disk/SQLite and is loaded on demand.
    """

    def __init__(self, limits: MemoryLimits | None = None):
        self.limits = limits or MemoryLimits()
        self.live_points = deque(maxlen=self.limits.live_points)
        self.events = deque(maxlen=self.limits.event_items)
        self.protocol_preview = deque(maxlen=self.limits.protocol_preview_items)
        self.analytics_cache: dict[str, Any] = {}
        self._cache_order = deque(maxlen=self.limits.analytics_cache_items)
        self._lock = threading.RLock()

    def add_live_point(self, item: Any) -> None:
        with self._lock:
            self.live_points.append(item)

    def add_event(self, item: Any) -> None:
        with self._lock:
            self.events.append(item)

    def add_protocol_preview(self, item: Any) -> None:
        with self._lock:
            self.protocol_preview.append(item)

    def cache_put(self, key: str, value: Any) -> None:
        with self._lock:
            if key not in self.analytics_cache and len(self.analytics_cache) >= self.limits.analytics_cache_items:
                while self._cache_order:
                    old = self._cache_order.popleft()
                    if old in self.analytics_cache:
                        self.analytics_cache.pop(old, None)
                        break
            self.analytics_cache[key] = value
            try:
                self._cache_order.remove(key)
            except ValueError:
                pass
            self._cache_order.append(key)

    def cache_get(self, key: str) -> Any:
        with self._lock:
            return self.analytics_cache.get(key)

    def clear_analytics_cache(self) -> None:
        with self._lock:
            self.analytics_cache.clear()
            self._cache_order.clear()

    def compact(self) -> None:
        """
        Strategic cleanup. Python already manages most memory automatically;
        this removes expired cache references and asks the GC to collect cycles.
        """
        with self._lock:
            if len(self.analytics_cache) > self.limits.analytics_cache_items:
                while len(self.analytics_cache) > self.limits.analytics_cache_items and self._cache_order:
                    self.analytics_cache.pop(self._cache_order.popleft(), None)
        gc.collect()


class MemoryHousekeeper:
    def __init__(self, store: BoundedRuntimeStore, interval_s: float = 300.0):
        self.store = store
        self.interval_s = interval_s
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="MemoryHousekeeper", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread(): self.thread.join(timeout=1)

    def _run(self) -> None:
        # Iterative loop: no recursive scheduling, so call stack does not grow.
        while not self.stop_event.wait(self.interval_s):
            self.store.compact()
