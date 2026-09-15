# Database Initialization and Schema

## Files Covered

| File | Role |
| --- | --- |
| `app/core/mysql/MySQLConnectionProvider.py` | Central MySQL singleton. Reads MySQL configuration, creates the database, creates tables, applies current schema checks, and inserts default rows. |
| `app/core/mysql/MySQLTable.py` | Enum of table names used by manager and job-tracking code. It does not include every table created by startup, but it centralizes names for the core tables used directly by managers. |
| `app/core/mysql/SupportedFunction.py` | Supported function enum, function default properties, function property type metadata, and function-to-computation labels. |
| `app/core/mysql/SupportedFilterSystem.py` | Supported filter-system enum used by project and filter configuration. |
| `app/core/mysql/UserRole.py` | User role enum used by startup role seeding and user-role lookup logic. |
| `app/core/mysql/MySQLRetriever.py` | SQL helper for retrieving and inserting filter definitions and threshold configuration records. |
| `app/core/mysql/managers/*.py` | Domain managers that read/write users, roles, projects, filters, functions, NVFlare jobs, datasource logs, workflow groups, participation state, client progress, and crypto audit records. |
| `app/core/mysql/job_tracking/*.py` | Job status/history/result readers and writers that use `job_runner_log`, `nvflare_jobs`, job/function mapping tables, and function config tables. |

## Initialization Entry Point

`MySQLConnectionProvider.get_instance()` returns a singleton instance of `MySQLConnectionProvider`. The constructor performs both connection setup and schema/default-data initialization.

Startup behavior is not limited to opening a database connection. The provider:

1. Loads MySQL configuration from `ResourceConfigProvider.get_mysql_config(check_cached=False)`.
2. Creates the target database if it does not already exist.
3. Builds a `dbutils.pooled_db.PooledDB` connection pool.
4. Executes all `CREATE TABLE IF NOT EXISTS` statements from `create_tables_str`.
5. Applies current schema checks for `users_fhir_source_by_project`.
6. Applies current lookup indexes for participation and function-config lookups.
7. Seeds supported functions and default function config properties.
8. Seeds user roles.
9. Seeds filter systems and allowed filter types.
10. Seeds default projects and project/function restrictions.
11. Seeds local/test users.
12. Seeds default NVFlare clients when the environment is not `LOCAL`.
13. Seeds default project datasource groups.
14. Seeds default project workflow groups and options.
15. Seeds default user FHIR sources.

The provider creates the database using a raw MySQL connection first, then creates the pooled connection against the target database.

## Connection Pool

The pool is configured in `MySQLConnectionProvider.__init__()` and rebuilt in `rebuild_pool()` with the same settings.

| Setting | Current value |
| --- | --- |
| Pool implementation | `dbutils.pooled_db.PooledDB` |
| DB driver | `MySQLdb` via `pymysql.install_as_MySQLdb()` |
| `maxconnections` | `150` |
| `mincached` | `15` |
| `maxcached` | `45` |
| `blocking` | `True` |
| `autocommit` | `True` |
| `client_flag` | `CLIENT.MULTI_STATEMENTS` |
| Cursor class | `MySQLdb.cursors.DictCursor` |
| `ping` | `1` |

`get_connection()` wraps pool access with `connection_pool_lock`. If acquiring a connection fails, it logs the error, calls `rebuild_pool()`, and retries once against the rebuilt pool.

## Startup Schema Order

The `create_tables_str` block creates tables in this order:

1. `defined_filter_system`
2. `defined_filter_system_allowed_filter_types`
3. `defined_projects`
4. `defined_roles`
5. `job_runner_log`
6. `defined_functions`
7. `defined_project_function_restrictions`
8. `defined_function_config_properties`
9. `defined_function_config_sets`
10. `defined_function_config_set_members`
11. `defined_fhir_filters`
12. `defined_fhir_filter_conditions`
13. `threshold_configs`
14. `nvflare_jobs`
15. `nvflare_job_crypto_audit`
16. `nvflare_job_functions`
17. `nvflare_job_function_configs`
18. `users`
19. `nvflare_clients`
20. `nvflare_project_client_exclusions`
21. `nvflare_client_participation`
22. `nvflare_client_participation_functions`
23. `nvflare_client_participation_function_configs`
24. `defined_project_datasource_groups`
25. `defined_project_workflow_groups`
26. `defined_project_workflow_group_options`
27. `users_fhir_source_by_project`
28. `nvflare_job_datasource_log`
29. `nvflare_job_workflow_groups`
30. `nvflare_job_workflow_group_options`

The order is important because many tables include foreign keys to tables created earlier in the block.

## Current Startup Schema Checks

After table creation, startup runs `_ensure_users_fhir_source_by_project_schema()`.

That method checks `information_schema` and ensures the following current shape exists for `users_fhir_source_by_project`:

| Item | Startup behavior |
| --- | --- |
| `id` column | Adds `id INT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST` if missing. If a primary key already exists, it drops the existing primary key before adding `id`. |
| `datasource_group` column | Adds `datasource_group INT NULL AFTER source` if missing. |
| `uq_ufsbp_user_project_group` | Adds unique key on `(user_id, project_id, datasource_group)` if missing. |
| `idx_ufsbp_user` | Adds index on `(user_id)` if missing. |
| `idx_ufsbp_datasource_group` | Adds index on `(datasource_group)` if missing. |
| `fk_ufsbp_datasource_group` | Adds foreign key from `datasource_group` to `defined_project_datasource_groups(id)` with `ON DELETE SET NULL` if missing. |

Startup also runs `_ensure_participation_lookup_indexes()`.

