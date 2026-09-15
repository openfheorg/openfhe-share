from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set, Union

from .fhir_project_config import resolve_project_config_path
from .fhir_value_utils import get_fhir_numeric_value

_ANALYSIS_DATA_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


def load_analysis_data_schema(project_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
    cache_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    cached = _ANALYSIS_DATA_SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    schema_path = resolve_project_config_path(__package__, "analysis_data.json", project_id)
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    if not isinstance(schema, dict):
        raise ValueError(f"Expected analysis data schema JSON object in {schema_path}")

    _ANALYSIS_DATA_SCHEMA_CACHE[cache_key] = schema
    return schema


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _parse_iso_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _patient_age_years(patient: Dict[str, Any]) -> Optional[int]:
    for ext in patient.get("extension") or []:
        if ext.get("url") == "http://fhir.org/guides/hrsa/uds-plus/StructureDefinition/uds-plus-age-extension":
            v = get_fhir_numeric_value(ext)
            if v is not None:
                return int(v)
            break
    bd = _parse_iso_date(patient.get("birthDate"))
    if not bd:
        return None
    today = date.today()
    years = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    return int(years)


def _obs_has_code(obs: Dict[str, Any], target_code_norm: str) -> bool:
    code = obs.get("code")
    codings = (code.get("coding") or []) if isinstance(code, dict) else []
    target = _normalize_key(target_code_norm)
    for cd in codings:
        if _normalize_key(cd.get("code")) == target:
            return True
    return False


def _component_has_code(component: Dict[str, Any], target_code_norm: str) -> bool:
    code = component.get("code")
    codings = (code.get("coding") or []) if isinstance(code, dict) else []
    target = _normalize_key(target_code_norm)
    for cd in codings:
        if _normalize_key(cd.get("code")) == target:
            return True
    return False


def _coding_matches(coding: Dict[str, Any], code: str, system: str = "") -> bool:
    if not isinstance(coding, dict):
        return False
    if _normalize_key(coding.get("code")) != _normalize_key(code):
        return False
    if system and _normalize_key(coding.get("system")) != _normalize_key(system):
        return False
    return True


def _value_codeable_concept_has_coding(value_codeable_concept: Dict[str, Any], code: str, system: str = "") -> bool:
    if not isinstance(value_codeable_concept, dict):
        return False
    for coding in value_codeable_concept.get("coding") or []:
        if _coding_matches(coding, code, system):
            return True
    return False


def _component_value_strings(component: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    value_codeable_concept = component.get("valueCodeableConcept") or {}
    if isinstance(value_codeable_concept, dict):
        text = _normalize_text(value_codeable_concept.get("text"))
        if text:
            out.append(text)
        for coding in value_codeable_concept.get("coding") or []:
            code = _normalize_text(coding.get("code"))
            display = _normalize_text(coding.get("display"))
            if code:
                out.append(code)
            if display:
                out.append(display)

    value_string = _normalize_text(component.get("valueString"))
    if value_string:
        out.append(value_string)

    return out


def _extract_patient_gender(patient: Dict[str, Any]) -> Optional[str]:
    gender = patient.get("gender")
    if isinstance(gender, str) and gender.strip():
        return gender.strip().upper()
    return None


def _extract_observation_value_string_by_code(
    observations: List[Dict[str, Any]],
    args: Dict[str, Any],
) -> Optional[str]:
    code = _normalize_text(args.get("code"))
    allowed_values = {
        _normalize_text(v).upper()
        for v in (args.get("allowedValues") or [])
        if _normalize_text(v)
    }

    for obs in observations or []:
        if not _obs_has_code(obs, code):
            continue

        value_string = _normalize_text(obs.get("valueString"))
        if value_string:
            value = value_string.upper()
            if not allowed_values or value in allowed_values:
                return value

        value_codeable_concept = obs.get("valueCodeableConcept") or {}
        if isinstance(value_codeable_concept, dict):
            text = _normalize_text(value_codeable_concept.get("text"))
            if text:
                value = text.upper()
                if not allowed_values or value in allowed_values:
                    return value
            for coding in value_codeable_concept.get("coding") or []:
                candidate = _normalize_text(coding.get("code")) or _normalize_text(coding.get("display"))
                if candidate:
                    value = candidate.upper()
                    if not allowed_values or value in allowed_values:
                        return value

    return None


def _extract_observation_value_numeric_by_code(
    observations: List[Dict[str, Any]],
    args: Dict[str, Any],
) -> Optional[float]:
    code = _normalize_text(args.get("code"))

    for obs in observations or []:
        if not _obs_has_code(obs, code):
            continue

        numeric_value = get_fhir_numeric_value(obs, primitive_keys=("valueInteger", "valueDecimal"))
        if numeric_value is not None:
            return numeric_value

        value_string = _normalize_text(obs.get("valueString"))
        if value_string:
            try:
                return float(value_string)
            except Exception:
                pass

    return None


def _extract_observation_component_quantity_by_parent_code_and_component_code(
    observations: List[Dict[str, Any]],
    args: Dict[str, Any],
) -> Optional[float]:
    parent_code = _normalize_text(args.get("parentCode"))
    component_code = _normalize_text(args.get("componentCode"))

    for obs in observations or []:
        if not _obs_has_code(obs, parent_code):
            continue

        for component in obs.get("component") or []:
            if not _component_has_code(component, component_code):
                continue
            numeric_value = get_fhir_numeric_value(component)
            if numeric_value is not None:
                return numeric_value

    return None


def _normalize_variant_value(candidate: Any) -> Optional[str]:
    value = _normalize_text(candidate).upper()
    if not value:
        return None

    if value in {"MUT", "WT"}:
        return value

    if value in {"LA26329-5", "SEQUENCE ALTERATION", "POS", "POSITIVE"}:
        return "MUT"

    if value in {"LA9658-1", "WILD TYPE", "N", "NORMAL"}:
        return "WT"

    return None


def _extract_observation_variant_value_by_parent_code_and_gene_code(
    observations: List[Dict[str, Any]],
    args: Dict[str, Any],
) -> Optional[str]:
    parent_code = _normalize_text(args.get("parentCode"))
    gene_component_code = _normalize_text(args.get("geneComponentCode"))
    gene_code_system = _normalize_text(args.get("geneCodeSystem"))
    gene_code = _normalize_text(args.get("geneCode"))
    value_component_code = _normalize_text(args.get("valueComponentCode") or "LL4033-8")
    allowed_values = {
        _normalize_text(v).upper()
        for v in (args.get("allowedValues") or [])
        if _normalize_text(v)
    }

    if not parent_code or not gene_component_code or not gene_code:
        return None

    for obs in observations or []:
        if not _obs_has_code(obs, parent_code):
            continue

        gene_match = False
        for component in obs.get("component") or []:
            if not _component_has_code(component, gene_component_code):
                continue
            value_codeable_concept = component.get("valueCodeableConcept") or {}
            if _value_codeable_concept_has_coding(value_codeable_concept, gene_code, gene_code_system):
                gene_match = True
                break

        if not gene_match:
            continue

        for component in obs.get("component") or []:
            if not _component_has_code(component, value_component_code):
                continue
            for candidate in _component_value_strings(component):
                value = _normalize_variant_value(candidate)
                if value and (not allowed_values or value in allowed_values):
                    return value

        for interpretation in obs.get("interpretation") or []:
            coding_list = (interpretation.get("coding") or []) if isinstance(interpretation, dict) else []
            for coding in coding_list:
                for candidate in (coding.get("code"), coding.get("display")):
                    value = _normalize_variant_value(candidate)
                    if value and (not allowed_values or value in allowed_values):
                        return value

        value_string = _normalize_text(obs.get("valueString"))
        value = _normalize_variant_value(value_string)
        if value and (not allowed_values or value in allowed_values):
            return value

        value_codeable_concept = obs.get("valueCodeableConcept") or {}
        if isinstance(value_codeable_concept, dict):
            text = _normalize_text(value_codeable_concept.get("text"))
            value = _normalize_variant_value(text)
            if value and (not allowed_values or value in allowed_values):
                return value
            for coding in value_codeable_concept.get("coding") or []:
                for candidate in (coding.get("code"), coding.get("display")):
                    value = _normalize_variant_value(candidate)
                    if value and (not allowed_values or value in allowed_values):
                        return value

    return None


def _extract_medication_names(medications: Dict[str, Set[str]]) -> List[str]:
    names = [n for n in (medications or {}).get("names") or [] if _normalize_text(n)]
    return sorted(set(names))


def _get_column_rule(
    computation_type: str,
    property_key: str,
    column_id: str,
    project_id: Optional[Union[int, str]] = None,
) -> Optional[Dict[str, Any]]:
    schema = load_analysis_data_schema(project_id=project_id)
    computations = schema.get("computations") or {}
    comp_block = computations.get(_normalize_text(computation_type)) or {}
    properties = comp_block.get("properties") or {}
    property_block = properties.get(_normalize_text(property_key)) or {}
    columns = property_block.get("columns") or {}
    rule = columns.get(_normalize_key(column_id))
    return rule if isinstance(rule, dict) else None




def get_analysis_resource_requirements(
    computation_type: str,
    workload_args: Dict[str, Any],
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, bool]:
    schema = load_analysis_data_schema(project_id=project_id)
    computations = schema.get("computations") or {}
    comp_block = computations.get(_normalize_text(computation_type)) or {}
    properties = comp_block.get("properties") or {}

    needs_patient = False
    needs_observation = False
    needs_medication = False

    for property_key, property_block in properties.items():
        selected_column = workload_args.get(property_key)
        column_id = _normalize_key(selected_column)
        if not column_id:
            continue
        columns = (property_block or {}).get("columns") or {}
        rule = columns.get(column_id)
        if not isinstance(rule, dict):
            continue
        resource_type = _normalize_text(rule.get("resourceType"))
        if resource_type == "Patient":
            needs_patient = True
        elif resource_type == "Observation":
            needs_observation = True
        elif resource_type == "MedicationStatement":
            needs_medication = True

    return {
        "needs_patient": needs_patient,
        "needs_observation": needs_observation,
        "needs_medication": needs_medication,
    }

def get_analysis_value_for_property(
    computation_type: str,
    property_key: str,
    column_id: str,
    patient: Dict[str, Any],
    observations: List[Dict[str, Any]],
    medications: Optional[Dict[str, Set[str]]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> Any:
    rule = _get_column_rule(computation_type, property_key, column_id, project_id=project_id)
    if not rule:
        return None

    extractor = _normalize_text(rule.get("extractor"))
    args = rule.get("args") or {}

    if extractor == "patient_gender":
        return _extract_patient_gender(patient)

    if extractor == "patient_age_years":
        return _patient_age_years(patient)

    if extractor == "observation_value_string_by_code":
        return _extract_observation_value_string_by_code(observations, args)

    if extractor == "observation_value_numeric_by_code":
        return _extract_observation_value_numeric_by_code(observations, args)

    if extractor == "observation_component_quantity_by_parent_code_and_component_code":
        return _extract_observation_component_quantity_by_parent_code_and_component_code(observations, args)

    if extractor == "observation_variant_value_by_parent_code_and_gene_code":
        return _extract_observation_variant_value_by_parent_code_and_gene_code(observations, args)

    if extractor == "medication_names":
        return _extract_medication_names(medications or {"tokens": set(), "names": set()})

    return None
