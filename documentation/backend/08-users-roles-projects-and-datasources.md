# Users, Roles, Projects, and Datasources

## Files Covered

| File | Role |
| --- | --- |
| `app/main.py` | Defines `POST /user/role` and the `UserLookupRequest` model. |
| `app/api/routes/ProjectRoutes.py` | Defines `POST /projects/list` and `POST /projects/fhir/source`. |
| `app/core/mysql/managers/UsersManager.py` | Resolves usernames, roles, user IDs, project datasource assignments, and individual FHIR source records. |
| `app/core/mysql/managers/RolesManager.py` | Resolves role IDs to role names and caches role-name lookups by role ID. |
| `app/core/mysql/managers/ProjectsManager.py` | Builds project response objects including filter system metadata, supported functions, datasource groups, selected datasource group, and workflow groups. |
| `app/core/mysql/UserRole.py` | Defines supported role enum values. |
| `app/core/mysql/MySQLConnectionProvider.py` | Creates the user/project/datasource schema and seeds default roles, users, projects, datasource groups, workflow groups, and user FHIR source assignments. |
| `app/core/mysql/MySQLTable.py` | Provides shared table-name constants used by the managers. |

## Scope

This area covers the backend identity and project-context data needed by the frontend before a job is configured or submitted.

The current backend does not implement a full authentication system in these files. The role endpoint performs a username lookup against MySQL and returns role/project context. The `UsersManager.validate_login()` code comments identify this as a simple lookup and not production authentication.

## Role Model

Roles are defined in `app/core/mysql/UserRole.py`.

| Role | Value | Seeded description |
| --- | --- | --- |
| Client | `CLIENT` | A user who runs NVFlare client jobs. |
| Initiator | `INITIATOR` | A user who initiates NVFlare jobs. |
| Observer | `OBSERVER` | A user who is not a client and can view job results. |
| Admin | `ADMIN` | Administrative user who can approve registration of new client machines, view results, and initiate jobs. |

Roles are persisted in `defined_roles` and are seeded during `MySQLConnectionProvider` initialization by `_ensure_default_roles_exist()`.

`RolesManager.get_role_name(role_id)` reads `defined_roles.name` for the supplied role ID. Results are cached in the class-level `_role_name_cache` dictionary keyed by integer role ID.

## User Tables

### `defined_roles`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Internal role ID. |
| `name` | `VARCHAR(50) NOT NULL UNIQUE` | Role name, matching `UserRole` enum values. |
| `description` | `TEXT` | Human-readable role description. |
| `create_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |
| `update_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | Update timestamp. |

### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Internal user ID. |
| `username` | `VARCHAR(50) NOT NULL UNIQUE` | Username used by `/user/role` and project datasource lookup. |
| `password_hash` | `VARCHAR(255) NOT NULL` | Seeded users use `DISABLED`. The current role endpoint does not validate passwords. |
| `role_id` | `INT NOT NULL` | Foreign key to `defined_roles.id`. |
| `create_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |
| `update_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | Update timestamp. |

Foreign keys:

| Constraint | Column | References | Delete behavior |
| --- | --- | --- | --- |
| unnamed FK | `role_id` | `defined_roles(id)` | Default MySQL behavior. |

## Project Tables

### `defined_projects`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Internal project ID. |
| `name` | `VARCHAR(255) NOT NULL` | Project name. Unique via `uq_project_name`. |
| `description` | `TEXT` | Project description shown to callers. |
| `status` | `ENUM('ACTIVE','ARCHIVED') NOT NULL DEFAULT 'ACTIVE'` | Project lifecycle status. |
| `fixed` | `TINYINT(1) NOT NULL DEFAULT 0` | Whether the project is treated as fixed. |
| `function_restrictions_enabled` | `TINYINT(1) NOT NULL DEFAULT 0` | Whether project-specific function restrictions apply. |
| `filter_system_id` | `INT DEFAULT NULL` | Optional foreign key to `defined_filter_system.id`. |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | Update timestamp. |

Keys and indexes:

| Name | Type | Columns |
| --- | --- | --- |
| `uq_project_name` | Unique key | `name` |
| `fk_defined_projects_filter_system` | Foreign key | `filter_system_id` to `defined_filter_system(id)` with `ON DELETE SET NULL` |
| `idx_filter_system_id` | Index | `filter_system_id` |

