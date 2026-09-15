# Functions, Filters, Thresholds, and Workflow Groups

## Files Covered

| File | Role |
| --- | --- |
| `app/api/routes/FunctionRoutes.py` | Defines the supported-function lookup endpoint. |
| `app/api/routes/FilterRoutes.py` | Defines filter lookup endpoints. |
| `app/api/routes/NVFlareRoutes.py` | Accepts submitted functions, filters, threshold configuration, and workflow group selections for job submission. |
| `app/api/models/FunctionBasedRequest.py` | Defines a shared function-based Pydantic model using `SupportedFunction`; this model is currently not used by the active function/filter endpoints. |
| `app/core/mysql/managers/FunctionsManager.py` | Normalizes submitted function maps, resolves function IDs, stores function configuration sets, links jobs to functions/configs, and fetches job function/config data. |
| `app/core/mysql/managers/FiltersManager.py` | Validates, normalizes, hashes, stores, and deduplicates submitted filter sets by project. |
| `app/core/mysql/managers/ThresholdManager.py` | Validates, reads, and creates threshold configuration rows. |
| `app/core/mysql/managers/ProjectsManager.py` | Reads project function capabilities, filter system metadata, and workflow group metadata for project list responses. |
| `app/core/mysql/managers/NVFlareJobsManager.py` | Creates job rows, links jobs to functions/configs, stores threshold references, records selected workflow groups, and returns workflow context in job history. |
| `app/core/mysql/MySQLRetriever.py` | Provides read-only filter retrieval and staged filter reconstruction by filter ID. |
| `app/core/mysql/SupportedFunction.py` | Defines supported function enum values, default function properties, property type metadata, computation-type mappings, and display labels. |
| `app/core/mysql/SupportedFilterSystem.py` | Defines supported filter systems. |
| `app/core/mysql/MySQLConnectionProvider.py` | Creates schema and seeds default functions, function defaults, filter systems, projects, project function restrictions, and workflow group options. |
| `app/core/job_runner/JobRunnerService.py` | Queues jobs with submitted `functions_map`, `filters`, `threshold`, datasource exclusions, and workflow group data. |
| `app/core/job_runner/job_tasks/NVFlareJobTask.py` | Persists filters, creates the NVFlare job entry, logs datasource/workflow context, and passes functions/workflow data to the job stager. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Converts function configuration and selected workflow groups into concrete NVFlare workflow definitions and workload arguments. |

## Current Endpoint Inventory

| Method | Path | Handler | File | Purpose |
| --- | --- | --- | --- | --- |
| `POST` | `/functions/supported_functions` | `fetch_supported_functions` | `FunctionRoutes.py` | Returns all rows from `defined_functions`. |
| `POST` | `/filters/fetch_single_filter` | `fetch_single_filter` | `FilterRoutes.py` | Returns one saved filter and its conditions by `filter_id`. |
| `POST` | `/filters/fetch_filters` | `fetch_filters` | `FilterRoutes.py` | Returns saved filters for a required `project_id`. |
| `POST` | `/nvflare/jobs/submit` | `submit_nvflare_job` | `NVFlareRoutes.py` | Accepts submitted filters, functions, threshold configuration, datasource group, participant overrides, and workflow group selections. |
| `POST` | `/projects/list` | `get_projects_list` | `ProjectRoutes.py` | Returns projects with function capabilities, filter systems, datasource groups, and workflow groups. |

The active function and filter routes use `include_in_schema=False`, so they are intentionally hidden from generated FastAPI OpenAPI output.

## Supported Functions

Supported functions are defined in `SupportedFunction.py` and seeded into `defined_functions` by `MySQLConnectionProvider._ensure_default_functions_exist()`.

Current enum values:

| Function | Seeded description |
| --- | --- |
| `SURVIVAL_ANALYSIS` | Runs survivability analysis using filtered patient data from all clients. |
| `CHI_SQUARE_TEST` | Statistical test for association between categorical variables. |
| `STANDARD_DEVIATION` | The spread of individual measurements around the mean. |
| `MEAN` | Summarizes continuous variables. |
| `T_TEST` | Compares means of two groups. |
| `ENCRYPTED_FILTERING` | Applies filters securely in encrypted form. |
| `COUNT` | Returns the number of records matching selected filters. |
| `LOGISTIC_CALIBRATION_STATISTICS` | Supports calibration statistics for risk assessment. |
| `PARTICIPATION_CONFIRMATION` | Exists in the enum and is included in the General Statistics project restriction list, but it is not included in the default function seed map in the current backend code. |

