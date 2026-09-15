import os
from datetime import datetime
import time

import requests
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey

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
    line = f"[{ts}] [WebhookWriter] {msg}"

    global _PRINT_BROKEN

    if not _PRINT_BROKEN:
        try:
            print(line, flush=True)
            return
        except Exception:
            _PRINT_BROKEN = True

    try:
        path = LOG_PATH or "/tmp/webhook_writer_fallback.log"
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class BackendWebhookWriter:
    def __init__(self):
        self.api_base = API_BASE.rstrip("/")
        self.endpoint_path = FUNCTION_SUBMIT_JOBSTATUS
        self.local_build = LOCAL_BUILD
        self.secret_name = None if self.local_build else SECRET_NAME
        self.session = requests.Session()

        if _should_skip_backend_progress_http():
            _log_line(
                "init: simulator mode — BackendWebhookWriter HTTP disabled "
                "(set DUALITY_SIM_ENABLE_BACKEND_HTTP=1 to enable)"
            )
        else:
            mode = "LOCAL" if self.local_build else "CLOUD"
            _log_line(f"init: mode={mode} api_base={self.api_base} endpoint={self.endpoint_path}")

    def write(self, data: dict, fl_ctx: FLContext):
        if _should_skip_backend_progress_http():
            return
        try:
            url = f"{self.api_base}{self.endpoint_path}"

            job_id = fl_ctx.get_job_id()
            site_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME) or ""
            scalars = (data or {}).get("scalars", {}) or {}

            out = {
                "job_id": job_id,
                "client_name": site_name,
                "phase": scalars.get("phase"),
                "round": scalars.get("round"),
                "origin": site_name,
                "timestamp": time.time(),
                "tag": data.get("tag"),
                "step": data.get("global_step"),
                "scalars": scalars,
            }

            function_name = data.get("function")
            if function_name:
                out["function"] = function_name

            if not self.local_build and ParticipationSecretsManager is not None:
                try:
                    pw = ParticipationSecretsManager.get_mysql_password(self.secret_name)  # type: ignore[arg-type]
                    out["$pw"] = pw
                except Exception as e:
                    _log_line(f"secret fetch failed: {e}")

            _log_line(
                "POST {url} phase={phase} round={round} client={client}".format(
                    url=url, phase=out.get("phase"), round=out.get("round"), client=out.get("client_name")
                )
            )
            resp = self.session.post(url, json=out, timeout=10)

            if not resp.ok:
                body = resp.text.strip()[:500]
                _log_line(f"HTTP {resp.status_code} body={body}")
            else:
                _log_line(f"OK {resp.status_code}")
            resp.raise_for_status()
        except requests.RequestException as e:
            status = getattr(e.response, "status_code", None)
            body = getattr(e.response, "text", "").strip() if getattr(e, "response", None) else ""
            _log_line(f"REQUEST ERROR status={status} err={e} body={body}")
        except Exception as e:
            _log_line(f"EXCEPTION: {e}")
