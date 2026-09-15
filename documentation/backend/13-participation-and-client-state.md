# Participation and Client State

## Files Covered

| File | Role |
| --- | --- |
| `app/api/routes/ClientRoutes.py` | Defines client connection status, participation status, and participation submission endpoints. |
| `app/core/mysql/managers/ParticipationManager.py` | Reads and writes client participation confirmations, participation function mappings, function config mappings, and role-selection flags. |
| `app/core/mysql/managers/NVFlareClientEmitManager.py` | Resolves NVFlare-assigned job IDs back to internal job runner IDs and writes progress/status messages from NVFlare webhook payloads. |
| `app/core/job_runner/job_tasks/NVFlareParticipationJobTask.py` | Runs the participation confirmation workflow before the main NVFlare analytics job is staged. |
| `app/core/nvflare/NVFlareClientSnapshot.py` | Calls the NVFlare admin kit, parses client connection status, and merges live NVFlare state with registered MySQL clients. |
| `app/core/job_runner/job_tasks/NVFlareJobTask.py` | Invokes participation confirmation before staging and submitting the main analytics job. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobStager.py` | Injects selected client participation behavior into generated NVFlare job config. |
| `app/core/mysql/MySQLConnectionProvider.py` | Creates participation/client tables, inserts default NVFlare clients, and ensures participation lookup indexes. |

## Overview

The backend separates client state into two related concerns:

1. **Connection state**: whether NVFlare clients and the NVFlare server are currently visible through the admin kit status command.
2. **Participation state**: whether registered clients have accepted, rejected, or still need to respond for a specific job definition.

Connection state is resolved dynamically by `NVFlareClientSnapshot`. Participation state is persisted in MySQL through `ParticipationManager`. The job submission flow combines both before running the main NVFlare analytics job.

Participation is tied to the exact job context the backend records:

- selected project filter set
- selected functions
- selected function configuration values
- optional threshold configuration
- contributing party selection
- analyzing party selection

A participation response for one function/filter/configuration combination does not automatically satisfy another combination unless the stored function/config mapping matches the request rules implemented in `ParticipationManager`.

## Client Connection Snapshot

`NVFlareClientSnapshot.get_clients(username=None)` builds the client list returned by `/clients/connection/status` and optionally by `/clients/participation/status`.

The snapshot flow is:

1. Create `NVFlareAdminKitManager`.
2. Run `check_status server` with a timeout of 20 seconds.
3. Parse the NVFlare output table with `CLIENT_ROW_RE`.
4. Create a synthetic server row named `Server`.
5. Read registered clients from MySQL using `ParticipationManager.clients_list()`.
6. Read initiator-owned client names with `ParticipationManager.get_all_initiator_client_names()`.
7. If `username` is supplied, read the client names mapped to that username with `ParticipationManager.get_client_names_for_username(username)`.
8. Insert the server row at the top of the response.
9. Mark live NVFlare client rows with registration, initiator, and submitted-user flags.
10. Append MySQL-registered clients missing from the NVFlare output with `last_connect_time: "0"`.

The server row uses these fields:

| Field | Meaning |
| --- | --- |
| `client_name` | Always `Server`. |
| `last_connect_time` | `SERVER_ONLINE` when the admin command succeeds, otherwise `0`. |
| `registered` | Always `False` for the synthetic server row. |
| `is_server` | Always `True` for the synthetic server row. |
| `server_online` | `True` when the admin command returns exit code 0. |
| `connection_error` | Present when the admin command fails or raises an exception. |

Client rows parsed from NVFlare contain:

| Field | Meaning |
| --- | --- |
| `client_name` | Client name parsed from the NVFlare table. |
| `last_connect_time` | Last connect time parsed from the NVFlare table. |
| `registered` | `True` if the name exists in `nvflare_clients`; otherwise `False`. |
| `is_initiator` | Present and `True` when the client is mapped to a user with role `INITIATOR`. |
| `is_submitted_user` | Present and `True` when `username` maps to that client. |

MySQL-registered clients that do not appear in the NVFlare status output are returned with `last_connect_time: "0"` and `registered: True`.

## Endpoint Inventory

| Method | Path | Handler | File | Purpose |
| --- | --- | --- | --- | --- |
| `POST` | `/clients/connection/status` | `list_clients_connection_status` | `ClientRoutes.py` | Returns current NVFlare server/client connection state merged with registered clients. |
| `POST` | `/clients/participation/status` | `list_clients_status` | `ClientRoutes.py` | Returns connection state plus participation status for a requested job context. |
| `POST` | `/clients/participation/submit` | `submit_participation` | `ClientRoutes.py` | Records a client participation confirmation for a filter/function/configuration context. |

All three routes are declared with `include_in_schema=False`, so they are intentionally hidden from generated FastAPI OpenAPI output.

`ClientRoutes.py` contains comments stating `Put behind bearer token`, but the current route code does not enforce bearer-token authentication. `/clients/participation/submit` performs a password check only when `EnvironmentProvider.get_env()` is not `Environment.LOCAL`.

## `POST /clients/connection/status`

### Purpose

Returns the current NVFlare client/server connection snapshot. This endpoint is used by the frontend to determine which clients are registered, online/offline, mapped to the submitted user, and mapped to initiator users.

### Request Body

The request body is optional.

```json
{
  "username": "initiator"
}
```

| Field | Required | Behavior |
| --- | --- | --- |
| `username` | No | When supplied, matching client rows are marked with `is_submitted_user: true`. |

### Backend Flow

1. Normalize `payload.username` if present.
2. Call `NVFlareClientSnapshot().get_clients(username=username)`.
3. Return `{"clients": clients_snapshot}`.

### Success Response Example

```json
{
  "clients": [
    {
      "client_name": "Server",
      "last_connect_time": "SERVER_ONLINE",
      "registered": false,
      "is_server": true,
      "server_online": true
    },
    {
      "client_name": "site1",
      "last_connect_time": "2026-04-28 18:10:20",
      "registered": true
    },
    {
      "client_name": "site3",
      "last_connect_time": "2026-04-28 18:10:25",
      "registered": true,
      "is_initiator": true,
      "is_submitted_user": true
    }
  ]
}
```

### Error Behavior

If the route itself raises an exception, it returns HTTP 500:

```json
{
  "error": "Failed to fetch client status: [...]"
}
```

If `check_status server` fails inside `NVFlareClientSnapshot`, the snapshot still returns a server row with `server_online: false`, `last_connect_time: "0"`, and a `connection_error` field when available.

## `POST /clients/participation/status`

### Purpose

Returns participation state for clients for a specific job context. The endpoint can return only participation rows, or it can merge participation fields into the current connection snapshot.

### Request Body Example

```json
{
  "username": "initiator",
  "include_connection_state": true,
  "participation_status": {
    "project_id": 1,
    "filters": {
      "Cancer Type": "Breast Carcinoma"
    },
    "functions": {
      "BIOMARKER_ENC_RISK_GROUP_COMPUTATION": [
        {
          "model_type": "encrypted",
          "model_key": "cox_lasso"
        }
      ]
    },
    "threshold_config": {
      "method": "COUNT",
      "threshold": 2
    },
    "non_contributing_clients": ["site2"],
    "exclude_analyzing_clients": []
  }
}
```

### Request Fields

| Field | Required | Behavior |
| --- | --- | --- |
| `username` | No | Passed to `NVFlareClientSnapshot` when connection state is included. |
| `include_connection_state` | No | Defaults to `true`. When false, the endpoint skips the NVFlare connection snapshot and returns participation-only rows. |
| `participation_status` | No | If missing or not an object, the endpoint returns the current connection snapshot only. |
| `participation_status.project_id` | Yes when `participation_status` is supplied | Used by `FiltersManager` to resolve the filter ID. Missing or invalid values return HTTP 400. |
| `participation_status.filters` | Yes for meaningful participation lookup | Used with `project_id` to resolve the `defined_fhir_filters` row. |
| `participation_status.functions` | Yes for meaningful participation lookup | Must be an object mapping function IDs/names to non-empty config object arrays. Missing or invalid values return the current client payload without participation matching. |
| `participation_status.threshold_config` | No | If supplied with valid `method` and `threshold`, participation matching requires an existing matching threshold row. |
| `participation_status.non_contributing_clients` | No | Client-name array used to filter participation rows whose stored `contributing_party` flag matches the current selection. |
| `participation_status.exclude_analyzing_clients` | No | Client-name array used to filter participation rows whose stored `analyzing_party` flag matches the current selection. |

### Function Map Matching

The route canonicalizes `participation_status.functions` before matching participation rows.

Input shape:

```json
{
  "MEAN": [
    { "model_type": "open_access" },
    { "rounds": "3" }
  ]
}
```

Canonicalized shape:

```json
{
  "MEAN": {
    "model_type": "open_access",
    "rounds": "3"
  }
}
```

All config objects for the same function are merged into one property map. Matching then uses `ParticipationManager.list_client_participation_status()`.

The route uppercases function IDs and trims property keys, but it does not change the case of property names or values. `ParticipationManager` folds case on both sides when it compares them against stored config rows; see `Config Property Case Folding`.

### Backend Flow

1. Parse the raw request body.
2. Resolve `username`.
3. Resolve `include_connection_state`; default is `true`.
4. Optionally call `NVFlareClientSnapshot().get_clients(username=username)`.
5. Validate `participation_status`.
6. Validate and convert `project_id`.
7. Parse optional `threshold_config` into a `Threshold` object when possible.
8. Validate and normalize the functions map.
9. Resolve `filter_id` using `FiltersManager(project_id=project_id, filters=filters).get_id_by_filters()`.
10. Query matching participation rows with `ParticipationManager.list_client_participation_status()`.
11. Filter returned participation rows by `non_contributing_clients` and `exclude_analyzing_clients` so the stored party flags match the current role selection.
12. Merge `participation`, `contributing_party`, and `analyzing_party` into connection rows when connection state is included.
13. Return `{"clients": clients_snapshot}`.

### Success Response with Connection State

```json
{
  "clients": [
    {
      "client_name": "Server",
      "last_connect_time": "SERVER_ONLINE",
      "registered": false,
      "is_server": true,
      "server_online": true,
      "participation": null,
      "contributing_party": true,
      "analyzing_party": true
    },
    {
      "client_name": "site1",
      "last_connect_time": "2026-04-28 18:10:20",
      "registered": true,
      "participation": "ACCEPT",
      "contributing_party": true,
      "analyzing_party": true
    },
    {
      "client_name": "site2",
      "last_connect_time": "0",
      "registered": true,
      "participation": null,
      "contributing_party": true,
      "analyzing_party": true
    }
  ]
}
```

### Success Response Without Connection State

When `include_connection_state` is false, the response contains only clients that have matching participation rows:

```json
{
  "clients": [
    {
      "client_name": "site1",
      "participation": "ACCEPT",
      "contributing_party": true,
      "analyzing_party": true
    }
  ]
}
```

### Error Behavior

Missing or invalid `project_id` returns HTTP 400:

```json
{
  "status": "FAILURE",
  "error": "project_id is required"
}
```

Unhandled exceptions return HTTP 500:

```json
{
  "error": "Failed to fetch client status: [...]"
}
```

If `participation_status` is missing, `functions` is missing/invalid, normalized functions are empty, or the filter cannot be resolved, the route returns the available client snapshot without matching participation records.

## `POST /clients/participation/submit`

### Purpose

Records a client response to a participation request.

The route writes the participation header row and synchronizes the associated function and function-config mapping rows. It supports both user-driven responses and NVFlare participation-confirmation job callbacks.

### Request Body Example

```json
{
  "client_name": "site1",
  "filter_id": 12,
  "confirmation": "ACCEPT",
  "functions_map": {
    "BIOMARKER_ENC_RISK_GROUP_COMPUTATION": {
      "model_type": "encrypted",
      "model_key": "cox_lasso"
    }
  },
  "threshold_config": {
    "method": "COUNT",
    "threshold": 2
  }
}
```

Non-local deployments must also include `$pw` matching the current MySQL password value:

```json
{
  "$pw": "mysql-password-value",
  "client_name": "site1",
  "filter_id": 12,
  "confirmation": "ACCEPT",
  "functions_map": {
    "MEAN": {
      "model_type": "open_access"
    }
  }
}
```

### Request Fields

| Field | Required | Behavior |
| --- | --- | --- |
| `$pw` | Required outside `LOCAL` | Compared against the MySQL password from `ResourceConfigProvider.get_mysql_config()`. The route refreshes the cached config once before rejecting. |
| `client_name` | Yes | Must resolve to an existing row in `nvflare_clients`. `Server` is not recorded as a participant. |
| `functions_map` | Yes | Must be an object mapping function identifiers to configuration maps. Normalized through `_normalize_functions_map()`. |
| `filter_id` | Yes | Links the participation row to `defined_fhir_filters.id`. |
| `confirmation` | Yes | Must match a `Confirmation` enum member: `PENDING`, `ACCEPT`, or `REJECT`. The error message currently says `ACCEPT or REJECT`, but the enum also contains `PENDING`. |
| `threshold_config` | No | If supplied with valid method/threshold values, persisted or reused through `ThresholdManager`. |

The submit route currently does not read `contributing_party` or `analyzing_party` from the request body. Direct submissions call `ParticipationManager.record_participation()` without those arguments, so existing party flags are preserved on duplicate rows and default to true for new rows.

### Backend Flow

1. Parse request JSON.
2. In non-local environments, validate `$pw` against the MySQL password.
3. Validate required fields: `client_name`, `functions_map`, `filter_id`, and `confirmation`.
4. Validate that `functions_map` is an object.
5. Normalize `functions_map` with `_normalize_functions_map()` from `FunctionsManager.py`.
6. Validate that at least one function remains after normalization.
7. Validate `confirmation` against the `Confirmation` enum.
8. Parse optional `threshold_config`.
9. Call `ParticipationManager.record_participation()`.
10. Return the participation row ID.
11. Close `ParticipationManager` in `finally`.

### Success Response

```json
{
  "status": "Participation recorded",
  "id": 47
}
```

### Error Responses

Missing required field:

```json
{
  "status": "Please provide client_name"
}
```

Invalid function payload:

```json
{
  "status": "functions must be an object mapping function_id -> { args }"
}
```

Invalid confirmation:

```json
{
  "status": "Confirmation must be ACCEPT or REJECT"
}
```

Unauthorized non-local submission:

```json
{
  "detail": "Unauthorized"
}
```

Exception while writing participation:

```json
{
  "status": "Exception occurred while recording participation",
  "log": ["Traceback lines..."]
}
```

## ParticipationManager

`ParticipationManager` owns participation persistence and participation lookup logic.

### Connection Ownership

The constructor gets a MySQL connection from `MySQLConnectionProvider.get_instance().get_connection()` and creates a dictionary cursor. Callers must call `complete()` to close the cursor and connection.

### Public Methods

| Method | Behavior |
| --- | --- |
| `clients_list()` | Returns registered NVFlare client names from `nvflare_clients`. |
| `resolve_client_id(client_name)` | Resolves a client name to `nvflare_clients.id`. |
| `record_participation(client_name, filter_id, functions_map, confirmation, threshold=None, contributing_party=None, analyzing_party=None)` | Upserts a participation row and synchronizes function/config mappings. |
| `record_pending_participation(client_name, filter_id, functions_map, contributing_party, analyzing_party, threshold=None)` | Records a `PENDING` participation row with explicit party-role flags. |
| `list_client_participation_status(functions, filter_id, confirmation=None, clients_snapshot=None, threshold=None)` | Returns rows matching function/config/filter/threshold criteria, optionally excluding offline clients from a supplied snapshot. |
| `list_clients_with_accepted_participation_csv(functions, filter_id, clients_snapshot, threshold=None)` | Returns comma-separated client names whose matching participation is `ACCEPT`. |
| `list_clients_without_participation_csv(functions, filter_id, clients_snapshot, threshold=None)` | Returns online clients that lack any matching participation record. |
| `get_all_initiator_client_names()` | Returns client names mapped to users with role `INITIATOR`. |
| `get_client_names_for_username(username)` | Returns client names mapped to the supplied username. |
| `auto_accept_participation_for_username(username, filter_id, functions_map, threshold=None)` | Records `ACCEPT` for the first client mapped to the submitting username. |

### Participation Matching Rule

A participation row matches a request when all of these are true:

1. The participation row is tied to the same `filter_id`.
2. The stored mapped function set includes all requested function names.
3. For each requested function, at least one mapped function config set includes all requested property/value pairs, compared case-insensitively.
4. If a threshold is supplied, a matching `threshold_configs` row must already exist and the participation row must reference that `threshold_config_id`.
5. If a `confirmation` filter is supplied, the row must have that confirmation value.
6. If a client snapshot is supplied, non-server clients with `last_connect_time` equal to `0` are excluded.

Extra stored functions or config values do not prevent a match as long as all requested functions and property/value pairs are covered.

### Config Matching Flow

`list_client_participation_status()` resolves the rule above in three stages:

1. `_normalize_map_for_participation()` uppercases and trims function names, trims property keys, coerces `None` values to an empty string, and merges every config object supplied for the same function into one property map. Functions with an empty property map are dropped, and an empty result returns no rows.
2. `_candidates_by_functions_only()` runs one SQL query that narrows participation rows by `filter_id`, optional `confirmation`, optional `threshold_config_id`, and excluded client names, keeping only rows whose distinct mapped function names cover every requested function.
3. `_matching_participation_ids_by_configs()` takes those candidate participation IDs, fetches the `property_name`/`property_value` rows for the requested functions in one query, groups them by `(participation_id, function_name, config_set_id)`, and keeps a participation row when, for every requested function, at least one of its config sets is a superset of that function's required pairs.

Only participation IDs that survive stage 3 are returned.

### Config Property Case Folding

`ParticipationManager._config_pair(prop, val)` applies `str(...).strip().casefold()` to both the property name and the property value. It is used on both sides of the stage-3 comparison: on the requested pairs when `required_by_fn` is built, and on the `property_name`/`property_value` values read back from the database.

The fold is required because `defined_function_config_properties` is declared `DEFAULT CHARSET=utf8mb4` with no explicit `COLLATE`, so `property_name` and `property_value` live under a case-insensitive collation. `UNIQUE KEY uq_func_prop_val (function_id, property_name, property_value)` therefore stores only one casing per logical pair, and an existing row can differ in case from the value a later request submits. SQL comparisons resolve that difference through the collation, but stage 3 compares the returned rows against the requested pairs as Python sets, and Python string comparison is case-sensitive. Without folding both sides, a stored row would be selected by the query and then rejected by the set comparison.

This matters for job-history and participation lookups that span a change in the casing a caller submits. The frontend `CHI_SQUARE_TEST`/`T_TEST` category-column option was corrected from `medication` to `Medication`; the stored property rows kept their original casing, and case-folded matching keeps those participation records reachable.

### Write Behavior

`record_participation()`:

1. Ignores `Server` by returning `None`.
2. Resolves `client_name` to `nvflare_clients.id`.
3. Normalizes the function map.
4. Persists or reuses the threshold row when a threshold is supplied.
5. Upserts `nvflare_client_participation` by `(client_id, filter_id)`.
6. Updates `confirmation` and `threshold_config_id` on duplicate rows.
7. Preserves existing `contributing_party` and `analyzing_party` values on duplicate rows when those arguments are `None`.
8. Resolves requested function IDs through `FunctionsManager`.
9. Synchronizes `nvflare_client_participation_functions` so the participation row maps to the desired functions.
10. Creates or reuses defined function config sets through `FunctionsManager.get_or_create_function_config_set_id()`.
11. Synchronizes `nvflare_client_participation_function_configs` so the participation row maps to the desired config sets.
12. Commits on success and rolls back on exception.

## Database Tables

### `nvflare_clients`

Created by `MySQLConnectionProvider`.

| Column | Definition | Purpose |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Internal client ID. |
| `client_name` | `VARCHAR(100) NOT NULL UNIQUE` | NVFlare client/site name. |
| `user_id` | `INT NOT NULL` | Links client to `users.id`. |
| `description` | `TEXT` | Human-readable client description. |
| `create_date` | `DATETIME DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `FOREIGN KEY (user_id)` | References `users(id)`. |
| `idx_user_id` | Index on `user_id`. |

