from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..config import AppConfig


class LWIPDisconnected(ConnectionError):
    pass


@dataclass
class LWIPStatus:
    state: str = "DISCONNECTED"
    peer: str = ""
    lan_ip: str = ""
    last_error: str = ""
    reconnect_count: int = 0
    last_connected_at: float = 0.0
    last_response_at: float = 0.0


class TCPListenerTransport:

    def __init__(self, cfg: AppConfig, event_callback: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.event_callback = event_callback
        self.status = LWIPStatus()
        self._listener: socket.socket | None = None
        self._socket: socket.socket | None = None
        self._socket_lock = threading.RLock()
        self._status_lock = threading.RLock()
        self._stop = threading.Event()
        self._listener_thread: threading.Thread | None = None
        self._tid = 100

    def _event(self, message: str) -> None:
        if self.event_callback:
            try:
                self.event_callback(message)
            except Exception:
                pass

    def _set_state(self, state: str, error: str = "") -> None:
        with self._status_lock:
            self.status.state = state
            if error:
                self.status.last_error = error

    def snapshot_status(self) -> LWIPStatus:
        with self._status_lock:
            return LWIPStatus(**self.status.__dict__)

    def start(self) -> None:
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._stop.clear()
        self._listener_thread = threading.Thread(target=self._listener_loop, name="LWIPListener", daemon=True)
        self._listener_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.close_active()
        listener = self._listener
        self._listener = None
        if listener:
            try:
                listener.close()
            except OSError:
                pass

    def _listener_loop(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener = srv
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.cfg.local_server_port))
            srv.listen(2)
            srv.settimeout(1.0)
            self._set_state("WAITING")
            while not self._stop.is_set():
                try:
                    sock, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                sock.settimeout(self.cfg.socket_timeout_s)
                with self._socket_lock:
                    old = self._socket
                    self._socket = sock
                if old:
                    try:
                        old.close()
                    except OSError:
                        pass
                now = time.time()
                with self._status_lock:
                    self.status.state = "CONNECTED"
                    self.status.peer = f"{addr[0]}:{addr[1]}"
                    self.status.last_error = ""
                    self.status.last_connected_at = now
                self._event(f"LWIP connected: {addr[0]}:{addr[1]}")
        except Exception as exc:
            self._set_state("ERROR", str(exc))
            self._event(f"LWIP listener error: {exc}")
        finally:
            try:
                srv.close()
            except OSError:
                pass
            self._listener = None

    @property
    def connected(self) -> bool:
        with self._socket_lock:
            return self._socket is not None

    def close_active(self, reason: str = "") -> None:
        with self._socket_lock:
            sock = self._socket
            self._socket = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        with self._status_lock:
            if not self._stop.is_set():
                self.status.state = "DISCONNECTED"
            if reason:
                self.status.last_error = reason
                self.status.reconnect_count += 1
        if reason:
            self._event(f"LWIP disconnected: {reason}")

