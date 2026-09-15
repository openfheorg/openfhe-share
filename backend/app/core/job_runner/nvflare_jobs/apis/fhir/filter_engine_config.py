from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import logging
import threading
import uuid
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union
import re
import pandas as pd

from .fhir_patient_query_engine import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RESOURCE_PAGE_SIZE,
    bundle_entries_from_url,
    chunked,
    normalize_filters,
    parse_iso_date,
    parse_iso_datetime,
    pid_from_ref,
    query_patients,
    resolve_server_url,
    session,
    load_patient_filter_schema,
    resolve_patient_filter_controls,
    condition_values,
)

from .fhir_observation_query_engine import get_cached_observations_by_patient, query_observations_by_patient
from .fhir_observation_data_engine import patient_satisfies_coded_observation_data_filters
from .fhir_analysis_query_engine import fetch_analysis_subject_context
from .fhir_analysis_data_engine import get_analysis_value_for_property
from .fhir_value_utils import get_fhir_numeric_value

_APPLY_FILTERS_CACHE: Dict[Tuple[str, str, str], List[str]] = {}
_LOCAL_BUNDLE_RESOURCE_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCAL_OBSERVATION_CACHE: Dict[Tuple[str, str, str], Dict[str, List[Dict[str, Any]]]] = {}

_CYTO_ID_RE = re.compile(r"-([0-9]{1,2}[pq][0-9]+(?:\.[0-9]+)?)$", re.IGNORECASE)


def _coerce_float_scalar(value: Any, label: str = "value") -> float:
    """Coerce a scalar-like value into a float with a useful error message."""
    if hasattr(value, "to_numpy"):
        arr = value.to_numpy().reshape(-1)
        arr = [v for v in arr if not pd.isna(v)]
        if len(arr) != 1:
            raise ValueError(
                f"{label} must contain exactly one numeric value; found {len(arr)} values"
            )
        value = arr[0]

    while isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError(
                f"{label} must contain exactly one numeric value; found {len(value)} values"
            )
        value = value[0]

    if isinstance(value, str):
        value = value.replace("\ufeff", "").strip()
        if not value:
            raise ValueError(f"{label} cannot be blank")

    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be numeric, got {value!r}") from e


LOINC = "http://loinc.org"
LNC_VARIANT_ASSESSMENT = "69548-6"
LNC_DNA_CHANGE_TYPE = "48019-4"
LNC_GENOMIC_REF_ID = "48013-7"

CANCER_TYPE_DISPLAY_MAP: Dict[str, str] = {
    "non-small cell lung cancer": "Non-small cell lung cancer (disorder)",
    "breast carcinoma": "Carcinoma of breast",
    "glioma": "Glioma (disorder)",
    "colorectal cancer": "Malignant tumor of colon",
    "pancreatic cancer": "Malignant tumor of pancreas",
    "gastrointestinal stromal tumor": "Gastrointestinal stromal tumor",
    "gastrointestinal neuroendocrine tumor": "Neuroendocrine neoplasm of gastrointestinal tract (disorder)",
    "non-hodgkin lymphoma": "Non-Hodgkin lymphoma",
    "bladder cancer": "Malignant tumor of urinary bladder",
    "esophagogastric carcinoma": "Malignant tumor of esophagus",
    "biliary cancer": "Cholangiocarcinoma",
    "melanoma": "Malignant melanoma of skin",
}

CANCER_TYPE_CODE_MAP: Dict[str, Set[str]] = {
    "non-small cell lung cancer": {"254637007"},
    "breast carcinoma": {"254838004"},
    "glioma": {"393564001"},
    "colorectal cancer": {"363406005"},
    "pancreatic cancer": {"363418001"},
    "gastrointestinal stromal tumor": {"420120006"},
    "gastrointestinal neuroendocrine tumor": {"721193002"},
    "non-hodgkin lymphoma": {"1172592001"},
    "bladder cancer": {"399326009"},
    "esophagogastric carcinoma": {"363402007"},
    "biliary cancer": {"70179006"},
    "melanoma": {"93655004"},
}

PCA_LOINC_CODE = "86206-0"
TOTAL_TMB_LOINC_CODE = "94076-7"


# The old engine required a MedicationStatement period. Keep that as the
# compatibility default. A datasource can opt into a different clinically
# approved definition only through its own patient_query.json.
_DEFAULT_BIOMARKER_SURVIVAL_WINDOW: Dict[str, Any] = {
    "start": {
        "resource": "MedicationStatement",
        "path": "effectivePeriod.start",
        "aggregation": "min",
    },
    "stop": {
        "resource": "MedicationStatement",
        "path": "effectivePeriod.end",
        "aggregation": "max",
    },
    "missing_window_behavior": "exclude",
}

_SUPPORTED_SURVIVAL_RESOURCES = {
    "MedicationStatement",
    "Condition",
    "Observation",
    "Patient",
}


def _survival_boundary_sources(window: Dict[str, Any], boundary: str) -> List[Dict[str, Any]]:
    raw_boundary = window.get(boundary)
    if not isinstance(raw_boundary, dict):
        raise ValueError(f"biomarker_survival_window.{boundary} must be an object")

    raw_sources = raw_boundary.get("sources")
    if raw_sources is None:
        raw_sources = [raw_boundary]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError(f"biomarker_survival_window.{boundary}.sources must be a non-empty list")

    sources: List[Dict[str, Any]] = []
    for source in raw_sources:
        if not isinstance(source, dict):
            raise ValueError(f"biomarker_survival_window.{boundary}.sources entries must be objects")
        resource = str(source.get("resource") or "").strip()
        path = str(source.get("path") or "").strip()
        aggregation = str(source.get("aggregation") or ("min" if boundary == "start" else "max")).strip().lower()
        if resource not in _SUPPORTED_SURVIVAL_RESOURCES:
            raise ValueError(
                f"biomarker_survival_window.{boundary} has unsupported resource {resource!r}; "
                f"expected one of {sorted(_SUPPORTED_SURVIVAL_RESOURCES)}"
            )
        if not path:
            raise ValueError(f"biomarker_survival_window.{boundary} requires a non-empty path")
        if aggregation not in {"min", "max", "first"}:
            raise ValueError(
                f"biomarker_survival_window.{boundary} has unsupported aggregation {aggregation!r}"
            )
        normalized = dict(source)
        normalized["resource"] = resource
        normalized["path"] = path
        normalized["aggregation"] = aggregation
        sources.append(normalized)
    return sources