### Function Defaults

`SupportedFunction.FUNCTION_DEFAULT_PROPERTIES` defines default configuration properties for these functions:

| Function | Default properties |
| --- | --- |
| `SURVIVAL_ANALYSIS` | `group_column_id=PBRM1`, `time_column_id=OS`, `censoring_column_id=OS_CNSR`, `time_grid_min=0`, `time_grid_step=0.1`, `time_grid_max=62`, `CI_type=None` |
| `CHI_SQUARE_TEST` | `category_column_1_id=PBRM1`, `category_column_2_id=gender` |
| `MEAN` | `data_column_id=Age` |
| `STANDARD_DEVIATION` | `data_column_id=Age`, `std_type=population` |
| `T_TEST` | `data_column_id=Age`, `category_column_1_id=PBRM1` |

Default properties are inserted into `defined_function_config_properties` if they do not already exist. The default seed routine inserts individual property rows only; it does not create default `defined_function_config_sets` rows.

### Function Property Type Metadata

`SupportedFunction.FUNCTION_PROPERTY_TYPES` defines lightweight property type metadata for:

| Function | Property type keys |
| --- | --- |
| `SURVIVAL_ANALYSIS` | `group_column_id`, `time_column_id`, `censoring_column_id`, `time_grid_min`, `time_grid_step`, `time_grid_max`, `is_biomarker_discovery`, `is_server_contributing_to_aggregation`, `model_key`, `cancer_type`, `CI_type` |
| `CHI_SQUARE_TEST` | `category_column_1_id`, `category_column_2_id` |
| `MEAN` | `data_column_id` |
| `STANDARD_DEVIATION` | `data_column_id`, `std_type` |
| `T_TEST` | `data_column_id`, `category_column_1_id` |

These type definitions are used as metadata. The active function endpoint returns database rows from `defined_functions`; it does not return this type map.

### Computation Type Mapping

`SupportedFunction.FUNCTION_TO_COMPUTATION_TYPE` maps logical backend function names to the `computation_type` values used by the statistical analytics workflow:

| Function | `computation_type` |
| --- | --- |
| `SURVIVAL_ANALYSIS` | `kaplan-meier` |
| `CHI_SQUARE_TEST` | `chi2` |
| `MEAN` | `mean` |
| `STANDARD_DEVIATION` | `stdev` |
| `T_TEST` | `t-test` |

`NVFlareJobStager._build_stat_analytics_workflows()` uses this map when a function configuration does not already include `computation_type`.

## `POST /functions/supported_functions`

### Request Body

The handler accepts a `Request` object but does not read the body. An empty JSON object is valid.

```json
{}
```

### Success Response

The route instantiates `FunctionsManager`, calls `get_supported_functions()`, closes the manager in a `finally` block, and returns:

```json
{
  "status": "SUCCESS",
  "functions": [
    {
      "id": 1,
      "name": "SURVIVAL_ANALYSIS",
      "description": "Runs survivability analysis using filtered patient data from all clients",
      "create_date": "2026-04-07T18:41:00",
      "update_date": "2026-04-07T18:41:00"
    }
  ]
}
```

`create_date` and `update_date` are converted to ISO strings when present.

### Error Behavior

Unhandled exceptions are logged and returned as:

```json
{
  "status": "FAILURE",
  "error": "Internal error"
}
```

with status code `500`.

## Function Storage and Job Linking

Function metadata and job configuration are split across several tables.

| Table | Purpose |
| --- | --- |
| `defined_functions` | One row per supported function. |
| `defined_project_function_restrictions` | Project-specific allowed functions and project-provided fixed, variable, and override configuration JSON. |
| `defined_function_config_properties` | Deduplicated function property rows by `(function_id, property_name, property_value)`. |
| `defined_function_config_sets` | A deterministic config-set header identified by `(function_id, config_hash)`. |
| `defined_function_config_set_members` | Join table linking config sets to property rows. |
| `nvflare_job_functions` | Join table linking an NVFlare job to selected functions. |
| `nvflare_job_function_configs` | Join table linking an NVFlare job to selected function config sets, with optional `workflow_id`. |

