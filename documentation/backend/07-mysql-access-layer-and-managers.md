# MySQL Access Layer and Managers

## Files Covered

| File/Directory | Role |
| --- | --- |
| `app/core/mysql/MySQLConnectionProvider.py` | Singleton connection provider, connection-pool creation, database creation, schema creation, schema compatibility checks, index checks, and default data seeding. |
| `app/core/mysql/MySQLRetriever.py` | Shared SELECT helper for defined FHIR filters and filter conditions. |
| `app/core/mysql/MySQLTable.py` | Enum of table names used by managers, retrievers, and job tracking classes. |
| `app/core/mysql/SupportedFunction.py` | Supported backend function enum plus default function configuration metadata. |
| `app/core/mysql/SupportedFilterSystem.py` | Supported filter system enum. |
| `app/core/mysql/UserRole.py` | User role enum. |
| `app/core/mysql/managers/` | Application-facing database manager classes. |
| `app/core/mysql/job_tracking/` | Job log/status reader and writer classes plus NVFlare result-data retriever. |

## Access Layer Shape

The backend MySQL access layer is organized around four layers:

1. `MySQLConnectionProvider` owns database bootstrapping and pooled connection creation.
2. `MySQLTable`, `SupportedFunction`, `SupportedFilterSystem`, and `UserRole` centralize table and enum names used by the data layer.
3. Manager classes under `app/core/mysql/managers/` provide application-facing read/write operations for users, roles, projects, functions, filters, thresholds, jobs, participation, client progress emission, and crypto audit logging.
4. Job tracking classes under `app/core/mysql/job_tracking/` read and write job execution status and retrieve NVFlare result/config artifacts.

Route files and job services generally call managers or retrievers rather than embedding database behavior directly. There are still a few direct SQL access points in route/job code, most notably in `JobRunnerRoutes.py` for result mapping/status support and in NVFlare job helper classes for staging and upload behavior.

## Connection Ownership and Cleanup Pattern

Most manager/retriever classes follow the same lifecycle:

1. Constructor calls `MySQLConnectionProvider.get_instance().get_connection()`.
2. Constructor opens a `MySQLdb.cursors.DictCursor`.
3. Public methods execute SQL through that cursor.
4. Caller is expected to call `complete()` in a `finally` block.
5. `complete()` closes the cursor and then closes the pooled connection handle.

Classes following this pattern include:

- `UsersManager`
- `RolesManager`
- `ProjectsManager`
- `FunctionsManager`
- `FiltersManager`
- `ThresholdManager`
- `NVFlareJobsManager`
- `ParticipationManager`
- `NVFlareClientEmitManager`
- `CryptoAuditManager`
- `MySQLRetriever`
- `JobStatusRetriever`
- `JobStatusWriter`

`NVFlareJobsDataRetriever` is different: it does not hold a long-lived MySQL connection in the constructor. It reads result files from local or remote job output paths and opens a short-lived MySQL connection only when it needs to fetch function configuration for a workflow.

## `MySQLConnectionProvider.py`

`MySQLConnectionProvider` is the central MySQL bootstrap and connection factory.

### Constructor Behavior

`MySQLConnectionProvider` is a singleton. `get_instance()` creates one process-local provider and reuses it for later calls.

During initialization, the provider:

1. Reads MySQL connection settings from `ResourceConfigProvider.get_mysql_config(check_cached=False)`.
2. Ensures the configured database exists by opening a raw MySQL connection and executing `CREATE DATABASE IF NOT EXISTS`.
3. Builds a `dbutils.pooled_db.PooledDB` pool with:
   - `maxconnections=150`
   - `mincached=15`
   - `maxcached=45`
   - `blocking=True`
   - `autocommit=True`
   - `client_flag=CLIENT.MULTI_STATEMENTS`
   - `cursorclass=MySQLdb.cursors.DictCursor`
   - `ping=1`
4. Runs `create_tables_if_not_exists()` against the SQL string defined in the same file.
5. Runs compatibility checks for `users_fhir_source_by_project`.
6. Ensures participation lookup indexes exist.
7. Seeds supported functions, roles, filter systems, projects, test users, datasource groups, workflow groups, and user FHIR source mappings.
8. Seeds default NVFlare clients only when the runtime environment is not `LOCAL`.

### Public Methods

| Method | Purpose |
| --- | --- |
| `get_instance()` | Returns the singleton provider. |
| `get_connection()` | Returns a pooled MySQL connection. If the pool fails, rebuilds the pool and retries once. |
| `rebuild_pool()` | Refreshes MySQL secret/config values and rebuilds the `PooledDB` pool. |
| `create_tables_if_not_exists(connection)` | Executes the semicolon-delimited schema creation string. |

### Schema and Seed Responsibilities

`MySQLConnectionProvider` creates or maintains the database tables used by the backend. It also inserts required default rows for supported functions, roles, filter systems, projects, datasource groups, workflow groups, test users, FHIR sources, and NVFlare clients.

Schema creation and seed details are documented in `06-database-initialization-and-schema.md`.