### `nvflare_project_client_exclusions`

Created by `MySQLConnectionProvider`, but not directly used in the current route code documented here.

| Column | Definition | Purpose |
| --- | --- | --- |
| `project_id` | `INT NOT NULL` | Project ID. |
| `client_id` | `INT NOT NULL` | Client ID. |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(project_id, client_id)`. |
| `fk_npce_project` | `project_id` references `defined_projects(id)` with `ON DELETE CASCADE`. |
| `fk_npce_client` | `client_id` references `nvflare_clients(id)` with `ON DELETE CASCADE`. |
| `idx_npce_client` | Index on `client_id`. |

### `nvflare_client_participation`

Stores the header row for a client's participation state for a filter context.

| Column | Definition | Purpose |
| --- | --- | --- |
| `id` | `INT AUTO_INCREMENT PRIMARY KEY` | Participation row ID. |
| `client_id` | `INT NOT NULL` | Links to `nvflare_clients.id`. |
| `filter_id` | `INT NOT NULL` | Links to `defined_fhir_filters.id`. |
| `threshold_config_id` | `INT NULL` | Optional link to `threshold_configs.id`. |
| `confirmation` | `ENUM('PENDING','ACCEPT','REJECT') NOT NULL DEFAULT 'PENDING'` | Client participation state. |
| `contributing_party` | `TINYINT(1) NOT NULL DEFAULT 1` | Whether the client is expected to contribute data to aggregation. |
| `analyzing_party` | `TINYINT(1) NOT NULL DEFAULT 1` | Whether the client is expected to receive/analyze final results. |
| `create_date` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| `uq_client_filter` | Unique key on `(client_id, filter_id)`. |
| `fk_ncp_client` | `client_id` references `nvflare_clients(id)` with `ON DELETE CASCADE`. |
| `fk_ncp_filter` | `filter_id` references `defined_fhir_filters(id)` with `ON DELETE CASCADE`. |
| `fk_ncp_threshold` | `threshold_config_id` references `threshold_configs(id)` with `ON DELETE SET NULL`. |
| `idx_ncp_threshold` | Index on `threshold_config_id`. |
| `idx_ncp_filter_confirmation_threshold` | Index on `(filter_id, confirmation, threshold_config_id, id, client_id)`. |

The unique key is only `(client_id, filter_id)`. Function/config mappings are synchronized for that row when participation is recorded.

### `nvflare_client_participation_functions`

Maps participation rows to supported functions.

| Column | Definition | Purpose |
| --- | --- | --- |
| `participation_id` | `INT NOT NULL` | Links to `nvflare_client_participation.id`. |
| `function_id` | `INT NOT NULL` | Links to `defined_functions.id`. |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(participation_id, function_id)`. |
| `fk_ncpf_participation` | `participation_id` references `nvflare_client_participation(id)` with `ON DELETE CASCADE`. |
| `fk_ncpf_function` | `function_id` references `defined_functions(id)` with `ON DELETE RESTRICT`. |
| `idx_ncpf_function` | Index on `function_id`. |