`FunctionsManager.normalize_map()` accepts either a single config object per function or a list of config objects per function. It uppercases function names, trims property keys, coerces `None` to an empty string, and returns a structure shaped as:

```json
{
  "SURVIVAL_ANALYSIS": [
    {
      "group_column_id": "risk_score_group",
      "time_column_id": "time",
      "censoring_column_id": "event"
    }
  ]
}
```

`FunctionsManager.ensure_configs_and_link()` resolves function IDs, creates or reuses config property rows, creates or reuses config set rows, links config sets to property rows, and inserts rows into `nvflare_job_function_configs` for the job.

`NVFlareJobsManager.establish_job_entry_id()` creates the `nvflare_jobs` row, validates that submitted function names exist, creates `nvflare_job_functions` links, and delegates config linking to `FunctionsManager`.

## Project Function Restrictions

Project-level function availability is read by `ProjectsManager._get_project_functions()` and returned through the project list flow.

If `defined_projects.function_restrictions_enabled` is false, the backend returns every `SupportedFunction` enum value as configurable for that project.

If restrictions are enabled, the backend reads enabled rows from `defined_project_function_restrictions` and returns each allowed function with:

| Field | Source |
| --- | --- |
| `function` | `defined_functions.name` mapped back to `SupportedFunction` |
| `configurable` | `defined_project_function_restrictions.configurable` |
| `custom_configuration_fixed` | JSON from `custom_configuration_fixed` |
| `custom_configuration_variable` | JSON from `custom_configuration_variable` |
| `override_configuration` | JSON from `override_configuration` |

The seed logic currently creates two default projects:

| Project | Filter system | Restricted functions | Notable configuration |
| --- | --- | --- | --- |
| `General Statistics` | `DEFAULT` | `SURVIVAL_ANALYSIS`, `CHI_SQUARE_TEST`, `MEAN`, `STANDARD_DEVIATION`, `PARTICIPATION_CONFIRMATION`, `T_TEST`, `ENCRYPTED_FILTERING`, `COUNT` | Empty fixed, variable, and override config maps. |
| `Biomarker Model Validation for Cancer Prognosis` | `CANCER_TYPE` | `SURVIVAL_ANALYSIS`, `LOGISTIC_CALIBRATION_STATISTICS` | `SURVIVAL_ANALYSIS` fixed config sets `is_server_contributing_to_aggregation=false`, `is_biomarker_discovery=true`, `model_key=cox_lasso`; variable config exposes `cancer_type` and `model_type`; override config sets `group_column_id=risk_score_group`, `time_column_id=time`, `censoring_column_id=event`, `time_grid_step=1`, `time_grid_max=110`. |

## Filter Systems

`SupportedFilterSystem.py` defines two filter systems:

| Filter system | Description seeded by backend | Allowed filter types seeded by backend |
| --- | --- | --- |
| `DEFAULT` | General analysis filter system tied to broad FHIR observation data. | `PATIENT_QUERY`, `PATIENT_DATA`, `OBSERVATION` |
| `CANCER_TYPE` | Filter system focused on known cancer types, utilized in biomarker pipeline. | `PATIENT_DATA` |

The seed code stores filter systems in `defined_filter_system` and allowed filter types in `defined_filter_system_allowed_filter_types`.

`ProjectsManager._get_filter_system_map()` reads these tables and attaches `filter_system` and `filter_system_allowed_filter_types` to project objects.

## Filters

Filters are stored as project-scoped, function-agnostic filter definitions.

`FiltersManager` validates submitted filter payloads, normalizes them, computes a SHA-256 hash over the normalized conditions, and reuses the existing filter row when a matching hash already exists for the same project.

### Filter Payload Shape

The job submission flow expects `filters` to be present in the `/nvflare/jobs/submit` body.

A typical filter object is shaped as:

