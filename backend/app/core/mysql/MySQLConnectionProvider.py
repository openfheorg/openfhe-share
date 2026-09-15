'''
Class used to establish and maintain a pooled connection system for MySQL.
It ensures the database exists, auto-creates required tables/schemas if missing,
and guarantees some default functions, roles, and test users exist.
This is the central entry point for any code that needs a DB connection.
'''

import threading
import json
import os
import re
from pathlib import Path
import pymysql

from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.aws.SecretsManager import MySQLSecret
from app.core.aws.ResourceConfigProvider import ResourceConfigProvider
from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.SupportedFilterSystem import SupportedFilterSystem
from app.core.mysql.SupportedFunction import MODEL_TYPE_ENCRYPTED, MODEL_TYPE_OPEN_ACCESS, SupportedFunction
from app.core.mysql.UserRole import UserRole

pymysql.install_as_MySQLdb()
import MySQLdb
from MySQLdb import OperationalError
from MySQLdb.constants import CLIENT
from dbutils.pooled_db import PooledDB

connection_pool_lock = threading.Lock()

class MySQLConnectionProvider:
    '''
    Lifecycle:
      1. Reads config from AWS Secrets Manager (via AWSResourceConfigProvider).
      2. Ensures the target database exists (creates it if missing).
      3. Builds a dbutils.PooledDB pool for efficient parallel access.
      4. Runs CREATE TABLE IF NOT EXISTS and ALTERs to enforce schema.
      5. Seeds required functions, roles, and test users.
    Provides get_connection() for pooled access and rebuild_pool() if the pool dies.
    '''
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        mysql_config: MySQLSecret = ResourceConfigProvider.get_mysql_config(check_cached=False)
        if mysql_config is None:
            print("MySQLConnectionProvider: [ERROR] mysql_config returned None. Can't perform MySQL secret lookup!", flush=True)

        self.host_string = mysql_config.host
        self.user_string = mysql_config.username
        self.password_string = mysql_config.password
        self.db_string = mysql_config.dbname
        self.port = mysql_config.port

        self._ensure_database_created()

        self.pool = PooledDB(
            creator=MySQLdb,
            maxconnections=150,
            mincached=15,
            maxcached=45,
            blocking=True,
            host=self.host_string,
            user=self.user_string,
            passwd=self.password_string,
            db=self.db_string,
            port=self.port,
            autocommit=True,
            client_flag=CLIENT.MULTI_STATEMENTS,
            cursorclass=MySQLdb.cursors.DictCursor,
            ping=1
        )

        self._ensure_tables_and_alters()
        self._ensure_project_model_file_settings_schema()
        self._ensure_project_workflow_group_validation_schema()
        self._ensure_users_fhir_source_by_project_schema()
        self._ensure_participation_lookup_indexes()
        self._ensure_landing_page_indexes()
        self._migrate_legacy_function_names()
        self._ensure_default_functions_exist()
        self._ensure_default_roles_exist()
        self._ensure_default_filter_systems_exist()
        self._ensure_default_projects_exist()
        self._ensure_test_users_exist()

        env = EnvironmentProvider.get_env()
        if env in (Environment.LOCAL, Environment.DEV):
            self._ensure_default_nvflare_clients()

        self._ensure_default_defined_project_datasource_groups()
        self._ensure_default_project_workflow_groups()
        self._ensure_default_user_fhir_sources()
        self._ensure_default_user_model_file_sources()

    def _ensure_database_created(self):
        try:
            connection = MySQLdb.connect(
                host=self.host_string,
                user=self.user_string,
                passwd=self.password_string,
                port=self.port
            )
        except Exception as e:
            print(f"MySQLConnectionProvider: [WARN] raw connect failed [{e}]. Forcing secret refresh.", flush=True)
            cfg: MySQLSecret = ResourceConfigProvider.get_mysql_config(check_cached=False)
            self.host_string = cfg.host
            self.user_string = cfg.username
            self.password_string = cfg.password
            self.db_string = cfg.dbname
            self.port = cfg.port
            connection = MySQLdb.connect(
                host=self.host_string,
                user=self.user_string,
                passwd=self.password_string,
                port=self.port
            )

        try:
            cursor = connection.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_string};")
        finally:
            cursor.close()
            connection.close()

    def _ensure_tables_and_alters(self):
        connection = self.get_connection()
        try:
            self.create_tables_if_not_exists(connection)
        finally:
            connection.close()

    def _ensure_project_model_file_settings_schema(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'defined_projects'
                  AND COLUMN_NAME = 'model_file_settings_enabled'
                """,
                (self.db_string,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    ALTER TABLE defined_projects
                    ADD COLUMN model_file_settings_enabled TINYINT(1) NOT NULL DEFAULT 0
                    AFTER function_restrictions_enabled
                    """
                )
            connection.commit()
        finally:
            cursor.close()
            connection.close()



    def _ensure_project_workflow_group_validation_schema(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'defined_project_workflow_groups'
                  AND COLUMN_NAME = 'validation_config'
                """,
                (self.db_string,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    ALTER TABLE defined_project_workflow_groups
                    ADD COLUMN validation_config JSON NULL
                    AFTER status
                    """
                )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def get_connection(self):
        with connection_pool_lock:
            try:
                return self.pool.connection()
            except Exception as e:
                print(f"MySQLConnectionProvider: Unexpected DB connection error {e}, rebuilding pool.", flush=True)
                self.rebuild_pool()
                return self.pool.connection()

    def _ensure_users_fhir_source_by_project_schema(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users_fhir_source_by_project'
                """,
                (self.db_string,),
            )
            existing_columns = {row["COLUMN_NAME"] for row in (cursor.fetchall() or [])}

            cursor.execute(
                """
                SELECT INDEX_NAME
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users_fhir_source_by_project'
                """,
                (self.db_string,),
            )
            existing_indexes = {row["INDEX_NAME"] for row in (cursor.fetchall() or [])}

            cursor.execute(
                """
                SELECT CONSTRAINT_NAME
                FROM information_schema.TABLE_CONSTRAINTS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'users_fhir_source_by_project'
                  AND CONSTRAINT_TYPE = 'PRIMARY KEY'
                """,
                (self.db_string,),
            )
            has_primary_key = cursor.fetchone() is not None

            cursor.execute(
                """
                SELECT CONSTRAINT_NAME
                FROM information_schema.REFERENTIAL_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA = %s
                  AND TABLE_NAME = 'users_fhir_source_by_project'
                  AND CONSTRAINT_NAME = 'fk_ufsbp_datasource_group'
                """,
                (self.db_string,),
            )
            has_datasource_group_fk = cursor.fetchone() is not None

            if 'id' not in existing_columns:
                if has_primary_key:
                    cursor.execute(
                        """
                        ALTER TABLE users_fhir_source_by_project
                        DROP PRIMARY KEY,
                        ADD COLUMN id INT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST
                        """
                    )
                else:
                    cursor.execute(
                        """
                        ALTER TABLE users_fhir_source_by_project
                        ADD COLUMN id INT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST
                        """
                    )
                existing_columns.add('id')
                existing_indexes.add('PRIMARY')

            if 'datasource_group' not in existing_columns:
                cursor.execute(
                    """
                    ALTER TABLE users_fhir_source_by_project
                    ADD COLUMN datasource_group INT NULL AFTER source
                    """
                )
                existing_columns.add('datasource_group')

            if 'uq_ufsbp_user_project_group' not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE users_fhir_source_by_project
                    ADD UNIQUE KEY uq_ufsbp_user_project_group (user_id, project_id, datasource_group)
                    """
                )
                existing_indexes.add('uq_ufsbp_user_project_group')

            if 'idx_ufsbp_user' not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE users_fhir_source_by_project
                    ADD INDEX idx_ufsbp_user (user_id)
                    """
                )
                existing_indexes.add('idx_ufsbp_user')

            if 'idx_ufsbp_datasource_group' not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE users_fhir_source_by_project
                    ADD INDEX idx_ufsbp_datasource_group (datasource_group)
                    """
                )
                existing_indexes.add('idx_ufsbp_datasource_group')

            if not has_datasource_group_fk:
                cursor.execute(
                    """
                    ALTER TABLE users_fhir_source_by_project
                    ADD CONSTRAINT fk_ufsbp_datasource_group FOREIGN KEY (datasource_group)
                    REFERENCES defined_project_datasource_groups(id) ON DELETE SET NULL
                    """
                )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_participation_lookup_indexes(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT TABLE_NAME, INDEX_NAME
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME IN (
                      'nvflare_client_participation',
                      'defined_function_config_properties'
                  )
                """,
                (self.db_string,),
            )
            existing_indexes = {
                (row["TABLE_NAME"], row["INDEX_NAME"])
                for row in (cursor.fetchall() or [])
            }

            if ('nvflare_client_participation', 'idx_ncp_filter_confirmation_threshold') not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE nvflare_client_participation
                    ADD INDEX idx_ncp_filter_confirmation_threshold
                        (filter_id, confirmation, threshold_config_id, id, client_id)
                    """
                )

            if ('defined_function_config_properties', 'idx_dfcp_name_value') not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE defined_function_config_properties
                    ADD INDEX idx_dfcp_name_value
                        (property_name, property_value, id, function_id)
                    """
                )

            connection.commit()
        finally:
            cursor.close()
            connection.close()


    def _ensure_landing_page_indexes(self):
        """Ensure indexes used by the Home/project landing summary queries exist."""
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT TABLE_NAME, INDEX_NAME
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME IN (
                      'nvflare_jobs',
                      'users_fhir_source_by_project'
                  )
                """,
                (self.db_string,),
            )
            existing_indexes = {
                (row["TABLE_NAME"], row["INDEX_NAME"])
                for row in (cursor.fetchall() or [])
            }

            if ('nvflare_jobs', 'idx_nvjobs_project_create') not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE nvflare_jobs
                    ADD INDEX idx_nvjobs_project_create
                        (project_id, create_date, id)
                    """
                )

            if ('users_fhir_source_by_project', 'idx_ufsbp_project_user') not in existing_indexes:
                cursor.execute(
                    """
                    ALTER TABLE users_fhir_source_by_project
                    ADD INDEX idx_ufsbp_project_user
                        (project_id, user_id)
                    """
                )

            connection.commit()
        finally:
            cursor.close()
            connection.close()


    def rebuild_pool(self):
        mysql_config: MySQLSecret = ResourceConfigProvider.get_mysql_config(check_cached=False)
        self.host_string = mysql_config.host
        self.user_string = mysql_config.username
        self.password_string = mysql_config.password
        self.db_string = mysql_config.dbname
        self.port = mysql_config.port

        self.pool = PooledDB(
            creator=MySQLdb,
            maxconnections=150,
            mincached=15,
            maxcached=45,
            blocking=True,
            host=self.host_string,
            user=self.user_string,
            passwd=self.password_string,
            db=self.db_string,
            port=self.port,
            autocommit=True,
            client_flag=CLIENT.MULTI_STATEMENTS,
            cursorclass=MySQLdb.cursors.DictCursor,
            ping=1
        )

    def create_tables_if_not_exists(self, connection):
        cursor = connection.cursor()
        try:
            for statement in create_tables_str.split(";"):
                if statement.strip():
                    cursor.execute(statement)
                    while cursor.nextset():
                        pass
        except MySQLdb.MySQLError as e:
            print(f"MySQLConnectionProvider: [ERROR] executing query:\n{statement}\n{e}")
        finally:
            cursor.close()

    def _migrate_legacy_function_names(self):
        """Rename legacy function tokens in place before default seeding.

        The function id is preserved, so project restrictions, configuration sets,
        job history, and participation rows that reference it by foreign key remain intact.
        """
        connection = self.get_connection()
        try:
            cursor = connection.cursor()
            legacy_name = "LOGISTIC_CALIBRATION_STATISTICS"
            canonical_name = str(SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION)

            cursor.execute(
                f"SELECT id FROM {MySQLTable.FUNCTIONS} WHERE name = %s LIMIT 1",
                (legacy_name,),
            )
            legacy_row = cursor.fetchone()
            if not legacy_row:
                return

            cursor.execute(
                f"SELECT id FROM {MySQLTable.FUNCTIONS} WHERE name = %s LIMIT 1",
                (canonical_name,),
            )
            canonical_row = cursor.fetchone()
            if canonical_row:
                print(
                    "MySQLConnectionProvider: [WARN] both legacy and canonical exceptional-response "
                    "function rows exist; leaving them unchanged for manual reconciliation.",
                    flush=True,
                )
                return

            cursor.execute(
                f"UPDATE {MySQLTable.FUNCTIONS} SET name = %s WHERE id = %s",
                (canonical_name, legacy_row["id"]),
            )
            print(
                f"MySQLConnectionProvider: migrated function {legacy_name} -> {canonical_name}",
                flush=True,
            )
        finally:
            try:
                cursor.close()
            except Exception:
                pass
            connection.close()

    def _ensure_default_functions_exist(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            required_functions = {
                SupportedFunction.SURVIVAL_ANALYSIS: 'Runs survivability analysis using filtered patient data from all clients',
                SupportedFunction.CHI_SQUARE_TEST: 'Statistical test for association between categorical variables',
                SupportedFunction.STANDARD_DEVIATION: 'The spread of individual measurements around the mean.',
                SupportedFunction.MEAN: 'Summarize continuous variables (e.g., average age, lab measurement mean, variation across sites.)',
                SupportedFunction.T_TEST: 'Compare means of two groups.',
                SupportedFunction.ENCRYPTED_FILTERING: 'Applies filters securely in encrypted form.',
                SupportedFunction.COUNT: 'Returns the number of records matching the selected filters.',
                SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION: 'Compute odds ratio per standard deviation of predictive model score for exceptional response.'
            }

            for name, description in required_functions.items():
                cursor.execute(
                    f"""
                    INSERT INTO {MySQLTable.FUNCTIONS} (name, description)
                    SELECT %s, %s
                    FROM DUAL
                    WHERE NOT EXISTS (
                    SELECT 1 FROM {MySQLTable.FUNCTIONS} WHERE name = %s
                    )
                    """,
                    (name, description, name),
                )

            # Keep the renamed function's user-facing description synchronized on existing DBs.
            renamed_function = SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION
            cursor.execute(
                f"UPDATE {MySQLTable.FUNCTIONS} SET description = %s WHERE name = %s",
                (required_functions[renamed_function], str(renamed_function)),
            )

            default_props = {}
            for fn, _ in required_functions.items():
                defaults = SupportedFunction.get_default_properties(fn.value)
                if defaults:
                    default_props[str(fn)] = defaults

            for fn_name, props in default_props.items():
                cursor.execute(f"SELECT id FROM {MySQLTable.FUNCTIONS} WHERE name = %s", (fn_name,))
                row = cursor.fetchone()
                if not row:
                    continue
                function_id = row["id"]

                for prop_name, prop_value in props.items():
                    cursor.execute(
                        """
                        INSERT INTO defined_function_config_properties (function_id, property_name, property_value)
                        SELECT %s, %s, %s
                        FROM DUAL
                        WHERE NOT EXISTS (
                        SELECT 1
                        FROM defined_function_config_properties
                        WHERE function_id = %s
                            AND property_name = %s
                            AND property_value = %s
                        )
                        """,
                        (function_id, prop_name, prop_value,
                         function_id, prop_name, prop_value),
                    )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_default_roles_exist(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            required_roles = {
                UserRole.INITIATOR: 'A user who initiates NVFlare jobs.',
                UserRole.CLIENT: 'A user who runs NVFlare client jobs.',
                UserRole.OBSERVER: 'A user who is not a client, and can view results of jobs.',
                UserRole.ADMIN: 'Administrative user who can approve registration of new client machines, view results, initiate jobs.',
            }

            for name, description in required_roles.items():
                cursor.execute("SELECT id FROM " + MySQLTable.USER_ROLES + " WHERE name = %s", (name,))
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO " + MySQLTable.USER_ROLES + " (name, description) VALUES (%s, %s)",
                        (name, description)
                    )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_default_filter_systems_exist(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            required_systems = {
                SupportedFilterSystem.DEFAULT: "General analysis filter system tied to broad fhir observation data.",
                SupportedFilterSystem.CANCER_TYPE: "Filter system focused on known cancer types, utilized in biomarker pipeline.",
            }

            for name, description in required_systems.items():
                cursor.execute(
                    """
                    INSERT INTO defined_filter_system (name, description)
                    SELECT %s, %s
                    FROM DUAL
                    WHERE NOT EXISTS (
                        SELECT 1 FROM defined_filter_system WHERE name = %s
                    )
                    """,
                    (str(name), description, str(name)),
                )

            cursor.execute("SELECT id, name FROM defined_filter_system")
            rows = cursor.fetchall() or []
            filter_system_id_by_name = {r["name"]: r["id"] for r in rows if r.get("name") and r.get("id")}

            allowed_by_system = {
                str(SupportedFilterSystem.DEFAULT): ["PATIENT_QUERY", "PATIENT_DATA", "OBSERVATION"],
                str(SupportedFilterSystem.CANCER_TYPE): ["PATIENT_DATA"],
            }

            for sys_name, allowed_types in allowed_by_system.items():
                fs_id = filter_system_id_by_name.get(sys_name)
                if not fs_id:
                    continue
                for ft in allowed_types:
                    cursor.execute(
                        """
                        INSERT INTO defined_filter_system_allowed_filter_types (filter_system_id, filter_type)
                        SELECT %s, %s
                        FROM DUAL
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM defined_filter_system_allowed_filter_types
                            WHERE filter_system_id = %s AND filter_type = %s
                        )
                        """,
                        (fs_id, ft, fs_id, ft),
                    )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_default_projects_exist(self):
        import json

        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            required_projects = {
                "General Statistics": {
                    "description": "Federated analysis functions for general statistics.",
                    "status": "ACTIVE",
                    "fixed": 1,
                    "function_restrictions_enabled": 1,
                    "model_file_settings_enabled": 0,
                    "filter_system": SupportedFilterSystem.DEFAULT,
                    "restricted_functions": [SupportedFunction.SURVIVAL_ANALYSIS,
                        SupportedFunction.CHI_SQUARE_TEST,
                        SupportedFunction.MEAN,
                        SupportedFunction.STANDARD_DEVIATION,
                        SupportedFunction.PARTICIPATION_CONFIRMATION,
                        SupportedFunction.T_TEST,
                        SupportedFunction.ENCRYPTED_FILTERING,
                        SupportedFunction.COUNT,
                        ],
                    "custom_function_configuration_fixed": {},
                    "custom_function_configuration_variable": {},
                    "override_function_configuration": {},
                },
                "Biomarker Model Validation for Cancer Prognosis": {
                    "description": "This pipeline identifies high-impact genetic biomarkers associated with survival outcomes in a specific cancer type. This is done by leveraging penalized generalized linear models — including Cox proportional hazards regression and logistic regression — trained on an initiating site's local dataset. Candidate biomarkers and model findings are validated across distributed participant sites to compare survival outcomes, characterize exceptional responders, and test the generalizability of the local hypothesis.",
                    "status": "ACTIVE",
                    "fixed": 1,
                    "function_restrictions_enabled": 1,
                    "model_file_settings_enabled": 1,
                    "filter_system": SupportedFilterSystem.CANCER_TYPE,
                    "restricted_functions": [SupportedFunction.SURVIVAL_ANALYSIS,
                        SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION,],
                    "custom_function_configuration_fixed": {
                        str(SupportedFunction.SURVIVAL_ANALYSIS): {
                            "is_server_contributing_to_aggregation": False,
                            "is_biomarker_discovery": True,
                            "model_key": "cox_lasso",
                        },
                        str(SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION): {
                            "is_server_contributing_to_aggregation": False,
                        }
                    },
                    "custom_function_configuration_variable": {
                        str(SupportedFunction.SURVIVAL_ANALYSIS): {
                            "cancer_type": {
                                "type": "str",
                                "default": "$PATIENT_DATA_CANCER_TYPE",
                                "description": "Selected cancer type on Patient filter screen.",
                            },
                            "model_type": {
                                "type": "select",
                                "options": [MODEL_TYPE_OPEN_ACCESS, MODEL_TYPE_ENCRYPTED],
                                "default": "Encrypted",
                                "description": "Open-access model: The training institution shares the model in the clear with all participants and computing server.\n\rEncrypted model: The training institution encrypts the model and neither the participants nor the computing server can retrieve the model weights.",
                            },
                        },
                        str(SupportedFunction.EXCEPTIONAL_RESPONSE_DISCRIMINATION): {
                            "cancer_type": {
                                "type": "str",
                                "default": "$PATIENT_DATA_CANCER_TYPE",
                                "description": "Selected cancer type on Patient filter screen.",
                            },
                            "model_type": {
                                "type": "select",
                                "options": [MODEL_TYPE_OPEN_ACCESS, MODEL_TYPE_ENCRYPTED],
                                "default": MODEL_TYPE_ENCRYPTED,
                                "description": "Open-access model: The training institution shares the model in the clear with all participants and computing server.\n\rEncrypted model: The training institution encrypts the model and neither the participants nor the computing server can retrieve the model weights.",
                            },
                        }
                    },
                    "override_function_configuration": {
                        str(SupportedFunction.SURVIVAL_ANALYSIS): {
                            "group_column_id": "risk_score_group",
                            "time_column_id": "time",
                            "censoring_column_id": "event",
                            "time_grid_step": 1,
                            "time_grid_max": 110,
                        }
                    },
                },
            }

            filter_system_ids: dict[SupportedFilterSystem, int] = {}
            for attrs in required_projects.values():
                fs = attrs["filter_system"]
                if fs in filter_system_ids:
                    continue
                cursor.execute(
                    "SELECT id FROM defined_filter_system WHERE name = %s",
                    (str(fs),),
                )
                row = cursor.fetchone()
                if row:
                    filter_system_ids[fs] = row["id"]

            for name, attrs in required_projects.items():
                filter_system_id = filter_system_ids.get(attrs["filter_system"])

                cursor.execute(
                    "SELECT id FROM defined_projects WHERE name = %s",
                    (name,),
                )
                row = cursor.fetchone()

                if not row:
                    cursor.execute(
                        """
                        INSERT INTO defined_projects
                            (name, description, status, fixed, function_restrictions_enabled, model_file_settings_enabled, filter_system_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            name,
                            attrs["description"],
                            attrs["status"],
                            attrs["fixed"],
                            attrs["function_restrictions_enabled"],
                            attrs.get("model_file_settings_enabled", 0),
                            filter_system_id,
                        ),
                    )
                    project_id = cursor.lastrowid
                else:
                    project_id = row["id"]
                    cursor.execute(
                        """
                        UPDATE defined_projects
                        SET description = %s,
                            status = %s,
                            fixed = %s,
                            function_restrictions_enabled = %s,
                            model_file_settings_enabled = %s,
                            filter_system_id = %s
                        WHERE id = %s
                        """,
                        (
                            attrs["description"],
                            attrs["status"],
                            attrs["fixed"],
                            attrs["function_restrictions_enabled"],
                            attrs.get("model_file_settings_enabled", 0),
                            filter_system_id,
                            project_id,
                        ),
                    )

                if attrs.get("function_restrictions_enabled") and attrs.get("restricted_functions"):
                    fixed_map = attrs.get("custom_function_configuration_fixed") or {}
                    variable_map = attrs.get("custom_function_configuration_variable") or {}
                    override_map = attrs.get("override_function_configuration") or {}

                    for fn in attrs["restricted_functions"]:
                        cursor.execute(
                            f"SELECT id FROM {MySQLTable.FUNCTIONS} WHERE name = %s",
                            (str(fn),),
                        )
                        fn_row = cursor.fetchone()
                        if not fn_row:
                            continue
                        function_id = fn_row["id"]

                        fixed_cfg = fixed_map.get(str(fn))
                        fixed_cfg_json = json.dumps(fixed_cfg) if fixed_cfg is not None else None

                        variable_cfg = variable_map.get(str(fn))
                        variable_cfg_json = json.dumps(variable_cfg) if variable_cfg is not None else None

                        override_cfg = override_map.get(str(fn))
                        override_cfg_json = json.dumps(override_cfg) if override_cfg is not None else None

                        cursor.execute(
                            """
                            INSERT INTO defined_project_function_restrictions
                                (project_id, function_id, enabled, configurable, custom_configuration_fixed, custom_configuration_variable, override_configuration)
                            VALUES (%s, %s, 'ENABLED', %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                enabled = VALUES(enabled),
                                configurable = VALUES(configurable),
                                custom_configuration_fixed = VALUES(custom_configuration_fixed),
                                custom_configuration_variable = VALUES(custom_configuration_variable),
                                override_configuration = VALUES(override_configuration)
                            """,
                            (project_id, function_id, 0, fixed_cfg_json, variable_cfg_json, override_cfg_json),
                        )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_test_users_exist(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            # Seed only the administrative account here. The NVFlare site users
            # (client_site1, client_site2, and initiator) are created separately by
            # _ensure_default_nvflare_clients().
            cursor.execute(
                f"SELECT id FROM {MySQLTable.USER_ROLES} WHERE name = %s",
                ('ADMIN',),
            )
            admin_role = cursor.fetchone()
            if not admin_role:
                return

            username = 'duality_admin'
            pwd_hash = 'DISABLED'

            cursor.execute(
                f"""
                INSERT INTO {MySQLTable.USERS} (username, password_hash, role_id)
                SELECT %s, %s, %s
                FROM DUAL
                WHERE NOT EXISTS (
                    SELECT 1 FROM {MySQLTable.USERS} WHERE username = %s
                )
                """,
                (username, pwd_hash, admin_role['id'], username),
            )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_default_nvflare_clients(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(f"SELECT id, name FROM {MySQLTable.USER_ROLES}")
            rows = cursor.fetchall()
            role_id_by_name = {r['name']: r['id'] for r in rows}

            client_role_id = role_id_by_name.get('CLIENT')
            initiator_role_id = role_id_by_name.get('INITIATOR')

            if not client_role_id or not initiator_role_id:
                return

            client_definitions = [
                {
                    "client_name": "site1",
                    "username": "client_site1",
                    "description": "Auto-created for site1",
                    "role_id": client_role_id,
                },
                {
                    "client_name": "site2",
                    "username": "client_site2",
                    "description": "Auto-created for site2",
                    "role_id": client_role_id,
                },
                {
                    "client_name": "site3",
                    "username": "initiator",
                    "description": "Auto-created for site3/intiiator",
                    "role_id": initiator_role_id,
                },
            ]

            for client in client_definitions:
                cursor.execute(
                    f"SELECT id FROM {MySQLTable.USERS} WHERE username = %s",
                    (client["username"],),
                )
                row = cursor.fetchone()

                if row:
                    user_id = row["id"]
                else:
                    cursor.execute(
                        f"""
                        INSERT INTO {MySQLTable.USERS} (username, password_hash, role_id)
                        VALUES (%s, %s, %s)
                        """,
                        (client["username"], "DISABLED", client["role_id"]),
                    )
                    user_id = cursor.lastrowid

                cursor.execute(
                    """
                    INSERT INTO nvflare_clients (client_name, user_id, description)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        user_id = VALUES(user_id),
                        description = VALUES(description)
                    """,
                    (client["client_name"], user_id, client["description"]),
                )

            connection.commit()
        finally:
            cursor.close()
            connection.close()


    def _ensure_default_defined_project_datasource_groups(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute("SELECT id, name FROM defined_projects")
            project_rows = cursor.fetchall() or []
            project_id_by_name = {row["name"]: row["id"] for row in project_rows if row.get("name") and row.get("id")}

            biomarker_project_id = project_id_by_name.get("Biomarker Model Validation for Cancer Prognosis")
            if not biomarker_project_id:
                connection.commit()
                return

            # Normalize the legacy MSK_Chord spelling if an existing database has it.
            # Fresh public databases seed only MSKChord below.
            cursor.execute(
                """
                SELECT id
                FROM defined_project_datasource_groups
                WHERE project_id = %s AND group_name = %s
                """,
                (biomarker_project_id, "MSKChord"),
            )
            mskchord_row = cursor.fetchone()
            if not mskchord_row:
                cursor.execute(
                    """
                    UPDATE defined_project_datasource_groups
                    SET group_name = %s
                    WHERE project_id = %s AND group_name = %s
                    """,
                    ("MSKChord", biomarker_project_id, "MSK_Chord"),
                )

            # The public biomarker pipeline includes only MSKChord. On a fresh
            # public database it is seeded first, so its datasource group id is 1.
            group_definitions = [
                {
                    "project_id": biomarker_project_id,
                    "group_name": "MSKChord",
                    "is_default": 1,
                },
            ]

            for group in group_definitions:
                cursor.execute(
                    """
                    INSERT INTO defined_project_datasource_groups (project_id, group_name, is_default)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        is_default = VALUES(is_default)
                    """,
                    (group["project_id"], group["group_name"], group["is_default"]),
                )

            cursor.execute(
                """
                UPDATE defined_project_datasource_groups
                SET is_default = CASE WHEN group_name = %s THEN 1 ELSE 0 END
                WHERE project_id = %s
                """,
                ("MSKChord", biomarker_project_id),
            )

            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_default_project_workflow_groups(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute("SELECT id, name FROM defined_projects")
            project_rows = cursor.fetchall() or []
            project_id_by_name = {row["name"]: row["id"] for row in project_rows if row.get("name") and row.get("id")}

            biomarker_project_id = project_id_by_name.get("Biomarker Model Validation for Cancer Prognosis")
            if not biomarker_project_id:
                connection.commit()
                return

            group_definition = {
                "project_id": biomarker_project_id,
                "group_key": "predictive_modeling_method_ids",
                "group_label": "Predictive Model Configuration",
                "group_description": "Select one or more predictive models to invoke.",
                "min_selected": 1,
                "max_selected": None,
                "is_required": 1,
                "page_order": 0,
                "status": "ACTIVE",
                "validation_config": {
                    "enabled": True,
                    "validation_type": "model_file_availability",
                    "endpoint": "/user/model-files/availability",
                    "method": "POST",
                    "username": "initiator",
                    "model_file_lookup_key": "cancer_type",
                    "lookup_value_context_key": "cancer_type",
                    "option_values_request_field": "model_keys",
                    "required_artifact_types": ["weights", "cutoff"],
                    "available_values_response_field": "available_model_keys",
                    "availability_response_field": "availability_by_model_key",
                    "disabled_label_suffix": " (Unsupported)",
                    "disabled_reason": "No model files are configured for this datasource group and cancer type.",
                },
            }

            cursor.execute(
                """
                INSERT INTO defined_project_workflow_groups
                    (project_id, group_key, group_label, group_description, min_selected, max_selected, is_required, page_order, status, validation_config)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    group_label = VALUES(group_label),
                    group_description = VALUES(group_description),
                    min_selected = VALUES(min_selected),
                    max_selected = VALUES(max_selected),
                    is_required = VALUES(is_required),
                    page_order = VALUES(page_order),
                    status = VALUES(status),
                    validation_config = VALUES(validation_config)
                """,
                (
                    group_definition["project_id"],
                    group_definition["group_key"],
                    group_definition["group_label"],
                    group_definition["group_description"],
                    group_definition["min_selected"],
                    group_definition["max_selected"],
                    group_definition["is_required"],
                    group_definition["page_order"],
                    group_definition["status"],
                    json.dumps(group_definition["validation_config"]),
                ),
            )

            cursor.execute(
                """
                SELECT id
                FROM defined_project_workflow_groups
                WHERE project_id = %s AND group_key = %s
                """,
                (biomarker_project_id, group_definition["group_key"]),
            )
            workflow_group_row = cursor.fetchone()
            if not workflow_group_row:
                connection.commit()
                return

            workflow_group_id = workflow_group_row["id"]

            option_definitions = [
                {
                    "workflow_group_id": workflow_group_id,
                    "option_key": "cox_lasso",
                    "option_label": "Lasso Cox Regression",
                    "option_value": "cox_lasso",
                    "option_description": "The model fits a Cox proportional hazards regression on patient survival data, using L1 (LASSO) penalization on the mutation burden gene features while leaving clinical covariates unpenalized. The regularization strength is chosen via 5-fold cross-validation on the concordance index. This produces a sparse linear risk score which is used to stratify patients into High/Low risk groups at a cutoff optimized on the training set by log-rank test separation of their Kaplan-Meier survival curves.",
                    "option_order": 0,
                    "is_default": 0,
                    "status": "ACTIVE",
                },
                {
                    "workflow_group_id": workflow_group_id,
                    "option_key": "logistic_reg",
                    "option_label": "Lasso Logistic Regression",
                    "option_value": "logistic_reg",
                    "option_description": "The model fits a logistic regression to predict exceptional responders (ER) – patients whose survival time exceeds the training mean + 2 standard deviations, using L1 (LASSO) penalization uniformly on all features. The regularization strength is chosen via 5-fold cross-validation on the concordance index. This produces a sparse linear risk score which is used to stratify patients into High/Low risk groups at a cutoff optimized on the training set by log-rank test separation of their Kaplan-Meier survival curves.",
                    "option_order": 1,
                    "is_default": 0,
                    "status": "ACTIVE",
                },
            ]

            for option_definition in option_definitions:
                cursor.execute(
                    """
                    INSERT INTO defined_project_workflow_group_options
                        (workflow_group_id, option_key, option_label, option_value, option_description, option_order, is_default, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        option_label = VALUES(option_label),
                        option_value = VALUES(option_value),
                        option_description = VALUES(option_description),
                        option_order = VALUES(option_order),
                        is_default = VALUES(is_default),
                        status = VALUES(status)
                    """,
                    (
                        option_definition["workflow_group_id"],
                        option_definition["option_key"],
                        option_definition["option_label"],
                        option_definition["option_value"],
                        option_definition["option_description"],
                        option_definition["option_order"],
                        option_definition["is_default"],
                        option_definition["status"],
                    ),
                )

            connection.commit()
        finally:
            cursor.close()
            connection.close()


    def _ensure_default_user_fhir_sources(self):
        connection = self.get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute("SELECT id, name FROM defined_projects")
            project_rows = cursor.fetchall() or []
            project_id_by_name = {row["name"]: row["id"] for row in project_rows if row.get("name") and row.get("id")}

            cursor.execute(f"SELECT id, username FROM {MySQLTable.USERS}")
            user_rows = cursor.fetchall() or []
            user_id_by_username = {row["username"]: row["id"] for row in user_rows if row.get("username") and row.get("id")}

            cursor.execute("SELECT id, project_id, group_name FROM defined_project_datasource_groups")
            datasource_group_rows = cursor.fetchall() or []
            datasource_group_id_by_key = {
                (row["project_id"], row["group_name"]): row["id"]
                for row in datasource_group_rows
                if row.get("project_id") and row.get("group_name") and row.get("id")
            }

            env = EnvironmentProvider.get_env()

            general_statistics_sources = {
                "client_site1": [
                    {
                        "source": "/data/client/Survivability_FHIR_Data_part2.json",
                        "datasource_group": None,
                    },
                ],
                "client_site2": [
                    {
                        "source": "/data/client/Survivability_FHIR_Data_part3.json",
                        "datasource_group": None,
                    },
                ],
                "initiator": [
                    {
                        "source": "/data/client/Survivability_FHIR_Data_part1.json",
                        "datasource_group": None,
                    },
                ],
            }

            local_biomarker_sources = {
                "client_site1": [
                    {
                        "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json",
                        "datasource_group": "MSKChord",
                    },
                ],
                "client_site2": [
                    {
                        "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json",
                        "datasource_group": "MSKChord",
                    },
                ],
                "initiator": [
                    {
                        "source": "/data/client/Biomarker_MSKChord_FHIR_Data_training_bundle.json",
                        "datasource_group": "MSKChord",
                    },
                ],
            }

            dev_biomarker_sources = {
                "client_site1": [
                    {
                        "source": "/path/to/site1/fhir_data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json",
                        "datasource_group": "MSKChord",
                    },
                ],
                "client_site2": [
                    {
                        "source": "/path/to/site2/fhir_data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json",
                        "datasource_group": "MSKChord",
                    },
                ],
                "initiator": [
                    {
                        "source": "/path/to/initiator/fhir_data/Biomarker_MSKChord_FHIR_Data_training_bundle.json",
                        "datasource_group": "MSKChord",
                    },
                ],
            }

            default_source_map = {
                "General Statistics": general_statistics_sources,
                "Biomarker Model Validation for Cancer Prognosis": local_biomarker_sources if env == Environment.LOCAL else dev_biomarker_sources,
            }

            def insert_source_if_changed(user_id, project_id, source, datasource_group_id):
                if datasource_group_id is None:
                    # The unique key (user_id, project_id, datasource_group) never
                    # collides on NULL groups, so ON DUPLICATE KEY UPDATE would
                    # insert a second row instead of updating the seeded one.
                    cursor.execute(
                        """
                        SELECT id
                        FROM users_fhir_source_by_project
                        WHERE user_id = %s AND project_id = %s AND datasource_group IS NULL
                        ORDER BY id
                        LIMIT 1
                        """,
                        (user_id, project_id),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        cursor.execute(
                            """
                            UPDATE users_fhir_source_by_project
                            SET source = %s, update_date = CURRENT_TIMESTAMP
                            WHERE id = %s
                            """,
                            (source, existing["id"]),
                        )
                        return
                cursor.execute(
                    """
                    INSERT INTO users_fhir_source_by_project
                        (user_id, project_id, source, datasource_group)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        source = VALUES(source),
                        update_date = CURRENT_TIMESTAMP
                    """,
                    (user_id, project_id, source, datasource_group_id),
                )

            for project_name, user_sources in default_source_map.items():
                project_id = project_id_by_name.get(project_name)
                if not project_id:
                    continue

                for username, source_configs in user_sources.items():
                    user_id = user_id_by_username.get(username)
                    if not user_id:
                        continue

                    for source_config in source_configs:
                        datasource_group_name = source_config.get("datasource_group")
                        datasource_group_id = None
                        if datasource_group_name:
                            datasource_group_id = datasource_group_id_by_key.get((project_id, datasource_group_name))

                        insert_source_if_changed(
                            user_id,
                            project_id,
                            source_config["source"],
                            datasource_group_id,
                        )

            connection.commit()
        finally:
            cursor.close()
            connection.close()


    def _default_biomarker_model_file_manifest(self) -> dict[str, list[str]]:
        """Return the reference biomarker model filenames that ship with standalone.

        The public biomarker pipeline includes only MSKChord.

        The backend should not need filesystem access to the model files at job time.
        This manifest is used only to seed MySQL rows that point at the initiator
        container paths under /data/model_files.
        """
        return {'datasource_group_1': ['cox_lasso_Breast Carcinoma_cutoff.csv',
                        'cox_lasso_Breast Carcinoma_weights.csv',
                        'cox_lasso_Colorectal Cancer_cutoff.csv',
                        'cox_lasso_Colorectal Cancer_weights.csv',
                        'cox_lasso_Non-Small Cell Lung Cancer_cutoff.csv',
                        'cox_lasso_Non-Small Cell Lung Cancer_weights.csv',
                        'cox_lasso_Pancreatic Cancer_cutoff.csv',
                        'cox_lasso_Pancreatic Cancer_weights.csv',
                        'cox_lasso_Prostate Cancer_cutoff.csv',
                        'cox_lasso_Prostate Cancer_weights.csv',
                        'logistic_reg_Breast Carcinoma_cutoff.csv',
                        'logistic_reg_Breast Carcinoma_weights.csv',
                        'logistic_reg_Colorectal Cancer_cutoff.csv',
                        'logistic_reg_Colorectal Cancer_weights.csv',
                        'logistic_reg_Non-Small Cell Lung Cancer_cutoff.csv',
                        'logistic_reg_Non-Small Cell Lung Cancer_weights.csv',
                        'logistic_reg_Pancreatic Cancer_cutoff.csv',
                        'logistic_reg_Pancreatic Cancer_weights.csv',
                        'logistic_reg_Prostate Cancer_cutoff.csv',
                        'logistic_reg_Prostate Cancer_weights.csv']}

    def _discover_reference_biomarker_model_files(self) -> dict[str, list[str]]:
        """Return datasource_group folder name -> sorted file names.

        Prefer a real reference tree when this code is being run from a local checkout,
        but fall back to the built-in manifest so the backend container can still seed
        the database even though it does not have access to standalone/docker_stage/model_files.
        """
        roots: list[Path] = []

        env_root = os.getenv("DUALITY_REFERENCE_BIOMARKER_MODELS_ROOT", "").strip()
        if env_root:
            roots.append(Path(env_root).expanduser())

        roots.extend(
            [
                Path("app") / "core" / "job_runner" / "nvflare_jobs" / "biomarker_models",
                Path.cwd() / "biomarker_models",
                Path.cwd() / "model_files" / "project_2",
            ]
        )

        try:
            here = Path(__file__).resolve()
            for base in [here.parent, *list(here.parents)[:8]]:
                roots.extend(
                    [
                        base / "biomarker_models",
                        base / "nvflare_jobs" / "biomarker_models",
                        base / "model_files" / "project_2",
                    ]
                )
        except Exception:
            pass

        for root in roots:
            try:
                root = root.expanduser().resolve()
            except Exception:
                continue
            if not root.is_dir():
                continue

            out: dict[str, list[str]] = {}
            for group_dir in sorted(root.glob("datasource_group_*")):
                if not group_dir.is_dir():
                    continue
                files = sorted(
                    f.name
                    for f in group_dir.glob("*.csv")
                    if re.match(r"^(cox_lasso|logistic_reg)_.+_(weights|cutoff)\.csv$", f.name)
                )
                if files:
                    out[group_dir.name] = files

            if out:
                return out

        return self._default_biomarker_model_file_manifest()

    def _parse_biomarker_model_file_name(self, file_name: str):
        match = re.match(r"^(cox_lasso|logistic_reg)_(.+)_(weights|cutoff)\.csv$", str(file_name or ""))
        if not match:
            return None
        return match.group(1), match.group(2), match.group(3)

    def _resolve_model_file_datasource_group_id(
        self,
        group_dir_name: str,
        datasource_group_rows: list[dict],
    ) -> int | None:
        """Resolve a standalone model folder to its fresh-install datasource group id.

        The biomarker datasource groups and model folders intentionally share the
        same stable numbering:
          datasource_group_1 -> id 1 -> MSKChord

        Return None rather than silently mapping a folder to the wrong datasource
        group if the fresh-install id/name contract is not satisfied.
        """
        if not datasource_group_rows:
            return None

        match = re.match(r"^datasource_group_(\d+)$", str(group_dir_name or ""))
        if not match:
            return None

        datasource_group_id = int(match.group(1))
        expected_group_name_by_id = {
            1: "MSKChord",
        }
        expected_group_name = expected_group_name_by_id.get(datasource_group_id)
        if expected_group_name is None:
            return None

        for row in datasource_group_rows:
            if (
                row.get("id") == datasource_group_id
                and str(row.get("group_name") or "").strip() == expected_group_name
            ):
                return datasource_group_id

        return None

    def _ensure_default_user_model_file_sources(self):
        connection = self.get_connection()
        inserted_or_updated = 0
        skipped_groups: list[str] = []
        try:
            cursor = connection.cursor()

            cursor.execute("SELECT id, name FROM defined_projects")
            project_rows = cursor.fetchall() or []
            project_id_by_name = {row["name"]: row["id"] for row in project_rows if row.get("name") and row.get("id")}

            biomarker_project_id = project_id_by_name.get("Biomarker Model Validation for Cancer Prognosis")
            if not biomarker_project_id:
                print("MySQLConnectionProvider: [WARN] Biomarker project not found; skipping default model file source seeding.", flush=True)
                connection.commit()
                return

            cursor.execute(f"SELECT id, username FROM {MySQLTable.USERS}")
            user_rows = cursor.fetchall() or []
            user_id_by_username = {row["username"]: row["id"] for row in user_rows if row.get("username") and row.get("id")}

            initiator_user_id = user_id_by_username.get("initiator")
            if not initiator_user_id:
                print("MySQLConnectionProvider: [WARN] Initiator user not found; skipping default model file source seeding.", flush=True)
                connection.commit()
                return

            cursor.execute(
                """
                SELECT id, project_id, group_name
                FROM defined_project_datasource_groups
                WHERE project_id = %s
                """,
                (biomarker_project_id,),
            )
            datasource_group_rows = cursor.fetchall() or []
            if not datasource_group_rows:
                print("MySQLConnectionProvider: [WARN] No biomarker datasource groups found; skipping default model file source seeding.", flush=True)
                connection.commit()
                return

            env = EnvironmentProvider.get_env()
            if env == Environment.LOCAL:
                model_root = "/data/model_files"
            else:
                model_root = "/path/to/initiator/models"

            # Seed initiator model mappings from the canonical built-in manifest.
            #
            # Do not auto-discover a local checkout model tree here. A stale
            # model_files/project_2 directory can otherwise silently override the
            # intended public datasource contract: datasource_group_1 = MSKChord.
            files_by_group = self._default_biomarker_model_file_manifest()

            for group_dir_name, file_names in files_by_group.items():
                datasource_group_id = self._resolve_model_file_datasource_group_id(
                    group_dir_name,
                    datasource_group_rows,
                )
                if datasource_group_id is None:
                    skipped_groups.append(group_dir_name)
                    continue

                for file_name in file_names:
                    parsed = self._parse_biomarker_model_file_name(file_name)
                    if not parsed:
                        continue
                    model_key, cancer_type, artifact_type = parsed
                    source = f"{model_root}/project_2/{group_dir_name}/{file_name}"

                    cursor.execute(
                        """
                        INSERT INTO users_model_file_source_by_project
                            (user_id, project_id, datasource_group, model_file_lookup_key, model_file_lookup_value, model_key, artifact_type, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            source = VALUES(source),
                            update_date = CURRENT_TIMESTAMP
                        """,
                        (
                            initiator_user_id,
                            biomarker_project_id,
                            datasource_group_id,
                            "cancer_type",
                            cancer_type,
                            model_key,
                            artifact_type,
                            source,
                        ),
                    )
                    inserted_or_updated += 1

            connection.commit()

            print(
                "MySQLConnectionProvider: default user model file source seeding complete: "
                f"rows_inserted_or_updated={inserted_or_updated}, "
                f"skipped_groups={skipped_groups}",
                flush=True,
            )
        finally:
            cursor.close()
            connection.close()


create_tables_str="""

    CREATE TABLE IF NOT EXISTS defined_filter_system (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        description TEXT,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_filter_system_allowed_filter_types (
        filter_system_id INT NOT NULL,
        filter_type ENUM('PATIENT_QUERY','PATIENT_DATA','OBSERVATION', 'OBSERVATION_QUERY', 'OBSERVATION_DATA') NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (filter_system_id, filter_type),
        CONSTRAINT fk_dfs_aft_system FOREIGN KEY (filter_system_id)
            REFERENCES defined_filter_system(id) ON DELETE CASCADE,
        INDEX idx_dfs_aft_type (filter_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_projects (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        status ENUM('ACTIVE','ARCHIVED') NOT NULL DEFAULT 'ACTIVE',
        fixed TINYINT(1) NOT NULL DEFAULT 0,
        function_restrictions_enabled TINYINT(1) NOT NULL DEFAULT 0,
        model_file_settings_enabled TINYINT(1) NOT NULL DEFAULT 0,
        filter_system_id INT DEFAULT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_project_name (name),
        CONSTRAINT fk_defined_projects_filter_system
            FOREIGN KEY (filter_system_id)
            REFERENCES defined_filter_system(id)
            ON DELETE SET NULL,
        INDEX idx_filter_system_id (filter_system_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_roles (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL UNIQUE,
        description TEXT,
        create_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS job_runner_log (
        uuid VARCHAR(36) PRIMARY KEY,
        status VARCHAR(255),
        log MEDIUMTEXT,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_create_date (create_date DESC),
        INDEX idx_update_date (update_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_functions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        description TEXT,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_project_function_restrictions (
        project_id INT NOT NULL,
        function_id INT NOT NULL,
        enabled ENUM('ENABLED','DISABLED') NOT NULL DEFAULT 'ENABLED',
        configurable TINYINT(1) NOT NULL DEFAULT 1,
        custom_configuration_fixed JSON NULL,
        custom_configuration_variable JSON NULL,
        override_configuration JSON NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (project_id, function_id),
        CONSTRAINT fk_dpfr_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        CONSTRAINT fk_dpfr_function FOREIGN KEY (function_id)
            REFERENCES defined_functions(id) ON DELETE CASCADE,
        INDEX idx_dpfr_function (function_id),
        INDEX idx_dpfr_enabled (enabled)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_function_config_properties (
        id INT AUTO_INCREMENT PRIMARY KEY,
        function_id INT NOT NULL,
        property_name VARCHAR(191) NOT NULL,
        property_value VARCHAR(191) NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_dfcp_function FOREIGN KEY (function_id)
            REFERENCES defined_functions(id) ON DELETE CASCADE,
        UNIQUE KEY uq_func_prop_val (function_id, property_name, property_value),
        INDEX idx_func_prop (function_id, property_name),
        INDEX idx_dfcp_name_value (property_name, property_value, id, function_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_function_config_sets (
        id INT AUTO_INCREMENT PRIMARY KEY,
        function_id INT NOT NULL,
        config_hash CHAR(64) NOT NULL,
        label VARCHAR(255),
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_dfcs_function FOREIGN KEY (function_id)
            REFERENCES defined_functions(id) ON DELETE RESTRICT,
        UNIQUE KEY uq_dfcs_func_hash (function_id, config_hash),
        INDEX idx_dfcs_function (function_id),
        INDEX idx_dfcs_hash (config_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_function_config_set_members (
        config_set_id INT NOT NULL,
        config_id INT NOT NULL,
        PRIMARY KEY (config_set_id, config_id),
        CONSTRAINT fk_dfcs_member_set FOREIGN KEY (config_set_id)
            REFERENCES defined_function_config_sets(id) ON DELETE CASCADE,
        CONSTRAINT fk_dfcs_member_cfg FOREIGN KEY (config_id)
            REFERENCES defined_function_config_properties(id) ON DELETE RESTRICT,
        INDEX idx_dfcs_member_cfg (config_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_fhir_filters (
        id INT AUTO_INCREMENT PRIMARY KEY,
        project_id INT NOT NULL,
        name VARCHAR(255),
        filter_hash CHAR(64) NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_dff_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        INDEX idx_project_id (project_id),
        INDEX idx_create_date (create_date),
        UNIQUE KEY uq_project_filter_hash (project_id, filter_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_fhir_filter_conditions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        filter_id INT NOT NULL,
        filter_type ENUM('PATIENT_QUERY','PATIENT_DATA','OBSERVATION', 'OBSERVATION_QUERY', 'OBSERVATION_DATA') NOT NULL,
        column_name VARCHAR(255) NOT NULL,
        operator VARCHAR(20) NOT NULL,
        value TEXT NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_filter_id (filter_id),
        INDEX idx_filter_type (filter_type),
        CONSTRAINT fk_filter_condition_filter FOREIGN KEY (filter_id)
            REFERENCES defined_fhir_filters(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS threshold_configs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        method ENUM('PROTECTED','EXPOSED') NOT NULL,
        threshold INT NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_threshold_method (method),
        INDEX idx_threshold_value (threshold)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_jobs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        project_id INT NOT NULL,
        nvflare_assigned_id VARCHAR(255) UNIQUE,
        filter_id INT,
        threshold_config_id INT NULL,
        status VARCHAR(255),
        job_path TEXT,
        output_path TEXT,
        job_runner_id VARCHAR(255),
        submit_time DATETIME(6) NULL,
        run_duration VARCHAR(64) NULL,
        non_contributing_clients TEXT NULL,
        exclude_analyzing_clients TEXT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_nvjobs_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        CONSTRAINT fk_nvjobs_filter FOREIGN KEY (filter_id)
            REFERENCES defined_fhir_filters(id) ON DELETE SET NULL,
        CONSTRAINT fk_nvjobs_threshold FOREIGN KEY (threshold_config_id)
            REFERENCES threshold_configs(id) ON DELETE SET NULL,
        INDEX idx_status (status),
        INDEX idx_filter_id (filter_id),
        INDEX idx_project_id (project_id),
        INDEX idx_nvjobs_project_create (project_id, create_date, id),
        INDEX idx_threshold_config_id (threshold_config_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_job_crypto_audit (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nvflare_job_id VARCHAR(255) UNIQUE,
        client_id VARCHAR(64) NULL,
        security_level VARCHAR(255) NULL,
        ring_dimension INT NOT NULL,
        batch_size INT NOT NULL,
        scale_mod_size INT NOT NULL,
        multiplicative_depth INT NOT NULL,
        scaling_technique VARCHAR(64) NOT NULL,
        keyswitch_technique VARCHAR(64) NOT NULL,
        ckks_data_type VARCHAR(32) NOT NULL,
        ind_cpa_noise_bits INT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_crypto_audit_job
            FOREIGN KEY (nvflare_job_id) REFERENCES nvflare_jobs(nvflare_assigned_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_job_functions (
        job_id INT NOT NULL,
        function_id INT NOT NULL,
        PRIMARY KEY (job_id, function_id),
        CONSTRAINT fk_nvjfunc_job FOREIGN KEY (job_id)
            REFERENCES nvflare_jobs(id) ON DELETE CASCADE,
        CONSTRAINT fk_nvjfunc_func FOREIGN KEY (function_id)
            REFERENCES defined_functions(id) ON DELETE RESTRICT,
        INDEX idx_job_id (job_id),
        INDEX idx_function_id (function_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_job_function_configs (
        job_id INT NOT NULL,
        function_config_id INT NOT NULL,
        workflow_id VARCHAR(255) DEFAULT NULL,
        PRIMARY KEY (job_id, function_config_id),
        CONSTRAINT fk_njfc_job FOREIGN KEY (job_id)
            REFERENCES nvflare_jobs(id) ON DELETE CASCADE,
        CONSTRAINT fk_njfc_fn_cfg FOREIGN KEY (function_config_id)
            REFERENCES defined_function_config_sets(id) ON DELETE RESTRICT,
        UNIQUE KEY uq_job_workflow (job_id, workflow_id),
        INDEX idx_njfc_workflow (workflow_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role_id INT NOT NULL,
        create_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (role_id) REFERENCES defined_roles(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_clients (
        id INT AUTO_INCREMENT PRIMARY KEY,
        client_name VARCHAR(100) NOT NULL UNIQUE,
        user_id INT NOT NULL,
        description TEXT,
        create_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        INDEX idx_user_id (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_project_client_exclusions (
        project_id INT NOT NULL,
        client_id INT NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (project_id, client_id),
        CONSTRAINT fk_npce_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        CONSTRAINT fk_npce_client FOREIGN KEY (client_id)
            REFERENCES nvflare_clients(id) ON DELETE CASCADE,
        INDEX idx_npce_client (client_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_client_participation (
        id INT AUTO_INCREMENT PRIMARY KEY,
        client_id INT NOT NULL,
        filter_id INT NOT NULL,
        threshold_config_id INT NULL,
        confirmation ENUM('PENDING','ACCEPT','REJECT') NOT NULL DEFAULT 'PENDING',
        contributing_party TINYINT(1) NOT NULL DEFAULT 1,
        analyzing_party TINYINT(1) NOT NULL DEFAULT 1,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_client_filter (client_id, filter_id),
        CONSTRAINT fk_ncp_client FOREIGN KEY (client_id)
            REFERENCES nvflare_clients(id) ON DELETE CASCADE,
        CONSTRAINT fk_ncp_filter FOREIGN KEY (filter_id)
            REFERENCES defined_fhir_filters(id) ON DELETE CASCADE,
        CONSTRAINT fk_ncp_threshold FOREIGN KEY (threshold_config_id)
            REFERENCES threshold_configs(id) ON DELETE SET NULL,
        INDEX idx_ncp_threshold (threshold_config_id),
        INDEX idx_ncp_filter_confirmation_threshold (filter_id, confirmation, threshold_config_id, id, client_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_client_participation_functions (
        participation_id INT NOT NULL,
        function_id INT NOT NULL,
        PRIMARY KEY (participation_id, function_id),
        CONSTRAINT fk_ncpf_participation FOREIGN KEY (participation_id)
            REFERENCES nvflare_client_participation(id) ON DELETE CASCADE,
        CONSTRAINT fk_ncpf_function FOREIGN KEY (function_id) REFERENCES defined_functions(id) ON DELETE RESTRICT,
        INDEX idx_ncpf_function (function_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS nvflare_client_participation_function_configs (
        participation_id INT NOT NULL,
        function_config_id INT NOT NULL,
        PRIMARY KEY (participation_id, function_config_id),
        CONSTRAINT fk_npfc_part FOREIGN KEY (participation_id) REFERENCES nvflare_client_participation(id) ON DELETE CASCADE,
        CONSTRAINT fk_npfc_fn_cfg FOREIGN KEY (function_config_id) REFERENCES defined_function_config_sets(id) ON DELETE RESTRICT,
        INDEX idx_npfc_part (participation_id),
        INDEX idx_npfc_fn_cfg (function_config_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_project_datasource_groups (
        id INT AUTO_INCREMENT PRIMARY KEY,
        project_id INT NOT NULL,
        group_name VARCHAR(255) NOT NULL,
        is_default TINYINT(1) NOT NULL DEFAULT 0,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_pdg_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        UNIQUE KEY uq_pdg_project_group_name (project_id, group_name),
        INDEX idx_pdg_project (project_id),
        INDEX idx_pdg_is_default (is_default)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_project_workflow_groups (
        id INT AUTO_INCREMENT PRIMARY KEY,
        project_id INT NOT NULL,
        group_key VARCHAR(100) NOT NULL,
        group_label VARCHAR(255) NOT NULL,
        group_description TEXT NULL,
        min_selected INT NOT NULL DEFAULT 0,
        max_selected INT NULL,
        is_required TINYINT(1) NOT NULL DEFAULT 0,
        page_order INT NOT NULL DEFAULT 0,
        status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
        validation_config JSON NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_dpwg_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        UNIQUE KEY uq_dpwg_project_group_key (project_id, group_key),
        INDEX idx_dpwg_project (project_id),
        INDEX idx_dpwg_project_order (project_id, page_order)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS defined_project_workflow_group_options (
        id INT AUTO_INCREMENT PRIMARY KEY,
        workflow_group_id INT NOT NULL,
        option_key VARCHAR(100) NOT NULL,
        option_label VARCHAR(255) NOT NULL,
        option_value VARCHAR(255) NOT NULL,
        option_order INT NOT NULL DEFAULT 0,
        option_description TEXT NULL,
        is_default TINYINT(1) NOT NULL DEFAULT 0,
        status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_dpwgo_group FOREIGN KEY (workflow_group_id)
            REFERENCES defined_project_workflow_groups(id) ON DELETE CASCADE,
        UNIQUE KEY uq_dpwgo_group_option_key (workflow_group_id, option_key),
        UNIQUE KEY uq_dpwgo_group_option_value (workflow_group_id, option_value),
        INDEX idx_dpwgo_group_order (workflow_group_id, option_order)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    CREATE TABLE IF NOT EXISTS users_fhir_source_by_project (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        project_id INT NOT NULL,
        source VARCHAR(1024) NOT NULL,
        datasource_group INT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_ufsbp_user FOREIGN KEY (user_id)
            REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT fk_ufsbp_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        CONSTRAINT fk_ufsbp_datasource_group FOREIGN KEY (datasource_group)
            REFERENCES defined_project_datasource_groups(id) ON DELETE SET NULL,
        UNIQUE KEY uq_ufsbp_user_project_group (user_id, project_id, datasource_group),
        INDEX idx_ufsbp_project (project_id),
        INDEX idx_ufsbp_project_user (project_id, user_id),
        INDEX idx_ufsbp_user (user_id),
        INDEX idx_ufsbp_datasource_group (datasource_group)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


    CREATE TABLE IF NOT EXISTS users_model_file_source_by_project (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        project_id INT NOT NULL,
        datasource_group INT NULL,
        model_file_lookup_key VARCHAR(191) NOT NULL,
        model_file_lookup_value VARCHAR(255) NOT NULL,
        model_key VARCHAR(100) NOT NULL,
        artifact_type ENUM('weights','cutoff') NOT NULL,
        source VARCHAR(1024) NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_umfsbp_user FOREIGN KEY (user_id)
            REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT fk_umfsbp_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        CONSTRAINT fk_umfsbp_datasource_group FOREIGN KEY (datasource_group)
            REFERENCES defined_project_datasource_groups(id) ON DELETE SET NULL,
        UNIQUE KEY uq_umfsbp_user_project_group_lookup_model_artifact
            (user_id, project_id, datasource_group, model_file_lookup_key, model_file_lookup_value, model_key, artifact_type),
        INDEX idx_umfsbp_project (project_id),
        INDEX idx_umfsbp_user (user_id),
        INDEX idx_umfsbp_datasource_group (datasource_group),
        INDEX idx_umfsbp_lookup (project_id, model_file_lookup_key, model_file_lookup_value)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


    CREATE TABLE IF NOT EXISTS nvflare_job_datasource_log (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nvflare_job_id INT NOT NULL,
        project_id INT NOT NULL,
        datasource_group_id INT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_nvjdl_job FOREIGN KEY (nvflare_job_id)
            REFERENCES nvflare_jobs(id) ON DELETE CASCADE,
        CONSTRAINT fk_nvjdl_project FOREIGN KEY (project_id)
            REFERENCES defined_projects(id) ON DELETE CASCADE,
        CONSTRAINT fk_nvjdl_datasource_group FOREIGN KEY (datasource_group_id)
            REFERENCES defined_project_datasource_groups(id) ON DELETE SET NULL,
        UNIQUE KEY uq_nvjdl_job (nvflare_job_id),
        INDEX idx_nvjdl_project (project_id),
        INDEX idx_nvjdl_datasource_group (datasource_group_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


    CREATE TABLE IF NOT EXISTS nvflare_job_workflow_groups (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nvflare_job_id INT NOT NULL,
        workflow_group_id INT NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_nvjwg_job FOREIGN KEY (nvflare_job_id)
            REFERENCES nvflare_jobs(id) ON DELETE CASCADE,
        CONSTRAINT fk_nvjwg_group FOREIGN KEY (workflow_group_id)
            REFERENCES defined_project_workflow_groups(id) ON DELETE CASCADE,
        UNIQUE KEY uq_nvjwg_job_group (nvflare_job_id, workflow_group_id),
        INDEX idx_nvjwg_job (nvflare_job_id),
        INDEX idx_nvjwg_group (workflow_group_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


    CREATE TABLE IF NOT EXISTS nvflare_job_workflow_group_options (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nvflare_job_workflow_group_id INT NOT NULL,
        workflow_group_option_id INT NOT NULL,
        create_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        update_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_njvwgo_job_group FOREIGN KEY (nvflare_job_workflow_group_id)
            REFERENCES nvflare_job_workflow_groups(id) ON DELETE CASCADE,
        CONSTRAINT fk_njvwgo_option FOREIGN KEY (workflow_group_option_id)
            REFERENCES defined_project_workflow_group_options(id) ON DELETE CASCADE,
        UNIQUE KEY uq_njvwgo_group_option (nvflare_job_workflow_group_id, workflow_group_option_id),
        INDEX idx_njvwgo_job_group (nvflare_job_workflow_group_id),
        INDEX idx_njvwgo_option (workflow_group_option_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

"""
