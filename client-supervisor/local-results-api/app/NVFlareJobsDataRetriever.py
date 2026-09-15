import json
import logging
import os
from typing import Dict, Any, Tuple, List

from app.SupportedFunction import FUNCTION_TO_COMPUTATION_TYPE, SupportedFunction

LOGGER = logging.getLogger("uvicorn.error")


class NVFlareJobsDataRetriever:
    def __init__(self, nvflare_job_id: str, function: SupportedFunction):
        self.function = function
        self.nvflare_job_id = nvflare_job_id

        name = self.function.name
        computation_type = FUNCTION_TO_COMPUTATION_TYPE.get(name)
        if not computation_type:
            raise ValueError(f"No computation_type mapping for function {name}")
        self.computation_type = computation_type

    def _local_jobs_root(self) -> str:
        explicit = (os.getenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION") or "").strip()
        if explicit:
            return explicit
        workspace = (os.getenv("DUALITY_NVFLARE_WORKSPACE") or "/nvflare").strip() or "/nvflare"
        return os.path.join(workspace, "job-results")

    def _read_local_json(self, path: str) -> Tuple[Dict[str, Any], str]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh), ""
        except FileNotFoundError:
            return {}, f"Unreadable file: {path} (not found)"
        except json.JSONDecodeError as e:
            return {}, f"Invalid JSON in {path}: {e}"
        except Exception as e:
            return {}, f"Unreadable file: {path} ({e})"

    def _read_prefer_raw(self, base_dir: str) -> Tuple[Dict[str, Any], str, str]:
        raw_path = os.path.join(base_dir, "raw_results.json")
        std_path = os.path.join(base_dir, "results.json")

        data, err = self._read_local_json(raw_path)
        if not err:
            return data, "", raw_path

        data2, err2 = self._read_local_json(std_path)
        if not err2:
            return data2, "", std_path

        return {}, f"{err}; {err2}", ""

    def _read_local_results(self, base_dir: str) -> Tuple[Dict[str, Any], str, str]:
        local_path = os.path.join(base_dir, "local_results.json")
        data, err = self._read_local_json(local_path)
        if not err:
            return data, "", local_path
        return {}, err, ""

    def _read_optional(
        self, base_dir: str, filename: str, ignore_missing: bool = False
    ) -> Tuple[Dict[str, Any], str, str]:
        path = os.path.join(base_dir, filename)
        data, err = self._read_local_json(path)
        if err:
            if ignore_missing and ("not found" in err.lower()):
                return {}, "", ""
            return {}, err, ""
        return data, "", path

    def list_workflow_dirs(self) -> List[str]:
        root = self._local_jobs_root()
        base = os.path.join(root, self.nvflare_job_id)
        if not os.path.isdir(base):
            LOGGER.warning("job directory not found: %s", base)
            return []

        comp_dir = os.path.join(base, self.computation_type)
        if not os.path.isdir(comp_dir):
            LOGGER.warning("computation directory not found: %s", comp_dir)
            return []

        workflow_ids: List[str] = []
        for d in os.listdir(comp_dir):
            p = os.path.join(comp_dir, d)
            if os.path.isdir(p):
                workflow_ids.append(d)
        return workflow_ids

    def retrieve_workflow_data(self, workflow_id: str) -> Dict[str, Any]:
        root = self._local_jobs_root()
        base = os.path.join(
            root,
            self.nvflare_job_id,
            self.computation_type,
            workflow_id,
        )
        LOGGER.info("reading workflow data from: %s", base)

        aggregated_dir = os.path.join(base, "aggregated")
        local_dir = os.path.join(base, "local")

        local_res, local_err, local_used = self._read_local_results(local_dir)
        aggregate_res, aggregate_err, aggregate_used = self._read_prefer_raw(aggregated_dir)
        aggregate_proc, proc_err, proc_used = self._read_optional(aggregated_dir, "processed_results.json")
        wf_error, wf_error_err, wf_error_used = self._read_optional(base, "error.json", ignore_missing=True)

        return {
            "local_results": local_res if not local_err else {"error": local_err},
            "aggregate_results": aggregate_res if not aggregate_err else {"error": aggregate_err},
            "aggregate_processed_results": aggregate_proc if not proc_err else {"error": proc_err},
            "workflow_error": wf_error if not wf_error_err and wf_error else None,
            "paths": {
                "local_used": local_used,
                "aggregated_used": aggregate_used,
                "aggregate_processed_used": proc_used,
                "workflow_error_used": wf_error_used,
            },
        }

    def retrieve_workflow_data_with_config(self, workflow_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        job_data = self.retrieve_workflow_data(workflow_id)
        return job_data, {}

    def get_profile_summary(self) -> Dict[str, Any]:
        base = os.path.join(self._local_jobs_root(), self.nvflare_job_id)
        path = os.path.join(base, "profile_summary.json")
        data, err = self._read_local_json(path)
        if err:
            return {}
        return data