| Table | Index ensured |
| --- | --- |
| `nvflare_client_participation` | `idx_ncp_filter_confirmation_threshold (filter_id, confirmation, threshold_config_id, id, client_id)` |
| `defined_function_config_properties` | `idx_dfcp_name_value (property_name, property_value, id, function_id)` |

Startup also runs `_ensure_landing_page_indexes()` for the Home/project landing read models:

| Table | Index ensured | Purpose |
| --- | --- | --- |
| `nvflare_jobs` | `idx_nvjobs_project_create (project_id, create_date, id)` | Supports project job counts and newest-first recent-job retrieval. |
| `users_fhir_source_by_project` | `idx_ufsbp_project_user (project_id, user_id)` | Supports distinct registered-user counts per project. |

These startup checks mean the current backend uses a create-table-first approach with targeted schema/index enforcement during startup.

## Table Inventory

### `defined_filter_system`

Stores named filter systems used by projects.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `name` | `VARCHAR(255) NOT NULL UNIQUE` |
| `description` | `TEXT` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Used by `ProjectsManager` and startup project/filter-system seeding.

### `defined_filter_system_allowed_filter_types`

Maps a filter system to allowed filter types.

| Column | Definition |
| --- | --- |
| `filter_system_id` | `INT NOT NULL` |
| `filter_type` | `ENUM('PATIENT_QUERY','PATIENT_DATA','OBSERVATION','OBSERVATION_QUERY','OBSERVATION_DATA') NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(filter_system_id, filter_type)` |
| `fk_dfs_aft_system` | `filter_system_id` references `defined_filter_system(id)` with `ON DELETE CASCADE` |
| `idx_dfs_aft_type` | `(filter_type)` |

Used by `ProjectsManager` when returning project metadata and by startup filter-system seeding.

### `defined_projects`

Stores selectable backend projects.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `name` | `VARCHAR(255) NOT NULL` |
| `description` | `TEXT` |
| `status` | `ENUM('ACTIVE','ARCHIVED') NOT NULL DEFAULT 'ACTIVE'` |
| `fixed` | `TINYINT(1) NOT NULL DEFAULT 0` |
| `function_restrictions_enabled` | `TINYINT(1) NOT NULL DEFAULT 0` |
| `filter_system_id` | `INT DEFAULT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `uq_project_name` | Unique key on `(name)` |
| `fk_defined_projects_filter_system` | `filter_system_id` references `defined_filter_system(id)` with `ON DELETE SET NULL` |
| `idx_filter_system_id` | `(filter_system_id)` |

Used by project listing, project datasource resolution, filter creation, NVFlare job logging, datasource group setup, and workflow group setup.

### `defined_roles`

Stores backend user roles.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `name` | `VARCHAR(50) NOT NULL UNIQUE` |
| `description` | `TEXT` |
| `create_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Used by `UsersManager`, `RolesManager`, `ParticipationManager`, startup role seeding, startup test-user seeding, and deployed-client user seeding.

### `job_runner_log`

Tracks job-runner status and log text by UUID.

| Column | Definition |
| --- | --- |
| `uuid` | `VARCHAR(36) PRIMARY KEY` |
| `status` | `VARCHAR(255)` |
| `log` | `MEDIUMTEXT` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Indexes:

| Name | Definition |
| --- | --- |
| `idx_create_date` | `(create_date DESC)` |
| `idx_update_date` | `(update_date)` |

Used by job status writer/retriever code.

### `defined_functions`

Stores supported computation functions.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `name` | `VARCHAR(255) NOT NULL UNIQUE` |
| `description` | `TEXT` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Used by `FunctionsManager`, `ProjectsManager`, `NVFlareJobsManager`, `NVFlareJobsDataRetriever`, startup function seeding, project/function restrictions, job/function mapping, and participation/function mapping.

### `defined_project_function_restrictions`

Stores which functions are enabled for each project and any project-specific config overrides.

| Column | Definition |
| --- | --- |
| `project_id` | `INT NOT NULL` |
| `function_id` | `INT NOT NULL` |
| `enabled` | `ENUM('ENABLED','DISABLED') NOT NULL DEFAULT 'ENABLED'` |
| `configurable` | `TINYINT(1) NOT NULL DEFAULT 1` |
| `custom_configuration_fixed` | `JSON NULL` |
| `custom_configuration_variable` | `JSON NULL` |
| `override_configuration` | `JSON NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(project_id, function_id)` |
| `fk_dpfr_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `fk_dpfr_function` | `function_id` references `defined_functions(id)` with `ON DELETE CASCADE` |
| `idx_dpfr_function` | `(function_id)` |
| `idx_dpfr_enabled` | `(enabled)` |

Used by `ProjectsManager` and startup project seeding.

### `defined_function_config_properties`

Stores individual function configuration properties.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `function_id` | `INT NOT NULL` |
| `property_name` | `VARCHAR(191) NOT NULL` |
| `property_value` | `VARCHAR(191) NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_dfcp_function` | `function_id` references `defined_functions(id)` with `ON DELETE CASCADE` |
| `uq_func_prop_val` | Unique key on `(function_id, property_name, property_value)` |
| `idx_func_prop` | `(function_id, property_name)` |
| `idx_dfcp_name_value` | `(property_name, property_value, id, function_id)` |

Used by `FunctionsManager`, `NVFlareJobsManager`, `NVFlareJobsDataRetriever`, and startup function property seeding.

### `defined_function_config_sets`

Groups a set of function config properties under a stable hash.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `function_id` | `INT NOT NULL` |
| `config_hash` | `CHAR(64) NOT NULL` |
| `label` | `VARCHAR(255)` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_dfcs_function` | `function_id` references `defined_functions(id)` with `ON DELETE RESTRICT` |
| `uq_dfcs_func_hash` | Unique key on `(function_id, config_hash)` |
| `idx_dfcs_function` | `(function_id)` |
| `idx_dfcs_hash` | `(config_hash)` |

