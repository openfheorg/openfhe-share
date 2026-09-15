from unittest.mock import patch

from app.core.job_runner.nvflare_jobs.apis.fhir import fhir_analysis_query_engine as module


def test_signature_is_order_independent():
    a = module._signature_from_params("Observation", {"code": {"B", "A"}, "status": {"final"}})
    b = module._signature_from_params("Observation", {"status": {"final"}, "code": {"A", "B"}})
    assert a == b
    assert len(a) == 64


def test_empty_plan_has_no_requirements():
    plan = module._empty_plan()
    assert not plan.needs_patient
    assert not plan.needs_observation
    assert not plan.needs_medication
    assert plan.observation_signature == "none"


def test_expand_param_values_accepts_list_or_scalar():
    assert module._expand_param_values({"values": [" A ", "", None]}) == ["A"]
    assert module._expand_param_values({"value": " B "}) == ["B"]
    assert module._expand_param_values({}) == []


def test_normalize_param_sets_deduplicates_identical_sets():
    normalized, signatures = module._normalize_param_sets(
        [{"code": {"A", "B"}}, {"code": {"B", "A"}}, {"code": {"C"}}]
    )
    assert normalized == [{"code": ["A", "B"]}, {"code": ["C"]}]
    assert len(signatures) == 2


def test_build_analysis_fetch_plan_combines_data_and_query_requirements():
    query_schema = {
        "computations": {
            "mean": {
                "properties": {
                    "data_column_id": {
                        "columns": {
                            "age": {
                                "resources": [
                                    {"resourceType": "Patient"},
                                    {
                                        "resourceType": "Observation",
                                        "params": [{"name": "code", "values": ["A", "B"]}],
                                    },
                                ]
                            }
                        }
                    }
                }
            }
        }
    }
    data_schema = {
        "computations": {
            "mean": {
                "properties": {
                    "data_column_id": {
                        "columns": {"age": {"resourceType": "Patient"}}
                    }
                }
            }
        }
    }
    with patch.object(module, "load_analysis_query_schema", return_value=query_schema), patch.object(
        module, "load_analysis_data_schema", return_value=data_schema
    ):
        plan = module.build_analysis_fetch_plan("mean", {"data_column_id": "AGE"})
    assert plan.needs_patient is True
    assert plan.needs_observation is True
    assert plan.observation_params == {"code": ["A", "B"]}
    assert plan.observation_param_sets == [{"code": ["A", "B"]}]


def test_build_analysis_fetch_plan_returns_empty_for_unknown_computation():
    with patch.object(module, "load_analysis_query_schema", return_value={"computations": {}}), patch.object(
        module, "load_analysis_data_schema", return_value={"computations": {}}
    ):
        assert module.build_analysis_fetch_plan("unknown", {}).observation_signature == "none"


def test_cache_keys_are_stable_for_subject_order():
    a = module._build_subject_cache_key("https://fhir", ["2", "1", "1"], project_id=3)
    b = module._build_subject_cache_key("https://fhir", ["1", "2"], project_id="3")
    assert a == b
    resource = module._build_analysis_resource_cache_key("https://fhir", " mean ", ["1"], " sig ", 3)
    assert resource[2] == "mean"
    assert resource[-1] == "sig"
