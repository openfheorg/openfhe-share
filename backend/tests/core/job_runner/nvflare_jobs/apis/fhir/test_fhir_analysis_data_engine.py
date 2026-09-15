from datetime import date
from unittest.mock import patch

from app.core.job_runner.nvflare_jobs.apis.fhir import fhir_analysis_data_engine as module


def coding(code, system=None):
    value = {"code": code}
    if system:
        value["system"] = system
    return value


def observation(code, **values):
    return {"resourceType": "Observation", "code": {"coding": [coding(code)]}, **values}


def test_normalize_and_parse_helpers():
    assert module._normalize_text(" x ") == "x"
    assert module._normalize_key(" X ") == "x"
    assert module._parse_iso_date("2026-07-18T00:00:00") == date(2026, 7, 18)
    assert module._parse_iso_date("bad") is None


def test_patient_age_prefers_age_extension():
    patient = {
        "birthDate": "1900-01-01",
        "extension": [
            {
                "url": "http://fhir.org/guides/hrsa/uds-plus/StructureDefinition/uds-plus-age-extension",
                "valueInteger": 42,
            }
        ],
    }
    assert module._patient_age_years(patient) == 42


def test_patient_age_uses_birthdate(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 18)

    monkeypatch.setattr(module, "date", FixedDate)
    assert module._patient_age_years({"birthDate": "1984-07-19"}) == 41
    assert module._patient_age_years({}) is None


def test_code_and_coding_match_helpers():
    obs = observation("PBRM1")
    assert module._obs_has_code(obs, "pbrm1")
    assert not module._obs_has_code(obs, "TP53")
    assert module._coding_matches(coding("A", "S"), "a", "s")
    assert module._value_codeable_concept_has_coding({"coding": [coding("A")]}, "a")


def test_component_value_strings_collects_text_codes_displays_and_string():
    component = {
        "valueCodeableConcept": {"text": "Text", "coding": [{"code": "C", "display": "Display"}]},
        "valueString": "String",
    }
    assert module._component_value_strings(component) == ["Text", "C", "Display", "String"]


def test_extract_observation_string_numeric_and_component_quantity():
    observations = [
        observation("GENE", valueString="mut"),
        observation("AGE", valueInteger=44),
        observation(
            "PARENT",
            component=[
                {"code": {"coding": [coding("CHILD")]}, "valueQuantity": {"value": "3.5"}}
            ],
        ),
    ]
    assert module._extract_observation_value_string_by_code(
        observations, {"code": "GENE", "allowedValues": ["MUT", "WT"]}
    ) == "MUT"
    assert module._extract_observation_value_numeric_by_code(observations, {"code": "AGE"}) == 44.0
    assert module._extract_observation_component_quantity_by_parent_code_and_component_code(
        observations, {"parentCode": "PARENT", "componentCode": "CHILD"}
    ) == 3.5


def test_normalize_variant_value_aliases():
    assert module._normalize_variant_value("positive") == "MUT"
    assert module._normalize_variant_value("wild type") == "WT"
    assert module._normalize_variant_value("other") is None


def test_extract_patient_gender_uppercases_value():
    assert module._extract_patient_gender({"gender": " female "}) == "FEMALE"
    assert module._extract_patient_gender({}) is None


def test_project1_public_survivability_gene_columns_use_direct_observations():
    """Public General Statistics JSON bundles store these gene states as direct valueString observations."""
    patient = {"resourceType": "Patient", "id": "RCC-1"}
    observations = [
        observation("PBRM1", valueString="MUT"),
        observation("BAP1", valueString="WT"),
        observation("NF2", valueString="WT"),
        observation("TSC1", valueString="MUT"),
    ]

    for computation_type, property_key in (
        ("kaplan-meier", "group_column_id"),
        ("chi2", "category_column_1_id"),
        ("chi2", "category_column_2_id"),
        ("t-test", "category_column_1_id"),
    ):
        assert module.get_analysis_value_for_property(
            computation_type,
            property_key,
            "PBRM1",
            patient,
            observations,
            project_id=1,
        ) == "MUT"
