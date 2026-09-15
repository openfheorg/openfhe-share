from datetime import datetime

import pandas as pd
import pytest

from app.core.job_runner.nvflare_jobs.apis.fhir import filter_engine_config as module


@pytest.mark.parametrize(
    "value,expected",
    [
        (" 3.5 ", 3.5),
        (["2"], 2.0),
        (((1,),), 1.0),
        (pd.Series([4]), 4.0),
    ],
)
def test_coerce_float_scalar(value, expected):
    assert module._coerce_float_scalar(value) == expected


@pytest.mark.parametrize("value", ["", [1, 2], pd.Series([1, 2]), "abc"])
def test_coerce_float_scalar_rejects_invalid_shapes(value):
    with pytest.raises(ValueError):
        module._coerce_float_scalar(value, "test")


def test_survival_boundary_sources_normalizes_single_source_and_defaults_aggregation():
    window = {"start": {"resource": "Patient", "path": "birthDate"}}
    assert module._survival_boundary_sources(window, "start") == [
        {"resource": "Patient", "path": "birthDate", "aggregation": "min"}
    ]


def test_survival_boundary_sources_accepts_multiple_sources():
    window = {
        "stop": {
            "sources": [
                {"resource": "Patient", "path": "deceasedDateTime", "aggregation": "first"},
                {"resource": "Observation", "path": "effectiveDateTime", "code": "X"},
            ]
        }
    }
    sources = module._survival_boundary_sources(window, "stop")
    assert sources[0]["aggregation"] == "first"
    assert sources[1]["aggregation"] == "max"


def test_survival_boundary_sources_rejects_unsupported_resource():
    with pytest.raises(ValueError, match="unsupported resource"):
        module._survival_boundary_sources(
            {"start": {"resource": "Procedure", "path": "performedDateTime"}},
            "start",
        )


def test_read_resource_path():
    assert module._read_resource_path({"a": {"b": 3}}, "a.b") == 3
    assert module._read_resource_path({"a": None}, "a.b") is None


def test_observation_matches_survival_source_filters_code_and_system():
    observation = {
        "code": {"coding": [{"system": "sys", "code": "A"}, {"system": "other", "code": "B"}]}
    }
    assert module._observation_matches_survival_source(observation, {})
    assert module._observation_matches_survival_source(observation, {"code": "A", "system": "sys"})
    assert not module._observation_matches_survival_source(observation, {"code": "A", "system": "other"})


def test_extract_survival_boundary_uses_min_max_and_first():
    patient = {"start": "2026-01-02T00:00:00", "stop": "2026-03-01T00:00:00"}
    conditions = [{"onsetDateTime": "2026-01-01T00:00:00"}]
    window = {
        "start": {
            "sources": [
                {"resource": "Patient", "path": "start", "aggregation": "first"},
                {"resource": "Condition", "path": "onsetDateTime", "aggregation": "min"},
            ]
        },
        "stop": {"resource": "Patient", "path": "stop", "aggregation": "max"},
    }
    start = module._extract_survival_boundary("start", window, patient, conditions, [], [])
    stop = module._extract_survival_boundary("stop", window, patient, conditions, [], [])
    assert start == datetime.fromisoformat("2026-01-02T00:00:00")
    assert stop == datetime.fromisoformat("2026-03-01T00:00:00")


def test_bundle_cache_key_is_stable_for_same_local_bundle():
    a = {"entry": [{"resource": {"resourceType": "Patient", "id": "1"}}]}
    b = {"entry": [{"resource": {"id": "1", "resourceType": "Patient"}}]}

    # Repeated calls for the same parsed bundle must reuse the same cache key,
    # including equivalent int/string project IDs.
    assert module._bundle_cache_key(a, 2) == module._bundle_cache_key(a, "2")

    # Distinct parsed bundle objects intentionally receive distinct identities,
    # even when their FHIR content is equivalent.
    assert module._bundle_cache_key(a, 2) != module._bundle_cache_key(b, 2)

    assert module._bundle_cache_key("https://fhir.example/", 2).endswith("https://fhir.example")