### `nvflare_client_participation_function_configs`

Maps participation rows to defined function config sets.

| Column | Definition | Purpose |
| --- | --- | --- |
| `participation_id` | `INT NOT NULL` | Links to `nvflare_client_participation.id`. |
| `function_config_id` | `INT NOT NULL` | Links to `defined_function_config_sets.id`. |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Primary key | `(participation_id, function_config_id)`. |
| `fk_npfc_part` | `participation_id` references `nvflare_client_participation(id)` with `ON DELETE CASCADE`. |
| `fk_npfc_fn_cfg` | `function_config_id` references `defined_function_config_sets(id)` with `ON DELETE RESTRICT`. |
| `idx_npfc_part` | Index on `participation_id`. |
| `idx_npfc_fn_cfg` | Index on `function_config_id`. |

## Default Client Seed Data

`MySQLConnectionProvider._ensure_default_nvflare_clients()` inserts or updates three default NVFlare clients:

| Client Name | Username | Role | Description |
| --- | --- | --- | --- |
| `site1` | `client_site1` | `CLIENT` | `Auto-created for site1` |
| `site2` | `client_site2` | `CLIENT` | `Auto-created for site2` |
| `site3` | `initiator` | `INITIATOR` | `Auto-created for site3/intiiator` |

If the mapped user does not exist, the seed routine creates it with password hash `DISABLED`. The client rows are then inserted into `nvflare_clients` or updated on duplicate `client_name`.