Used by `FunctionsManager`, `NVFlareJobsManager`, `ParticipationManager`, and `NVFlareJobsDataRetriever`.

### `defined_function_config_set_members`

Maps config sets to individual config property rows.

| Column | Definition |
| --- | --- |
| `config_set_id` | `INT NOT NULL` |
| `config_id` | `INT NOT NULL` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(config_set_id, config_id)` |
| `fk_dfcs_member_set` | `config_set_id` references `defined_function_config_sets(id)` with `ON DELETE CASCADE` |
| `fk_dfcs_member_cfg` | `config_id` references `defined_function_config_properties(id)` with `ON DELETE RESTRICT` |
| `idx_dfcs_member_cfg` | `(config_id)` |

Used by `FunctionsManager`, `NVFlareJobsManager`, and `NVFlareJobsDataRetriever`.

### `defined_fhir_filters`

Stores saved filter definitions by project and hash.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `project_id` | `INT NOT NULL` |
| `name` | `VARCHAR(255)` |
| `filter_hash` | `CHAR(64) NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_dff_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `idx_project_id` | `(project_id)` |
| `idx_create_date` | `(create_date)` |
| `uq_project_filter_hash` | Unique key on `(project_id, filter_hash)` |

Used by `FiltersManager`, `MySQLRetriever`, `NVFlareJobsManager`, `ParticipationManager`, and job submission/status flows.

### `defined_fhir_filter_conditions`

Stores the individual conditions for a saved FHIR filter.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `filter_id` | `INT NOT NULL` |
| `filter_type` | `ENUM('PATIENT_QUERY','PATIENT_DATA','OBSERVATION','OBSERVATION_QUERY','OBSERVATION_DATA') NOT NULL` |
| `column_name` | `VARCHAR(255) NOT NULL` |
| `operator` | `VARCHAR(20) NOT NULL` |
| `value` | `TEXT NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_filter_condition_filter` | `filter_id` references `defined_fhir_filters(id)` with `ON DELETE CASCADE` |
| `idx_filter_id` | `(filter_id)` |
| `idx_filter_type` | `(filter_type)` |

Used by `FiltersManager` and `MySQLRetriever`.

### `threshold_configs`

Stores threshold configuration rows for protected/exposed threshold behavior.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `method` | `ENUM('PROTECTED','EXPOSED') NOT NULL` |
| `threshold` | `INT NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Indexes:

| Name | Definition |
| --- | --- |
| `idx_threshold_method` | `(method)` |
| `idx_threshold_value` | `(threshold)` |

Used by `ThresholdManager`, `MySQLRetriever`, `NVFlareJobsManager`, and participation/job records.

### `nvflare_jobs`

Stores submitted NVFlare job records.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `project_id` | `INT NOT NULL` |
| `nvflare_assigned_id` | `VARCHAR(255) UNIQUE` |
| `filter_id` | `INT` |
| `threshold_config_id` | `INT NULL` |
| `status` | `VARCHAR(255)` |
| `job_path` | `TEXT` |
| `output_path` | `TEXT` |
| `job_runner_id` | `VARCHAR(255)` |
| `submit_time` | `DATETIME(6) NULL` |
| `run_duration` | `VARCHAR(64) NULL` |
| `non_contributing_clients` | `TEXT NULL` |
| `exclude_analyzing_clients` | `TEXT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_nvjobs_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `fk_nvjobs_filter` | `filter_id` references `defined_fhir_filters(id)` with `ON DELETE SET NULL` |
| `fk_nvjobs_threshold` | `threshold_config_id` references `threshold_configs(id)` with `ON DELETE SET NULL` |
| `idx_status` | `(status)` |
| `idx_filter_id` | `(filter_id)` |
| `idx_project_id` | `(project_id)` |
| `idx_nvjobs_project_create` | `(project_id, create_date, id)` |
| `idx_threshold_config_id` | `(threshold_config_id)` |

Used by `NVFlareJobsManager`, `LandingPageManager`, `NVFlareJobsDataRetriever`, `JobStatusRetriever`, `NVFlareClientEmitManager`, crypto audit records, datasource logs, workflow group logs, and job result/status endpoints.

### `nvflare_job_crypto_audit`

Stores crypto audit parameters reported for an NVFlare job.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `nvflare_job_id` | `VARCHAR(255) UNIQUE` |
| `client_id` | `VARCHAR(64) NULL` |
| `security_level` | `VARCHAR(255) NULL` |
| `ring_dimension` | `INT NOT NULL` |
| `batch_size` | `INT NOT NULL` |
| `scale_mod_size` | `INT NOT NULL` |
| `multiplicative_depth` | `INT NOT NULL` |
| `scaling_technique` | `VARCHAR(64) NOT NULL` |
| `keyswitch_technique` | `VARCHAR(64) NOT NULL` |
| `ckks_data_type` | `VARCHAR(32) NOT NULL` |
| `ind_cpa_noise_bits` | `INT NOT NULL` |
| `created_at` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |

Constraints:

| Name | Definition |
| --- | --- |
| `fk_crypto_audit_job` | `nvflare_job_id` references `nvflare_jobs(nvflare_assigned_id)` |

Used by `CryptoAuditManager` and `/nvflare/jobs/audit/submit`.

### `nvflare_job_functions`

Maps jobs to selected functions.