### Error and Transaction Behavior

- Raw database creation retries after forcing a secret refresh when the first raw connection attempt fails.
- `get_connection()` rebuilds the pool after an unexpected connection-pool error.
- `create_tables_if_not_exists()` catches `MySQLdb.MySQLError`, prints the failed statement and error, and closes the cursor.
- Seed and compatibility methods call `connection.commit()` after their changes and close their cursors/connections in `finally` blocks.

## `MySQLTable.py`

`MySQLTable` is a string enum of table names used across the data layer.

| Enum | Table |
| --- | --- |
| `PROJECTS` | `defined_projects` |
| `USER_ROLES` | `defined_roles` |
| `JOB_RUNNER_LOG` | `job_runner_log` |
| `FUNCTIONS` | `defined_functions` |
| `FUNCTION_CONFIG_PROPERTIES` | `defined_function_config_properties` |
| `FUNCTION_CONFIG_SETS` | `defined_function_config_sets` |
| `FUNCTION_CONFIG_SET_MEMBERS` | `defined_function_config_set_members` |
| `FHIR_FILTERS` | `defined_fhir_filters` |
| `FHIR_FILTER_CONDITIONS` | `defined_fhir_filter_conditions` |
| `NVFLARE_JOBS` | `nvflare_jobs` |
| `NVFLARE_JOB_FUNCTIONS` | `nvflare_job_functions` |
| `NVFLARE_JOB_FUNCTION_CONFIGS` | `nvflare_job_function_configs` |
| `NVFLARE_JOB_CRYPTO_AUDIT` | `nvflare_job_crypto_audit` |
| `USERS` | `users` |
| `CLIENTS` | `nvflare_clients` |
| `PROJECT_CLIENT_EXCLUSIONS` | `nvflare_project_client_exclusions` |
| `PARTICIPATION` | `nvflare_client_participation` |
| `PARTICIPATION_FUNCTIONS` | `nvflare_client_participation_functions` |
| `PARTICIPATION_FUNCTION_CONFIGS` | `nvflare_client_participation_function_configs` |
| `THRESHOLD_CONFIGS` | `threshold_configs` |

Several newer tables are referenced directly by string in manager code instead of through `MySQLTable`, including datasource group, workflow group, filter system, and job workflow/datasource log tables.

## `MySQLRetriever.py`

`MySQLRetriever` is a thin SELECT-only helper for filter lookup.

### Constructor and Cleanup

- Opens a pooled connection and dict cursor in `__init__()`.
- `complete()` closes the cursor and connection.

### Public Methods

| Method | Reads | Purpose |
| --- | --- | --- |
| `get_all_filters(project_id)` | `defined_fhir_filters`, `defined_fhir_filter_conditions` | Returns all filters for a project, including decoded condition values. |
| `get_single_filter(filter_id)` | `defined_fhir_filters`, `defined_fhir_filter_conditions` | Returns one filter and its conditions. |
| `stage_filters_by_id(filter_id)` | `defined_fhir_filters`, `defined_fhir_filter_conditions` | Returns staged condition data for a persisted filter ID. |

### Callers

- `FilterRoutes.py` uses it for filter fetch endpoints.
- `NVFlareJobStager.py` uses it when staging job inputs.
- `NVFlareJobUploader.py` imports it for NVFlare upload-related workflows.

### Behavior Notes

- Filter condition values are stored as CSV-encoded strings and decoded on read.
- Missing filters return empty or `None` style responses depending on the method path used by the caller.
- This class does not write to MySQL.

## Manager Summary

