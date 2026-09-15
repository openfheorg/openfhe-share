from nvflare.app_common.abstract.aggregator import Aggregator
from nvflare.apis.dxo import from_shareable, DXO, DataKind
from nvflare.apis.shareable import Shareable

import requests
import os
import json
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple, List

from sm import ParticipationSecretsManager

FUNCTION_SUBMIT_PARTICIPATION = "/clients/participation/submit"

API_BASE = os.getenv("DUALITY_BACKEND_URL")

local_build = True
if not API_BASE:
    local_build = False
    API_BASE = "https://api.example.org"
    SECRET_NAME = "example-database-secret"

LOG_PATH = os.getenv("DUALITY_NVFLARE_LOG_PATH", "./logs/duality_nvflare.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

DEFAULT_FILTERS_REL_PATH = os.getenv("FILTERS_PATH", "custom/filters.json")


def _log_line(msg: str):
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"[{ts}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


class CustomResponseAggregator(Aggregator):
    def __init__(self, output_dir="output"):
        super().__init__()
        self.output_dir = output_dir
        self.responses: Dict[str, Dict[str, Any]] = {}
        self._cached_functions_map: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._cached_threshold_config: Optional[Dict[str, Any]] = None
        self._filters_rel_path = DEFAULT_FILTERS_REL_PATH
        mode = "LOCAL" if local_build else "CLOUD"
        _log_line(f"Aggregator init: mode={mode} API_BASE={API_BASE} LOG_PATH={LOG_PATH}")

    def _resolve_filters_path(self, fl_ctx) -> Tuple[Optional[Path], Iterable[Path]]:
        rel = Path(self._filters_rel_path)
        if rel.is_absolute() and rel.exists():
            return rel, []

        app_root = fl_ctx.get_prop("app_root", None)
        job_id = fl_ctx.get_prop("job_id", None)

        bases: list[Path] = []
        if app_root:
            bases.append(Path(app_root))
        if job_id:
            bases.append(Path.cwd() / str(job_id) / "app_server")
        bases.append(Path.cwd())

        module_dir = Path(__file__).resolve().parent
        bases.append(module_dir)
        bases.append(module_dir.parent)

        for b in bases:
            p = (b / rel).resolve()
            if p.exists():
                return p, bases
        return None, bases

    def _load_functions_map_from_filters(self, fl_ctx) -> Optional[Dict[str, List[Dict[str, str]]]]:
        if self._cached_functions_map is not None:
            return self._cached_functions_map

        path, searched = self._resolve_filters_path(fl_ctx)
        if not path or not path.exists():
            _log_line(f"filters.json not found; searched={ [str(b) for b in searched] }")
            return None

        try:
            txt = Path(path).read_text(encoding="utf-8", errors="ignore")
            data = json.loads(txt)
            fm = data.get("functions_map")
            if isinstance(fm, dict):
                out: Dict[str, List[Dict[str, str]]] = {}
                for k, v in fm.items():
                    name = str(k).strip().upper()
                    if not name:
                        continue

                    cfgs: List[Dict[str, str]] = []
                    if isinstance(v, list):
                        raw_list = v
                    elif isinstance(v, dict):
                        raw_list = [v]
                    else:
                        raw_list = []

                    for cfg in raw_list:
                        if not isinstance(cfg, dict):
                            continue
                        arg_map: Dict[str, str] = {}
                        for pk, pv in cfg.items():
                            pk_str = str(pk).strip()
                            if not pk_str:
                                continue
                            arg_map[pk_str] = "" if pv is None else str(pv)
                        if arg_map:
                            cfgs.append(arg_map)

                    if cfgs:
                        out[name] = cfgs

                self._cached_functions_map = out
                _log_line(f"Loaded functions_map from {path}: keys={sorted(out.keys())}")
                return out
            else:
                _log_line(f"filters.json has no 'functions_map' object at {path}")
        except Exception:
            _log_line("Failed parsing filters.json:\n" + traceback.format_exc())

        return None

    def _load_threshold_config_from_filters(self, fl_ctx) -> Optional[Dict[str, Any]]:
        if self._cached_threshold_config is not None:
            return self._cached_threshold_config

        path, searched = self._resolve_filters_path(fl_ctx)
        if not path or not path.exists():
            _log_line(f"filters.json not found for threshold_config; searched={ [str(b) for b in searched] }")
            return None

        try:
            txt = Path(path).read_text(encoding="utf-8", errors="ignore")
            data = json.loads(txt)
        except Exception:
            _log_line("Failed parsing filters.json for threshold_config:\n" + traceback.format_exc())
            return None

        tc = data.get("threshold_config")
        if not isinstance(tc, dict):
            _log_line(f"filters.json has no 'threshold_config' object at {path}")
            return None

        out: Dict[str, Any] = {}

        if "id" in tc and tc["id"] is not None:
            out["id"] = tc["id"]

        method = tc.get("method")
        if method is not None:
            out["method"] = str(method).strip().upper()

        threshold_val = tc.get("threshold")
        if threshold_val is not None:
            try:
                out["threshold"] = int(threshold_val)
            except Exception:
                out["threshold"] = threshold_val

        if not out:
            return None

        self._cached_threshold_config = out
        _log_line(f"Loaded threshold_config from {path}: {out}")
        return out

    def reset(self, fl_ctx):
        self.responses = {}
        self._cached_functions_map = None
        self._cached_threshold_config = None
        _log_line("Aggregator reset: cleared pending responses")

    def accept(self, shareable: Shareable, fl_ctx) -> bool:
        confirmation = None
        filter_id = None
        try:
            dxo = from_shareable(shareable)
            meta = getattr(dxo, "meta", {}) or {}
            confirmation = meta.get("confirmation")
            filter_id = meta.get("filter_id")
        except Exception:
            _log_line("accept: failed to parse DXO/meta:\n" + traceback.format_exc())

        peer_props = shareable.get_peer_props() or {}
        site = (
            peer_props.get("__identity_name__")
            or peer_props.get("__client_name__")
            or peer_props.get("__fqsn__")
            or "unknown"
        )

        self.responses[site] = {
            "filter_id": filter_id,
            "confirmation": (str(confirmation).upper() if confirmation is not None else None),
        }

        msg = f"accept: site={site} filter_id={filter_id} confirmation={confirmation}"
        _log_line(msg)
        try:
            self.log_info(fl_ctx, "[Aggregator] " + msg)
        except Exception:
            pass
        return True

    def submit_participation(
        self,
        client_name: str,
        functions_map: Dict[str, List[Dict[str, str]]],
        filter_id,
        confirmation,
        threshold_config=None,
    ):
        payload: Dict[str, Any] = {
            "client_name": client_name,
            "functions_map": functions_map,
            "filter_id": filter_id,
            "confirmation": confirmation,
        }

        if threshold_config is not None:
            payload["threshold_config"] = threshold_config

        if not local_build:
            pw = ParticipationSecretsManager.get_mysql_password(SECRET_NAME)
            payload["$pw"] = pw

        url = f"{API_BASE}{FUNCTION_SUBMIT_PARTICIPATION}"
        try:
            pretty = json.dumps(payload, ensure_ascii=False)
        except Exception:
            pretty = "<unserializable payload>"
        _log_line(f"submit_participation: POST {url} payload={pretty}")

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if not resp.ok:
                _log_line(f"submit_participation: HTTP {resp.status_code} body={resp.text.strip()}")
            resp.raise_for_status()
            _log_line(f"submit_participation: SUCCESS site={client_name}")
            return resp.json()
        except requests.RequestException as rexc:
            status = getattr(rexc.response, "status_code", None)
            body = getattr(rexc.response, "text", "").strip() if getattr(rexc, "response", None) else ""
            _log_line(f"submit_participation: REQUEST ERROR status={status} err={rexc} body={body}")
            raise
        except Exception:
            _log_line("submit_participation: EXCEPTION\n" + traceback.format_exc())
            raise

    def aggregate(self, fl_ctx) -> Shareable:
        _log_line(f"aggregate: submitting {len(self.responses)} responses")

        functions_map = self._load_functions_map_from_filters(fl_ctx)
        threshold_config = self._load_threshold_config_from_filters(fl_ctx)

        if not functions_map:
            _log_line("aggregate: no functions_map available; skipping submissions")
        else:
            for site, vals in self.responses.items():
                try:
                    result = self.submit_participation(
                        client_name=site,
                        functions_map=functions_map,
                        filter_id=vals["filter_id"],
                        confirmation=vals["confirmation"],
                        threshold_config=threshold_config,
                    )
                    _log_line(f"aggregate: submitted for {site} -> {result}")
                except Exception as e:
                    _log_line(f"aggregate: FAILED for {site} -> {e}")

        dxo = DXO(data_kind=DataKind.WEIGHTS, data={})
        return dxo.to_shareable()
