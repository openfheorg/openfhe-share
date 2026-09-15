"""
Routes for listing NVFlare client connection status and optional participation status.
"""

import traceback
from typing import Dict, List, Optional
import logging
from fastapi import HTTPException, Request, APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.aws.ResourceConfigProvider import ResourceConfigProvider
from app.core.mysql.managers.FiltersManager import FiltersManager
from app.core.mysql.managers.FunctionsManager import FunctionsManager, _normalize_functions_map
from app.core.mysql.managers.ParticipationManager import Confirmation, ParticipationManager
from app.core.mysql.managers.ThresholdManager import Threshold, ThresholdMethod
from app.core.mysql.managers.UsersManager import UsersManager
from app.core.nvflare.NVFlareClientSnapshot import NVFlareClientSnapshot

router = APIRouter()

def _validate_internal_backend_secret(body: dict) -> None:
    env = EnvironmentProvider.get_env()
    if env == Environment.LOCAL:
        return

    pw = body.get("$pw", "") if isinstance(body, dict) else ""
    mysql_config = ResourceConfigProvider.get_mysql_config()
    password_string = mysql_config.password
    if pw != password_string:
        mysql_config = ResourceConfigProvider.get_mysql_config(check_cached=False)
        if pw != mysql_config.password:
            print(f"ClientRoutes: internal request received a bad password: {pw}", flush=True)
            raise HTTPException(status_code=401, detail="Unauthorized")


def _parse_optional_int(value, field_name: str):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer when provided")


def _body_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return default



def _normalize_client_name_set(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item).strip()
        for item in value
        if str(item).strip()
    }

def _participation_row_matches_selected_roles(
    row,
    non_contributing_clients: set[str],
    exclude_analyzing_clients: set[str],
) -> bool:
    name = str(row.get("client_name") or "").strip()
    if not name:
        return False

    expected_contributing = name not in non_contributing_clients
    expected_analyzing = name not in exclude_analyzing_clients
    actual_contributing = True if row.get("contributing_party") is None else bool(row.get("contributing_party"))
    actual_analyzing = True if row.get("analyzing_party") is None else bool(row.get("analyzing_party"))

    return (
        actual_contributing == expected_contributing
        and actual_analyzing == expected_analyzing
    )

def _canonicalize_functions_map(functions_map: Dict[str, List[Dict[str, str]]]) -> Dict[str, Dict[str, str]]:
    """
    Convert a functions map of the form:
        { "FN": [ {prop: val, ...}, {prop: val, ...}, ... ], ... }
    into:
        { "FN": {prop: val, ...}, ... }

    All (prop, value) pairs from every config object for a function are merged.
    This means participation is considered accepted only if, for each function,
    the stored participation config set includes every (prop, value) pair that
    appears in any of the provided configs for that function.
    """
    canonical: Dict[str, Dict[str, str]] = {}
    for fn_name, cfg_list in (functions_map or {}).items():
        name = str(fn_name).strip().upper()
        if not name:
            continue
        merged: Dict[str, str] = {}
        if isinstance(cfg_list, list):
            for cfg in cfg_list:
                if not isinstance(cfg, dict):
                    continue
                for k, v in cfg.items():
                    key = str(k).strip()
                    if not key:
                        continue
                    merged[key] = "" if v is None else str(v)
        if merged:
            canonical[name] = merged
    return canonical


# Put behind bearer token
class ClientConnectionStatusRequest(BaseModel):
    # Optional username used to mark any matching client rows as belonging
    # to the submitted user via is_submitted_user.
    username: Optional[str] = None


