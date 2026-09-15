"""
Routes for job status and results retrieval.
"""

import math
import traceback
from fastapi import Request, APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

import asyncio
import boto3
import botocore.exceptions
import json
import re
import time
import traceback
import uuid


from app.core.mysql.SupportedFunction import SupportedFunction
from app.core.mysql.job_tracking.JobStatusRetriever import JobStatusRetriever
from app.core.mysql.job_tracking.NVFlareJobsDataRetriever import NVFlareJobsDataRetriever
from app.core.job_runner.nvflare_jobs import taskflow_service
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.MySQLTable import MySQLTable

router = APIRouter()


def sanitize_json_values(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, dict):
        return {key: sanitize_json_values(val) for key, val in value.items()}

    if isinstance(value, list):
        return [sanitize_json_values(item) for item in value]

    if isinstance(value, tuple):
        return [sanitize_json_values(item) for item in value]

    return value


JOB_STATUS_WS_POLL_INTERVAL_SECONDS = 0.5
JOB_STATUS_WS_ACK_TIMEOUT_SECONDS = 5.0
JOB_STATUS_WS_HEARTBEAT_INTERVAL_SECONDS = 10.0
JOB_STATUS_WS_API_GATEWAY_WSS_URL = "wss://ws.example.org/prod"
JOB_STATUS_WS_CONNECT_READY_MAX_WAIT_SECONDS = 10.0
JOB_STATUS_WS_CONNECT_READY_POLL_SECONDS = 0.5

_ACTIVE_API_GATEWAY_CONNECTIONS: dict[str, dict] = {}
_ACTIVE_API_GATEWAY_CONNECTIONS_LOCK = asyncio.Lock()


def _derive_management_endpoint_from_websocket_url(websocket_url: str) -> str:
    value = (websocket_url or "").strip().rstrip("/")

    if value.startswith("wss://"):
        return "https://" + value[len("wss://"):]
    if value.startswith("ws://"):
        return "http://" + value[len("ws://"):]
    if value.startswith("https://") or value.startswith("http://"):
        return value

    return f"https://{value}"


def _build_job_status_response_body(job_id: str, status_obj: dict | None) -> dict:
    if not status_obj:
        return sanitize_json_values({
            "job_id": job_id,
            "status": "QUEUED",
            "log": [],
            "last_update": "None",
            "functions": []
        })

    response_body = {
        "job_id": job_id,
        "status": status_obj.get("status"),
        "log": str(status_obj["log"]).splitlines() if status_obj.get("log") else [],
        "last_update": status_obj["update_date"].isoformat() if status_obj.get("update_date") else "None",
        "functions": status_obj.get("functions", [])
    }

    if "referenced_by" in status_obj and status_obj["referenced_by"]:
        response_body["referenced_by"] = status_obj["referenced_by"]

    if "run_duration" in status_obj and status_obj["run_duration"] is not None:
        response_body["run_duration"] = status_obj["run_duration"]

    return sanitize_json_values(response_body)


def _try_parse_json_string(value):
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        return None


async def _read_request_json(request: Request) -> dict:
    try:
        parsed = await request.json()
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    except Exception:
        raw = (await request.body()).decode("utf-8", "ignore")
        parsed = _try_parse_json_string(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"raw_body": raw}


def _coerce_dict(value) -> dict:
    if isinstance(value, dict):
        return value

    parsed = _try_parse_json_string(value)
    if isinstance(parsed, dict):
        return parsed

    return {}


def _first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _get_request_context(payload: dict) -> dict:
    return _coerce_dict(payload.get("requestContext"))


def _get_body_payload(payload: dict) -> dict:
    return _coerce_dict(payload.get("body"))


def _get_query_params(payload: dict) -> dict:
    query_params = _coerce_dict(payload.get("queryStringParameters"))
    if query_params:
        return query_params

    params = _coerce_dict(payload.get("params"))
    query_params = _coerce_dict(params.get("querystring"))
    if query_params:
        return query_params

    query_params = _coerce_dict(params.get("queryString"))
    if query_params:
        return query_params

    return {}


