'''
Class used to tap into the users table to establish various information, and validate access.
Right now it’s mostly a helper for quick login validation and role resolution, 
but can be extended later to handle richer user/permission management.
'''

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.managers.FunctionsManager import FunctionsManager
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter, safe_status_update
from app.core.mysql.SupportedFunction import SupportedFunction
from app.core.mysql.managers.RolesManager import RolesManager
 
from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider

class UsersManager:

    def __init__(self, status_writer:JobStatusWriter=None):
        self.status_writer = status_writer
        safe_status_update(self.status_writer, JobRunnerStatus.PROCESSING, "UsersManager: Initiating manager", )

        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def validate_login(self, username: str):
        # NOT FOR PRODUCTION USE: This is just a simple lookup.
        # Given a username, fetch the associated role_id from users table.
        # Then resolve that role_id into a role name using RolesManager.
        # Returns the role name if found, otherwise None.

        query = f"""
            SELECT u.role_id
            FROM {MySQLTable.USERS} u
            WHERE u.username = %s
            LIMIT 1
        """
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()

        if not result:
            return None

        role_id = result["role_id"]

        # Lookup role name using RolesManager
        roles_manager = RolesManager()
        role_name = roles_manager.get_role_name(role_id)
        roles_manager.complete()

        return role_name

    def get_user_id_by_username(self, username: str):
        query = f"""
            SELECT u.id
            FROM {MySQLTable.USERS} u
            WHERE u.username = %s
            LIMIT 1
        """
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()

        if not result:
            return None

        return result["id"]

    def get_nvflare_client_for_user(self, user_id: int):
        """Return the single NVFlare client mapped to a user.

        nvflare_clients.client_name is the authoritative site name used by the
        standalone UI to resolve the matching local results-agent port.
        """
        query = """
            SELECT
                nc.id AS client_id,
                nc.client_name,
                nc.description
            FROM nvflare_clients nc
            WHERE nc.user_id = %s
            ORDER BY nc.id
            LIMIT 2
        """
        self.cursor.execute(query, (user_id,))
        rows = self.cursor.fetchall() or []

        if not rows:
            return None

        if len(rows) > 1:
            raise ValueError(
                f"User {user_id} is mapped to multiple NVFlare clients"
            )

        return rows[0]

    def get_user_by_client_name(self, client_name: str):
        normalized_client_name = str(client_name or "").strip()
        if not normalized_client_name:
            return None

        query = """
            SELECT
                nc.id AS client_id,
                nc.client_name,
                u.id AS user_id,
                u.username
            FROM nvflare_clients nc
            JOIN users u
                ON u.id = nc.user_id
            WHERE nc.client_name = %s
               OR LOWER(REPLACE(nc.client_name, '-', '')) = LOWER(REPLACE(%s, '-', ''))
            ORDER BY CASE WHEN nc.client_name = %s THEN 0 ELSE 1 END
            LIMIT 1
        """
        self.cursor.execute(query, (normalized_client_name, normalized_client_name, normalized_client_name))
        result = self.cursor.fetchone()

        if not result:
            return None

        return result


    def get_fhir_source(self, user_id: int, project_id: int, datasource_group: int | None = None):
        record = self.get_fhir_source_record(user_id, project_id, datasource_group)
        if not record:
            return None
        return record["source"]

    def get_fhir_source_record(self, user_id: int, project_id: int, datasource_group: int | None = None):
        if datasource_group is None:
            query = """
                SELECT
                    ufsbp.id,
                    ufsbp.source,
                    ufsbp.datasource_group,
                    ufsbp.create_date,
                    pdg.group_name AS datasource_group_name,
                    CASE
                        WHEN pdg.is_default = 1 THEN 1
                        WHEN ufsbp.datasource_group IS NULL THEN 1
                        ELSE 0
                    END AS is_default_group
                FROM users_fhir_source_by_project ufsbp
                LEFT JOIN defined_project_datasource_groups pdg
                    ON pdg.id = ufsbp.datasource_group
                WHERE ufsbp.user_id = %s
                  AND ufsbp.project_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM users_fhir_source_by_project newer
                      WHERE newer.user_id = ufsbp.user_id
                        AND newer.project_id = ufsbp.project_id
                        AND newer.datasource_group <=> ufsbp.datasource_group
                        AND (
                            newer.create_date > ufsbp.create_date
                            OR (newer.create_date = ufsbp.create_date AND newer.id > ufsbp.id)
                        )
                  )
                ORDER BY
                    CASE
                        WHEN pdg.is_default = 1 THEN 0
                        WHEN ufsbp.datasource_group IS NULL THEN 0
                        ELSE 1
                    END,
                    ufsbp.datasource_group,
                    ufsbp.create_date DESC,
                    ufsbp.id DESC
                LIMIT 1
            """
            self.cursor.execute(query, (user_id, project_id))
        else:
            query = """
                SELECT
                    ufsbp.id,
                    ufsbp.source,
                    ufsbp.datasource_group,
                    ufsbp.create_date,
                    pdg.group_name AS datasource_group_name,
                    CASE
                        WHEN pdg.is_default = 1 THEN 1
                        WHEN ufsbp.datasource_group IS NULL THEN 1
                        ELSE 0
                    END AS is_default_group
                FROM users_fhir_source_by_project ufsbp
                LEFT JOIN defined_project_datasource_groups pdg
                    ON pdg.id = ufsbp.datasource_group
                WHERE ufsbp.user_id = %s
                  AND ufsbp.project_id = %s
                  AND ufsbp.datasource_group = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM users_fhir_source_by_project newer
                      WHERE newer.user_id = ufsbp.user_id
                        AND newer.project_id = ufsbp.project_id
                        AND newer.datasource_group <=> ufsbp.datasource_group
                        AND (
                            newer.create_date > ufsbp.create_date
                            OR (newer.create_date = ufsbp.create_date AND newer.id > ufsbp.id)
                        )
                  )
                LIMIT 1
            """
            self.cursor.execute(query, (user_id, project_id, datasource_group))

        result = self.cursor.fetchone()

        if not result:
            return None

        if result["datasource_group"] is None and not result.get("datasource_group_name"):
            result["datasource_group_name"] = "DEFAULT"

        result["is_default_group"] = bool(result.get("is_default_group"))
        if result.get("create_date") is not None:
            result["create_date"] = result["create_date"].isoformat()

        return result

    def get_user_project_datasources(self, user_id: int):
        query = f"""
            SELECT
                p.id AS project_id,
                p.name AS project_name,
                ufsbp.id AS datasource_id,
                ufsbp.source,
                ufsbp.create_date,
                ufsbp.datasource_group AS datasource_group_id,
                pdg.group_name AS datasource_group_name,
                CASE
                    WHEN pdg.is_default = 1 THEN 1
                    WHEN ufsbp.datasource_group IS NULL THEN 1
                    ELSE 0
                END AS is_default_group
            FROM users_fhir_source_by_project ufsbp
            JOIN {MySQLTable.PROJECTS} p
                ON p.id = ufsbp.project_id
            LEFT JOIN defined_project_datasource_groups pdg
                ON pdg.id = ufsbp.datasource_group
            WHERE ufsbp.user_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM users_fhir_source_by_project newer
                  WHERE newer.user_id = ufsbp.user_id
                    AND newer.project_id = ufsbp.project_id
                    AND newer.datasource_group <=> ufsbp.datasource_group
                    AND (
                        newer.create_date > ufsbp.create_date
                        OR (newer.create_date = ufsbp.create_date AND newer.id > ufsbp.id)
                    )
              )
            ORDER BY
                p.name,
                CASE
                    WHEN pdg.is_default = 1 THEN 0
                    WHEN ufsbp.datasource_group IS NULL THEN 0
                    ELSE 1
                END,
                COALESCE(pdg.group_name, 'DEFAULT'),
                ufsbp.create_date DESC,
                ufsbp.id DESC
        """
        self.cursor.execute(query, (user_id,))
        rows = self.cursor.fetchall() or []

        projects_by_id = {}
        ordered_projects = []

        for row in rows:
            project_id = row["project_id"]

            if project_id not in projects_by_id:
                project_entry = {
                    "project_id": project_id,
                    "project_name": row["project_name"],
                    "datasources": [],
                }
                projects_by_id[project_id] = project_entry
                ordered_projects.append(project_entry)

            datasource_group_id = row.get("datasource_group_id")
            datasource_group_name = row.get("datasource_group_name")

            if datasource_group_id is None and not datasource_group_name:
                datasource_group_name = "DEFAULT"

            create_date = row.get("create_date")

            projects_by_id[project_id]["datasources"].append(
                {
                    "id": row["datasource_id"],
                    "source": row["source"],
                    "create_date": create_date.isoformat() if create_date is not None else None,
                    "datasource_group_id": datasource_group_id,
                    "datasource_group_name": datasource_group_name,
                    "is_default_group": bool(row.get("is_default_group")),
                }
            )

        return ordered_projects


    def get_model_file_sources(
        self,
        user_id: int,
        project_id: int,
        datasource_group: int | None,
        model_file_lookup_key: str,
        model_file_lookup_value: str,
        model_keys: list[str],
        artifact_types: list[str] | None = None,
    ):
        normalized_model_keys = []
        for model_key in model_keys or []:
            if not isinstance(model_key, str):
                continue
            value = model_key.strip()
            if value and value not in normalized_model_keys:
                normalized_model_keys.append(value)

        if not normalized_model_keys:
            return {
                "user_id": user_id,
                "project_id": project_id,
                "datasource_group": datasource_group,
                "model_file_lookup_key": model_file_lookup_key,
                "model_file_lookup_value": model_file_lookup_value,
                "models": {},
            }

        normalized_artifacts = []
        for artifact_type in artifact_types or ["weights", "cutoff"]:
            if not isinstance(artifact_type, str):
                continue
            value = artifact_type.strip().lower()
            if value in ("weights", "cutoff") and value not in normalized_artifacts:
                normalized_artifacts.append(value)

        if not normalized_artifacts:
            normalized_artifacts = ["weights", "cutoff"]

        lookup_key = str(model_file_lookup_key or "").strip()
        lookup_value = str(model_file_lookup_value or "").strip()
        if not lookup_key:
            raise ValueError("model_file_lookup_key is required")
        if not lookup_value:
            raise ValueError("model_file_lookup_value is required")

        model_key_placeholders = ",".join(["%s"] * len(normalized_model_keys))
        artifact_placeholders = ",".join(["%s"] * len(normalized_artifacts))

        query = f"""
            SELECT
                umfsbp.id,
                umfsbp.user_id,
                umfsbp.project_id,
                umfsbp.datasource_group,
                umfsbp.model_file_lookup_key,
                umfsbp.model_file_lookup_value,
                umfsbp.model_key,
                umfsbp.artifact_type,
                umfsbp.source,
                umfsbp.create_date,
                pdg.group_name AS datasource_group_name
            FROM users_model_file_source_by_project umfsbp
            LEFT JOIN defined_project_datasource_groups pdg
                ON pdg.id = umfsbp.datasource_group
            WHERE umfsbp.user_id = %s
              AND umfsbp.project_id = %s
              AND umfsbp.datasource_group <=> %s
              AND umfsbp.model_file_lookup_key = %s
              AND umfsbp.model_file_lookup_value = %s
              AND umfsbp.model_key IN ({model_key_placeholders})
              AND umfsbp.artifact_type IN ({artifact_placeholders})
            ORDER BY
                umfsbp.model_key,
                FIELD(umfsbp.artifact_type, 'weights', 'cutoff'),
                umfsbp.create_date DESC,
                umfsbp.id DESC
        """
        params = [
            user_id,
            project_id,
            datasource_group,
            lookup_key,
            lookup_value,
            *normalized_model_keys,
            *normalized_artifacts,
        ]
        self.cursor.execute(query, tuple(params))
        rows = self.cursor.fetchall() or []

        models = {}
        records = []
        seen = set()
        datasource_group_name = None

        for row in rows:
            model_key = row.get("model_key")
            artifact_type = row.get("artifact_type")
            if not model_key or not artifact_type:
                continue

            # The unique key prevents duplicates for the same lookup, but keeping the first
            # row makes this method tolerant of historical rows if the schema was manually
            # edited before the uniqueness constraint existed.
            dedupe_key = (model_key, artifact_type)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            models.setdefault(model_key, {})[artifact_type] = row.get("source")
            datasource_group_name = datasource_group_name or row.get("datasource_group_name")

            create_date = row.get("create_date")
            records.append(
                {
                    "id": row.get("id"),
                    "user_id": row.get("user_id"),
                    "project_id": row.get("project_id"),
                    "datasource_group": row.get("datasource_group"),
                    "datasource_group_name": row.get("datasource_group_name"),
                    "model_file_lookup_key": row.get("model_file_lookup_key"),
                    "model_file_lookup_value": row.get("model_file_lookup_value"),
                    "model_key": model_key,
                    "artifact_type": artifact_type,
                    "source": row.get("source"),
                    "create_date": create_date.isoformat() if create_date is not None else None,
                }
            )

        return {
            "user_id": user_id,
            "project_id": project_id,
            "datasource_group": datasource_group,
            "datasource_group_name": datasource_group_name,
            "model_file_lookup_key": lookup_key,
            "model_file_lookup_value": lookup_value,
            "model_keys": normalized_model_keys,
            "artifact_types": normalized_artifacts,
            "models": models,
            "records": records,
        }



    def get_model_file_availability(
        self,
        user_id: int,
        project_id: int,
        datasource_group: int | None,
        model_file_lookup_key: str,
        model_file_lookup_value: str,
        model_keys: list[str] | None = None,
        required_artifact_types: list[str] | None = None,
    ):
        """Return which model keys have all required model-file settings.

        This is intended for UI validation. It uses the same storage table and
        lookup dimensions as get_model_file_sources, but model_keys are optional
        and the result is shaped around option availability instead of job-stager
        file-source payload generation.
        """
        lookup_key = str(model_file_lookup_key or "").strip()
        lookup_value = str(model_file_lookup_value or "").strip()
        if not lookup_key:
            raise ValueError("model_file_lookup_key is required")
        if not lookup_value:
            raise ValueError("model_file_lookup_value is required")

        normalized_model_keys: list[str] = []
        for model_key in model_keys or []:
            if not isinstance(model_key, str):
                continue
            value = model_key.strip()
            if value and value not in normalized_model_keys:
                normalized_model_keys.append(value)

        normalized_artifacts: list[str] = []
        for artifact_type in required_artifact_types or ["weights", "cutoff"]:
            if not isinstance(artifact_type, str):
                continue
            value = artifact_type.strip().lower()
            if value in ("weights", "cutoff") and value not in normalized_artifacts:
                normalized_artifacts.append(value)

        if not normalized_artifacts:
            normalized_artifacts = ["weights", "cutoff"]

        conditions = [
            "umfsbp.user_id = %s",
            "umfsbp.project_id = %s",
            "umfsbp.datasource_group <=> %s",
            "umfsbp.model_file_lookup_key = %s",
            "umfsbp.model_file_lookup_value = %s",
        ]
        params: list[object] = [
            user_id,
            project_id,
            datasource_group,
            lookup_key,
            lookup_value,
        ]

        if normalized_model_keys:
            model_key_placeholders = ",".join(["%s"] * len(normalized_model_keys))
            conditions.append(f"umfsbp.model_key IN ({model_key_placeholders})")
            params.extend(normalized_model_keys)

        artifact_placeholders = ",".join(["%s"] * len(normalized_artifacts))
        conditions.append(f"umfsbp.artifact_type IN ({artifact_placeholders})")
        params.extend(normalized_artifacts)

        query = f"""
            SELECT
                umfsbp.id,
                umfsbp.user_id,
                umfsbp.project_id,
                umfsbp.datasource_group,
                umfsbp.model_file_lookup_key,
                umfsbp.model_file_lookup_value,
                umfsbp.model_key,
                umfsbp.artifact_type,
                umfsbp.source,
                umfsbp.create_date,
                pdg.group_name AS datasource_group_name
            FROM users_model_file_source_by_project umfsbp
            LEFT JOIN defined_project_datasource_groups pdg
                ON pdg.id = umfsbp.datasource_group
            WHERE {' AND '.join(conditions)}
            ORDER BY
                umfsbp.model_key,
                FIELD(umfsbp.artifact_type, 'weights', 'cutoff'),
                umfsbp.create_date DESC,
                umfsbp.id DESC
        """
        self.cursor.execute(query, tuple(params))
        rows = self.cursor.fetchall() or []

        records = []
        artifacts_by_model_key: dict[str, dict[str, str | None]] = {}
        datasource_group_name = None
        seen = set()

        for row in rows:
            model_key = row.get("model_key")
            artifact_type = row.get("artifact_type")
            if not model_key or not artifact_type:
                continue

            model_key_s = str(model_key)
            artifact_type_s = str(artifact_type)
            dedupe_key = (model_key_s, artifact_type_s)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            artifacts_by_model_key.setdefault(model_key_s, {})[artifact_type_s] = row.get("source")
            datasource_group_name = datasource_group_name or row.get("datasource_group_name")

            create_date = row.get("create_date")
            records.append(
                {
                    "id": row.get("id"),
                    "user_id": row.get("user_id"),
                    "project_id": row.get("project_id"),
                    "datasource_group": row.get("datasource_group"),
                    "datasource_group_id": row.get("datasource_group"),
                    "datasource_group_name": row.get("datasource_group_name"),
                    "model_file_lookup_key": row.get("model_file_lookup_key"),
                    "model_file_lookup_value": row.get("model_file_lookup_value"),
                    "model_key": model_key_s,
                    "artifact_type": artifact_type_s,
                    "source": row.get("source"),
                    "create_date": create_date.isoformat() if create_date is not None else None,
                }
            )

        model_keys_to_report = list(normalized_model_keys)
        if not model_keys_to_report:
            model_keys_to_report = sorted(artifacts_by_model_key.keys())

        availability_by_model_key = {}
        available_model_keys = []
        for model_key in model_keys_to_report:
            artifacts = artifacts_by_model_key.get(model_key, {})
            artifact_status = {
                artifact_type: bool(artifacts.get(artifact_type))
                for artifact_type in normalized_artifacts
            }
            missing_artifact_types = [
                artifact_type
                for artifact_type, present in artifact_status.items()
                if not present
            ]
            available = len(missing_artifact_types) == 0
            if available:
                available_model_keys.append(model_key)

            availability_by_model_key[model_key] = {
                "available": available,
                "artifacts": artifact_status,
                "missing_artifact_types": missing_artifact_types,
                "sources": {
                    artifact_type: artifacts.get(artifact_type)
                    for artifact_type in normalized_artifacts
                    if artifacts.get(artifact_type)
                },
            }

        return {
            "user_id": user_id,
            "project_id": project_id,
            "datasource_group": datasource_group,
            "datasource_group_id": datasource_group,
            "datasource_group_name": datasource_group_name,
            "model_file_lookup_key": lookup_key,
            "model_file_lookup_value": lookup_value,
            "required_artifact_types": normalized_artifacts,
            "requested_model_keys": normalized_model_keys,
            "available_model_keys": available_model_keys,
            "availability_by_model_key": availability_by_model_key,
            "records": records,
        }


    def get_model_file_sources_for_client(
        self,
        client_name: str,
        project_id: int,
        datasource_group: int | None,
        model_file_lookup_key: str,
        model_file_lookup_value: str,
        model_keys: list[str],
        artifact_types: list[str] | None = None,
    ):
        user_record = self.get_user_by_client_name(client_name)
        if not user_record:
            raise ValueError(f"No user is mapped to NVFlare client {client_name!r}")

        result = self.get_model_file_sources(
            user_id=user_record["user_id"],
            project_id=project_id,
            datasource_group=datasource_group,
            model_file_lookup_key=model_file_lookup_key,
            model_file_lookup_value=model_file_lookup_value,
            model_keys=model_keys,
            artifact_types=artifact_types,
        )
        result["client_id"] = user_record.get("client_id")
        result["client_name"] = user_record.get("client_name")
        result["username"] = user_record.get("username")
        return result


    def get_project_model_file_settings_enabled_map(self):
        query = """
            SELECT id, model_file_settings_enabled
            FROM defined_projects
        """
        self.cursor.execute(query)
        rows = self.cursor.fetchall() or []
        return {row["id"]: bool(row.get("model_file_settings_enabled")) for row in rows}

    def get_user_project_model_file_sources(self, user_id: int, project_id: int):
        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.USERS}
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        if not self.cursor.fetchone():
            raise ValueError("User not found")

        self.cursor.execute(
            f"""
            SELECT id, COALESCE(model_file_settings_enabled, 0) AS model_file_settings_enabled
            FROM {MySQLTable.PROJECTS}
            WHERE id = %s
            LIMIT 1
            """,
            (project_id,),
        )
        project_row = self.cursor.fetchone()
        if not project_row:
            raise ValueError("Project not found")

        model_file_settings_enabled = bool(project_row.get("model_file_settings_enabled"))

        self.cursor.execute(
            """
            SELECT
                umfsbp.id,
                umfsbp.user_id,
                umfsbp.project_id,
                umfsbp.datasource_group,
                pdg.group_name AS datasource_group_name,
                CASE
                    WHEN pdg.is_default = 1 THEN 1
                    WHEN umfsbp.datasource_group IS NULL THEN 1
                    ELSE 0
                END AS is_default_group,
                umfsbp.model_file_lookup_key,
                umfsbp.model_file_lookup_value,
                umfsbp.model_key,
                umfsbp.artifact_type,
                umfsbp.source,
                umfsbp.create_date,
                umfsbp.update_date
            FROM users_model_file_source_by_project umfsbp
            LEFT JOIN defined_project_datasource_groups pdg
                ON pdg.id = umfsbp.datasource_group
            WHERE umfsbp.user_id = %s
              AND umfsbp.project_id = %s
            ORDER BY
                CASE
                    WHEN pdg.is_default = 1 THEN 0
                    WHEN umfsbp.datasource_group IS NULL THEN 0
                    ELSE 1
                END,
                COALESCE(pdg.group_name, 'DEFAULT'),
                umfsbp.model_file_lookup_value,
                umfsbp.model_key,
                FIELD(umfsbp.artifact_type, 'weights', 'cutoff'),
                umfsbp.id
            """,
            (user_id, project_id),
        )
        rows = self.cursor.fetchall() or []

        records = []
        for row in rows:
            datasource_group_name = row.get("datasource_group_name")
            if row.get("datasource_group") is None and not datasource_group_name:
                datasource_group_name = "DEFAULT"

            create_date = row.get("create_date")
            update_date = row.get("update_date")
            records.append(
                {
                    "id": row.get("id"),
                    "user_id": row.get("user_id"),
                    "project_id": row.get("project_id"),
                    "datasource_group": row.get("datasource_group"),
                    "datasource_group_id": row.get("datasource_group"),
                    "datasource_group_name": datasource_group_name,
                    "is_default_group": bool(row.get("is_default_group")),
                    "model_file_lookup_key": row.get("model_file_lookup_key"),
                    "model_file_lookup_value": row.get("model_file_lookup_value"),
                    "model_key": row.get("model_key"),
                    "artifact_type": row.get("artifact_type"),
                    "source": row.get("source"),
                    "create_date": create_date.isoformat() if create_date is not None else None,
                    "update_date": update_date.isoformat() if update_date is not None else None,
                }
            )

        return {
            "user_id": user_id,
            "project_id": project_id,
            "model_file_settings_enabled": model_file_settings_enabled,
            "records": records,
        }

    def upsert_user_project_model_file_source(
        self,
        user_id: int,
        project_id: int,
        datasource_group: int | None,
        model_file_lookup_key: str,
        model_file_lookup_value: str,
        model_key: str,
        artifact_type: str,
        source: str,
    ):
        lookup_key = str(model_file_lookup_key or "").strip()
        lookup_value = str(model_file_lookup_value or "").strip()
        normalized_model_key = str(model_key or "").strip()
        normalized_artifact_type = str(artifact_type or "").strip().lower()
        normalized_source = str(source or "").strip()

        if not lookup_key:
            raise ValueError("model_file_lookup_key is required")
        if not lookup_value:
            raise ValueError("model_file_lookup_value is required")
        if not normalized_model_key:
            raise ValueError("model_key is required")
        if normalized_artifact_type not in ("weights", "cutoff"):
            raise ValueError("artifact_type must be weights or cutoff")
        if not normalized_source:
            raise ValueError("Model file source is required")

        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.USERS}
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        if not self.cursor.fetchone():
            raise ValueError("User not found")

        self.cursor.execute(
            f"""
            SELECT id, COALESCE(model_file_settings_enabled, 0) AS model_file_settings_enabled
            FROM {MySQLTable.PROJECTS}
            WHERE id = %s
            LIMIT 1
            """,
            (project_id,),
        )
        project_row = self.cursor.fetchone()
        if not project_row:
            raise ValueError("Project not found")
        if not bool(project_row.get("model_file_settings_enabled")):
            raise ValueError("Project does not support model file settings")

        if datasource_group is not None:
            self.cursor.execute(
                """
                SELECT id
                FROM defined_project_datasource_groups
                WHERE id = %s
                  AND project_id = %s
                LIMIT 1
                """,
                (datasource_group, project_id),
            )
            if not self.cursor.fetchone():
                raise ValueError("Datasource group not found for project")

        self.cursor.execute(
            """
            INSERT INTO users_model_file_source_by_project
                (user_id, project_id, datasource_group, model_file_lookup_key, model_file_lookup_value, model_key, artifact_type, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                source = VALUES(source),
                update_date = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                project_id,
                datasource_group,
                lookup_key,
                lookup_value,
                normalized_model_key,
                normalized_artifact_type,
                normalized_source,
            ),
        )

        return self.get_model_file_sources(
            user_id=user_id,
            project_id=project_id,
            datasource_group=datasource_group,
            model_file_lookup_key=lookup_key,
            model_file_lookup_value=lookup_value,
            model_keys=[normalized_model_key],
            artifact_types=[normalized_artifact_type],
        )

    def create_user_project_datasource(self, user_id: int, project_id: int, source: str, datasource_group: int | None = None):
        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.USERS}
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        if not self.cursor.fetchone():
            raise ValueError("User not found")

        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.PROJECTS}
            WHERE id = %s
            LIMIT 1
            """,
            (project_id,),
        )
        if not self.cursor.fetchone():
            raise ValueError("Project not found")

        if datasource_group is not None:
            self.cursor.execute(
                """
                SELECT id
                FROM defined_project_datasource_groups
                WHERE id = %s
                  AND project_id = %s
                LIMIT 1
                """,
                (datasource_group, project_id),
            )
            if not self.cursor.fetchone():
                raise ValueError("Datasource group not found for project")

        self.cursor.execute(
            """
            INSERT INTO users_fhir_source_by_project (user_id, project_id, source, datasource_group)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, project_id, source, datasource_group),
        )

        return self.get_fhir_source_record(user_id, project_id, datasource_group)
