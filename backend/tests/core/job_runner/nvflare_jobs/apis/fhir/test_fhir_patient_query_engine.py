from datetime import date, datetime
from unittest.mock import Mock, patch

import pytest

from app.core.job_runner.nvflare_jobs.apis.fhir import fhir_patient_query_engine as module


def test_resolve_server_url_accepts_string_or_dict_and_strips_trailing_slash():
    assert module.resolve_server_url("https://fhir.example/") == "https://fhir.example"
    assert module.resolve_server_url({"server_url": "https://fhir.example/base/"}) == "https://fhir.example/base"
    with pytest.raises(ValueError):
        module.resolve_server_url({})


def test_chunked_normalizes_and_skips_blank_values():
    assert list(module.chunked([" a ", "", None, 2, "b"], 2)) == [["a", "2"], ["b"]]


def test_parse_iso_helpers():
    assert module.parse_iso_datetime("2026-07-18T12:30:00Z").isoformat() == "2026-07-18T12:30:00+00:00"
    assert module.parse_iso_datetime("bad") is None
    assert module.parse_iso_date("2026-07-18T12:00:00") == date(2026, 7, 18)
    assert module.parse_iso_date(None) is None


def test_normalize_filters_accepts_list_or_conditions_dict():
    conditions = [{"x": 1}]
    assert module.normalize_filters(conditions) is conditions
    assert module.normalize_filters({"conditions": conditions}) is conditions
    assert module.normalize_filters({}) == []


def test_http_get_json_uses_cache():
    module._HTTP_CACHE.clear()
    response = Mock()
    response.json.return_value = {"resourceType": "Bundle"}
    session = Mock()
    session.get.return_value = response

    first = module.http_get_json(session, "https://example/Patient", params=[("a", "b")])
    second = module.http_get_json(session, "https://example/Patient", params=[("a", "b")])

    assert first == second == {"resourceType": "Bundle"}
    session.get.assert_called_once()
    response.raise_for_status.assert_called_once()


def test_http_get_json_rejects_non_object_json():
    response = Mock()
    response.json.return_value = []
    session = Mock()
    session.get.return_value = response
    module._HTTP_CACHE.clear()
    with pytest.raises(ValueError, match="non-JSON"):
        module.http_get_json(session, "https://example/Patient")


def test_bundle_entries_follows_next_links():
    page1 = {
        "entry": [{"resource": {"resourceType": "Patient", "id": "1"}}],
        "link": [{"relation": "next", "url": "https://example/Patient?page=2"}],
    }
    page2 = {"entry": [{"resource": {"resourceType": "Patient", "id": "2"}}]}
    with patch.object(module, "http_get_json", side_effect=[page1, page2]) as get_json:
        result = module.bundle_entries_from_url(Mock(), "https://example/Patient", params=[("_count", "1")])
    assert [row["id"] for row in result] == ["1", "2"]
    assert get_json.call_count == 2
    assert get_json.call_args_list[1].kwargs["params"] is None


def test_pid_from_ref():
    assert module.pid_from_ref("Patient/abc") == "abc"
    assert module.pid_from_ref("Observation/abc") is None
    assert module.pid_from_ref(None) is None


def test_normalize_save_target_and_matching_condition():
    control = {
        "id": "gender",
        "save": {"targets": [{"filter_group": "Patient", "field": "gender", "operator": "="}]},
    }
    condition = {"filter_type": "Patient", "column_name": "gender", "operator": "=", "value": "female"}
    assert module.normalize_save_target(control["save"]["targets"][0]) == {
        "filter_type": "Patient",
        "column_name": "gender",
        "operator": "=",
    }
    assert module.find_matching_condition_for_control(control, [condition]) is condition
    assert module.find_matching_condition_for_control(control, []) is None


def test_serialize_condition_to_query_parts():
    assert module.serialize_condition_to_query_parts(
        {"query": {"kind": "search-param", "param": "gender"}},
        {"value": "female"},
    ) == [("gender", "female")]
    assert module.serialize_condition_to_query_parts(
        {"query": {"kind": "date-range", "param": "birthdate"}},
        {"values": ["2000-01-01", "2020-01-01"]},
    ) == [("birthdate", "ge2000-01-01"), ("birthdate", "le2020-01-01")]
    assert module.serialize_condition_to_query_parts(
        {"query": {"kind": "reverse-chain-token", "resource": "Observation", "referenceParam": "subject", "param": "code"}},
        {"value": ["A", "B"]},
    ) == [("_has:Observation:subject:code", "A,B")]


def test_build_patient_search_params_uses_schema_controls():
    schema = {
        "controls": [
            {
                "id": "gender",
                "save": {"targets": [{"filter_group": "Patient", "field": "gender", "operator": "="}]},
                "query": {"kind": "search-param", "param": "gender"},
            }
        ]
    }
    filters = [{"filter_type": "Patient", "column_name": "gender", "operator": "=", "value": "female"}]
    with patch.object(module, "load_patient_filter_schema", return_value=schema):
        params = module.build_patient_search_params(filters)
    assert params == [("_count", str(module.DEFAULT_RESOURCE_PAGE_SIZE)), ("gender", "female")]


def test_query_patients_deduplicates_by_id_and_ignores_other_resources():
    resources = [
        {"resourceType": "Patient", "id": "1"},
        {"resourceType": "Patient", "id": "1", "name": "new"},
        {"resourceType": "Observation", "id": "o1"},
    ]
    with patch.object(module, "session", return_value=Mock()), patch.object(
        module, "fetch_patients_prefiltered", return_value=resources
    ):
        result = module.query_patients([], "https://fhir.example")
    assert result == {"1": resources[1]}