| Column | Definition |
| --- | --- |
| `job_id` | `INT NOT NULL` |
| `function_id` | `INT NOT NULL` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(job_id, function_id)` |
| `fk_nvjfunc_job` | `job_id` references `nvflare_jobs(id)` with `ON DELETE CASCADE` |
| `fk_nvjfunc_func` | `function_id` references `defined_functions(id)` with `ON DELETE RESTRICT` |
| `idx_job_id` | `(job_id)` |
| `idx_function_id` | `(function_id)` |

Used by `NVFlareJobsManager` and `FunctionsManager`.

### `nvflare_job_function_configs`

Maps jobs to selected function config sets and optional workflow IDs.

| Column | Definition |
| --- | --- |
| `job_id` | `INT NOT NULL` |
| `function_config_id` | `INT NOT NULL` |
| `workflow_id` | `VARCHAR(255) DEFAULT NULL` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(job_id, function_config_id)` |
| `fk_njfc_job` | `job_id` references `nvflare_jobs(id)` with `ON DELETE CASCADE` |
| `fk_njfc_fn_cfg` | `function_config_id` references `defined_function_config_sets(id)` with `ON DELETE RESTRICT` |
| `uq_job_workflow` | Unique key on `(job_id, workflow_id)` |
| `idx_njfc_workflow` | `(workflow_id)` |

Used by `NVFlareJobsManager`, `FunctionsManager`, and `NVFlareJobsDataRetriever`.

### `users`

Stores backend users.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `username` | `VARCHAR(50) NOT NULL UNIQUE` |
| `password_hash` | `VARCHAR(255) NOT NULL` |
| `role_id` | `INT NOT NULL` |
| `create_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints:

| Name | Definition |
| --- | --- |
| Foreign key | `role_id` references `defined_roles(id)` |

Used by `UsersManager`, `ParticipationManager`, startup test-user seeding, startup deployed-client user seeding, and user FHIR source assignment.

### `nvflare_clients`

Maps NVFlare client names to backend users.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `client_name` | `VARCHAR(100) NOT NULL UNIQUE` |
| `user_id` | `INT NOT NULL` |
| `description` | `TEXT` |
| `create_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Foreign key | `user_id` references `users(id)` |
| `idx_user_id` | `(user_id)` |

Used by `ParticipationManager`, `NVFlareClientSnapshot`-related flows, project client exclusions, and startup deployed-client seeding.

### `nvflare_project_client_exclusions`

Stores excluded clients per project.

| Column | Definition |
| --- | --- |
| `project_id` | `INT NOT NULL` |
| `client_id` | `INT NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(project_id, client_id)` |
| `fk_npce_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `fk_npce_client` | `client_id` references `nvflare_clients(id)` with `ON DELETE CASCADE` |
| `idx_npce_client` | `(client_id)` |

Currently created by startup schema. It is included in `MySQLTable.PROJECT_CLIENT_EXCLUSIONS`.

### `nvflare_client_participation`

Stores client participation decisions for a filter/threshold context.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `client_id` | `INT NOT NULL` |
| `filter_id` | `INT NOT NULL` |
| `threshold_config_id` | `INT NULL` |
| `confirmation` | `ENUM('PENDING','ACCEPT','REJECT') NOT NULL DEFAULT 'PENDING'` |
| `contributing_party` | `TINYINT(1) NOT NULL DEFAULT 1` |
| `analyzing_party` | `TINYINT(1) NOT NULL DEFAULT 1` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `uq_client_filter` | Unique key on `(client_id, filter_id)` |
| `fk_ncp_client` | `client_id` references `nvflare_clients(id)` with `ON DELETE CASCADE` |
| `fk_ncp_filter` | `filter_id` references `defined_fhir_filters(id)` with `ON DELETE CASCADE` |
| `fk_ncp_threshold` | `threshold_config_id` references `threshold_configs(id)` with `ON DELETE SET NULL` |
| `idx_ncp_threshold` | `(threshold_config_id)` |
| `idx_ncp_filter_confirmation_threshold` | `(filter_id, confirmation, threshold_config_id, id, client_id)` |

Used by `ParticipationManager` for pending/accepted/rejected participation state, contributing-party state, analyzing-party state, and function/config mappings.

### `nvflare_client_participation_functions`

Maps participation records to functions.

| Column | Definition |
| --- | --- |
| `participation_id` | `INT NOT NULL` |
| `function_id` | `INT NOT NULL` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(participation_id, function_id)` |
| `fk_ncpf_participation` | `participation_id` references `nvflare_client_participation(id)` with `ON DELETE CASCADE` |
| `fk_ncpf_function` | `function_id` references `defined_functions(id)` with `ON DELETE RESTRICT` |
| `idx_ncpf_function` | `(function_id)` |

Used by `ParticipationManager`.

### `nvflare_client_participation_function_configs`

Maps participation records to function config sets.

