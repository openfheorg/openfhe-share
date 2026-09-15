from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal, QTimer

from share_desktop.paths import LOGS_DIR
from share_desktop.runners.process_runner import ManagedProcess


class ResultsContainerRunner(QObject):
    output = Signal(str)
    state_changed = Signal(str)
    health_changed = Signal(bool, str)

    def __init__(self, repo_root: Path, container_name: str, port: int, job_results_dir_name: str = "job-results") -> None:
        super().__init__()
        self.repo_root = repo_root
        self.container_name = container_name
        self.port = port
        self.job_results_dir_name = (job_results_dir_name or "job-results").strip().strip("/") or "job-results"
        self.control_proc = ManagedProcess("Results Control", LOGS_DIR / "results-control-output.log", use_pty=False)
        self.logs_proc = ManagedProcess("Results API", LOGS_DIR / "results-service-output.log", use_pty=False)
        self._active_action = ""
        self.control_proc.output.connect(self.output)
        self.control_proc.state_changed.connect(lambda state: self.state_changed.emit(f"control-{state}"))
        self.control_proc.exited.connect(self._on_control_exit)
        self.logs_proc.output.connect(self.output)
        self.logs_proc.state_changed.connect(lambda state: self.state_changed.emit(f"logs-{state}"))

    @property
    def agent_manage_path(self) -> Path:
        return self.repo_root / "local-results-api" / "agent_manage.py"

    def container_job_save_location(self) -> str:
        # Workspace is mounted into the container at /nvflare. The host-side
        # NVFlare process writes to <workspace>/<job_results_dir_name>, so the
        # results API must read the equivalent path inside the container.
        return f"/nvflare/{self.job_results_dir_name}"

    def host_job_save_location(self, workspace_root: Path) -> Path:
        path = workspace_root.expanduser().resolve() / self.job_results_dir_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _cmd(self, args: list[str], workspace_root: Path | None = None) -> list[str]:
        if not self.agent_manage_path.exists():
            raise RuntimeError(f"agent_manage.py not found: {self.agent_manage_path}")
        cmd = [sys.executable, str(self.agent_manage_path), *args]
        if workspace_root is not None:
            workspace = workspace_root.expanduser().resolve()
            host_results = self.host_job_save_location(workspace)
            container_results = self.container_job_save_location()
            self.output.emit(f"[Results Config] workspace host path: {workspace}\n")
            self.output.emit(f"[Results Config] job results host path: {host_results}\n")
            self.output.emit(f"[Results Config] DUALITY_NVFLARE_JOB_SAVE_LOCATION={container_results}\n")
            cmd.extend(["--workspace", str(workspace)])
            cmd.extend(["--job_save_location", container_results])
        return cmd

    def _run_control(self, args: list[str], workspace_root: Path | None = None, action: str = "") -> None:
        if self.control_proc.is_running:
            self.output.emit("[Results Control] command already running\n")
            return
        self._active_action = action
        cmd = self._cmd(args, workspace_root=workspace_root)
        self.output.emit(f"[Results Control] {' '.join(cmd)}\n")
        self.control_proc.start(cmd, cwd=self.repo_root)

    def build_deploy(self, workspace_root: Path) -> None:
        self.state_changed.emit("building")
        self._run_control(
            ["build_deploy", "--container", self.container_name, "--port", str(self.port)],
            workspace_root=workspace_root,
            action="start",
        )

    def start(self, workspace_root: Path) -> None:
        self.state_changed.emit("starting")
        self._run_control(
            ["start", "--container", self.container_name, "--port", str(self.port)],
            workspace_root=workspace_root,
            action="start",
        )

    def stop(self) -> None:
        self.state_changed.emit("stopping")
        # Stop following logs first so the UI does not confuse the live log tail
        # with the actual stop command.
        self.stop_logs()

        # Older prototype builds ran `docker run` attached in the control
        # process. If that process is still attached, it blocks the stop command.
        # Detach/kill the stale control process, then issue the real docker stop.
        if self.control_proc.is_running:
            self.output.emit("[Results Control] terminating attached control process before stop\n")
            self.control_proc.kill_process_group(grace_seconds=1)
            QTimer.singleShot(500, lambda: self._run_control(["stop", "--container", self.container_name], action="stop"))
            return

        self._run_control(["stop", "--container", self.container_name], action="stop")

    def status(self) -> dict:
        cmd = self._cmd(["status", "--container", self.container_name])
        result = subprocess.run(
            cmd,
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
        )
        if result.stdout:
            self.output.emit(result.stdout)
        try:
            return json.loads((result.stdout or "").strip().splitlines()[-1])
        except Exception:
            return {"exists": False, "running": False, "raw": result.stdout or ""}

    def _probe_health(self) -> tuple[bool, str]:
        url = f"http://127.0.0.1:{self.port}/health"
        try:
            response = requests.get(url, timeout=2)
            ok = 200 <= response.status_code < 300
            detail = ""
            try:
                payload = response.json()
                job_path = payload.get("job_save_location")
                exists = payload.get("job_save_location_exists")
                if job_path:
                    detail = f" · job results {job_path} exists={exists}"
            except Exception:
                pass
            msg = f"{url} -> HTTP {response.status_code}{detail}"
            return ok, msg
        except Exception as exc:
            return False, f"{url} -> {exc}"

    def check_health(self) -> tuple[bool, str]:
        ok, msg = self._probe_health()
        self.health_changed.emit(ok, msg)
        return ok, msg

    def check_health_async(self, attempts: int = 5, delay_ms: int = 750) -> None:
        """Retry health checks without freezing the Qt UI.

        Uvicorn can briefly accept and close connections while the container is
        starting/restarting. The browser may work a second later, so avoid
        leaving the overview card stuck on a transient RemoteDisconnected error.
        """
        remaining = max(1, attempts)

        def attempt() -> None:
            nonlocal remaining
            ok, msg = self._probe_health()
            if ok or remaining <= 1:
                self.health_changed.emit(ok, msg)
                return
            remaining -= 1
            QTimer.singleShot(delay_ms, attempt)

        attempt()

    def start_logs(self) -> None:
        if self.logs_proc.is_running:
            return
        # docker logs normally prints the entire old container history before following.
        # Keep the demo UI readable by showing only a small recent tail, then live logs.
        self.logs_proc.start(["docker", "logs", "--tail", "100", "-f", self.container_name], cwd=self.repo_root)

    def stop_logs(self) -> None:
        self.logs_proc.kill_process_group(grace_seconds=1)

    def _on_control_exit(self, code: int) -> None:
        self.output.emit(f"[Results Control exited with code {code}]\n")
        action = self._active_action
        self._active_action = ""
        if code == 0 and action == "start":
            self.state_changed.emit("running")
            self.start_logs()
            self.check_health_async(attempts=10, delay_ms=1000)
        elif code == 0 and action == "stop":
            self.stop_logs()
            self.state_changed.emit("stopped")
        elif code == 0:
            self.state_changed.emit("stopped")
        else:
            self.state_changed.emit("error")
