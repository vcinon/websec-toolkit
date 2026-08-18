"""Subprocess lifecycle management for scans.

Processes are always started from an argument array (never a shell string) and
run in their own process group so the whole tree can be signalled reliably.
Output is streamed to in-memory ring buffers that Server-Sent Event consumers
subscribe to, so Flask workers are never blocked by a running scan.
"""

from __future__ import annotations

import contextlib
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_line(line: str) -> str:
    """Strip ANSI escapes and control characters from tool output."""
    return CONTROL_PATTERN.sub("", ANSI_PATTERN.sub("", line)).rstrip("\r\n")


@dataclass
class RunningProcess:
    scan_id: int
    popen: subprocess.Popen
    log_path: Path
    buffer: deque[str]
    subscribers: list[queue.Queue] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    paused: bool = False
    finished: threading.Event = field(default_factory=threading.Event)

    @property
    def pid(self) -> int:
        return self.popen.pid


class ProcessManager:
    def __init__(self, buffer_lines: int = 5000):
        self._processes: dict[int, RunningProcess] = {}
        self._lock = threading.Lock()
        self._buffer_lines = buffer_lines

    # -- lifecycle ----------------------------------------------------
    def start(
        self,
        scan_id: int,
        argv: list[str],
        log_path: Path,
        on_line: Callable[[int, str], None] | None = None,
        on_exit: Callable[[int, int], None] | None = None,
        cwd: Path | None = None,
    ) -> RunningProcess:
        if self.get(scan_id) is not None:
            raise RuntimeError(f"Scan {scan_id} is already running")

        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
        }
        # argv list only; a shell is never involved
        popen = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            errors="replace",
            cwd=str(cwd) if cwd else None,
            env=env,
            start_new_session=True,
        )
        process = RunningProcess(
            scan_id=scan_id,
            popen=popen,
            log_path=log_path,
            buffer=deque(maxlen=self._buffer_lines),
        )
        with self._lock:
            self._processes[scan_id] = process

        thread = threading.Thread(
            target=self._pump,
            args=(process, on_line, on_exit),
            name=f"scan-{scan_id}-reader",
            daemon=True,
        )
        thread.start()
        return process

    def _pump(
        self,
        process: RunningProcess,
        on_line: Callable[[int, str], None] | None,
        on_exit: Callable[[int, int], None] | None,
    ) -> None:
        assert process.popen.stdout is not None
        with process.log_path.open("a", encoding="utf-8") as log_file:
            for raw_line in process.popen.stdout:
                for chunk in raw_line.replace("\r", "\n").split("\n"):
                    line = clean_line(chunk)
                    if not line.strip():
                        continue
                    log_file.write(line + "\n")
                    log_file.flush()
                    self._broadcast(process, line)
                    if on_line:
                        on_line(process.scan_id, line)
        exit_code = process.popen.wait()
        process.finished.set()
        self._broadcast(process, f"__EXIT__:{exit_code}", event="exit")
        with self._lock:
            self._processes.pop(process.scan_id, None)
        if on_exit:
            on_exit(process.scan_id, exit_code)

    def _broadcast(self, process: RunningProcess, line: str, event: str = "line") -> None:
        with process.lock:
            if event == "line":
                process.buffer.append(line)
            for subscriber in list(process.subscribers):
                with contextlib.suppress(queue.Full):
                    subscriber.put_nowait((event, line))

    # -- access -------------------------------------------------------
    def get(self, scan_id: int) -> RunningProcess | None:
        with self._lock:
            return self._processes.get(scan_id)

    def running_ids(self) -> list[int]:
        with self._lock:
            return list(self._processes)

    def buffered_lines(self, scan_id: int) -> list[str]:
        process = self.get(scan_id)
        if not process:
            return []
        with process.lock:
            return list(process.buffer)

    # -- control ------------------------------------------------------
    def _signal(self, process: RunningProcess, sig: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(process.pid), sig)

    def pause(self, scan_id: int) -> bool:
        process = self.get(scan_id)
        if not process or process.paused:
            return False
        self._signal(process, signal.SIGSTOP)
        process.paused = True
        self._broadcast(process, "[toolkit] scan paused")
        return True

    def resume(self, scan_id: int) -> bool:
        process = self.get(scan_id)
        if not process or not process.paused:
            return False
        self._signal(process, signal.SIGCONT)
        process.paused = False
        self._broadcast(process, "[toolkit] scan resumed")
        return True

    def stop(self, scan_id: int, timeout: float = 5.0) -> bool:
        process = self.get(scan_id)
        if not process:
            return False
        if process.paused:
            self._signal(process, signal.SIGCONT)
            process.paused = False
        self._broadcast(process, "[toolkit] stopping scan")
        self._signal(process, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.popen.poll() is not None:
                break
            time.sleep(0.1)
        else:
            self._signal(process, signal.SIGKILL)
        process.finished.wait(timeout=timeout)
        return True

    def stop_all(self) -> None:
        for scan_id in self.running_ids():
            self.stop(scan_id, timeout=2.0)

    # -- streaming ----------------------------------------------------
    def subscribe(self, scan_id: int) -> tuple[list[str], queue.Queue | None]:
        process = self.get(scan_id)
        if not process:
            return [], None
        subscriber: queue.Queue = queue.Queue(maxsize=10000)
        with process.lock:
            backlog = list(process.buffer)
            process.subscribers.append(subscriber)
        return backlog, subscriber

    def unsubscribe(self, scan_id: int, subscriber: queue.Queue) -> None:
        process = self.get(scan_id)
        if not process:
            return
        with process.lock:
            if subscriber in process.subscribers:
                process.subscribers.remove(subscriber)

    def stream(self, scan_id: int) -> Iterator[tuple[str, str]]:
        """Yield (event, data) tuples for a running scan."""
        backlog, subscriber = self.subscribe(scan_id)
        for line in backlog:
            yield ("line", line)
        if subscriber is None:
            yield ("exit", "__EXIT__:done")
            return
        try:
            while True:
                try:
                    event, line = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ("ping", "")
                    if self.get(scan_id) is None:
                        yield ("exit", "__EXIT__:done")
                        return
                    continue
                yield (event, line)
                if event == "exit":
                    return
        finally:
            self.unsubscribe(scan_id, subscriber)


process_manager = ProcessManager()