| Column | Definition |
| --- | --- |
| `participation_id` | `INT NOT NULL` |
| `function_config_id` | `INT NOT NULL` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(participation_id, function_config_id)` |
| `fk_npfc_part` | `participation_id` references `nvflare_client_participation(id)` with `ON DELETE CASCADE` |
| `fk_npfc_fn_cfg` | `function_config_id` references `defined_function_config_sets(id)` with `ON DELETE RESTRICT` |
| `idx_npfc_part` | `(participation_id)` |
| `idx_npfc_fn_cfg` | `(function_config_id)` |

Used by `ParticipationManager`.

### `defined_project_datasource_groups`

Stores named datasource groups per project.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `project_id` | `INT NOT NULL` |
| `group_name` | `VARCHAR(255) NOT NULL` |
| `is_default` | `TINYINT(1) NOT NULL DEFAULT 0` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_pdg_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `uq_pdg_project_group_name` | Unique key on `(project_id, group_name)` |
| `idx_pdg_project` | `(project_id)` |
| `idx_pdg_is_default` | `(is_default)` |

Used by `ProjectsManager`, `UsersManager`, `NVFlareJobsManager`, startup datasource group seeding, and user FHIR source assignment.

### `defined_project_workflow_groups`

Stores selectable workflow group definitions per project.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `project_id` | `INT NOT NULL` |
| `group_key` | `VARCHAR(100) NOT NULL` |
| `group_label` | `VARCHAR(255) NOT NULL` |
| `group_description` | `TEXT NULL` |
| `min_selected` | `INT NOT NULL DEFAULT 0` |
| `max_selected` | `INT NULL` |
| `is_required` | `TINYINT(1) NOT NULL DEFAULT 0` |
| `page_order` | `INT NOT NULL DEFAULT 0` |
| `status` | `ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE'` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_dpwg_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `uq_dpwg_project_group_key` | Unique key on `(project_id, group_key)` |
| `idx_dpwg_project` | `(project_id)` |
| `idx_dpwg_project_order` | `(project_id, page_order)` |

Used by `ProjectsManager`, `NVFlareJobsManager`, startup workflow group seeding, and job workflow logging.

### `defined_project_workflow_group_options`

Stores selectable options under a workflow group.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `workflow_group_id` | `INT NOT NULL` |
| `option_key` | `VARCHAR(100) NOT NULL` |
| `option_label` | `VARCHAR(255) NOT NULL` |
| `option_value` | `VARCHAR(255) NOT NULL` |
| `option_order` | `INT NOT NULL DEFAULT 0` |
| `option_description` | `TEXT NULL` |
| `is_default` | `TINYINT(1) NOT NULL DEFAULT 0` |
| `status` | `ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE'` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_dpwgo_group` | `workflow_group_id` references `defined_project_workflow_groups(id)` with `ON DELETE CASCADE` |
| `uq_dpwgo_group_option_key` | Unique key on `(workflow_group_id, option_key)` |
| `uq_dpwgo_group_option_value` | Unique key on `(workflow_group_id, option_value)` |
| `idx_dpwgo_group_order` | `(workflow_group_id, option_order)` |

Used by `ProjectsManager`, `NVFlareJobsManager`, startup workflow group option seeding, and job workflow option logging.

### `users_fhir_source_by_project`

Stores the FHIR source or local JSON source assigned to a user for a project and optional datasource group.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `user_id` | `INT NOT NULL` |
| `project_id` | `INT NOT NULL` |
| `source` | `VARCHAR(1024) NOT NULL` |
| `datasource_group` | `INT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_ufsbp_user` | `user_id` references `users(id)` with `ON DELETE CASCADE` |
| `fk_ufsbp_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `fk_ufsbp_datasource_group` | `datasource_group` references `defined_project_datasource_groups(id)` with `ON DELETE SET NULL` |
| `uq_ufsbp_user_project_group` | Unique key on `(user_id, project_id, datasource_group)` |
| `idx_ufsbp_project` | `(project_id)` |
| `idx_ufsbp_project_user` | `(project_id, user_id)` |
| `idx_ufsbp_user` | `(user_id)` |
| `idx_ufsbp_datasource_group` | `(datasource_group)` |

Used by `UsersManager`, `ProjectsManager` datasource flows, `LandingPageManager` registered-user counts, and startup user FHIR source seeding.

### `nvflare_job_datasource_log`

Stores the datasource group selected for a submitted NVFlare job.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `nvflare_job_id` | `INT NOT NULL` |
| `project_id` | `INT NOT NULL` |
| `datasource_group_id` | `INT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_nvjdl_job` | `nvflare_job_id` references `nvflare_jobs(id)` with `ON DELETE CASCADE` |
| `fk_nvjdl_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE` |
| `fk_nvjdl_datasource_group` | `datasource_group_id` references `defined_project_datasource_groups(id)` with `ON DELETE SET NULL` |
| `uq_nvjdl_job` | Unique key on `(nvflare_job_id)` |
| `idx_nvjdl_project` | `(project_id)` |
| `idx_nvjdl_datasource_group` | `(datasource_group_id)` |

Used by `NVFlareJobsManager` during job creation/history flows.

### `nvflare_job_workflow_groups`

Stores workflow group selections attached to an NVFlare job.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `nvflare_job_id` | `INT NOT NULL` |
| `workflow_group_id` | `INT NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_nvjwg_job` | `nvflare_job_id` references `nvflare_jobs(id)` with `ON DELETE CASCADE` |
| `fk_nvjwg_group` | `workflow_group_id` references `defined_project_workflow_groups(id)` with `ON DELETE CASCADE` |
| `uq_nvjwg_job_group` | Unique key on `(nvflare_job_id, workflow_group_id)` |
| `idx_nvjwg_job` | `(nvflare_job_id)` |
| `idx_nvjwg_group` | `(workflow_group_id)` |

Used by `NVFlareJobsManager` during job creation/history flows.

### `nvflare_job_workflow_group_options`

Stores selected workflow group options attached to an NVFlare job workflow group row.

| Column | Definition |
| --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `nvflare_job_workflow_group_id` | `INT NOT NULL` |
| `workflow_group_option_id` | `INT NOT NULL` |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `fk_njvwgo_job_group` | `nvflare_job_workflow_group_id` references `nvflare_job_workflow_groups(id)` with `ON DELETE CASCADE` |
| `fk_njvwgo_option` | `workflow_group_option_id` references `defined_project_workflow_group_options(id)` with `ON DELETE CASCADE` |
| `uq_njvwgo_group_option` | Unique key on `(nvflare_job_workflow_group_id, workflow_group_option_id)` |
| `idx_njvwgo_job_group` | `(nvflare_job_workflow_group_id)` |
| `idx_njvwgo_option` | `(workflow_group_option_id)` |