## Participation Confirmation Job Flow

The main analytics job does not immediately stage and submit the analytics template. `NVFlareJobTask.run_nvflare_job()` first creates a participation confirmation task.

### Main Job Integration

`NVFlareJobTask.run_nvflare_job()`:

1. Saves or resolves the submitted filters through `FiltersManager.save_or_get_filter_id()`.
2. Creates the internal NVFlare job record through `NVFlareJobsManager.establish_job_entry_id()`.
3. Logs datasource/workflow context through `NVFlareJobsManager.log_job_run_context()`.
4. Creates `NVFlareParticipationJobTask` with project ID, datasource group ID, functions map, filter ID, NVFlare provision object, job manager, status writer, threshold, username, and selected client role lists.
5. Calls `get_participation_client_list()`.
6. Fails the main job if the returned participating client CSV is empty.
7. Stages the main analytics job with only the participating client list.
8. Passes `non_contributing_clients` and `exclude_analyzing_clients` into `NVFlareJobStager` for main job packaging.

### Participation Task Behavior

`NVFlareParticipationJobTask.get_participation_client_list()` performs these steps:

1. Reads the current client snapshot from `NVFlareClientSnapshot`.
2. Removes clients that are in both `non_contributing_clients` and `exclude_analyzing_clients`. These clients are excluded from both contribution and analysis roles, so they do not receive participation requests.
3. Creates `ParticipationManager`.
4. Logs participation initialization through `JobStatusWriter`.
5. If `username` is provided, attempts to auto-accept participation for the client mapped to that username unless that client is excluded from both contribution and analysis.
6. Records requested participation roles for online clients:
   - `contributing_party` is false when the client name appears in `non_contributing_clients`.
   - `analyzing_party` is false when the client name appears in `exclude_analyzing_clients`.
   - Existing participation rows preserve their current confirmation value but update the party-role flags.
   - Missing participation rows are inserted as `PENDING`.
