import csv
import json
import os
import re
import shutil
import copy
import math
from pathlib import Path
from typing import List, Optional, Dict, Any, Set, Iterable

from fastapi.encoders import jsonable_encoder

from app.core.mysql.MySQLRetriever import MySQLRetriever
from app.core.mysql.SupportedFunction import FUNCTION_TO_COMPUTATION_TYPE, SupportedFunction, MODEL_TYPE_ENCRYPTED, MODEL_TYPE_OPEN_ACCESS
from app.core.mysql.managers.NVFlareJobsManager import NVFlareJobsManager
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.mysql.managers.ProjectsManager import Project, ProjectsManager
from app.core.mysql.managers.UsersManager import UsersManager
from app.core.mysql.managers.ThresholdManager import Threshold, ThresholdMethod

LOCAL_NVFLARE_JOBS_DIR = os.path.join("app", "core", "job_runner", "nvflare_jobs", "jobs")
LOCAL_JOB_ROOT = Path("/tmp/nvflare_jobs/jobs").resolve()
DEFAULT_JOB_TEMPLATE = "nvflare_job_template"
DEFAULT_GLOBAL_SCHEMA = "global_schema.json"
# Source-controlled schemas selected at staging time. This directory lives beside
# NVFlareJobStager.py in the backend repository, not inside a job template.
LOCAL_GLOBAL_SCHEMA_DIR = Path(__file__).resolve().parent / "global_schema"
MODEL_FILE_SOURCES_CONFIG = "model_file_sources.json"
DEFAULT_INITIATOR_CLIENT_NAME = "site3"
# Must match apis/stat_analytics_event_type.PROFILE_CONSOLIDATE_WORKFLOW_ID (tail profile merge workflow).
_PROFILE_CONSOLIDATE_WORKFLOW_ID = "workflow_consolidate_profile_summaries"

# Server preprocess + aggregate_stat_analytics for the encrypted biomarker HE steps
# can exceed NVFlare's default task timeout (2 min). Use 10 min so heavy HE work completes.
ENC_BIOMARKER_DISC_TRAIN_TIMEOUT_SEC = 600

# Reuse-scores split/shared-cache graph (supersedes the old fused
# ``workflow_enc_biomarker_disc_1`` / ``biomarker_enc_risk_group_computation``): one
# score-cache producer computes the risk-score dot product once and caches the packed
# ciphertext; KM and LCS each consume it via a postprocess workflow. The three templates
# below plus the shared ``workflow_model_upload`` reproduce the hand-authored sim configs
# (tests/sim_config_fed_server_{enc,survival_enc,combined_enc}_split.json).

# Producer: dot product + neutral pack, cache packed rsf-scaled score (no decrypt).
ENC_BIOMARKER_SCORE_CACHE_WORKFLOW_TEMPLATE = {
    "id": "workflow_enc_biomarker_score_cache",
    "path": "workflow_runtime.customSAG",
    "args": {
        "min_clients": 0,
        "num_rounds": 1,
        "start_round": 0,
        "wait_time_after_min_received": 0,
        "aggregator_id": "aggregator",
        "persistor_id": "persistor",
        "persist_every_n_rounds": 1,
        "shareable_generator_id": "shareable_generator",
        "train_task_name": "task_enc_biomarker_score_cache",
        "allow_empty_global_weights": True,
        "train_timeout": ENC_BIOMARKER_DISC_TRAIN_TIMEOUT_SEC,
        "workload_args": {
            "computation_type": "biomarker_enc_score_cache",
            "global_schema": "global_schema.json",
            "cancer_type": "Non-Small Cell Lung Cancer",
            "model_keys": ["cox_lasso"],
        },
    },
}

# KM consumer: from cache, -cutoff, x rm, decrypt -> risk groups.
ENC_BIOMARKER_RISK_GROUP_POSTPROCESS_WORKFLOW_TEMPLATE = {
    "id": "workflow_enc_biomarker_risk_group_postprocess",
    "path": "workflow_runtime.customSAG",
    "args": {
        "min_clients": 0,
        "num_rounds": 2,
        "start_round": 0,
        "wait_time_after_min_received": 0,
        "aggregator_id": "aggregator",
        "persistor_id": "persistor",
        "persist_every_n_rounds": 2,
        "shareable_generator_id": "shareable_generator",
        "train_task_name": "task_enc_biomarker_risk_group_postprocess",
        "allow_empty_global_weights": True,
        "train_timeout": ENC_BIOMARKER_DISC_TRAIN_TIMEOUT_SEC,
        "workload_args": {
            "computation_type": "biomarker_enc_risk_group_postprocess",
            "global_schema": "global_schema.json",
            "cancer_type": "Non-Small Cell Lung Cancer",
            "model_keys": ["cox_lasso"],
        },
    },
}

WORKFLOW_MODEL_UPLOAD_TEMPLATE = {
    "id": "workflow_model_upload",
    "path": "duality_nvflare_workflows.customSAG.customSAG",
    "args": {
        "min_clients": 0,
        "num_rounds": 1,
        "start_round": 0,
        "wait_time_after_min_received": 0,
        "aggregator_id": "aggregator",
        "persistor_id": "persistor",
        "persist_every_n_rounds": 1,
        "shareable_generator_id": "shareable_generator",
        "train_task_name": "task_model_upload",
        "allow_empty_global_weights": True,
        "train_timeout": 60,
        "workload_args": {
            "model_keys": [],
            "cancer_type": "",
            "model_file_sources_config": MODEL_FILE_SOURCES_CONFIG,
        },
    },
}

ENCRYPTED_PERSISTOR_GENERATE_INDEX_KEYS = True
ENCRYPTED_PERSISTOR_INDICES = [1, 2, 4, 8, 16, 32, 64, 128, 256, -511]

# Open-access Exceptional Response Discrimination (meta-analysis) chain config, loaded
# by the stager when a function-config's computation_type resolves to "meta-analysis".
_META_ANALYSIS_CHAIN_CONFIG_OPEN = "config_meta_analysis_open.json"
# Encrypted Exceptional Response Discrimination (meta-analysis) chain config, loaded
# by the stager when a meta-analysis function-config's model_type is Encrypted.
# Same KeyGen->...->meta-analysis shape as the open config but with the
# encrypt-at-initiator scoring prefix (model_upload[Encrypted] -> HE scoring).
_META_ANALYSIS_CHAIN_CONFIG_ENCRYPTED = "config_meta_analysis_enc.json"
# train_task_names that belong only to the meta-analysis chain; pruned from the
# carried-over template workflows so the chain builder is the sole emitter.
_META_ANALYSIS_CHAIN_TRAIN_TASKS = {"task_reference_stat_analytics"}

THRESHOLD_WORKFLOW_TEMPLATE_UNSECURE = {
    "id": "workflow_threshold_samples_unsecure",
    "path": "workflow_runtime.customSAG",
    "args": {
        "min_clients": 0,
        "num_rounds": 2,
        "start_round": 0,
        "aggregator_id": "aggregator",
        "persistor_id": "persistor",
        "persist_every_n_rounds": 2,
        "shareable_generator_id": "shareable_generator",
        "train_task_name": "task_threshold_samples_unsecure",
        "allow_empty_global_weights": True,
        "train_timeout": 0,
        "wait_time_after_min_received": 0,
        "workload_args": {
            "min_global_samples": 10,
            "workflows": {}
        }
    }
}

THRESHOLD_WORKFLOW_TEMPLATE_SECURE = {
    "id": "workflow_threshold_samples_secure",
    "path": "workflow_runtime.customSAG",
    "args": {
        "min_clients": 0,
        "num_rounds": 2,
        "start_round": 0,
        "aggregator_id": "aggregator",
        "persistor_id": "persistor",
        "persist_every_n_rounds": 2,
        "shareable_generator_id": "shareable_generator",
        "train_task_name": "task_threshold_samples_secure",
        "allow_empty_global_weights": True,
        "train_timeout": 0,
        "wait_time_after_min_received": 0,
        "workload_args": {
            "min_global_samples": 10,
            "workflows": {}
        }
    }
}