Used by `NVFlareJobsManager` during job creation/history flows.

## Default Seed Data

### Supported Functions

Startup inserts these rows into `defined_functions` when missing:

| Function | Description |
| --- | --- |
| `SURVIVAL_ANALYSIS` | Runs survivability analysis using filtered patient data from all clients. |
| `CHI_SQUARE_TEST` | Statistical test for association between categorical variables. |
| `STANDARD_DEVIATION` | The spread of individual measurements around the mean. |
| `MEAN` | Summarize continuous variables such as average age, lab measurement mean, and variation across sites. |
| `T_TEST` | Compare means of two groups. |
| `ENCRYPTED_FILTERING` | Applies filters securely in encrypted form. |
| `COUNT` | Returns the number of records matching the selected filters. |
| `LOGISTIC_CALIBRATION_STATISTICS` | Compares predicted probabilities to real-world outcomes, helping with reliable risk assessment. |

`SupportedFunction.PARTICIPATION_CONFIRMATION` exists in the enum and is included in the General Statistics project restrictions, but it is not currently part of the `required_functions` insertion map in `_ensure_default_functions_exist()`.

### Default Function Config Properties

Startup inserts default rows into `defined_function_config_properties` for functions that have entries in `FUNCTION_DEFAULT_PROPERTIES`.

| Function | Default properties |
| --- | --- |
| `SURVIVAL_ANALYSIS` | `group_column_id=PBRM1`, `time_column_id=OS`, `censoring_column_id=OS_CNSR`, `time_grid_min=0`, `time_grid_step=0.1`, `time_grid_max=62`, `CI_type=None` |
| `CHI_SQUARE_TEST` | `category_column_1_id=PBRM1`, `category_column_2_id=gender` |
| `MEAN` | `data_column_id=Age` |
| `STANDARD_DEVIATION` | `data_column_id=Age`, `std_type=population` |
| `T_TEST` | `data_column_id=Age`, `category_column_1_id=PBRM1` |

### Roles

Startup inserts these rows into `defined_roles` when missing:

| Role | Description |
| --- | --- |
| `INITIATOR` | A user who initiates NVFlare jobs. |
| `CLIENT` | A user who runs NVFlare client jobs. |
| `OBSERVER` | A user who is not a client, and can view results of jobs. |
| `ADMIN` | Administrative user who can approve registration of new client machines, view results, initiate jobs. |

### Filter Systems

Startup inserts these rows into `defined_filter_system` when missing:

| Filter system | Description |
| --- | --- |
| `DEFAULT` | General analysis filter system tied to broad FHIR observation data. |
| `CANCER_TYPE` | Filter system focused on known cancer types, utilized in biomarker pipeline. |

Startup inserts these allowed filter types into `defined_filter_system_allowed_filter_types`:

| Filter system | Allowed filter types |
| --- | --- |
| `DEFAULT` | `PATIENT_QUERY`, `PATIENT_DATA`, `OBSERVATION` |
| `CANCER_TYPE` | `PATIENT_DATA` |

### Projects

Startup upserts two projects.

| Project | Status | Fixed | Function restrictions | Filter system |
| --- | --- | --- | --- | --- |
| `General Statistics` | `ACTIVE` | `1` | Enabled | `DEFAULT` |
| `Biomarker Model Validation for Cancer Prognosis` | `ACTIVE` | `1` | Enabled | `CANCER_TYPE` |

`General Statistics` is restricted to these functions if the function rows exist:

- `SURVIVAL_ANALYSIS`
- `CHI_SQUARE_TEST`
- `MEAN`
- `STANDARD_DEVIATION`
- `PARTICIPATION_CONFIRMATION`
- `T_TEST`
- `ENCRYPTED_FILTERING`
- `COUNT`

`Biomarker Model Validation for Cancer Prognosis` is restricted to:

- `SURVIVAL_ANALYSIS`
- `LOGISTIC_CALIBRATION_STATISTICS`

For the biomarker project, startup stores fixed, variable, and override config JSON for `SURVIVAL_ANALYSIS` in `defined_project_function_restrictions`.

Fixed config:

```json
{
  "is_server_contributing_to_aggregation": false,
  "is_biomarker_discovery": true,
  "model_key": "cox_lasso"
}
```

Variable config:

```json
{
  "cancer_type": {
    "type": "str",
    "default": "$PATIENT_DATA_CANCER_TYPE",
    "description": "Selected cancer type on Patient filter screen."
  },
  "model_type": {
    "type": "select",
    "options": ["Open-access", "Encrypted"],
    "default": "Encrypted",
    "description": "Open-access model: The training institution shares the model in the clear with all participants and computing server.\n\rEncrypted model: The training institution encrypts the model and neither the participants nor the computing server can retrieve the model weights."
  }
}
```

Override config:

```json
{
  "group_column_id": "risk_score_group",
  "time_column_id": "time",
  "censoring_column_id": "event",
  "time_grid_step": 1,
  "time_grid_max": 110
}
```

### Test Users

Startup inserts these users with `password_hash='DISABLED'` if the matching roles exist:

| Username | Role |
| --- | --- |
| `client` | `CLIENT` |
| `initiator` | `INITIATOR` |
| `observer` | `OBSERVER` |

### Default NVFlare Clients