7. Builds a pending-client CSV from matching `PENDING` rows.
8. If no pending clients remain, returns the accepted-client CSV immediately.
9. In non-local environments, verifies SSH connectivity to the NVFlare server.
10. Stages a participation confirmation job using the `participation_confirmation` job template.
11. Submits the participation job through `NVFlareJobRunner`.
12. Polls MySQL every 5 seconds until all pending clients respond or the 900-second timeout expires.
13. Returns a CSV of clients with matching `ACCEPT` participation.

The returned accepted-client CSV becomes the client list used to stage the main analytics job.

## Contributing and Analyzing Party Selection

Two client-name lists flow through job submission and participation:

| Field | Meaning |
| --- | --- |
| `non_contributing_clients` | Clients that should not contribute data to aggregation. |
| `exclude_analyzing_clients` | Clients that should not receive/analyze final results. |

`NVFlareParticipationJobTask` computes the party flags written to `nvflare_client_participation`:

| Client Selection | Stored `contributing_party` | Stored `analyzing_party` |
| --- | --- | --- |
| Client is in neither list | `true` | `true` |
| Client is in `non_contributing_clients` only | `false` | `true` |
| Client is in `exclude_analyzing_clients` only | `true` | `false` |
| Client is in both lists | Excluded from participation snapshot | Excluded from participation snapshot |