## Datasource Tables

### `defined_project_datasource_groups`

Datasource groups are project-level labels used to distinguish multiple datasource assignments for the same project. The public biomarker pipeline seeds only `MSKChord`. On a fresh public database it is the first datasource group and receives id `1`, aligned with `standalone/client_utils/model_files/project_2/datasource_group_1`. Existing upgraded databases may retain an earlier row id.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Internal datasource group ID. |
| `project_id` | `INT NOT NULL` | Project owning the group. |
| `group_name` | `VARCHAR(255) NOT NULL` | Group label. Unique per project. |
| `is_default` | `TINYINT(1) NOT NULL DEFAULT 0` | Whether this is the project default group. |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | Update timestamp. |

Keys and indexes:

| Name | Type | Columns |
| --- | --- | --- |
| `fk_pdg_project` | Foreign key | `project_id` to `defined_projects(id)` with `ON DELETE CASCADE` |
| `uq_pdg_project_group_name` | Unique key | `project_id`, `group_name` |
| `idx_pdg_project` | Index | `project_id` |
| `idx_pdg_is_default` | Index | `is_default` |

Startup normalization in `_ensure_default_defined_project_datasource_groups()` renames the old biomarker group label in place if it exists and the current one does not (preserving the group's database id on upgraded installations):

| Old value | Current value |
| --- | --- |
| `MSK_Chord` | `MSKChord` |

### `users_fhir_source_by_project`

This table maps a user to a FHIR source for a project and optional datasource group.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Internal mapping ID. |
| `user_id` | `INT NOT NULL` | User owning the source assignment. |
| `project_id` | `INT NOT NULL` | Project for the source assignment. |
| `source` | `VARCHAR(1024) NOT NULL` | FHIR server base URL or JSON filename. |
| `datasource_group` | `INT NULL` | Optional datasource group ID. `NULL` is treated as the default source assignment for projects without explicit groups. |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |
| `update_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | Update timestamp. |

Keys and indexes:

| Name | Type | Columns |
| --- | --- | --- |
| `fk_ufsbp_user` | Foreign key | `user_id` to `users(id)` with `ON DELETE CASCADE` |
| `fk_ufsbp_project` | Foreign key | `project_id` to `defined_projects(id)` with `ON DELETE CASCADE` |
| `fk_ufsbp_datasource_group` | Foreign key | `datasource_group` to `defined_project_datasource_groups(id)` with `ON DELETE SET NULL` |
| `uq_ufsbp_user_project_group` | Unique key | `user_id`, `project_id`, `datasource_group` |
| `idx_ufsbp_project` | Index | `project_id` |
| `idx_ufsbp_user` | Index | `user_id` |
| `idx_ufsbp_datasource_group` | Index | `datasource_group` |

`MySQLConnectionProvider._ensure_users_fhir_source_by_project_schema()` also performs startup checks for this table. It adds the `datasource_group` column and supporting keys/foreign key when needed.

## Default Seed Data

### Default Users

`_ensure_test_users_exist()` always seeds these users when their roles exist:

| Username | Role | Password hash |
| --- | --- | --- |
| `client` | `CLIENT` | `DISABLED` |
| `initiator` | `INITIATOR` | `DISABLED` |
| `observer` | `OBSERVER` | `DISABLED` |

`_ensure_default_nvflare_clients()` runs only when `EnvironmentProvider.get_env()` is not `Environment.LOCAL`. It ensures the following NVFlare client/user pairings exist:

| NVFlare client | Username | Role | Description |
| --- | --- | --- | --- |
| `site1` | `client_site1` | `CLIENT` | `Auto-created for site1` |
| `site2` | `client_site2` | `CLIENT` | `Auto-created for site2` |
| `site3` | `initiator` | `INITIATOR` | `Auto-created for site3/intiiator` |

Because `client_site1` and `client_site2` are created by the non-local NVFlare client seed path, local environments only get those users if they already exist or are added another way.

### Default Projects

`_ensure_default_projects_exist()` seeds or updates these projects:

| Project | Status | Fixed | Function restrictions | Filter system |
| --- | --- | --- | --- | --- |
| `General Statistics` | `ACTIVE` | `1` | `1` | `DEFAULT` |
| `Biomarker Model Validation for Cancer Prognosis` | `ACTIVE` | `1` | `1` | `CANCER_TYPE` |

`General Statistics` enables these restricted functions:

| Function |
| --- |
| `SURVIVAL_ANALYSIS` |
| `CHI_SQUARE_TEST` |
| `MEAN` |
| `STANDARD_DEVIATION` |
| `PARTICIPATION_CONFIRMATION` |
| `T_TEST` |
| `ENCRYPTED_FILTERING` |
| `COUNT` |

`Biomarker Model Validation for Cancer Prognosis` enables these restricted functions:

| Function |
| --- |
| `SURVIVAL_ANALYSIS` |
| `LOGISTIC_CALIBRATION_STATISTICS` |

For the biomarker project, `SURVIVAL_ANALYSIS` receives fixed, variable, and override configuration through `defined_project_function_restrictions`.

Fixed configuration:

```json
{
  "is_server_contributing_to_aggregation": false,
  "is_biomarker_discovery": true,
  "model_key": "cox_lasso"
}
```

Variable configuration:

```json
{
  "cancer_type": {
    "type": "str",
    "default": "$PATIENT_DATA_CANCER_TYPE",
    "description": "Selected cancer type on Patient filter screen."
  },
  "model_type": {
    "type": "select",
    "options": ["Open Access", "Encrypted"],
    "default": "Encrypted",
    "description": "Open-access model: The training institution shares the model in the clear with all participants and computing server.\n\rEncrypted model: The training institution encrypts the model and neither the participants nor the computing server can retrieve the model weights."
  }
}
```

Override configuration:

```json
{
  "group_column_id": "risk_score_group",
  "time_column_id": "time",
  "censoring_column_id": "event",
  "time_grid_step": 1,
  "time_grid_max": 110
}
```

### Default Datasource Groups

Only the biomarker project has default explicit datasource groups in the current seed code.

| Project | Group | Default |
| --- | --- | --- |
| `Biomarker Model Validation for Cancer Prognosis` | `MSKChord` | `true` |

Projects without rows in `defined_project_datasource_groups` are treated as having no explicit datasource groups. For source records without an explicit group, `UsersManager` returns the datasource group name as `DEFAULT`.

### Default User FHIR Sources

`_ensure_default_user_fhir_sources()` seeds source assignments for users that exist in the database at startup.

#### General Statistics

| Username | Source | Datasource group |
| --- | --- | --- |
| `client_site1` | `/data/client/Survivability_FHIR_Data_part2.json` | `NULL` |
| `client_site2` | `/data/client/Survivability_FHIR_Data_part3.json` | `NULL` |
| `initiator` | `/data/client/Survivability_FHIR_Data_part1.json` | `NULL` |

#### Biomarker Model Validation for Cancer Prognosis

| Username | Source | Datasource group |
| --- | --- | --- |
| `client_site1` | `Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json` | `MSKChord` |
| `client_site2` | `Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json` | `MSKChord` |
| `initiator` | `Biomarker_MSKChord_FHIR_Data_training_bundle.json` | `MSKChord` |

For datasource-grouped records, the seed code looks up the group ID by `(project_id, group_name)` before inserting the row. If the group cannot be found, the row is handled as a `NULL` datasource group entry.

## `POST /user/role`

Defined in `app/main.py`.

### Purpose

Returns role and project datasource context for a username.

### Request Model

`UserLookupRequest`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `username` | `str` | Yes | Username to look up in `users.username`. |

Example request:

```json
{
  "username": "initiator"
}
```

### Backend Flow

1. `app/main.py` creates `UsersManager`.
2. `UsersManager.validate_login(username)` reads `users.role_id` by username.
3. `UsersManager.validate_login(username)` creates `RolesManager` and resolves `defined_roles.name` by role ID.
4. `UsersManager.get_user_id_by_username(username)` reads `users.id`.
5. `UsersManager.get_user_project_datasources(user_id)` reads project datasource assignments from `users_fhir_source_by_project`, `defined_projects`, and `defined_project_datasource_groups`.
6. The route closes the manager in a `finally` block.

### Successful Response

Status: `200`

Example response:

```json
{
  "username": "initiator",
  "role": "INITIATOR",
  "user_id": 3,
  "projects": [
    {
      "project_id": 1,
      "project_name": "General Statistics",
      "datasources": [
        {
          "source": "/data/client/Survivability_FHIR_Data_part1.json",
          "datasource_group_id": null,
          "datasource_group_name": "DEFAULT",
          "is_default_group": true
        }
      ]
    },
    {
      "project_id": 2,
      "project_name": "Biomarker Model Validation for Cancer Prognosis",
      "datasources": [
        {
          "source": "Biomarker_MSKChord_FHIR_Data_training_bundle.json",
          "datasource_group_id": 1,
          "datasource_group_name": "MSKChord",
          "is_default_group": true
        }
      ]
    }
  ]
}
```

IDs are database-generated. The values above show the response shape, not guaranteed IDs for every database.

### Error Responses

| Status | Body | Cause |
| --- | --- | --- |
| `404` | `{"error":"User not found"}` | `UsersManager.validate_login()` did not find a matching username. |
| `422` | FastAPI validation response | Request body does not include a valid `username` string. |
| `500` | FastAPI/internal error response | Unhandled database or runtime error. |

### Tables Read

| Table | Purpose |
| --- | --- |
| `users` | Resolve role ID and user ID by username. |
| `defined_roles` | Resolve role name by role ID. |
| `users_fhir_source_by_project` | Read datasource assignments for the user. |
| `defined_projects` | Add project IDs and names to datasource assignments. |
| `defined_project_datasource_groups` | Add datasource group names/default flags when present. |

## `POST /projects/list`

Defined in `app/api/routes/ProjectRoutes.py`.

### Purpose

Returns all projects and their configuration context. The route is marked `include_in_schema=False`, so it is hidden from generated OpenAPI docs.

### Request Body

No request model is defined. The endpoint accepts an empty POST body.

Example request:

```json
{}
```

### Backend Flow

1. `ProjectRoutes.get_projects_list()` creates `ProjectsManager`.
2. `ProjectsManager.get_project_list()` loads project rows ordered by project name.
3. `ProjectsManager` loads filter system metadata from `defined_filter_system` and `defined_filter_system_allowed_filter_types`.
4. For each project, `ProjectsManager._build_project()` resolves supported functions, datasource group summary, and workflow group summary.
5. The route returns `{"projects": ...}` using `jsonable_encoder()`.
6. The route closes the manager in a `finally` block.

### Successful Response

Status: `200`

Example response shape:

```json
{
  "projects": [
    {
      "id": 2,
      "name": "Biomarker Model Validation for Cancer Prognosis",
      "description": "This pipeline identifies high-impact genetic biomarkers associated with survival outcomes in a specific cancer type. This is done by leveraging penalized generalized linear models — including Cox proportional hazards regression and logistic regression — trained on an initiating site's local dataset. Candidate biomarkers and model findings are validated across distributed participant sites to compare survival outcomes, characterize exceptional responder patterns, and evaluate encrypted model-sharing workflows.",
      "status": "ACTIVE",
      "fixed": true,
      "function_restrictions_enabled": true,
      "filter_system": "CANCER_TYPE",
      "filter_system_allowed_filter_types": ["PATIENT_DATA"],
      "functions": [
        {
          "function": "LOGISTIC_CALIBRATION_STATISTICS",
          "configurable": false,
          "custom_configuration_fixed": null,
          "custom_configuration_variable": null,
          "override_configuration": null
        },
        {
          "function": "SURVIVAL_ANALYSIS",
          "configurable": false,
          "custom_configuration_fixed": {
            "is_server_contributing_to_aggregation": false,
            "is_biomarker_discovery": true,
            "model_key": "cox_lasso"
          },
          "custom_configuration_variable": {
            "cancer_type": {
              "type": "str",
              "default": "$PATIENT_DATA_CANCER_TYPE",
              "description": "Selected cancer type on Patient filter screen."
            },
            "model_type": {
              "type": "select",
              "options": ["Open Access", "Encrypted"],
              "default": "Encrypted",
              "description": "Open-access model: The training institution shares the model in the clear with all participants and computing server.\n\rEncrypted model: The training institution encrypts the model and neither the participants nor the computing server can retrieve the model weights."
            }
          },
          "override_configuration": {
            "group_column_id": "risk_score_group",
            "time_column_id": "time",
            "censoring_column_id": "event",
            "time_grid_step": 1,
            "time_grid_max": 110
          }
        }
      ],
      "datasource_groups_defined": true,
      "datasource_groups": [
        {
          "id": 1,
          "group_name": "MSKChord",
          "is_default": true
        }
      ],
      "default_datasource_group": {
        "id": 1,
        "group_name": "MSKChord",
        "is_default": true
      },
      "selected_datasource_group": null,
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
              "option_description": "The model fits a Cox proportional hazards regression on patient survival data, using L1 (LASSO) penalization on the mutation burden gene features while leaving clinical covariates unpenalized. The regularization strength is chosen via 5-fold cross-validation on the concordance index. This produces a sparse linear risk score which is used to stratify patients into High/Low risk groups at a cutoff optimized on the training set by log-rank test separation of their Kaplan-Meier survival curves.",
              "option_order": 0,
              "is_default": false
            },
            {
              "id": 2,
              "option_key": "logistic_reg",
              "option_label": "Lasso Logistic Regression",
              "option_value": "logistic_reg",
              "option_description": "The model fits a logistic regression to predict exceptional responders (ER) – patients whose survival time exceeds the training mean + 2 standard deviations, using L1 (LASSO) penalization uniformly on all features. The regularization strength is chosen via 5-fold cross-validation on the concordance index. This produces a sparse linear risk score which is used to stratify patients into High/Low risk groups at a cutoff optimized on the training set by log-rank test separation of their Kaplan-Meier survival curves.",
              "option_order": 1,
              "is_default": false
            }
          ]
        }
      ]
    }
  ]
}
```

IDs are database-generated. The response shape comes from `Project`, `ProjectFunctionCapability`, `ProjectDatasourceGroup`, `ProjectWorkflowGroup`, and `ProjectWorkflowGroupOption` dataclasses.

### Error Responses

| Status | Body | Cause |
| --- | --- | --- |
| `200` | `{"projects": []}` | No projects exist in the table. |
| `500` | FastAPI/internal error response | Unhandled database or runtime error. |

No explicit 404 response is implemented for this endpoint.

### Tables Read

| Table | Purpose |
| --- | --- |
| `defined_projects` | Base project records. |
| `defined_filter_system` | Filter system names/descriptions. |
| `defined_filter_system_allowed_filter_types` | Allowed filter types for each filter system. |
| `defined_project_function_restrictions` | Project-specific enabled functions and config JSON. |
| `defined_functions` | Function names used to map restrictions to `SupportedFunction` enum values. |
| `defined_project_datasource_groups` | Datasource group summaries and default group. |
| `defined_project_workflow_groups` | Active workflow group metadata. |
| `defined_project_workflow_group_options` | Active workflow options for each workflow group. |

## `POST /projects/fhir/source`

Defined in `app/api/routes/ProjectRoutes.py`.

### Purpose

Returns the FHIR source assignment for a username/project and optional datasource group. It can also execute a FHIR query against the resolved source when `execute_query` is provided and the source is a FHIR server URL.

The route is marked `include_in_schema=False`, so it is hidden from generated OpenAPI docs.

### Request Model

`ProjectFHIRSourceRequest`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `username` | `str` | Yes | Username to resolve. |
| `project_id` | `int` | Yes | Project ID to resolve against. |
| `datasource_group` | `int | None` | No | Datasource group ID. When omitted, the manager selects the default or `NULL` group source for the user/project. |
| `execute_query` | `str | None` | No | Optional FHIR query path to execute against a non-JSON source. |

Example request without query execution:

```json
{
  "username": "initiator",
  "project_id": 2,
  "datasource_group": 1
}
```

Example request with query execution:

```json
{
  "username": "initiator",
  "project_id": 1,
  "datasource_group": null,
  "execute_query": "Patient?_count=1"
}
```

### Backend Flow

1. `ProjectRoutes.get_project_fhir_source()` creates `UsersManager` and `ProjectsManager`.
2. `UsersManager.get_user_id_by_username(username)` resolves the user ID.
3. If no user is found, the route returns `404`.
4. `UsersManager.get_fhir_source_record(user_id, project_id, datasource_group)` resolves the source assignment.
5. If no source record is found, the route returns `404`.
6. `ProjectsManager.get_project_datasource_group_summary(project_id)` loads datasource group metadata for the project.
7. The route builds the response payload with source and datasource group context.
8. If `execute_query` is provided and the resolved source ends in `.json`, query execution is skipped.
9. If `execute_query` is provided and the resolved source does not end in `.json`, the route joins the source base URL and query path, performs `requests.get()` with `Accept: application/fhir+json, application/json`, and a `60` second timeout.
10. The route attempts to parse the upstream response as JSON. If parsing fails, it stores the upstream response text in `query_results`.
11. Both managers are closed in a `finally` block.

### Source Selection Rules

When `datasource_group` is omitted, `UsersManager.get_fhir_source_record()` selects one source for the user/project ordered by:

1. Explicit datasource group marked as default in `defined_project_datasource_groups`.
2. `NULL` datasource group.
3. Other datasource group IDs and source values.

When `datasource_group` is provided, the lookup requires an exact `users_fhir_source_by_project.datasource_group` match.

If the selected row has `datasource_group IS NULL` and no joined datasource group name, `UsersManager` returns `datasource_group_name` as `DEFAULT`.

### Successful Response Without Query Execution

Status: `200`

Example JSON-file response:

```json
{
  "username": "initiator",
  "user_id": 3,
  "project_id": 2,
  "source": "Biomarker_MSKChord_FHIR_Data_training_bundle.json",
  "source_type": "json",
  "datasource_group": 1,
  "datasource_group_name": "MSKChord",
  "is_default_group": true,
  "datasource_groups_defined": true,
  "datasource_groups": [
    {
      "id": 1,
      "group_name": "MSKChord",
      "is_default": true
    }
  ],
  "default_datasource_group": {
    "id": 1,
    "group_name": "MSKChord",
    "is_default": true
  }
}
```

Example FHIR-server response (when a user has configured an `http(s)://.../fhir` source; the seeded demo sources are local JSON files and take the JSON branch below):