| Manager | Primary Responsibility | Main Tables Read | Main Tables Written |
| --- | --- | --- | --- |
| `UsersManager` | User role, user ID, and user/project datasource lookup. | `users`, `defined_roles`, `users_fhir_source_by_project`, `defined_project_datasource_groups`, `defined_projects` | None |
| `RolesManager` | Resolve role ID to role name. | `defined_roles` | None |
| `ProjectsManager` | Return project definitions, function restrictions, filter systems, datasource groups, and workflow groups. | `defined_projects`, `defined_filter_system`, `defined_filter_system_allowed_filter_types`, `defined_project_function_restrictions`, `defined_functions`, `defined_project_datasource_groups`, `defined_project_workflow_groups`, `defined_project_workflow_group_options` | None |
| `LandingPageManager` | Read-only global Home aggregates and optimized project landing summaries/recent jobs. | `nvflare_jobs`, `defined_roles`, `users`, `defined_functions`, `defined_projects`, `defined_filter_system`, `users_fhir_source_by_project`, project function/datasource-group tables, recent-job function/config tables | None |
| `FunctionsManager` | Resolve supported functions, normalize function maps, create/reuse function config sets, link jobs to functions/configs. | `defined_functions`, `defined_function_config_properties`, `defined_function_config_sets`, `defined_function_config_set_members`, `nvflare_job_functions`, `nvflare_job_function_configs` | `defined_function_config_properties`, `defined_function_config_sets`, `defined_function_config_set_members`, `nvflare_job_functions`, `nvflare_job_function_configs` |
| `FiltersManager` | Normalize, hash, reuse, and persist FHIR filters and filter conditions. | `defined_fhir_filters`, `defined_fhir_filter_conditions` | `defined_fhir_filters`, `defined_fhir_filter_conditions` |
| `ThresholdManager` | Validate, reuse, and persist threshold configs. | `threshold_configs` | `threshold_configs` |
| `NVFlareJobsManager` | Create/update NVFlare job records, job context logs, workflow mapping, history retrieval, and audit enrichment. | `nvflare_jobs`, `job_runner_log`, `nvflare_job_functions`, `nvflare_job_function_configs`, `defined_functions`, `defined_function_config_*`, `defined_project_datasource_groups`, `defined_project_workflow_groups`, `defined_project_workflow_group_options`, `nvflare_job_datasource_log`, `nvflare_job_workflow_groups`, `nvflare_job_workflow_group_options`, `nvflare_job_crypto_audit` | `nvflare_jobs`, `threshold_configs`, `nvflare_job_functions`, `nvflare_job_function_configs`, `nvflare_job_datasource_log`, `nvflare_job_workflow_groups`, `nvflare_job_workflow_group_options` |
| `ParticipationManager` | Record and query client participation decisions for filters/functions/configs/thresholds. | `nvflare_clients`, `users`, `defined_roles`, `nvflare_client_participation`, `nvflare_client_participation_functions`, `nvflare_client_participation_function_configs`, `defined_functions`, `defined_function_config_sets`, `threshold_configs` | `nvflare_client_participation`, `nvflare_client_participation_functions`, `nvflare_client_participation_function_configs`, `threshold_configs` |
| `NVFlareClientEmitManager` | Resolve an NVFlare assigned ID to a job runner ID and append client progress/status messages to the job log. | `nvflare_jobs`, `job_runner_log` | `job_runner_log` |
| `CryptoAuditManager` | Insert crypto audit entries for NVFlare jobs. | None | `nvflare_job_crypto_audit` |

## `UsersManager.py`

`UsersManager` handles user lookup and datasource assignment lookup.

### Constructor Behavior

`UsersManager(status_writer=None)` stores the optional status writer, emits a processing log via `safe_status_update()`, then opens a pooled MySQL connection and dict cursor.

### Public Methods

| Method | Purpose |
| --- | --- |
| `validate_login(username)` | Looks up `users.role_id`, resolves the role through `RolesManager`, and returns the role name or `None`. The code comments identify this as not production login logic. |
| `get_user_id_by_username(username)` | Returns the user ID for a username or `None`. |
| `get_fhir_source(user_id, project_id, datasource_group=None)` | Returns only the datasource `source` string from `get_fhir_source_record()`. |
| `get_fhir_source_record(user_id, project_id, datasource_group=None)` | Returns datasource source, group ID, group name, and default-group flag. When no datasource group is supplied, it prefers the default group or legacy `NULL` group row. |
| `get_user_project_datasources(user_id)` | Returns projects and datasource assignments grouped by project for the user. |

### Callers

- `app/main.py` uses `validate_login()` for `POST /user/role`.
- `ProjectRoutes.py` uses user and datasource lookup behavior for `/projects/fhir/source`.
- NVFlare job staging/resolution paths use user datasource information when resolving project-specific FHIR sources.

### Error and Transaction Behavior

`UsersManager` performs read-only queries. It does not commit. It returns `None` when a user, role, or datasource record is not found.

## `RolesManager.py`

`RolesManager` resolves role IDs to role names.

### Constructor and Cleanup

- Opens a pooled connection and dict cursor in `__init__()`.
- `complete()` closes both resources.

### Public Methods

| Method | Purpose |
| --- | --- |
| `get_role_name(role_id)` | Selects `defined_roles.name` for the supplied ID and returns the role name or `None`. |

### Callers

`UsersManager.validate_login()` creates a `RolesManager` to resolve the role ID read from `users`.

## `ProjectsManager.py`

`ProjectsManager` returns project metadata used by the frontend and job setup flow.

### Dataclasses Returned

| Dataclass | Purpose |
| --- | --- |
| `ProjectFunctionCapability` | Function available to a project, whether it is configurable, and any fixed/variable/override config metadata. |
| `FilterSystemInfo` | Filter system name, description, and allowed filter types. |
| `ProjectDatasourceGroup` | Project datasource group ID/name/default flag. |
| `ProjectWorkflowGroupOption` | Selectable workflow-group option. |
| `ProjectWorkflowGroup` | Workflow group definition and its options. |
| `Project` | Full project record returned by project list/detail methods. |

### Public Methods

| Method | Purpose |
| --- | --- |
| `get_defined_project_datasource_groups(project_id)` | Returns datasource groups for a project ordered by default flag and name. |
| `get_default_project_datasource_group(project_id)` | Returns the default datasource group for a project, or the first available group if none is flagged default. |
| `get_project_datasource_group_by_id(project_id, datasource_group_id)` | Returns one datasource group by project and ID. |
| `get_project_datasource_group_summary(project_id)` | Returns datasource group presence, group list, and default group. |
| `get_defined_project_workflow_groups(project_id)` | Returns workflow group definitions and ordered options for a project. |
| `get_project_workflow_group_summary(project_id)` | Returns workflow group presence and group definitions. |
| `get_project_list()` | Returns all active project definitions. |
| `get_project(project_id, datasource_group_id)` | Returns one project definition and selected datasource group context. |