def _load_biomarker_survival_window(
    project_id: Optional[Union[int, str]],
    datasource_group_id: Optional[Union[int, str]],
) -> Dict[str, Any]:
    schema = load_patient_filter_schema(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    configured = schema.get("biomarker_survival_window")
    window = configured if isinstance(configured, dict) else _DEFAULT_BIOMARKER_SURVIVAL_WINDOW

    # Validate at load time so an incomplete datasource contract cannot silently
    # change cohort eligibility at runtime.
    _survival_boundary_sources(window, "start")
    _survival_boundary_sources(window, "stop")
    missing_window_behavior = str(window.get("missing_window_behavior") or "exclude").strip().lower()
    if missing_window_behavior not in {"exclude", "censor_at_latest_deceased_or_today"}:
        raise ValueError(
            "Unsupported biomarker_survival_window.missing_window_behavior "
            f"{missing_window_behavior!r}; expected 'exclude' or "
            "'censor_at_latest_deceased_or_today'."
        )
    return window


def _load_biomarker_resource_linkage(
    project_id: Optional[Union[int, str]],
    datasource_group_id: Optional[Union[int, str]],
) -> Optional[Dict[str, Any]]:
    """Load an optional datasource-defined biomarker resource linkage contract.

    Datasources without this block retain the historical patient-scoped behavior.
    The currently supported contract anchors biomarker data to one or more matching
    Condition resources and selects related Observations through a configured FHIR
    reference path (for example ``focus.reference``).
    """
    schema = load_patient_filter_schema(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    configured = schema.get("biomarker_resource_linkage")
    if configured is None:
        return None
    if not isinstance(configured, dict):
        raise ValueError("biomarker_resource_linkage must be an object")

    scope = str(configured.get("scope") or "").strip().lower()
    if scope != "condition":
        raise ValueError(
            "Unsupported biomarker_resource_linkage.scope "
            f"{scope!r}; currently expected 'condition'."
        )

    anchor = configured.get("anchor")
    if not isinstance(anchor, dict):
        raise ValueError("biomarker_resource_linkage.anchor must be an object")
    anchor_resource = str(anchor.get("resource") or "").strip()
    if anchor_resource != "Condition":
        raise ValueError(
            "biomarker_resource_linkage.anchor.resource must currently be 'Condition'"
        )
    match_control = str(anchor.get("match_control") or "").strip()
    if match_control != "cancer_type":
        raise ValueError(
            "biomarker_resource_linkage.anchor.match_control must currently be 'cancer_type'"
        )

    related = configured.get("related_resources")
    if not isinstance(related, dict):
        raise ValueError("biomarker_resource_linkage.related_resources must be an object")
    observation_cfg = related.get("Observation")
    if not isinstance(observation_cfg, dict):
        raise ValueError(
            "biomarker_resource_linkage.related_resources.Observation must be an object"
        )
    reference_path = str(observation_cfg.get("reference_path") or "").strip()
    if not reference_path:
        raise ValueError(
            "biomarker_resource_linkage.related_resources.Observation.reference_path "
            "must be non-empty"
        )

    normalized = dict(configured)
    normalized["scope"] = scope
    normalized["anchor"] = dict(anchor)
    normalized["anchor"]["resource"] = anchor_resource
    normalized["anchor"]["match_control"] = match_control
    normalized["related_resources"] = dict(related)
    normalized["related_resources"]["Observation"] = dict(observation_cfg)
    normalized["related_resources"]["Observation"]["reference_path"] = reference_path
    normalized["related_resources"]["Observation"]["required"] = bool(
        observation_cfg.get("required", False)
    )
    return normalized


def _read_resource_path(resource: Dict[str, Any], path: str) -> Any:
    value: Any = resource
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _read_resource_path_values(resource: Dict[str, Any], path: str) -> List[Any]:
    """Read a dotted FHIR path while transparently traversing arrays.

    This is intentionally small rather than a full FHIRPath evaluator. It supports
    config paths such as ``focus.reference`` where ``focus`` is a FHIR array.
    """
    values: List[Any] = [resource]
    for part in path.split("."):
        next_values: List[Any] = []
        for value in values:
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                child = candidate.get(part)
                if isinstance(child, list):
                    next_values.extend(child)
                elif child is not None:
                    next_values.append(child)
        values = next_values
        if not values:
            break
    return values


def _canonical_fhir_reference(reference: Any) -> str:
    """Normalize relative/absolute FHIR references to ``Resource/id`` when possible."""
    ref = str(reference or "").strip()
    if not ref:
        return ""
    ref = ref.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    parts = [part for part in ref.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return ref


def _observation_matches_survival_source(observation: Dict[str, Any], source: Dict[str, Any]) -> bool:
    code = str(source.get("code") or "").strip()
    system = str(source.get("system") or "").strip()
    if not code:
        return True
    for coding in ((observation.get("code") or {}).get("coding") or []):
        if str(coding.get("code") or "").strip() != code:
            continue
        if system and str(coding.get("system") or "").strip() != system:
            continue
        return True
    return False


def _survival_source_resources(
    source: Dict[str, Any],
    patient: Dict[str, Any],
    conds: List[Dict[str, Any]],
    meds: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    resource = source["resource"]
    if resource == "Patient":
        return [patient]
    if resource == "MedicationStatement":
        return meds
    if resource == "Condition":
        return conds
    if resource == "Observation":
        return [obs for obs in observations if _observation_matches_survival_source(obs, source)]
    return []


def _extract_survival_boundary(
    boundary: str,
    window: Dict[str, Any],
    patient: Dict[str, Any],
    conds: List[Dict[str, Any]],
    meds: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
) -> Optional[datetime]:
    for source in _survival_boundary_sources(window, boundary):
        values = [
            parsed
            for resource in _survival_source_resources(source, patient, conds, meds, observations)
            for parsed in [parse_iso_datetime(_read_resource_path(resource, source["path"]))]
            if parsed is not None
        ]
        if not values:
            continue
        aggregation = source["aggregation"]
        if aggregation == "min":
            return min(values)
        if aggregation == "max":
            return max(values)
        return values[0]
    return None


def _default_censor_datetime_for_window(
    window: Dict[str, Any],
    patients: Dict[str, Dict[str, Any]],
) -> Optional[datetime]:
    """Resolve a datasource's site-level censor date from its declared death fields.

    Group 3 has diagnosis dates and death dates, but not treatment periods. For
    living subjects, preserve the branch's intended behavior: censor at the
    latest death represented by that datasource/site; if there are no death
    dates at all, use today. This is activated only by an explicit datasource
    configuration, never as a generic medication fallback.
    """
    behavior = str(window.get("missing_window_behavior") or "exclude").strip().lower()
    if behavior != "censor_at_latest_deceased_or_today":
        return None

    death_values: List[datetime] = []
    for source in _survival_boundary_sources(window, "stop"):
        if source.get("resource") != "Patient":
            continue
        for patient in (patients or {}).values():
            parsed = parse_iso_datetime(_read_resource_path(patient, source["path"]))
            if parsed is not None:
                death_values.append(parsed)

    if death_values:
        return max(death_values)
    return datetime.combine(date.today(), datetime.min.time())


def _resolve_configured_survival_window(
    window: Dict[str, Any],
    patient: Dict[str, Any],
    conds: List[Dict[str, Any]],
    meds: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    default_censor_datetime: Optional[datetime] = None,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    start = _extract_survival_boundary("start", window, patient, conds, meds, observations)
    stop = _extract_survival_boundary("stop", window, patient, conds, meds, observations)

    behavior = str(window.get("missing_window_behavior") or "exclude").strip().lower()
    if stop is None and start is not None and behavior == "censor_at_latest_deceased_or_today":
        stop = default_censor_datetime

    stop = _normalize_datetime_timezone(stop, start)
    return start, stop


@dataclass(frozen=True)
class BiomarkerSubject:
    subject_id: str
    panel_version: Optional[str]
    cancer_type_display: Optional[str]
    cancer_type_code: Optional[str]
    gender: Optional[str]
    age: Optional[int]
    tstart_seq: Optional[datetime]
    tstop_seq: Optional[datetime]
    tstart_trt: Optional[datetime]
    tstop_trt: Optional[datetime]
    event: Optional[int]
    pcs: Dict[str, float]
    total_mutation_burden: Optional[float]
    gene_features: Dict[str, float]


def _is_local_bundle(bundle: Dict[str, Any] | str) -> bool:
    return isinstance(bundle, dict) and isinstance(bundle.get("entry"), list)


# Identity used for the bundle-keyed caches below. Deriving it from CONTENT means
# json.dumps-ing the whole bundle -- ~250 ms on a 48 MB one -- on EVERY apply_filters and
# every resource-index build, which costs far more than the caches it keys can ever save.
# A bundle is parsed once (utils._load_stat_data_source caches it by path) and then treated
# as read-only, so a one-off stamp is a sound identity and reduces the key to a dict lookup.
#
# NOT id(): CPython reuses a freed dict's address, and its entry list's, essentially every
# time at these sizes -- measured 99-100% reuse for bundles of 5k+ entries -- so an
# id()-based key would silently collide across two different bundles.
_BUNDLE_IDENTITY_FIELD = "__duality_bundle_identity__"


def _local_bundle_identity(bundle: Dict[str, Any]) -> str:
    """Stable per-object id for a parsed local bundle, stamped on first use.

    Falls back to hashing the content when the mapping cannot be stamped, so an unusual
    caller stays correct (just slow) rather than sharing another bundle's key.
    """
    stamped = bundle.get(_BUNDLE_IDENTITY_FIELD)
    if isinstance(stamped, str) and stamped:
        return stamped
    try:
        # setdefault so two threads stamping at once still agree on one value.
        return bundle.setdefault(_BUNDLE_IDENTITY_FIELD, uuid.uuid4().hex)
    except Exception:
        try:
            payload = json.dumps(bundle, sort_keys=True, default=str)
        except Exception:
            payload = str(bundle)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bundle_cache_key(
    bundle: Dict[str, Any] | str,
    project_id: Optional[Union[int, str]] = None,
) -> str:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    if _is_local_bundle(bundle):
        return f"{project_key}||local||{_local_bundle_identity(bundle)}"
    server_url = resolve_server_url(bundle)
    return f"{project_key}||server||{server_url}"


def _index_local_bundle_resources(
    bundle: Dict[str, Any],
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    cache_key = _bundle_cache_key(bundle, project_id=project_id)
    cached = _LOCAL_BUNDLE_RESOURCE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    patients: Dict[str, Dict[str, Any]] = {}
    patient_obs: Dict[str, List[Dict[str, Any]]] = {}
    patient_conditions: Dict[str, List[Dict[str, Any]]] = {}
    patient_meds: Dict[str, Dict[str, Set[str]]] = {}
    patient_med_statements: Dict[str, List[Dict[str, Any]]] = {}
    ref_to_pid: Dict[str, str] = {}
    groups: List[Dict[str, Any]] = []

    for entry in bundle.get("entry", []) or []:
        res = entry.get("resource") or {}
        if res.get("resourceType") != "Patient":
            continue
        pid = str(res.get("id") or "").strip()
        if not pid:
            continue
        patients[pid] = res
        patient_obs.setdefault(pid, [])
        patient_conditions.setdefault(pid, [])
        patient_med_statements.setdefault(pid, [])
        patient_meds.setdefault(pid, {"tokens": set(), "codes": set(), "names": set()})
        ref_to_pid[f"Patient/{pid}"] = pid
        full_url = entry.get("fullUrl")
        if isinstance(full_url, str) and full_url.strip():
            ref_to_pid[full_url.strip()] = pid

    for entry in bundle.get("entry", []) or []:
        res = entry.get("resource") or {}
        rt = res.get("resourceType")

        if rt == "Observation":
            pid = ref_to_pid.get(((res.get("subject") or {}).get("reference")) or "")
            if pid in patient_obs:
                patient_obs[pid].append(res)
            continue

        if rt == "Condition":
            pid = ref_to_pid.get(((res.get("subject") or {}).get("reference")) or "")
            if pid in patient_conditions:
                patient_conditions[pid].append(res)
            continue

        if rt == "MedicationStatement":
            pid = ref_to_pid.get(((res.get("subject") or {}).get("reference")) or "")
            if pid in patient_med_statements:
                patient_med_statements[pid].append(res)

                cc = res.get("medicationCodeableConcept") or {}
                for cd in (cc.get("coding") or []):
                    disp = str(cd.get("display") or "").strip()
                    if disp:
                        patient_meds[pid]["names"].add(disp)
                    system = str(cd.get("system") or "").strip()
                    code = str(cd.get("code") or "").strip()
                    if code:
                        patient_meds[pid]["codes"].add(code.lower())
                    if system and code:
                        patient_meds[pid]["tokens"].add(f"{system}|{code}".lower())
            continue

        if rt == "Group":
            groups.append(res)

    data = {
        "patients": patients,
        "patient_obs": patient_obs,
        "patient_conditions": patient_conditions,
        "patient_meds": patient_meds,
        "patient_med_statements": patient_med_statements,
        "ref_to_pid": ref_to_pid,
        "groups": groups,
    }
    _LOCAL_BUNDLE_RESOURCE_CACHE[cache_key] = data
    return data


def _build_local_observation_cache_key(
    bundle: Dict[str, Any],
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Tuple[str, str, str]:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    bundle_key = _bundle_cache_key(bundle, project_id=project_id)
    wanted = sorted({str(pid).strip() for pid in subject_ids if str(pid).strip()})
    signature = json.dumps(wanted, separators=(",", ":"))
    return project_key, bundle_key, hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _get_cached_local_observation_subset(
    bundle: Dict[str, Any],
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    bundle_key = _bundle_cache_key(bundle, project_id=project_id)
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    wanted_set = set(wanted)
    for (cached_project_key, cached_bundle_key, _), cached_map in list(_LOCAL_OBSERVATION_CACHE.items()):
        if cached_project_key != project_key or cached_bundle_key != bundle_key:
            continue
        if wanted_set.issubset(set(cached_map.keys())):
            return {pid: list(cached_map.get(pid, [])) for pid in wanted}

    return None


def _get_cached_local_observations_by_patient(
    bundle: Dict[str, Any],
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    cache_key = _build_local_observation_cache_key(bundle, wanted, project_id=project_id)
    cached = _LOCAL_OBSERVATION_CACHE.get(cache_key)
    if cached is not None:
        return {pid: list(cached.get(pid, [])) for pid in wanted}

    subset_cached = _get_cached_local_observation_subset(bundle, wanted, project_id=project_id)
    if subset_cached is not None:
        return subset_cached

    indexed = _index_local_bundle_resources(bundle, project_id=project_id)
    patient_obs = indexed["patient_obs"]
    result = {pid: list(patient_obs.get(pid, [])) for pid in wanted}
    _LOCAL_OBSERVATION_CACHE[cache_key] = {pid: list(obs) for pid, obs in result.items()}
    return result


def _build_cancer_type_maps(
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    schema = load_patient_filter_schema(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    controls = schema.get("controls") or []
    options = []
    for control in controls:
        if not isinstance(control, dict):
            continue
        if str(control.get("id") or "").strip() == "cancer_type":
            options = control.get("options") or []
            break

    by_code: Dict[str, str] = {}
    by_label: Dict[str, str] = {}

    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or option.get("value") or "").strip()
        value = str(option.get("value") or option.get("label") or "").strip()
        code = str(option.get("code") or "").strip()
        canonical = value or label
        if not canonical:
            continue
        if code:
            by_code[code] = canonical
        if label:
            by_label[label.lower()] = canonical
        if value:
            by_label[value.lower()] = canonical

    return by_code, by_label


def _resolve_cancer_type_value(
    condition_resource: Dict[str, Any],
    by_code: Dict[str, str],
    by_label: Dict[str, str],
) -> str:
    codings = ((condition_resource.get("code") or {}).get("coding") or []) if isinstance((condition_resource.get("code") or {}), dict) else []
    for cd in codings:
        code = str(cd.get("code") or "").strip()
        display = str(cd.get("display") or "").strip()
        if code and code in by_code:
            return by_code[code]
        if display and display.lower() in by_label:
            return by_label[display.lower()]
    text = str(((condition_resource.get("code") or {}).get("text")) or "").strip()
    if text and text.lower() in by_label:
        return by_label[text.lower()]
    return ""


def _condition_matches_cancer_type(
    condition_resource: Dict[str, Any],
    desired: str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> bool:
    desired = str(desired or "").strip()
    if not desired:
        return False

    desired_norm = desired.lower()
    by_code, by_label = _build_cancer_type_maps(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )

    desired_codes = set(CANCER_TYPE_CODE_MAP.get(desired_norm) or set())
    if desired_norm.isdigit():
        desired_codes.add(desired_norm)
    for code, canonical in by_code.items():
        if str(canonical or "").strip().lower() == desired_norm:
            desired_codes.add(str(code).strip())

    desired_displays = {desired_norm}
    lookup_display = CANCER_TYPE_DISPLAY_MAP.get(desired_norm)
    if lookup_display:
        desired_displays.add(lookup_display.strip().lower())
    mapped_label = by_label.get(desired_norm)
    if mapped_label:
        desired_displays.add(mapped_label.strip().lower())
    for label, canonical in by_label.items():
        if str(canonical or "").strip().lower() == desired_norm:
            desired_displays.add(str(label or "").strip().lower())

    resolved = _resolve_cancer_type_value(condition_resource, by_code, by_label)
    if resolved and resolved.strip().lower() == desired_norm:
        return True

    codeable = condition_resource.get("code") or {}
    codings = (codeable.get("coding") or []) if isinstance(codeable, dict) else []
    for cd in codings:
        code = str(cd.get("code") or "").strip()
        display = str(cd.get("display") or "").strip().lower()
        if code and code in desired_codes:
            return True
        if display and display in desired_displays:
            return True

    text = str(codeable.get("text") or "").strip().lower() if isinstance(codeable, dict) else ""
    return bool(text and text in desired_displays)


def _matching_conditions_for_cancer_type(
    conditions: Iterable[Dict[str, Any]],
    desired: str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> List[Dict[str, Any]]:
    """Return the Conditions that satisfy the datasource's cancer-type semantics.

    This is the shared matcher used by both patient filtering and condition-scoped
    biomarker extraction so those two stages cannot drift apart.
    """
    desired = str(desired or "").strip()
    if not desired:
        return []
    return [
        condition
        for condition in (conditions or [])
        if _condition_matches_cancer_type(
            condition,
            desired,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        )
    ]


def _scope_biomarker_resources_for_patient(
    pid: str,
    conds: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    linkage: Optional[Dict[str, Any]],
    cancer_type: Optional[str],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply a datasource-defined biomarker linkage contract to one patient."""
    if linkage is None:
        return list(conds or []), list(observations or [])

    desired = str(cancer_type or "").strip()
    if desired:
        scoped_conds = _matching_conditions_for_cancer_type(
            conds,
            desired,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        )
    else:
        # A single Condition is unambiguous. Multiple Conditions cannot safely be
        # collapsed once a datasource declares Condition-scoped biomarker linkage.
        if len(conds or []) > 1:
            raise ValueError(
                "Datasource requires condition-scoped biomarker linkage, but no cancer_type "
                f"was supplied for patient {pid!r} with {len(conds or [])} Conditions."
            )
        scoped_conds = list(conds or [])

    if not scoped_conds:
        return [], []

    anchor_refs = {
        _canonical_fhir_reference(f"Condition/{condition.get('id')}")
        for condition in scoped_conds
        if str(condition.get("id") or "").strip()
    }
    observation_cfg = linkage["related_resources"]["Observation"]
    reference_path = observation_cfg["reference_path"]
    scoped_observations: List[Dict[str, Any]] = []
    for observation in observations or []:
        refs = {
            _canonical_fhir_reference(value)
            for value in _read_resource_path_values(observation, reference_path)
            if _canonical_fhir_reference(value)
        }
        # A focused Observation belongs only to the Condition(s) it references.
        # Unfocused Observations are retained as patient-level/shared context for
        # backward compatibility with older bundles and resources such as PCA
        # observations that may not be sample-scoped.
        if not refs or refs.intersection(anchor_refs):
            scoped_observations.append(observation)

    if observation_cfg.get("required") and not scoped_observations:
        return scoped_conds, []
    return scoped_conds, scoped_observations


def _patient_data_matches_cancer_type(
    pid: str,
    cond: Dict[str, Any],
    patient_conditions: Dict[str, List[Dict[str, Any]]],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> bool:
    """True if this patient's Conditions satisfy a PATIENT_DATA cancer_type filter.

    Uses the same Condition matcher as condition-scoped biomarker extraction so
    filtering and downstream feature construction agree on the selected cancer.
    """
    raw_val = cond.get("value")
    if isinstance(raw_val, list):
        raw_val = raw_val[0] if raw_val else None
    desired = str(raw_val or "").strip()
    if not desired:
        return False

    return bool(
        _matching_conditions_for_cancer_type(
            patient_conditions.get(pid, []) or [],
            desired,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        )
    )


def _match_local_patient_query(
    patient: Dict[str, Any],
    pid: str,
    filters: Any,
    patient_meds: Dict[str, Dict[str, Set[str]]],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> bool:
    """Evaluate Patient-query controls against an in-memory FHIR bundle.

    Important compatibility rule: this uses the same ``patient_query.json`` control
    resolution as the HAPI Patient endpoint path.  The filter payload is first
    matched back to a control through its save-target triple, then that control's
    query semantics are applied locally.  This keeps current config-driven filter
    payloads and older DB-staged payloads compatible with local JSON traversal.
    """
    resolved = resolve_patient_filter_controls(
        filters,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        include_defaults=True,
    )

    for control, cond in resolved:
        query = control.get("query") or {}
        kind = str(query.get("kind") or "").strip()
        param = str(query.get("param") or "").strip()
        control_id = str(control.get("id") or "").strip()

        if kind == "search-param":
            raw_val = cond.get("value")
            desired = str(raw_val or "").strip().lower()
            if not desired:
                continue

            # project_1 currently uses the Patient.gender search parameter.  Use
            # the FHIR query param, rather than the saved column name, as the
            # semantic key so config/storage naming changes do not break traversal.
            if param == "gender":
                if str(patient.get("gender") or "").strip().lower() != desired:
                    return False
            continue

        if kind == "date-range":
            vals = condition_values(cond)
            if len(vals) < 2:
                return False
            lo = parse_iso_date(vals[0]) if vals[0] else None
            hi = parse_iso_date(vals[1]) if vals[1] else None

            if param == "birthdate" or control_id == "birthDate":
                actual = parse_iso_date(patient.get("birthDate"))
            elif param == "death-date" or control_id == "death-date":
                actual = parse_iso_date(patient.get("deceasedDateTime") or patient.get("deceasedDate"))
            else:
                # Same compatibility stance as the remote serializer: an unknown
                # control that cannot produce a supported Patient query is ignored.
                continue

            if not actual or (lo and actual < lo) or (hi and actual > hi):
                return False
            continue

        if kind == "reverse-chain-token":
            resource = str(query.get("resource") or "").strip()
            reference_param = str(query.get("referenceParam") or "").strip()
            token_param = str(query.get("param") or "").strip()
            if resource != "MedicationStatement" or reference_param != "subject" or token_param != "code":
                continue

            # HAPI token search interprets commas as OR.  Preserve that behavior
            # locally (J7527,J9299 => Everolimus OR Nivolumab).
            raw_values = [
                value.strip().lower()
                for value in str(cond.get("value") or "").split(",")
                if value.strip()
            ]
            if not raw_values:
                return False
            meds = patient_meds.get(pid) or {"names": set(), "codes": set(), "tokens": set()}
            names = {str(v).strip().lower() for v in meds.get("names") or set()}
            codes = {str(v).strip().lower() for v in meds.get("codes") or set()}
            tokens = {str(v).strip().lower() for v in meds.get("tokens") or set()}
            if not any(value in names or value in codes or value in tokens for value in raw_values):
                return False
            continue

    return True


def _match_local_patient_data(
    patient: Dict[str, Any],
    pid: str,
    conds: List[Dict[str, Any]],
    patient_conditions: Dict[str, List[Dict[str, Any]]],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> bool:
    for cond in conds or []:
        col = str(cond.get("column_name") or "").strip()

        if col == "deceased_date":
            vals = cond.get("values")
            if not isinstance(vals, list) or len(vals) != 2:
                return False
            deceased = patient.get("deceasedDateTime") or patient.get("deceasedDate")
            d = parse_iso_date(deceased)
            lo = parse_iso_date(vals[0]) if vals[0] else None
            hi = parse_iso_date(vals[1]) if vals[1] else None
            if not d or (lo and d < lo) or (hi and d > hi):
                return False
            continue

        if col == "cancer_type":
            if not _patient_data_matches_cancer_type(
                pid,
                cond,
                patient_conditions,
                project_id=project_id,
                datasource_group_id=datasource_group_id,
            ):
                return False
            continue

    return True
def _count_type(flist: List[Dict[str, Any]], t: str) -> int:
    T = t.upper()
    return sum(1 for c in flist if (c.get("filter_type") or "").upper() == T)


def _parse_regions(cond: Dict[str, Any]) -> Set[str]:
    vals = cond.get("values")
    if isinstance(vals, list) and vals:
        return {s for v in vals if v is not None and (s := str(v).strip())}
    val = cond.get("value", "")
    if isinstance(val, str) and val:
        return {s for part in val.split(",") if (s := part.strip())}
    return set()


def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(int(v))
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _coerce_category(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, list):
        if not v:
            return None
        v = v[0]
    s = str(v).strip()
    if not s:
        return None
    return s.upper()


def _fetch_patients_by_ids(sess, server_url: str, subject_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in chunked(subject_ids, DEFAULT_BATCH_SIZE):
        params = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)), ("_id", ",".join(chunk))]
        out.extend(bundle_entries_from_url(sess, f"{server_url}/Patient", params=params))
    return out


def _fetch_conditions_by_subject_ids(sess, server_url: str, subject_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    refs = [f"Patient/{sid}" for sid in subject_ids if str(sid).strip()]
    for chunk in chunked(refs, DEFAULT_BATCH_SIZE):
        params = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)), ("subject", ",".join(chunk))]
        out.extend(bundle_entries_from_url(sess, f"{server_url}/Condition", params=params))
    return out


def _fetch_medication_statements_by_subject_ids(sess, server_url: str, subject_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    refs = [f"Patient/{sid}" for sid in subject_ids if str(sid).strip()]
    for chunk in chunked(refs, DEFAULT_BATCH_SIZE):
        params = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)), ("subject", ",".join(chunk))]
        out.extend(bundle_entries_from_url(sess, f"{server_url}/MedicationStatement", params=params))
    return out


def _fetch_observations_by_subject_ids(sess, server_url: str, subject_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    refs = [f"Patient/{sid}" for sid in subject_ids if str(sid).strip()]
    for chunk in chunked(refs, DEFAULT_BATCH_SIZE):
        params = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)), ("subject", ",".join(chunk))]
        out.extend(bundle_entries_from_url(sess, f"{server_url}/Observation", params=params))
    return out


def _fetch_conditions_index_for_subject_ids(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
) -> Dict[str, List[Dict[str, Any]]]:
    patient_conditions: Dict[str, List[Dict[str, Any]]] = {
        str(pid).strip(): [] for pid in subject_ids if str(pid).strip()
    }
    conds_raw = _fetch_conditions_by_subject_ids(sess, server_url, patient_conditions.keys())
    for res in conds_raw:
        if res.get("resourceType") != "Condition":
            continue
        subj = (res.get("subject") or {}).get("reference", "")
        pid = pid_from_ref(subj)
        if pid in patient_conditions:
            patient_conditions[pid].append(res)
    return patient_conditions


def _fetch_observation_index_for_subject_ids(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
) -> Dict[str, List[Dict[str, Any]]]:
    patient_obs: Dict[str, List[Dict[str, Any]]] = {
        str(pid).strip(): [] for pid in subject_ids if str(pid).strip()
    }
    obs_raw = _fetch_observations_by_subject_ids(sess, server_url, patient_obs.keys())
    for res in obs_raw:
        if res.get("resourceType") != "Observation":
            continue
        subj = (res.get("subject") or {}).get("reference", "")
        pid = pid_from_ref(subj)
        if pid in patient_obs:
            patient_obs[pid].append(res)
    return patient_obs


def _fetch_groups(sess, server_url: str) -> List[Dict[str, Any]]:
    return bundle_entries_from_url(sess, f"{server_url}/Group", params=[("_count", str(DEFAULT_RESOURCE_PAGE_SIZE))])


def _patient_age_years(patient: Dict[str, Any]) -> Optional[int]:
    for ext in patient.get("extension") or []:
        if ext.get("url") == "http://fhir.org/guides/hrsa/uds-plus/StructureDefinition/uds-plus-age-extension":
            v = get_fhir_numeric_value(ext)
            if v is not None:
                return int(v)
            break
    bd = parse_iso_date(patient.get("birthDate"))
    if not bd:
        return None
    today = date.today()
    years = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    return int(years)


def _patient_event_flag(patient: Dict[str, Any]) -> Optional[int]:
    if patient.get("deceasedBoolean") is True:
        return 1
    if patient.get("deceasedDateTime") or patient.get("deceasedDate"):
        return 1
    if patient.get("deceasedBoolean") is False:
        return 0
    return 0


def _obs_has_loinc_code(obs: Dict[str, Any], code: str) -> bool:
    codings = ((obs.get("code") or {}).get("coding") or []) if isinstance(obs.get("code"), dict) else []
    for cd in codings:
        if (cd.get("system") or "").strip() == LOINC and (cd.get("code") or "").strip() == code:
            return True
    return False


def _obs_component_value(obs: Dict[str, Any], text: str) -> Optional[float]:
    for comp in obs.get("component") or []:
        ctext = (((comp.get("code") or {}).get("text")) or "")
        if str(ctext).strip() != text:
            continue
        v = get_fhir_numeric_value(comp)
        if v is not None:
            return v
        return None
    return None


def _obs_component_string(obs: Dict[str, Any], text: str) -> Optional[str]:
    for comp in obs.get("component") or []:
        ctext = (((comp.get("code") or {}).get("text")) or "")
        if str(ctext).strip() != text:
            continue
        vs = comp.get("valueString")
        if isinstance(vs, str) and vs.strip():
            return vs.strip()
    return None


def _has_coding(coding_list: List[Dict[str, Any]] | None, system: str, code: str) -> bool:
    if not isinstance(coding_list, list):
        return False
    for cd in coding_list:
        if cd.get("system") == system and cd.get("code") == code:
            return True
    return False


def _get_component(obs: Dict[str, Any], system: str, code: str) -> Dict[str, Any] | None:
    for comp in obs.get("component", []) or []:
        if _has_coding((comp.get("code") or {}).get("coding"), system, code):
            return comp
    return None


def _extract_change_type(obs: Dict[str, Any]) -> str | None:
    code = obs.get("code") or {}
    labels: List[str] = []

    if isinstance(code, dict):
        text = code.get("text")
        if isinstance(text, str) and text.strip():
            labels.append(text.strip().lower())

        for cd in code.get("coding") or []:
            raw_code = cd.get("code")
            raw_display = cd.get("display")
            if isinstance(raw_code, str) and raw_code.strip():
                labels.append(raw_code.strip().lower())
            if isinstance(raw_display, str) and raw_display.strip():
                labels.append(raw_display.strip().lower())

    joined = " ".join(labels)

    if "deletion" in joined:
        return "deletion"
    if "duplication" in joined:
        return "duplication"
    if "amplification" in joined:
        return "amplification"

    comp = _get_component(obs, LOINC, LNC_DNA_CHANGE_TYPE)
    if comp:
        vcc = comp.get("valueCodeableConcept") or {}
        for cd in (vcc.get("coding") or []):
            sys = (cd.get("system") or "").lower()
            code_val = (cd.get("code") or "").lower()
            disp = (cd.get("display") or "").lower()
            txt = f"{sys} {code_val} {disp}"
            if "deletion" in txt or "so:0000159" in txt:
                return "deletion"
            if "duplication" in txt or "so:1000035" in txt:
                return "duplication"
            if "amplification" in txt or "copy_number_gain" in txt or "so:0001742" in txt or "so:0001869" in txt:
                return "amplification"

    oid = (obs.get("id") or "").lower()
    if "-deletion-" in oid or "-del-" in oid:
        return "deletion"
    if "-duplication-" in oid or "-dup-" in oid:
        return "duplication"
    if "-amplification-" in oid or "-amp-" in oid:
        return "amplification"

    for comp in obs.get("component", []) or []:
        label = ((comp.get("code", {}) or {}).get("text") or "").lower()
        for cd in (comp.get("code", {}) or {}).get("coding", []) or []:
            s = ((cd.get("display") or "") + " " + (cd.get("code") or "")).lower()
            label += " " + s
        if "deletion" in label or " del" in label:
            return "deletion"
        if "duplication" in label or " dup" in label:
            return "duplication"
        if "amplification" in label or " amp" in label or "copy number gain" in label:
            return "amplification"

    return None


def _regions_from_comp(comp: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    vcc = comp.get("valueCodeableConcept") or {}
    for cd in vcc.get("coding", []) or []:
        for k in ("code", "display"):
            v = cd.get(k)
            if isinstance(v, str) and v.strip():
                out.add(v.strip())
    vs = comp.get("valueString")
    if isinstance(vs, str) and vs.strip():
        out.add(vs.strip())
    return out


def _extract_region(obs: Dict[str, Any]) -> str | None:
    comp = _get_component(obs, LOINC, LNC_GENOMIC_REF_ID)
    if comp:
        vcc = comp.get("valueCodeableConcept") or {}
        cds = vcc.get("coding") or []
        if cds:
            code = (cds[0].get("code") or "").strip()
            disp = (cds[0].get("display") or "").strip()
            if code:
                return code
            if disp:
                return disp
        vs = comp.get("valueString")
        if isinstance(vs, str) and vs.strip():
            return vs.strip()

    oid = obs.get("id") or ""
    m = _CYTO_ID_RE.search(oid)
    if m:
        return m.group(1)

    code = obs.get("code") or {}
    labels: List[str] = []

    if isinstance(code, dict):
        text = code.get("text")
        if isinstance(text, str) and text.strip():
            labels.append(text.strip())

        for cd in code.get("coding") or []:
            raw_code = cd.get("code")
            raw_display = cd.get("display")
            if isinstance(raw_code, str) and raw_code.strip():
                labels.append(raw_code.strip())
            if isinstance(raw_display, str) and raw_display.strip():
                labels.append(raw_display.strip())

    region_re = re.compile(r"(?:deletion|duplication|amplification)[ _-]+([0-9]{1,2}[pq][0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
    for label in labels:
        m = region_re.search(label)
        if m:
            return m.group(1)

    for comp in obs.get("component", []) or []:
        reg = _regions_from_comp(comp)
        if reg:
            return next(iter(reg))

    return None


def _is_pos(obs: Dict[str, Any]) -> bool:
    interps = obs.get("interpretation") or []
    for cc in interps:
        for cd in (cc.get("coding") or []):
            code = (cd.get("code") or "").strip().upper()
            disp = (cd.get("display") or "").strip().lower()
            if code == "POS" or disp == "positive":
                return True

    vs = obs.get("valueString")
    if isinstance(vs, str) and vs.strip():
        val = vs.strip().upper()
        if val == "MUT":
            return True
        if val == "WT":
            return False

    vb = obs.get("valueBoolean")
    if vb is True:
        return True
    if vb is False:
        return False

    vcc = obs.get("valueCodeableConcept") or {}
    text = (vcc.get("text") or "").strip().lower() if isinstance(vcc, dict) else ""
    if text in {"positive", "mut"}:
        return True
    if text in {"negative", "wt"}:
        return False

    for cd in (vcc.get("coding") or []) if isinstance(vcc, dict) else []:
        code = (cd.get("code") or "").strip().lower()
        disp = (cd.get("display") or "").strip().lower()
        if code in {"pos", "positive", "mut"} or disp in {"positive", "mut"}:
            return True
        if code in {"neg", "negative", "wt"} or disp in {"negative", "wt"}:
            return False

    return False


def _patient_data_requires_conditions(conds: List[Dict[str, Any]]) -> bool:
    for cond in conds or []:
        col = str(cond.get("column_name") or "").strip()
        if col == "cancer_type":
            return True
    return False


def _extract_cancer_type(conds: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    for c in conds or []:
        code = c.get("code") or {}
        codings = (code.get("coding") or []) if isinstance(code, dict) else []
        for cd in codings:
            disp = cd.get("display")
            cc = cd.get("code")
            if isinstance(disp, str) and disp.strip():
                return disp.strip(), str(cc).strip() if cc is not None else None
            if cc is not None:
                return None, str(cc).strip()
    return None, None


def _extract_treatment_window(meds: List[Dict[str, Any]]) -> Tuple[Optional[datetime], Optional[datetime]]:
    starts: List[datetime] = []
    ends: List[datetime] = []
    for ms in meds or []:
        ep = ms.get("effectivePeriod") or {}
        s = parse_iso_datetime(ep.get("start"))
        e = parse_iso_datetime(ep.get("end"))
        if s:
            starts.append(s)
        if e:
            ends.append(e)
    return (min(starts) if starts else None, max(ends) if ends else None)


def _normalize_datetime_timezone(value: Optional[datetime], reference: Optional[datetime]) -> Optional[datetime]:
    if value is None or reference is None:
        return value
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value


def _extract_sequence_and_pcs(obs_list: List[Dict[str, Any]]) -> Tuple[Optional[datetime], Optional[datetime], Dict[str, float]]:
    pca = None
    for o in obs_list or []:
        if _obs_has_loinc_code(o, PCA_LOINC_CODE):
            pca = o
            break
    if not pca:
        return None, None, {}
    ep = pca.get("effectivePeriod") or {}
    s = parse_iso_datetime(ep.get("start"))
    e = parse_iso_datetime(ep.get("end"))
    pcs: Dict[str, float] = {}
    for k in ("PC1", "PC2", "PC3", "PC4", "PC5"):
        v = _obs_component_value(pca, k)
        if v is not None:
            pcs[k] = float(v)
    return s, e, pcs


def _extract_total_tmb(obs_list: List[Dict[str, Any]]) -> Optional[float]:
    for o in obs_list or []:
        if not _obs_has_loinc_code(o, TOTAL_TMB_LOINC_CODE):
            continue
        v = get_fhir_numeric_value(o)
        if v is not None:
            return v
        return None
    return None


def _extract_gene_features(obs_list: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for o in obs_list or []:
        gene = _obs_component_string(o, "Gene symbol")
        if not gene:
            continue
        gene_norm = gene.strip().upper()
        for comp in o.get("component") or []:
            ctext = (((comp.get("code") or {}).get("text")) or "")
            ctext = str(ctext).strip()
            if not ctext or ctext == "Gene symbol":
                continue
            fv = get_fhir_numeric_value(comp)
            if fv is None:
                continue
            out[f"{ctext}_{gene_norm}"] = fv
    return out


def _get_workload_arg(workload_args: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in workload_args and workload_args.get(key) is not None:
            return workload_args.get(key)
    return None


def _match_patient_data(
    patient: Dict[str, Any],
    pid: str,
    conds: List[Dict[str, Any]],
    patient_conditions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> bool:
    patient_conditions = patient_conditions or {}
    for cond in conds:
        col = cond.get("column_name")

        if col == "deceased_date":
            vals = cond.get("values")
            if not vals or len(vals) != 2:
                return False
            deceased = patient.get("deceasedDateTime") or patient.get("deceasedDate")
            if not deceased:
                return False
            d = parse_iso_date(deceased)
            lo = parse_iso_date(vals[0])
            hi = parse_iso_date(vals[1])
            if not d or not lo or not hi:
                return False
            if not (lo <= d <= hi):
                return False

        elif col == "cancer_type":
            raw_val = cond.get("value")
            if isinstance(raw_val, list):
                raw_val = raw_val[0] if raw_val else None
            desired = str(raw_val or "").strip()
            if not desired:
                return False

            desired_norm = desired.strip().lower()
            lookup_display = CANCER_TYPE_DISPLAY_MAP.get(desired_norm) or desired
            lookup_display_norm = lookup_display.strip().lower()

            found_display = False
            for c in patient_conditions.get(pid, []) or []:
                codings = ((c.get("code") or {}).get("coding") or []) if isinstance((c.get("code") or {}), dict) else []
                for cd in codings:
                    disp = cd.get("display")
                    if isinstance(disp, str) and disp.strip().lower() == lookup_display_norm:
                        found_display = True
                        break
                if found_display:
                    break

            if found_display:
                continue

            codes = set(CANCER_TYPE_CODE_MAP.get(desired_norm) or set())
            if desired_norm.isdigit():
                codes.add(desired_norm)

            if not codes:
                return False

            found_code = False
            for c in patient_conditions.get(pid, []) or []:
                codings = ((c.get("code") or {}).get("coding") or []) if isinstance((c.get("code") or {}), dict) else []
                for cd in codings:
                    code = cd.get("code")
                    if code is not None and str(code).strip() in codes:
                        found_code = True
                        break
                if found_code:
                    break

            if not found_code:
                return False

    return True



def apply_filters(
    filters: Any,
    bundle: Dict[str, Any] | str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> List[str]:
    flist = normalize_filters(filters)

    cache_target = _bundle_cache_key(bundle, project_id=project_id) if _is_local_bundle(bundle) else resolve_server_url(bundle)
    filter_repr = json.dumps(flist, sort_keys=True, default=str)
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    datasource_group_key = (
        str(datasource_group_id).strip()
        if datasource_group_id is not None and str(datasource_group_id).strip()
        else "__default__"
    )
    cache_key = (
        f"{project_key}::{datasource_group_key}||{cache_target}||"
        f"{hashlib.sha256(filter_repr.encode('utf-8')).hexdigest()}"
    )

    if cache_key in _APPLY_FILTERS_CACHE:
        print("\n" + "=" * 100)
        print("APPLY FILTERS CACHE HIT")
        print(f"cache_key={cache_key}")
        print(f"cache_entries={len(_APPLY_FILTERS_CACHE)}")
        print("=" * 100 + "\n")
        return list(_APPLY_FILTERS_CACHE[cache_key])

    if _is_local_bundle(bundle):
        indexed = _index_local_bundle_resources(bundle, project_id=project_id)
        patients = indexed["patients"]
        patient_meds = indexed["patient_meds"]
        patient_conditions = indexed["patient_conditions"]

        pids_curr: Set[str] = set(patients.keys())
        print(
            "[FHIR LOCAL FILTER] start "
            f"project_id={project_id} datasource_group_id={datasource_group_id} "
            f"patients={len(pids_curr)} conditions="
            + json.dumps(flist, default=str),
            flush=True,
        )

        # Resolve the patient-query controls even if the stored filter list has no
        # PATIENT_QUERY rows.  The HAPI path has always synthesized the schema's
        # birth/death defaults in that case; local JSON must do the same.
        resolved_patient_controls = resolve_patient_filter_controls(
            filters,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            include_defaults=True,
        )
        if resolved_patient_controls:
            print(
                "[FHIR LOCAL FILTER] resolved patient controls="
                + json.dumps(
                    [
                        {
                            "control_id": control.get("id"),
                            "query": control.get("query"),
                            "condition": condition,
                        }
                        for control, condition in resolved_patient_controls
                    ],
                    default=str,
                ),
                flush=True,
            )
            keep: Set[str] = set()
            for pid in pids_curr:
                if _match_local_patient_query(
                    patients[pid],
                    pid,
                    filters,
                    patient_meds,
                    project_id=project_id,
                    datasource_group_id=datasource_group_id,
                ):
                    keep.add(pid)
            pids_curr = keep
            print(f"[FHIR LOCAL FILTER] after patient-query controls={len(pids_curr)}", flush=True)

        patient_data_conds = [c for c in flist if (c.get("filter_type") or "").upper() == "PATIENT_DATA"]
        if patient_data_conds:
            keep: Set[str] = set()
            for pid in pids_curr:
                if _match_local_patient_data(
                    patients[pid],
                    pid,
                    patient_data_conds,
                    patient_conditions,
                    project_id=project_id,
                    datasource_group_id=datasource_group_id,
                ):
                    keep.add(pid)
            pids_curr = keep
            print(f"[FHIR LOCAL FILTER] after patient-data controls={len(pids_curr)}", flush=True)

        observation_query_conds = [c for c in flist if (c.get("filter_type") or "").upper() == "OBSERVATION_QUERY"]
        observation_data_conds = [
            c for c in flist if (c.get("filter_type") or "").upper() in {"OBSERVATION", "OBSERVATION_DATA"}
        ]

        if (observation_query_conds or observation_data_conds) and pids_curr:
            patient_obs = _get_cached_local_observations_by_patient(bundle, pids_curr, project_id=project_id)

            if observation_data_conds:
                keep: Set[str] = set()
                for pid in pids_curr:
                    if patient_satisfies_coded_observation_data_filters(
                        patient_obs.get(pid, []),
                        observation_data_conds,
                        project_id=project_id,
                    ):
                        print(f"{pid} satisfied local data pass", flush=True)
                        keep.add(pid)
                pids_curr = keep
                print(f"[FHIR LOCAL FILTER] after observation-data controls={len(pids_curr)}", flush=True)
            else:
                pids_curr = {pid for pid in pids_curr if patient_obs.get(pid)}
                print(f"[FHIR LOCAL FILTER] after observation-query controls={len(pids_curr)}", flush=True)

        result = sorted(list(pids_curr))
        _APPLY_FILTERS_CACHE[cache_key] = result

        print("\n" + "=" * 100)
        print("APPLY FILTERS CACHE STORE")
        print(f"cache_key={cache_key}")
        print(f"result size={len(result)}")
        print(f"cache_entries={len(_APPLY_FILTERS_CACHE)}")
        print("=" * 100 + "\n")

        return result

    server_url = resolve_server_url(bundle)

    if cache_key in _APPLY_FILTERS_CACHE:
        print("\n" + "=" * 100)
        print("APPLY FILTERS CACHE HIT")
        print(f"cache_key={cache_key}")
        print(f"cache_entries={len(_APPLY_FILTERS_CACHE)}")
        print("=" * 100 + "\n")
        return list(_APPLY_FILTERS_CACHE[cache_key])

    patients = query_patients(
        filters,
        server_url,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    if not patients:
        _APPLY_FILTERS_CACHE[cache_key] = []
        print("\n" + "=" * 100)
        print("APPLY FILTERS CACHE STORE")
        print(f"cache_key={cache_key}")
        print(f"cache_entries={len(_APPLY_FILTERS_CACHE)}")
        print("=" * 100 + "\n")
        return []

    pids_curr: Set[str] = set(patients.keys())
    sess = session()

    patient_data_conds = [c for c in flist if (c.get("filter_type") or "").upper() == "PATIENT_DATA"]
    if patient_data_conds:
        patient_conditions = None
        if _patient_data_requires_conditions(patient_data_conds):
            patient_conditions = _fetch_conditions_index_for_subject_ids(sess, server_url, pids_curr)
        keep: Set[str] = set()
        for pid in pids_curr:
            if _match_patient_data(patients[pid], pid, patient_data_conds, patient_conditions):
                keep.add(pid)
        pids_curr = keep

    observation_query_conds = [c for c in flist if (c.get("filter_type") or "").upper() == "OBSERVATION_QUERY"]
    observation_data_conds = [
        c for c in flist if (c.get("filter_type") or "").upper() in {"OBSERVATION", "OBSERVATION_DATA"}
    ]

    if (observation_query_conds or observation_data_conds) and pids_curr:
        if observation_query_conds:
            patient_obs = query_observations_by_patient(filters, server_url, pids_curr, project_id=project_id)
        else:
            patient_obs = get_cached_observations_by_patient(server_url, pids_curr, project_id=project_id)

        if observation_data_conds:
            keep: Set[str] = set()
            for pid in pids_curr:
                if patient_satisfies_coded_observation_data_filters(patient_obs.get(pid, []), observation_data_conds, project_id=project_id):
                    print(f"{pid} satisfied local data pass", flush=True)
                    keep.add(pid)
            pids_curr = keep
        else:
            pids_curr = {pid for pid in pids_curr if patient_obs.get(pid)}

    result = list(pids_curr)
    _APPLY_FILTERS_CACHE[cache_key] = result

    print("\n" + "=" * 100)
    print("APPLY FILTERS CACHE STORE")
    print(f"cache_key={cache_key}")
    print(f"result size={len(result)}")
    print(f"cache_entries={len(_APPLY_FILTERS_CACHE)}")
    print("=" * 100 + "\n")

    return result



def _fetch_analysis_context(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    computation_type: str,
    workload_args: Dict[str, Any],
    project_id: Optional[Union[int, str]] = None,
) -> Tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, Dict[str, Set[str]]],
]:
    if _is_local_bundle(bundle):
        indexed = _index_local_bundle_resources(bundle, project_id=project_id)
        wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
        patients = {pid: indexed["patients"].get(pid, {"id": pid}) for pid in wanted}
        patient_obs = _get_cached_local_observations_by_patient(bundle, wanted, project_id=project_id)

        patient_meds: Dict[str, Dict[str, Set[str]]] = {}
        med_statements = indexed["patient_med_statements"]
        med_tokens = indexed["patient_meds"]

        for pid in wanted:
            meds_for_pid = med_statements.get(pid, [])
            names = set()
            for med in meds_for_pid:
                cc = med.get("medicationCodeableConcept") or {}
                for cd in (cc.get("coding") or []):
                    disp = str(cd.get("display") or "").strip()
                    if disp:
                        names.add(disp)
            tokens = set(med_tokens.get(pid, {}).get("tokens") or set())
            patient_meds[pid] = {
                "names": names,
                "tokens": tokens,
            }

        return patients, patient_obs, patient_meds

    server_url = resolve_server_url(bundle)
    return fetch_analysis_subject_context(
        server_url=server_url,
        subject_ids=subject_ids,
        computation_type=computation_type,
        workload_args=workload_args,
        project_id=project_id,
    )


def _get_analysis_value(
    computation_type: str,
    property_key: str,
    column_id: str,
    patient: Dict[str, Any],
    obs_list: List[Dict[str, Any]],
    meds: Optional[Dict[str, Set[str]]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> Any:
    return get_analysis_value_for_property(
        computation_type=computation_type,
        property_key=property_key,
        column_id=column_id,
        patient=patient,
        observations=obs_list,
        medications=meds,
        project_id=project_id,
    )


_SUBJECTS_CACHE = OrderedDict()
_SUBJECTS_CACHE_LOCK = threading.Lock()
_SUBJECTS_CACHE_MAX = 4


def build_biomarker_subjects(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
    cancer_type: Optional[str] = None,
) -> List[BiomarkerSubject]:
    subject_ids = list(subject_ids)
    bundle_key = id(bundle) if _is_local_bundle(bundle) else resolve_server_url(bundle)
    cache_key = (
        bundle_key,
        str(project_id),
        str(datasource_group_id),
        str(cancer_type or ""),
        frozenset(subject_ids),
    )
    with _SUBJECTS_CACHE_LOCK:
        if cache_key in _SUBJECTS_CACHE:
            _SUBJECTS_CACHE.move_to_end(cache_key)
            return _SUBJECTS_CACHE[cache_key]

    if _is_local_bundle(bundle):
        indexed = _index_local_bundle_resources(bundle, project_id=project_id)
        patients = indexed["patients"]
        conds_by_pid = indexed["patient_conditions"]
        meds_by_pid = indexed["patient_med_statements"]
        obs_by_pid = indexed["patient_obs"]
        panel_by_pid: Dict[str, Set[str]] = {}

        for group in indexed["groups"]:
            gname = group.get("name") or None
            ident_val = None
            ids = group.get("identifier") or []
            if isinstance(ids, list) and ids:
                ident_val = (ids[0] or {}).get("value")
            panel_val = str(ident_val or gname or "").strip() or None
            for mem in group.get("member") or []:
                mref = (((mem.get("entity") or {}).get("reference")) or "")
                pid = pid_from_ref(mref)
                if pid and panel_val and pid in patients:
                    panel_by_pid.setdefault(pid, set()).add(panel_val)
    else:
        server_url = resolve_server_url(bundle)
        patients, conds_by_pid, meds_by_pid, obs_by_pid, panel_by_pid = _index_bundle_for_biomarkers_from_server(server_url, subject_ids)

    survival_window = _load_biomarker_survival_window(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    resource_linkage = _load_biomarker_resource_linkage(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    default_censor_datetime = _default_censor_datetime_for_window(
        window=survival_window,
        patients=patients,
    )

    out: List[BiomarkerSubject] = []
    for pid in subject_ids:
        if pid not in patients:
            continue
        patient = patients[pid]
        conds = conds_by_pid.get(pid, [])
        meds = meds_by_pid.get(pid, [])
        obs_list = obs_by_pid.get(pid, [])
        conds, obs_list = _scope_biomarker_resources_for_patient(
            pid=pid,
            conds=conds,
            observations=obs_list,
            linkage=resource_linkage,
            cancer_type=cancer_type,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        )
        if resource_linkage is not None and not conds:
            continue
        cancer_disp, cancer_code = _extract_cancer_type(conds)
        tstart_seq, tstop_seq, pcs = _extract_sequence_and_pcs(obs_list)
        tstart_trt, tstop_trt = _resolve_configured_survival_window(
            window=survival_window,
            patient=patient,
            conds=conds,
            meds=meds,
            observations=obs_list,
            default_censor_datetime=default_censor_datetime,
        )
        total_tmb = _extract_total_tmb(obs_list)
        gene_features = _extract_gene_features(obs_list)
        pset = panel_by_pid.get(pid) or set()
        panel_version = next(iter(pset)) if pset else None
        gender = patient.get("gender")
        gender = gender.upper() if isinstance(gender, str) and gender else None
        age = _patient_age_years(patient)
        event = _patient_event_flag(patient)
        out.append(
            BiomarkerSubject(
                subject_id=pid,
                panel_version=panel_version,
                cancer_type_display=cancer_disp,
                cancer_type_code=cancer_code,
                gender=gender,
                age=age,
                tstart_seq=tstart_seq,
                tstop_seq=tstop_seq,
                tstart_trt=tstart_trt,
                tstop_trt=tstop_trt,
                event=event,
                pcs=pcs,
                total_mutation_burden=total_tmb,
                gene_features=gene_features,
            )
        )

    with _SUBJECTS_CACHE_LOCK:
        _SUBJECTS_CACHE[cache_key] = out
        _SUBJECTS_CACHE.move_to_end(cache_key)
        while len(_SUBJECTS_CACHE) > _SUBJECTS_CACHE_MAX:
            _SUBJECTS_CACHE.popitem(last=False)
    return out

def _index_bundle_for_biomarkers_from_server(
    server_url: str,
    subject_ids: Iterable[str],
) -> Tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, Set[str]],
]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}, {}, {}, {}, {}

    sess = session()
    patients_raw = _fetch_patients_by_ids(sess, server_url, wanted)
    conds_raw = _fetch_conditions_by_subject_ids(sess, server_url, wanted)
    meds_raw = _fetch_medication_statements_by_subject_ids(sess, server_url, wanted)
    obs_raw = _fetch_observations_by_subject_ids(sess, server_url, wanted)
    groups_raw = _fetch_groups(sess, server_url)

    patients: Dict[str, Dict[str, Any]] = {}
    conditions_by_pid: Dict[str, List[Dict[str, Any]]] = {}
    meds_by_pid: Dict[str, List[Dict[str, Any]]] = {}
    obs_by_pid: Dict[str, List[Dict[str, Any]]] = {}
    panel_versions_by_pid: Dict[str, Set[str]] = {}

    for res in patients_raw:
        if res.get("resourceType") != "Patient":
            continue
        pid = res.get("id")
        if isinstance(pid, str) and pid:
            patients[pid] = res
            conditions_by_pid.setdefault(pid, [])
            meds_by_pid.setdefault(pid, [])
            obs_by_pid.setdefault(pid, [])
            panel_versions_by_pid.setdefault(pid, set())

    for res in conds_raw:
        if res.get("resourceType") != "Condition":
            continue
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if pid:
            conditions_by_pid.setdefault(pid, []).append(res)

    for res in meds_raw:
        if res.get("resourceType") != "MedicationStatement":
            continue
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if pid:
            meds_by_pid.setdefault(pid, []).append(res)

    for res in obs_raw:
        if res.get("resourceType") != "Observation":
            continue
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if pid:
            obs_by_pid.setdefault(pid, []).append(res)

    for res in groups_raw:
        if res.get("resourceType") != "Group":
            continue
        gname = res.get("name") or None
        ident_val = None
        ids = res.get("identifier") or []
        if isinstance(ids, list) and ids:
            ident_val = (ids[0] or {}).get("value")
        panel_val = str(ident_val or gname or "").strip() or None
        for mem in res.get("member") or []:
            mref = (((mem.get("entity") or {}).get("reference")) or "")
            pid = pid_from_ref(mref)
            if pid and panel_val and pid in patients:
                panel_versions_by_pid.setdefault(pid, set()).add(panel_val)

    return patients, conditions_by_pid, meds_by_pid, obs_by_pid, panel_versions_by_pid


def _normalize_covariate_key(name: str) -> str:
    """Canonical lookup key for a covariate/feature name.

    Covariate exports separate the gene with ':' or '.' depending on the
    datasource group's training pipeline; extracted feature keys use '_' and
    lowercase. One function so the model->schema and schema->feature joins
    normalize identically.
    """
    return str(name).strip().lower().replace(":", "_").replace(".", "_")


def align_model_coefficients(coef_by_covariate, biomarker_covariates, context_label=""):
    """Align model coefficients to the schema's covariate order.

    Exact name match first, then the normalized key — so a model trained under
    one export convention still lands on the right schema column. A model
    covariate that resolves to no schema column would silently vanish from the
    risk score, so it is logged loudly instead.

    Returns ``(coef_vector_in_schema_order, n_mapped, missing_model_covariates)``.
    """
    exact = {str(k): float(v) for k, v in dict(coef_by_covariate).items()}
    by_norm = {}
    for name, value in exact.items():
        by_norm.setdefault(_normalize_covariate_key(name), (name, value))

    matched_model_names = set()
    coef_vec = []
    for cov in biomarker_covariates:
        cov = str(cov)
        if cov in exact:
            coef_vec.append(exact[cov])
            matched_model_names.add(cov)
            continue
        hit = by_norm.get(_normalize_covariate_key(cov))
        if hit is not None:
            coef_vec.append(hit[1])
            matched_model_names.add(hit[0])
            continue
        coef_vec.append(0.0)

    missing = sorted(set(exact) - matched_model_names)
    if missing:
        logging.getLogger(__name__).warning(
            "%s: %d of %d model covariates match no schema covariate and are "
            "DROPPED from the risk score (first few: %s). The model and the "
            "datasource group's global schema disagree.",
            context_label or "align_model_coefficients",
            len(missing),
            len(exact),
            missing[:5],
        )
    return coef_vec, len(matched_model_names), missing


def _survival_time_months(subject: "BiomarkerSubject") -> Optional[float]:
    """Unrounded survival time in months, or None when the subject must be dropped.

    Every biomarker extraction (scoring, KM grouping, time/censoring) must apply
    this identically: cached scores are matched to later extractions positionally,
    so a subject dropped in one loop but kept in another would misalign them all.
    Reference parity: no rounding, and rows with time <= 0 are excluded.
    """
    if subject.tstart_trt is None or subject.tstop_trt is None:
        return None
    delta = subject.tstop_trt - subject.tstart_trt
    months = (float(delta.total_seconds()) / 86400.0) / 30.44
    if not (months > 0.0):  # also rejects NaN
        return None
    return months


def build_biomarker_subjects_dataframe(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    biomarker_covariates: List[str],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
    cancer_type: Optional[str] = None,
) -> pd.DataFrame:
    subjects = build_biomarker_subjects(
        bundle,
        subject_ids,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        cancer_type=cancer_type,
    )
    rows: List[Dict[str, Any]] = []
    for s in subjects:
        if not s.subject_id:
            continue
        if _survival_time_months(s) is None:
            continue
        if s.event is None:
            continue

        feats: Dict[str, float] = {}
        feats["age"] = float(s.age) if s.age is not None else 0.0
        feats["pc1"] = float(s.pcs.get("PC1")) if s.pcs.get("PC1") is not None else 0.0
        feats["pc2"] = float(s.pcs.get("PC2")) if s.pcs.get("PC2") is not None else 0.0
        feats["pc3"] = float(s.pcs.get("PC3")) if s.pcs.get("PC3") is not None else 0.0
        feats["pc4"] = float(s.pcs.get("PC4")) if s.pcs.get("PC4") is not None else 0.0
        feats["pc5"] = float(s.pcs.get("PC5")) if s.pcs.get("PC5") is not None else 0.0
        feats["gender_male"] = 1.0 if (s.gender or "").strip().upper() == "MALE" else 0.0
        feats["mutation_burden"] = float(s.total_mutation_burden) if s.total_mutation_burden is not None else 0.0
        feats["mutation_burden_of_cancer"] = float(s.total_mutation_burden) if s.total_mutation_burden is not None else 0.0
        for k, v in (s.gene_features or {}).items():
            try:
                feats[_normalize_covariate_key(k)] = float(v)
            except Exception:
                continue

        row: Dict[str, Any] = {}
        for cov in biomarker_covariates:
            v = feats.get(cov.lower())
            if v is None:
                v = feats.get(_normalize_covariate_key(cov))
            if v is None:
                v = 0.0
            row[cov] = v
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=biomarker_covariates)
    return pd.DataFrame(rows, columns=biomarker_covariates)


# Width of the band around the cutoff inside which a patient's arm cannot be
# guaranteed: the encrypted comparison resolves such a patient on CKKS noise rather
# than on the model, so the clear and encrypted paths may legitimately disagree about
# them. Only the COUNT of such patients is retained (see ``NEAR_CUTOFF_ATTR``) -- never
# a margin or a score -- and only this clear path can measure it, since it alone knows
# the exact ``score - cutoff``.
NEAR_CUTOFF_MARGIN = 1e-5
NEAR_CUTOFF_ATTR = "biomarker_near_cutoff"


def biomarker_subjects_to_km_dataframe(
    subjects: List[BiomarkerSubject],
    coeffs: pd.DataFrame,
    cutoff_value: float,
    target_biomarker_covariates: List[str],
    group_col: str,
    time_col: str,
    censoring_col: str,
    epsilon: float,
) -> pd.DataFrame:
    cutoff_value = _coerce_float_scalar(cutoff_value, "biomarker model cutoff")

    if isinstance(coeffs, pd.DataFrame) and "penalized" not in coeffs.columns:
        coeffs = coeffs.copy()
        coeffs["penalized"] = True

    coef_df = coeffs
    if isinstance(coeffs, pd.DataFrame) and not coeffs.empty and "penalized" in coeffs.columns:
        try:
            pen = coeffs["penalized"]
            mask = pen == True
            if not mask.any() and pen.dtype == object:
                mask = pen.astype(str).str.strip().str.lower().isin(["true", "1", "t", "yes", "y"])
            if mask.any():
                coef_df = coeffs[mask]
        except Exception:
            coef_df = coeffs

    coef_pen = coef_df.set_index("covariate")
    aligned_coefs, _, _ = align_model_coefficients(
        coef_pen["coef"].to_dict(),
        target_biomarker_covariates,
        context_label="biomarker KM recompute",
    )
    coef_map: Dict[str, float] = {
        str(cov): float(val)
        for cov, val in zip(target_biomarker_covariates, aligned_coefs)
    }
    coef_map_lc: Dict[str, float] = {str(k).lower(): float(v) for k, v in coef_map.items()}

    cov_names = list(coef_map.keys())
    cov_names_lc = [c.lower() for c in cov_names]

    rows: List[Dict[str, Any]] = []
    near_cutoff = 0
    for s in subjects:
        if not s.subject_id:
            continue
        months = _survival_time_months(s)
        if months is None:
            continue

        if s.event is None:
            continue
        event_bool = bool(int(s.event) != 0)

        feats: Dict[str, float] = {}
        feats["age"] = float(s.age) if s.age is not None else 0.0
        feats["pc1"] = float(s.pcs.get("PC1")) if s.pcs.get("PC1") is not None else 0.0
        feats["pc2"] = float(s.pcs.get("PC2")) if s.pcs.get("PC2") is not None else 0.0
        feats["pc3"] = float(s.pcs.get("PC3")) if s.pcs.get("PC3") is not None else 0.0
        feats["pc4"] = float(s.pcs.get("PC4")) if s.pcs.get("PC4") is not None else 0.0
        feats["pc5"] = float(s.pcs.get("PC5")) if s.pcs.get("PC5") is not None else 0.0
        feats["gender_male"] = 1.0 if (s.gender or "").strip().upper() == "MALE" else 0.0

        if s.total_mutation_burden is not None:
            feats["mutation_burden"] = float(s.total_mutation_burden)
            feats["mutation_burden_of_cancer"] = float(s.total_mutation_burden)

        for k, v in (s.gene_features or {}).items():
            try:
                feats[_normalize_covariate_key(k)] = float(v)
            except Exception:
                continue

        risk_score = 0.0
        for cov, cov_lc in zip(cov_names, cov_names_lc):
            coef = coef_map_lc.get(cov_lc, 0.0)
            if coef == 0.0:
                continue
            v = feats.get(cov_lc)
            if v is None:
                v = feats.get(_normalize_covariate_key(cov))
            if v is None:
                v = 0.0
            risk_score += float(v) * float(coef)

        diff = risk_score - cutoff_value
        if abs(diff) <= NEAR_CUTOFF_MARGIN:
            near_cutoff += 1
        if abs(diff) <= epsilon:
            cleaned_diff = 0.0
        else:
            cleaned_diff = diff

        group = "high_score" if float(cleaned_diff) > 0.0 else "low_score"

        rows.append(
            {
                group_col: group,
                time_col: float(months),
                censoring_col: bool(event_bool),
            }
        )

    if not rows:
        empty = pd.DataFrame(columns=[group_col, time_col, censoring_col])
        empty.attrs[NEAR_CUTOFF_ATTR] = near_cutoff
        return empty

    df = pd.DataFrame(rows, columns=[group_col, time_col, censoring_col])
    df[group_col] = df[group_col].astype(str)
    df[time_col] = pd.to_numeric(df[time_col], errors="coerce").astype(float)
    df = df.dropna(subset=[time_col])
    df[censoring_col] = df[censoring_col].astype(bool)
    df = df.dropna(subset=[group_col, censoring_col])
    # In-memory only: an aggregate count on the frame this function already returns.
    # Nothing in the analytics chain reads it and ``attrs`` is never serialized, so
    # only a caller that deliberately looks for it (the sweep's binning probe) sees it.
    df.attrs[NEAR_CUTOFF_ATTR] = near_cutoff
    return df


def build_biomarker_km_dataframe(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    coeffs: pd.DataFrame,
    cutoff_value: float,
    target_biomarker_covariates: List[str],
    group_col: str,
    time_col: str,
    censoring_col: str,
    epsilon: float,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
    cancer_type: Optional[str] = None,
) -> pd.DataFrame:
    subjects = build_biomarker_subjects(
        bundle,
        subject_ids,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        cancer_type=cancer_type,
    )
    return biomarker_subjects_to_km_dataframe(
        subjects=subjects,
        coeffs=coeffs,
        cutoff_value=cutoff_value,
        target_biomarker_covariates=target_biomarker_covariates,
        group_col=group_col,
        time_col=time_col,
        censoring_col=censoring_col,
        epsilon=epsilon,
    )


def extract_survivability_data(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    group_col: str,
    time_col: str,
    censoring_col: str,
    project_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    if not group_col or not time_col or not censoring_col:
        raise ValueError(
            f"extract_survivability_data missing required columns: "
            f"group_col={group_col}, time_col={time_col}, censoring_col={censoring_col}"
        )

    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return pd.DataFrame(columns=[group_col, time_col, censoring_col])

    workload_args = {
        "group_column_id": group_col,
        "time_column_id": time_col,
        "censoring_column_id": censoring_col,
    }
    patients, patient_obs, patient_meds = _fetch_analysis_context(
        bundle=bundle,
        subject_ids=wanted,
        computation_type="kaplan-meier",
        workload_args=workload_args,
        project_id=project_id,
    )

    rows: List[Dict[str, Any]] = []
    for pid in wanted:
        patient = patients.get(pid, {"id": pid})
        obs_list = patient_obs.get(pid, [])
        meds = patient_meds.get(pid)

        g_val = _get_analysis_value("kaplan-meier", "group_column_id", group_col, patient, obs_list, meds, project_id=project_id)
        t_val = _get_analysis_value("kaplan-meier", "time_column_id", time_col, patient, obs_list, meds, project_id=project_id)
        c_val = _get_analysis_value("kaplan-meier", "censoring_column_id", censoring_col, patient, obs_list, meds, project_id=project_id)

        if g_val is None or t_val is None or c_val is None:
            continue

        rows.append({group_col: g_val, time_col: t_val, censoring_col: c_val})

    if not rows:
        return pd.DataFrame(columns=[group_col, time_col, censoring_col])

    df = pd.DataFrame(rows, columns=[group_col, time_col, censoring_col])
    df[group_col] = df[group_col].astype(str)
    df[time_col] = pd.to_numeric(df[time_col], errors="coerce").astype(float)
    df = df.dropna(subset=[time_col])

    def _to_event_bool(v: Any) -> bool:
        try:
            iv = int(float(v))
            return iv != 0
        except Exception:
            return bool(v)

    df[censoring_col] = df[censoring_col].apply(_to_event_bool).astype(bool)
    return df


def extract_kaplan_meier_time_censoring_data(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    time_col: str,
    censoring_col: str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
    cancer_type: Optional[str] = None,
) -> pd.DataFrame:
    if not time_col or not censoring_col:
        raise ValueError(
            f"extract_kaplan_meier_time_censoring_data missing required columns: "
            f"time_col={time_col}, censoring_col={censoring_col}"
        )

    subjects = build_biomarker_subjects(
        bundle,
        subject_ids,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        cancer_type=cancer_type,
    )
    rows: List[Dict[str, Any]] = []
    for s in subjects:
        if not s.subject_id or s.event is None:
            continue
        t_val = _survival_time_months(s)
        if t_val is None:
            continue
        event_bool = bool(int(s.event) != 0)
        rows.append({time_col: float(t_val), censoring_col: event_bool})

    if not rows:
        return pd.DataFrame(columns=[time_col, censoring_col])

    df = pd.DataFrame(rows, columns=[time_col, censoring_col])
    df[time_col] = pd.to_numeric(df[time_col], errors="coerce").astype(float)
    df = df.dropna(subset=[time_col])
    df[censoring_col] = df[censoring_col].astype(bool)
    return df


def extract_mean_data(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    data_column_id: str,
    project_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return pd.DataFrame(columns=[data_column_id])

    workload_args = {
        "data_column_id": data_column_id,
    }
    patients, patient_obs, patient_meds = _fetch_analysis_context(
        bundle=bundle,
        subject_ids=wanted,
        computation_type="mean",
        workload_args=workload_args,
        project_id=project_id,
    )

    rows: List[Dict[str, Any]] = []
    for pid in wanted:
        patient = patients.get(pid, {"id": pid})
        obs_list = patient_obs.get(pid, [])
        meds = patient_meds.get(pid)
        raw_val = _get_analysis_value("mean", "data_column_id", data_column_id, patient, obs_list, meds, project_id=project_id)
        num_val = _coerce_float(raw_val)
        if num_val is None:
            continue
        rows.append({data_column_id: num_val})

    if not rows:
        return pd.DataFrame(columns=[data_column_id])

    df = pd.DataFrame(rows, columns=[data_column_id])
    df[data_column_id] = pd.to_numeric(df[data_column_id], errors="coerce").astype(float)
    df = df.dropna(subset=[data_column_id])
    return df


def extract_stdev_data(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    data_column_id: str,
    project_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return pd.DataFrame(columns=[data_column_id])

    workload_args = {
        "data_column_id": data_column_id,
    }
    patients, patient_obs, patient_meds = _fetch_analysis_context(
        bundle=bundle,
        subject_ids=wanted,
        computation_type="stdev",
        workload_args=workload_args,
        project_id=project_id,
    )

    rows: List[Dict[str, Any]] = []
    for pid in wanted:
        patient = patients.get(pid, {"id": pid})
        obs_list = patient_obs.get(pid, [])
        meds = patient_meds.get(pid)
        raw_val = _get_analysis_value("stdev", "data_column_id", data_column_id, patient, obs_list, meds, project_id=project_id)
        num_val = _coerce_float(raw_val)
        if num_val is None:
            continue
        rows.append({data_column_id: num_val})

    if not rows:
        return pd.DataFrame(columns=[data_column_id])

    df = pd.DataFrame(rows, columns=[data_column_id])
    df[data_column_id] = pd.to_numeric(df[data_column_id], errors="coerce").astype(float)
    df = df.dropna(subset=[data_column_id])
    return df


def extract_chi2_data(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    category_column_1_id: str,
    category_column_2_id: str,
    project_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return pd.DataFrame(columns=[category_column_1_id, category_column_2_id])

    workload_args = {
        "category_column_1_id": category_column_1_id,
        "category_column_2_id": category_column_2_id,
    }
    patients, patient_obs, patient_meds = _fetch_analysis_context(
        bundle=bundle,
        subject_ids=wanted,
        computation_type="chi2",
        workload_args=workload_args,
        project_id=project_id,
    )

    rows: List[Dict[str, Any]] = []
    for pid in wanted:
        patient = patients.get(pid, {"id": pid})
        obs_list = patient_obs.get(pid, [])
        meds = patient_meds.get(pid)

        v1_raw = _get_analysis_value("chi2", "category_column_1_id", category_column_1_id, patient, obs_list, meds, project_id=project_id)
        v2_raw = _get_analysis_value("chi2", "category_column_2_id", category_column_2_id, patient, obs_list, meds, project_id=project_id)
        v1 = _coerce_category(v1_raw)
        v2 = _coerce_category(v2_raw)
        if v1 is None or v2 is None:
            continue
        rows.append({category_column_1_id: v1, category_column_2_id: v2})

    if not rows:
        return pd.DataFrame(columns=[category_column_1_id, category_column_2_id])

    df = pd.DataFrame(rows, columns=[category_column_1_id, category_column_2_id])
    df[category_column_1_id] = df[category_column_1_id].astype(str).str.upper()
    df[category_column_2_id] = df[category_column_2_id].astype(str).str.upper()
    return df


def extract_ttest_data(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    data_column_id: str,
    category_column_1_id: str,
    project_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return pd.DataFrame(columns=[data_column_id, category_column_1_id])

    workload_args = {
        "data_column_id": data_column_id,
        "category_column_1_id": category_column_1_id,
    }
    patients, patient_obs, patient_meds = _fetch_analysis_context(
        bundle=bundle,
        subject_ids=wanted,
        computation_type="t-test",
        workload_args=workload_args,
        project_id=project_id,
    )

    rows: List[Dict[str, Any]] = []
    for pid in wanted:
        patient = patients.get(pid, {"id": pid})
        obs_list = patient_obs.get(pid, [])
        meds = patient_meds.get(pid)

        num_raw = _get_analysis_value("t-test", "data_column_id", data_column_id, patient, obs_list, meds, project_id=project_id)
        num_val = _coerce_float(num_raw)
        cat_raw = _get_analysis_value("t-test", "category_column_1_id", category_column_1_id, patient, obs_list, meds, project_id=project_id)
        cat_val = _coerce_category(cat_raw)
        if num_val is None or cat_val is None:
            continue
        rows.append({data_column_id: num_val, category_column_1_id: cat_val})

    if not rows:
        return pd.DataFrame(columns=[data_column_id, category_column_1_id])

    df = pd.DataFrame(rows, columns=[data_column_id, category_column_1_id])
    df[data_column_id] = pd.to_numeric(df[data_column_id], errors="coerce").astype(float)
    df = df.dropna(subset=[data_column_id])
    df[category_column_1_id] = df[category_column_1_id].astype(str).str.upper()
    return df


def extract_data_for_computation(
    computation_type: str,
    workload_args: Dict[str, Any],
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    ct = (computation_type or "").strip().lower()

    if ct == "kaplan-meier":
        return extract_survivability_data(
            bundle=bundle,
            subject_ids=subject_ids,
            group_col=_get_workload_arg(workload_args, "group_col", "group_column_id"),
            time_col=_get_workload_arg(workload_args, "time_col", "time_column_id"),
            censoring_col=_get_workload_arg(workload_args, "censoring_col", "censoring_column_id"),
            project_id=project_id,
        )

    if ct == "kaplan-meier-time-censoring":
        return extract_kaplan_meier_time_censoring_data(
            bundle=bundle,
            subject_ids=subject_ids,
            time_col=_get_workload_arg(workload_args, "time_col", "time_column_id"),
            censoring_col=_get_workload_arg(workload_args, "censoring_col", "censoring_column_id"),
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            cancer_type=workload_args.get("cancer_type"),
        )

    if ct == "biomarker-kaplan-meier":
        return build_biomarker_km_dataframe(
            bundle=bundle,
            subject_ids=subject_ids,
            coeffs=workload_args.get("coeffs"),
            cutoff_value=workload_args.get("cutoff_value"),
            target_biomarker_covariates=workload_args.get("target_biomarker_covariates"),
            group_col=_get_workload_arg(workload_args, "group_col", "group_column_id"),
            time_col=_get_workload_arg(workload_args, "time_col", "time_column_id"),
            censoring_col=_get_workload_arg(workload_args, "censoring_col", "censoring_column_id"),
            epsilon=workload_args.get("epsilon"),
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            cancer_type=workload_args.get("cancer_type"),
        )

    if ct == "biomarker-subjects":
        return build_biomarker_subjects_dataframe(
            bundle=bundle,
            subject_ids=subject_ids,
            biomarker_covariates=workload_args.get("biomarker_covariates"),
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            cancer_type=workload_args.get("cancer_type"),
        )

    if ct == "mean":
        return extract_mean_data(
            bundle=bundle,
            subject_ids=subject_ids,
            data_column_id=workload_args.get("data_column_id"),
            project_id=project_id,
        )

    if ct == "stdev":
        return extract_stdev_data(
            bundle=bundle,
            subject_ids=subject_ids,
            data_column_id=workload_args.get("data_column_id"),
            project_id=project_id,
        )

    if ct == "mean-stdev":
        return extract_mean_data(
            bundle=bundle,
            subject_ids=subject_ids,
            data_column_id=workload_args.get("data_column_id"),
            project_id=project_id,
        )

    if ct == "meta-analysis":
        return extract_kaplan_meier_time_censoring_data(
            bundle=bundle,
            subject_ids=subject_ids,
            time_col=_get_workload_arg(workload_args, "time_col", "time_column_id"),
            censoring_col=_get_workload_arg(workload_args, "censoring_col", "censoring_column_id"),
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            cancer_type=workload_args.get("cancer_type"),
        )

    if ct == "chi2":
        return extract_chi2_data(
            bundle=bundle,
            subject_ids=subject_ids,
            category_column_1_id=workload_args.get("category_column_1_id"),
            category_column_2_id=workload_args.get("category_column_2_id"),
            project_id=project_id,
        )

    if ct == "t-test":
        return extract_ttest_data(
            bundle=bundle,
            subject_ids=subject_ids,
            data_column_id=workload_args.get("data_column_id"),
            category_column_1_id=workload_args.get("category_column_1_id"),
            project_id=project_id,
        )

    raise ValueError(f"Unsupported computation_type: {computation_type}")


def extract_data_for_computation_type(
    computation_type: str,
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    workload_args: Dict[str, Any],
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> pd.DataFrame:
    return extract_data_for_computation(
        computation_type=computation_type,
        workload_args=workload_args,
        bundle=bundle,
        subject_ids=subject_ids,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