```json
{
  "username": "initiator",
  "user_id": 3,
  "project_id": 1,
  "source": "https://example-fhir-server.test/fhir",
  "source_type": "fhir_server",
  "datasource_group": null,
  "datasource_group_name": "DEFAULT",
  "is_default_group": true,
  "datasource_groups_defined": false,
  "datasource_groups": [],
  "default_datasource_group": null
}
```

### Successful Response With Query Execution Skipped

Status: `200`

When the resolved source is a `.json` file and `execute_query` is provided:

```json
{
  "username": "initiator",
  "user_id": 3,
  "project_id": 2,
  "source": "Biomarker_MSKChord_FHIR_Data_training_bundle.json",
  "source_type": "json",
  "datasource_group": 1,
  "datasource_group_name": "MSKChord",
  "is_default_group": true,
  "datasource_groups_defined": true,
  "datasource_groups": [
    {
      "id": 1,
      "group_name": "MSKChord",
      "is_default": true
    }
  ],
  "default_datasource_group": {
    "id": 1,
    "group_name": "MSKChord",
    "is_default": true
  },
  "query_executed": false,
  "query_execution_message": "Query execution skipped because source is a json file."
}
```

### Successful Response With FHIR Query Execution

Status: `200`

The upstream FHIR status code is stored in `query_status_code`; the backend route itself still returns `200` unless an exception is raised.

