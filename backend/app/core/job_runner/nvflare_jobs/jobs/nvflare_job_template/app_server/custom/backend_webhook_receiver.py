import os
import queue
import threading
import time
import traceback
from datetime import datetime

import requests
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey
from nvflare.apis.shareable import Shareable
from nvflare.app_common.widgets.streaming import AnalyticsReceiver
from nvflare.apis.dxo import from_shareable, DataKind

try:
    from sm import ParticipationSecretsManager
except Exception:
    ParticipationSecretsManager = None


FUNCTION_SUBMIT_JOBSTATUS = "/nvflare/client/emit_progress"

API_BASE = os.getenv("DUALITY_BACKEND_URL")
LOCAL_BUILD = True
if not API_BASE:
    LOCAL_BUILD = False
    API_BASE = "https://api.example.org"
    SECRET_NAME = "example-database-secret"

LOG_PATH = os.getenv("DUALITY_NVFLARE_LOG_PATH", "./logs/duality_nvflare.log")

_PRINT_BROKEN = False


def _should_skip_backend_progress_http() -> bool:
    sim = os.getenv("FL_IS_SIMULATOR", "").strip().lower() in ("1", "true", "yes", "on")
    if not sim:
        return False
    if os.getenv("DUALITY_SIM_ENABLE_BACKEND_HTTP", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return True


def _log_line(msg: str):
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"[{ts}] [WebhookReceiver] {msg}"

    global _PRINT_BROKEN

    if not _PRINT_BROKEN:
        try:
            print(line, flush=True)
            return
        except Exception:
            _PRINT_BROKEN = True

    try:
        path = LOG_PATH or "/tmp/nvflare_webhook_receiver_fallback.log"
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _extract_analytics_dict(shareable: Shareable) -> dict | None:
    try:
        dxo = from_shareable(shareable)
    except Exception:
        return None
    if dxo is None or dxo.data_kind != DataKind.ANALYTIC:
        return None
    data = dxo.data if isinstance(dxo.data, dict) else {}
    scalars = data.get("scalars")
    if not isinstance(scalars, dict):
        scalars = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    return {
        "tag": data.get("tag"),
        "global_step": data.get("global_step"),
        "scalars": scalars,
        "function": data.get("function"),
    }


class BackendWebhookReceiver(AnalyticsReceiver):
    def __init__(self, events=None, writer_id=None):
        super().__init__(events=events or ["fed.analytix_log_stats"])
        self.writer_id = writer_id

        self.api_base = API_BASE.rstrip("/")
        self.endpoint_path = FUNCTION_SUBMIT_JOBSTATUS
        self.local_build = LOCAL_BUILD
        self.secret_name = None if self.local_build else SECRET_NAME

        self.q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

        mode = "LOCAL" if self.local_build else "CLOUD"
        self._skip_http = _should_skip_backend_progress_http()
        if self._skip_http:
            _log_line(
                f"init: simulator mode — backend webhook HTTP disabled "
                f"(set DUALITY_SIM_ENABLE_BACKEND_HTTP=1 to POST to {self.api_base})"
            )
        else:
            _log_line(f"init: mode={mode} api_base={self.api_base} endpoint={self.endpoint_path} queue_max={self.q.maxsize}")

    def initialize(self, fl_ctx: FLContext):
        _log_line("initialize called")
        return

    def save(self, fl_ctx: FLContext, shareable: Shareable, record_origin):
        if self._skip_http:
            return
        _log_line("save: received fed.job_progress")
        try:
            job_id = fl_ctx.get_job_id()
            site_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME) or ""

            data = _extract_analytics_dict(shareable)
            if not data:
                _log_line("save: warning: non-ANALYTIC or unparsable shareable; dropping")
                return

            scalars = (data or {}).get("scalars", {}) or {}

            phase_val = scalars.get("phase")
            if phase_val is None:
                phase_val = scalars.get("phase_id")

            _log_line(
                "save: from={site} origin={origin} job={job} tag={tag} step={step} "
                "phase={phase} round={round}".format(
                    site=site_name,
                    origin=record_origin,
                    job=job_id,
                    tag=(data or {}).get("tag"),
                    step=(data or {}).get("global_step"),
                    phase=phase_val,
                    round=scalars.get("round"),
                )
            )

            payload = {
                "job_id": job_id,
                "site": site_name,
                "origin": str(record_origin),
                "timestamp": time.time(),
                "data": data,
            }

            self.q.put_nowait(payload)

        except queue.Full:
            _log_line("save: queue full, dropping event")
        except Exception:
            _log_line("save: exception while enqueuing event:\n" + traceback.format_exc())

    def finalize(self, fl_ctx: FLContext):
        _log_line("finalize called")
        try:
            self.q.put_nowait(None)
        except Exception:
            pass

    def _worker_loop(self):
        session = requests.Session()

        while True:
            item = self.q.get()
            if item is None:
                break

            try:
                url = f"{self.api_base}{self.endpoint_path}"

                data = (item.get("data") or {})
                scalars = data.get("scalars", {}) or {}

                phase_val = scalars.get("phase")
                if phase_val is None:
                    phase_val = scalars.get("phase_id")

                out = {
                    "job_id": item.get("job_id"),
                    "client_name": item.get("site"),
                    "phase": phase_val,
                    "round": scalars.get("round"),
                    "origin": item.get("origin"),
                    "timestamp": item.get("timestamp"),
                    "tag": data.get("tag"),
                    "step": data.get("global_step"),
                    "scalars": scalars,
                }

                function_name = data.get("function")
                if function_name:
                    out["function"] = function_name

                if not self.local_build:
                    if ParticipationSecretsManager is None:
                        _log_line("worker: ParticipationSecretsManager not available in CLOUD mode")
                    else:
                        try:
                            pw = ParticipationSecretsManager.get_mysql_password(self.secret_name)  # type: ignore[arg-type]
                            out["$pw"] = pw
                        except Exception:
                            _log_line("worker: failed to fetch secret:\n" + traceback.format_exc())

                _log_line(
                    "worker: POST {url} phase={phase} round={round} client={client}".format(
                        url=url, phase=out.get("phase"), round=out.get("round"), client=out.get("client_name")
                    )
                )

                resp = session.post(url, json=out, timeout=10)
                if not resp.ok:
                    body = resp.text.strip()[:500]
                    _log_line(f"worker: HTTP {resp.status_code} body={body}")
                else:
                    _log_line(f"worker: OK {resp.status_code}")
                resp.raise_for_status()

            except requests.RequestException as rexc:
                status = getattr(rexc.response, "status_code", None)
                body = getattr(rexc.response, "text", "").strip() if getattr(rexc, "response", None) else ""
                _log_line(f"worker: REQUEST ERROR status={status} err={rexc} body={body}")
            except Exception:
                _log_line("worker: EXCEPTION\n" + traceback.format_exc())
            finally:
                self.q.task_done()

        try:
            session.close()
        except Exception:
            pass
        _log_line("worker: exiting")