```json
{
  "name": "Cancer Type Filter",
  "conditions": [
    {
      "filter_type": "PATIENT_DATA",
      "column_name": "cancer_type",
      "operator": "=",
      "value": "Melanoma"
    }
  ]
}
```

`filters.name` is required and must be a string when filters are persisted by `FiltersManager`.

`filters.conditions` may be `null` or an empty array. In that case the manager stores a filter header with an empty condition list and a deterministic hash for the empty condition signature.

### Supported Filter Types

`FiltersManager.FilterType` accepts:

| Filter type |
| --- |
| `PATIENT_QUERY` |
| `PATIENT_DATA` |
| `OBSERVATION` |
| `OBSERVATION_QUERY` |
| `OBSERVATION_DATA` |

The filter system attached to a project controls which filter types are advertised to the frontend through project metadata. `FiltersManager` itself validates against the full `FilterType` enum.

### Supported Operators

`FiltersManager.Operator` accepts:

| Canonical operator | Accepted aliases |
| --- | --- |
| `=` | `=`, `==` |
| `!=` | `!=`, `<>` |
| `>` | `>` |
| `>=` | `>=` |
| `<` | `<` |
| `<=` | `<=` |
| `LIKE` | `LIKE` |
| `IN` | `IN` |
| `NOT_IN` | `NOT_IN`, `NOT IN` |
| `BETWEEN` | `BETWEEN` |
| `IN_ALL` | `IN_ALL`, `IN ALL` |

`IN`, `NOT_IN`, and `IN_ALL` require a non-empty `values` array, or a single `value` that can be coerced into a one-item array.

`BETWEEN` requires exactly two values.

Other operators store a scalar `value`; missing scalar values are stored as an empty string.

List values are CSV-encoded with escaping for commas and backslashes before being stored in `defined_fhir_filter_conditions.value`.

### Filter Normalization

For each condition, `FiltersManager`:

1. Uppercases and validates `filter_type`.
2. Requires a non-empty `column_name`.
3. Canonicalizes `operator`.
4. Serializes scalar or list values.
5. Sorts normalized conditions by `filter_type`, `column_name`, `operator`, and `value`.
6. Builds a deterministic signature.
7. Hashes the signature with SHA-256.
8. Looks for an existing row in `defined_fhir_filters` by `(project_id, filter_hash)`.
9. Inserts `defined_fhir_filters` and `defined_fhir_filter_conditions` only when no matching row exists.

### `POST /filters/fetch_filters`

#### Request Body

```json
{
  "project_id": 2
}
```

`project_id` is required and must be convertible to an integer.

#### Success Response

The route calls `MySQLRetriever.get_all_filters(project_id=project_id)` and returns:

```json
{
  "status": "SUCCESS",
  "filters": [
    {
      "id": 10,
      "name": "Cancer Type Filter",
      "project_id": 2,
      "conditions": [
        {
          "filter_type": "PATIENT_DATA",
          "column_name": "cancer_type",
          "operator": "=",
          "value": "Melanoma"
        }
      ],
      "create_date": "2026-04-28T20:34:00",
      "update_date": "2026-04-28T20:34:00"
    }
  ]
}
```

#### Error Behavior

Missing or invalid `project_id` returns:

```json
{
  "status": "FAILURE",
  "error": "project_id is required"
}
```

with status code `400`.

Unhandled exceptions are logged and returned with status code `500`:

```json
{
  "status": "FAILURE",
  "error": "<exception text>"
}
```

### `POST /filters/fetch_single_filter`

#### Request Body

```json
{
  "filter_id": 10
}
```

`filter_id` is required and must be convertible to an integer.

#### Success Response

The route calls `MySQLRetriever.get_single_filter(filter_id)` and returns:

```json
{
  "status": "SUCCESS",
  "filter": {
    "id": 10,
    "name": "Cancer Type Filter",
    "conditions": [
      {
        "filter_type": "PATIENT_DATA",
        "column_name": "cancer_type",
        "operator": "=",
        "value": "Melanoma"
      }
    ],
    "create_date": "2026-04-28T20:34:00",
    "update_date": "2026-04-28T20:34:00"
  }
}
```

If no filter exists for the provided ID, `filter` is `null` and the response status is still `SUCCESS`.

