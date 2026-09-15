from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from .fhir_patient_query_engine import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RESOURCE_PAGE_SIZE,
    _debug,
    bundle_entries_from_url,
    chunked,
    pid_from_ref,
    session,
)
from .fhir_project_config import resolve_project_config_path
from .fhir_analysis_data_engine import load_analysis_data_schema
from .fhir_observation_query_engine import get_cached_observations_by_patient

_ANALYSIS_QUERY_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_ANALYSIS_PATIENT_CACHE: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
_ANALYSIS_OBSERVATION_CACHE: Dict[Tuple[str, str, str, str], Dict[str, List[Dict[str, Any]]]] = {}
_ANALYSIS_MEDICATION_CACHE: Dict[Tuple[str, str, str, str], Dict[str, Dict[str, Set[str]]]] = {}


@dataclass(frozen=True)
class AnalysisFetchPlan:
    needs_patient: bool
    needs_observation: bool
    needs_medication: bool
    observation_params: Dict[str, List[str]]
    observation_signature: str
    observation_param_sets: List[Dict[str, List[str]]]
    observation_signatures: List[str]
    medication_params: Dict[str, List[str]]
    medication_signature: str


def load_analysis_query_schema(project_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
    cache_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    cached = _ANALYSIS_QUERY_SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        schema_path = resolve_project_config_path(__package__, "analysis_query.json", project_id)
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        if not isinstance(schema, dict):
            raise ValueError(f"Expected analysis query schema JSON object in {schema_path}")
        _debug(f"Loaded analysis query schema from {schema_path}")
    except FileNotFoundError:
        schema = {
            "version": "2.0",
            "computations": {}
        }
        _debug("analysis_query.json not found; using analysis_data-driven fallback for fetch planning")

    _ANALYSIS_QUERY_SCHEMA_CACHE[cache_key] = schema
    return schema


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_column_id(value: Any) -> str:
    return _normalize_text(value).lower()


def _signature_from_params(resource_type: str, params: Dict[str, Set[str]]) -> str:
    payload = {
        "resourceType": resource_type,
        "params": {k: sorted(v) for k, v in sorted(params.items())},
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _empty_plan() -> AnalysisFetchPlan:
    return AnalysisFetchPlan(
        needs_patient=False,
        needs_observation=False,
        needs_medication=False,
        observation_params={},
        observation_signature="none",
        observation_param_sets=[],
        observation_signatures=[],
        medication_params={},
        medication_signature="none",
    )


def _expand_param_values(param: Dict[str, Any]) -> List[str]:
    raw_values = param.get("values")
    if isinstance(raw_values, list):
        return [_normalize_text(v) for v in raw_values if _normalize_text(v)]
    raw_value = _normalize_text(param.get("value"))
    if raw_value:
        return [raw_value]
    return []


def _normalize_param_sets(param_sets: List[Dict[str, Set[str]]]) -> Tuple[List[Dict[str, List[str]]], List[str]]:
    deduped: Dict[str, Dict[str, List[str]]] = {}
    for param_set in param_sets:
        signature = _signature_from_params("Observation", param_set)
        if signature in deduped:
            continue
        deduped[signature] = {k: sorted(v) for k, v in param_set.items()}
    signatures = list(deduped.keys())
    normalized = [deduped[sig] for sig in signatures]
    return normalized, signatures


def build_analysis_fetch_plan(
    computation_type: str,
    workload_args: Dict[str, Any],
    project_id: Optional[Union[int, str]] = None,
) -> AnalysisFetchPlan:
    query_schema = load_analysis_query_schema(project_id=project_id)
    query_computations = query_schema.get("computations") or {}
    query_comp_block = query_computations.get(_normalize_text(computation_type))
    query_properties = query_comp_block.get("properties") if isinstance(query_comp_block, dict) else {}
    query_properties = query_properties or {}

    try:
        data_schema = load_analysis_data_schema(project_id=project_id)
        data_computations = data_schema.get("computations") or {}
        data_comp_block = data_computations.get(_normalize_text(computation_type))
        data_properties = data_comp_block.get("properties") if isinstance(data_comp_block, dict) else {}
        data_properties = data_properties or {}
    except FileNotFoundError:
        data_properties = {}

    if not query_properties and not data_properties:
        return _empty_plan()

    needs_patient = False
    needs_observation = False
    needs_medication = False
    observation_params: Dict[str, Set[str]] = {}
    observation_param_sets_raw: List[Dict[str, Set[str]]] = []
    medication_params: Dict[str, Set[str]] = {}

    property_keys = set(query_properties.keys()) | set(data_properties.keys())

    for property_key in property_keys:
        selected_column = workload_args.get(property_key)
        column_id = _normalize_column_id(selected_column)
        if not column_id:
            continue

        data_columns = ((data_properties.get(property_key) or {}).get("columns") or {})
        data_rule = data_columns.get(column_id)
        if isinstance(data_rule, dict):
            data_resource_type = _normalize_text(data_rule.get("resourceType"))
            if data_resource_type == "Patient":
                needs_patient = True
            elif data_resource_type == "Observation":
                needs_observation = True
            elif data_resource_type == "MedicationStatement":
                needs_medication = True

        query_columns = ((query_properties.get(property_key) or {}).get("columns") or {})
        query_column_block = query_columns.get(column_id)
        if not isinstance(query_column_block, dict):
            continue

        for resource_rule in query_column_block.get("resources") or []:
            resource_type = _normalize_text(resource_rule.get("resourceType"))
            if not resource_type:
                continue

            params = resource_rule.get("params") or []

            if resource_type == "Patient":
                needs_patient = True
                continue

            if resource_type == "Observation":
                needs_observation = True
                param_set: Dict[str, Set[str]] = {}
                for param in params:
                    name = _normalize_text(param.get("name"))
                    if not name:
                        continue
                    for value in _expand_param_values(param):
                        observation_params.setdefault(name, set()).add(value)
                        param_set.setdefault(name, set()).add(value)
                if param_set:
                    observation_param_sets_raw.append(param_set)
                continue

            if resource_type == "MedicationStatement":
                needs_medication = True
                for param in params:
                    name = _normalize_text(param.get("name"))
                    if not name:
                        continue
                    for value in _expand_param_values(param):
                        medication_params.setdefault(name, set()).add(value)
                continue

    normalized_observation_params = {k: sorted(v) for k, v in observation_params.items()}
    normalized_observation_param_sets, observation_signatures = _normalize_param_sets(observation_param_sets_raw)
    normalized_medication_params = {k: sorted(v) for k, v in medication_params.items()}

    observation_signature = _signature_from_params("Observation", observation_params)
    if needs_observation and not normalized_observation_params and not normalized_observation_param_sets:
        observation_signature = "__broad__"

    return AnalysisFetchPlan(
        needs_patient=needs_patient,
        needs_observation=needs_observation,
        needs_medication=needs_medication,
        observation_params=normalized_observation_params,
        observation_signature=observation_signature,
        observation_param_sets=normalized_observation_param_sets,
        observation_signatures=observation_signatures,
        medication_params=normalized_medication_params,
        medication_signature=_signature_from_params("MedicationStatement", medication_params),
    )


def _build_subject_cache_key(
    server_url: str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Tuple[str, str, str]:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    wanted = sorted({str(pid).strip() for pid in subject_ids if str(pid).strip()})
    signature = json.dumps(wanted, separators=(",", ":"))
    return project_key, server_url, hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _build_analysis_resource_cache_key(
    server_url: str,
    computation_type: str,
    subject_ids: Iterable[str],
    resource_signature: str,
    project_id: Optional[Union[int, str]] = None,
) -> Tuple[str, str, str, str, str]:
    project_key, _, subject_hash = _build_subject_cache_key(server_url, subject_ids, project_id=project_id)
    return (
        project_key,
        server_url,
        _normalize_text(computation_type),
        subject_hash,
        _normalize_text(resource_signature) or "none",
    )


def _fetch_patients_by_ids(sess, server_url: str, subject_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in chunked(subject_ids, DEFAULT_BATCH_SIZE):
        params = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)), ("_id", ",".join(chunk))]
        out.extend(bundle_entries_from_url(sess, f"{server_url}/Patient", params=params))
    return out


def _fetch_observations_by_subject_ids(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
    extra_params: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    refs = [f"Patient/{sid}" for sid in subject_ids if str(sid).strip()]
    extra_params = extra_params or {}

    for chunk in chunked(refs, DEFAULT_BATCH_SIZE):
        params: List[Tuple[str, str]] = [
            ("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)),
            ("subject", ",".join(chunk)),
        ]
        for key, values in sorted(extra_params.items()):
            normalized_values = sorted({_normalize_text(v) for v in values if _normalize_text(v)})
            if normalized_values:
                params.append((key, ",".join(normalized_values)))
        out.extend(bundle_entries_from_url(sess, f"{server_url}/Observation", params=params))
    return out


def _fetch_medication_statements_by_subject_ids(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
    extra_params: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    refs = [f"Patient/{sid}" for sid in subject_ids if str(sid).strip()]
    extra_params = extra_params or {}

    for chunk in chunked(refs, DEFAULT_BATCH_SIZE):
        params: List[Tuple[str, str]] = [
            ("_count", str(DEFAULT_RESOURCE_PAGE_SIZE)),
            ("subject", ",".join(chunk)),
        ]
        for key, values in sorted(extra_params.items()):
            normalized_values = sorted({_normalize_text(v) for v in values if _normalize_text(v)})
            if normalized_values:
                params.append((key, ",".join(normalized_values)))
        out.extend(bundle_entries_from_url(sess, f"{server_url}/MedicationStatement", params=params))
    return out


def _fetch_patients_map(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    cache_key = _build_subject_cache_key(server_url, wanted, project_id=project_id)
    cached = _ANALYSIS_PATIENT_CACHE.get(cache_key)
    if cached is not None:
        print("\n" + "=" * 100)
        print("ANALYSIS PATIENT CACHE HIT")
        print(f"cache_key={cache_key}")
        print(f"cache_entries={len(_ANALYSIS_PATIENT_CACHE)}")
        print("=" * 100 + "\n")
        return {pid: dict(cached[pid]) for pid in wanted if pid in cached}

    patients_raw = _fetch_patients_by_ids(sess, server_url, wanted)
    patients: Dict[str, Dict[str, Any]] = {}
    for res in patients_raw:
        if res.get("resourceType") == "Patient" and res.get("id"):
            patients[res["id"]] = res

    _ANALYSIS_PATIENT_CACHE[cache_key] = {pid: dict(patient) for pid, patient in patients.items()}

    print("\n" + "=" * 100)
    print("ANALYSIS PATIENT CACHE STORE")
    print(f"cache_key={cache_key}")
    print(f"cache_entries={len(_ANALYSIS_PATIENT_CACHE)}")
    print("=" * 100 + "\n")

    return {pid: dict(patient) for pid, patient in patients.items()}


def _fetch_observation_map_for_param_set(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
    computation_type: str,
    observation_params: Dict[str, List[str]],
    observation_signature: str,
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    cache_key = _build_analysis_resource_cache_key(server_url, computation_type, wanted, observation_signature, project_id=project_id)
    cached = _ANALYSIS_OBSERVATION_CACHE.get(cache_key)
    if cached is not None:
        print("\n" + "=" * 100)
        print("ANALYSIS OBSERVATION CACHE HIT")
        print(f"cache_key={cache_key}")
        print(f"cache_entries={len(_ANALYSIS_OBSERVATION_CACHE)}")
        print("=" * 100 + "\n")
        return {pid: list(cached.get(pid, [])) for pid in wanted}

    patient_obs: Dict[str, List[Dict[str, Any]]] = {pid: [] for pid in wanted}
    obs_raw = _fetch_observations_by_subject_ids(sess, server_url, wanted, observation_params)
    for res in obs_raw:
        if res.get("resourceType") != "Observation":
            continue
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if pid in patient_obs:
            patient_obs[pid].append(res)

    _ANALYSIS_OBSERVATION_CACHE[cache_key] = {pid: list(obs) for pid, obs in patient_obs.items()}

    print("\n" + "=" * 100)
    print("ANALYSIS OBSERVATION CACHE STORE")
    print(f"cache_key={cache_key}")
    print(f"cache_entries={len(_ANALYSIS_OBSERVATION_CACHE)}")
    print("=" * 100 + "\n")

    return {pid: list(obs) for pid, obs in patient_obs.items()}


def _merge_patient_observation_maps(
    wanted: List[str],
    maps: List[Dict[str, List[Dict[str, Any]]]],
) -> Dict[str, List[Dict[str, Any]]]:
    merged: Dict[str, List[Dict[str, Any]]] = {pid: [] for pid in wanted}
    seen_ids: Dict[str, Set[str]] = {pid: set() for pid in wanted}

    for obs_map in maps:
        for pid in wanted:
            for obs in obs_map.get(pid, []):
                oid = str(obs.get("id") or "").strip()
                if oid:
                    if oid in seen_ids[pid]:
                        continue
                    seen_ids[pid].add(oid)
                merged[pid].append(obs)

    return merged


def _fetch_observation_map(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
    computation_type: str,
    observation_params: Dict[str, List[str]],
    observation_signature: str,
    observation_param_sets: Optional[List[Dict[str, List[str]]]] = None,
    observation_signatures: Optional[List[str]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    param_sets = observation_param_sets or []
    signatures = observation_signatures or []

    if not param_sets:
        return _fetch_observation_map_for_param_set(
            sess=sess,
            server_url=server_url,
            subject_ids=wanted,
            computation_type=computation_type,
            observation_params=observation_params,
            observation_signature=observation_signature,
            project_id=project_id,
        )

    maps: List[Dict[str, List[Dict[str, Any]]]] = []
    for idx, param_set in enumerate(param_sets):
        sig = signatures[idx] if idx < len(signatures) else _signature_from_params(
            "Observation",
            {k: set(v) for k, v in param_set.items()},
        )
        maps.append(
            _fetch_observation_map_for_param_set(
                sess=sess,
                server_url=server_url,
                subject_ids=wanted,
                computation_type=computation_type,
                observation_params=param_set,
                observation_signature=sig,
                project_id=project_id,
            )
        )

    return _merge_patient_observation_maps(wanted, maps)


def _fetch_medication_map(
    sess,
    server_url: str,
    subject_ids: Iterable[str],
    computation_type: str,
    medication_params: Dict[str, List[str]],
    medication_signature: str,
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, Dict[str, Set[str]]]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    cache_key = _build_analysis_resource_cache_key(server_url, computation_type, wanted, medication_signature, project_id=project_id)
    cached = _ANALYSIS_MEDICATION_CACHE.get(cache_key)
    if cached is not None:
        print("\n" + "=" * 100)
        print("ANALYSIS MEDICATION CACHE HIT")
        print(f"cache_key={cache_key}")
        print(f"cache_entries={len(_ANALYSIS_MEDICATION_CACHE)}")
        print("=" * 100 + "\n")
        return {
            pid: {
                "tokens": set(cached.get(pid, {}).get("tokens") or set()),
                "names": set(cached.get(pid, {}).get("names") or set()),
            }
            for pid in wanted
        }

    patient_meds: Dict[str, Dict[str, Set[str]]] = {pid: {"tokens": set(), "names": set()} for pid in wanted}
    meds_raw = _fetch_medication_statements_by_subject_ids(sess, server_url, wanted, medication_params)
    for res in meds_raw:
        if res.get("resourceType") != "MedicationStatement":
            continue
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if not pid or pid not in patient_meds:
            continue
        cc = res.get("medicationCodeableConcept") or {}
        for cd in (cc.get("coding") or []):
            disp = (cd.get("display") or "").strip()
            if disp:
                patient_meds[pid]["names"].add(disp)
            sys = (cd.get("system") or "").strip()
            code = (cd.get("code") or "").strip()
            if sys and code:
                patient_meds[pid]["tokens"].add(f"{sys}|{code}".lower())
        text = (cc.get("text") or "").strip() if isinstance(cc, dict) else ""
        if text:
            patient_meds[pid]["names"].add(text)
        med_ref = res.get("medicationReference") or {}
        med_disp = (med_ref.get("display") or "").strip() if isinstance(med_ref, dict) else ""
        if med_disp:
            patient_meds[pid]["names"].add(med_disp)

    _ANALYSIS_MEDICATION_CACHE[cache_key] = {
        pid: {"tokens": set(meds["tokens"]), "names": set(meds["names"])}
        for pid, meds in patient_meds.items()
    }

    print("\n" + "=" * 100)
    print("ANALYSIS MEDICATION CACHE STORE")
    print(f"cache_key={cache_key}")
    print(f"cache_entries={len(_ANALYSIS_MEDICATION_CACHE)}")
    print("=" * 100 + "\n")

    return {
        pid: {"tokens": set(meds["tokens"]), "names": set(meds["names"])}
        for pid, meds in patient_meds.items()
    }


def fetch_analysis_subject_context(
    server_url: str,
    subject_ids: Iterable[str],
    computation_type: str,
    workload_args: Dict[str, Any],
    project_id: Optional[Union[int, str]] = None,
) -> Tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, Dict[str, Set[str]]],
]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}, {}, {}

    plan = build_analysis_fetch_plan(computation_type, workload_args, project_id=project_id)
    sess = session()

    if plan.needs_patient:
        patients = _fetch_patients_map(sess, server_url, wanted, project_id=project_id)
    else:
        patients = {pid: {"id": pid} for pid in wanted}

    if plan.needs_observation:
        if plan.observation_signature == "__broad__":
            _debug("Analysis fetch plan using shared broad observation cache")
            patient_obs = get_cached_observations_by_patient(server_url, wanted, project_id=project_id)
        else:
            patient_obs = _fetch_observation_map(
                sess=sess,
                server_url=server_url,
                subject_ids=wanted,
                computation_type=computation_type,
                observation_params=plan.observation_params,
                observation_signature=plan.observation_signature,
                observation_param_sets=plan.observation_param_sets,
                observation_signatures=plan.observation_signatures,
                project_id=project_id,
            )
    else:
        patient_obs = {pid: [] for pid in wanted}

    if plan.needs_medication:
        patient_meds = _fetch_medication_map(
            sess=sess,
            server_url=server_url,
            subject_ids=wanted,
            computation_type=computation_type,
            medication_params=plan.medication_params,
            medication_signature=plan.medication_signature,
            project_id=project_id,
        )
    else:
        patient_meds = {pid: {"tokens": set(), "names": set()} for pid in wanted}

    return patients, patient_obs, patient_meds
