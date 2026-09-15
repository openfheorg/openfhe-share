"""
NVFlare Jobs Manager

Overview
--------
`nvflare_jobs` holds one row per NVFlare job broadcasted to clients (not to be confused with the task runner).
Each NVFlare job can be associated with one or more functions, and each function can have one or more
configuration sets recorded in `defined_function_config_sets`.

Relationships:
    nvflare_jobs (1)
      ├─< nvflare_job_functions (M) >─ defined_functions (1)
      └─< nvflare_job_function_configs (M) >─ defined_function_config_sets (1)
             └─< defined_function_config_set_members (M) >─ defined_function_config_properties (1)

Responsibilities:
  - Insert a new nvflare_jobs row.
  - Delegate all function/config linking to FunctionsManager.
  - Update fields (status, paths, timing).
  - Retrieve job history, optionally filtered by function names and/or date.
"""

from enum import Enum
from typing import Any, Dict, Mapping, Optional, List

from app.core.mysql.managers.FunctionsManager import FunctionsManager
from app.core.mysql.managers.ThresholdManager import Threshold, ThresholdManager
from app.core.mysql.MySQLTable import MySQLTable

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter, safe_status_update
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider


class NVFlareJobFunctionFilterMode(str, Enum):
    ANY = "ANY"
    ONLY = "ONLY"


class NVFlareJobCreateDateDateFilterMode(str, Enum):
    ON = "ON"
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class NVFlareStatus(str, Enum):
    STAGING = "Staging"
    PROCESSING = "Processing"
    FAILURE = "Failure"
    WARNING = "Warning"
    ERROR = "Error"
    DONE = "DONE"

    def __str__(self):
        return self.value

# Various statuses may override anything given because they represent a full stop in analysis
FAILURE_JOB_RUNNER_STATUSES = {
        JobRunnerStatus.THRESHOLD_NOT_MET,
        # Add more overriding statuses here as needed
    }


