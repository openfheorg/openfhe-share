"""Optimized read models for the SHARE Home and project landing pages.

These queries are intentionally purpose-built for the landing-page UI.  They avoid
loading complete job histories or the heavier project/job objects used by the
workflow screens when the landing page only needs summary statistics and the five
most recent jobs.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Optional

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.UserRole import UserRole


class LandingPageManager:
    """Read-only aggregate queries for the SHARE landing pages."""

    RECENT_JOB_LIMIT = 5

    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    @staticmethod
    def _iso(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _safe_json_object(value: Any) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, (list, tuple)):
            return None
        try:
            text = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
            text = text.strip()
            if not text or text == "null":
                return None
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def get_home_summary(self, username: str) -> Optional[dict[str, Any]]:
        """Return the role-appropriate data model for the global SHARE Home page.

        Home is intentionally scoped by the requesting user's role.  Initiators,
        observers, and administrators receive the system-level distributions used
        by the full Home dashboard.  Clients receive only the non-sensitive
        aggregate information they need: total jobs and supported functions.

        ``None`` is returned when the username does not resolve to a SHARE user.
        """
        normalized_username = str(username or "").strip()
        if not normalized_username:
            return None

        self.cursor.execute(
            """
            SELECT r.name AS role
            FROM users u
            JOIN defined_roles r
                ON r.id = u.role_id
            WHERE u.username = %s
            LIMIT 1
            """,
            (normalized_username,),
        )
        user_row = self.cursor.fetchone()
        if not user_row or not user_row.get("role"):
            return None

        role = str(user_row["role"]).strip().upper()
        is_client = role == UserRole.CLIENT.value

        job_statuses: list[dict[str, Any]] = []
        if is_client:
            # Clients may see the overall amount of SHARE activity, but not the
            # system-wide status distribution.  Use the cheapest possible query.
            self.cursor.execute(
                """
                SELECT COUNT(*) AS total_jobs
                FROM nvflare_jobs
                """
            )
            total_job_row = self.cursor.fetchone() or {}
            total_jobs = int(total_job_row.get("total_jobs") or 0)
        else:
            self.cursor.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(status), ''), 'UNKNOWN') AS status,
                    COUNT(*) AS job_count
                FROM nvflare_jobs
                GROUP BY COALESCE(NULLIF(TRIM(status), ''), 'UNKNOWN')
                ORDER BY job_count DESC, status ASC
                """
            )
            status_rows = self.cursor.fetchall() or []
            job_statuses = [
                {
                    "status": str(row.get("status") or "UNKNOWN"),
                    "count": int(row.get("job_count") or 0),
                }
                for row in status_rows
            ]
            total_jobs = sum(entry["count"] for entry in job_statuses)

        user_roles: list[dict[str, Any]] = []
        total_users: Optional[int] = None
        if not is_client:
            self.cursor.execute(
                """
                SELECT
                    r.id AS role_id,
                    r.name AS role,
                    r.description,
                    COUNT(u.id) AS user_count
                FROM defined_roles r
                LEFT JOIN users u
                    ON u.role_id = r.id
                GROUP BY r.id, r.name, r.description
                ORDER BY user_count DESC, r.name ASC
                """
            )
            role_rows = self.cursor.fetchall() or []
            user_roles = [
                {
                    "role_id": int(row["role_id"]),
                    "role": str(row.get("role") or "UNKNOWN"),
                    "description": row.get("description"),
                    "count": int(row.get("user_count") or 0),
                }
                for row in role_rows
                if row.get("role_id") is not None
            ]
            total_users = sum(entry["count"] for entry in user_roles)

        self.cursor.execute(
            """
            SELECT
                id,
                name,
                description
            FROM defined_functions
            ORDER BY name ASC
            """
        )
        function_rows = self.cursor.fetchall() or []
        functions = [
            {
                "id": int(row["id"]),
                "name": str(row.get("name") or ""),
                "description": row.get("description"),
            }
            for row in function_rows
            if row.get("id") is not None and row.get("name")
        ]

        response: dict[str, Any] = {
            "total_jobs": total_jobs,
            "total_functions": len(functions),
            "functions": functions,
        }

        if not is_client:
            response.update(
                {
                    "total_users": total_users or 0,
                    "job_statuses": job_statuses,
                    "user_roles": user_roles,
                }
            )

        return response

    def get_project_landing_summary(self, project_id: int) -> Optional[dict[str, Any]]:
        """Return the data required to render one project's landing panel.

        This deliberately does *not* call ``NVFlareJobsManager.get_nvflare_jobs``:
        that method builds the complete Job History record set (crypto audit,
        workflow groups, etc.).  The landing page only needs the overall count and
        five recent rows, so we fetch exactly those fields here.
        """
        self.cursor.execute(
            """
            SELECT
                p.id,
                p.name,
                p.description,
                p.status,
                p.fixed,
                p.function_restrictions_enabled,
                p.model_file_settings_enabled,
                p.filter_system_id,
                dfs.name AS filter_system,
                (
                    SELECT COUNT(*)
                    FROM nvflare_jobs j
                    WHERE j.project_id = p.id
                ) AS total_jobs,
                (
                    SELECT COUNT(DISTINCT ufsbp.user_id)
                    FROM users_fhir_source_by_project ufsbp
                    WHERE ufsbp.project_id = p.id
                ) AS registered_user_count
            FROM defined_projects p
            LEFT JOIN defined_filter_system dfs
                ON dfs.id = p.filter_system_id
            WHERE p.id = %s
            LIMIT 1
            """,
            (project_id,),
        )
        project_row = self.cursor.fetchone()
        if not project_row:
            return None

        restrictions_enabled = bool(project_row.get("function_restrictions_enabled"))
        functions = self._get_project_functions(project_id, restrictions_enabled)
        datasource_groups = self._get_project_datasource_groups(project_id)
        recent_jobs = self._get_recent_jobs(project_id, self.RECENT_JOB_LIMIT)
        function_usage_distribution = self._get_function_usage_distribution(project_id)

        project = {
            "id": int(project_row["id"]),
            "name": str(project_row.get("name") or ""),
            "description": project_row.get("description"),
            "status": project_row.get("status"),
            "fixed": bool(project_row.get("fixed")),
            "function_restrictions_enabled": restrictions_enabled,
            "model_file_settings_enabled": bool(project_row.get("model_file_settings_enabled")),
            "filter_system_id": project_row.get("filter_system_id"),
            "filter_system": project_row.get("filter_system"),
            "registered_user_count": int(project_row.get("registered_user_count") or 0),
            "total_jobs": int(project_row.get("total_jobs") or 0),
            "function_count": len(functions),
            "datasource_groups_defined": len(datasource_groups) > 0,
            "datasource_groups": datasource_groups,
            "default_datasource_group": next(
                (group for group in datasource_groups if group.get("is_default")),
                None,
            ),
            "functions": functions,
        }

        return {
            "project": project,
            "recent_jobs": recent_jobs,
            "function_usage_distribution": function_usage_distribution,
        }

    def _get_function_usage_distribution(self, project_id: int) -> list[dict[str, Any]]:
        """Count jobs by the exact set of computation functions they used.

        Every NVFlare job is linked to its selected functions through
        ``nvflare_job_functions`` when the job is created.  Treat each job as one
        observation: a MEAN-only job increments the MEAN bucket, while a job that
        ran MEAN and CHI_SQUARE_TEST increments the MEAN+CHI_SQUARE_TEST bucket.
        """
        self.cursor.execute(
            """
            SELECT
                j.id AS job_id,
                df.name AS function_name
            FROM nvflare_jobs j
            JOIN nvflare_job_functions njf
                ON njf.job_id = j.id
            JOIN defined_functions df
                ON df.id = njf.function_id
            WHERE j.project_id = %s
            ORDER BY j.id ASC, df.name ASC
            """,
            (project_id,),
        )

        functions_by_job: dict[int, set[str]] = {}
        for row in self.cursor.fetchall() or []:
            job_id = row.get("job_id")
            function_name = row.get("function_name")
            if job_id is None or not function_name:
                continue
            functions_by_job.setdefault(int(job_id), set()).add(str(function_name))

        combination_counts: Counter[tuple[str, ...]] = Counter(
            tuple(sorted(function_names))
            for function_names in functions_by_job.values()
            if function_names
        )

        return [
            {
                "functions": list(function_names),
                "count": count,
            }
            for function_names, count in sorted(
                combination_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    def _get_project_functions(
        self,
        project_id: int,
        restrictions_enabled: bool,
    ) -> list[dict[str, Any]]:
        if restrictions_enabled:
            self.cursor.execute(
                """
                SELECT
                    df.id AS function_id,
                    df.name AS function_name,
                    df.description,
                    dpfr.configurable,
                    dpfr.custom_configuration_fixed,
                    dpfr.custom_configuration_variable,
                    dpfr.override_configuration
                FROM defined_project_function_restrictions dpfr
                JOIN defined_functions df
                    ON df.id = dpfr.function_id
                WHERE dpfr.project_id = %s
                  AND dpfr.enabled = 'ENABLED'
                ORDER BY df.name ASC
                """,
                (project_id,),
            )
            rows = self.cursor.fetchall() or []
            return [
                {
                    "function_id": int(row["function_id"]),
                    "function": str(row.get("function_name") or ""),
                    "description": row.get("description"),
                    "configurable": bool(row.get("configurable")),
                    "custom_configuration_fixed": self._safe_json_object(row.get("custom_configuration_fixed")),
                    "custom_configuration_variable": self._safe_json_object(row.get("custom_configuration_variable")),
                    "override_configuration": self._safe_json_object(row.get("override_configuration")),
                }
                for row in rows
                if row.get("function_id") is not None and row.get("function_name")
            ]

        self.cursor.execute(
            """
            SELECT
                id AS function_id,
                name AS function_name,
                description
            FROM defined_functions
            ORDER BY name ASC
            """
        )
        rows = self.cursor.fetchall() or []
        return [
            {
                "function_id": int(row["function_id"]),
                "function": str(row.get("function_name") or ""),
                "description": row.get("description"),
                "configurable": True,
                "custom_configuration_fixed": None,
                "custom_configuration_variable": None,
                "override_configuration": None,
            }
            for row in rows
            if row.get("function_id") is not None and row.get("function_name")
        ]

    def _get_project_datasource_groups(self, project_id: int) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT
                id,
                project_id,
                group_name,
                is_default
            FROM defined_project_datasource_groups
            WHERE project_id = %s
            ORDER BY is_default DESC, group_name ASC, id ASC
            """,
            (project_id,),
        )
        rows = self.cursor.fetchall() or []
        return [
            {
                "id": int(row["id"]),
                "project_id": int(row["project_id"]),
                "group_name": str(row.get("group_name") or ""),
                "is_default": bool(row.get("is_default")),
            }
            for row in rows
            if row.get("id") is not None and row.get("group_name")
        ]

    def _get_recent_jobs(self, project_id: int, limit: int) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 25))
        self.cursor.execute(
            f"""
            SELECT
                j.id,
                j.project_id,
                j.nvflare_assigned_id,
                j.filter_id,
                j.status,
                j.job_runner_id,
                j.submit_time,
                j.run_duration,
                j.create_date,
                j.update_date,
                j.non_contributing_clients,
                j.exclude_analyzing_clients,
                nvjdl.datasource_group_id,
                pdg.group_name AS datasource_group_name,
                nvjdl.create_date AS datasource_log_create_date,
                nvjdl.update_date AS datasource_log_update_date
            FROM nvflare_jobs j
            LEFT JOIN nvflare_job_datasource_log nvjdl
                ON nvjdl.nvflare_job_id = j.id
            LEFT JOIN defined_project_datasource_groups pdg
                ON pdg.id = nvjdl.datasource_group_id
            WHERE j.project_id = %s
            ORDER BY j.create_date DESC, j.id DESC
            LIMIT {safe_limit}
            """,
            (project_id,),
        )
        rows = self.cursor.fetchall() or []
        if not rows:
            return []

        job_ids = [int(row["id"]) for row in rows]
        functions_by_job = self._get_recent_job_functions(job_ids)
        function_configs_by_job = self._get_recent_job_function_configs(job_ids)

        out: list[dict[str, Any]] = []
        for row in rows:
            job_id = int(row["id"])
            datasource_group_id = row.get("datasource_group_id")
            datasource_log = None
            if datasource_group_id is not None or row.get("datasource_group_name") is not None:
                datasource_log = {
                    "project_id": int(row["project_id"]),
                    "datasource_group_id": int(datasource_group_id) if datasource_group_id is not None else None,
                    "datasource_group_name": row.get("datasource_group_name"),
                    "create_date": self._iso(row.get("datasource_log_create_date")),
                    "update_date": self._iso(row.get("datasource_log_update_date")),
                }

            job = {
                "id": job_id,
                "project_id": int(row["project_id"]),
                "nvflare_assigned_id": row.get("nvflare_assigned_id"),
                "filter_id": row.get("filter_id"),
                "status": row.get("status"),
                "job_runner_id": row.get("job_runner_id"),
                "non_contributing_clients": row.get("non_contributing_clients"),
                "exclude_analyzing_clients": row.get("exclude_analyzing_clients"),
                "submit_time": self._iso(row.get("submit_time")),
                "run_duration": row.get("run_duration"),
                "create_date": self._iso(row.get("create_date")),
                "update_date": self._iso(row.get("update_date")),
                "functions": sorted(functions_by_job.get(job_id, set())),
                "functions_map": function_configs_by_job.get(job_id, {}),
            }

            if datasource_log is not None:
                job["datasource_group_id"] = datasource_log.get("datasource_group_id")
                job["datasource_group_name"] = datasource_log.get("datasource_group_name")
                job["datasource_log"] = datasource_log

            out.append(job)

        return out

    def _get_recent_job_functions(self, job_ids: list[int]) -> dict[int, set[str]]:
        if not job_ids:
            return {}
        placeholders = ",".join(["%s"] * len(job_ids))
        self.cursor.execute(
            f"""
            SELECT
                njf.job_id,
                df.name AS function_name
            FROM nvflare_job_functions njf
            JOIN defined_functions df
                ON df.id = njf.function_id
            WHERE njf.job_id IN ({placeholders})
            """,
            job_ids,
        )
        result: dict[int, set[str]] = {job_id: set() for job_id in job_ids}
        for row in self.cursor.fetchall() or []:
            job_id = row.get("job_id")
            function_name = row.get("function_name")
            if job_id is None or not function_name:
                continue
            result.setdefault(int(job_id), set()).add(str(function_name))
        return result

    def _get_recent_job_function_configs(
        self,
        job_ids: list[int],
    ) -> dict[int, dict[str, list[dict[str, str]]]]:
        if not job_ids:
            return {}
        placeholders = ",".join(["%s"] * len(job_ids))
        self.cursor.execute(
            f"""
            SELECT
                njfc.job_id,
                df.name AS function_name,
                dfcs.id AS config_set_id,
                dfcp.property_name,
                dfcp.property_value
            FROM nvflare_job_function_configs njfc
            JOIN defined_function_config_sets dfcs
                ON dfcs.id = njfc.function_config_id
            JOIN defined_functions df
                ON df.id = dfcs.function_id
            LEFT JOIN defined_function_config_set_members dfcsm
                ON dfcsm.config_set_id = dfcs.id
            LEFT JOIN defined_function_config_properties dfcp
                ON dfcp.id = dfcsm.config_id
            WHERE njfc.job_id IN ({placeholders})
            ORDER BY njfc.job_id, df.name, dfcs.id, dfcp.property_name
            """,
            job_ids,
        )

        grouped: dict[int, dict[str, dict[int, dict[str, str]]]] = {
            job_id: {} for job_id in job_ids
        }
        for row in self.cursor.fetchall() or []:
            job_id = int(row["job_id"])
            function_name = str(row["function_name"])
            config_set_id = int(row["config_set_id"])
            config = grouped.setdefault(job_id, {}).setdefault(function_name, {}).setdefault(config_set_id, {})
            property_name = row.get("property_name")
            if property_name is not None:
                config[str(property_name)] = "" if row.get("property_value") is None else str(row.get("property_value"))

        out: dict[int, dict[str, list[dict[str, str]]]] = {}
        for job_id, function_map in grouped.items():
            out[job_id] = {
                function_name: list(config_sets.values())
                for function_name, config_sets in function_map.items()
            }
        return out
