from __future__ import annotations

import hashlib


from typing import Any, Dict, Iterable, List, Optional, Union
import json

from .fhir_project_config import resolve_project_config_path
from .fhir_patient_query_engine import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RESOURCE_PAGE_SIZE,
    _debug,
    bundle_entries_from_url,
    chunked,
    find_matching_condition_for_control,
    normalize_filters,
    pid_from_ref,
    resolve_server_url,
    serialize_condition_to_query_parts,
    session,
)

_OBSERVATION_FILTER_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_OBSERVATION_BROAD_CACHE: Dict[tuple[str, str, str], Dict[str, List[Dict[str, Any]]]] = {}


def load_observation_filter_schema(project_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
    cache_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    cached = _OBSERVATION_FILTER_SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        schema_path = resolve_project_config_path(__package__, "observation_query.json", project_id)
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        if not isinstance(schema, dict):
            raise ValueError(f"Expected observation filter schema JSON object in {schema_path}")
        _debug(f"Loaded observation filter schema from {schema_path}")
    except FileNotFoundError:
        schema = {
            "version": "2.0",
            "resource": {
                "type": "Observation"
            },
            "controls": []
        }
        _debug("observation_query.json not found; using empty observation query schema")

    _OBSERVATION_FILTER_SCHEMA_CACHE[cache_key] = schema
    return schema


def build_observation_search_params(filters: Any, project_id: Optional[Union[int, str]] = None) -> List[tuple[str, str]]:
    flist = normalize_filters(filters)
    params: List[tuple[str, str]] = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE))]
    schema = load_observation_filter_schema(project_id=project_id)
    controls = schema.get("controls") or []

    _debug(f"Building observation search params from {len(flist)} filters")

    for control in controls:
        if not isinstance(control, dict):
            continue
        condition = find_matching_condition_for_control(control, flist)
        if not condition:
            continue
        control_params = serialize_condition_to_query_parts(control, condition)
        if control_params:
            _debug(f"Observation control id={control.get('id')} produced params={control_params}")
            params.extend(control_params)

    _debug(f"Built observation search params={params}")
    return params




def _build_subject_cache_key(
    server_url: str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> tuple[str, str, str]:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    wanted = sorted({str(pid).strip() for pid in subject_ids if str(pid).strip()})
    signature = json.dumps(wanted, separators=(",", ":"))
    return project_key, server_url, hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _get_cached_observation_subset(
    server_url: str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    wanted_set = set(wanted)
    for (cached_project_key, cached_server_url, _), cached_map in _OBSERVATION_BROAD_CACHE.items():
        if cached_project_key != project_key or cached_server_url != server_url:
            continue
        if wanted_set.issubset(set(cached_map.keys())):
            _debug(
                f"Observation broad cache subset hit requested={len(wanted_set)} "
                f"cached_patients={len(cached_map)} entries={len(_OBSERVATION_BROAD_CACHE)}"
            )
            return {pid: list(cached_map.get(pid, [])) for pid in wanted}

    return None


def get_cached_observations_by_patient(
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    server_url = resolve_server_url(bundle)
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]
    if not wanted:
        return {}

    cache_key = _build_subject_cache_key(server_url, wanted, project_id=project_id)
    cached = _OBSERVATION_BROAD_CACHE.get(cache_key)
    if cached is not None:
        _debug(f"Observation broad cache hit key={cache_key} entries={len(_OBSERVATION_BROAD_CACHE)}")
        return {pid: list(cached.get(pid, [])) for pid in wanted}

    subset_cached = _get_cached_observation_subset(server_url, wanted, project_id=project_id)
    if subset_cached is not None:
        return subset_cached

    patient_obs: Dict[str, List[Dict[str, Any]]] = {pid: [] for pid in wanted}
    observations = query_observations([], server_url, wanted, project_id=project_id)

    for res in observations:
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if pid in patient_obs:
            patient_obs[pid].append(res)

    _OBSERVATION_BROAD_CACHE[cache_key] = {pid: list(obs) for pid, obs in patient_obs.items()}
    _debug(f"Observation broad cache store key={cache_key} entries={len(_OBSERVATION_BROAD_CACHE)}")
    return {pid: list(obs) for pid, obs in patient_obs.items()}

def fetch_observations_prefiltered(
    server_url: str,
    filters: Any,
    subject_ids: Optional[Iterable[str]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> List[Dict[str, Any]]:
    sess = session()
    base_params = build_observation_search_params(filters, project_id=project_id)
    out: List[Dict[str, Any]] = []

    refs = [f"Patient/{str(sid).strip()}" for sid in (subject_ids or []) if str(sid).strip()]
    if refs:
        for chunk in chunked(refs, DEFAULT_BATCH_SIZE):
            params = list(base_params)
            params.append(("subject", ",".join(chunk)))
            out.extend(bundle_entries_from_url(sess, f"{server_url}/Observation", params=params))
    else:
        out.extend(bundle_entries_from_url(sess, f"{server_url}/Observation", params=base_params))

    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for res in out:
        if res.get("resourceType") != "Observation":
            continue
        oid = str(res.get("id") or "").strip()
        if oid and oid in seen:
            continue
        if oid:
            seen.add(oid)
        deduped.append(res)

    _debug(f"fetch_observations_prefiltered returned {len(deduped)} Observation resources")
    return deduped


def query_observations(
    filters: Any,
    bundle: Dict[str, Any] | str,
    subject_ids: Optional[Iterable[str]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> List[Dict[str, Any]]:
    server_url = resolve_server_url(bundle)
    _debug(f"Resolved server URL={server_url}")
    return fetch_observations_prefiltered(server_url, filters, subject_ids, project_id=project_id)


def query_observations_by_patient(
    filters: Any,
    bundle: Dict[str, Any] | str,
    subject_ids: Iterable[str],
    project_id: Optional[Union[int, str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    wanted = [str(pid).strip() for pid in subject_ids if str(pid).strip()]

    base_params = build_observation_search_params(filters, project_id=project_id)
    if len(base_params) == 1 and base_params[0][0] == "_count":
        patient_obs = get_cached_observations_by_patient(bundle, wanted, project_id=project_id)
        _debug(
            "query_observations_by_patient counts="
            + str({pid: len(obs) for pid, obs in patient_obs.items()})
        )
        return patient_obs

    patient_obs: Dict[str, List[Dict[str, Any]]] = {pid: [] for pid in wanted}
    observations = query_observations(filters, bundle, wanted, project_id=project_id)

    for res in observations:
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if pid in patient_obs:
            patient_obs[pid].append(res)

    _debug(
        "query_observations_by_patient counts="
        + str({pid: len(obs) for pid, obs in patient_obs.items()})
    )
    return patient_obs


def query_observation_patient_ids(
    filters: Any,
    bundle: Dict[str, Any] | str,
    subject_ids: Optional[Iterable[str]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> List[str]:
    observations = query_observations(filters, bundle, subject_ids, project_id=project_id)
    out: List[str] = []
    seen: set[str] = set()

    for res in observations:
        pid = pid_from_ref(((res.get("subject") or {}).get("reference")))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)

    _debug(f"query_observation_patient_ids returning {len(out)} ids")
    return out