#### Error Behavior

Missing `filter_id` returns status code `400`:

```json
{
  "status": "Submission must include filter_id"
}
```

Invalid `filter_id` returns status code `400`:

```json
{
  "status": "filter_id must be an integer"
}
```

Unhandled exceptions are logged and returned with status code `500`:

```json
{
  "status": "FAILURE",
  "error": "<exception text>"
}
```

## Thresholds

Thresholds are stored in `threshold_configs` and represented in code by `ThresholdManager.Threshold`.

Current methods:

| Method | Behavior |
| --- | --- |
| `Threshold.normalized()` | Converts method strings to `ThresholdMethod` enum values and threshold values to integers. |
| `ThresholdManager.get_or_create()` | Validates the threshold, returns an existing row when found, otherwise inserts a new row and returns it with an ID. |
| `ThresholdManager.get_if_exists()` | Validates the threshold and returns a matching row if one exists. |

Current threshold methods:

| Method |
| --- |
| `PROTECTED` |
| `EXPOSED` |

### Threshold Submission Shape

`/nvflare/jobs/submit` reads an optional `threshold_config` object. It accepts either `thresholdMethod` or `method` for the method field.

```json
{
  "threshold_config": {
    "thresholdMethod": "PROTECTED",
    "threshold": 5
  }
}
```

If `threshold_config` is present and valid, `NVFlareRoutes.submit_nvflare_job()` persists it through `ThresholdManager.get_or_create()` before queueing the job.

Invalid threshold method returns status code `400`:

```json
{
  "status": "Invalid threshold method"
}
```

Invalid threshold value returns status code `400`:

```json
{
  "status": "Invalid threshold value"
}
```

When a threshold is associated with a job, `NVFlareJobsManager.establish_job_entry_id()` stores the threshold ID in `nvflare_jobs.threshold_config_id`.

## Workflow Groups

Workflow groups allow a project to expose grouped option selections that affect job staging.

The current backend seeds one workflow group for the `Biomarker Model Validation for Cancer Prognosis` project.

| Field | Current value |
| --- | --- |
| `group_key` | `predictive_modeling_method_ids` |
| `group_label` | `Predictive Model Configuration` |
| `group_description` | `Select one or more predictive models to invoke.` |
| `min_selected` | `1` |
| `max_selected` | `NULL` |
| `is_required` | `1` |
| `page_order` | `0` |
| `status` | `ACTIVE` |

Seeded options:

| Option key | Option label | Option value | Default | Order |
| --- | --- | --- | --- | --- |
| `cox_lasso` | `Lasso Cox Regression` | `cox_lasso` | `0` | `0` |
| `logistic_reg` | `Lasso Logistic Regression` | `logistic_reg` | `0` | `1` |

The Cox option description explains a Cox proportional hazards regression using L1 penalization on mutation burden gene features with unpenalized clinical covariates and 5-fold cross-validation on concordance index.

The logistic option description explains logistic regression for exceptional responders whose survival time exceeds the training mean plus two standard deviations, using L1 penalization and 5-fold cross-validation on concordance index.

### Workflow Group Exposure to Frontend

`ProjectsManager.get_defined_project_workflow_groups(project_id)` returns active groups and active options ordered by group `page_order`, option `option_order`, labels, and IDs.

`ProjectsManager.get_project_workflow_group_summary(project_id)` returns:

```json
{
  "workflow_groups_defined": true,
  "workflow_groups": [
    {
      "id": 1,
      "group_key": "predictive_modeling_method_ids",
      "group_label": "Predictive Model Configuration",
      "group_description": "Select one or more predictive models to invoke.",
      "min_selected": 1,
      "max_selected": null,
      "is_required": true,
      "page_order": 0,
      "options": [
        {
          "id": 1,
          "option_key": "cox_lasso",
          "option_label": "Lasso Cox Regression",
          "option_value": "cox_lasso",
          "option_description": "...",
          "option_order": 0,
          "is_default": false
        }
      ]
    }
  ]
}
```

The project list response includes `workflow_groups_defined` and `workflow_groups` inside each project object.

### Workflow Group Submission Shape

`/nvflare/jobs/submit` reads optional `workflow_group_data`. When present, it must be a JSON object.