The `/clients/participation/status` endpoint uses these same lists to decide whether a stored participation row matches the current frontend selection. A stored `ACCEPT` for `site1` as a contributing/analyzing party does not satisfy a later request where `site1` is selected as non-contributing or excluded from analysis.

## Main Job Packaging Effects

`NVFlareJobStager` receives `non_contributing_clients` and `exclude_analyzing_clients` when staging the main analytics job. During persistor config update, it injects these arrays into the persistor component args when they differ from the current template values:

```json
{
  "non_contributing_clients": ["site2"],
  "exclude_analyzing_clients": ["site1"]
}
```

The same method also forces current server ownership/contribution behavior in the persistor args:

```json
{
  "is_server_data_owner": false,
  "is_server_contributing_to_aggregation": false
}
```

Only these two flags are forced to `false`. `hide_result_from_server` is **not** overridden — it is read from the template per workflow (`_template_hide_result_from_server`) and is `True` for the hidden-result workflows (the terminal meta-analysis / leader-local PQC steps).

The generated runtime code uses these values in the analytics executor, aggregator, and persistor paths to control contribution and result visibility behavior. For **survival** biomarker discovery, this honors `non_contributing_clients` the same way the LCS scoring path does: a non-contributing client (e.g. the leader) is excluded from the **federated** KM result and instead scores its **own** cohort locally from the plaintext model for its Initiator (local) view — so it keeps its high/low curves for display while the federated estimate is over the contributing sites only.