def _extract_connection_id(payload: dict) -> str | None:
    request_context = _get_request_context(payload)
    body_payload = _get_body_payload(payload)
    query_params = _get_query_params(payload)

    value = _first_non_empty(
        payload.get("connectionId"),
        payload.get("connection_id"),
        request_context.get("connectionId"),
        body_payload.get("connectionId"),
        body_payload.get("connection_id"),
        query_params.get("connectionId"),
        query_params.get("connection_id")
    )

    return str(value) if value is not None else None


def _extract_job_id(payload: dict) -> str | None:
    request_context = _get_request_context(payload)
    body_payload = _get_body_payload(payload)
    query_params = _get_query_params(payload)

    value = _first_non_empty(
        payload.get("job_id"),
        payload.get("jobId"),
        body_payload.get("job_id"),
        body_payload.get("jobId"),
        query_params.get("job_id"),
        query_params.get("jobId"),
        request_context.get("job_id"),
        request_context.get("jobId")
    )

    return str(value) if value is not None else None


def _extract_message_id(payload: dict) -> str | None:
    body_payload = _get_body_payload(payload)

    value = _first_non_empty(
        payload.get("message_id"),
        payload.get("messageId"),
        body_payload.get("message_id"),
        body_payload.get("messageId")
    )

    return str(value) if value is not None else None


def _extract_route_key(payload: dict) -> str | None:
    request_context = _get_request_context(payload)
    body_payload = _get_body_payload(payload)

    value = _first_non_empty(
        payload.get("routeKey"),
        request_context.get("routeKey"),
        body_payload.get("routeKey"),
        body_payload.get("action"),
        body_payload.get("type")
    )

    return str(value) if value is not None else None


def _extract_management_endpoint(payload: dict) -> str:
    request_context = _get_request_context(payload)

    domain_name = _first_non_empty(
        payload.get("domainName"),
        payload.get("domain"),
        request_context.get("domainName"),
        request_context.get("domain")
    )

    stage = _first_non_empty(
        payload.get("stage"),
        request_context.get("stage")
    )

    if domain_name:
        endpoint = f"https://{str(domain_name).strip().rstrip('/')}"
        if stage and str(stage).strip() and str(stage).strip() != "$default":
            endpoint = f"{endpoint}/{str(stage).strip()}"
        return endpoint

    return _derive_management_endpoint_from_websocket_url(JOB_STATUS_WS_API_GATEWAY_WSS_URL)


def _is_api_gateway_connection_gone(exc: Exception) -> bool:
    if not isinstance(exc, botocore.exceptions.ClientError):
        return False

    return exc.response.get("Error", {}).get("Code") == "GoneException"


def _post_to_connection_sync(management_endpoint: str, connection_id: str, payload: dict) -> None:
    client = boto3.client("apigatewaymanagementapi", endpoint_url=management_endpoint)
    client.post_to_connection(
        ConnectionId=connection_id,
        Data=json.dumps(sanitize_json_values(payload)).encode("utf-8")
    )


async def _post_to_connection(management_endpoint: str, connection_id: str, payload: dict) -> None:
    await asyncio.to_thread(_post_to_connection_sync, management_endpoint, connection_id, payload)


def _delete_connection_sync(management_endpoint: str, connection_id: str) -> None:
    client = boto3.client("apigatewaymanagementapi", endpoint_url=management_endpoint)
    client.delete_connection(ConnectionId=connection_id)


async def _delete_connection(management_endpoint: str, connection_id: str) -> None:
    try:
        await asyncio.to_thread(_delete_connection_sync, management_endpoint, connection_id)
    except botocore.exceptions.ClientError as exc:
        if not _is_api_gateway_connection_gone(exc):
            raise


def _get_connection_sync(management_endpoint: str, connection_id: str) -> dict:
    client = boto3.client("apigatewaymanagementapi", endpoint_url=management_endpoint)
    return client.get_connection(ConnectionId=connection_id)


async def _get_connection(management_endpoint: str, connection_id: str) -> dict:
    return await asyncio.to_thread(_get_connection_sync, management_endpoint, connection_id)