class NVFlareJobsManager:
    def __init__(
        self,
        status_writer: Optional[JobStatusWriter] = None,
        project_id: Optional[int] = None,
    ):
        self.nvflare_job_mysql_id: Optional[int] = None
        self.status_writer = status_writer
        self.job_id = self.status_writer.get_job_id() if self.status_writer else None
        self.project_id = project_id

        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def _client_list_to_csv(self, client_names: Optional[List[str]]) -> Optional[str]:
        if not client_names:
            return None

        cleaned_names: List[str] = []
        seen_names = set()
        for client_name in client_names:
            normalized_name = str(client_name).strip()
            if not normalized_name or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            cleaned_names.append(normalized_name)

        return ",".join(cleaned_names) if cleaned_names else None

    def _persist_threshold_if_needed(self, threshold: Threshold | None) -> Optional[int]:
        if threshold is None:
            return None
        if threshold.id is not None:
            return threshold.id
        tm = ThresholdManager()
        try:
            persisted = tm.get_or_create(threshold)
        finally:
            tm.complete()
        return persisted.id

    def establish_job_entry_id(
        self,
        filter_id: str,
        functions_map: Mapping[str, object],
        threshold: Threshold | None = None,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None,
    ) -> Optional[int]:
        if self.nvflare_job_mysql_id:
            return self.nvflare_job_mysql_id
        if not filter_id:
            return None
        if self.project_id is None:
            raise ValueError("NVFlareJobsManager.project_id must be set to create an NVFlare job.")

        normalized_map: Dict[str, List[Dict[str, str]]] = FunctionsManager.normalize_map(functions_map or {})
        if not normalized_map:
            raise ValueError("At least one function must be specified to create an NVFlare job.")

        threshold_config_id = self._persist_threshold_if_needed(threshold)

        non_contributing_clients_csv = self._client_list_to_csv(non_contributing_clients)
        exclude_analyzing_clients_csv = self._client_list_to_csv(exclude_analyzing_clients)

        fm = None
        try:
            sql_job = f"""
                INSERT INTO {MySQLTable.NVFLARE_JOBS} (
                    project_id,
                    nvflare_assigned_id,
                    filter_id,
                    threshold_config_id,
                    status,
                    job_path,
                    output_path,
                    job_runner_id,
                    non_contributing_clients,
                    exclude_analyzing_clients
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            params_job = (
                self.project_id,
                None,
                filter_id,
                threshold_config_id,
                NVFlareStatus.PROCESSING,
                None,
                None,
                self.job_id,
                non_contributing_clients_csv,
                exclude_analyzing_clients_csv,
            )
            self.cursor.execute(sql_job, params_job)
            self.nvflare_job_mysql_id = int(self.cursor.lastrowid)
            self.connection.commit()

            fn_names = list(normalized_map.keys())
            fm = FunctionsManager()
            fm.ensure_functions_exist(fn_names)
            fm.link_job_functions(self.nvflare_job_mysql_id, fn_names)
            fm.ensure_configs_and_link(self.nvflare_job_mysql_id, normalized_map)

            safe_status_update(
                self.status_writer,
                JobRunnerStatus.JOB_DEFINING,
                f"NVFlareJobsManager: Logged NVFlare job {self.nvflare_job_mysql_id} linked to functions {fn_names} with configs",
            )

            return self.nvflare_job_mysql_id

        except Exception as e:
            safe_status_update(
                self.status_writer,
                JobRunnerStatus.FAILURE,
                f"NVFlareJobsManager: Failed to create NVFlare job for job_runner_id={self.job_id} - {e}",
            )
            raise
        finally:
            if fm is not None:
                fm.complete()

    # Set nvflare job status to status arg, unless job runner has encountered a status
    # indicating analysis has full stopped (OVERRIDE_JOB_RUNNER_STATUSES).
    def set_nvflare_job_status(self, status: str) -> str:
        select_sql = f"SELECT job_runner_id FROM {MySQLTable.NVFLARE_JOBS} WHERE id=%s"
        self.cursor.execute(select_sql, (self.nvflare_job_mysql_id,))
        row = self.cursor.fetchone()

        final_status = status

        if row is not None and row["job_runner_id"]:
            log_sql = f"SELECT status FROM {MySQLTable.JOB_RUNNER_LOG} WHERE uuid=%s"
            self.cursor.execute(log_sql, (row["job_runner_id"],))
            log_row = self.cursor.fetchone()

            if log_row is not None:
                log_status = log_row["status"]
                if log_status in FAILURE_JOB_RUNNER_STATUSES:
                    final_status = log_status

        update_sql = f"UPDATE {MySQLTable.NVFLARE_JOBS} SET status=%s WHERE id=%s"
        self.cursor.execute(update_sql, (final_status, self.nvflare_job_mysql_id))
        self.connection.commit()

        return final_status

    def set_nvflare_assigned_id(self, assigned_id: str):
        sql = f"UPDATE {MySQLTable.NVFLARE_JOBS} SET nvflare_assigned_id=%s WHERE id=%s"
        self.cursor.execute(sql, (assigned_id, self.nvflare_job_mysql_id))
        self.connection.commit()

    def set_nvflare_job_path(self, job_path: str):
        sql = f"UPDATE {MySQLTable.NVFLARE_JOBS} SET job_path=%s WHERE id=%s"
        self.cursor.execute(sql, (job_path, self.nvflare_job_mysql_id))
        self.connection.commit()

    def set_nvflare_output_path(self, output_path: str):
        sql = f"UPDATE {MySQLTable.NVFLARE_JOBS} SET output_path=%s WHERE id=%s"
        self.cursor.execute(sql, (output_path, self.nvflare_job_mysql_id))
        self.connection.commit()

    def set_submission_timing(self, submit_time, run_duration: str):
        sql = f"UPDATE {MySQLTable.NVFLARE_JOBS} SET submit_time=%s, run_duration=%s WHERE id=%s"
        self.cursor.execute(sql, (submit_time, run_duration, self.nvflare_job_mysql_id))
        self.connection.commit()

    def set_participation_client_overrides(
        self,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None,
    ) -> None:
        sql = f"""
            UPDATE {MySQLTable.NVFLARE_JOBS}
            SET non_contributing_clients=%s,
                exclude_analyzing_clients=%s
            WHERE id=%s
        """
        self.cursor.execute(
            sql,
            (
                self._client_list_to_csv(non_contributing_clients),
                self._client_list_to_csv(exclude_analyzing_clients),
                self.nvflare_job_mysql_id,
            ),
        )
        self.connection.commit()

    def log_job_run_context(
        self,
        datasource_group_id: Optional[int] = None,
        workflow_group_data: Optional[Mapping[str, Any] | List[Any]] = None,
    ) -> None:
        if not self.nvflare_job_mysql_id:
            raise ValueError("NVFlare job id is not set on NVFlareJobsManager.")
        if self.project_id is None:
            raise ValueError("NVFlareJobsManager.project_id must be set to log job context.")

        self._upsert_job_datasource_log(datasource_group_id)
        self._replace_job_workflow_group_log(workflow_group_data)
        self.connection.commit()

    def _upsert_job_datasource_log(self, datasource_group_id: Optional[int]) -> None:
        sql = """
            INSERT INTO nvflare_job_datasource_log (
                nvflare_job_id,
                project_id,
                datasource_group_id
            )
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                project_id = VALUES(project_id),
                datasource_group_id = VALUES(datasource_group_id),
                update_date = CURRENT_TIMESTAMP
        """
        self.cursor.execute(
            sql,
            (self.nvflare_job_mysql_id, self.project_id, datasource_group_id),
        )

    def _replace_job_workflow_group_log(
        self,
        workflow_group_data: Optional[Mapping[str, Any] | List[Any]],
    ) -> None:
        self.cursor.execute(
            "DELETE FROM nvflare_job_workflow_groups WHERE nvflare_job_id = %s",
            (self.nvflare_job_mysql_id,),
        )

        normalized_groups = self._normalize_workflow_group_data(workflow_group_data)
        if not normalized_groups:
            return

        for group_entry in normalized_groups:
            workflow_group_id = self._resolve_workflow_group_id(group_entry)
            if workflow_group_id is None:
                continue

            self.cursor.execute(
                """
                INSERT INTO nvflare_job_workflow_groups (nvflare_job_id, workflow_group_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    update_date = CURRENT_TIMESTAMP
                """,
                (self.nvflare_job_mysql_id, workflow_group_id),
            )
            job_workflow_group_id = int(self.cursor.lastrowid or 0)
            if not job_workflow_group_id:
                self.cursor.execute(
                    """
                    SELECT id
                    FROM nvflare_job_workflow_groups
                    WHERE nvflare_job_id = %s AND workflow_group_id = %s
                    """,
                    (self.nvflare_job_mysql_id, workflow_group_id),
                )
                row = self.cursor.fetchone()
                if not row:
                    continue
                job_workflow_group_id = int(row["id"])

            option_ids = self._resolve_workflow_group_option_ids(workflow_group_id, group_entry)
            for option_id in option_ids:
                self.cursor.execute(
                    """
                    INSERT INTO nvflare_job_workflow_group_options (
                        nvflare_job_workflow_group_id,
                        workflow_group_option_id
                    )
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE
                        update_date = CURRENT_TIMESTAMP
                    """,
                    (job_workflow_group_id, option_id),
                )

    def _normalize_workflow_group_data(
        self,
        workflow_group_data: Optional[Mapping[str, Any] | List[Any]],
    ) -> List[Dict[str, Any]]:
        if workflow_group_data is None:
            return []

        normalized_groups: List[Dict[str, Any]] = []

        if isinstance(workflow_group_data, Mapping):
            for outer_group_key, entry in workflow_group_data.items():
                if isinstance(entry, Mapping):
                    group_key = entry.get("group_key") or entry.get("workflow_group_key") or outer_group_key
                    selected_options = (
                        entry.get("selected_values")
                        or entry.get("selected_options")
                        or entry.get("option_values")
                        or entry.get("option_keys")
                        or entry.get("selected_option_values")
                        or entry.get("selected_option_keys")
                        or []
                    )
                else:
                    group_key = outer_group_key
                    selected_options = entry

                normalized_groups.append({
                    "group_key": str(group_key),
                    "selected_options": self._normalize_selected_options(selected_options),
                })
            return normalized_groups

        if isinstance(workflow_group_data, list):
            for entry in workflow_group_data:
                if not isinstance(entry, Mapping):
                    continue
                group_key = entry.get("group_key") or entry.get("workflow_group_key")
                if not group_key:
                    continue
                selected_options = (
                    entry.get("selected_values")
                    or entry.get("selected_options")
                    or entry.get("option_values")
                    or entry.get("option_keys")
                    or entry.get("selected_option_values")
                    or entry.get("selected_option_keys")
                    or []
                )
                normalized_groups.append({
                    "group_key": str(group_key),
                    "selected_options": self._normalize_selected_options(selected_options),
                })
            return normalized_groups

        return []

    def _normalize_selected_options(self, selected_options: Any) -> List[str]:
        if selected_options is None:
            return []
        if isinstance(selected_options, str):
            return [selected_options]
        if isinstance(selected_options, list):
            normalized_values: List[str] = []
            for item in selected_options:
                if item is None:
                    continue
                if isinstance(item, Mapping):
                    option_value = (
                        item.get("option_value")
                        or item.get("value")
                        or item.get("option_key")
                        or item.get("key")
                    )
                    if option_value is not None:
                        normalized_values.append(str(option_value))
                    continue
                normalized_values.append(str(item))
            return normalized_values
        if isinstance(selected_options, Mapping):
            nested_values = (
                selected_options.get("selected_values")
                or selected_options.get("selected_options")
                or selected_options.get("option_values")
                or selected_options.get("option_keys")
                or selected_options.get("selected_option_values")
                or selected_options.get("selected_option_keys")
            )
            if nested_values is not None:
                return self._normalize_selected_options(nested_values)
            option_value = (
                selected_options.get("option_value")
                or selected_options.get("value")
                or selected_options.get("option_key")
                or selected_options.get("key")
            )
            return [str(option_value)] if option_value is not None else []
        return [str(selected_options)]

    def _resolve_workflow_group_id(self, group_entry: Mapping[str, Any]) -> Optional[int]:
        group_key = group_entry.get("group_key") or group_entry.get("workflow_group_key")
        if not group_key:
            return None

        self.cursor.execute(
            """
            SELECT id
            FROM defined_project_workflow_groups
            WHERE project_id = %s AND group_key = %s
            """,
            (self.project_id, str(group_key)),
        )
        row = self.cursor.fetchone()
        if row:
            return int(row["id"])

        safe_status_update(
            self.status_writer,
            JobRunnerStatus.PROCESSING,
            f"NVFlareJobsManager: Skipping unknown workflow group key '{group_key}' for project {self.project_id}",
        )
        return None

    def _extract_raw_option_refs(self, group_entry: Mapping[str, Any]) -> List[Any]:
        raw_options = group_entry.get("selected_options") or []
        if isinstance(raw_options, list):
            return raw_options
        if raw_options is None:
            return []
        return [raw_options]

    def _resolve_workflow_group_option_ids(
        self,
        workflow_group_id: int,
        group_entry: Mapping[str, Any],
    ) -> List[int]:
        option_ids: List[int] = []
        seen_option_ids = set()

        for raw_option in self._extract_raw_option_refs(group_entry):
            resolved_option_id = self._resolve_single_workflow_group_option_id(workflow_group_id, raw_option)
            if resolved_option_id is None or resolved_option_id in seen_option_ids:
                continue
            seen_option_ids.add(resolved_option_id)
            option_ids.append(resolved_option_id)

        return option_ids

    def _resolve_single_workflow_group_option_id(
        self,
        workflow_group_id: int,
        raw_option: Any,
    ) -> Optional[int]:
        candidate_str = str(raw_option)
        self.cursor.execute(
            """
            SELECT id
            FROM defined_project_workflow_group_options
            WHERE workflow_group_id = %s
              AND (
                  option_key = %s OR
                  option_value = %s
              )
            LIMIT 1
            """,
            (workflow_group_id, candidate_str, candidate_str),
        )
        row = self.cursor.fetchone()
        if row:
            return int(row["id"])

        safe_status_update(
            self.status_writer,
            JobRunnerStatus.PROCESSING,
            f"NVFlareJobsManager: Skipping unknown workflow group option '{candidate_str}' for workflow_group_id {workflow_group_id}",
        )
        return None

    def _fetch_job_datasource_log(self, job_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        if not job_ids:
            return {}

        placeholders = ",".join(["%s"] * len(job_ids))
        sql = f"""
            SELECT
                jl.nvflare_job_id,
                jl.project_id,
                jl.datasource_group_id,
                dg.group_name AS datasource_group_name,
                jl.create_date,
                jl.update_date
            FROM nvflare_job_datasource_log jl
            LEFT JOIN defined_project_datasource_groups dg
              ON dg.id = jl.datasource_group_id
            WHERE jl.nvflare_job_id IN ({placeholders})
        """
        self.cursor.execute(sql, job_ids)
        rows = self.cursor.fetchall() or []

        out: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            out[int(row["nvflare_job_id"])] = {
                "project_id": row["project_id"],
                "datasource_group_id": row["datasource_group_id"],
                "datasource_group_name": row["datasource_group_name"],
                "create_date": row["create_date"].isoformat() if row.get("create_date") else None,
                "update_date": row["update_date"].isoformat() if row.get("update_date") else None,
            }
        return out

    def _fetch_job_workflow_groups(self, job_ids: List[int]) -> tuple[Dict[int, List[Dict[str, Any]]], Dict[int, Dict[str, List[str]]]]:
        if not job_ids:
            return {}, {}

        placeholders = ",".join(["%s"] * len(job_ids))
        sql = f"""
            SELECT
                jwg.nvflare_job_id,
                jwg.id AS nvflare_job_workflow_group_id,
                wg.id AS workflow_group_id,
                wg.group_key,
                wg.group_label,
                wg.group_description,
                wg.min_selected,
                wg.max_selected,
                wg.is_required,
                wg.page_order,
                wg.status AS workflow_group_status,
                jwgo.id AS nvflare_job_workflow_group_option_log_id,
                opt.id AS workflow_group_option_id,
                opt.option_key,
                opt.option_label,
                opt.option_value,
                opt.option_order,
                opt.is_default,
                opt.status AS workflow_group_option_status
            FROM nvflare_job_workflow_groups jwg
            JOIN defined_project_workflow_groups wg
              ON wg.id = jwg.workflow_group_id
            LEFT JOIN nvflare_job_workflow_group_options jwgo
              ON jwgo.nvflare_job_workflow_group_id = jwg.id
            LEFT JOIN defined_project_workflow_group_options opt
              ON opt.id = jwgo.workflow_group_option_id
            WHERE jwg.nvflare_job_id IN ({placeholders})
            ORDER BY jwg.nvflare_job_id ASC, wg.page_order ASC, opt.option_order ASC, opt.id ASC
        """
        self.cursor.execute(sql, job_ids)
        rows = self.cursor.fetchall() or []

        workflow_groups_by_job: Dict[int, List[Dict[str, Any]]] = {}
        workflow_group_data_by_job: Dict[int, Dict[str, List[str]]] = {}
        group_cache: Dict[tuple[int, int], Dict[str, Any]] = {}

        for row in rows:
            job_id = int(row["nvflare_job_id"])
            job_groups = workflow_groups_by_job.setdefault(job_id, [])
            workflow_group_data = workflow_group_data_by_job.setdefault(job_id, {})

            cache_key = (job_id, int(row["nvflare_job_workflow_group_id"]))
            group_payload = group_cache.get(cache_key)
            if group_payload is None:
                group_payload = {
                    "nvflare_job_workflow_group_id": row["nvflare_job_workflow_group_id"],
                    "workflow_group_id": row["workflow_group_id"],
                    "group_key": row["group_key"],
                    "group_label": row["group_label"],
                    "group_description": row["group_description"],
                    "min_selected": row["min_selected"],
                    "max_selected": row["max_selected"],
                    "is_required": row["is_required"],
                    "page_order": row["page_order"],
                    "status": row["workflow_group_status"],
                    "selected_options": [],
                }
                group_cache[cache_key] = group_payload
                job_groups.append(group_payload)
                workflow_group_data[str(row["group_key"])] = []

            option_id = row.get("workflow_group_option_id")
            if option_id is None:
                continue

            option_payload = {
                "nvflare_job_workflow_group_option_log_id": row["nvflare_job_workflow_group_option_log_id"],
                "workflow_group_option_id": option_id,
                "option_key": row["option_key"],
                "option_label": row["option_label"],
                "option_value": row["option_value"],
                "option_order": row["option_order"],
                "is_default": row["is_default"],
                "status": row["workflow_group_option_status"],
            }
            group_payload["selected_options"].append(option_payload)
            workflow_group_data[str(row["group_key"])].append(str(row["option_value"]))

        return workflow_groups_by_job, workflow_group_data_by_job

    def set_workflow_for_function_config(
        self,
        function_name: str,
        config_index: int,
        workflow_id: str,
    ) -> None:
        if not self.nvflare_job_mysql_id:
            raise ValueError("NVFlare job id is not set on NVFlareJobsManager.")

        fn_name = function_name.strip().upper()
        offset = max(0, int(config_index))

        sql = f"""
            UPDATE {MySQLTable.NVFLARE_JOB_FUNCTION_CONFIGS}
            SET workflow_id = %s
            WHERE job_id = %s
              AND function_config_id = (
                  SELECT cfg_id FROM (
                      SELECT njfc.function_config_id AS cfg_id
                      FROM {MySQLTable.NVFLARE_JOB_FUNCTION_CONFIGS} njfc
                      JOIN {MySQLTable.FUNCTION_CONFIG_SETS} dfcs
                        ON dfcs.id = njfc.function_config_id
                      JOIN {MySQLTable.FUNCTIONS} df
                        ON df.id = dfcs.function_id
                      WHERE njfc.job_id = %s
                        AND df.name = %s
                      ORDER BY njfc.function_config_id ASC
                      LIMIT %s, 1
                  ) AS x
              )
        """
        params = (
            workflow_id,
            self.nvflare_job_mysql_id,
            self.nvflare_job_mysql_id,
            fn_name,
            offset,
        )
        self.cursor.execute(sql, params)
        self.connection.commit()

    def ensure_and_set_workflow_for_function_config(
        self,
        function_name: str,
        props: Mapping[str, object],
        workflow_id: str,
    ) -> int:
        if not self.nvflare_job_mysql_id:
            raise ValueError("NVFlare job id is not set on NVFlareJobsManager.")

        fm = FunctionsManager()
        try:
            cfg_set_id = fm.ensure_job_function_config_row(
                job_id=self.nvflare_job_mysql_id,
                function_name=function_name,
                props=props,
            )
        finally:
            fm.complete()

        sql = f"""
            UPDATE {MySQLTable.NVFLARE_JOB_FUNCTION_CONFIGS}
            SET workflow_id = %s
            WHERE job_id = %s AND function_config_id = %s
        """
        self.cursor.execute(sql, (workflow_id, self.nvflare_job_mysql_id, cfg_set_id))
        self.connection.commit()
        return cfg_set_id

    def get_workflow_bindings(self) -> List[tuple[str, str]]:
        """Return ``[(function_name, workflow_id), ...]`` for this job.

        These are the workflows the stager promised would carry each selected function
        config's result (see ``NVFlareJobStager._ensure_workflow_binding``) -- one terminal
        workflow per config, not the intermediate chain steps. Rows whose ``workflow_id`` is
        NULL were never bound and are skipped: there is nothing to verify for them.
        """
        if not self.nvflare_job_mysql_id:
            raise ValueError("NVFlare job id is not set on NVFlareJobsManager.")

        sql = f"""
            SELECT df.name AS function_name, njfc.workflow_id AS workflow_id
            FROM {MySQLTable.NVFLARE_JOB_FUNCTION_CONFIGS} njfc
            JOIN {MySQLTable.FUNCTION_CONFIG_SETS} dfcs
              ON dfcs.id = njfc.function_config_id
            JOIN {MySQLTable.FUNCTIONS} df
              ON df.id = dfcs.function_id
            WHERE njfc.job_id = %s AND njfc.workflow_id IS NOT NULL
        """
        self.cursor.execute(sql, (self.nvflare_job_mysql_id,))

        bindings: List[tuple[str, str]] = []
        for row in self.cursor.fetchall():
            function_name = str(row["function_name"] or "").strip()
            workflow_id = str(row["workflow_id"] or "").strip()
            if function_name and workflow_id:
                bindings.append((function_name, workflow_id))
        return bindings

    def get_nvflare_job_by_assigned_id(
        self,
        nvflare_assigned_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the metadata required to open ResultsPage directly.

        This deliberately returns the compact job-summary shape used by the
        normal Results page: job timing/status, datasource selection, party
        participation, function names, and the threshold comparison the job ran
        with. Workflow configuration and crypto-audit details are not part of Job
        Summary and remain available through their existing dedicated flows.
        """
        assigned_id = str(nvflare_assigned_id or "").strip()
        if not assigned_id:
            return None

        self.cursor.execute(
            f"""
            SELECT j.*,
                   tc.id AS threshold_id,
                   tc.method AS threshold_method,
                   tc.threshold AS threshold_value
            FROM {MySQLTable.NVFLARE_JOBS} j
            LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
              ON tc.id = j.threshold_config_id
            WHERE j.nvflare_assigned_id = %s
            ORDER BY j.id DESC
            LIMIT 1
            """,
            (assigned_id,),
        )
        row = self.cursor.fetchone()
        if not row:
            return None

        internal_job_id = int(row["id"])
        datasource_log_by_job = self._fetch_job_datasource_log([internal_job_id])

        functions_manager = FunctionsManager()
        try:
            functions_by_job = functions_manager.fetch_job_functions([internal_job_id])
        finally:
            functions_manager.complete()

        job: Dict[str, Any] = {
            "id": internal_job_id,
            "project_id": row["project_id"],
            "nvflare_assigned_id": row["nvflare_assigned_id"],
            "filter_id": row["filter_id"],
            "status": row["status"],
            "non_contributing_clients": row.get("non_contributing_clients"),
            "exclude_analyzing_clients": row.get("exclude_analyzing_clients"),
            "submit_time": row["submit_time"].isoformat() if row.get("submit_time") else None,
            "run_duration": row.get("run_duration"),
            "create_date": row["create_date"].isoformat() if row.get("create_date") else None,
            "update_date": row["update_date"].isoformat() if row.get("update_date") else None,
            "functions": sorted(functions_by_job.get(internal_job_id, set())),
        }

        if row.get("threshold_id") is not None:
            job["threshold"] = {
                "id": row.get("threshold_id"),
                "method": row.get("threshold_method"),
                "threshold": row.get("threshold_value"),
            }

        datasource_log = datasource_log_by_job.get(internal_job_id)
        if datasource_log is not None:
            job["datasource_log"] = datasource_log
            job["datasource_group_id"] = datasource_log.get("datasource_group_id")
            job["datasource_group_name"] = datasource_log.get("datasource_group_name")

        return job

    def get_nvflare_jobs(
        self,
        function_names: Optional[List[str]] = None,
        match_mode: NVFlareJobFunctionFilterMode = NVFlareJobFunctionFilterMode.ANY,
        create_date: Optional[str] = None,
        date_filter_mode: Optional[NVFlareJobCreateDateDateFilterMode] = None,
    ):
        names: List[str] = sorted(function_names)
        since: Optional[str] = create_date

        mode = date_filter_mode
        date_val = since
        if mode is None and since:
            mode = NVFlareJobCreateDateDateFilterMode.AFTER

        pid = self.project_id

        fm = None
        try:
            def append_date_clause(sql_base: str, params_list: list, alias: str = "j") -> tuple[str, list]:
                if mode and date_val:
                    if mode == NVFlareJobCreateDateDateFilterMode.ON:
                        sql_base += f" AND DATE({alias}.create_date) = DATE(%s)"
                        params_list.append(date_val)
                    elif mode == NVFlareJobCreateDateDateFilterMode.BEFORE:
                        sql_base += f" AND {alias}.create_date <= %s"
                        params_list.append(date_val)
                    elif mode == NVFlareJobCreateDateDateFilterMode.AFTER:
                        sql_base += f" AND {alias}.create_date >= %s"
                        params_list.append(date_val)
                return sql_base, params_list

            def append_project_clause(sql_base: str, params_list: list, alias: str = "j") -> tuple[str, list]:
                if pid is not None:
                    sql_base += f" AND {alias}.project_id = %s"
                    params_list.append(pid)
                return sql_base, params_list

            if names:
                placeholders = ",".join(["%s"] * len(names))
                if match_mode == NVFlareJobFunctionFilterMode.ONLY:
                    base_sql = f"""
                        SELECT j.*,
                               tc.id AS threshold_id,
                               tc.method AS threshold_method,
                               tc.threshold AS threshold_value
                        FROM {MySQLTable.NVFLARE_JOBS} j
                        LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
                          ON tc.id = j.threshold_config_id
                        JOIN (
                            SELECT job_id, COUNT(DISTINCT function_id) AS total_fn
                            FROM {MySQLTable.NVFLARE_JOB_FUNCTIONS}
                            GROUP BY job_id
                        ) t ON t.job_id = j.id
                        JOIN {MySQLTable.NVFLARE_JOB_FUNCTIONS} njf ON njf.job_id = j.id
                        JOIN {MySQLTable.FUNCTIONS} df ON df.id = njf.function_id
                        WHERE df.name IN ({placeholders})
                    """
                    params = list(names)
                    base_sql, params = append_project_clause(base_sql, params, alias="j")
                    base_sql, params = append_date_clause(base_sql, params, alias="j")
                    base_sql += """
                        GROUP BY j.id, t.total_fn
                        HAVING COUNT(DISTINCT df.name) = %s
                           AND t.total_fn = %s
                        ORDER BY j.create_date DESC
                    """
                    params += [len(names), len(names)]
                    sql = base_sql
                    print(f"NVFlareJobsManager.get_nvflare_jobs: SQL established: {sql}", flush=True)
                    self.cursor.execute(sql, params)
                else:
                    sql = f"""
                        SELECT DISTINCT j.*,
                                        tc.id AS threshold_id,
                                        tc.method AS threshold_method,
                                        tc.threshold AS threshold_value
                        FROM {MySQLTable.NVFLARE_JOBS} j
                        LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
                          ON tc.id = j.threshold_config_id
                        JOIN {MySQLTable.NVFLARE_JOB_FUNCTIONS} njf ON njf.job_id = j.id
                        JOIN {MySQLTable.FUNCTIONS} df ON df.id = njf.function_id
                        WHERE df.name IN ({placeholders})
                    """
                    params = list(names)
                    sql, params = append_project_clause(sql, params, alias="j")
                    sql, params = append_date_clause(sql, params, alias="j")
                    sql += " ORDER BY j.create_date DESC"
                    print(f"NVFlareJobsManager.get_nvflare_jobs: SQL established: {sql}", flush=True)
                    self.cursor.execute(sql, params)
            else:
                if mode and date_val:
                    sql = f"""
                        SELECT j.*,
                               tc.id AS threshold_id,
                               tc.method AS threshold_method,
                               tc.threshold AS threshold_value
                        FROM {MySQLTable.NVFLARE_JOBS} j
                        LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
                          ON tc.id = j.threshold_config_id
                        WHERE 1=1
                    """
                    params = []
                    sql, params = append_project_clause(sql, params, alias="j")
                    sql, params = append_date_clause(sql, params, alias="j")
                    sql += " ORDER BY j.create_date DESC"
                    print(f"NVFlareJobsManager.get_nvflare_jobs: SQL established: {sql}", flush=True)
                    self.cursor.execute(sql, params)
                else:
                    if pid is not None:
                        sql = f"""
                            SELECT j.*,
                                   tc.id AS threshold_id,
                                   tc.method AS threshold_method,
                                   tc.threshold AS threshold_value
                            FROM {MySQLTable.NVFLARE_JOBS} j
                            LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
                              ON tc.id = j.threshold_config_id
                            WHERE j.project_id = %s
                            ORDER BY j.create_date DESC
                        """
                        params = [pid]
                        print(f"NVFlareJobsManager.get_nvflare_jobs: SQL established: {sql}", flush=True)
                        self.cursor.execute(sql, params)
                    else:
                        sql = f"""
                            SELECT j.*,
                                   tc.id AS threshold_id,
                                   tc.method AS threshold_method,
                                   tc.threshold AS threshold_value
                            FROM {MySQLTable.NVFLARE_JOBS} j
                            LEFT JOIN {MySQLTable.THRESHOLD_CONFIGS} tc
                              ON tc.id = j.threshold_config_id
                            ORDER BY j.create_date DESC
                        """
                        print(f"NVFlareJobsManager.get_nvflare_jobs: SQL established: {sql}", flush=True)
                        self.cursor.execute(sql)

            rows = self.cursor.fetchall()
            if not rows:
                print(
                    "NVFlareJobsManager: Retrieved 0 job(s){}{}{}".format(
                        f" for functions {names}" if names else "",
                        f" with date_filter={mode.value}:{date_val}" if mode and date_val else "",
                        f" with match_mode={match_mode.value}" if names else "",
                    ),
                    flush=True,
                )
                return []

            nv_ids = [r["nvflare_assigned_id"] for r in rows if r.get("nvflare_assigned_id")]
            audit_by_nv_id = {}
            if nv_ids:
                placeholders = ",".join(["%s"] * len(nv_ids))
                audit_sql = f"""
                    SELECT
                        nvflare_job_id,
                        security_level,
                        ring_dimension,
                        batch_size,
                        scale_mod_size,
                        multiplicative_depth,
                        scaling_technique,
                        keyswitch_technique,
                        ckks_data_type,
                        ind_cpa_noise_bits,
                        created_at
                    FROM {MySQLTable.NVFLARE_JOB_CRYPTO_AUDIT}
                    WHERE nvflare_job_id IN ({placeholders})
                """
                print(f"NVFlareJobsManager.get_nvflare_jobs: audit SQL established: {audit_sql}", flush=True)
                self.cursor.execute(audit_sql, nv_ids)
                audit_rows = self.cursor.fetchall()
                for a in audit_rows:
                    audit_by_nv_id[a["nvflare_job_id"]] = {
                        "nvflare_job_id": a["nvflare_job_id"],
                        "security_level": a["security_level"],
                        "ring_dimension": a["ring_dimension"],
                        "batch_size": a["batch_size"],
                        "scale_mod_size": a["scale_mod_size"],
                        "multiplicative_depth": a["multiplicative_depth"],
                        "scaling_technique": a["scaling_technique"],
                        "keyswitch_technique": a["keyswitch_technique"],
                        "ckks_data_type": a["ckks_data_type"],
                        "ind_cpa_noise_bits": a["ind_cpa_noise_bits"],
                        "created_at": a["created_at"].isoformat() if a.get("created_at") else None,
                    }

            job_ids = [r["id"] for r in rows]

            datasource_log_by_job = self._fetch_job_datasource_log(job_ids)
            workflow_groups_by_job, workflow_group_data_by_job = self._fetch_job_workflow_groups(job_ids)

            fm = FunctionsManager()
            fn_by_job = fm.fetch_job_functions(job_ids)
            fm_by_job = fm.fetch_job_function_configs(job_ids)

            out = []
            for r in rows:
                jid = r["id"]
                tid = r.get("threshold_config_id")

                threshold_payload = None
                if r.get("threshold_id") is not None:
                    threshold_payload = {
                        "id": r["threshold_id"],
                        "method": r["threshold_method"],
                        "threshold": r["threshold_value"],
                    }

                job_dict = {
                    "id": r["id"],
                    "project_id": r["project_id"],
                    "nvflare_assigned_id": r["nvflare_assigned_id"],
                    "filter_id": r["filter_id"],
                    "threshold_config_id": tid,
                    "status": r["status"],
                    "job_path": r["job_path"],
                    "output_path": r["output_path"],
                    "job_runner_id": r["job_runner_id"],
                    "non_contributing_clients": r.get("non_contributing_clients"),
                    "exclude_analyzing_clients": r.get("exclude_analyzing_clients"),
                    "submit_time": r["submit_time"].isoformat() if r.get("submit_time") else None,
                    "run_duration": r["run_duration"],
                    "create_date": r["create_date"].isoformat() if r.get("create_date") else None,
                    "update_date": r["update_date"].isoformat() if r.get("update_date") else None,
                    "functions": sorted(fn_by_job.get(jid, set())),
                    "functions_map": fm_by_job.get(jid, {}),
                }

                if threshold_payload is not None:
                    job_dict["threshold"] = threshold_payload

                datasource_log = datasource_log_by_job.get(jid)
                if datasource_log is not None:
                    job_dict["datasource_log"] = datasource_log
                    job_dict["datasource_group_id"] = datasource_log.get("datasource_group_id")
                    job_dict["datasource_group_name"] = datasource_log.get("datasource_group_name")

                workflow_groups = workflow_groups_by_job.get(jid)
                if workflow_groups is not None:
                    job_dict["workflow_groups"] = workflow_groups
                    job_dict["workflow_group_data"] = workflow_group_data_by_job.get(jid, {})

                nv_id = r.get("nvflare_assigned_id")
                if nv_id and nv_id in audit_by_nv_id:
                    job_dict["crypto_audit_record"] = audit_by_nv_id[nv_id]

                out.append(job_dict)

            print(
                "NVFlareJobsManager: Retrieved {} job(s){}{}{}".format(
                    len(out),
                    f" for functions {names}" if names else "",
                    f" with date_filter={mode.value}:{date_val}" if mode and date_val else "",
                    f" with match_mode={match_mode.value}" if names else "",
                ),
                flush=True,
            )
            return out

        except Exception as e:
            print(
                f"NVFlareJobsManager: Failed to fetch jobs (functions={names}, date_filter={mode.value + ':' + str(date_val) if mode and date_val else 'N/A'}, match_mode={match_mode.value if names else 'N/A'}) - {e}",
                flush=True,
            )
            raise
        finally:
            if fm is not None:
                fm.complete()

