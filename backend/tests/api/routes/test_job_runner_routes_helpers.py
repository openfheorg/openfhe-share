import json
from datetime import datetime, timezone

import pytest

from app.api.routes.JobRunnerRoutes import (
    _build_job_status_response_body,
    _coerce_dict,
    _derive_management_endpoint_from_websocket_url,
    _extract_connection_id,
    _extract_job_id,
    _extract_management_endpoint,
    _extract_message_id,
    _extract_route_key,
    _first_non_empty,
    _serialize_nvflare_job_info,
    _try_parse_json_string,
    sanitize_json_values,
)


def test_sanitize_json_values_recurses_and_replaces_non_finite_numbers():
    value = {"a": float("nan"), "b": [float("inf"), 1], "c": (2,)}
    assert sanitize_json_values(value) == {"a": None, "b": [None, 1], "c": [2]}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("wss://host/prod/", "https://host/prod"),
        ("ws://host/default", "http://host/default"),
        ("https://host/prod/", "https://host/prod"),
        ("host/prod", "https://host/prod"),
    ],
)
def test_derive_management_endpoint(value, expected):
    assert _derive_management_endpoint_from_websocket_url(value) == expected


def test_build_job_status_response_body_for_queued_and_existing_status():
    assert _build_job_status_response_body("job", None)["status"] == "QUEUED"
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    result = _build_job_status_response_body(
        "job",
        {
            "status": "DONE",
            "log": "line1\nline2",
            "update_date": now,
            "functions": ["MEAN"],
            "referenced_by": ["nv1"],
            "run_duration": "1s",
        },
    )
    assert result["log"] == ["line1", "line2"]
    assert result["last_update"] == now.isoformat()
    assert result["referenced_by"] == ["nv1"]


def test_json_and_dict_helpers():
    assert _try_parse_json_string('{"a":1}') == {"a": 1}
    assert _try_parse_json_string("bad") is None
    assert _coerce_dict('{"a":1}') == {"a": 1}
    assert _coerce_dict([1]) == {}
    assert _first_non_empty(None, " ", 0, "x") == 0


def test_extractors_accept_api_gateway_payload_shapes():
    payload = {
        "requestContext": {"connectionId": "conn", "routeKey": "$connect", "domainName": "api.example", "stage": "prod"},
        "body": json.dumps({"jobId": "job", "messageId": "msg"}),
    }
    assert _extract_connection_id(payload) == "conn"
    assert _extract_job_id(payload) == "job"
    assert _extract_message_id(payload) == "msg"
    assert _extract_route_key(payload) == "$connect"
    assert _extract_management_endpoint(payload) == "https://api.example/prod"


def test_extract_management_endpoint_omits_default_stage():
    payload = {"requestContext": {"domainName": "api.example", "stage": "$default"}}
    assert _extract_management_endpoint(payload) == "https://api.example"


def test_serialize_nvflare_job_info_adds_threshold_and_iso_dates():
    created = datetime(2026, 7, 18, tzinfo=timezone.utc)
    result = _serialize_nvflare_job_info(
        {
            "id": 1,
            "project_id": 2,
            "threshold_id": 3,
            "threshold_method": "PROTECTED",
            "threshold_value": 5,
            "create_date": created,
        },
        ["MEAN"],
    )
    assert result["create_date"] == created.isoformat()
    assert result["functions"] == ["MEAN"]
    assert result["threshold"] == {"id": 3, "method": "PROTECTED", "threshold": 5}


def test_serialize_nvflare_job_info_preserves_logged_datasource_selection():
    logged_at = datetime(2026, 8, 14, 20, 39, 48, tzinfo=timezone.utc)
    result = _serialize_nvflare_job_info(
        {
            "id": 5,
            "project_id": 2,
            "datasource_log_id": 17,
            "datasource_log_project_id": 2,
            "datasource_log_group_id": 3,
            "datasource_log_group_name": "MSKChord",
            "datasource_log_create_date": logged_at,
            "datasource_log_update_date": logged_at,
        },
        ["EXCEPTIONAL_RESPONSE_DISCRIMINATION", "SURVIVAL_ANALYSIS"],
    )

    assert result["datasource_group_id"] == 3
    assert result["datasource_group_name"] == "MSKChord"
    assert result["datasource_log"] == {
        "project_id": 2,
        "datasource_group_id": 3,
        "datasource_group_name": "MSKChord",
        "create_date": logged_at.isoformat(),
        "update_date": logged_at.isoformat(),
    }

def test_serialize_nvflare_job_info_preserves_logged_default_datasource():
    result = _serialize_nvflare_job_info(
        {
            "id": 6,
            "project_id": 2,
            "datasource_log_id": 18,
            "datasource_log_project_id": 2,
            "datasource_log_group_id": None,
            "datasource_log_group_name": None,
        },
        ["SURVIVAL_ANALYSIS"],
    )

    assert "datasource_log" in result
    assert result["datasource_group_id"] is None
    assert result["datasource_group_name"] is None