# Put behind bearer token
@router.post("/clients/connection/status", include_in_schema=False)
async def list_clients_connection_status(payload: Optional[ClientConnectionStatusRequest] = None):
    try:
        print(f"ClientRoutes: raw payload={payload}", flush=True)
        username = payload.username.strip() if payload and payload.username else None
        print(f"ClientRoutes: resolved username={username}", flush=True)

        # Always get current connection snapshot
        clients_snapshot = NVFlareClientSnapshot().get_clients(username=username)
        print(f"ClientRoutes: Snapshot clients returned: {clients_snapshot}", flush=True)
        return JSONResponse({"clients": clients_snapshot})

    except Exception:
        print("ClientRoutes: exception in /clients/connection/status", flush=True)
        print(traceback.format_exc(), flush=True)
        return JSONResponse(
            content={"error": f"Failed to fetch client status: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )

# Put behind bearer token
@router.post("/clients/datasource/source", include_in_schema=False)
async def get_client_datasource_source(request: Request):
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if not isinstance(body, dict):
            return JSONResponse(
                content={"status": "FAILURE", "error": "Request body must be a JSON object"},
                status_code=400,
            )

        print(f"ClientRoutes: /clients/datasource/source called with body={body}", flush=True)
        _validate_internal_backend_secret(body)

        client_name = str(body.get("client_name") or body.get("site") or "").strip()
        if not client_name:
            return JSONResponse(
                content={"status": "FAILURE", "error": "client_name is required"},
                status_code=400,
            )

        try:
            project_id = int(body.get("project_id"))
        except (TypeError, ValueError):
            return JSONResponse(
                content={"status": "FAILURE", "error": "project_id is required and must be an integer"},
                status_code=400,
            )

        raw_datasource_group = body.get("datasource_group_id")
        if raw_datasource_group is None:
            raw_datasource_group = body.get("datasource_group")

        try:
            datasource_group_id = _parse_optional_int(raw_datasource_group, "datasource_group_id")
        except ValueError as e:
            return JSONResponse(
                content={"status": "FAILURE", "error": str(e)},
                status_code=400,
            )

        users_manager = UsersManager()
        try:
            client_user = users_manager.get_user_by_client_name(client_name)
            if not client_user:
                return JSONResponse(
                    content={
                        "status": "FAILURE",
                        "error": f"No user is associated with client_name [{client_name}]",
                    },
                    status_code=404,
                )

            source_record = users_manager.get_fhir_source_record(
                user_id=client_user["user_id"],
                project_id=project_id,
                datasource_group=datasource_group_id,
            )

            if not source_record:
                return JSONResponse(
                    content={
                        "status": "FAILURE",
                        "error": (
                            f"No datasource found for client_name [{client_name}], "
                            f"project_id [{project_id}], datasource_group [{datasource_group_id}]"
                        ),
                    },
                    status_code=404,
                )

            source = source_record["source"]
            print(
                f"ClientRoutes: resolved datasource for client_name={client_name}, project_id={project_id}, datasource_group_id={datasource_group_id}",
                flush=True,
            )
            return JSONResponse(
                content={
                    "status": "SUCCESS",
                    "requested_client_name": client_name,
                    "client_name": client_user["client_name"],
                    "username": client_user["username"],
                    "user_id": client_user["user_id"],
                    "project_id": project_id,
                    "source": source,
                    "source_type": "json" if str(source).lower().endswith(".json") else "fhir_server",
                    "datasource_group": source_record["datasource_group"],
                    "datasource_group_id": source_record["datasource_group"],
                    "datasource_group_name": source_record["datasource_group_name"],
                    "is_default_group": source_record["is_default_group"],
                    "datasource_record_id": source_record.get("id"),
                    "create_date": source_record.get("create_date"),
                },
                status_code=200,
            )
        finally:
            users_manager.complete()

    except HTTPException:
        raise
    except Exception:
        print("ClientRoutes: exception in /clients/datasource/source", flush=True)
        print(traceback.format_exc(), flush=True)
        return JSONResponse(
            content={"status": "FAILURE", "error": f"Failed to fetch datasource: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )


# Put behind bearer token
@router.post("/clients/participation/status", include_in_schema=False)
async def list_clients_status(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        username = None
        raw_username = body.get("username")
        if isinstance(raw_username, str) and raw_username.strip():
            username = raw_username.strip()

        include_connection_state = _body_bool(body.get("include_connection_state"), True)

        clients_snapshot = []
        if include_connection_state:
            clients_snapshot = NVFlareClientSnapshot().get_clients(username=username)
            print(f"ClientRoutes: resolved username={username}", flush=True)
            print(f"ClientRoutes: Snapshot clients returned: {clients_snapshot}", flush=True)
        else:
            print(
                f"ClientRoutes: resolved username={username}; skipping connection snapshot for participation-only lookup",
                flush=True,
            )

        participation_status = body.get("participation_status")
        if not isinstance(participation_status, dict):
            return JSONResponse({"clients": clients_snapshot})

        filters = participation_status.get("filters")
        funcs_raw = participation_status.get("functions")
        non_contributing_clients = _normalize_client_name_set(
            participation_status.get("non_contributing_clients")
        )
        exclude_analyzing_clients = _normalize_client_name_set(
            participation_status.get("exclude_analyzing_clients")
        )
        raw_project_id = participation_status.get("project_id")
        try:
            project_id = int(raw_project_id) if raw_project_id is not None else None
        except (TypeError, ValueError):
            project_id = None

        if project_id is None:
            return JSONResponse(
                content={"status": "FAILURE", "error": "project_id is required"},
                status_code=400,
            )

        # Optional threshold_config
        threshold_obj = None
        threshold_cfg = participation_status.get("threshold_config") if isinstance(participation_status, dict) else None
        if isinstance(threshold_cfg, dict):
            method_raw = threshold_cfg.get("method")
            threshold_raw = threshold_cfg.get("threshold")

            method_enum = None
            if isinstance(method_raw, str):
                try:
                    method_enum = ThresholdMethod(method_raw)
                except ValueError:
                    method_enum = None

            try:
                threshold_val = int(threshold_raw) if threshold_raw is not None else None
            except (TypeError, ValueError):
                threshold_val = None

            if method_enum is not None and threshold_val is not None:
                threshold_obj = Threshold(id=None, method=method_enum, threshold=threshold_val)

        if not isinstance(funcs_raw, dict) or len(funcs_raw) == 0:
            print(
                "ClientRoutes: participation_status.functions missing/invalid; returning current client payload.",
                flush=True,
            )
            return JSONResponse({"clients": clients_snapshot})

        normalized_functions: Dict[str, List[Dict[str, str]]] = {}
        for k, v in funcs_raw.items():
            fn_id = str(k).strip().upper()
            if not fn_id:
                continue

            if not isinstance(v, list) or len(v) == 0:
                print(
                    f"ClientRoutes: participation_status.functions[{fn_id}] is not a non-empty list; skipping.",
                    flush=True,
                )
                continue

            configs_for_fn: List[Dict[str, str]] = []
            for cfg in v:
                if not isinstance(cfg, dict):
                    print(
                        f"ClientRoutes: participation_status.functions[{fn_id}] entry is not an object; skipping that entry.",
                        flush=True,
                    )
                    continue
                arg_map: Dict[str, str] = {}
                for ak, av in cfg.items():
                    key = str(ak).strip()
                    if not key:
                        continue
                    arg_map[key] = "" if av is None else str(av)
                if arg_map:
                    configs_for_fn.append(arg_map)

            if configs_for_fn:
                normalized_functions[fn_id] = configs_for_fn

        if not normalized_functions:
            print(
                "ClientRoutes: participation_status.functions empty after sanitize; returning current client payload.",
                flush=True,
            )
            return JSONResponse({"clients": clients_snapshot})

        canonical_functions_map = _canonicalize_functions_map(normalized_functions)
        print(
            f"ClientRoutes: canonical_functions_map for participation matching: {canonical_functions_map}",
            flush=True,
        )

        filters_manager = FiltersManager(project_id=project_id, filters=filters)
        filter_id = filters_manager.get_id_by_filters()
        print(f"ClientRoutes: Resolved filter_id={filter_id}", flush=True)

        if filter_id and canonical_functions_map:
            db = ParticipationManager()
            try:
                kwargs = {
                    "functions": canonical_functions_map,
                    "filter_id": filter_id,
                    "clients_snapshot": clients_snapshot if include_connection_state else None,
                }
                if threshold_obj is not None:
                    kwargs["threshold"] = threshold_obj

                participation_rows = db.list_client_participation_status(**kwargs)
                print(
                    f"ClientRoutes: Participation rows fetched from DB: {participation_rows}",
                    flush=True,
                )

                participation_map = {}
                for row in participation_rows:
                    if not _participation_row_matches_selected_roles(
                        row,
                        non_contributing_clients,
                        exclude_analyzing_clients,
                    ):
                        continue

                    name = row.get("client_name")
                    if name:
                        contributing_party_raw = row.get("contributing_party")
                        analyzing_party_raw = row.get("analyzing_party")
                        participation_map[name.strip()] = {
                            "confirmation": row.get("confirmation"),
                            "contributing_party": True if contributing_party_raw is None else bool(contributing_party_raw),
                            "analyzing_party": True if analyzing_party_raw is None else bool(analyzing_party_raw),
                        }

                print(
                    f"ClientRoutes: Participation map built: {participation_map}",
                    flush=True,
                )

                if include_connection_state:
                    for c in clients_snapshot:
                        name = c.get("client_name", "").strip()
                        participation = participation_map.get(name)
                        if participation:
                            c["participation"] = participation.get("confirmation")
                            c["contributing_party"] = participation.get("contributing_party")
                            c["analyzing_party"] = participation.get("analyzing_party")
                        else:
                            c["participation"] = None
                            c["contributing_party"] = True
                            c["analyzing_party"] = True
                        print(f"ClientRoutes: Updated client entry: {c}", flush=True)
                else:
                    clients_snapshot = [
                        {
                            "client_name": name,
                            "participation": participation.get("confirmation"),
                            "contributing_party": participation.get("contributing_party"),
                            "analyzing_party": participation.get("analyzing_party"),
                        }
                        for name, participation in sorted(participation_map.items())
                    ]
            finally:
                db.complete()
                print("ClientRoutes: ParticipationManager connection closed.", flush=True)

        print(f"ClientRoutes: Final clients list returned: {clients_snapshot}", flush=True)
        return JSONResponse({"clients": clients_snapshot})

    except Exception:
        return JSONResponse(
            content={"error": f"Failed to fetch client status: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )

# Put behind bearer token
@router.post("/clients/participation/submit", include_in_schema=False)
async def submit_participation(request: Request):
    print(f"ClientRoutes: submit_participation request recieved: {request}", flush=True)

    body = await request.json()

    env = EnvironmentProvider.get_env()
    if env != Environment.LOCAL:
        pw = body.get("$pw", "")
        mysql_config = ResourceConfigProvider.get_mysql_config()
        password_string = mysql_config.password
        if pw != password_string:
            mysql_config = ResourceConfigProvider.get_mysql_config(check_cached=False)
            if pw != mysql_config.password:
                print(f"ClientRoutes: submit_participation request recieved a bad password: {pw}", flush=True)
                raise HTTPException(status_code=401, detail="Unauthorized")

    required_fields = ["client_name", "functions_map", "filter_id", "confirmation"]
    for field in required_fields:
        if body.get(field) in (None, "", []):
            print(f"ClientRoutes: submit_participation recieved missing request data: {field}", flush=True)
            return JSONResponse(content={"status": f"Please provide {field}"}, status_code=400)

    funcs_raw = body.get("functions_map")
    if not isinstance(funcs_raw, dict):
        return JSONResponse(
            content={"status": "functions must be an object mapping function_id -> { args }"},
            status_code=400,
        )

    try:
        functions_map = _normalize_functions_map(funcs_raw)
    except Exception:
        logging.exception("Failed to normalize functions map (participation)")
        return JSONResponse(content={"status": "Invalid functions payload"}, status_code=400)

    if not any(str(fid).strip() for fid in functions_map.keys()):
        return JSONResponse(
            content={"status": "functions must contain at least one function"},
            status_code=400,
        )

    conf_raw = str(body["confirmation"]).upper()
    if conf_raw not in Confirmation.__members__.keys():
        print(
            f"ClientRoutes: submit_participation recieved abnormal confirmation string: {conf_raw}",
            flush=True,
        )
        return JSONResponse(
            content={"status": "Confirmation must be ACCEPT or REJECT"},
            status_code=400,
        )
    conf_enum = Confirmation[conf_raw]

    threshold_obj: Threshold | None = None
    raw_threshold = body.get("threshold_config")
    if isinstance(raw_threshold, dict):
        method_raw = raw_threshold.get("method")
        threshold_val = raw_threshold.get("threshold")
        threshold_id = raw_threshold.get("id")
        if method_raw is not None and threshold_val is not None:
            try:
                threshold_obj = Threshold(
                    method=str(method_raw).strip().upper(),
                    threshold=int(threshold_val),
                    id=int(threshold_id) if threshold_id is not None else None,
                )
            except Exception:
                return JSONResponse(
                    content={"status": "Invalid threshold_config payload"},
                    status_code=400,
                )

    participation_manager = ParticipationManager()
    try:
        recorded_id = participation_manager.record_participation(
            body["client_name"],
            int(body["filter_id"]),
            functions_map,
            conf_enum,
            threshold=threshold_obj,
        )

        if recorded_id is None:
            print("ClientRoutes: Failed to persist confirmation.", flush=True)
            return JSONResponse(
                content={"status": "Failed to persist confirmation."},
                status_code=500,
            )

        print(
            f"ClientRoutes: Participation successfully recorded with id {recorded_id}.",
            flush=True,
        )
        return JSONResponse(
            content={"status": "Participation recorded", "id": recorded_id},
            status_code=200,
        )

    except Exception:
        print(
            f"ClientRoutes: submit_participation hit exception {traceback.format_exc().splitlines()}.",
            flush=True,
        )
        return JSONResponse(
            content={
                "status": "Exception occurred while recording participation",
                "log": traceback.format_exc().splitlines(),
            },
            status_code=400,
        )
    finally:
        participation_manager.complete()