### Internal Methods

| Method | Purpose |
| --- | --- |
| `_safe_json_loads(raw)` | Safely parses JSON object values from DB text/bytes. |
| `_get_filter_system_map()` | Loads filter systems and allowed filter types. |
| `_get_project_functions(project_id, restrictions_enabled)` | Builds function capability records from all supported functions or project restrictions. |
| `_build_project(row, filter_system_map, datasource_group_id)` | Builds a `Project` dataclass from DB rows and supporting maps. |

### Callers

- `ProjectRoutes.py` uses it for `/projects/list` and project datasource behavior.
- `NVFlareJobStager.py` uses it to resolve project configuration during job staging.

### Error and Transaction Behavior

`ProjectsManager` is read-only. It parses invalid or empty JSON configuration fields as `None`. It does not commit.

## `LandingPageManager.py`

`LandingPageManager` provides purpose-built read models for the authenticated SHARE landing environment. It owns a pooled connection and dictionary cursor and exposes `complete()` for cleanup.

### Public Methods

| Method | Purpose |
| --- | --- |
| `get_home_summary()` | Returns grouped job status counts, role/user counts, totals, and the defined function catalog for global Home. |
| `get_project_landing_summary(project_id)` | Returns project metadata, total jobs, distinct registered users, datasource groups/default group, project capabilities, and five recent jobs. Returns `None` for an unknown project. |

### Internal Landing Helpers

The manager includes focused helpers for project function capability retrieval, datasource groups, recent jobs, recent-job function membership, and recent-job function configuration maps. It deliberately does not call the full `NVFlareJobsManager.get_nvflare_jobs()` history path.

### Callers

- `LandingPageRoutes.py` `/landing/home`
- `LandingPageRoutes.py` `/landing/project`

### Error and Transaction Behavior

The manager is read-only. Route handlers close it in `finally` using `complete()`. See `24-landing-page-summary-endpoints.md` for query strategy and response contracts.

## `FunctionsManager.py`

`FunctionsManager` resolves supported functions and persists reusable function configuration sets.

### Constructor Behavior

`FunctionsManager` opens a pooled connection and dict cursor. It also uses the class-level `_function_id_cache` to cache supported-function IDs by uppercased function name.

### Normalization

`normalize_map(functions_map)` accepts function maps in either single-config or list-of-configs shape and returns a normalized `dict[str, list[dict[str, str]]]`:

- Function keys are stripped and uppercased.
- Property keys are stripped.
- `None` property values become empty strings.
- Empty function keys or empty config objects are dropped.

The module-level `_normalize_functions_map(functions)` applies default properties from `SupportedFunction` to incoming function maps and raises `ValueError` if the input is not an object.

### Public Methods

| Method | Purpose |
| --- | --- |
| `get_function_id(function)` | Returns a supported function ID with in-process caching. |
| `get_supported_functions()` | Returns all defined functions with ISO-formatted date fields. |
| `get_function_ids_by_names(names)` | Bulk-resolves function IDs by name. |
| `ensure_functions_exist(names)` | Returns name-to-ID mapping or raises `ValueError` for unknown function names. |
| `link_job_functions(job_id, names)` | Inserts rows into `nvflare_job_functions` for the job and function names. |
| `get_or_create_function_config_property_id(function_id, prop, val)` | Reuses or inserts a function config property row. Handles duplicate insert races by re-querying. |
| `get_or_create_function_config_set_id(function_id, props)` | Hashes a config property set, reuses or inserts the config set, and links member properties. |
| `ensure_configs_and_link(job_id, functions_map)` | Ensures config sets exist and links them to a job through `nvflare_job_function_configs`. |
| `ensure_job_function_config_row(job_id, function_name, props)` | Ensures one concrete job/function config link exists and commits it. |
| `fetch_job_functions(job_ids)` | Returns job ID to set of function names. |
| `fetch_job_function_configs(job_ids)` | Returns job ID to function-name to list of property dictionaries. |

### Callers

- `FunctionRoutes.py` uses `get_supported_functions()`.
- `FilterRoutes.py` imports it for function-aware filter behavior.
- `ClientRoutes.py` uses normalization/manager behavior for participation requests.
- `NVFlareJobsManager` uses function/config tables when creating and retrieving job records.
- Job staging/task code uses function map normalization and supported-function metadata.

### Error and Transaction Behavior

- Unknown function names raise `ValueError` through `ensure_functions_exist()`.
- Empty config properties raise `ValueError` when creating a config set.
- Some insert/link methods rely on autocommit or caller-level commits; `ensure_job_function_config_row()` commits explicitly.
- Duplicate config property insert races are handled by catching `MySQLdb.IntegrityError` and re-selecting the property row.

