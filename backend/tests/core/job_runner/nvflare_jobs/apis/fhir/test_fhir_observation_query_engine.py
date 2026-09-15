from unittest.mock import patch

from app.core.job_runner.nvflare_jobs.apis.fhir import fhir_observation_query_engine as module


def test_subject_cache_key_is_order_independent():
    assert module._build_subject_cache_key("https://fhir", ["2", "1"], 2) == module._build_subject_cache_key(
        "https://fhir", ["1", "2"], "2"
    )


def test_cached_observation_subset_returns_requested_copy():
    module._OBSERVATION_BROAD_CACHE.clear()
    key = module._build_subject_cache_key("https://fhir", ["1", "2"], 2)
    module._OBSERVATION_BROAD_CACHE[key] = {"1": [{"id": "a"}], "2": [{"id": "b"}]}
    result = module._get_cached_observation_subset("https://fhir", ["2"], 2)
    assert result == {"2": [{"id": "b"}]}
    result["2"].append({"id": "c"})
    assert len(module._OBSERVATION_BROAD_CACHE[key]["2"]) == 1


def test_build_observation_search_params_uses_controls():
    schema = {
        "controls": [
            {
                "id": "code",
                "save": {"targets": [{"filter_group": "Observation", "field": "code", "operator": "="}]},
                "query": {"kind": "search-param", "param": "code"},
            }
        ]
    }
    filters = [{"filter_type": "Observation", "column_name": "code", "operator": "=", "value": "PBRM1"}]
    with patch.object(module, "load_observation_filter_schema", return_value=schema):
        params = module.build_observation_search_params(filters)
    assert params[-1] == ("code", "PBRM1")


def test_fetch_observations_prefiltered_deduplicates_and_filters_resource_type():
    resources = [
        {"resourceType": "Observation", "id": "1"},
        {"resourceType": "Observation", "id": "1"},
        {"resourceType": "Observation"},
        {"resourceType": "Patient", "id": "p"},
    ]
    with patch.object(module, "session", return_value=object()), patch.object(
        module, "build_observation_search_params", return_value=[("_count", "10")]
    ), patch.object(module, "bundle_entries_from_url", return_value=resources):
        result = module.fetch_observations_prefiltered("https://fhir", [], ["p1"])
    assert result == [resources[0], resources[2]]


def test_get_cached_observations_queries_once_then_reuses_cache():
    module._OBSERVATION_BROAD_CACHE.clear()
    observations = [
        {"resourceType": "Observation", "id": "o1", "subject": {"reference": "Patient/1"}},
        {"resourceType": "Observation", "id": "o2", "subject": {"reference": "Patient/2"}},
    ]
    with patch.object(module, "query_observations", return_value=observations) as query:
        first = module.get_cached_observations_by_patient("https://fhir", ["1", "2"])
        second = module.get_cached_observations_by_patient("https://fhir", ["2", "1"])
    assert first["1"][0]["id"] == "o1"
    assert second["2"][0]["id"] == "o2"
    query.assert_called_once()
