from __future__ import annotations

import importlib
import logging
import os
import socket
import sys
import threading
import traceback
from pathlib import Path

import requests
import uvicorn
from PySide6.QtCore import QObject, QTimer, Signal

from share_desktop.paths import LOGS_DIR


class _QtLogHandler(logging.Handler):
    def __init__(self, emit_text) -> None:
        super().__init__()
        self._emit_text = emit_text
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit_text(self.format(record) + "\n")
        except Exception:
            pass


class ResultsApiRunner(QObject):
    """Run the local Results API inside the SHARE Client process.

    Uvicorn owns a dedicated background thread and event loop. The Qt UI remains
    responsive while the API serves localhost requests, and closing SHARE Client
    terminates the embedded service automatically.
    """

    output = Signal(str)
    state_changed = Signal(str)
    health_changed = Signal(bool, str)
    _thread_finished = Signal(int, str)

    def __init__(self, repo_root: Path, port: int, job_results_dir_name: str = "job-results") -> None:
        super().__init__()
        self.repo_root = repo_root.expanduser().resolve()
        self.port = int(port)
        self.job_results_dir_name = (job_results_dir_name or "job-results").strip().strip("/") or "job-results"
        self.host = "127.0.0.1"
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._workspace_root: Path | None = None
        self._site = ""
        self._expected_stop = False
        self._pending_restart: tuple[Path, str] | None = None
        self._recovery_attempts = 0
        self._consecutive_health_failures = 0
        self._startup_watch_attempts = 0
        self._thread_finished.connect(self._on_thread_finished)

    @property
    def api_root(self) -> Path:
        return self.repo_root / "local-results-api"

    @property
    def api_module_path(self) -> Path:
        return self.api_root / "app" / "main.py"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def pid(self) -> int:
        # Embedded mode has no separate OS process. The service shares the
        # supervisor PID and runs on a dedicated thread.
        return os.getpid()

    def host_job_save_location(self, workspace_root: Path) -> Path:
        path = workspace_root.expanduser().resolve() / self.job_results_dir_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def start(self, workspace_root: Path, site: str) -> None:
        workspace = workspace_root.expanduser().resolve()
        normalized_site = (site or "").strip()
        if not normalized_site:
            raise RuntimeError("The authenticated client site is required before starting the Results API.")
        if not self.api_module_path.is_file():
            raise RuntimeError(f"Results API application not found: {self.api_module_path}")
        if self.is_running:
            self.output.emit(f"[Results API] already running on http://{self.host}:{self.port}\n")
            self.state_changed.emit("running")
            self.check_health_async(attempts=3, delay_ms=500)
            return
        if not self._port_available():
            raise RuntimeError(
                f"Port {self.port} is already in use. Stop the previous Results API container or process before "
                "starting the embedded service. For the legacy container, run: "
                "docker stop duality-client-agent"
            )

        job_results = self.host_job_save_location(workspace)
        self._workspace_root = workspace
        self._site = normalized_site
        self._expected_stop = False
        self._pending_restart = None
        self._startup_watch_attempts = 0

        # The shared Results API code reads these values at startup and per request.
        os.environ["DUALITY_CLIENT_SITE"] = normalized_site
        os.environ["DUALITY_CLIENT_WORKSPACE"] = str(workspace)
        os.environ["DUALITY_NVFLARE_WORKSPACE"] = str(workspace)
        os.environ["DUALITY_NVFLARE_JOB_SAVE_LOCATION"] = str(job_results)

        app = self._load_fastapi_app()
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
            log_config=None,
            access_log=True,
        )
        self._server = uvicorn.Server(config)

        self.output.emit(f"[Results Config] mode: embedded Uvicorn\n")
        self.output.emit(f"[Results Config] site: {normalized_site}\n")
        self.output.emit(f"[Results Config] workspace: {workspace}\n")
        self.output.emit(f"[Results Config] DUALITY_NVFLARE_JOB_SAVE_LOCATION={job_results}\n")
        self.output.emit(f"[Results Config] endpoint: http://{self.host}:{self.port}\n")
        self.state_changed.emit("starting")

        self._thread = threading.Thread(
            target=self._run_server,
            name="SHARE-Results-API",
            daemon=True,
        )
        self._thread.start()
        QTimer.singleShot(100, self._watch_startup)

    def restart(self, workspace_root: Path, site: str) -> None:
        workspace = workspace_root.expanduser().resolve()
        normalized_site = (site or "").strip()
        if not self.is_running:
            self.start(workspace, normalized_site)
            return
        self.output.emit("[Results API] restart requested\n")
        self._pending_restart = (workspace, normalized_site)
        self._expected_stop = True
        self.state_changed.emit("restarting")
        if self._server is not None:
            self._server.should_exit = True

    def stop(self) -> None:
        self._pending_restart = None
        self._expected_stop = True
        if not self.is_running:
            self.state_changed.emit("stopped")
            return
        self.output.emit("[Results API] graceful stop requested\n")
        self.state_changed.emit("stopping")
        if self._server is not None:
            self._server.should_exit = True
        QTimer.singleShot(5000, self._force_exit_if_needed)

    def shutdown_for_app_exit(self, timeout_seconds: float = 5.0) -> None:
        self._pending_restart = None
        self._expected_stop = True
        server = self._server
        thread = self._thread
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, timeout_seconds))
        if thread is not None and thread.is_alive() and server is not None:
            server.force_exit = True
            thread.join(timeout=1.0)

    def status(self) -> dict:
        return {
            "exists": True,
            "running": self.is_running,
            "mode": "embedded",
            "pid": self.pid if self.is_running else None,
            "host": self.host,
            "port": self.port,
            "workspace": str(self._workspace_root) if self._workspace_root else "",
            "site": self._site,
        }

    def _load_fastapi_app(self):
        api_root_text = str(self.api_root)
        if api_root_text not in sys.path:
            sys.path.insert(0, api_root_text)
        module = importlib.import_module("app.main")
        app = getattr(module, "app", None)
        if app is None:
            raise RuntimeError(f"The Results API module does not expose 'app': {self.api_module_path}")
        return app

    def _run_server(self) -> None:
        log_path = LOGS_DIR / "results-service-output.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def emit_text(text: str) -> None:
            self.output.emit(text)
            try:
                with log_path.open("a", encoding="utf-8", errors="replace") as stream:
                    stream.write(text)
            except Exception:
                pass

        handler = _QtLogHandler(emit_text)
        loggers = [
            logging.getLogger("uvicorn"),
            logging.getLogger("uvicorn.error"),
            logging.getLogger("uvicorn.access"),
        ]
        previous: list[tuple[logging.Logger, int, bool]] = []
        for logger in loggers:
            previous.append((logger, logger.level, logger.propagate))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False

        code = 0
        detail = ""
        try:
            assert self._server is not None
            self._server.run()
        except SystemExit as exc:
            code = int(exc.code or 1)
            detail = f"Uvicorn exited during startup with code {code}."
            emit_text(f"[Results API] {detail}\n")
        except Exception as exc:
            code = 1
            detail = f"{exc}\n{traceback.format_exc()}"
            emit_text(f"[Results API] embedded server failure: {detail}\n")
        finally:
            for logger, old_level, old_propagate in previous:
                try:
                    logger.removeHandler(handler)
                    logger.setLevel(old_level)
                    logger.propagate = old_propagate
                except Exception:
                    pass
            self._thread_finished.emit(code, detail)

    def _watch_startup(self) -> None:
        if not self.is_running:
            return
        server = self._server
        if server is not None and server.started:
            self.state_changed.emit("running")
            self.output.emit(f"[Results API] serving http://{self.host}:{self.port}\n")
            self.check_health_async(attempts=8, delay_ms=500)
            return
        self._startup_watch_attempts += 1
        if self._startup_watch_attempts >= 100:
            self.output.emit("[Results API] startup timed out\n")
            self.state_changed.emit("error")
            self.stop()
            return
        QTimer.singleShot(100, self._watch_startup)

    def _on_thread_finished(self, code: int, detail: str) -> None:
        self._thread = None
        self._server = None
        pending = self._pending_restart
        self._pending_restart = None

        if pending is not None:
            self.output.emit("[Results API] restart stop completed; starting again\n")
            self._expected_stop = False
            QTimer.singleShot(250, lambda: self.start(pending[0], pending[1]))
            return

        if self._expected_stop:
            self._expected_stop = False
            self.state_changed.emit("stopped")
            return

        if self._workspace_root is not None and self._site and self._recovery_attempts < 3:
            self._recovery_attempts += 1
            delay_ms = 1000 * (2 ** (self._recovery_attempts - 1))
            self.output.emit(
                f"[Results API] exited unexpectedly with code {code}; automatic restart "
                f"{self._recovery_attempts}/3 in {delay_ms // 1000}s\n"
            )
            self.state_changed.emit("recovering")
            workspace = self._workspace_root
            site = self._site
            QTimer.singleShot(delay_ms, lambda: self.start(workspace, site))
            return

        if detail:
            self.output.emit(detail + "\n")
        self.state_changed.emit("error")

    def _force_exit_if_needed(self) -> None:
        if self.is_running and self._server is not None:
            self.output.emit("[Results API] graceful stop timed out; forcing Uvicorn exit\n")
            self._server.force_exit = True

    def _probe_health(self) -> tuple[bool, str]:
        url = f"http://{self.host}:{self.port}/health"
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
            return ok, f"{url} -> HTTP {response.status_code}{detail}"
        except Exception as exc:
            return False, f"{url} -> {exc}"

    def check_health(self) -> tuple[bool, str]:
        ok, msg = self._probe_health()
        self._record_health(ok, msg, recover=False)
        return ok, msg

    def check_health_async(self, attempts: int = 5, delay_ms: int = 750, recover: bool = False) -> None:
        remaining = max(1, attempts)

        def attempt() -> None:
            nonlocal remaining
            ok, msg = self._probe_health()
            if ok or remaining <= 1:
                self._record_health(ok, msg, recover=recover)
                return
            remaining -= 1
            QTimer.singleShot(delay_ms, attempt)

        attempt()

    def _record_health(self, ok: bool, msg: str, recover: bool) -> None:
        self.health_changed.emit(ok, msg)
        if ok:
            self._consecutive_health_failures = 0
            self._recovery_attempts = 0
            return

        self._consecutive_health_failures += 1
        if recover and self.is_running and self._consecutive_health_failures >= 3:
            self.output.emit(
                "[Results API] three consecutive health checks failed; restarting embedded service\n"
            )
            self._consecutive_health_failures = 0
            if self._workspace_root is not None and self._site:
                self.restart(self._workspace_root, self._site)

    def _port_available(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, self.port))
                return True
            except OSError:
                return False