## NVFlare Client Progress Emission

`NVFlareClientEmitManager` handles progress/status events emitted from NVFlare runtime code.

### Role

The manager receives an NVFlare-assigned job ID, looks up the internal `job_runner_id` from `nvflare_jobs`, creates a `JobStatusWriter`, and logs progress messages based on numeric event codes.

### Lookup

`_lookup_job_runner_id(nvflare_assigned_id)` queries:

```sql
SELECT job_runner_id
FROM nvflare_jobs
WHERE nvflare_assigned_id = %s
LIMIT 1
```

If no internal job runner ID is found, no status writer is created.

### Payload Shape

`log_progress_from_payload()` expects payloads like:

```json
{
  "job_id": "nvflare-generated-id",
  "client_name": "site1",
  "phase": 2,
  "round": 0,
  "origin": "site1",
  "timestamp": 1234567890.0,
  "tag": "job_progress",
  "step": 0,
  "scalars": {
    "code": 400,
    "phase_id": 2,
    "round": 0
  },
  "function": "mean"
}
```

The manager reads:

| Payload Field | Use |
| --- | --- |
| `scalars.code` | Numeric progress code mapped to a human-readable message and `JobRunnerStatus`. |
| `scalars.round` | Zero-indexed round number displayed to users as one-indexed. |
| `origin` or `client_name` | Client/server display prefix. |
| `function` | Optional function label prefix. |