## `FiltersManager.py`

`FiltersManager` validates, normalizes, hashes, reuses, and persists FHIR filter definitions.

### Constructor Behavior

`FiltersManager(project_id, filters, status_writer=None)` stores the project ID, incoming filters object, and optional status writer. It opens a pooled connection and dict cursor.

### Public Methods

| Method | Purpose |
| --- | --- |
| `save_or_get_filter_id()` | Returns an existing matching filter ID or inserts a new filter and condition rows. |
| `get_id_by_filters()` | Looks for an existing filter by normalized condition signature/hash and exact condition equality. |

### Internal Behavior

| Method | Purpose |
| --- | --- |
| `_csv_encode(items)` / `_csv_decode(s)` | Stores and reads multi-value condition values as CSV text. |
| `_canonicalize_operator(op_in)` | Normalizes operator values. |
| `_validate_and_normalize_conditions(name, conditions)` | Validates filter shape and returns normalized conditions. |
| `_conditions_equal(a, b)` | Compares condition sets for exact reuse. |
| `_build_signature(conditions)` | Builds stable condition representation. |
| `_compute_hash(conditions)` | Hashes normalized condition sets. |
| `_insert_filter(name, hash_val)` | Inserts a row into `defined_fhir_filters`. |
| `_insert_conditions(filter_id, conditions)` | Inserts rows into `defined_fhir_filter_conditions`. |

### Callers

- `ClientRoutes.py` uses it while preparing participation status/submit operations.
- `NVFlareJobTask.py` uses it to save or resolve filters before job creation.
- `NVFlareJobUploader.py` imports it for upload-related flow support.

### Error and Transaction Behavior

- Validation errors are raised for invalid filter payloads.
- New filter and condition inserts commit explicitly.
- This manager does not wrap the entire filter insert sequence in a multi-step transaction beyond the method-level commits present in the code.

## `ThresholdManager.py`

`ThresholdManager` stores and reuses threshold configuration records.

### Types

| Type | Purpose |
| --- | --- |
| `ThresholdMethod` | Enum currently containing `PERCENTAGE` and `ROW_COUNT`. |
| `Threshold` | Dataclass with `method`, `threshold`, and optional persisted `id`. |

### Public Methods

| Method | Purpose |
| --- | --- |
| `get_or_create(threshold)` | Validates and normalizes the threshold, reuses an existing row if found, or inserts a new row. |
| `get_if_exists(threshold)` | Returns an existing threshold row or `None`. |

### Callers

- `ClientRoutes.py` uses thresholds for participation status/submit flows.
- `NVFlareRoutes.py` parses threshold request values for job history/submission flows.
- `NVFlareJobsManager` and `ParticipationManager` persist threshold references as needed.
- `JobRunnerService.py`, `NVFlareJobTask.py`, `NVFlareParticipationJobTask.py`, and `NVFlareJobStager.py` pass threshold objects through the job lifecycle.

### Error and Transaction Behavior

- Invalid threshold shape/value raises `ValueError` through validation.
- `get_or_create()` commits on insert and rolls back on `MySQLdb.IntegrityError` before re-selecting.

## `NVFlareJobsManager.py`

`NVFlareJobsManager` owns the database record for a submitted NVFlare job and most job history retrieval logic.

### Constructor Behavior

`NVFlareJobsManager(status_writer=None, project_id=None)` stores the optional status writer and project ID, initializes `nvflare_job_mysql_id` to `None`, then opens a pooled connection and dict cursor.

### Enums

| Enum | Values/Purpose |
| --- | --- |
| `NVFlareJobFunctionFilterMode` | Controls job-history function matching behavior. Includes match modes such as requiring all functions or matching any function. |
| `NVFlareJobCreateDateDateFilterMode` | Controls create-date filtering behavior for job history. |
| `NVFlareStatus` | Tracks NVFlare lifecycle statuses such as `PROCESSING`, `SUBMITTED`, `RUNNING`, `COMPLETE`, and failure-style terminal states. |

### Public Write/Update Methods

| Method | Main Writes | Purpose |
| --- | --- | --- |
| `establish_job_entry_id(filter_id, functions_map, threshold, non_contributing_clients, exclude_analyzing_clients)` | `nvflare_jobs`, `threshold_configs`, `nvflare_job_functions`, `nvflare_job_function_configs` | Creates the main job record and links functions/config sets. |
| `set_nvflare_job_status(status)` | `nvflare_jobs` | Updates job status. Failure statuses are reconciled with the job runner log status. |
| `set_nvflare_assigned_id(assigned_id)` | `nvflare_jobs` | Stores the NVFlare assigned job ID. |
| `set_nvflare_job_path(job_path)` | `nvflare_jobs` | Stores the staged/submitted job path. |
| `set_nvflare_output_path(output_path)` | `nvflare_jobs` | Stores the output path. |
| `set_submission_timing(submit_time, run_duration)` | `nvflare_jobs` | Stores submit time and run duration. |
| `set_participation_client_overrides(non_contributing_clients, exclude_analyzing_clients)` | `nvflare_jobs` | Stores comma-separated client override lists. |
| `log_job_run_context(datasource_group_id, workflow_group_data)` | `nvflare_job_datasource_log`, `nvflare_job_workflow_groups`, `nvflare_job_workflow_group_options` | Persists selected datasource group and workflow group selections for the job. |
| `set_workflow_for_function_config(function_name, config_index, workflow_id)` | `nvflare_job_function_configs` | Assigns a workflow ID to a job function config by function and config index. |
| `ensure_and_set_workflow_for_function_config(function_name, props, workflow_id)` | `defined_function_config_*`, `nvflare_job_function_configs` | Ensures a config row exists for a concrete property set and stores its workflow ID. |