async def _wait_for_api_gateway_connection_ready(
    management_endpoint: str,
    connection_id: str,
    max_wait_seconds: float = JOB_STATUS_WS_CONNECT_READY_MAX_WAIT_SECONDS,
    poll_seconds: float = JOB_STATUS_WS_CONNECT_READY_POLL_SECONDS
) -> None:
    deadline = time.monotonic() + max_wait_seconds
    last_exc: Exception | None = None

    while True:
        try:
            await _get_connection(management_endpoint, connection_id)
            return
        except botocore.exceptions.ClientError as exc:
            last_exc = exc

            if not _is_api_gateway_connection_gone(exc):
                raise

            if time.monotonic() >= deadline:
                raise

            await asyncio.sleep(poll_seconds)

    if last_exc:
        raise last_exc


async def _wait_for_ws_ack(
    websocket: WebSocket,
    expected_message_id: str,
    timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for ack for message_id={expected_message_id}")

        incoming = await asyncio.wait_for(websocket.receive_json(), timeout=remaining)
        if not isinstance(incoming, dict):
            continue

        if incoming.get("type") != "ack":
            continue

        if incoming.get("message_id") == expected_message_id:
            return


async def _send_ws_message_with_ack(
    websocket: WebSocket,
    message_type: str,
    payload: dict,
    ack_timeout_seconds: float
) -> str:
    message_id = uuid.uuid4().hex

    outbound = {
        "type": message_type,
        "message_id": message_id,
        "requires_ack": True,
        **payload
    }

    await websocket.send_json(outbound)
    await _wait_for_ws_ack(websocket, message_id, ack_timeout_seconds)

    return message_id


async def _remove_api_gateway_connection(connection_id: str, cancel_task: bool = True) -> dict | None:
    async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
        state = _ACTIVE_API_GATEWAY_CONNECTIONS.pop(connection_id, None)

    if not state:
        return None

    stop_event = state.get("stop_event")
    if isinstance(stop_event, asyncio.Event):
        stop_event.set()

    pending_ack_event = state.get("pending_ack_event")
    if isinstance(pending_ack_event, asyncio.Event):
        pending_ack_event.set()

    task = state.get("task")
    if cancel_task and isinstance(task, asyncio.Task) and not task.done() and task is not asyncio.current_task():
        task.cancel()

    return state


async def _mark_api_gateway_message_acknowledged(connection_id: str, message_id: str | None) -> bool:
    if not connection_id or not message_id:
        return False

    async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
        state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
        if not state:
            return False

        pending_message_id = state.get("pending_ack_message_id")
        pending_ack_event = state.get("pending_ack_event")
        if pending_message_id != message_id or not isinstance(pending_ack_event, asyncio.Event):
            return False

        state["pending_ack_message_id"] = None
        state["pending_ack_event"] = None
        pending_ack_event.set()
        return True


async def _send_api_gateway_message_with_ack(
    connection_id: str,
    management_endpoint: str,
    message_type: str,
    payload: dict,
    ack_timeout_seconds: float
) -> str:
    message_id = uuid.uuid4().hex
    ack_event = asyncio.Event()

    async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
        state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
        if not state:
            raise RuntimeError(f"No active API Gateway websocket state for connection_id={connection_id}")

        state["pending_ack_message_id"] = message_id
        state["pending_ack_event"] = ack_event

    outbound = {
        "type": message_type,
        "message_id": message_id,
        "requires_ack": True,
        **payload
    }

    try:
        await _post_to_connection(management_endpoint, connection_id, outbound)
        await asyncio.wait_for(ack_event.wait(), timeout=ack_timeout_seconds)
        return message_id
    except Exception:
        async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
            state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
            if state and state.get("pending_ack_message_id") == message_id:
                state["pending_ack_message_id"] = None
                state["pending_ack_event"] = None
        raise


async def _run_api_gateway_job_status_stream(connection_id: str) -> None:
    sql_status_retriever = JobStatusRetriever()
    last_payload_signature = None
    last_outbound_at = 0.0

    try:
        async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
            state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)

        if not state:
            return

        await _wait_for_api_gateway_connection_ready(
            management_endpoint=state["management_endpoint"],
            connection_id=connection_id
        )

        while True:
            async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
                state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)

            if not state:
                break

            stop_event = state.get("stop_event")
            if isinstance(stop_event, asyncio.Event) and stop_event.is_set():
                break

            job_id = state["job_id"]
            management_endpoint = state["management_endpoint"]

            status_obj = sql_status_retriever.get_status_by_uuid(job_id)
            response_body = _build_job_status_response_body(job_id, status_obj)
            payload_signature = json.dumps(response_body, sort_keys=True, default=str)
            now = time.monotonic()

            should_send_status = payload_signature != last_payload_signature
            should_send_heartbeat = (
                not should_send_status and
                (now - last_outbound_at) >= JOB_STATUS_WS_HEARTBEAT_INTERVAL_SECONDS
            )

            if should_send_status:
                await _send_api_gateway_message_with_ack(
                    connection_id=connection_id,
                    management_endpoint=management_endpoint,
                    message_type="job_status",
                    payload=response_body,
                    ack_timeout_seconds=JOB_STATUS_WS_ACK_TIMEOUT_SECONDS
                )
                last_payload_signature = payload_signature
                last_outbound_at = time.monotonic()

                status_upper = str(response_body.get("status") or "").upper()
                if status_upper in {"DONE", "FAILURE"}:
                    break

            elif should_send_heartbeat:
                await _send_api_gateway_message_with_ack(
                    connection_id=connection_id,
                    management_endpoint=management_endpoint,
                    message_type="heartbeat",
                    payload={"job_id": job_id},
                    ack_timeout_seconds=JOB_STATUS_WS_ACK_TIMEOUT_SECONDS
                )
                last_outbound_at = time.monotonic()

            if isinstance(stop_event, asyncio.Event):
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=JOB_STATUS_WS_POLL_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(JOB_STATUS_WS_POLL_INTERVAL_SECONDS)

    except asyncio.CancelledError:
        pass

    except TimeoutError as exc:
        print(f"JobRunnerRoutes: API Gateway websocket ack timeout for connection_id={connection_id}: {exc}", flush=True)
        try:
            async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
                state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
            if state:
                await _delete_connection(state["management_endpoint"], connection_id)
        except Exception:
            pass

    except botocore.exceptions.ClientError as exc:
        if _is_api_gateway_connection_gone(exc):
            print(
                f"JobRunnerRoutes: API Gateway websocket connection gone for connection_id={connection_id}: "
                f"{traceback.format_exc().splitlines()}",
                flush=True
            )
        else:
            print(
                f"JobRunnerRoutes: API Gateway websocket client error for connection_id={connection_id}: "
                f"{traceback.format_exc().splitlines()}",
                flush=True
            )

    except Exception:
        print(f"JobRunnerRoutes: API Gateway websocket stream hit exception {traceback.format_exc().splitlines()}", flush=True)
        try:
            async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
                state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
            if state:
                await _post_to_connection(
                    state["management_endpoint"],
                    connection_id,
                    {
                        "type": "job_status_error",
                        "job_id": state["job_id"],
                        "status": "Exception occurred while retrieving job status",
                        "log": traceback.format_exc().splitlines()
                    }
                )
        except Exception:
            pass

        try:
            async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
                state = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
            if state:
                await _delete_connection(state["management_endpoint"], connection_id)
        except Exception:
            pass

    finally:
        sql_status_retriever.complete()
        await _remove_api_gateway_connection(connection_id, cancel_task=False)


