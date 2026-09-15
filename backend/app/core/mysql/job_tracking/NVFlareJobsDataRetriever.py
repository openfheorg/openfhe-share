import json
import os
import re
from typing import Dict, Any, Tuple, List

import pymysql
from app.core.ssh.SSHConnectionProvider import SSHConnectionProvider
from app.core.nvflare.NVFlareServerProvider import NVFlareProvisionProvider
from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.mysql.SupportedFunction import FUNCTION_TO_COMPUTATION_TYPE, SupportedFunction
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider

pymysql.install_as_MySQLdb()
import MySQLdb  # type: ignore


class NVFlareJobsDataRetriever:
    """
    SSH into the NVFlare server and pull initiator & aggregated JSON payloads.
    Prefer raw_results.json over results.json. Also include aggregated processed_results.json.
    Also include workflow-level error.json if present under the workflow folder.

    Response body structure (per job_id):
    {
      "initiator_results": <dict> | {"error": <str>},
      "aggregate_results": <dict> | {"error": <str>},
      "aggregate_processed_results": <dict> | {"error": <str>},
      "workflow_error": <dict> | {"error": <str>}
    }

    - If EnvironmentProvider.get_env() == Environment.LOCAL
      read results directly from the bind-mounted filesystem instead of SSH.
    - Otherwise (EC2, staging, prod), use SSH as before.

    Requires nvflare_job_id and function.
    Directory structure:
        [job_id]/
            [computation_type]/
                [workflow_id]/
                    initiator/
                    local/
                    client/
                        [site_folder]/
                            error.json
                    aggregated/
                    error.json

    Initiator result lookup order:
    1. initiator/raw_results.json
    2. initiator/results.json
    3. client/*/error.json
    4. local/local_results.json
    5. local/error.json
    """

    def __init__(self, nvflare_job_id: str, function: SupportedFunction):
        self.function = function
        if not nvflare_job_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(nvflare_job_id)):
            raise ValueError(f"Invalid nvflare_job_id: {nvflare_job_id!r}")
        self.nvflare_job_id = nvflare_job_id
        self.nvflare_provision = NVFlareProvisionProvider.get_nvflare_instance()

        self.env = EnvironmentProvider.get_env()
        self.use_local = self.env == Environment.LOCAL

        self.ssh_provider = None
        if not self.use_local:
            self.ssh_provider = SSHConnectionProvider.get_instance()

        name = self.function.name
        computation_type = FUNCTION_TO_COMPUTATION_TYPE.get(name)
        if not computation_type:
            raise ValueError(f"No computation_type mapping for function {name}")
        self.computation_type = computation_type

    def _local_jobs_root(self) -> str:
        explicit = os.getenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION")
        if explicit:
            return explicit

        workspace = os.getenv("DUALITY_NVFLARE_WORKSPACE") or "/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00"
        host = os.getenv("DUALITY_NVFLARE_HOST")
        return os.path.join(workspace, host, "job-results")

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

    def _read_remote_json(self, remote_path: str) -> Tuple[Dict[str, Any], str]:
        if not self.ssh_provider:
            return {}, "SSH provider unavailable in local mode"
        cmd = f"cat {remote_path}"
        code, out, err = self.ssh_provider.run(cmd)
        if code != 0:
            return {}, f"Unreadable file: {remote_path} ({err or out})"

        text = (out or "").strip()
        if not text:
            return {}, f"Empty file: {remote_path}"

        try:
            return json.loads(text), ""
        except json.JSONDecodeError as e:
            return {}, f"Invalid JSON in {remote_path}: {e}"

    def _read_prefer_raw(self, base_dir: str) -> Tuple[Dict[str, Any], str, str]:
        raw_path = os.path.join(base_dir, "raw_results.json")
        std_path = os.path.join(base_dir, "results.json")

        reader = self._read_local_json if self.use_local else self._read_remote_json

        data, err = reader(raw_path)
        if not err:
            return data, "", raw_path

        data2, err2 = reader(std_path)
        if not err2:
            return data2, "", std_path

        combined_err = f"{err}; {err2}"
        return {}, combined_err, ""

    def _read_optional(self, base_dir: str, filename: str, ignore_missing: bool = False) -> Tuple[Dict[str, Any], str, str]:
        path = os.path.join(base_dir, filename)
        reader = self._read_local_json if self.use_local else self._read_remote_json
        data, err = reader(path)
        if err:
            if ignore_missing and ("not found" in err.lower() or "no such file" in err.lower()):
                return {}, "", ""
            return {}, err, ""
        return data, "", path

    def _list_client_site_dirs(self, client_dir: str) -> List[str]:
        if self.use_local:
            if not os.path.isdir(client_dir):
                return []
            return [
                os.path.join(client_dir, d)
                for d in os.listdir(client_dir)
                if os.path.isdir(os.path.join(client_dir, d))
            ]

        if not self.ssh_provider:
            return []

        cmd = f"find {client_dir} -mindepth 1 -maxdepth 1 -type d"
        code, out, err = self.ssh_provider.run(cmd)
        if code != 0:
            return []

        return [line.strip() for line in out.splitlines() if line.strip()]

    def _read_client_site_error(self, client_dir: str) -> Tuple[Dict[str, Any], str, str]:
        site_dirs = self._list_client_site_dirs(client_dir)

        if not site_dirs:
            return {}, f"No site folders found under {client_dir}", ""

        collected_errors = []

        for site_dir in site_dirs:
            data, err, used = self._read_optional(site_dir, "error.json", ignore_missing=True)
            if not err and used:
                return data, "", used
            if err:
                collected_errors.append(err)
            else:
                collected_errors.append(f"Unreadable file: {os.path.join(site_dir, 'error.json')} (not found)")

        return {}, "; ".join(collected_errors), ""

    def _read_initiator_results(self, base_dir: str) -> Tuple[Dict[str, Any], str, str]:
        initiator_dir = os.path.join(base_dir, "initiator")
        client_dir = os.path.join(base_dir, "client")
        local_dir = os.path.join(base_dir, "local")

        initiator_res, initiator_err, initiator_used = self._read_prefer_raw(initiator_dir)
        if not initiator_err:
            return initiator_res, "", initiator_used

        client_error_res, client_error_err, client_error_used = self._read_client_site_error(client_dir)
        if not client_error_err and client_error_used:
            return client_error_res, "", client_error_used

        local_res, local_err, local_used = self._read_optional(local_dir, "local_results.json", ignore_missing=True)
        if not local_err and local_used:
            return local_res, "", local_used

        local_error_res, local_error_err, local_error_used = self._read_optional(local_dir, "error.json", ignore_missing=True)
        if not local_error_err and local_error_used:
            return local_error_res, "", local_error_used

        local_path = os.path.join(local_dir, "local_results.json")
        local_error_path = os.path.join(local_dir, "error.json")

        combined_parts = [initiator_err]

        if client_error_err:
            combined_parts.append(client_error_err)
        else:
            combined_parts.append(f"No readable client site error.json found under {client_dir}")

        if local_err:
            combined_parts.append(local_err)
        else:
            combined_parts.append(f"Unreadable file: {local_path} (not found)")

        if local_error_err:
            combined_parts.append(local_error_err)
        else:
            combined_parts.append(f"Unreadable file: {local_error_path} (not found)")

        return {}, "; ".join(part for part in combined_parts if part), ""

    def list_workflow_dirs(self) -> List[str]:
        if self.use_local:
            base = os.path.join(self._local_jobs_root(), self.nvflare_job_id)
        else:
            base = os.path.join(self.nvflare_provision.client_to_server_job_save_location, self.nvflare_job_id)

        comp_dirs = []
        if self.use_local:
            if not os.path.isdir(base):
                return []
            for d in os.listdir(base):
                if d.lower() == self.computation_type:
                    comp_dirs.append(os.path.join(base, d))
        else:
            cmd = f"ls -1 {base}"
            code, out, err = self.ssh_provider.run(cmd)
            if code == 0:
                for d in out.strip().splitlines():
                    if d.lower() == self.computation_type:
                        comp_dirs.append(os.path.join(base, d))

        if not comp_dirs:
            return []

        comp_dir = comp_dirs[0]

        workflow_ids = []
        if self.use_local:
            if not os.path.isdir(comp_dir):
                return []
            for d in os.listdir(comp_dir):
                if os.path.isdir(os.path.join(comp_dir, d)):
                    workflow_ids.append(d)
        else:
            cmd = f"ls -1 {comp_dir}"
            code, out, err = self.ssh_provider.run(cmd)
            if code == 0:
                for d in out.strip().splitlines():
                    workflow_ids.append(d)

        return workflow_ids

    def retrieve_workflow_data(self, workflow_id: str) -> Dict[str, Any]:
        if self.use_local:
            base = os.path.join(
                self._local_jobs_root(),
                self.nvflare_job_id,
                self.computation_type,
                workflow_id,
            )
        else:
            base = os.path.join(
                self.nvflare_provision.client_to_server_job_save_location,
                self.nvflare_job_id,
                self.computation_type,
                workflow_id,
            )

        aggregated_dir = os.path.join(base, "aggregated")

        initiator_res, initiator_err, initiator_used = self._read_initiator_results(base)
        aggregate_res, aggregate_err, aggregate_used = self._read_prefer_raw(aggregated_dir)
        aggregate_proc, proc_err, proc_used = self._read_optional(aggregated_dir, "processed_results.json")

        wf_error, wf_error_err, wf_error_used = self._read_optional(base, "error.json", ignore_missing=True)

        return {
            "initiator_results": initiator_res if not initiator_err else {"error": initiator_err},
            "aggregate_results": aggregate_res if not aggregate_err else {"error": aggregate_err},
            "aggregate_processed_results": aggregate_proc if not proc_err else {"error": proc_err},
            "workflow_error": wf_error if not wf_error_err and wf_error else None,
            "paths": {
                "initiator_used": initiator_used,
                "aggregated_used": aggregate_used,
                "aggregate_processed_used": proc_used,
                "workflow_error_used": wf_error_used,
            },
        }

    def _fetch_function_config_for_workflow(self, workflow_id: str) -> Dict[str, Any]:
        connection = MySQLConnectionProvider.get_instance().get_connection()
        cursor = connection.cursor(MySQLdb.cursors.DictCursor)
        try:
            sql = """
                SELECT dfcp.property_name, dfcp.property_value
                FROM nvflare_jobs j
                JOIN nvflare_job_function_configs njfc
                  ON njfc.job_id = j.id
                JOIN defined_function_config_sets dfcs
                  ON dfcs.id = njfc.function_config_id
                JOIN defined_functions df
                  ON df.id = dfcs.function_id
                JOIN defined_function_config_set_members dfcsm
                  ON dfcsm.config_set_id = dfcs.id
                JOIN defined_function_config_properties dfcp
                  ON dfcp.id = dfcsm.config_id
                WHERE j.nvflare_assigned_id = %s
                  AND df.name = %s
                  AND njfc.workflow_id = %s
                ORDER BY dfcp.property_name
            """
            params = (
                self.nvflare_job_id,
                self.function.value,
                workflow_id,
            )
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            cfg: Dict[str, Any] = {}
            for r in rows:
                cfg[r["property_name"]] = r["property_value"]
            return cfg
        finally:
            cursor.close()
            connection.close()

    def retrieve_workflow_data_with_config(self, workflow_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        job_data = self.retrieve_workflow_data(workflow_id)
        function_config = self._fetch_function_config_for_workflow(workflow_id)
        return job_data, function_config

    def retrieve_function_config(self, workflow_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        function_config = self._fetch_function_config_for_workflow(workflow_id)
        return function_config

    def get_profile_summary(self) -> Dict[str, Any]:
        if self.use_local:
            base = os.path.join(self._local_jobs_root(), self.nvflare_job_id)
        else:
            base = os.path.join(self.nvflare_provision.client_to_server_job_save_location, self.nvflare_job_id)

        path = os.path.join(base, "profile_summary.json")
        reader = self._read_local_json if self.use_local else self._read_remote_json
        data, err = reader(path)
        if err:
            return {}
        return data