### Public Read Methods

| Method | Purpose |
| --- | --- |
| `get_nvflare_jobs(function_names, match_mode, create_date, date_filter_mode)` | Retrieves NVFlare job history rows using optional function and create-date filters. Enriches rows with functions, function configs, datasource log, workflow group log, and crypto audit data. |

### Internal Context Methods

| Method | Purpose |
| --- | --- |
| `_client_list_to_csv(client_names)` | Normalizes client-name lists to comma-separated strings. |
| `_persist_threshold_if_needed(threshold)` | Persists a threshold through `ThresholdManager` when present. |
| `_upsert_job_datasource_log(datasource_group_id)` | Inserts or updates the selected datasource group log for the current job. |
| `_replace_job_workflow_group_log(workflow_group_data)` | Replaces workflow group selections for the current job. |
| `_normalize_workflow_group_data(workflow_group_data)` | Normalizes workflow group data from request payloads. |
| `_normalize_selected_options(selected_options)` | Normalizes selected workflow option references. |
| `_resolve_workflow_group_id(group_entry)` | Resolves workflow group IDs from group payload values. |
| `_extract_raw_option_refs(group_entry)` | Extracts selected option references from group payload values. |
| `_resolve_workflow_group_option_ids(workflow_group_id, group_entry)` | Resolves selected option IDs for a workflow group. |
| `_resolve_single_workflow_group_option_id(workflow_group_id, raw_option)` | Resolves one workflow option by ID/key/value/label-style input. |
| `_fetch_job_datasource_log(job_ids)` | Fetches datasource context for job history rows. |
| `_fetch_job_workflow_groups(job_ids)` | Fetches workflow group context for job history rows. |

### Callers

- `NVFlareRoutes.py` uses it for `/nvflare/jobs/history`.
- `NVFlareJobTask.py` uses it to create and update job records during job submission and execution.
- `NVFlareParticipationJobTask.py` uses it in participation-related job flows.
- `NVFlareJobMonitor.py` uses it while monitoring job completion.
- `NVFlareJobStager.py` uses workflow mapping methods when staging workflow-specific configs.

### Error and Transaction Behavior

- Most write methods commit immediately after updating a job row or context log.
- Workflow group logging deletes existing workflow group rows for the job and inserts the current selections.
- If a failure status is being written, the manager checks `job_runner_log` and uses the job runner failure status when present.
- The manager expects `nvflare_job_mysql_id` to be established before update/context methods are called.

## `ParticipationManager.py`

`ParticipationManager` records and resolves client participation decisions for a filter/function/config/threshold combination.

### Constructor Behavior

`ParticipationManager()` opens a pooled connection and dict cursor.

### Types

| Type | Purpose |
| --- | --- |
| `Confirmation` | Participation confirmation enum. Used for statuses such as pending/accepted style participation states. |

### Public Methods

| Method | Purpose |
| --- | --- |
| `clients_list()` | Returns all NVFlare client names ordered by client name. |
| `resolve_client_id(client_name)` | Returns client ID for a client name, creating or resolving through the clients table depending on code path. |
| `record_participation(client_name, filter_id, functions_map, confirmation, threshold, contributing_party, analyzing_party)` | Upserts a participation record and rewrites related function/config rows for that participation. |
| `record_pending_participation(client_name, filter_id, functions_map, contributing_party, analyzing_party, threshold)` | Records pending participation for a client. |
| `list_client_participation_status(functions, filter_id, confirmation, clients_snapshot, threshold)` | Returns participation status for a client snapshot and requested functions/filter/threshold. Server entries are treated specially. |
| `list_clients_with_accepted_participation_csv(functions, filter_id, clients_snapshot, threshold)` | Returns accepted client names as CSV. |
| `list_clients_without_participation_csv(functions, filter_id, clients_snapshot, threshold)` | Returns clients without matching participation as CSV. |
| `get_all_initiator_client_names()` | Returns client names associated with users whose role is `INITIATOR`. |
| `get_client_names_for_username(username)` | Returns client names associated with a username. |
| `auto_accept_participation_for_username(username, filter_id, functions_map, threshold)` | Auto-accepts participation for the user's associated clients. |

### Internal Methods