async def _handle_api_gateway_connect(payload: dict) -> JSONResponse:
    connection_id = _extract_connection_id(payload)
    job_id = _extract_job_id(payload)
    management_endpoint = _extract_management_endpoint(payload)

    if not connection_id:
        return JSONResponse({"error": "connectionId is required."}, status_code=400)

    if not job_id:
        return JSONResponse({"error": "job_id is required."}, status_code=400)

    await _remove_api_gateway_connection(connection_id)

    stop_event = asyncio.Event()
    state = {
        "connection_id": connection_id,
        "job_id": job_id,
        "management_endpoint": management_endpoint,
        "stop_event": stop_event,
        "task": None,
        "pending_ack_message_id": None,
        "pending_ack_event": None
    }

    async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
        _ACTIVE_API_GATEWAY_CONNECTIONS[connection_id] = state

    task = asyncio.create_task(_run_api_gateway_job_status_stream(connection_id))

    async with _ACTIVE_API_GATEWAY_CONNECTIONS_LOCK:
        current = _ACTIVE_API_GATEWAY_CONNECTIONS.get(connection_id)
        if current is not None:
            current["task"] = task

    return JSONResponse({
        "ok": True,
        "connection_id": connection_id,
        "job_id": job_id,
        "management_endpoint": management_endpoint
    }, status_code=200)