class NVFlareJobStager:
    # Initialize the job stager with selected functions, clients, filters, template, and optional managers.
    # projectId now needed for conveying project information
    def __init__(
        self,
        project_id: int,
        functions_map: Dict[str, object],
        status_writer: JobStatusWriter,
        clients_list: str,
        filters_id: Optional[int] = None,
        job_template_name=None,
        nvflare_jobs_manager: Optional[NVFlareJobsManager] = None,
        threshold: Optional[Threshold] = None,
        datasource_group_id: Optional[int] = None,
        workflow_group_data: Optional[Dict[str, Any]] = None,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None,
    ):
        self.project_id = int(project_id)
        projects_manager = ProjectsManager()
        self.project: Project = projects_manager.get_project(project_id, datasource_group_id=datasource_group_id)
        projects_manager.complete()

        normalized: Dict[str, List[Dict[str, str]]] = {}
        for fn_name, cfg_val in (functions_map or {}).items():
            if cfg_val is None:
                continue
            if isinstance(cfg_val, list):
                cfg_list = [c for c in cfg_val if isinstance(c, dict)]
            elif isinstance(cfg_val, dict):
                cfg_list = [cfg_val]
            else:
                continue
            if cfg_list:
                normalized[str(fn_name).strip().upper()] = cfg_list

        self.functions_map: Dict[str, List[Dict[str, str]]] = normalized
        self.status_writer = status_writer
        self.participating_clients = clients_list
        self.filters = None
        self.nvflare_jobs_manager = nvflare_jobs_manager
        self.threshold = threshold
        self.datasource_group_id = datasource_group_id
        self.workflow_group_data = workflow_group_data or {}
        self.non_contributing_clients = self._normalize_client_name_list(non_contributing_clients)
        self.exclude_analyzing_clients = self._normalize_client_name_list(exclude_analyzing_clients)

        if job_template_name is not None:
            self.job_template_name = job_template_name
        else:
            self.job_template_name = DEFAULT_JOB_TEMPLATE

        if filters_id:
            mr = MySQLRetriever()
            try:
                staged_filters = mr.stage_filters_by_id(filters_id)
            finally:
                mr.complete()

            if staged_filters:
                self.filters = staged_filters
            else:
                self.filters = None

    def _normalize_client_name_list(self, value: Optional[List[str]]) -> List[str]:
        if value is None:
            return []

        if not isinstance(value, list):
            return []

        normalized: List[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            client_name = item.strip()
            if client_name and client_name not in normalized:
                normalized.append(client_name)

        return normalized


    def _get_all_workload_args(self) -> List[Dict[str, Any]]:
        workload_args_list: List[Dict[str, Any]] = []

        for _, cfg_list in (self.functions_map or {}).items():
            if not isinstance(cfg_list, list):
                continue
            for cfg in cfg_list:
                if isinstance(cfg, dict):
                    workload_args_list.append(cfg)

        return workload_args_list

    def _get_biomarker_cancer_type_from_functions_map(self) -> Optional[str]:
        for workload_args in self._get_all_workload_args():
            value = workload_args.get("cancer_type")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _get_selected_model_keys(self) -> List[str]:
        if not isinstance(self.workflow_group_data, dict):
            return []

        raw = self.workflow_group_data.get("predictive_modeling_method_ids")
        if not isinstance(raw, dict):
            return []

        selected_values = raw.get("selected_values")
        if not isinstance(selected_values, list):
            return []

        out: List[str] = []
        for value in selected_values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized:
                continue
            if normalized not in out:
                out.append(normalized)
        return out

    def _get_effective_model_keys(self) -> List[str]:
        return self._get_selected_model_keys()


    def _iter_project_config_candidate_paths(self, file_name: str) -> Iterable[Path]:
        rel = Path("apis") / "fhir" / "config" / f"project_{self.project_id}" / file_name
        seen: Set[str] = set()

        candidate_bases: List[Path] = [Path.cwd().resolve()]
        try:
            here = Path(__file__).resolve()
            candidate_bases.extend([here.parent, *list(here.parents)[:12]])
        except Exception:
            pass

        for base in candidate_bases:
            for candidate in (base / rel, base.parent / rel):
                key = str(candidate)
                if key in seen:
                    continue
                seen.add(key)
                yield candidate

    def _load_project_patient_query_config(self) -> Optional[Dict[str, Any]]:
        for candidate in self._iter_project_config_candidate_paths("patient_query.json"):
            if not candidate.exists():
                continue
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(
                    f"NVFlareJobStager: failed reading model file lookup config from {candidate}: {e}",
                    flush=True,
                )
                return None
        return None

    def _get_model_file_lookup_key_from_project_config(self) -> Optional[str]:
        cfg = self._load_project_patient_query_config()
        if isinstance(cfg, dict):
            for node in self._walk_dict_nodes(cfg):
                if not isinstance(node, dict):
                    continue

                is_lookup = node.get("model_file_lookup_key") is True
                lookup_cfg = node.get("model_file_lookup")
                if isinstance(lookup_cfg, dict) and lookup_cfg.get("enabled") is True:
                    is_lookup = True

                if not is_lookup:
                    continue

                key = node.get("id") or node.get("column_name")
                if isinstance(key, str) and key.strip():
                    return key.strip()

        # Backward-compatible fallback for the biomarker project while older config
        # files are still being replaced in deployed environments.
        cancer_type = self._get_biomarker_cancer_type_from_functions_map()
        if cancer_type:
            return "cancer_type"
        return None

    def _get_model_file_lookup_value(self, lookup_key: str) -> Optional[str]:
        key = str(lookup_key or "").strip()
        if not key:
            return None

        for workload_args in self._get_all_workload_args():
            value = workload_args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list)):
                return str(value).strip()

        filters_obj = self.filters
        if filters_obj is not None:
            for node in self._walk_dict_nodes(filters_obj):
                if not isinstance(node, dict):
                    continue
                column_name = node.get("column_name")
                if not isinstance(column_name, str) or column_name.strip() != key:
                    continue
                value = node.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if value is not None and not isinstance(value, (dict, list)):
                    return str(value).strip()

        return None

    def _get_initiator_client_name(self) -> str:
        value = os.getenv("DUALITY_INITIATOR_CLIENT_NAME", DEFAULT_INITIATOR_CLIENT_NAME)
        normalized = str(value or "").strip()
        return normalized or DEFAULT_INITIATOR_CLIENT_NAME

    def _get_model_file_sources_payload(self) -> Optional[Dict[str, Any]]:
        lookup_key = self._get_model_file_lookup_key_from_project_config()
        if not lookup_key:
            return None

        lookup_value = self._get_model_file_lookup_value(lookup_key)
        if not lookup_value:
            raise ValueError(
                f"Project {self.project_id} declares model file lookup key {lookup_key!r}, "
                "but the selected job configuration did not contain a value for it."
            )

        model_keys = self._get_effective_model_keys()
        if not model_keys:
            return None

        initiator_client_name = self._get_initiator_client_name()
        manager = UsersManager()
        try:
            payload = manager.get_model_file_sources_for_client(
                client_name=initiator_client_name,
                project_id=self.project_id,
                datasource_group=self.datasource_group_id,
                model_file_lookup_key=lookup_key,
                model_file_lookup_value=lookup_value,
                model_keys=model_keys,
                artifact_types=["weights", "cutoff"],
            )
        finally:
            manager.complete()

        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, dict):
            models = {}

        missing: List[str] = []
        for model_key in model_keys:
            artifacts = models.get(model_key)
            if not isinstance(artifacts, dict):
                missing.append(f"{model_key}: weights, cutoff")
                continue
            for artifact_type in ("weights", "cutoff"):
                source = artifacts.get(artifact_type)
                if not isinstance(source, str) or not source.strip():
                    missing.append(f"{model_key}: {artifact_type}")

        if missing:
            raise FileNotFoundError(
                "Missing model file source rows for "
                f"initiator_client={initiator_client_name!r}, project_id={self.project_id}, "
                f"datasource_group_id={self.datasource_group_id}, "
                f"{lookup_key}={lookup_value!r}: " + "; ".join(missing)
            )

        payload["config_file"] = MODEL_FILE_SOURCES_CONFIG
        payload["source_type"] = "initiator_local_path"
        payload["model_type"] = MODEL_TYPE_ENCRYPTED if self._is_encrypted_model() else MODEL_TYPE_OPEN_ACCESS
        return payload

    def _write_model_file_sources_if_needed(self, job_dir: Path) -> None:
        payload = self._get_model_file_sources_payload()
        if not payload:
            return

        custom_dir = job_dir / "app_client" / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        target = custom_dir / MODEL_FILE_SOURCES_CONFIG
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        models = payload.get("models") if isinstance(payload, dict) else {}
        model_keys = sorted(models.keys()) if isinstance(models, dict) else []
        print(
            f"NVFlareJobStager: wrote {MODEL_FILE_SOURCES_CONFIG} for "
            f"initiator_client={payload.get('client_name')}, "
            f"lookup={payload.get('model_file_lookup_key')}={payload.get('model_file_lookup_value')}, "
            f"model_keys={model_keys}",
            flush=True,
        )

    def _expand_functions_map_for_selected_models(self) -> Dict[str, List[Dict[str, Any]]]:
        expanded: Dict[str, List[Dict[str, Any]]] = {}
        selected_model_keys = self._get_selected_model_keys()

        for func_name, cfg_list in (self.functions_map or {}).items():
            if not isinstance(cfg_list, list):
                continue

            expanded_cfgs: List[Dict[str, Any]] = []
            for cfg in cfg_list:
                if not isinstance(cfg, dict):
                    continue

                is_biomarker_discovery = bool(
                    str(cfg.get("is_biomarker_discovery", "")).strip().lower() in ("true", "1")
                )

                if selected_model_keys and is_biomarker_discovery:
                    for selected_model_key in selected_model_keys:
                        if not isinstance(selected_model_key, str):
                            continue
                        normalized_model_key = selected_model_key.strip()
                        if not normalized_model_key:
                            continue
                        expanded_cfg = dict(cfg)
                        expanded_cfg["model_key"] = normalized_model_key
                        expanded_cfgs.append(expanded_cfg)
                    continue

                expanded_cfgs.append(dict(cfg))

            if expanded_cfgs:
                expanded[str(func_name).strip().upper()] = expanded_cfgs

        return expanded

    def _expand_project_functions_for_selected_models(self) -> List[Dict[str, Any]]:
        project_functions = getattr(self.project, "functions", None)
        if not isinstance(project_functions, list):
            return []

        selected_model_keys = self._get_selected_model_keys()
        expanded_functions: List[Dict[str, Any]] = []

        for project_function in project_functions:
            if not isinstance(project_function, dict):
                continue

            fixed_cfg = project_function.get("custom_configuration_fixed")
            is_biomarker_discovery = isinstance(fixed_cfg, dict) and bool(
                str(fixed_cfg.get("is_biomarker_discovery", "")).strip().lower() in ("true", "1")
            )

            if selected_model_keys and is_biomarker_discovery:
                for selected_model_key in selected_model_keys:
                    if not isinstance(selected_model_key, str):
                        continue
                    normalized_model_key = selected_model_key.strip()
                    if not normalized_model_key:
                        continue
                    expanded_function = copy.deepcopy(project_function)
                    expanded_fixed_cfg = expanded_function.get("custom_configuration_fixed")
                    if not isinstance(expanded_fixed_cfg, dict):
                        expanded_fixed_cfg = {}
                        expanded_function["custom_configuration_fixed"] = expanded_fixed_cfg
                    expanded_fixed_cfg["model_key"] = normalized_model_key
                    expanded_functions.append(expanded_function)
                continue

            expanded_functions.append(copy.deepcopy(project_function))

        return expanded_functions


    def _parse_bool_strict(self, s: str) -> Optional[bool]:
        v = str(s).strip().lower()
        if v == "true":
            return True
        if v == "false":
            return False
        if v == "1":
            return True
        if v == "0":
            return False
        return None

    def _walk_dict_nodes(self, node: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(node, dict):
            yield node
            for v in node.values():
                yield from self._walk_dict_nodes(v)
        elif isinstance(node, list):
            for item in node:
                yield from self._walk_dict_nodes(item)

    def _is_encrypted_model(self) -> bool:
        for _, cfg_list in (self.functions_map or {}).items():
            if not isinstance(cfg_list, list):
                continue
            for cfg in cfg_list:
                if not isinstance(cfg, dict):
                    continue
                mt = cfg.get("model_type")
                if isinstance(mt, str) and mt.strip().lower() == MODEL_TYPE_ENCRYPTED.lower():
                    return True
        return False

    def _is_lcs_only_encrypted_biomarker(self) -> bool:
        """True when an ENCRYPTED job runs LCS (meta-analysis) with NO KM biomarker-discovery
        consumer sharing the score cache.

        The rsf baking exists only for KM's sign resolution, so such a job uploads the model
        unbaked (rsf=1) and skips the LCS descale entirely -- avoiding the near-zero-cutoff
        (large-rsf) precision loss -- and needs only depth 4 instead of 5. Detected from
        ``functions_map`` (order-independent) so the mult_depth floor and the ``lcs_only`` flag
        set on the model_upload/score_cache/score_postprocess workload_args agree.
        """
        if not self._is_encrypted_model():
            return False
        has_lcs = False
        has_km_discovery = False
        for func_name, cfg_list in (self.functions_map or {}).items():
            if not isinstance(cfg_list, list):
                continue
            comp_default = FUNCTION_TO_COMPUTATION_TYPE.get(str(func_name))
            for cfg in cfg_list:
                if not isinstance(cfg, dict):
                    continue
                comp = str(cfg.get("computation_type") or comp_default or "").strip().lower()
                if comp == "meta-analysis":
                    has_lcs = True
                elif comp == "kaplan-meier" and str(
                    cfg.get("is_biomarker_discovery", "")
                ).strip().lower() in ("true", "1"):
                    has_km_discovery = True
        return has_lcs and not has_km_discovery

    def _get_custom_config_variable_names_for_function(self, func_name: str) -> Set[str]:
        if self.project is None:
            return set()

        fn_upper = str(func_name or "").strip().upper()
        if not fn_upper:
            return set()

        project_functions = getattr(self.project, "functions", None)
        if not isinstance(project_functions, list):
            return set()

        for f in project_functions:
            if not isinstance(f, dict):
                continue
            f_name = f.get("function")
            if not isinstance(f_name, str):
                continue
            if f_name.strip().upper() != fn_upper:
                continue
            var_map = f.get("custom_configuration_variable")
            if not isinstance(var_map, dict):
                return set()
            return {str(k) for k in var_map.keys() if isinstance(k, str) and str(k).strip()}

        return set()

    def _apply_custom_config_vars_to_filters(self, func_name: str, workload_args: Dict[str, Any]) -> None:
        if not workload_args:
            return

        allowed = self._get_custom_config_variable_names_for_function(func_name)
        if not allowed:
            return

        filters_obj = self.filters
        if filters_obj is None:
            return

        for prop_name, prop_value in list(workload_args.items()):
            if prop_name not in allowed:
                continue
            if prop_value is None:
                continue
            if isinstance(prop_value, str) and prop_value.strip() == "":
                continue

            target = str(prop_name).strip()

            for d in self._walk_dict_nodes(filters_obj):
                col = d.get("column_name")
                if not isinstance(col, str):
                    continue
                if col.strip() != target:
                    continue
                if "value" in d:
                    d["value"] = prop_value

    # Parse a CSV of client names, honoring backslash escapes, into a list of client identifiers.
    def _parse_clients(self, clients_csv: str) -> List[str]:
        if not clients_csv:
            return []
        out, cur, esc = [], [], False
        for ch in clients_csv:
            if esc:
                cur.append(ch)
            elif ch == "\\":
                esc = True
            elif ch == ",":
                token = "".join(cur).strip()
                if token:
                    out.append(token)
                cur = []
            else:
                cur.append(ch)
                esc = False
        token = "".join(cur).strip()
        if token:
            out.append(token)
        return out

    # Coerce workload argument values to the expected types defined for a function.
    def _coerce_workload_arg_types(self, func_name: str, workload_args: Dict[str, object]) -> None:
        if not workload_args:
            return

        for prop_name, value in list(workload_args.items()):
            prop_type = SupportedFunction.get_property_type(func_name, prop_name)
            pt = str(prop_type or "").strip().lower()

            if pt in ("bool", "boolean"):
                if isinstance(value, bool):
                    continue
                if isinstance(value, int) and value in (0, 1):
                    workload_args[prop_name] = bool(value)
                    continue
                if isinstance(value, str):
                    b = self._parse_bool_strict(value)
                    if b is not None:
                        workload_args[prop_name] = b
                continue

            if pt in ("int", "integer"):
                if isinstance(value, int) and not isinstance(value, bool):
                    continue
                if isinstance(value, float) and float(value).is_integer():
                    workload_args[prop_name] = int(value)
                    continue
                if isinstance(value, str):
                    s = value.strip()
                    if s:
                        try:
                            workload_args[prop_name] = int(s)
                        except ValueError:
                            pass
                continue

            if pt in ("float", "number", "decimal"):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    workload_args[prop_name] = float(value)
                    continue
                if isinstance(value, str):
                    s = value.strip()
                    if s:
                        try:
                            workload_args[prop_name] = float(s)
                        except ValueError:
                            pass
                continue

            # No declared type for this property: leave the value alone. Previously this
            # branch stringified any non-string value, which silently undid the submission-layer
            # coercion (SupportedFunction.coerce_value_for_type via _normalize_functions_map)
            # for fields not in this function's own FUNCTION_PROPERTY_TYPES map (e.g. fields
            # that leaked between functions during cfg_dict merging).

    def _workflow_is_kaplan_meier(self, wf: Dict[str, Any]) -> bool:
        if not isinstance(wf, dict):
            return False
        args = wf.get("args")
        if not isinstance(args, dict):
            return False
        workload_args = args.get("workload_args")
        if not isinstance(workload_args, dict):
            return False
        ct = workload_args.get("computation_type")
        if not isinstance(ct, str):
            return False
        return ct.strip().lower() == "kaplan-meier"

    # Generic matcher for the encrypted biomarker HE workflows on the reuse-scores
    # split/shared-cache path, keyed on id prefix / train task / computation_type.
    def _workflow_matches_enc_biomarker(
        self,
        wf: Dict[str, Any],
        id_prefix: str,
        train_task: str,
        computation_type: str,
    ) -> bool:
        if not isinstance(wf, dict):
            return False
        args = wf.get("args") if isinstance(wf.get("args"), dict) else {}
        wargs = args.get("workload_args") if isinstance(args.get("workload_args"), dict) else {}
        wf_id = wf.get("id")
        if isinstance(wf_id, str) and wf_id.strip().lower().startswith(id_prefix):
            return True
        ttn = args.get("train_task_name")
        if isinstance(ttn, str) and ttn.strip().lower() == train_task:
            return True
        ct = str(wargs.get("computation_type") or "").strip().lower()
        return ct == computation_type

    # Producer: computes the risk-score dot product once and caches the packed score ct.
    def _workflow_is_enc_biomarker_score_cache(self, wf: Dict[str, Any]) -> bool:
        return self._workflow_matches_enc_biomarker(
            wf,
            "workflow_enc_biomarker_score_cache",
            "task_enc_biomarker_score_cache",
            "biomarker_enc_score_cache",
        )

    # KM consumer: -cutoff, x rm, decrypt -> risk groups (from the shared cache).
    def _workflow_is_enc_biomarker_risk_group_postprocess(self, wf: Dict[str, Any]) -> bool:
        return self._workflow_matches_enc_biomarker(
            wf,
            "workflow_enc_biomarker_risk_group_postprocess",
            "task_enc_biomarker_risk_group_postprocess",
            "biomarker_enc_risk_group_postprocess",
        )

    # LCS consumer: x 1/rsf, decrypt -> raw scores (from the shared cache).
    def _workflow_is_enc_biomarker_score_postprocess(self, wf: Dict[str, Any]) -> bool:
        return self._workflow_matches_enc_biomarker(
            wf,
            "workflow_enc_biomarker_score_postprocess",
            "task_enc_biomarker_score_postprocess",
            "biomarker_enc_score_postprocess",
        )

    # Consumers of the cached score (KM and/or LCS postprocess). The score-cache
    # producer is inserted immediately before the first such workflow.
    def _workflow_is_enc_biomarker_score_consumer(self, wf: Dict[str, Any]) -> bool:
        return (
            self._workflow_is_enc_biomarker_risk_group_postprocess(wf)
            or self._workflow_is_enc_biomarker_score_postprocess(wf)
        )

    # Any encrypted biomarker HE workflow (score-cache producer + both postprocess
    # consumers). Used to grant the longer HE train_timeout.
    def _workflow_is_enc_biomarker_he(self, wf: Dict[str, Any]) -> bool:
        return (
            self._workflow_is_enc_biomarker_score_cache(wf)
            or self._workflow_is_enc_biomarker_score_consumer(wf)
        )

    # True for any workflow that consumes biomarker model artifacts after the upload workflow runs.
    # This applies to both encrypted and open-access model jobs. On the encrypted split path the
    # earliest such workflow is the score-cache producer, so the shared model_upload anchors before it.
    def _workflow_is_biomarker_consumer(self, wf: Dict[str, Any]) -> bool:
        if self._workflow_is_enc_biomarker_score_cache(wf) or self._workflow_is_enc_biomarker_score_consumer(wf):
            return True
        if not isinstance(wf, dict):
            return False

        wf_id = wf.get("id")
        wf_id_normalized = wf_id.strip().lower() if isinstance(wf_id, str) else ""

        args = wf.get("args")
        if not isinstance(args, dict):
            return False

        wargs = args.get("workload_args")
        if not isinstance(wargs, dict):
            return False

        computation_type = str(wargs.get("computation_type", "")).strip().lower()

        if wf_id_normalized.startswith("workflow_biomarker_score_computation"):
            return True

        if computation_type == "biomarker_score_computation":
            return True

        if not wf_id_normalized.startswith("workflow_stat_analytics"):
            return False

        return str(wargs.get("is_biomarker_discovery", "")).strip().lower() in ("true", "1")

    # Apply cancer_type + model_keys (and single-model model_key, matching the sim
    # configs) to a cloned biomarker workflow's workload_args.
    def _apply_biomarker_workload_args(self, wf: Dict[str, Any], client_count: int) -> None:
        args = wf.get("args")
        if not isinstance(args, dict):
            args = {}
            wf["args"] = args
        args["min_clients"] = client_count

        workload_args = args.get("workload_args")
        if not isinstance(workload_args, dict):
            workload_args = {}

        cancer_type = self._get_biomarker_cancer_type_from_functions_map()
        if cancer_type:
            workload_args["cancer_type"] = cancer_type

        model_keys = self._get_effective_model_keys()
        if model_keys:
            workload_args["model_keys"] = model_keys
            # Single-model discovery is the common case; carry the scalar model_key too
            # (the shared cache is keyed by model, so a single key is unambiguous).
            if len(model_keys) == 1:
                workload_args["model_key"] = model_keys[0]

        args["workload_args"] = workload_args
        wf["args"] = args

    def _insert_enc_biomarker_risk_group_postprocess_workflow(self, workflows: List[Dict], client_count: int) -> List[Dict]:
        # KM consumer of the shared score cache. Emitted only when a kaplan-meier
        # (biomarker discovery) workflow is present; inserted immediately before it.
        if not self._is_encrypted_model():
            return workflows

        if not isinstance(workflows, list) or not workflows:
            return workflows

        for w in workflows:
            if self._workflow_is_enc_biomarker_risk_group_postprocess(w):
                return workflows

        km_idx = None
        for i, w in enumerate(workflows):
            if self._workflow_is_kaplan_meier(w):
                km_idx = i
                break

        if km_idx is None:
            return workflows

        wf = copy.deepcopy(ENC_BIOMARKER_RISK_GROUP_POSTPROCESS_WORKFLOW_TEMPLATE)
        self._apply_biomarker_workload_args(wf, client_count)

        new_workflows = list(workflows)
        new_workflows.insert(km_idx, wf)
        return new_workflows

    def _insert_enc_biomarker_score_cache_workflow(self, workflows: List[Dict], client_count: int) -> List[Dict]:
        # Single shared producer feeding every score consumer (KM risk-group +/- LCS
        # score postprocess). Inserted immediately before the first such consumer.
        if not self._is_encrypted_model():
            return workflows

        if not isinstance(workflows, list) or not workflows:
            return workflows

        for w in workflows:
            if self._workflow_is_enc_biomarker_score_cache(w):
                return workflows

        consumer_idx = next(
            (i for i, w in enumerate(workflows) if self._workflow_is_enc_biomarker_score_consumer(w)),
            None,
        )
        if consumer_idx is None:
            return workflows

        wf = copy.deepcopy(ENC_BIOMARKER_SCORE_CACHE_WORKFLOW_TEMPLATE)
        self._apply_biomarker_workload_args(wf, client_count)

        new_workflows = list(workflows)
        new_workflows.insert(consumer_idx, wf)
        return new_workflows

    def _insert_model_upload_workflow(self, workflows: List[Dict], client_count: int) -> List[Dict]:
        if not isinstance(workflows, list) or not workflows:
            return workflows

        # Idempotent: one shared model_upload per job. Both the KM and LCS branches now
        # read the single upload's ``_score`` (for_scoring) artifacts via the shared score
        # cache, so a job never needs a second variant-specific upload.
        for w in workflows:
            wf_id = (w.get("id") or "")
            if isinstance(wf_id, str) and wf_id.strip().lower().startswith("workflow_model_upload"):
                return workflows

        # Upload only makes sense if a downstream consumer will read the uploaded model files:
        # the encrypted score-cache producer, or open-access biomarker validation
        # (stat_analytics + is_biomarker_discovery).
        consumer_idx = next((i for i, w in enumerate(workflows) if self._workflow_is_biomarker_consumer(w)), None,)
        if consumer_idx is None:
            return workflows

        # Insert *before* the consumer and after KeyGen if present.
        keygen_idx = next((i for i, w in enumerate(workflows) if isinstance(w.get("id"), str) and w["id"].strip().lower().startswith("workflow_keygen")), None,)
        insert_pos = (keygen_idx + 1) if keygen_idx is not None else consumer_idx

        wf = copy.deepcopy(WORKFLOW_MODEL_UPLOAD_TEMPLATE)
        wf["args"]["min_clients"] = client_count
        cancer_type = self._get_biomarker_cancer_type_from_functions_map()
        if cancer_type:
            wf["args"]["workload_args"]["cancer_type"] = cancer_type
        model_keys = self._get_effective_model_keys()
        if model_keys:
            wf["args"]["workload_args"]["model_keys"] = model_keys
        # Runtime branches on model_type after the initiator uploads the selected model files.
        is_encrypted = self._is_encrypted_model()
        wf["args"]["workload_args"]["model_type"] = (
            MODEL_TYPE_ENCRYPTED if is_encrypted else MODEL_TYPE_OPEN_ACCESS
        )
        if is_encrypted:
            # The shared upload distributes every artifact both branches need: coeff +
            # cutoff + encrypted 1/rsf + ER_threshold sidecar, no plaintext rsf/scale.json.
            # ``for_scoring`` selects that unified ``_score`` artifact set; the depth
            # workflow level-matches the encoded model weights to the score-cache depth (5).
            wf["args"]["workload_args"]["for_scoring"] = True
            wf["args"]["workload_args"]["biomarker_depth_workflow"] = "workflow_enc_biomarker_score_cache"

        new_workflows = list(workflows)
        new_workflows.insert(insert_pos, wf)
        return new_workflows


    def _ensure_workflow_binding(self, func_name: str, config_props: Dict[str, Any], workflow_id: str) -> None:
        if self.nvflare_jobs_manager is None:
            return

        self.nvflare_jobs_manager.ensure_and_set_workflow_for_function_config(
            function_name=func_name,
            props=config_props,
            workflow_id=workflow_id,
        )

    def _get_unique_workflow_id(self, base_workflow_id: str, used_workflow_ids: Set[str]) -> str:
        if base_workflow_id not in used_workflow_ids:
            used_workflow_ids.add(base_workflow_id)
            return base_workflow_id

        index = 2
        while True:
            candidate = f"{base_workflow_id}_{index}"
            if candidate not in used_workflow_ids:
                used_workflow_ids.add(candidate)
                return candidate
            index += 1

    # Build stat_analytics workflows from a template based on the selected functions map.
    def _build_stat_analytics_workflows(self, data: Dict, workflows: List[Dict], client_count: int) -> List[Dict]:
        base_template = None
        for w in workflows:
            args = w.get("args")
            if isinstance(args, dict) and args.get("train_task_name") == "task_stat_analytics":
                base_template = w
                break
        if not base_template:
            return workflows

        template_args = base_template.get("args") or {}
        template_workload_defaults = {}
        base_workload = template_args.get("workload_args")
        if isinstance(base_workload, dict):
            template_workload_defaults = dict(base_workload)

        non_analytics = []
        for w in workflows:
            args = w.get("args")
            if not isinstance(args, dict):
                non_analytics.append(w)
                continue
            ttn = args.get("train_task_name")
            if ttn == "task_stat_analytics":
                continue
            if ttn in _META_ANALYSIS_CHAIN_TRAIN_TASKS:
                continue
            non_analytics.append(w)

        analytics_workflows = []
        index = 1
        used_workflow_ids: Set[str] = {
            str(w.get("id")).strip()
            for w in workflows
            if isinstance(w, dict) and str(w.get("id") or "").strip()
        }

        for func_name, cfg_list in self.functions_map.items():
            if not isinstance(cfg_list, list):
                continue

            for cfg_idx, cfg_dict in enumerate(cfg_list):
                if not isinstance(cfg_dict, dict):
                    continue

                base_workload_args = dict(template_workload_defaults)
                base_workload_args.update(cfg_dict)

                effective_comp_type = base_workload_args.get("computation_type") or FUNCTION_TO_COMPUTATION_TYPE.get(
                    str(func_name)
                )
                if not effective_comp_type:
                    continue
                base_workload_args["computation_type"] = effective_comp_type

                if "global_schema" not in base_workload_args:
                    base_workload_args["global_schema"] = DEFAULT_GLOBAL_SCHEMA

                if str(effective_comp_type).strip().lower() == "meta-analysis":
                    # Exceptional Response Discrimination: emit the multi-workflow chain
                    # (score-comp -> mean-stdev -> lr-fit -> meta-analysis).
                    analytics_workflows.extend(
                        self._build_meta_analysis_chain_for_config(
                            data=data,
                            func_name=func_name,
                            cfg_idx=cfg_idx,
                            cfg_dict=cfg_dict,
                            base_workload_args=base_workload_args,
                            client_count=client_count,
                            used_workflow_ids=used_workflow_ids,
                        )
                    )
                    continue

                selected_model_keys = self._get_selected_model_keys()
                is_biomarker_discovery = bool(
                    str(base_workload_args.get("is_biomarker_discovery", "")).strip().lower() in ("true", "1")
                )

                if selected_model_keys and is_biomarker_discovery:
                    model_keys_to_build: List[str] = []
                    for selected_model_key in selected_model_keys:
                        if not isinstance(selected_model_key, str):
                            continue
                        normalized_model_key = selected_model_key.strip()
                        if not normalized_model_key:
                            continue
                        if normalized_model_key not in model_keys_to_build:
                            model_keys_to_build.append(normalized_model_key)

                    for selected_model_key in model_keys_to_build:
                        workload_args = dict(base_workload_args)
                        workload_args["model_key"] = selected_model_key

                        self._coerce_workload_arg_types(func_name, workload_args)
                        self._apply_custom_config_vars_to_filters(func_name, workload_args)

                        wf = copy.deepcopy(base_template)
                        wf_id = self._get_unique_workflow_id(
                            f"workflow_stat_analytics__{selected_model_key}",
                            used_workflow_ids,
                        )
                        wf["id"] = wf_id

                        wf_args = wf.get("args") or {}
                        wf_args["min_clients"] = client_count
                        if "num_rounds" not in wf_args:
                            wf_args["num_rounds"] = 3
                        wf_args["train_task_name"] = "task_stat_analytics"
                        wf_args["workload_args"] = workload_args
                        wf["args"] = wf_args

                        config_props = dict(cfg_dict)
                        config_props["model_key"] = selected_model_key

                        try:
                            self._ensure_workflow_binding(func_name, config_props, wf_id)
                        except Exception as e:
                            print(
                                f"NVFlareJobStager: Failed to record workflow_id mapping for {func_name}[{cfg_idx}] -> {wf_id}: {e}",
                                flush=True,
                            )

                        analytics_workflows.append(wf)

                    continue

                workload_args = dict(base_workload_args)

                self._coerce_workload_arg_types(func_name, workload_args)
                self._apply_custom_config_vars_to_filters(func_name, workload_args)

                wf = copy.deepcopy(base_template)
                wf_id = self._get_unique_workflow_id(
                    f"workflow_stat_analytics_{index}",
                    used_workflow_ids,
                )
                index += 1
                wf["id"] = wf_id

                wf_args = wf.get("args") or {}
                wf_args["min_clients"] = client_count
                if "num_rounds" not in wf_args:
                    wf_args["num_rounds"] = 3
                wf_args["train_task_name"] = "task_stat_analytics"
                wf_args["workload_args"] = workload_args
                wf["args"] = wf_args

                try:
                    self._ensure_workflow_binding(func_name, cfg_dict, wf_id)
                except Exception as e:
                    print(
                        f"NVFlareJobStager: Failed to record workflow_id mapping for {func_name}[{cfg_idx}] -> {wf_id}: {e}",
                        flush=True,
                    )

                analytics_workflows.append(wf)

        analytics_workflows = self._wire_open_access_km_score_reuse(analytics_workflows)

        if not analytics_workflows:
            return workflows

        # Stat templates were removed from non_analytics; anything left (e.g. KeyGen, enc biomarker)
        # keeps template order. Profile-consolidate must run *after* all stat workflows, not here.
        tail_profile = [
            w
            for w in non_analytics
            if isinstance(w, dict) and w.get("id") == _PROFILE_CONSOLIDATE_WORKFLOW_ID
        ]
        non_analytics_core = [
            w
            for w in non_analytics
            if not (isinstance(w, dict) and w.get("id") == _PROFILE_CONSOLIDATE_WORKFLOW_ID)
        ]
        return non_analytics_core + analytics_workflows + tail_profile

    def _mark_lcs_only_encrypted_workflows(self, workflows: List[Dict]) -> bool:
        """Set ``lcs_only=True`` on the model_upload + score_cache + LCS score_postprocess
        workload_args when this is an LCS-only encrypted job. Returns True if anything changed.

        This is the single flag that (a) makes the leader upload the model unbaked at rsf=1 and
        emit no 1/rsf ciphertext, (b) makes the LCS postprocess skip the descale (via the absent
        1/rsf artifact), and (c) lowers depth_required to 4 for the score_cache/postprocess (and,
        through the model-upload level-match, the upload itself). KM-only / combined jobs never
        enter here, so they keep the baked shared cache at depth 5.
        """
        if not self._is_lcs_only_encrypted_biomarker():
            return False
        targets = {
            "workflow_model_upload",
            "workflow_enc_biomarker_score_cache",
            "workflow_enc_biomarker_score_postprocess",
        }
        changed = False
        for wf in workflows:
            if not isinstance(wf, dict):
                continue
            wf_id = str(wf.get("id") or "").strip()
            # ids may be suffixed (e.g. __<model_key>); match by prefix.
            if any(wf_id == t or wf_id.startswith(t + "__") for t in targets):
                wa = (wf.get("args") or {}).get("workload_args")
                if isinstance(wa, dict) and not wa.get("lcs_only"):
                    wa["lcs_only"] = True
                    changed = True
        return changed

    def _wire_open_access_km_score_reuse(self, analytics_workflows: List[Dict]) -> List[Dict]:
        """Make an open-access Kaplan-Meier discovery workflow REUSE the per-patient scores a
        Exceptional Response Discrimination (meta-analysis) chain already computes for the same model,
        instead of re-scoring the cohort from the on-disk model.

        When both a KM biomarker-discovery function and an LCS function are selected for the same
        open-access ``model_key``, the LCS chain emits a ``biomarker_score_computation`` that scores
        every client's cohort once and caches the raw per-patient scores on each client. This pass:

          1. sets ``from_cached_score`` on each such KM workflow, so its grouping consumes the
             cached scores (``local_pre_kaplan_meier``'s reuse branch) rather than recomputing, and
          2. reorders each reusing KM workflow to run immediately AFTER its model's
             ``biomarker_score_computation`` -- the cache is populated by that workflow and cleared
             at the next one, so the KM must fall inside its model's cache window.

        No-op unless a matching (KM discovery + score-comp) pair for the same model exists, so a
        KM-only job (no LCS chain, no cache) keeps recomputing untouched. The encrypted path is
        never touched -- it has its own precomputed-score handoff (``w_biomarker_risk_scores``).
        """
        if self._is_encrypted_model():
            return analytics_workflows

        def _wl(wf: Dict) -> Dict:
            args = wf.get("args") if isinstance(wf, dict) else None
            wl = (args or {}).get("workload_args") if isinstance(args, dict) else None
            return wl if isinstance(wl, dict) else {}

        def _is_true(v) -> bool:
            return str(v).strip().lower() in ("true", "1")

        # model_keys for which an open-access biomarker_score_computation will populate the cache.
        score_comp_models: Set[str] = set()
        for wf in analytics_workflows:
            wl = _wl(wf)
            if str(wl.get("computation_type", "")).strip() == "biomarker_score_computation":
                mk = str(wl.get("model_key", "")).strip()
                if mk:
                    score_comp_models.add(mk)
        if not score_comp_models:
            return analytics_workflows

        # KM biomarker-discovery workflows whose model has a score cache -> mark for reuse.
        reuse_km_by_model: Dict[str, List[Dict]] = {}
        for wf in analytics_workflows:
            wl = _wl(wf)
            if str(wl.get("computation_type", "")).strip() != "kaplan-meier":
                continue
            if not _is_true(wl.get("is_biomarker_discovery", "")):
                continue
            mk = str(wl.get("model_key", "")).strip()
            if not mk or mk not in score_comp_models:
                continue
            wl["from_cached_score"] = True
            reuse_km_by_model.setdefault(mk, []).append(wf)
        if not reuse_km_by_model:
            return analytics_workflows

        # Reorder: drop the reusing KM workflows from their original slots and re-emit each one
        # right after its model's biomarker_score_computation (stable for everything else).
        reuse_ids = {id(wf) for wfs in reuse_km_by_model.values() for wf in wfs}
        reordered: List[Dict] = []
        for wf in analytics_workflows:
            if id(wf) in reuse_ids:
                continue
            reordered.append(wf)
            wl = _wl(wf)
            if str(wl.get("computation_type", "")).strip() == "biomarker_score_computation":
                mk = str(wl.get("model_key", "")).strip()
                for km_wf in reuse_km_by_model.get(mk, []):
                    reordered.append(km_wf)
        return reordered

    def _resolve_meta_analysis_model_keys(self, cfg_dict: Dict) -> List[str]:
        """Resolve the model keys for the meta-analysis chain.

        Reads the workflow-groups selection (``predictive_modeling_method_ids``),
        falling back to ``cfg_dict["model_key"]``.
        """
        keys = [k for k in self._get_selected_model_keys() if isinstance(k, str) and k.strip()]
        if not keys:
            fallback = cfg_dict.get("model_key")
            if isinstance(fallback, str) and fallback.strip():
                keys = [fallback.strip()]
        if not keys:
            raise ValueError(
                "Exceptional Response Discrimination requires at least one "
                "model_key, resolved from the workflow-groups "
                "'predictive_modeling_method_ids' selection or the function config "
                "'model_key'. None was provided."
            )
        seen: Set[str] = set()
        out: List[str] = []
        for k in keys:
            kk = k.strip()
            if kk not in seen:
                seen.add(kk)
                out.append(kk)
        return out

    def _load_meta_analysis_chain_templates(self, model_type: str) -> List[Dict]:
        """Load the meta-analysis chain workflow templates for ``model_type``.

        Open-access loads ``config_meta_analysis_open.json``; encrypted loads
        ``config_meta_analysis_enc.json`` (the encrypt-at-initiator chain:
        model_upload[Encrypted] -> HE scoring -> mean-stdev -> meta-analysis).
        Both drop the bundled ``workflow_KeyGen`` (the runtime template already
        provides KeyGen).
        """
        mt = str(model_type or "").strip().lower()
        if mt == MODEL_TYPE_ENCRYPTED.lower():
            config_name = _META_ANALYSIS_CHAIN_CONFIG_ENCRYPTED
        else:
            config_name = _META_ANALYSIS_CHAIN_CONFIG_OPEN
        config_path = Path(LOCAL_NVFLARE_JOBS_DIR) / "configs" / config_name
        with open(config_path, "r") as f:
            chain_config = json.load(f)
        workflows = chain_config.get("workflows") or []
        return [
            w
            for w in workflows
            if isinstance(w, dict) and str(w.get("id") or "").strip() != "workflow_KeyGen"
        ]

    def _resolve_horizon_threshold_for_model(self, model_key: str, cancer_type: str) -> Optional[float]:
        """Read the ``ER_threshold`` (horizon) from the model's cutoff CSV.

        Injected into the encrypted meta-analysis chain: only the ciphertext is
        placed on the server, so the persistor cannot read this column itself.
        ``ER_threshold`` is a non-secret study horizon (distinct from the secret
        cutoff/coefficients), so shipping it in ``workload_args`` does not expose
        model weights. Returns None on any failure; the encrypted persistor has
        no plaintext CSV to fall back to, so a None here surfaces downstream as a
        missing-horizon error -- we log the cause so it is traceable.
        """
        def _give_up(reason: str) -> None:
            print(
                f"NVFlareJobStager: could not resolve ER_threshold for "
                f"{model_key}/{cancer_type} ({reason}); the encrypted persistor "
                f"cannot read it from a plaintext CSV.",
                flush=True,
            )
            return None

        try:
            cutoff_src = self._find_biomarker_model_file(model_key, cancer_type, "cutoff")
        except Exception as e:
            return _give_up(f"cutoff file lookup failed: {e}")
        if not cutoff_src or not Path(cutoff_src).exists():
            return _give_up("cutoff file not found")
        try:
            with open(cutoff_src, newline="") as f:
                row = next(csv.DictReader(f), None)
            if not row or "ER_threshold" not in row:
                return _give_up("ER_threshold column missing")
            horizon = float(row["ER_threshold"])
        except (StopIteration, TypeError, ValueError, KeyError) as e:
            return _give_up(f"ER_threshold parse failed: {e}")
        if horizon > 0:
            return horizon
        return _give_up(f"non-positive ER_threshold ({horizon})")

    def _template_hide_result_from_server(self, data: Dict) -> bool:
        """Read the persistor's ``hide_result_from_server`` from the server config."""
        for comp in (data.get("components") or []):
            if isinstance(comp, dict) and comp.get("id") == "persistor":
                return bool((comp.get("args") or {}).get("hide_result_from_server", False))
        return False

    def _build_meta_analysis_chain_for_config(
        self,
        data: Dict,
        func_name: str,
        cfg_idx: int,
        cfg_dict: Dict,
        base_workload_args: Dict,
        client_count: int,
        used_workflow_ids: Set[str],
    ) -> List[Dict]:
        """Build the open-access meta-analysis (LCS) chain for one function-config.

        Per selected model_key, clones the chain templates from
        ``config_meta_analysis_open.json``, patches ``cancer_type`` / ``model_key`` /
        ``global_schema`` into each workflow's ``workload_args``, suffixes the ids with
        ``__<model_key>`` (so two keys produce two non-colliding chains), resolves
        ``num_rounds`` for the HE steps from the persistor's
        ``hide_result_from_server``, and binds the terminal meta-analysis workflow to
        the function-config.
        """
        model_type = str(base_workload_args.get("model_type") or "").strip()
        is_encrypted = model_type.lower() == MODEL_TYPE_ENCRYPTED.lower()
        model_keys = self._resolve_meta_analysis_model_keys(cfg_dict)
        chain_templates = self._load_meta_analysis_chain_templates(model_type)
        hide_result = self._template_hide_result_from_server(data)
        cancer_type = base_workload_args.get("cancer_type")
        global_schema = base_workload_args.get("global_schema", DEFAULT_GLOBAL_SCHEMA)

        built: List[Dict] = []
        for model_key in model_keys:
            terminal_wf_id: Optional[str] = None
            for tmpl in chain_templates:
                wf = copy.deepcopy(tmpl)
                base_id = str(wf.get("id") or "").strip()
                wf_args = wf.get("args") or {}
                wf_args["min_clients"] = client_count

                # HE stat_analytics steps need an extra AES-dispersal round when
                # hide_result_from_server; clear-text reference steps keep their
                # template num_rounds. Keyed off train_task_name (not the workflow id)
                # so a template rename can't silently break the round count.
                if wf_args.get("train_task_name") == "task_stat_analytics":
                    required_rounds = 4 if hide_result else 3
                    wf_args["num_rounds"] = required_rounds
                    wf_args["persist_every_n_rounds"] = required_rounds

                wl = wf_args.get("workload_args")
                if isinstance(wl, dict):
                    if "cancer_type" in wl and cancer_type is not None:
                        wl["cancer_type"] = cancer_type
                    if "model_key" in wl:
                        wl["model_key"] = model_key
                    # Keep the list form ``model_keys`` (used by HE scoring / .ct
                    # resolution) consistent with the per-chain ``model_key``.
                    if "model_keys" in wl:
                        wl["model_keys"] = [model_key]
                    # Encrypted meta-analysis: inject the non-secret horizon here, since
                    # the server has no plaintext cutoff CSV to read ER_threshold from.
                    # time_column_id marks the meta-analysis (fused lr_fit) step.
                    if (
                        is_encrypted
                        and "time_column_id" in wl
                        and cancer_type is not None
                        and wl.get("horizon_threshold") is None
                    ):
                        horizon = self._resolve_horizon_threshold_for_model(model_key, cancer_type)
                        if horizon is not None:
                            wl["horizon_threshold"] = horizon
                    wl.setdefault("global_schema", global_schema)

                wf["id"] = self._get_unique_workflow_id(f"{base_id}__{model_key}", used_workflow_ids)
                wf["args"] = wf_args
                built.append(wf)
                terminal_wf_id = wf["id"]

            if terminal_wf_id is not None:
                config_props = dict(cfg_dict)
                config_props["model_key"] = model_key
                try:
                    self._ensure_workflow_binding(func_name, config_props, terminal_wf_id)
                except Exception as e:
                    print(
                        f"NVFlareJobStager: Failed to record workflow_id mapping for "
                        f"{func_name}[{cfg_idx}] -> {terminal_wf_id}: {e}",
                        flush=True,
                    )

        return built

    # Insert a threshold_samples workflow into the workflow list when thresholding is enabled.
    def _insert_threshold_workflow(self, data: Dict, workflows: List[Dict], client_count: int) -> List[Dict]:
        if self.threshold is None:
            return workflows

        if str(self.job_template_name).lower() == SupportedFunction.PARTICIPATION_CONFIRMATION.value.lower():
            return workflows

        stat_map: Dict[str, Dict] = {}
        for w in workflows:
            args = w.get("args") or {}
            train_task = (args.get("train_task_name") or "").lower()
            if train_task == "task_stat_analytics":
                wf_id = w.get("id")
                if not wf_id:
                    continue
                workload_args = args.get("workload_args") or {}
                stat_map[wf_id] = workload_args

        if not stat_map:
            return workflows

        if self.threshold.method == ThresholdMethod.PROTECTED:
            tmpl = THRESHOLD_WORKFLOW_TEMPLATE_SECURE
        else:
            tmpl = THRESHOLD_WORKFLOW_TEMPLATE_UNSECURE

        threshold_wf = copy.deepcopy(tmpl)
        t_args = threshold_wf.get("args") or {}
        t_args["min_clients"] = client_count

        w_args = t_args.get("workload_args") or {}
        try:
            w_args["min_global_samples"] = int(self.threshold.threshold)
        except (TypeError, ValueError):
            pass
        w_args["workflows"] = stat_map
        t_args["workload_args"] = w_args
        threshold_wf["args"] = t_args

        keygen_idx = None
        for i, w in enumerate(workflows):
            w_id = (w.get("id") or "").lower()
            args = w.get("args") or {}
            train_task = (args.get("train_task_name") or "").lower()
            if "keygen" in w_id or train_task == "task_keygen":
                keygen_idx = i
                break

        new_workflows = list(workflows)
        if keygen_idx is not None:
            insert_pos = keygen_idx + 1
        else:
            insert_pos = len(new_workflows)
        new_workflows.insert(insert_pos, threshold_wf)
        return new_workflows

    def _get_selected_global_schema_path(self) -> Path:
        """Resolve the source-controlled schema for this job's project/group.

        Project 1 has one schema because it has no datasource groups. Project 2
        requires a datasource-group-specific schema so that
        ``metadata.biomarker_covariates`` matches the selected model artifacts.
        Other projects retain the template schema as a backward-compatible fallback
        until a source-controlled schema is added for them.
        """
        cached = getattr(self, "_global_schema_source_path", None)
        if isinstance(cached, Path):
            return cached

        if self.project_id == 1:
            schema_path = (
                LOCAL_GLOBAL_SCHEMA_DIR
                / "project_1"
                / DEFAULT_GLOBAL_SCHEMA
            )
        elif self.project_id == 2:
            if self.datasource_group_id is None:
                raise ValueError(
                    "Project 2 requires datasource_group_id to select a global schema."
                )
            try:
                datasource_group_id = int(self.datasource_group_id)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"Invalid datasource_group_id for Project 2: {self.datasource_group_id!r}"
                ) from e

            schema_path = (
                LOCAL_GLOBAL_SCHEMA_DIR
                / "project_2"
                / f"datasource_group_{datasource_group_id}"
                / DEFAULT_GLOBAL_SCHEMA
            )
        else:
            templates_root = Path(LOCAL_NVFLARE_JOBS_DIR)
            template_name = str(self.job_template_name or DEFAULT_JOB_TEMPLATE)
            schema_path = (
                templates_root
                / template_name
                / "app_server"
                / "custom"
                / DEFAULT_GLOBAL_SCHEMA
            )

        if not schema_path.is_file():
            raise FileNotFoundError(
                "Global schema not found for "
                f"project_id={self.project_id}, datasource_group_id={self.datasource_group_id}: "
                f"{schema_path}"
            )

        self._global_schema_source_path = schema_path
        return schema_path

    # Load and validate the selected global schema before it is staged into app_server/custom.
    def _load_global_schema(self) -> Dict[str, Any]:
        schema_path = self._get_selected_global_schema_path()
        try:
            with schema_path.open("r", encoding="utf-8") as f:
                schema = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in global schema {schema_path}: {e}") from e
        except OSError as e:
            raise OSError(f"Unable to read global schema {schema_path}: {e}") from e

        if not isinstance(schema, dict):
            raise ValueError(f"Global schema {schema_path} must contain a JSON object.")

        return schema

    def _stage_selected_global_schema(self, job_dir: Path) -> None:
        """Copy the selected project/group schema into the staged server custom dir."""
        source = self._get_selected_global_schema_path()
        schema = self._load_global_schema()

        target_dir = job_dir / "app_server" / "custom"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / DEFAULT_GLOBAL_SCHEMA
        shutil.copy2(source, target)

        # Reuse the already validated selected schema for OpenFHE group-count logic.
        self._global_schema_cache = schema

        print(
            "NVFlareJobStager: staged global schema "
            f"source={source}, target={target}, "
            f"project_id={self.project_id}, datasource_group_id={self.datasource_group_id}",
            flush=True,
        )

    # Determine the number of groups for a categorical column using the global schema.
    def _get_group_count_from_schema(self, group_column_id: str) -> int:
        if not group_column_id:
            return 2
        if not hasattr(self, "_global_schema_cache"):
            self._global_schema_cache = self._load_global_schema()
        schema = getattr(self, "_global_schema_cache", None)
        if not isinstance(schema, dict):
            return 2
        columns = schema.get("columns")
        if not isinstance(columns, dict):
            return 2
        col = columns.get(group_column_id)
        if not isinstance(col, dict):
            return 2
        categories = col.get("categories")
        if not isinstance(categories, list):
            return 2
        if not categories:
            return 2
        return len(categories)

    # Update the persistor component's OpenFHE arguments based on selected functions and threshold settings.
    def _update_persistor_openfhe_args(self, data: Dict, client_count: int) -> bool:
        components = data.get("components")
        if not isinstance(components, list):
            return False

        persistor = None
        for comp in components:
            if isinstance(comp, dict) and comp.get("id") == "persistor":
                persistor = comp
                break

        if persistor is None:
            return False

        args = persistor.get("args")
        if not isinstance(args, dict):
            args = {}
            persistor["args"] = args

        updated = False

        if args.get("non_contributing_clients") != self.non_contributing_clients:
            args["non_contributing_clients"] = self.non_contributing_clients
            updated = True

        if args.get("exclude_analyzing_clients") != self.exclude_analyzing_clients:
            args["exclude_analyzing_clients"] = self.exclude_analyzing_clients
            updated = True

        # Manually override is_server_data_owner until this gets implemented at server (initiator now at site3)
        if args.get("is_server_data_owner") is not False:
            args["is_server_data_owner"] = False
            updated = True

        if args.get("is_server_contributing_to_aggregation") is not False:
            args["is_server_contributing_to_aggregation"] = False
            updated = True

        is_server_data_owner = bool(args.get("is_server_data_owner", True))
        is_server_contributing = bool(args.get("is_server_contributing_to_aggregation", True))
        num_data_owners = client_count + 1 if (is_server_data_owner and is_server_contributing) else client_count

        if not self.functions_map and self.threshold is None and not self._is_encrypted_model():
            return updated

        mult_depth_required = 0.0
        require_mult_keys = False
        require_index_keys = False
        require_sum_keys = False
        required_indices = set()

        if self._is_encrypted_model():
            require_index_keys = True
            required_indices.update(ENCRYPTED_PERSISTOR_INDICES)
            # Reuse-scores: the shared score-cache producer + postprocess consumers need
            # depth_required=5 (3 pack + 1 tail + 1 decrypt margin). KM/combined jobs already
            # exceed this via kaplan-meier, so depth-5 biomarker is free. An LCS-only encrypted
            # job (no KM consumer) uploads unbaked (rsf=1) and skips the descale tail, so it needs
            # only 3 pack + 1 decrypt margin = 4 -- one fewer RNS limb (~20%/op, same ring 16384).
            # Must match the persistor depth_required (lcs_only branch) and the lcs_only flag set
            # on the model_upload/score_cache/score_postprocess workload_args below.
            mult_depth_required = max(
                mult_depth_required, 4.0 if self._is_lcs_only_encrypted_biomarker() else 5.0
            )

        if self.threshold is not None:
            if self.threshold.method == ThresholdMethod.PROTECTED:
                mult_depth_required = max(mult_depth_required, math.log2(num_data_owners + 1))
                require_mult_keys = True
            else:
                mult_depth_required = max(mult_depth_required, 1.0)

        for func_name, cfg_list in (self.functions_map or {}).items():
            comp_type_default = FUNCTION_TO_COMPUTATION_TYPE.get(str(func_name))
            if not isinstance(cfg_list, list):
                continue

            for cfg in cfg_list:
                if not isinstance(cfg, dict):
                    continue

                comp_type = cfg.get("computation_type") or comp_type_default
                if not comp_type:
                    continue

                comp_type_str = str(comp_type).lower()

                if comp_type_str == "mean":
                    mult_depth_required = max(mult_depth_required, 2.0)

                elif comp_type_str == "stdev":
                    mult_depth_required = max(mult_depth_required, 3.0)
                    require_mult_keys = True
                    require_index_keys = True
                    required_indices.update([1, 2])

                elif comp_type_str == "chi2":
                    mult_depth_required = max(
                        mult_depth_required,
                        4.0 + float(math.ceil(math.log2(num_data_owners))) + 1.0,
                    )
                    require_mult_keys = True
                    require_sum_keys = True

                elif comp_type_str == "kaplan-meier":
                    group_column_id = cfg.get("group_column_id")
                    group_count = self._get_group_count_from_schema(
                        str(group_column_id) if group_column_id is not None else ""
                    )
                    mult_depth_required = max(
                        mult_depth_required,
                        6.0 + float(math.ceil(math.log2(num_data_owners))) + float(group_count - 1),
                    )
                    require_mult_keys = True

                elif comp_type_str == "t-test":
                    mult_depth_required = max(mult_depth_required, 5.0)
                    require_mult_keys = True
                    require_index_keys = True
                    required_indices.update([1, 2, 8])

                elif comp_type_str == "meta-analysis":
                    mult_depth_required = max(mult_depth_required, 4.0)
                    require_mult_keys = True
                    require_index_keys = True
                    required_indices.update([1, 2])

        if mult_depth_required <= 0 and not self._is_encrypted_model():
            return False

        mult_depth_int = int(math.ceil(mult_depth_required)) if mult_depth_required > 0 else int(args.get("mult_depth") or 0)

        if mult_depth_required > 0 and args.get("mult_depth") != mult_depth_int:
            args["mult_depth"] = mult_depth_int
            updated = True

        if args.get("generate_mult_keys") != require_mult_keys:
            args["generate_mult_keys"] = require_mult_keys
            updated = True

        if self._is_encrypted_model():
            if args.get("generate_index_keys") != ENCRYPTED_PERSISTOR_GENERATE_INDEX_KEYS:
                args["generate_index_keys"] = ENCRYPTED_PERSISTOR_GENERATE_INDEX_KEYS
                updated = True
        else:
            if args.get("generate_index_keys") != require_index_keys:
                args["generate_index_keys"] = require_index_keys
                updated = True

        if args.get("generate_sum_keys") != require_sum_keys:
            args["generate_sum_keys"] = require_sum_keys
            updated = True

        if self._is_encrypted_model():
            indices_list = list(ENCRYPTED_PERSISTOR_INDICES)
        else:
            indices_list = sorted(required_indices) if require_index_keys else []

        if args.get("indices") != indices_list:
            args["indices"] = indices_list
            updated = True

        return updated

    # Patch the server config JSON with updated workflows, min_clients, and OpenFHE settings.
    def _update_server_config_text(self, raw_text: str, client_count: int) -> Optional[str]:
        text = re.sub(r"/\*.*?\*/", "", raw_text, flags=re.DOTALL)
        text = re.sub(r"(^|\s)//.*?$", r"\1", text, flags=re.MULTILINE)
        try:
            data = json.loads(text)
        except Exception:
            return None

        workflows = data.get("workflows")
        if not isinstance(workflows, list):
            return None

        updated = False

        server_cfg = data.get("server")
        if not isinstance(server_cfg, dict):
            server_cfg = {}
            data["server"] = server_cfg
            updated = True

        if server_cfg.get("heart_beat_timeout") != 120:
            server_cfg["heart_beat_timeout"] = 120
            updated = True

        # Perf: server-side task dispatch interval. Lower = less per-round polling latency across the
        # ~39 federated rounds (each round waits for the server to hand out the next task). 3-client
        # standalone, so the extra polling load is negligible.
        if server_cfg.get("task_request_interval") != 0.5:
            server_cfg["task_request_interval"] = 0.5
            updated = True

        for w in workflows:
            args = w.get("args")
            if isinstance(args, dict) and args.get("min_clients") != client_count:
                args["min_clients"] = client_count
                updated = True
            # Perf: min_clients is forced to client_count (all clients) just above, so
            # wait_time_after_min_received only grants grace for clients *beyond* min -- of which there
            # are none. Setting it to 0 removes a per-round straggler-grace dead-time with no correctness
            # impact (the controller still waits for all min_clients=all). task_check_period is the
            # client task-poll interval; 0.1 picks up the next round's task faster than 0.5.
            if isinstance(args, dict) and args.get("wait_time_after_min_received") != 0:
                args["wait_time_after_min_received"] = 0
                updated = True
            if isinstance(args, dict) and args.get("task_check_period") != 0.1:
                args["task_check_period"] = 0.1
                updated = True
            # Ensure enc biomarker workflow has enough time for preprocess + HE aggregation
            if isinstance(args, dict) and self._workflow_is_enc_biomarker_he(w):
                if args.get("train_timeout", 0) == 0:
                    args["train_timeout"] = ENC_BIOMARKER_DISC_TRAIN_TIMEOUT_SEC
                    updated = True

        if self.functions_map:
            new_workflows = self._build_stat_analytics_workflows(data, workflows, client_count)
            if new_workflows is not workflows:
                workflows = new_workflows
                data["workflows"] = workflows
                updated = True

        if self.threshold is not None and self.functions_map:
            new_workflows = self._insert_threshold_workflow(data, workflows, client_count)
            if new_workflows is not workflows:
                workflows = new_workflows
                data["workflows"] = workflows
                updated = True

        # Reuse-scores split/shared-cache assembly. Order matters: the KM risk-group
        # postprocess is inserted before the kaplan-meier workflow; the single shared
        # score cache is inserted before the first score consumer (KM and/or LCS
        # postprocess); the single shared model_upload is inserted before the score
        # cache. (The LCS score postprocess comes from the meta-analysis chain config.)
        new_workflows = self._insert_enc_biomarker_risk_group_postprocess_workflow(workflows, client_count)
        if new_workflows is not workflows:
            workflows = new_workflows
            data["workflows"] = workflows
            updated = True

        new_workflows = self._insert_enc_biomarker_score_cache_workflow(workflows, client_count)
        if new_workflows is not workflows:
            workflows = new_workflows
            data["workflows"] = workflows
            updated = True

        new_workflows = self._insert_model_upload_workflow(workflows, client_count)
        if new_workflows is not workflows:
            workflows = new_workflows
            data["workflows"] = workflows
            updated = True

        # LCS-only encrypted jobs: flag the upload + score-cache + LCS postprocess so the model is
        # uploaded unbaked (rsf=1), the descale is skipped, and depth_required drops to 4 (matching
        # the mult_depth=4 floor set above). No-op for KM-only / combined (baked, depth 5).
        if self._mark_lcs_only_encrypted_workflows(workflows):
            data["workflows"] = workflows
            updated = True

        if str(self.job_template_name).lower() != SupportedFunction.PARTICIPATION_CONFIRMATION.value.lower():
            if self._update_persistor_openfhe_args(data, client_count):
                updated = True

        if not updated:
            return None

        return json.dumps(data, indent=2, ensure_ascii=False)

    # Recursively copy all non-bytecode files from a template directory to a destination.
    def _copytree(self, src: Path, dst: Path) -> None:
        for root, _, files in os.walk(src):
            rel = Path(root).relative_to(src)
            (dst / rel).mkdir(parents=True, exist_ok=True)
            for f in files:
                s = Path(root) / f
                d = dst / rel / f
                if d.suffix in (".pyc", ".pyo"):
                    continue
                shutil.copy2(s, d)

    # Build a local job directory from a template, applying config patches and writing filters/meta.
    def _build_local_job_dir(self, job_template: str) -> Path:
        template = Path(LOCAL_NVFLARE_JOBS_DIR) / job_template

        print(
            f"NVFlareJobStager: using template path: {template}",
            flush=True,
        )
        print(
            f"NVFlareJobStager: raw participating_clients CSV: {repr(self.participating_clients)}",
            flush=True,
        )

        if not template.exists():
            raise FileNotFoundError(f"Job template not found: {template}")

        job_dir = (LOCAL_JOB_ROOT / job_template).resolve()

        print(
            f"NVFlareJobStager: building job_dir: {job_dir}",
            flush=True,
        )

        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        self._copytree(template, job_dir)
        self._stage_selected_global_schema(job_dir)
        self._write_model_file_sources_if_needed(job_dir)

        clients = self._parse_clients(self.participating_clients or "")

        print(
            f"NVFlareJobStager: parsed clients: {clients}",
            flush=True,
        )
        print(
            f"NVFlareJobStager: participation settings: "
            f"non_contributing_clients={self.non_contributing_clients}, "
            f"exclude_analyzing_clients={self.exclude_analyzing_clients}",
            flush=True,
        )

        client_count = max(1, len(clients))

        print(
            f"NVFlareJobStager: computed client_count: {client_count}",
            flush=True,
        )

        server_cfg = job_dir / "app_server" / "config" / "config_fed_server.json"

        print(
            f"NVFlareJobStager: server config path: {server_cfg}",
            flush=True,
        )

        if server_cfg.exists():
            try:
                patched = self._update_server_config_text(
                    server_cfg.read_text(encoding="utf-8"),
                    client_count
                )
                if patched is None:
                    print(
                        "NVFlareJobStager: server config patch returned None; leaving template config unchanged",
                        flush=True,
                    )
                else:
                    print(f"Patched server config:\n\n\n{patched}", flush=True)
                    server_cfg.write_text(patched, encoding="utf-8")
            except Exception as e:
                print(
                    f"NVFlareJobStager: exception while patching server config: {e}",
                    flush=True,
                )
                raise

        filters_json_obj: Dict[str, object] = {}

        if self.filters is not None:
            if isinstance(self.filters, dict):
                filters_json_obj = dict(self.filters)
            else:
                try:
                    filters_json_obj = json.loads(self.filters)
                except Exception:
                    filters_json_obj = {"filters_raw": self.filters}

        expanded_functions_map = self._expand_functions_map_for_selected_models()
        if expanded_functions_map:
            filters_json_obj["functions_map"] = expanded_functions_map
        elif self.functions_map:
            filters_json_obj["functions_map"] = self.functions_map

        if self.threshold is not None:
            filters_json_obj["threshold_config"] = {
                "id": self.threshold.id,
                "method": self.threshold.method.value if self.threshold.method is not None else None,
                "threshold": self.threshold.threshold,
            }

        if self.project is not None:
            project_json = jsonable_encoder(self.project)
            expanded_project_functions = self._expand_project_functions_for_selected_models()
            if expanded_project_functions:
                project_json["functions"] = expanded_project_functions
            filters_json_obj["project"] = project_json

        if filters_json_obj:
            print(
                f"NVFlareJobStager: filters_json_obj: "
                f"{json.dumps(filters_json_obj, indent=2, ensure_ascii=False)}",
                flush=True,
            )
            payload = json.dumps(filters_json_obj, indent=2, ensure_ascii=False)
            for app_name in ("app_client", "app_server"):
                (job_dir / app_name / "custom").mkdir(parents=True, exist_ok=True)
                (job_dir / app_name / "custom" / "filters.json").write_text(
                    payload,
                    encoding="utf-8",
                )

        print(
            f"NVFlareJobStager: preparing meta.json for clients: {clients}",
            flush=True,
        )

        meta = {
            "name": job_template.lower(),
            "resource_spec": {},
            "min_clients": client_count,
            "deploy_map": {"app_client": clients, "app_server": ["server"]},
            "job_name": job_template,
        }

        print(
            f"NVFlareJobStager: final meta.json payload: {json.dumps(meta, indent=2, ensure_ascii=False)}",
            flush=True,
        )

        (job_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return job_dir

    # Stage the job on disk and record that the job has been prepared for upload.
    def stage_job(self) -> str:
        job_template = str(self.job_template_name).lower()
        job_dir = self._build_local_job_dir(job_template)
        staged_path = str(job_dir)

        print(
            f"NVFlareJobStager: staged job path: {staged_path}",
            flush=True,
        )

        self.status_writer.log(
            "NVFlareJobStager: Job staging complete",
            JobRunnerStatus.JOB_UPLOAD,
        )
        return staged_path
