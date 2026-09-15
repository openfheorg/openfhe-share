from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
import json
import threading
from collections import OrderedDict
import requests

from .fhir_project_config import resolve_project_config_path

DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_BATCH_SIZE = 50
DEFAULT_RESOURCE_PAGE_SIZE = 2400

DEBUG = True

_PATIENT_FILTER_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}

def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[FHIR QUERY DEBUG] {msg}")


def resolve_server_url(bundle: Dict[str, Any] | str) -> str:
    if isinstance(bundle, str):
        server_url = bundle
    elif isinstance(bundle, dict):
        server_url = bundle.get("server_url")
    else:
        server_url = None
    if not isinstance(server_url, str) or not server_url.strip():
        raise ValueError("Expected a FHIR server URL string or a dict containing server_url")
    return server_url.rstrip("/")


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        }
    )
    return s


def chunked(items: Iterable[str], size: int) -> Iterable[List[str]]:
    chunk: List[str] = []
    for item in items:
        if item is None:
            continue
        s = str(item).strip()
        if not s:
            continue
        chunk.append(s)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def parse_iso_datetime(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s.strip():
        return None
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(v)
    except Exception:
        try:
            return datetime.fromisoformat(v[:19])
        except Exception:
            return None


def parse_iso_date(s: Any) -> Optional[date]:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        return None


def normalize_filters(filters: Any) -> List[Dict[str, Any]]:
    if isinstance(filters, list):
        return filters
    if isinstance(filters, dict):
        conds = filters.get("conditions")
        if isinstance(conds, list):
            return conds
    return []


# URL/HTTP fetch cache: Memoizing responses here caches URL-sourced data across workflows
_HTTP_CACHE = OrderedDict()
_HTTP_CACHE_LOCK = threading.Lock()
_HTTP_CACHE_MAX = 256


def http_get_json(
    sess: requests.Session,
    url: str,
    params: Optional[List[Tuple[str, str]]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    cache_key = (url, tuple(sorted(params)) if params else ())
    with _HTTP_CACHE_LOCK:
        if cache_key in _HTTP_CACHE:
            _HTTP_CACHE.move_to_end(cache_key)
            return _HTTP_CACHE[cache_key]

    resp = sess.get(url, params=params, timeout=timeout_seconds)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"FHIR server returned non-JSON response from {url}")

    with _HTTP_CACHE_LOCK:
        _HTTP_CACHE[cache_key] = data
        _HTTP_CACHE.move_to_end(cache_key)
        while len(_HTTP_CACHE) > _HTTP_CACHE_MAX:
            _HTTP_CACHE.popitem(last=False)
    return data


def _format_query_string(params: Optional[List[Tuple[str, str]]]) -> str:
    if not params:
        return ""
    prepared = requests.PreparedRequest()
    prepared.prepare_url("http://debug.local", params)
    url = prepared.url or ""
    if "?" not in url:
        return ""
    return url.split("?", 1)[1]


def _debug_log_request(url: str, params: Optional[List[Tuple[str, str]]]) -> None:
    qs = _format_query_string(params)
    if qs:
        _debug(f"Running query: {url}?{qs}")
    else:
        _debug(f"Running query: {url}")


def bundle_entries_from_url(
    sess: requests.Session,
    url: str,
    params: Optional[List[Tuple[str, str]]] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    next_url: Optional[str] = url
    next_params: Optional[List[Tuple[str, str]]] = params
    page_num = 0

    while next_url:
        page_num += 1
        _debug_log_request(next_url, next_params)
        bundle = http_get_json(sess, next_url, params=next_params, timeout_seconds=timeout_seconds)

        page_entries = 0
        for entry in bundle.get("entry") or []:
            resource = entry.get("resource")
            if isinstance(resource, dict):
                out.append(resource)
                page_entries += 1

        bundle_total = bundle.get("total")
        if isinstance(bundle_total, int):
            _debug(f"Page {page_num} returned {page_entries} resources, bundle total={bundle_total}")
        else:
            _debug(f"Page {page_num} returned {page_entries} resources")

        next_link = None
        for link in bundle.get("link") or []:
            if (link.get("relation") or "").strip().lower() == "next":
                next_link = link.get("url")
                break

        next_url = next_link
        next_params = None

    _debug(f"Final accumulated resource count={len(out)}")
    return out


def pid_from_ref(ref: Any) -> Optional[str]:
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith("Patient/"):
        return ref.split("/", 1)[1]
    return None


def _schema_cache_key(
    project_id: Optional[Union[int, str]],
    datasource_group_id: Optional[Union[int, str]],
) -> str:
    project_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    group_key = str(datasource_group_id).strip() if datasource_group_id is not None and str(datasource_group_id).strip() else "__default__"
    return f"{project_key}::{group_key}"


def load_patient_filter_schema(
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    cache_key = _schema_cache_key(project_id, datasource_group_id)
    cached = _PATIENT_FILTER_SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    schema_path = resolve_project_config_path(
        __package__,
        "patient_query.json",
        project_id,
        datasource_group_id=datasource_group_id,
    )
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    if not isinstance(schema, dict):
        raise ValueError(f"Expected patient filter schema JSON object in {schema_path}")

    _PATIENT_FILTER_SCHEMA_CACHE[cache_key] = schema
    _debug(
        "Loaded patient filter schema from "
        f"{schema_path} (project_id={project_id}, datasource_group_id={datasource_group_id})"
    )
    return schema


def normalize_save_target(target: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(target, dict):
        return {}
    return {
        "filter_type": str(target.get("filter_group") or "").strip(),
        "column_name": str(target.get("field") or "").strip(),
        "operator": str(target.get("operator") or "").strip(),
    }


def find_matching_condition_for_control(
    control: Dict[str, Any],
    flist: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    save = control.get("save") or {}
    targets = save.get("targets") or []
    for raw_target in targets:
        target = normalize_save_target(raw_target)
        filter_type = target.get("filter_type")
        column_name = target.get("column_name")
        operator = target.get("operator")
        if not filter_type or not column_name or not operator:
            continue

        for cond in flist:
            cond_filter_type = str(cond.get("filter_type") or "").strip()
            cond_column_name = str(cond.get("column_name") or "").strip()
            cond_operator = str(cond.get("operator") or "").strip()
            if cond_filter_type == filter_type and cond_column_name == column_name and cond_operator == operator:
                _debug(
                    f"Matched condition to control id={control.get('id')} "
                    f"filter_type={cond_filter_type} column_name={cond_column_name} operator={cond_operator}"
                )
                return cond
    return None


def stringify_query_value(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return ",".join(str(x).strip() for x in val if x is not None and str(x).strip())
    return str(val).strip()


def _first_save_target_for_control(control: Dict[str, Any]) -> Dict[str, Any]:
    save = control.get("save") or {}
    targets = save.get("targets") or []
    for raw_target in targets:
        target = normalize_save_target(raw_target)
        if target.get("filter_type") and target.get("column_name") and target.get("operator"):
            return target
    return {}


def synthesize_default_condition_for_control(control: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the condition implied by a patient-query control's default.

    This deliberately mirrors the historical remote Patient endpoint behavior in
    ``build_patient_search_params``.  The local-bundle path uses the same helper so
    switching a datasource from HAPI to a JSON bundle does not change the cohort.
    """
    control_id = str(control.get("id") or "").strip()
    query = control.get("query") or {}
    kind = str(query.get("kind") or "").strip()
    param = str(query.get("param") or "").strip()
    target = _first_save_target_for_control(control)
    if not target:
        return None

    today = date.today()
    today_iso = today.isoformat()

    if control_id == "birthDate" and kind == "date-range" and param == "birthdate":
        # Keep the existing endpoint semantics exactly: 100 years before today's
        # month/day through today.
        try:
            start = date(today.year - 100, today.month, today.day)
        except ValueError:
            # Feb 29 on a non-leap target year.
            start = date(today.year - 100, today.month, 28)
        values = [start.isoformat(), today_iso]
    elif control_id == "death-date" and kind == "date-range" and param == "death-date":
        values = ["2000-01-01", today_iso]
    else:
        return None

    return {
        "filter_type": target["filter_type"],
        "column_name": target["column_name"],
        "operator": target["operator"],
        "value": ",".join(values),
        "values": values,
        "__default__": True,
    }


def resolve_patient_filter_controls(
    filters: Any,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
    include_defaults: bool = True,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Resolve stored filter conditions back onto the patient-query schema.

    The frontend, MySQL filter store, remote HAPI query builder, and local JSON
    traversal all meet at this representation.  Matching is intentionally based on
    the save target triple (filter_type, column_name, operator), not on ad-hoc
    column-name checks.
    """
    flist = normalize_filters(filters)
    schema = load_patient_filter_schema(
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    resolved: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    for control in schema.get("controls") or []:
        if not isinstance(control, dict):
            continue
        condition = find_matching_condition_for_control(control, flist)
        if condition is None and include_defaults:
            condition = synthesize_default_condition_for_control(control)
        if condition is not None:
            resolved.append((control, condition))

    return resolved


def condition_values(condition: Dict[str, Any]) -> List[str]:
    """Read multi-valued conditions from either current or legacy storage shape."""
    values = condition.get("values")
    if isinstance(values, list):
        return ["" if value is None else str(value).strip() for value in values]

    raw = condition.get("value")
    if raw is None:
        return []
    if isinstance(raw, list):
        return ["" if value is None else str(value).strip() for value in raw]

    # FiltersManager reconstructs ``values`` for BETWEEN/IN today, but older
    # staged payloads can contain only the CSV ``value``.  Patient filters do not
    # currently use escaped commas inside individual values, so this is the same
    # compatibility rule the historical query path effectively used.
    return [part.strip() for part in str(raw).split(",")]


def serialize_condition_to_query_parts(
    control: Dict[str, Any],
    condition: Dict[str, Any],
) -> List[Tuple[str, str]]:
    query = control.get("query")
    if not isinstance(query, dict):
        return []

    kind = str(query.get("kind") or "").strip()
    if not kind:
        return []

    if kind == "search-param":
        param = str(query.get("param") or "").strip()
        raw_value = stringify_query_value(condition.get("value"))
        if not param or raw_value == "":
            return []
        return [(param, raw_value)]

    if kind == "date-range":
        param = str(query.get("param") or "").strip()
        if not param:
            return []
        values = condition.get("values")
        if not isinstance(values, list):
            return []
        start = str(values[0] if len(values) > 0 and values[0] is not None else "").strip()
        end = str(values[1] if len(values) > 1 and values[1] is not None else "").strip()
        parts: List[Tuple[str, str]] = []
        if start:
            parts.append((param, f"{str(query.get('startPrefix') or 'ge').strip()}{start}"))
        if end:
            parts.append((param, f"{str(query.get('endPrefix') or 'le').strip()}{end}"))
        return parts

    if kind == "reverse-chain-token":
        resource = str(query.get("resource") or "").strip()
        reference_param = str(query.get("referenceParam") or "").strip()
        param = str(query.get("param") or "").strip()
        raw_value = stringify_query_value(condition.get("value"))
        if not resource or not reference_param or not param or raw_value == "":
            return []
        return [(f"_has:{resource}:{reference_param}:{param}", raw_value)]

    return []


def build_patient_search_params(
    filters: Any,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> List[Tuple[str, str]]:
    params: List[Tuple[str, str]] = [("_count", str(DEFAULT_RESOURCE_PAGE_SIZE))]
    resolved = resolve_patient_filter_controls(
        filters,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        include_defaults=True,
    )

    _debug(f"Building patient search params from {len(resolved)} resolved controls")

    for control, condition in resolved:
        control_params = serialize_condition_to_query_parts(control, condition)
        if control_params:
            suffix = " [default]" if condition.get("__default__") else ""
            _debug(f"Control id={control.get('id')} produced params={control_params}{suffix}")
            params.extend(control_params)

    _debug(f"Built patient search params={params}")
    return params


def fetch_patients_prefiltered(
    sess: requests.Session,
    server_url: str,
    filters: Any,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> List[Dict[str, Any]]:
    params = build_patient_search_params(
        filters,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )
    patients = bundle_entries_from_url(sess, f"{server_url}/Patient", params=params)
    _debug(f"fetch_patients_prefiltered returned {len(patients)} Patient resources")
    return patients


def query_patients(
    filters: Any,
    bundle: Dict[str, Any] | str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    server_url = resolve_server_url(bundle)
    _debug(f"Resolved server URL={server_url}")
    sess = session()
    patients_raw = fetch_patients_prefiltered(
        sess,
        server_url,
        filters,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
    )

    patients: Dict[str, Dict[str, Any]] = {}
    for res in patients_raw:
        if res.get("resourceType") != "Patient":
            continue
        pid = res.get("id")
        if isinstance(pid, str) and pid.strip():
            patients[pid] = res

    _debug(f"query_patients unique patient count={len(patients)}")
    return patients


def query_patient_ids(
    filters: Any,
    bundle: Dict[str, Any] | str,
    project_id: Optional[Union[int, str]] = None,
    datasource_group_id: Optional[Union[int, str]] = None,
) -> List[str]:
    patient_ids = list(
        query_patients(
            filters,
            bundle,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
        ).keys()
    )
    _debug(f"query_patient_ids returning {len(patient_ids)} ids")
    return patient_ids
