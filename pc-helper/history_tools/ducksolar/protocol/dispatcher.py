from __future__ import annotations

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable


class Priority(IntEnum):
    CLOUD = 0
    CRITICAL = 10
    MONITOR = 20
    SLOW = 30


_counter = itertools.count()


@dataclass(order=True)
class ProtocolJob:
    priority: int
    sequence: int = field(default_factory=lambda: next(_counter))
    name: str = field(compare=False, default="")
    request: bytes = field(compare=False, default=b"")
    action: Callable | None = field(compare=False, default=None)
    deadline: float | None = field(compare=False, default=None)
    cancelled: threading.Event = field(compare=False, default_factory=threading.Event)
    callback: Callable[[bytes | None, Exception | None], None] | None = field(compare=False, default=None)


class ProtocolDispatcher:
    """Single serialized transaction queue for the LWIP/inverter channel."""

    def __init__(self, transport, max_queue_size: int = 256):
        self.transport = transport
        self.queue: queue.PriorityQueue[ProtocolJob] = queue.PriorityQueue(maxsize=max_queue_size)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="ProtocolDispatcher", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        while True:
            try: job = self.queue.get_nowait()
            except queue.Empty: break
            if job.callback: job.callback(None, ConnectionError('Server stopping'))
            self.queue.task_done()
        if self.thread: self.thread.join(timeout=3)


    def submit(self, job: ProtocolJob, timeout: float = 0.25) -> bool:
        if self.stop_event.is_set(): return False
        try:
            self.queue.put(job, timeout=timeout)
            return True
        except queue.Full:
            return False

    def transact_sync(self, request: bytes, priority: int, name: str, timeout: float = 12.0, action=None, on_wait=None) -> bytes:
        done = threading.Event()
        result: dict[str, object] = {}

        def callback(response, error):
            result["response"] = response
            result["error"] = error
            done.set()

        job=ProtocolJob(
            priority=int(priority),
            name=name,
            request=request,
            action=action,
            callback=callback, deadline=time.monotonic()+timeout,
        )
        if not self.submit(job):
            raise TimeoutError("Protocol dispatcher queue is full")

        wait_until=time.monotonic()+timeout
        while not done.wait(min(.1,max(0,wait_until-time.monotonic()))):
            if time.monotonic()>=wait_until:
                job.cancelled.set()
                raise TimeoutError(f"Protocol job timed out: {name}")
            if on_wait is not None:
                try:
                    on_wait()
                except Exception:
                    # Do not abandon an already transmitted request or retry it
                    # because observational live publication failed.
                    import logging
                    logging.getLogger(__name__).exception('Live refresh during protocol wait failed')

        err = result.get("error")
        if isinstance(err, Exception):
            raise err

        response = result.get("response")
        if not isinstance(response, (bytes, bytearray)):
            raise TimeoutError(f"No protocol response: {name}")
        return bytes(response)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                job = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            response = None
            error = None
            try:
                if job.cancelled.is_set() or job.deadline is not None and time.monotonic()>job.deadline:
                    raise TimeoutError('Queued operation expired before execution')
                response = job.action() if job.action else self.transport.transact(job.request)
            except Exception as exc:
                error = exc

            try:
                if job.callback:
                    job.callback(response, error)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Protocol result callback failed')
            finally:
                self.queue.task_done()