```json
{
  "username": "initiator",
  "user_id": 3,
  "project_id": 1,
  "source": "https://example-fhir-server.test/fhir",
  "source_type": "fhir_server",
  "datasource_group": null,
  "datasource_group_name": "DEFAULT",
  "is_default_group": true,
  "datasource_groups_defined": false,
  "datasource_groups": [],
  "default_datasource_group": null,
  "query_executed": true,
  "executed_url": "https://example-fhir-server.test/fhir/Patient?_count=1",
  "query_status_code": 200,
  "query_results": {
    "resourceType": "Bundle"
  }
}
```

### Error Responses

| Status | Body | Cause |
| --- | --- | --- |
| `404` | `{"message":"User not found for username [<username>]"}` | Username does not exist in `users`. |
| `404` | `{"message":"No FHIR source found for username [<username>] project_id [<project_id>] and datasource_group [<datasource_group>]"}` | No matching row exists in `users_fhir_source_by_project`. |
| `422` | FastAPI validation response | Request body does not match `ProjectFHIRSourceRequest`. |
| `500` | FastAPI/internal error response | Unhandled database error, request error, timeout, invalid URL, or other runtime exception. |

The current route does not catch `requests.get()` exceptions. A failed upstream connection or timeout results in an unhandled exception response from FastAPI.

