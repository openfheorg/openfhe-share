from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Union
import json
import re

from .fhir_project_config import resolve_project_config_path

LOINC = "http://loinc.org"
DEBUG = False

_OBSERVATION_DATA_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


def load_observation_data_schema(project_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
    cache_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    cached = _OBSERVATION_DATA_SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    schema_path = resolve_project_config_path(__package__, "observation_data.json", project_id)
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    if not isinstance(schema, dict):
        raise ValueError(f"Expected observation data schema JSON object in {schema_path}")

    controls = schema.get("controls") or []
    local_pass = schema.get("localPass") or {}
    observation_model = local_pass.get("observationModel") or {}
    patient_metrics = local_pass.get("patientMetrics") or {}
    if DEBUG:
        print(
            "[OBS DATA ENGINE] Loaded observation_data schema:",
            f"controls={len(controls)}",
            f"observation_model_fields={list(observation_model.keys())}",
            f"patient_metrics={list(patient_metrics.keys())}",
        )

    _OBSERVATION_DATA_SCHEMA_CACHE[cache_key] = schema
    return schema


class FHIRObservationDataEngine:
    def __init__(
        self,
        schema: Optional[Dict[str, Any]] = None,
        project_id: Optional[Union[int, str]] = None,
    ):
        self.project_id = project_id
        self.schema = schema or load_observation_data_schema(project_id=project_id)
        self.controls = self.schema.get("controls") or []
        self.local_pass = self.schema.get("localPass") or {}
        self.observation_model = self.local_pass.get("observationModel") or {}
        self.patient_metrics = self.local_pass.get("patientMetrics") or {}

    def patient_satisfies_filters(
        self,
        observations: List[Dict[str, Any]],
        conditions: List[Dict[str, Any]],
    ) -> bool:
        normalized = [self._normalize_observation(obs) for obs in observations or []]
        metrics = self._build_patient_metrics(normalized)

        active_conditions = [
            cond
            for cond in conditions or []
            if str(cond.get("filter_type") or "").strip().upper() in {"OBSERVATION", "OBSERVATION_DATA"}
        ]

        if active_conditions and DEBUG:
            print(
                "[OBS DATA ENGINE] Evaluating patient:",
                f"observations={len(observations or [])}",
                f"normalized={len(normalized)}",
                f"active_conditions={len(active_conditions)}",
            )
            print("[OBS DATA ENGINE] Computed metrics:", metrics)

        for condition in active_conditions:
            control = self._find_control_for_condition(condition)
            if not control:
                if DEBUG:
                    print(
                        "[OBS DATA ENGINE] No control match for condition:",
                        {
                            "filter_type": condition.get("filter_type"),
                            "column_name": condition.get("column_name"),
                            "operator": condition.get("operator"),
                            "value": condition.get("value"),
                            "values": condition.get("values"),
                        },
                    )
                continue

            rule = control.get("localPass") or {}
            metric_name = str(rule.get("metric") or "").strip()
            operator = str(rule.get("operator") or "").strip()
            value_from = str(rule.get("valueFrom") or "").strip() or "value"

            if not metric_name or not operator:
                if DEBUG:
                    print(
                        "[OBS DATA ENGINE] Control matched but localPass rule incomplete:",
                        {
                            "label": control.get("label"),
                            "metric": metric_name,
                            "operator": operator,
                            "valueFrom": value_from,
                        },
                    )
                continue

            actual = metrics.get(metric_name)
            expected = self._get_condition_value(condition, value_from)
            passed = self._compare(actual, operator, expected)

            if DEBUG:
                print(
                    "[OBS DATA ENGINE] Rule check:",
                    {
                        "label": control.get("label"),
                        "metric": metric_name,
                        "operator": operator,
                        "valueFrom": value_from,
                        "actual": actual,
                        "expected": expected,
                        "passed": passed,
                    },
                )

            if not passed:
                return False

        return True

    def _find_control_for_condition(self, condition: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cond_filter_type = str(condition.get("filter_type") or "").strip()
        cond_column_name = str(condition.get("column_name") or "").strip()
        cond_operator = str(condition.get("operator") or "").strip()

        for control in self.controls:
            save = control.get("save") or {}
            targets = save.get("targets") or []
            for target in targets:
                target_filter_type = str(target.get("filter_group") or "").strip()
                target_field = str(target.get("field") or "").strip()
                target_operator = str(target.get("operator") or "").strip()
                if (
                    target_filter_type == cond_filter_type
                    and target_field == cond_column_name
                    and target_operator == cond_operator
                ):
                    if DEBUG:
                        print(
                            "[OBS DATA ENGINE] Matched condition to control:",
                            {
                                "label": control.get("label"),
                                "filter_type": cond_filter_type,
                                "field": cond_column_name,
                                "operator": cond_operator,
                            },
                        )
                    return control
        return None

    def _normalize_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, rule in self.observation_model.items():
            extractor = str((rule or {}).get("extractor") or "").strip()
            args = (rule or {}).get("args") or {}
            out[key] = self._run_extractor(extractor, observation, args)
        return out

    def _run_extractor(self, extractor: str, observation: Dict[str, Any], args: Dict[str, Any]) -> Any:
        if extractor == "interpretation_positive":
            return self._extract_interpretation_positive(observation)
        if extractor == "component_or_text_code":
            return self._extract_component_or_text_code(observation, args)
        if extractor == "component_or_id_region":
            return self._extract_component_or_id_region(observation, args)
        return None

    def _extract_interpretation_positive(self, observation: Dict[str, Any]) -> bool:
        interps = observation.get("interpretation") or []
        for cc in interps:
            for cd in (cc.get("coding") or []):
                code = str(cd.get("code") or "").strip().upper()
                disp = str(cd.get("display") or "").strip().lower()
                if code == "POS" or disp == "positive":
                    return True

        vs = observation.get("valueString")
        if isinstance(vs, str) and vs.strip():
            val = vs.strip().upper()
            if val == "MUT":
                return True
            if val == "WT":
                return False

        vb = observation.get("valueBoolean")
        if vb is True:
            return True
        if vb is False:
            return False

        vcc = observation.get("valueCodeableConcept") or {}
        text = str(vcc.get("text") or "").strip().lower() if isinstance(vcc, dict) else ""
        if text in {"positive", "mut"}:
            return True
        if text in {"negative", "wt"}:
            return False

        for cd in (vcc.get("coding") or []) if isinstance(vcc, dict) else []:
            code = str(cd.get("code") or "").strip().lower()
            disp = str(cd.get("display") or "").strip().lower()
            if code in {"pos", "positive", "mut"} or disp in {"positive", "mut"}:
                return True
            if code in {"neg", "negative", "wt"} or disp in {"negative", "wt"}:
                return False

        return False

    def _extract_component_or_text_code(self, observation: Dict[str, Any], args: Dict[str, Any]) -> Optional[str]:
        component_code_system = str(args.get("componentCodeSystem") or "").strip()
        component_code = str(args.get("componentCode") or "").strip()
        value_map = args.get("valueMap") or {}
        id_fallback = args.get("idFallback") or {}

        candidates: List[str] = []

        component = self._get_component(observation, component_code_system, component_code)
        if component:
            candidates.extend(self._collect_strings_from_component_value(component))

        candidates.extend(self._collect_strings_from_code_block(observation.get("code") or {}))

        oid = str(observation.get("id") or "").strip().lower()
        if oid:
            candidates.append(oid)

        lowered_candidates = [c.lower() for c in candidates if isinstance(c, str) and c.strip()]

        for normalized_value, tokens in value_map.items():
            token_list = [str(token).strip().lower() for token in (tokens or []) if str(token).strip()]
            if token_list and any(any(token in candidate for token in token_list) for candidate in lowered_candidates):
                return normalized_value

        for normalized_value, tokens in id_fallback.items():
            token_list = [str(token).strip().lower() for token in (tokens or []) if str(token).strip()]
            if token_list and any(token in oid for token in token_list):
                return normalized_value

        return None

    def _extract_component_or_id_region(self, observation: Dict[str, Any], args: Dict[str, Any]) -> Optional[str]:
        component_code_system = str(args.get("componentCodeSystem") or "").strip()
        component_code = str(args.get("componentCode") or "").strip()
        id_regex = str(args.get("idRegex") or "").strip()

        component = self._get_component(observation, component_code_system, component_code)
        if component:
            region = self._extract_region_from_component(component)
            if region:
                return region

        oid = str(observation.get("id") or "").strip()
        if id_regex and oid:
            match = re.search(id_regex, oid, re.IGNORECASE)
            if match:
                return match.group(1)

        for comp in observation.get("component", []) or []:
            region = self._extract_region_from_component(comp)
            if region:
                return region

        return None

    def _build_patient_metrics(self, normalized_observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}

        unresolved = dict(self.patient_metrics)
        while unresolved:
            progressed = False

            for metric_name in list(unresolved.keys()):
                rule = unresolved[metric_name] or {}
                aggregate = str(rule.get("aggregate") or "").strip()

                if aggregate == "count":
                    where = rule.get("where") or {}
                    metrics[metric_name] = sum(
                        1 for obs in normalized_observations if self._matches_where(obs, where)
                    )
                    progressed = True
                    del unresolved[metric_name]
                    continue

                if aggregate == "set":
                    where = rule.get("where") or {}
                    value_field = str(rule.get("value") or "").strip()
                    values = {
                        obs.get(value_field)
                        for obs in normalized_observations
                        if self._matches_where(obs, where) and obs.get(value_field) not in {None, ""}
                    }
                    metrics[metric_name] = values
                    progressed = True
                    del unresolved[metric_name]
                    continue

                if aggregate == "sumMetrics":
                    metric_names = [str(name).strip() for name in (rule.get("metrics") or []) if str(name).strip()]
                    if all(name in metrics for name in metric_names):
                        metrics[metric_name] = sum(float(metrics.get(name, 0) or 0) for name in metric_names)
                        progressed = True
                        del unresolved[metric_name]
                    continue

                if aggregate == "unionMetrics":
                    metric_names = [str(name).strip() for name in (rule.get("metrics") or []) if str(name).strip()]
                    if all(name in metrics for name in metric_names):
                        merged: Set[str] = set()
                        for name in metric_names:
                            value = metrics.get(name) or set()
                            if isinstance(value, set):
                                merged.update(str(item) for item in value if item not in {None, ""})
                            elif isinstance(value, list):
                                merged.update(str(item) for item in value if item not in {None, ""})
                        metrics[metric_name] = merged
                        progressed = True
                        del unresolved[metric_name]
                    continue

                metrics[metric_name] = None
                progressed = True
                del unresolved[metric_name]

            if not progressed:
                break

        return metrics

    def _matches_where(self, normalized_observation: Dict[str, Any], where: Dict[str, Any]) -> bool:
        for key, expected in (where or {}).items():
            if normalized_observation.get(key) != expected:
                return False
        return True

    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        if operator == ">=":
            try:
                return float(actual or 0) >= float(expected or 0)
            except Exception:
                return False

        if operator == "<=":
            try:
                return float(actual or 0) <= float(expected or 0)
            except Exception:
                return False

        if operator == ">":
            try:
                return float(actual or 0) > float(expected or 0)
            except Exception:
                return False

        if operator == "<":
            try:
                return float(actual or 0) < float(expected or 0)
            except Exception:
                return False

        if operator == "=":
            return actual == expected

        if operator == "IN":
            expected_set = self._to_string_set(expected)
            actual_set = self._to_string_set(actual)
            return bool(expected_set & actual_set)

        if operator == "overlaps":
            expected_set = self._to_string_set(expected)
            actual_set = self._to_string_set(actual)
            return bool(expected_set & actual_set)

        return False

    def _get_condition_value(self, condition: Dict[str, Any], value_from: str) -> Any:
        if value_from == "values":
            values = condition.get("values")
            if isinstance(values, list):
                return [str(v).strip() for v in values if v is not None and str(v).strip()]
            raw = condition.get("value")
            if isinstance(raw, str) and raw.strip():
                return [part.strip() for part in raw.split(",") if part.strip()]
            return []

        raw_value = condition.get("value")
        if raw_value is not None and str(raw_value).strip() != "":
            return raw_value

        values = condition.get("values")
        if isinstance(values, list) and values:
            if len(values) == 1:
                return values[0]
            return values

        return None

    def _to_string_set(self, value: Any) -> Set[str]:
        if value is None:
            return set()
        if isinstance(value, set):
            return {str(v).strip() for v in value if v is not None and str(v).strip()}
        if isinstance(value, list):
            return {str(v).strip() for v in value if v is not None and str(v).strip()}
        if isinstance(value, str):
            return {part.strip() for part in value.split(",") if part.strip()}
        return {str(value).strip()} if str(value).strip() else set()

    def _get_component(self, observation: Dict[str, Any], system: str, code: str) -> Optional[Dict[str, Any]]:
        for comp in observation.get("component", []) or []:
            if self._has_coding((comp.get("code") or {}).get("coding"), system, code):
                return comp
        return None

    def _has_coding(self, coding_list: Any, system: str, code: str) -> bool:
        if not isinstance(coding_list, list):
            return False
        for cd in coding_list:
            if cd.get("system") == system and cd.get("code") == code:
                return True
        return False

    def _collect_strings_from_component_value(self, component: Dict[str, Any]) -> List[str]:
        out: List[str] = []

        vcc = component.get("valueCodeableConcept") or {}
        if isinstance(vcc, dict):
            text = str(vcc.get("text") or "").strip()
            if text:
                out.append(text)
            for cd in vcc.get("coding") or []:
                code = str(cd.get("code") or "").strip()
                display = str(cd.get("display") or "").strip()
                system = str(cd.get("system") or "").strip()
                if code:
                    out.append(code)
                if display:
                    out.append(display)
                if system:
                    out.append(system)

        vs = component.get("valueString")
        if isinstance(vs, str) and vs.strip():
            out.append(vs.strip())

        return out

    def _collect_strings_from_code_block(self, code_block: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        if not isinstance(code_block, dict):
            return out

        text = str(code_block.get("text") or "").strip()
        if text:
            out.append(text)

        for cd in code_block.get("coding") or []:
            code = str(cd.get("code") or "").strip()
            display = str(cd.get("display") or "").strip()
            system = str(cd.get("system") or "").strip()
            if code:
                out.append(code)
            if display:
                out.append(display)
            if system:
                out.append(system)

        return out

    def _extract_region_from_component(self, component: Dict[str, Any]) -> Optional[str]:
        vcc = component.get("valueCodeableConcept") or {}
        if isinstance(vcc, dict):
            for cd in vcc.get("coding") or []:
                code = str(cd.get("code") or "").strip()
                display = str(cd.get("display") or "").strip()
                if code:
                    return code
                if display:
                    return display

        vs = component.get("valueString")
        if isinstance(vs, str) and vs.strip():
            return vs.strip()

        return None



_ENGINE_CACHE: Dict[str, FHIRObservationDataEngine] = {}


def get_observation_data_engine(
    project_id: Optional[Union[int, str]] = None,
) -> FHIRObservationDataEngine:
    cache_key = str(project_id).strip() if project_id is not None and str(project_id).strip() else "__default__"
    engine = _ENGINE_CACHE.get(cache_key)
    if engine is None:
        if DEBUG:
            print("[OBS DATA ENGINE] Creating engine instance", f"project_id={project_id}")
        engine = FHIRObservationDataEngine(project_id=project_id)
        _ENGINE_CACHE[cache_key] = engine
    return engine


def patient_satisfies_coded_observation_data_filters(
    observations: List[Dict[str, Any]],
    conditions: List[Dict[str, Any]],
    project_id: Optional[Union[int, str]] = None,
) -> bool:
    return get_observation_data_engine(project_id=project_id).patient_satisfies_filters(observations, conditions)