The stager expects the predictive modeling selection under `workflow_group_data.predictive_modeling_method_ids.selected_values`:

```json
{
  "workflow_group_data": {
    "predictive_modeling_method_ids": {
      "selected_values": ["cox_lasso", "logistic_reg"]
    }
  }
}
```

`NVFlareJobsManager` accepts several equivalent names when logging the selection:

| Accepted group key fields |
| --- |
| `group_key` |
| `workflow_group_key` |
| outer object key |

| Accepted selected option fields |
| --- |
| `selected_values` |
| `selected_options` |
| `option_values` |
| `option_keys` |
| `selected_option_values` |
| `selected_option_keys` |

Selected option objects may use `option_value`, `value`, `option_key`, or `key`.

If `workflow_group_data` is present but is not an object, `/nvflare/jobs/submit` returns status code `400`:

```json
{
  "status": "workflow_group_data must be an object when provided"
}
```

### Workflow Group Logging

`NVFlareJobTask.run_nvflare_job()` calls `NVFlareJobsManager.log_job_run_context()` after creating the NVFlare job entry.

That method:

1. Upserts one row in `nvflare_job_datasource_log` for the job.
2. Deletes existing `nvflare_job_workflow_groups` rows for the job.
3. Normalizes submitted workflow group data.
4. Resolves workflow groups by `(project_id, group_key)`.
5. Resolves selected options by matching `option_key` or `option_value`.
6. Inserts `nvflare_job_workflow_groups` rows.
7. Inserts `nvflare_job_workflow_group_options` rows.
8. Commits the changes.

Unknown workflow group keys and unknown option values are skipped and logged to the job status writer when available. They do not fail the job submission path by themselves.

`NVFlareJobsManager._fetch_job_workflow_groups()` returns workflow group logs for job history. It also builds a compact `workflow_group_data` map shaped as:

```json
{
  "predictive_modeling_method_ids": ["cox_lasso", "logistic_reg"]
}
```

## Workflow Group Effect on NVFlare Staging

`NVFlareJobStager` uses `workflow_group_data` to determine selected biomarker model keys.

The current selector is specific to:

```json
{
  "predictive_modeling_method_ids": {
    "selected_values": ["cox_lasso", "logistic_reg"]
  }
}
```

`NVFlareJobStager._get_selected_model_keys()` reads that object and returns unique non-empty string values in selected order.

When selected model keys exist and a submitted function config has `is_biomarker_discovery` set to a truthy string form (`"true"` or `"1"`), the stager:

1. Expands the submitted `functions_map` so the biomarker function config is duplicated once per selected model key.
2. Adds or replaces `model_key` in each duplicated config.
3. Expands project function metadata in the same way for staging.
4. Copies biomarker model cutoff and weights CSV files for each selected model key and cancer type into both `app_client/custom` and `app_server/custom`.
5. Creates one stat analytics workflow per selected model key.
6. Uses workflow IDs shaped as `workflow_stat_analytics__{model_key}`, for example `workflow_stat_analytics__cox_lasso` and `workflow_stat_analytics__logistic_reg`.
7. Records the workflow ID against the corresponding job function config through `NVFlareJobsManager.ensure_and_set_workflow_for_function_config()`.

If no selected model keys are present, normal stat analytics workflow IDs use the indexed shape `workflow_stat_analytics_{index}`.

`NVFlareJobStager._get_unique_workflow_id()` preserves the requested workflow ID when unused. If a duplicate ID already exists in the generated workflow list, it appends `_2`, `_3`, and so on until the ID is unique.

## Job Submission Flow for Functions, Filters, Thresholds, and Workflow Groups

`/nvflare/jobs/submit` performs the following current-state flow:

1. Reads the JSON body.
2. Requires `filters`.
3. Requires integer-convertible `project_id`.
4. Reads participant override arrays from `non_contributing_clients` and `exclude_analyzing_clients`, defaulting to empty lists.
5. Reads `functions_map`.
6. If `functions_map` is missing, falls back to a legacy single-function shape using `function` and `function_config`.
7. Normalizes the function map with `_normalize_functions_map()`.
8. Requires at least one function key.
9. Validates `workflow_group_data` as an object when present.
10. Reads optional `datasource_group` and converts it to an integer when provided.
11. Reads optional `threshold_config` and persists it when valid.
12. Calls `JobRunnerService.request_job_run()` with project ID, functions map, filters, threshold, participant overrides, datasource group ID, and workflow group data.
13. Returns the queued job runner ID.