### Deduplication

Progress messages are deduplicated for 3 seconds using this key:

```text
(job_runner_id, client_name, function_name, code, round)
```

Missing rounds are represented internally as `-1` for the dedupe key.

### Server Detection

A progress event is treated as server-originated when `client_name` or `origin` is `initiator` or `server` case-insensitively. Server messages are displayed with the prefix `NVFlare Server`; client messages use `Client {client_name}`.

### Status Mapping

| Code(s) | Status |
| --- | --- |
| `100` | `JOB_RECEIVED` |
| `720` | `THRESHOLD_NOT_MET` |
| `900` | `ERROR` |
| `300`, `1120`, `1140`, `1210`, `1220` | `SERVER_COMPUTE` or `CLIENT_COMPUTE` |
| `101` | `KEYGEN_WORKFLOW` |
| `500` | `DECRYPTION` |
| `400`, `420`, `500`, `1110`, `1150`, `1160`, `1170`, `1180`, `1230` | `SERVER_ENCRYPTION` or `CLIENT_ENCRYPTION` |
| `410`, `711`, `1100`, `1130` | `SERVER_ANALYSIS` or `CLIENT_ANALYSIS` |
| `600`, `702`, `710`, `712`, `1190`, `1240` | `SERVER_RESULTS` or `CLIENT_RESULTS` |
| Anything else | `PROCESSING` |

`500` appears in both the explicit `DECRYPTION` branch and the encryption set, but the explicit `500` branch returns first, so it resolves to `DECRYPTION`.

## Security and Auth Assumptions

Current backend behavior:

- Client routes are hidden from OpenAPI with `include_in_schema=False`.
- Route comments indicate these endpoints should be placed behind bearer-token authentication.
- Bearer-token validation is not implemented in `ClientRoutes.py`.
- `/clients/connection/status` and `/clients/participation/status` do not enforce authentication in the current code.
- `/clients/participation/submit` checks `$pw` against the MySQL password only when the environment is not `LOCAL`.
- In local mode, `/clients/participation/submit` does not require `$pw`.

## Frontend Behavior Supported by This Backend

The backend provides the data needed for the frontend to:

- show the server as a distinct always-present row
- show registered clients even when they are offline
- distinguish the submitting user's mapped client
- distinguish initiator clients
- show participation confirmation status for each client
- keep contributing/analyzing selections aligned with stored participation responses
- prevent stale acceptance records from satisfying a different role-selection context
- submit the main analytics job only after participation has been established

## Operational Notes

- `NVFlareClientSnapshot` depends on the NVFlare admin kit command `check_status server`.
- When the admin status command fails, the endpoint can still return registered clients from MySQL.
- Offline clients are represented by `last_connect_time` equal to `0` or the string `"0"`.
- Participation matching can exclude offline clients when a connection snapshot is provided.
- Participation records are not stored for the synthetic `Server` row.
- The submitting user's mapped client can be auto-accepted by `NVFlareParticipationJobTask`.
- Clients excluded from both contribution and analysis are filtered out of the participation snapshot and do not receive confirmation requests.