### Tables Read

| Table | Purpose |
| --- | --- |
| `users` | Resolve user ID by username. |
| `users_fhir_source_by_project` | Resolve source assignment. |
| `defined_project_datasource_groups` | Resolve group name/default flag and group summary. |

## Manager Behavior

### `UsersManager`

Constructor behavior:

1. Optionally receives a `JobStatusWriter`.
2. Calls `safe_status_update()` with `JobRunnerStatus.PROCESSING` and message `UsersManager: Initiating manager` when a writer is available.
3. Opens a pooled MySQL connection through `MySQLConnectionProvider.get_instance().get_connection()`.
4. Creates a `DictCursor`.

Cleanup:

- `complete()` closes the cursor and then closes the connection.

Public methods used by this area:

| Method | Purpose | Tables read |
| --- | --- | --- |
| `validate_login(username)` | Returns role name for username or `None`. | `users`, `defined_roles` through `RolesManager` |
| `get_user_id_by_username(username)` | Returns integer user ID or `None`. | `users` |
| `get_fhir_source(user_id, project_id, datasource_group=None)` | Returns only the source string or `None`. | `users_fhir_source_by_project`, `defined_project_datasource_groups` |
| `get_fhir_source_record(user_id, project_id, datasource_group=None)` | Returns source, datasource group ID/name, and default-group flag. | `users_fhir_source_by_project`, `defined_project_datasource_groups` |
| `get_user_project_datasources(user_id)` | Returns projects and datasource assignments for a user. | `users_fhir_source_by_project`, `defined_projects`, `defined_project_datasource_groups` |