Startup only inserts default NVFlare clients when `EnvironmentProvider.get_env()` is not `Environment.LOCAL`.

| NVFlare client | Username | Role | Description |
| --- | --- | --- | --- |
| `site1` | `client_site1` | `CLIENT` | `Auto-created for site1` |
| `site2` | `client_site2` | `CLIENT` | `Auto-created for site2` |
| `site3` | `initiator` | `INITIATOR` | `Auto-created for site3/intiiator` |

The startup routine creates the backing user if it does not already exist, then upserts the `nvflare_clients` row.

### Default Datasource Groups

Startup seeds datasource groups for `Biomarker Model Validation for Cancer Prognosis`.

| Group | `is_default` |
| --- | --- |
| `MSKChord` | `1` |

Fresh public installs seed only MSKChord. Because it is the first and only datasource group, its fresh-install datasource-group id is `1`. When upgrading an existing database, startup also normalizes the legacy group spelling in place, so an existing row keeps its current id:

| Existing name | Current name |
| --- | --- |
| `MSK_Chord` | `MSKChord` |

After upserting the groups, startup sets `MSKChord` as the only default group for the biomarker project.

### Default Workflow Group

Startup seeds one workflow group for `Biomarker Model Validation for Cancer Prognosis`.

| Field | Value |
| --- | --- |
| `group_key` | `predictive_modeling_method_ids` |
| `group_label` | `Predictive Model Configuration` |
| `group_description` | `Select one or more predictive models to invoke.` |
| `min_selected` | `1` |
| `max_selected` | `NULL` |
| `is_required` | `1` |
| `page_order` | `0` |
| `status` | `ACTIVE` |

Startup seeds two options under that group:

| Option key | Label | Value | Order | Default | Status |
| --- | --- | --- | --- | --- | --- |
| `cox_lasso` | `Lasso Cox Regression` | `cox_lasso` | `0` | `0` | `ACTIVE` |
| `logistic_reg` | `Lasso Logistic Regression` | `logistic_reg` | `1` | `0` | `ACTIVE` |

### Default User FHIR Sources

Startup seeds source assignments into `users_fhir_source_by_project`.

For `General Statistics`:

| Username | Source | Datasource group |
| --- | --- | --- |
| `client_site1` | `/data/client/Survivability_FHIR_Data_part2.json` | `NULL` |
| `client_site2` | `/data/client/Survivability_FHIR_Data_part3.json` | `NULL` |
| `initiator` | `/data/client/Survivability_FHIR_Data_part1.json` | `NULL` |

For `Biomarker Model Validation for Cancer Prognosis`:

| Username | Source | Datasource group |
| --- | --- | --- |
| `client_site1` | `Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json` | `MSKChord` |
| `client_site2` | `Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json` | `MSKChord` |
| `initiator` | `Biomarker_MSKChord_FHIR_Data_training_bundle.json` | `MSKChord` |

When a source has no datasource group, startup keeps a single `(user_id, project_id, NULL)` row and deletes duplicate NULL-group rows for that user/project. When a datasource group is present, startup uses `ON DUPLICATE KEY UPDATE` against `(user_id, project_id, datasource_group)`.

## Manager and Job-Tracking Usage Map

| Table | Main current users |
| --- | --- |
| `defined_filter_system` | `ProjectsManager`, startup filter-system/project seeding |
| `defined_filter_system_allowed_filter_types` | `ProjectsManager`, startup filter-system seeding |
| `defined_projects` | `ProjectsManager`, `FiltersManager`, `NVFlareJobsManager`, startup project/datasource/workflow seeding |
| `defined_roles` | `UsersManager`, `RolesManager`, `ParticipationManager`, startup role/user/client seeding |
| `job_runner_log` | `JobStatusWriter`, `JobStatusRetriever` |
| `defined_functions` | `FunctionsManager`, `ProjectsManager`, `NVFlareJobsManager`, `NVFlareJobsDataRetriever`, startup function/project seeding |
| `defined_project_function_restrictions` | `ProjectsManager`, startup project seeding |
| `defined_function_config_properties` | `FunctionsManager`, `NVFlareJobsManager`, `NVFlareJobsDataRetriever`, startup function property seeding |
| `defined_function_config_sets` | `FunctionsManager`, `NVFlareJobsManager`, `ParticipationManager`, `NVFlareJobsDataRetriever` |
| `defined_function_config_set_members` | `FunctionsManager`, `NVFlareJobsManager`, `NVFlareJobsDataRetriever` |
| `defined_fhir_filters` | `FiltersManager`, `MySQLRetriever`, `NVFlareJobsManager`, `ParticipationManager` |
| `defined_fhir_filter_conditions` | `FiltersManager`, `MySQLRetriever` |
| `threshold_configs` | `ThresholdManager`, `MySQLRetriever`, `NVFlareJobsManager`, `ParticipationManager` |
| `nvflare_jobs` | `NVFlareJobsManager`, `NVFlareJobsDataRetriever`, `JobStatusRetriever`, `NVFlareClientEmitManager`, `CryptoAuditManager` |
| `nvflare_job_crypto_audit` | `CryptoAuditManager` |
| `nvflare_job_functions` | `NVFlareJobsManager`, `FunctionsManager` |
| `nvflare_job_function_configs` | `NVFlareJobsManager`, `FunctionsManager`, `NVFlareJobsDataRetriever` |
| `users` | `UsersManager`, `ParticipationManager`, startup user/client/source seeding |
| `nvflare_clients` | `ParticipationManager`, startup client seeding |
| `nvflare_project_client_exclusions` | Created by startup schema and exposed through `MySQLTable.PROJECT_CLIENT_EXCLUSIONS` |
| `nvflare_client_participation` | `ParticipationManager` |
| `nvflare_client_participation_functions` | `ParticipationManager` |
| `nvflare_client_participation_function_configs` | `ParticipationManager` |
| `defined_project_datasource_groups` | `ProjectsManager`, `UsersManager`, `NVFlareJobsManager`, startup datasource/source seeding |
| `defined_project_workflow_groups` | `ProjectsManager`, `NVFlareJobsManager`, startup workflow seeding |
| `defined_project_workflow_group_options` | `ProjectsManager`, `NVFlareJobsManager`, startup workflow option seeding |
| `users_fhir_source_by_project` | `UsersManager`, project datasource resolution, startup source seeding |
| `nvflare_job_datasource_log` | `NVFlareJobsManager` |
| `nvflare_job_workflow_groups` | `NVFlareJobsManager` |
| `nvflare_job_workflow_group_options` | `NVFlareJobsManager` |