def test_index_local_bundle_resources_groups_resources_by_patient():
    module._LOCAL_BUNDLE_RESOURCE_CACHE.clear()
    bundle = {
        "entry": [
            {"fullUrl": "urn:patient:1", "resource": {"resourceType": "Patient", "id": "1"}},
            {"resource": {"resourceType": "Observation", "id": "o1", "subject": {"reference": "urn:patient:1"}}},
            {"resource": {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/1"}}},
            {
                "resource": {
                    "resourceType": "MedicationStatement",
                    "id": "m1",
                    "subject": {"reference": "Patient/1"},
                    "medicationCodeableConcept": {
                        "coding": [{"system": "rx", "code": "1", "display": "Drug"}]
                    },
                }
            },
            {"resource": {"resourceType": "Group", "id": "g1"}},
        ]
    }
    data = module._index_local_bundle_resources(bundle)
    assert data["patients"]["1"]["id"] == "1"
    assert data["patient_obs"]["1"][0]["id"] == "o1"
    assert data["patient_conditions"]["1"][0]["id"] == "c1"
    assert "Drug" in data["patient_meds"]["1"]["names"]
    assert "1" in data["patient_meds"]["1"]["codes"]
    assert "rx|1" in data["patient_meds"]["1"]["tokens"]
    assert data["groups"][0]["id"] == "g1"


def test_local_patient_query_supports_code_and_deceased_date_filters():
    patient = {
        "resourceType": "Patient",
        "id": "1",
        "gender": "female",
        "birthDate": "1980-06-15",
        "deceasedDateTime": "2024-03-10T12:00:00Z",
    }
    medications = {
        "1": {
            "names": {"Everolimus"},
            "codes": {"j7527"},
            "tokens": {"http://example.test/hcpcs|j7527"},
        }
    }
    conditions = [
        {
            "filter_type": "PATIENT_QUERY",
            "column_name": "medication",
            "operator": "=",
            "value": "J7527",
        },
        {
            "filter_type": "PATIENT_QUERY",
            "column_name": "deceased_date",
            "operator": "BETWEEN",
            "values": ["2024-01-01", "2024-12-31"],
        },
    ]

    assert module._match_local_patient_query(patient, "1", conditions, medications)

    # FHIR token search treats comma-separated values as OR. Local JSON filtering
    # must therefore match the same combined medication value used by General
    # Statistics filters.
    conditions[0]["value"] = "J9299,J7527"
    assert module._match_local_patient_query(patient, "1", conditions, medications)

    conditions[0]["value"] = "J9299,J0000"
    assert not module._match_local_patient_query(patient, "1", conditions, medications)

    conditions[0]["value"] = "J7527"
    conditions[1]["values"] = ["2023-01-01", "2023-12-31"]
    assert not module._match_local_patient_query(patient, "1", conditions, medications)


def test_local_patient_query_accepts_legacy_between_value_csv_shape():
    patient = {
        "resourceType": "Patient",
        "id": "1",
        "birthDate": "1980-06-15",
        "deceasedDateTime": "2024-03-10T12:00:00Z",
    }
    conditions = [
        {
            "filter_type": "PATIENT_QUERY",
            "column_name": "birthDate",
            "operator": "BETWEEN",
            "value": "1970-01-01,1990-12-31",
        },
        {
            "filter_type": "PATIENT_QUERY",
            "column_name": "deceased_date",
            "operator": "BETWEEN",
            "value": "2024-01-01,2024-12-31",
        },
    ]
    assert module._match_local_patient_query(patient, "1", conditions, {})


def test_local_patient_query_uses_same_schema_defaults_as_remote_query(monkeypatch):
    # The remote Patient endpoint path synthesizes birth/death defaults when the
    # stored filter payload contains no PATIENT_QUERY conditions.  Local JSON must
    # not silently become an unfiltered cohort in that situation.
    patient_in_defaults = {
        "resourceType": "Patient",
        "id": "1",
        "birthDate": "1980-06-15",
        "deceasedDateTime": "2024-03-10T12:00:00Z",
    }
    patient_outside_death_default = {
        "resourceType": "Patient",
        "id": "2",
        "birthDate": "1980-06-15",
        "deceasedDateTime": "1999-12-31T12:00:00Z",
    }

    assert module._match_local_patient_query(patient_in_defaults, "1", [], {})
    assert not module._match_local_patient_query(patient_outside_death_default, "2", [], {})