The queued worker later creates `NVFlareJobTask`, which persists filters through `FiltersManager`, creates the job through `NVFlareJobsManager`, logs datasource/workflow context, and stages the concrete NVFlare job through `NVFlareJobStager`.

## Database Tables

### `defined_functions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `name` | `VARCHAR(255)` | Unique function name. |
| `description` | `TEXT` | Function description. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

### `defined_project_function_restrictions`

| Column | Type | Notes |
| --- | --- | --- |
| `project_id` | `INT` | Part of primary key; FK to `defined_projects(id)` with cascade delete. |
| `function_id` | `INT` | Part of primary key; FK to `defined_functions(id)` with cascade delete. |
| `enabled` | `ENUM('ENABLED','DISABLED')` | Defaults to `ENABLED`. |
| `configurable` | `TINYINT(1)` | Defaults to `1`. |
| `custom_configuration_fixed` | `JSON` | Project-defined fixed config. |
| `custom_configuration_variable` | `JSON` | Project-defined variable config. |
| `override_configuration` | `JSON` | Project-defined config overrides. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Primary key: `(project_id, function_id)`.

Indexes: `idx_dpfr_function`, `idx_dpfr_enabled`.

### `defined_function_config_properties`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `function_id` | `INT` | FK to `defined_functions(id)` with cascade delete. |
| `property_name` | `VARCHAR(191)` | Config property name. |
| `property_value` | `VARCHAR(191)` | Config property value. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique key: `(function_id, property_name, property_value)`.

Indexes: `idx_func_prop`, `idx_dfcp_name_value`.

### `defined_function_config_sets`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `function_id` | `INT` | FK to `defined_functions(id)` with restrict delete. |
| `config_hash` | `CHAR(64)` | SHA-256 hash of sorted property key/value pairs. |
| `label` | `VARCHAR(255)` | Optional label. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique key: `(function_id, config_hash)`.

Indexes: `idx_dfcs_function`, `idx_dfcs_hash`.

### `defined_function_config_set_members`

| Column | Type | Notes |
| --- | --- | --- |
| `config_set_id` | `INT` | FK to `defined_function_config_sets(id)` with cascade delete. |
| `config_id` | `INT` | FK to `defined_function_config_properties(id)` with restrict delete. |

Primary key: `(config_set_id, config_id)`.

Index: `idx_dfcs_member_cfg`.

### `defined_filter_system`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `name` | `VARCHAR(255)` | Unique filter system name. |
| `description` | `TEXT` | Filter system description. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

### `defined_filter_system_allowed_filter_types`

| Column | Type | Notes |
| --- | --- | --- |
| `filter_system_id` | `INT` | FK to `defined_filter_system(id)` with cascade delete. |
| `filter_type` | `ENUM('PATIENT_QUERY','PATIENT_DATA','OBSERVATION','OBSERVATION_QUERY','OBSERVATION_DATA')` | Allowed filter type. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Primary key: `(filter_system_id, filter_type)`.

Index: `idx_dfs_aft_type`.

### `defined_fhir_filters`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `project_id` | `INT` | FK to `defined_projects(id)` with cascade delete. |
| `name` | `VARCHAR(255)` | User/display name for the filter set. |
| `filter_hash` | `CHAR(64)` | SHA-256 hash of normalized conditions. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique key: `(project_id, filter_hash)`.

Indexes: `idx_project_id`, `idx_create_date`.

### `defined_fhir_filter_conditions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `filter_id` | `INT` | FK to `defined_fhir_filters(id)` with cascade delete. |
| `filter_type` | `ENUM('PATIENT_QUERY','PATIENT_DATA','OBSERVATION','OBSERVATION_QUERY','OBSERVATION_DATA')` | Filter classification. |
| `column_name` | `VARCHAR(255)` | Field/column being filtered. |
| `operator` | `VARCHAR(20)` | Canonical operator string. |
| `value` | `TEXT` | Scalar value or escaped CSV list. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Indexes: `idx_filter_id`, `idx_filter_type`.