### `RolesManager`

Constructor behavior:

1. Opens a pooled MySQL connection.
2. Creates a `DictCursor`.

Cleanup:

- `complete()` closes the cursor and connection.

Public methods:

| Method | Purpose | Tables read |
| --- | --- | --- |
| `get_role_name(role_id)` | Returns role name for role ID or `None`. Uses `_role_name_cache` before querying. | `defined_roles` |

### `ProjectsManager`

Constructor behavior:

1. Opens a pooled MySQL connection.
2. Creates a `DictCursor`.

Cleanup:

- `complete()` closes the cursor and connection.

Primary public methods:

| Method | Purpose | Tables read |
| --- | --- | --- |
| `get_project_list()` | Returns all project dataclasses ordered by project name. | `defined_projects`, filter-system tables, function restriction tables, datasource group tables, workflow group tables |
| `get_project(project_id, datasource_group_id=None)` | Returns one project dataclass or `None`. | Same project-supporting tables as `get_project_list()` |
| `get_defined_project_datasource_groups(project_id)` | Returns datasource group dataclasses ordered by default first, then group name/id. | `defined_project_datasource_groups` |
| `get_default_project_datasource_group(project_id)` | Returns the default datasource group dataclass or `None`. | `defined_project_datasource_groups` |
| `get_project_datasource_group_by_id(project_id, datasource_group_id)` | Returns a datasource group by ID for the project or `None`. | `defined_project_datasource_groups` |
| `get_project_datasource_group_summary(project_id)` | Returns `datasource_groups_defined`, all groups, and default group. | `defined_project_datasource_groups` |
| `get_defined_project_workflow_groups(project_id)` | Returns active workflow groups and active options. | `defined_project_workflow_groups`, `defined_project_workflow_group_options` |
| `get_project_workflow_group_summary(project_id)` | Returns `workflow_groups_defined` and workflow groups. | `defined_project_workflow_groups`, `defined_project_workflow_group_options` |