| Method | Purpose |
| --- | --- |
| `_is_server_client_name(client_name)` | Detects server-style client names. |
| `_is_server_snapshot_entry(entry)` | Detects server entries in a client snapshot. |
| `_normalize_map_for_participation(functions)` | Normalizes function maps for participation matching. |
| `_persist_threshold_if_needed(threshold)` | Persists threshold config when a threshold is supplied. |
| `_candidates_by_functions_only(...)` | Finds participation candidates matching function/filter/confirmation/threshold constraints. |
| `_configs_match_for_participation(participation_id, fn_name, required_pairs)` | Checks whether persisted config pairs match a requested function config. |
| `_matching_participation_ids_by_configs(participation_ids, fn_map)` | Filters candidate participation IDs by function config matches. |

### Callers

- `ClientRoutes.py` uses it for participation status and submit endpoints.
- `NVFlareParticipationJobTask.py` uses it to record pending and accepted/declined participation during participation-confirmation workflows.

### Error and Transaction Behavior

- `record_participation()` uses `ON DUPLICATE KEY UPDATE` for the main participation row.
- Related function/config rows are deleted and recreated to match the latest submitted function map.
- Successful write paths commit explicitly.
- `record_participation()` rolls back and re-raises on exceptions.
- Server entries are handled specially in status listing and are not treated like normal client participation rows.

## `NVFlareClientEmitManager.py`

`NVFlareClientEmitManager` receives client progress/status emissions from NVFlare job runtime code and appends those messages into the backend job log.

### Constructor Behavior

`NVFlareClientEmitManager(nvflare_assigned_id)` stores the NVFlare assigned ID, opens a pooled connection and dict cursor, and resolves the corresponding `job_runner_id` from `nvflare_jobs`.

### Public Methods

| Method | Purpose |
| --- | --- |
| `log_progress_from_payload(payload)` | Parses an emission payload and writes a progress/status log message. |
| `log_progress()` | Writes progress using the manager's current state. |

### Module Helpers

| Helper | Purpose |
| --- | --- |
| `_resolve_status(payload)` | Converts payload status values into backend job runner status values. |
| `_to_int(value)` | Safely converts numeric payload values to integers. |

### Callers

`NVFlareRoutes.py` uses this manager for `POST /nvflare/client/emit_progress`.

### Error and Transaction Behavior

- If the NVFlare assigned ID cannot be resolved to a job runner ID, progress cannot be associated with a job log.
- Progress writes go through job logging behavior against `job_runner_log`.
- The manager closes its cursor and connection in `complete()`.

## `CryptoAuditManager.py`

`CryptoAuditManager` writes crypto audit records associated with NVFlare jobs.

### Types

| Type | Purpose |
| --- | --- |
| `CryptoAudit` | Dataclass-style payload for crypto audit fields. |

### Public Methods

| Method | Writes | Purpose |
| --- | --- | --- |
| `log_audit(audit)` | `nvflare_job_crypto_audit` | Inserts a crypto audit event and returns the new row ID. |

### Callers

`NVFlareRoutes.py` uses this manager for `POST /nvflare/jobs/audit/submit`.

### Error and Transaction Behavior

`log_audit()` commits after inserting the audit row. It does not perform lookup validation beyond the insert path in the manager.

## Job Tracking Classes

### `JobStatusWriter.py`

`JobStatusWriter` appends timestamped log messages and current job status to `job_runner_log`.

#### Constructor Behavior

`JobStatusWriter(job_id)` stores the UUID-style job runner ID, opens a pooled connection and dict cursor, and creates a `threading.Lock` so concurrent `log()` calls for the same writer do not interleave database writes.

#### Public Methods

| Method | Purpose |
| --- | --- |
| `get_job_id()` | Returns the job UUID associated with this writer. |
| `log(log_message, status=None)` | Appends a timestamped log line to `job_runner_log`. If `status` is supplied, also updates the current status. |
| `complete()` | Closes cursor and connection. |

#### Status Enum

`JobRunnerStatus` contains queue, processing, participation, filter, secure-connection, upload, broadcast, compute, key generation, decryption, encryption, analysis, results, warning/error/failure, and `DONE` states used across the job lifecycle.

#### Stop Behavior

Before writing a log entry, `log()` checks whether the job row is marked with status `STOP`. If so, it appends a stop message, commits, and exits the process with `os._exit(0)`.

#### Helper

`safe_status_update(status_writer, status, message)` safely logs a status update when a writer is available. It is used by manager/task code that may run with or without a writer.

### `JobStatusRetriever.py`

`JobStatusRetriever` reads persisted job status for `/jobs/status` style flows.

#### Constructor Behavior

`JobStatusRetriever(max_retries=3, base_delay=0.2)` opens a pooled connection and dict cursor and stores retry settings.

#### Public Methods

| Method | Reads | Purpose |
| --- | --- | --- |
| `get_status_by_uuid(uuid)` | `job_runner_log`, `nvflare_jobs`, `nvflare_job_functions`, `defined_functions` | Returns a job log row and enriches it with referenced NVFlare assigned IDs, run duration, NVFlare job rows, and function names. |

#### Error Behavior

