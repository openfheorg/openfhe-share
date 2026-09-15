from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from share_desktop.paths import LOGS_DIR
from share_desktop.runners.process_runner import ManagedProcess


class NvflareRunner(QObject):
    """Runs and monitors the extracted NVFlare startup kit for the desktop demo.

    The stock startup/start.sh backgrounds startup/sub_start.sh, then exits. That made
    the first prototype report NVFlare as stopped even though the real FL process may
    still be alive. For the desktop UI we run sub_start.sh in the foreground instead.
    This uses the startup kit's own script without editing it and lets the app capture
    stdout/stderr for the full lifetime of the client.
    """

    output = Signal(str)
    state_changed = Signal(str)
    exited = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.proc = ManagedProcess("NVFlare", LOGS_DIR / "nvflare-output.log", use_pty=True)
        self.proc.output.connect(self.output)
        self.proc.state_changed.connect(self.state_changed)
        self.proc.exited.connect(self._on_proc_exit)
        self._workspace_root: Path | None = None

    def set_workspace(self, workspace_root: Path | None) -> None:
        if workspace_root is None:
            return
        self._workspace_root = workspace_root.expanduser().resolve()

    @property
    def is_running(self) -> bool:
        if self.proc.is_running:
            return True
        return self._live_pid() is not None

    @property
    def pid(self) -> int | None:
        if self.proc.pid and self.proc.is_running:
            return self.proc.pid
        return self._live_pid()

    def status_detail(self) -> str:
        pid = self.pid
        if not pid:
            return "not running"
        daemon_pid = self._read_pid(self._pid_file("daemon_pid.fl"))
        client_pid = self._read_pid(self._pid_file("pid.fl"))
        parts = []
        if daemon_pid and self._pid_alive(daemon_pid):
            parts.append(f"daemon PID {daemon_pid}")
        if client_pid and self._pid_alive(client_pid):
            parts.append(f"client PID {client_pid}")
        return " · ".join(parts) if parts else f"PID {pid}"

    def start(self, workspace_root: Path, env: dict[str, str] | None = None) -> None:
        workspace = workspace_root.expanduser().resolve()
        self.set_workspace(workspace)
        startup_dir = workspace / "startup"
        start_sh = startup_dir / "start.sh"
        sub_start_sh = startup_dir / "sub_start.sh"
        if not start_sh.exists():
            raise RuntimeError(f"start.sh not found: {start_sh}")
        if self.is_running:
            self.output.emit(f"[NVFlare] already running; {self.status_detail()}\n")
            self.state_changed.emit("running")
            return

        self._cleanup_stale_control_files(workspace)

        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        run_env["DUALITY_CLIENT_WORKSPACE"] = str(workspace)
        if run_env.get("DUALITY_NVFLARE_JOB_SAVE_LOCATION"):
            self.output.emit(
                f"[NVFlare] DUALITY_NVFLARE_JOB_SAVE_LOCATION={run_env['DUALITY_NVFLARE_JOB_SAVE_LOCATION']}\n"
            )

        if sub_start_sh.exists():
            self.output.emit(
                "[NVFlare] launching startup/sub_start.sh in the foreground for UI monitoring.\n"
                "[NVFlare] This is the same startup-kit worker that startup/start.sh backgrounds.\n"
            )
            cmd = ["bash", "./sub_start.sh"]
        else:
            self.output.emit(
                "[NVFlare] startup/sub_start.sh not found; falling back to startup/start.sh.\n"
                "[NVFlare] If start.sh backgrounds the worker, UI state may be less precise.\n"
            )
            cmd = ["bash", "./start.sh"]
        self.proc.start(cmd, cwd=startup_dir, env=run_env)

    def graceful_stop(self, workspace_root: Path) -> str:
        workspace = workspace_root.expanduser().resolve()
        self.set_workspace(workspace)
        startup_dir = workspace / "startup"
        stop_sh = startup_dir / "stop_fl.sh"
        if not stop_sh.exists():
            raise RuntimeError(f"stop_fl.sh not found: {stop_sh}")
        self.state_changed.emit("stopping")
        result = subprocess.run(
            ["bash", "./stop_fl.sh"],
            cwd=startup_dir,
            input="y\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        text = result.stdout or ""
        self.output.emit(text)
        if not self.is_running:
            self.state_changed.emit("stopped")
        else:
            self.output.emit(f"[NVFlare] stop requested; waiting for shutdown. {self.status_detail()}\n")
        return text

    def force_kill(self, workspace_root: Path | None = None) -> None:
        if workspace_root is not None:
            self.set_workspace(workspace_root)
        self.state_changed.emit("killing")
        self.proc.kill_process_group(grace_seconds=3)

        workspace = self._workspace_root
        if workspace is not None:
            # Kill any pids recorded by the startup kit too. This covers cases where
            # the client was started before the GUI, or start.sh backgrounded work.
            for filename in ("pid.fl", "daemon_pid.fl"):
                pid = self._read_pid(self._pid_file(filename))
                if pid and self._pid_alive(pid):
                    self._terminate_pid(pid)
            self._remove_control_files(workspace)
        self.state_changed.emit("stopped")

    def _on_proc_exit(self, code: int) -> None:
        # If an old backgrounded pid is still alive, keep the user-facing state honest.
        if self._live_pid() is not None:
            self.state_changed.emit("running")
            self.output.emit(f"[NVFlare] launcher exited with code {code}, but startup-kit pid is still alive: {self.status_detail()}\n")
        else:
            self.exited.emit(code)

    def _pid_file(self, filename: str) -> Path | None:
        if self._workspace_root is None:
            return None
        return self._workspace_root / filename

    def _read_pid(self, path: Path | None) -> int | None:
        if path is None or not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            return int(text) if text else None
        except Exception:
            return None

    def _live_pid(self) -> int | None:
        for filename in ("daemon_pid.fl", "pid.fl"):
            pid = self._read_pid(self._pid_file(filename))
            if pid and self._pid_alive(pid):
                return pid
        return None

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    def _terminate_pid(self, pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            pass
        deadline = time.time() + 3
        while time.time() < deadline:
            if not self._pid_alive(pid):
                return
            time.sleep(0.2)
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    def _cleanup_stale_control_files(self, workspace: Path) -> None:
        # A stale shutdown.fl/restart.fl can make the client immediately stop after launch.
        for filename in ("shutdown.fl", "restart.fl"):
            try:
                (workspace / filename).unlink(missing_ok=True)
            except Exception:
                pass
        for filename in ("pid.fl", "daemon_pid.fl"):
            path = workspace / filename
            pid = self._read_pid(path)
            if pid is None or not self._pid_alive(pid):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _remove_control_files(self, workspace: Path) -> None:
        for filename in ("pid.fl", "daemon_pid.fl", "shutdown.fl", "restart.fl"):
            try:
                (workspace / filename).unlink(missing_ok=True)
            except Exception:
                pass