## Authentication and Authorization Assumptions

Current backend behavior in these files:

- `/user/role` accepts a username and does not validate a password, token, session, or signed identity claim.
- `/projects/list` does not receive a user context and does not enforce per-user project authorization.
- `/projects/fhir/source` receives `username` in the request body and trusts it for lookup.
- Route-level authorization is not enforced in `ProjectRoutes.py`.
- The route files documented here do not use FastAPI dependency-based auth guards.

These endpoints should be treated as current development-state role/project-context endpoints, not a completed production authorization layer.

## Frontend Integration Contract

The frontend caller files are not included in `backend.zip`, so exact component names are not defined by this backend package. The backend contract exposed to the frontend is:

| Backend endpoint | Frontend use |
| --- | --- |
| `POST /user/role` | Resolve role, user ID, and project datasource context after username/login context is known. |
| `POST /user/datasource/apply` | Save changed datasource values from the UserSettings page and return refreshed project datasource context. |
| `POST /projects/list` | Populate available projects, supported functions, filter-system constraints, datasource group selectors, and workflow group selectors. |
| `POST /projects/fhir/source` | Resolve the current user's FHIR server URL or local JSON source for the selected project and datasource group. Optionally proxy a simple FHIR query for non-JSON sources. |
| `POST /clients/datasource/source` | Internal NVFlare server lookup that resolves the runtime datasource for a client/site, project, and datasource group. |