SQL execution is retried with exponential backoff through `_exec()`. The final failed attempt re-raises the exception.

### `NVFlareJobsDataRetriever.py`

`NVFlareJobsDataRetriever` retrieves result/config data for a completed NVFlare job.

#### Constructor Behavior

`NVFlareJobsDataRetriever(nvflare_job_id, function)` stores the NVFlare assigned ID and supported function. It does not open a persistent MySQL connection in the constructor.

#### Public Methods

| Method | Purpose |
| --- | --- |
| `list_workflow_dirs()` | Lists workflow output directories for the job. |
| `retrieve_workflow_data(workflow_id)` | Reads workflow result data from local or remote output. |
| `retrieve_workflow_data_with_config(workflow_id)` | Returns workflow data plus the function config associated with the workflow. |
| `retrieve_function_config(workflow_id)` | Returns the persisted function config for a workflow ID. |
| `get_profile_summary()` | Reads profiling/summary data from job output when available. |

#### MySQL Usage

`_fetch_function_config_for_workflow(workflow_id)` opens a short-lived pooled connection and reads:

- `nvflare_jobs`
- `nvflare_job_function_configs`
- `defined_function_config_sets`
- `defined_function_config_set_members`
- `defined_function_config_properties`
- `defined_functions`

It closes the cursor and connection after the query.

#### File/Output Usage

Result data is read from job output paths. The retriever supports local job roots and remote path reads, prefers raw JSON when available, and includes helper behavior for optional files, initiator results, client site directories, and client site error files.

#### Callers

`JobRunnerRoutes.py` uses this retriever for job result, function config, mapping, and profile-summary related endpoints.

## Route and Service Callers

| Caller | MySQL Classes Used |
| --- | --- |
| `app/main.py` | `UsersManager` |
| `ClientRoutes.py` | `FiltersManager`, `FunctionsManager`, `_normalize_functions_map`, `ParticipationManager`, `ThresholdManager` |
| `FilterRoutes.py` | `MySQLRetriever`, `FunctionsManager` |
| `FunctionRoutes.py` | `FunctionsManager` |
| `JobRunnerRoutes.py` | `JobStatusRetriever`, `NVFlareJobsDataRetriever`, `MySQLConnectionProvider`, `MySQLTable` |
| `NVFlareRoutes.py` | `CryptoAuditManager`, `NVFlareClientEmitManager`, `NVFlareJobsManager`, `ThresholdManager`, `_normalize_functions_map` |
| `ProjectRoutes.py` | `ProjectsManager`, `UsersManager` |
| `JobRunnerService.py` | `JobStatusWriter`, `Threshold` |
| `NVFlareJobTask.py` | `FiltersManager`, `NVFlareJobsManager`, `JobStatusWriter`, `Threshold` |
| `NVFlareParticipationJobTask.py` | `ParticipationManager`, `NVFlareJobsManager`, `JobStatusWriter`, `Threshold` |
| `NVFlareJobMonitor.py` | `JobStatusWriter`, `NVFlareJobsManager` |
| `NVFlareJobStager.py` | `MySQLRetriever`, `NVFlareJobsManager`, `ProjectsManager`, `Threshold` |
| `NVFlareJobUploader.py` | `MySQLRetriever`, `FiltersManager`, `MySQLConnectionProvider`, `JobStatusWriter` |

## Transaction and Error Handling Rules in Current Code

- Connections are pooled and typically opened per manager instance.
- Most managers use a single cursor for the instance lifetime.
- Callers are responsible for closing managers/retrievers with `complete()`.
- Read-only managers do not commit.
- Write managers generally commit inside the public method that performs the write.
- `ParticipationManager.record_participation()` rolls back on exception.
- `ThresholdManager.get_or_create()` rolls back after duplicate insert races before re-selecting.
- `FunctionsManager.get_or_create_function_config_property_id()` handles duplicate insert races by re-querying.
- `JobStatusRetriever` retries failed read queries with exponential backoff.
- `JobStatusWriter.log()` catches and prints MySQL errors around stop-status checking and then attempts normal logging.
- `MySQLConnectionProvider.get_connection()` rebuilds the pool if a pooled connection cannot be retrieved.

## Schema Change Guidance for Manager Code

When adding or changing MySQL-backed behavior:

1. Add or update table definitions in `MySQLConnectionProvider.py` schema creation code.
2. Add startup compatibility checks only when an existing deployed database needs a transitional column/index/constraint check.
3. Prefer adding table names to `MySQLTable.py` when multiple classes will reference the table.
4. Keep route files thin; route handlers should call a manager, retriever, or service class.
5. Use parameterized SQL for all request-derived values.
6. Keep connection ownership clear: the class that opens a connection should close it.
7. Wrap manager use in route/job code with `try/finally` and call `complete()`.
8. For multi-table writes, commit only after the related rows are consistent, and roll back on exceptions.
9. Keep function configuration writes aligned with `FunctionsManager.normalize_map()` and config-set hashing.
10. Keep participation writes aligned with function/config/threshold matching so participation status remains reusable across equivalent requests.