## Schema Change Guidance

Current schema definitions live in `create_tables_str` inside `app/core/mysql/MySQLConnectionProvider.py`.

Current default data lives in methods on `MySQLConnectionProvider`:

| Method | Responsibility |
| --- | --- |
| `_ensure_default_functions_exist()` | Inserts function rows and default function config properties. |
| `_ensure_default_roles_exist()` | Inserts role rows. |
| `_ensure_default_filter_systems_exist()` | Inserts filter systems and allowed filter types. |
| `_ensure_default_projects_exist()` | Inserts/updates project rows and project/function restrictions. |
| `_ensure_test_users_exist()` | Inserts local/test users. |
| `_ensure_default_nvflare_clients()` | Inserts deployed default users and NVFlare clients when not local. |
| `_ensure_default_defined_project_datasource_groups()` | Inserts/updates datasource groups for the biomarker project. |
| `_ensure_default_project_workflow_groups()` | Inserts/updates workflow group and options for the biomarker project. |
| `_ensure_default_user_fhir_sources()` | Inserts/updates user/project/source mappings. |

Current schema enforcement outside `CREATE TABLE IF NOT EXISTS` lives in:

| Method | Responsibility |
| --- | --- |
| `_ensure_users_fhir_source_by_project_schema()` | Ensures `id`, `datasource_group`, unique key, indexes, and datasource group FK exist. |
| `_ensure_participation_lookup_indexes()` | Ensures lookup indexes for participation and function config property queries. |

When adding or changing backend schema in this codebase:

1. Update the create-table definition in `create_tables_str`.
2. Update `MySQLTable.py` when manager code should reference the table through the enum.
3. Update manager/job-tracking SQL in the same change.
4. Update seed methods when the table requires default rows.
5. Verify foreign key creation order in `create_tables_str`.
6. Verify startup remains idempotent. Existing seed logic uses `INSERT ... WHERE NOT EXISTS`, `ON DUPLICATE KEY UPDATE`, or explicit existence checks depending on the table.
7. Verify affected API responses and frontend assumptions when changing project, datasource, workflow group, function, filter, or job-history tables.

## Troubleshooting

| Symptom | Likely area to check |
| --- | --- |
| Backend fails before table creation | MySQL secret/config returned by `ResourceConfigProvider.get_mysql_config(check_cached=False)`, raw MySQL connectivity, database host/port/user/password. |
| Database exists but tables are missing | `create_tables_if_not_exists()`, SQL error printed from `MySQLConnectionProvider`, permissions for `CREATE TABLE`. |
| Startup fails on foreign key creation | Table creation order, referenced table existence, referenced column type, storage engine, existing incompatible table shape. |
| User datasource lookup fails | `users`, `defined_projects`, `defined_project_datasource_groups`, and `users_fhir_source_by_project` seed rows. |
| Biomarker project does not show modeling method options | `defined_project_workflow_groups` and `defined_project_workflow_group_options` seed rows. |
| Job history lacks datasource/workflow metadata | `nvflare_job_datasource_log`, `nvflare_job_workflow_groups`, and `nvflare_job_workflow_group_options` rows written by `NVFlareJobsManager`. |
| Participation lookup is slow | `idx_ncp_filter_confirmation_threshold` on `nvflare_client_participation` and `idx_dfcp_name_value` on `defined_function_config_properties`. |
| Function config lookup is missing expected defaults | `defined_functions`, `defined_function_config_properties`, and `SupportedFunction.FUNCTION_DEFAULT_PROPERTIES`. |


## Runtime Datasource Seed Values

`MySQLConnectionProvider._ensure_default_user_fhir_sources()` seeds datasource rows in `users_fhir_source_by_project`. The seeded string is environment-specific only for the actual datasource value stored in that table.

| Environment | Biomarker datasource string behavior |
| --- | --- |
| `LOCAL` | Stores client-container runtime paths under `/data/client/<filename>.json`. |
| `DEV` and other non-local defaults | Stores the existing development WorkSpaces paths under `/path/to/site1/fhir_data`, `/path/to/site2/fhir_data`, and `/path/to/initiator/fhir_data`. |

The local values are:

| User | Group | Source |
| --- | --- | --- |
| `client_site1` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json` |
| `client_site2` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json` |
| `initiator` | `MSKChord` | `/data/client/Biomarker_MSKChord_FHIR_Data_training_bundle.json` |

`_ensure_default_nvflare_clients()` still runs for both `LOCAL` and `DEV` so `site1`, `site2`, and `site3` are present in `nvflare_clients`. `site3` maps to the `initiator` user.

`_ensure_default_user_fhir_sources()` inserts a new datasource history row only when the latest row for the same user/project/group differs from the expected source.
