import os
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from nvflare.apis.event_type import EventType
from nvflare.apis.fl_component import FLComponent
from nvflare.apis.fl_constant import ReservedKey, ReturnCode
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable

try:
    from sm import ParticipationSecretsManager
except Exception:
    ParticipationSecretsManager = None


DATASOURCE_LOOKUP_TOPIC = "duality.datasource.lookup"
DATASOURCE_ENDPOINT_PATH = "/clients/datasource/source"

API_BASE = os.getenv("DUALITY_BACKEND_URL")
LOCAL_BUILD = True
if not API_BASE:
    LOCAL_BUILD = False
    API_BASE = "https://api.example.org"
    SECRET_NAME = "example-database-secret"

LOG_PATH = os.getenv("DUALITY_NVFLARE_LOG_PATH", "./logs/duality_datasource_receiver.log")

_PRINT_BROKEN = False


def _log_line(msg: str):
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"[{ts}] [DatasourceRequestReceiver] {msg}"

    global _PRINT_BROKEN

    if not _PRINT_BROKEN:
        try:
            print(line, flush=True)
            return
        except Exception:
            _PRINT_BROKEN = True

    try:
        path = LOG_PATH or "/tmp/duality_datasource_receiver.log"
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _coerce_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


class DatasourceRequestReceiver(FLComponent):
    def __init__(self, topic: str = DATASOURCE_LOOKUP_TOPIC, timeout: int = 15):
        super().__init__()
        self.topic = topic
        self.timeout = timeout
        self.api_base = API_BASE.rstrip("/")
        self.endpoint_path = DATASOURCE_ENDPOINT_PATH
        self.local_build = LOCAL_BUILD
        self.secret_name = None if self.local_build else SECRET_NAME
        self.session = requests.Session()
        self._registered = False

        mode = "LOCAL" if self.local_build else "CLOUD"
        _log_line(f"init: mode={mode} api_base={self.api_base} endpoint={self.endpoint_path} topic={self.topic}")

    def initialize(self, fl_ctx: FLContext):
        self._register(fl_ctx)

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        if event_type == EventType.START_RUN:
            self._register(fl_ctx)
        elif event_type == EventType.END_RUN:
            try:
                self.session.close()
            except Exception:
                pass

    def _register(self, fl_ctx: FLContext):
        if self._registered:
            return
        engine = fl_ctx.get_engine()
        if engine is None:
            _log_line("register skipped: no engine in FLContext")
            return
        engine.register_aux_message_handler(self.topic, self.handle_datasource_lookup)
        self._registered = True
        _log_line(f"registered aux handler topic={self.topic}")

    def _reply(self, status: str, payload: Optional[Dict[str, Any]] = None, rc: str = ReturnCode.OK) -> Shareable:
        response = Shareable(payload or {})
        response["status"] = status
        response.set_return_code(rc)
        return response

    def _resolve_client_name(self, request: Shareable) -> Optional[str]:
        peer_props = request.get_peer_props() or {}
        for key in (ReservedKey.CLIENT_NAME, ReservedKey.IDENTITY_NAME, "site_name", "client_name"):
            value = peer_props.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        value = request.get("client_name")
        if isinstance(value, str) and value.strip():
            return value.strip()

        value = request.get("site")
        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    def _secret_payload(self) -> Dict[str, Any]:
        if self.local_build:
            return {}
        if ParticipationSecretsManager is None:
            raise RuntimeError("ParticipationSecretsManager not available")
        pw = ParticipationSecretsManager.get_mysql_password(self.secret_name)  # type: ignore[arg-type]
        return {"$pw": pw}

    def handle_datasource_lookup(self, topic: str, request: Shareable, fl_ctx: FLContext) -> Shareable:
        try:
            client_name = self._resolve_client_name(request)
            project_id = _coerce_int_or_none(request.get("project_id"))
            datasource_group_id = _coerce_int_or_none(
                request.get("datasource_group_id", request.get("datasource_group"))
            )

            if not client_name:
                return self._reply(
                    "FAILURE",
                    {"error": "client_name could not be resolved from NVFlare peer context"},
                    ReturnCode.BAD_REQUEST_DATA,
                )

            if project_id is None:
                return self._reply(
                    "FAILURE",
                    {"client_name": client_name, "error": "project_id is required"},
                    ReturnCode.BAD_REQUEST_DATA,
                )

            payload = {
                "client_name": client_name,
                "project_id": project_id,
                "datasource_group_id": datasource_group_id,
            }
            payload.update(self._secret_payload())

            url = f"{self.api_base}{self.endpoint_path}"
            _log_line(
                "POST {url} client_name={client_name} project_id={project_id} datasource_group_id={group_id}".format(
                    url=url,
                    client_name=client_name,
                    project_id=project_id,
                    group_id=datasource_group_id,
                )
            )

            resp = self.session.post(url, json=payload, timeout=self.timeout)
            body_text = resp.text.strip()[:1000]
            if not resp.ok:
                _log_line(f"HTTP {resp.status_code} body={body_text}")
                return self._reply(
                    "FAILURE",
                    {
                        "client_name": client_name,
                        "project_id": project_id,
                        "datasource_group_id": datasource_group_id,
                        "error": f"Backend datasource lookup failed with HTTP {resp.status_code}",
                        "body": body_text,
                    },
                    ReturnCode.EXECUTION_EXCEPTION,
                )

            data = resp.json()
            source = data.get("source")
            if not isinstance(source, str) or not source.strip():
                return self._reply(
                    "FAILURE",
                    {
                        "client_name": client_name,
                        "project_id": project_id,
                        "datasource_group_id": datasource_group_id,
                        "error": "Backend datasource lookup did not return source",
                        "body": body_text,
                    },
                    ReturnCode.EXECUTION_EXCEPTION,
                )

            response_payload = {
                "client_name": client_name,
                "project_id": project_id,
                "datasource_group_id": data.get("datasource_group_id", datasource_group_id),
                "datasource_group_name": data.get("datasource_group_name"),
                "source": source.strip(),
                "source_type": data.get("source_type"),
                "datasource_record_id": data.get("datasource_record_id"),
            }
            _log_line(
                "resolved client_name={client_name} project_id={project_id} datasource_group_id={group_id} source={source}".format(
                    client_name=client_name,
                    project_id=project_id,
                    group_id=response_payload.get("datasource_group_id"),
                    source=response_payload.get("source"),
                )
            )
            return self._reply("SUCCESS", response_payload, ReturnCode.OK)

        except Exception as exc:
            _log_line("EXCEPTION\n" + traceback.format_exc())
            return self._reply(
                "FAILURE",
                {"error": str(exc), "traceback": traceback.format_exc()},
                ReturnCode.EXECUTION_EXCEPTION,
            )
