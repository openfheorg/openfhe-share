from __future__ import annotations

import codecs
import os
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QObject, Signal


class ManagedProcess(QObject):
    output = Signal(str)
    line = Signal(str)
    state_changed = Signal(str)
    exited = Signal(int)

    def __init__(self, name: str, log_path: Path, use_pty: bool = False) -> None:
        super().__init__()
        self.name = name
        self.log_path = log_path
        self.use_pty = use_pty
        self.process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._waiter_thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._pty_master_fd: int | None = None
        self.last_output_at: datetime | None = None
        self._line_buffer = ""

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def pid(self) -> int | None:
        if self.process is None:
            return None
        return self.process.pid

    def start(
        self,
        cmd: Sequence[str],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if self.is_running:
            self.output.emit(f"[{self.name}] already running; PID {self.pid}\n")
            return

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop_requested.clear()
        self._line_buffer = ""
        self.state_changed.emit("starting")

        if self.use_pty and os.name == "posix":
            self._start_pty(cmd, cwd=cwd, env=env)
        else:
            self._start_pipe(cmd, cwd=cwd, env=env)

        self.state_changed.emit("running")
        self.output.emit(f"[{self.name}] started; PID {self.pid}\n")

        self._waiter_thread = threading.Thread(target=self._wait_for_exit, name=f"{self.name}-wait", daemon=True)
        self._waiter_thread.start()

    def _start_pipe(self, cmd: Sequence[str], cwd: Path | str | None, env: Mapping[str, str] | None) -> None:
        self.process = subprocess.Popen(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=False,
            bufsize=0,
            start_new_session=True,
        )
        assert self.process.stdout is not None
        self._reader_thread = threading.Thread(target=self._read_stream, args=(self.process.stdout,), name=f"{self.name}-read", daemon=True)
        self._reader_thread.start()

    def _start_pty(self, cmd: Sequence[str], cwd: Path | str | None, env: Mapping[str, str] | None) -> None:
        master_fd, slave_fd = os.openpty()
        self._pty_master_fd = master_fd
        self.process = subprocess.Popen(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            text=False,
            bufsize=0,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)
        self._reader_thread = threading.Thread(target=self._read_fd, args=(master_fd,), name=f"{self.name}-pty-read", daemon=True)
        self._reader_thread.start()

    def _read_fd(self, fd: int) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while not self._stop_requested.is_set():
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    self._handle_text(text)
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
            self._pty_master_fd = None

    def _read_stream(self, stream) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while not self._stop_requested.is_set():
                chunk = stream.read(4096)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    self._handle_text(text)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _handle_text(self, text: str) -> None:
        self.last_output_at = datetime.now(timezone.utc)
        self.output.emit(text)
        with self.log_path.open("a", encoding="utf-8", errors="replace") as f:
            f.write(text)

        normalized = text.replace("\r", "\n")
        self._line_buffer += normalized
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            if line:
                self.line.emit(line)

    def terminate(self) -> None:
        if not self.is_running:
            return
        self.state_changed.emit("stopping")
        try:
            self.process.terminate()
        except Exception:
            pass

    def kill_process_group(self, grace_seconds: float = 0) -> None:
        if not self.is_running or self.process is None:
            return
        self.state_changed.emit("killing")
        pid = self.process.pid
        if os.name == "posix":
            try:
                os.killpg(pid, signal.SIGTERM)
            except Exception:
                try:
                    self.process.terminate()
                except Exception:
                    pass
            if grace_seconds:
                try:
                    self.process.wait(timeout=grace_seconds)
                    return
                except Exception:
                    pass
            try:
                os.killpg(pid, signal.SIGKILL)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        else:
            try:
                self.process.kill()
            except Exception:
                pass

    def _wait_for_exit(self) -> None:
        code = 0
        if self.process is not None:
            try:
                code = int(self.process.wait())
            except Exception:
                code = -1
        self._stop_requested.set()
        self.state_changed.emit("stopped" if code == 0 else "exited")
        self.exited.emit(code)