## Operational Notes

- All three endpoints create managers inside the route handler and close them in `finally` blocks.
- All MySQL reads use parameterized queries for runtime request values.
- `jsonable_encoder()` is used in project routes so dataclasses and enum values can be serialized into JSON responses.
- Project IDs, datasource group IDs, workflow group IDs, and user IDs are database-generated and should not be hardcoded in callers.
- `source_type` is derived by checking whether the resolved source lowercased string ends with `.json`.
- For projects without explicit datasource groups, the group list is empty, `datasource_groups_defined` is `false`, and default source rows are represented with `datasource_group_name: "DEFAULT"`.


## User Settings Datasource Updates

The current UserSettings flow writes datasource values to `users_fhir_source_by_project` through `POST /user/datasource/apply`.

Request identity can be either:

| Field | Purpose |
| --- | --- |
| `user_id` | Preferred direct user identity from `UserRoleContext`. |
| `username` | Fallback identity when `user_id` is unavailable. |

Each update contains:

| Field | Purpose |
| --- | --- |
| `project_id` | Target project. |
| `datasource_group_id` | Target datasource group, or `null` for project-level source. |
| `source` | Runtime JSON path or FHIR `/fhir` URL. |

The route validates each source, upserts the current user's datasource records, commits as one operation, and returns the refreshed project datasource payload from `UsersManager.get_user_project_datasources(user_id)`.

JSON sources must end with `.json`. FHIR sources must be `http` or `https` URLs ending in `/fhir` after trailing slashes are removed.

## User Settings Model File Source Updates

The current UserSettings flow also writes initiator-local model file source paths to `users_model_file_source_by_project` through `POST /user/model-files/apply`.

Request identity can be either `user_id` or `username`, matching the datasource apply behavior.

Each model file update contains:

| Field | Purpose |
| --- | --- |
| `project_id` | Target project. |
| `datasource_group_id` | Target datasource group. |
| `model_file_lookup_key` | Lookup dimension, currently cancer type for biomarker models. |
| `model_file_lookup_value` | Lookup value, such as `Non-Small Cell Lung Cancer`. |
| `model_key` | Model family, such as `cox_lasso` or `logistic_reg`. |
| `artifact_type` | Artifact role, such as `weights` or `cutoff`. |
| `source` | Initiator-local filesystem path for the artifact. |

The backend stores these source paths but does not open them during staging. At runtime, the generated job supplies them to the initiator/leader site through `app_client/custom/model_file_sources.json`, and the model-upload workflow reads the files from the initiator's filesystem.

## NVFlare Runtime Datasource Lookup

NVFlare clients do not read a client-side FHIR base config file. At job runtime:

1. The client reads `custom/filters.json` to get `project_id` and selected datasource group.
2. The client sends an aux request to the NVFlare server on `duality.datasource.lookup`.
3. The server calls `POST /clients/datasource/source` with `client_name`, `project_id`, and `datasource_group_id`.
4. The backend maps `client_name` through `nvflare_clients` to a user.
5. `UsersManager.get_fhir_source_record()` returns the current datasource row.
6. The server replies to the client with the datasource string.

The `client_name` mapping is:

| Client name | User |
| --- | --- |
| `site1` | `client_site1` |
| `site2` | `client_site2` |
| `site3` | `initiator` |

`site3` is the initiator.

For local biomarker JSON data, the datasource returned to a client must be the container-visible path under `/data/client/`, not the host-side staging path under `nvflare_stage/data/`.