### `threshold_configs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `method` | `ENUM('PROTECTED','EXPOSED')` | Threshold method. |
| `threshold` | `INT` | Threshold value. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Indexes: `idx_threshold_method`, `idx_threshold_value`.

There is no unique constraint on `(method, threshold)` in the current table definition. `ThresholdManager.get_or_create()` checks for an existing row before insert.

### `defined_project_workflow_groups`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `project_id` | `INT` | FK to `defined_projects(id)` with cascade delete. |
| `group_key` | `VARCHAR(100)` | Stable group key used in request payloads. |
| `group_label` | `VARCHAR(255)` | Display label. |
| `group_description` | `TEXT` | Optional display description. |
| `min_selected` | `INT` | Minimum selected options. |
| `max_selected` | `INT` | Optional maximum selected options. |
| `is_required` | `TINYINT(1)` | Required flag. |
| `page_order` | `INT` | Frontend ordering. |
| `status` | `ENUM('ACTIVE','INACTIVE')` | Defaults to `ACTIVE`. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique key: `(project_id, group_key)`.

Indexes: `idx_dpwg_project`, `idx_dpwg_project_order`.

### `defined_project_workflow_group_options`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `workflow_group_id` | `INT` | FK to `defined_project_workflow_groups(id)` with cascade delete. |
| `option_key` | `VARCHAR(100)` | Stable option key. |
| `option_label` | `VARCHAR(255)` | Display label. |
| `option_value` | `VARCHAR(255)` | Submitted value used by staging. |
| `option_order` | `INT` | Frontend ordering. |
| `option_description` | `TEXT` | Optional description. |
| `is_default` | `TINYINT(1)` | Default-selected flag. |
| `status` | `ENUM('ACTIVE','INACTIVE')` | Defaults to `ACTIVE`. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique keys: `(workflow_group_id, option_key)`, `(workflow_group_id, option_value)`.

Index: `idx_dpwgo_group_order`.

### `nvflare_job_function_configs`

| Column | Type | Notes |
| --- | --- | --- |
| `job_id` | `INT` | FK to `nvflare_jobs(id)` with cascade delete. |
| `function_config_id` | `INT` | FK to `defined_function_config_sets(id)` with restrict delete. |
| `workflow_id` | `VARCHAR(255)` | Optional concrete NVFlare workflow ID. |

Primary key: `(job_id, function_config_id)`.

Unique key: `(job_id, workflow_id)`.

Index: `idx_njfc_workflow`.

### `nvflare_job_workflow_groups`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `nvflare_job_id` | `INT` | FK to `nvflare_jobs(id)` with cascade delete. |
| `workflow_group_id` | `INT` | FK to `defined_project_workflow_groups(id)` with cascade delete. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique key: `(nvflare_job_id, workflow_group_id)`.

Indexes: `idx_nvjwg_job`, `idx_nvjwg_group`.

### `nvflare_job_workflow_group_options`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT` | Primary key. |
| `nvflare_job_workflow_group_id` | `INT` | FK to `nvflare_job_workflow_groups(id)` with cascade delete. |
| `workflow_group_option_id` | `INT` | FK to `defined_project_workflow_group_options(id)` with cascade delete. |
| `create_date` | `DATETIME` | Defaults to current timestamp. |
| `update_date` | `DATETIME` | Auto-updated timestamp. |

Unique key: `(nvflare_job_workflow_group_id, workflow_group_option_id)`.

Indexes: `idx_njvwgo_job_group`, `idx_njvwgo_option`.

## Authentication and Security Assumptions

The active function and filter routes do not enforce authentication in the route code. `FilterRoutes.py` contains comments indicating these endpoints should be placed behind a bearer token, but there is no route-level token validation in the current implementation.

`/nvflare/jobs/submit` accepts function, filter, threshold, datasource, and workflow group data from the request body and validates only the shapes shown above before queueing the job. Function existence is validated when the job row is established by `NVFlareJobsManager` and `FunctionsManager`.