async def _handle_api_gateway_ack(payload: dict) -> JSONResponse:
    connection_id = _extract_connection_id(payload)
    message_id = _extract_message_id(payload)
    acknowledged = await _mark_api_gateway_message_acknowledged(connection_id, message_id)

    return JSONResponse({
        "ok": True,
        "connection_id": connection_id,
        "message_id": message_id,
        "acknowledged": acknowledged
    }, status_code=200)


async def _handle_api_gateway_disconnect(payload: dict) -> JSONResponse:
    connection_id = _extract_connection_id(payload)
    if not connection_id:
        return JSONResponse({"error": "connectionId is required."}, status_code=400)

    await _remove_api_gateway_connection(connection_id)

    return JSONResponse({
        "ok": True,
        "connection_id": connection_id
    }, status_code=200)


@router.websocket("/jobs/status/ws/{job_id}")
@router.websocket("/jobs/status/ws/local/{job_id}")
async def job_status_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()

    sql_status_retriever = JobStatusRetriever()
    last_payload_signature = None
    last_outbound_at = 0.0

    try:
        connection_message_displayed = False
        print(f"JobRunnerRoutes: websocket attempting to connect for job_id={job_id}", flush=True)
        while True:
            status_obj = sql_status_retriever.get_status_by_uuid(job_id)
            response_body = _build_job_status_response_body(job_id, status_obj)
            payload_signature = json.dumps(response_body, sort_keys=True, default=str)
            now = time.monotonic()

            should_send_status = payload_signature != last_payload_signature
            should_send_heartbeat = (
                not should_send_status and
                (now - last_outbound_at) >= JOB_STATUS_WS_HEARTBEAT_INTERVAL_SECONDS
            )

            if should_send_status:
                await _send_ws_message_with_ack(
                    websocket=websocket,
                    message_type="job_status",
                    payload=response_body,
                    ack_timeout_seconds=JOB_STATUS_WS_ACK_TIMEOUT_SECONDS
                )
                last_payload_signature = payload_signature
                last_outbound_at = time.monotonic()

                status_upper = str(response_body.get("status") or "").upper()
                if status_upper in {"DONE", "FAILURE"}:
                    break

            elif should_send_heartbeat:
                await _send_ws_message_with_ack(
                    websocket=websocket,
                    message_type="heartbeat",
                    payload={"job_id": job_id},
                    ack_timeout_seconds=JOB_STATUS_WS_ACK_TIMEOUT_SECONDS
                )
                last_outbound_at = time.monotonic()

            if not connection_message_displayed:
                print(f"JobRunnerRoutes: websocket in connection state for job_id={job_id}", flush=True)
                connection_message_displayed = True

            await asyncio.sleep(JOB_STATUS_WS_POLL_INTERVAL_SECONDS)

    except WebSocketDisconnect:
        print(f"JobRunnerRoutes: websocket disconnected for job_id={job_id}", flush=True)

    except TimeoutError as exc:
        print(f"JobRunnerRoutes: websocket ack timeout for job_id={job_id}: {exc}", flush=True)
        try:
            await websocket.close(code=1008, reason="Frontend did not acknowledge websocket message")
        except Exception:
            pass

    except Exception:
        print(f"JobRunnerRoutes: job_status_ws hit exception {traceback.format_exc().splitlines()}", flush=True)
        try:
            await websocket.send_json({
                "type": "job_status_error",
                "job_id": job_id,
                "status": "Exception occurred while retrieving job status",
                "log": traceback.format_exc().splitlines()
            })
        except Exception:
            pass

        try:
            await websocket.close(code=1011, reason="Internal websocket error")
        except Exception:
            pass

    finally:
        sql_status_retriever.complete()
        try:
            await websocket.close()
        except Exception:
            pass


@router.post("/jobs/status/ws/connect", include_in_schema=False)
async def job_status_ws_api_gateway_connect(request: Request):
    body = await _read_request_json(request)
    return await _handle_api_gateway_connect(body)


@router.post("/jobs/status/ws/ack", include_in_schema=False)
async def job_status_ws_api_gateway_ack(request: Request):
    body = await _read_request_json(request)
    return await _handle_api_gateway_ack(body)


@router.post("/jobs/status/ws/disconnect", include_in_schema=False)
async def job_status_ws_api_gateway_disconnect(request: Request):
    body = await _read_request_json(request)
    return await _handle_api_gateway_disconnect(body)


@router.post("/jobs/status/ws/default", include_in_schema=False)
async def job_status_ws_api_gateway_default(request: Request):
    body = await _read_request_json(request)
    route_key = (_extract_route_key(body) or "").strip().lower()

    if route_key == "ack":
        return await _handle_api_gateway_ack(body)

    return JSONResponse({"ok": True, "route": route_key or "$default"}, status_code=200)


# Put behind bearer token
@router.post("/jobs/status", include_in_schema=False)
async def job_status(request: Request):
    # Fetches the current status and log for a given job_id from job_runner_log.
    body = await request.json()
    job_id = body.get("job_id")

    sql_status_retriever = JobStatusRetriever()
    try:
        status_obj = sql_status_retriever.get_status_by_uuid(job_id)
        response_body = _build_job_status_response_body(job_id, status_obj)
        return JSONResponse(content=response_body, status_code=200)

    except Exception:
        print(f"NVFlareRoutes: job_status hit exception {traceback.format_exc().splitlines()}", flush=True)
        return JSONResponse(content={
            "job_id": job_id,
            "status": "Exception occured while retrieving job status",
            "log": traceback.format_exc().splitlines()
        }, status_code=400)
    finally:
        sql_status_retriever.complete()


def _isoformat_if_present(value):
    return value.isoformat() if value else None


def _serialize_nvflare_job_info(row: dict, functions: list[str]) -> dict:
    threshold_payload = None
    if row.get("threshold_id") is not None:
        threshold_payload = {
            "id": row.get("threshold_id"),
            "method": row.get("threshold_method"),
            "threshold": row.get("threshold_value"),
        }

    payload = {
        "id": row.get("id"),
        "project_id": row.get("project_id"),
        "nvflare_assigned_id": row.get("nvflare_assigned_id"),
        "filter_id": row.get("filter_id"),
        "threshold_config_id": row.get("threshold_config_id"),
        "status": row.get("status"),
        "job_path": row.get("job_path"),
        "output_path": row.get("output_path"),
        "job_runner_id": row.get("job_runner_id"),
        "non_contributing_clients": row.get("non_contributing_clients"),
        "exclude_analyzing_clients": row.get("exclude_analyzing_clients"),
        "submit_time": _isoformat_if_present(row.get("submit_time")),
        "run_duration": row.get("run_duration"),
        "create_date": _isoformat_if_present(row.get("create_date")),
        "update_date": _isoformat_if_present(row.get("update_date")),
        "functions": functions,
    }

    if threshold_payload is not None:
        payload["threshold"] = threshold_payload

    # The Results page uses /jobs/info when opened from Job History. Preserve
    # the datasource selection logged when the job was submitted instead of
    # making the frontend infer it from the project's current default group.
    # datasource_log_id distinguishes a logged default (NULL group id) from
    # an older job that has no datasource log row at all.
    if row.get("datasource_log_id") is not None:
        datasource_log = {
            "project_id": row.get("datasource_log_project_id"),
            "datasource_group_id": row.get("datasource_log_group_id"),
            "datasource_group_name": row.get("datasource_log_group_name"),
            "create_date": _isoformat_if_present(row.get("datasource_log_create_date")),
            "update_date": _isoformat_if_present(row.get("datasource_log_update_date")),
        }
        payload["datasource_log"] = datasource_log
        payload["datasource_group_id"] = datasource_log["datasource_group_id"]
        payload["datasource_group_name"] = datasource_log["datasource_group_name"]

    return payload


@router.post("/jobs/info", include_in_schema=False)
async def get_nvflare_job_info(request: Request):
    body = await request.json()
    nvflare_job_id = body.get("nvflare_job_id") or body.get("nvflare_assigned_id")
    job_runner_id = body.get("job_runner_id")
    internal_job_id = body.get("id")

    where_clauses = []
    params = []

    if nvflare_job_id:
        where_clauses.append("j.nvflare_assigned_id = %s")
        params.append(str(nvflare_job_id))

    if job_runner_id:
        where_clauses.append("j.job_runner_id = %s")
        params.append(str(job_runner_id))

    if internal_job_id is not None:
        try:
            where_clauses.append("j.id = %s")
            params.append(int(internal_job_id))
        except (TypeError, ValueError):
            pass

    if not where_clauses:
        return JSONResponse({"error": "nvflare_job_id, job_runner_id, or id is required."}, status_code=400)

    connection = MySQLConnectionProvider.get_instance().get_connection()
    cursor = connection.cursor()
    try:
        sql = f"""
            SELECT j.*,
                   tc.id AS threshold_id,
                   tc.method AS threshold_method,
                   tc.threshold AS threshold_value,
                   jl.id AS datasource_log_id,
                   jl.project_id AS datasource_log_project_id,
                   jl.datasource_group_id AS datasource_log_group_id,
                   dg.group_name AS datasource_log_group_name,
                   jl.create_date AS datasource_log_create_date,
                   jl.update_date AS datasource_log_update_date
            FROM {MySQLTable.NVFLARE_JOBS} j
            LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
              ON tc.id = j.threshold_config_id
            LEFT JOIN nvflare_job_datasource_log jl
              ON jl.nvflare_job_id = j.id
            LEFT JOIN defined_project_datasource_groups dg
              ON dg.id = jl.datasource_group_id
            WHERE {' OR '.join(where_clauses)}
            ORDER BY j.id DESC
            LIMIT 1
        """
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            return JSONResponse({"job": None}, status_code=200)

        cursor.execute(
            f"""
            SELECT df.name
            FROM {MySQLTable.NVFLARE_JOB_FUNCTIONS} njf
            JOIN {MySQLTable.FUNCTIONS} df
              ON df.id = njf.function_id
            WHERE njf.job_id = %s
            ORDER BY df.name
            """,
            (row["id"],),
        )
        function_rows = cursor.fetchall() or []
        functions = [str(function_row["name"]) for function_row in function_rows if function_row.get("name")]

        return JSONResponse(sanitize_json_values({"job": _serialize_nvflare_job_info(row, functions)}), status_code=200)
    except Exception:
        return JSONResponse(
            content={"error": f"Failed to fetch NVFlare job information: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )
    finally:
        cursor.close()
        connection.close()


# Put behind bearer token
@router.post("/jobs/results", include_in_schema=False)
async def get_job_results_by_nvflare_id(request: Request):
    body = await request.json()
    nvflare_job_id = body.get("nvflare_job_id")
    function_name = body.get("function")
    workflow_id = body.get("workflow_id")

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    # nvflare_job_id becomes a filesystem path component; constrain it to an
    # id-safe charset to prevent path traversal.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(nvflare_job_id)):
        return JSONResponse({"error": "Invalid nvflare_job_id."}, status_code=400)
    if not function_name:
        return JSONResponse({"error": "function is required."}, status_code=400)
    if not workflow_id:
        return JSONResponse({"error": "workflow_id is required."}, status_code=400)

    try:
        function_enum = SupportedFunction(function_name)
    except Exception:
        return JSONResponse({"error": f"Unsupported function '{function_name}'"}, status_code=400)

    try:
        retriever = NVFlareJobsDataRetriever(nvflare_job_id, function_enum)
        job_data, function_config = retriever.retrieve_workflow_data_with_config(workflow_id)

        payload = sanitize_json_values({
            "job_data": job_data,
            "function_config": function_config
        })

        # Taskflow diagnostics are intentionally NOT generated on this request.
        # The results viewer starts them only after workflow data has loaded so
        # users can begin reviewing results while diagnostics finish separately.
        return JSONResponse(payload)
    except Exception:
        return JSONResponse(
            content={"error": f"Failed to fetch workflow data: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )


@router.post("/jobs/taskflow/start", include_in_schema=False)
async def start_job_taskflow_diagnostics(request: Request):
    body = await request.json()
    nvflare_job_id = str(body.get("nvflare_job_id") or "").strip()

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    if not taskflow_service.is_valid_job_id(nvflare_job_id):
        return JSONResponse({"error": "Invalid nvflare_job_id."}, status_code=400)

    try:
        await taskflow_service.ensure_generation_started(
            nvflare_job_id,
            case_label=f"Job {nvflare_job_id}",
        )
        diagnostics = taskflow_service.get_diagnostics(nvflare_job_id)
        state = (diagnostics.get("status") or {}).get("state")
        return JSONResponse(
            sanitize_json_values(diagnostics),
            status_code=202 if state in {"queued", "running"} else 200,
        )
    except Exception:
        return JSONResponse(
            content={"error": f"Failed to start taskflow diagnostics: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )


@router.post("/jobs/taskflow/status", include_in_schema=False)
async def get_job_taskflow_diagnostics_status(request: Request):
    body = await request.json()
    nvflare_job_id = str(body.get("nvflare_job_id") or "").strip()

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    if not taskflow_service.is_valid_job_id(nvflare_job_id):
        return JSONResponse({"error": "Invalid nvflare_job_id."}, status_code=400)

    try:
        return JSONResponse(sanitize_json_values(taskflow_service.get_diagnostics(nvflare_job_id)), status_code=200)
    except Exception:
        return JSONResponse(
            content={"error": f"Failed to fetch taskflow diagnostics: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )


@router.get("/jobs/taskflow/artifact", include_in_schema=False)
async def get_job_taskflow_artifact(nvflare_job_id: str, artifact: str):
    if not taskflow_service.is_valid_job_id(nvflare_job_id):
        return JSONResponse({"error": "Invalid nvflare_job_id."}, status_code=400)

    path = taskflow_service.get_artifact_path(nvflare_job_id, artifact)
    if path is None:
        return JSONResponse({"error": "Taskflow artifact not found."}, status_code=404)

    return FileResponse(path=path)


# Put behind bearer token
@router.post("/jobs/function/config", include_in_schema=False)
async def get_job_function_config(request: Request):
    body = await request.json()
    nvflare_job_id = body.get("nvflare_job_id")
    function_name = body.get("function")
    workflow_id = body.get("workflow_id")

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    # nvflare_job_id becomes a filesystem path component; constrain it to an
    # id-safe charset to prevent path traversal.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(nvflare_job_id)):
        return JSONResponse({"error": "Invalid nvflare_job_id."}, status_code=400)
    if not function_name:
        return JSONResponse({"error": "function is required."}, status_code=400)
    if not workflow_id:
        return JSONResponse({"error": "workflow_id is required."}, status_code=400)

    try:
        function_enum = SupportedFunction(function_name)
    except Exception:
        return JSONResponse({"error": f"Unsupported function '{function_name}'"}, status_code=400)

    try:
        retriever = NVFlareJobsDataRetriever(nvflare_job_id, function_enum)
        function_config = retriever.retrieve_function_config(workflow_id)
        return JSONResponse({"function_config": sanitize_json_values(function_config)})
    except Exception:
        return JSONResponse(
            content={"error": f"Failed to fetch workflow data: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )


@router.post("/jobs/results/mapping", include_in_schema=False)
async def get_job_results_mapping(request: Request):
    body = await request.json()
    nvflare_job_id = body.get("nvflare_job_id")
    function_name = body.get("function")

    if not nvflare_job_id:
        return JSONResponse({"error": "nvflare_job_id is required."}, status_code=400)
    if not function_name:
        return JSONResponse({"error": "function is required."}, status_code=400)

    function_enum = SupportedFunction.from_name(function_name)
    if function_enum is None:
        return JSONResponse(
            {"error": f"Unsupported function '{function_name}'"},
            status_code=400,
        )

    try:
        retriever = NVFlareJobsDataRetriever(
            nvflare_job_id=nvflare_job_id,
            function=function_enum
        )
        workflow_dirs = retriever.list_workflow_dirs()
        profile_summary = retriever.get_profile_summary()

        payload = {"workflow_dirs": workflow_dirs}
        if profile_summary:
            payload["profile_summary"] = profile_summary

        return JSONResponse(sanitize_json_values(payload))
    except Exception:
        return JSONResponse(
            {"error": f"Failed to fetch mapping: {traceback.format_exc().splitlines()}"},
            status_code=500,
        )
