# API Endpoints

## Files Covered

| File | Area |
| --- | --- |
| `app/main.py` | FastAPI app creation plus `/health` and `/user/role`. |
| `app/api/AppRoutes.py` | Shared `APIRouter` assembly and route module registration. |
| `app/api/routes/ClientRoutes.py` | Client connection state, participation lookup, and participation submission. |
| `app/api/routes/ClientContentRoutes.py` | Site-specific startup-kit binary delivery. |
| `app/api/models/ClientContentRequest.py` | Startup-kit request model containing `client_name`. |
| `app/api/routes/FilterRoutes.py` | Filter lookup endpoints. |
| `app/api/routes/FunctionRoutes.py` | Supported function lookup endpoint. |
| `app/api/routes/JobRunnerRoutes.py` | Job status polling, websocket status streaming, API Gateway websocket integration, job info, result retrieval, function config lookup, and workflow result mapping. |
| `app/api/routes/NVFlareRoutes.py` | NVFlare client progress emission, job history, job submission, and crypto audit submission. |
| `app/api/routes/ProjectRoutes.py` | Project listing and user/project FHIR datasource resolution. |
| `app/api/routes/UserRoutes.py` | User role/session lookup and user datasource settings apply endpoint. |
| `app/api/models/FunctionBasedRequest.py` | Shared Pydantic model containing a `function: SupportedFunction` field. |

## Route Assembly

`app/main.py` creates `FastAPI(title="Duality NVFlare Backend")`, registers CORS middleware, defines the health endpoint, and includes `api_router` from `app/api/AppRoutes.py`. User role/session routes are handled by `UserRoutes.py`.

`app/api/AppRoutes.py` creates a shared `APIRouter` and registers route modules in this order:

1. `FilterRoutes.router`
2. `FunctionRoutes.router`
3. `NVFlareRoutes.router`
4. `JobRunnerRoutes.router`
5. `ClientRoutes.router`
6. `ClientContentRoutes.router`
7. `ProjectRoutes.router`
8. `UserRoutes.router`

No router-level prefix is applied in `AppRoutes.py`, so every path below is mounted exactly as declared in its route file.

Most feature routes use `include_in_schema=False`. The client startup-kit delivery route is declared with explicit binary response metadata and is available to generated OpenAPI/Swagger documentation.

## CORS and Authentication State

`app/main.py` allows these exact origins:

| Origin | Current purpose visible from code |
| --- | --- |
| `http://localhost:3000` | Local frontend development. |
| `http://127.0.0.1:3000` | Local frontend development using loopback IP. |
| `http://api.example.org` | AWS ALB-hosted backend/frontend integration origin. |
| `https://app.example.org` | Amplify-hosted main branch origin. |
| `https://dev-app.example.org` | Amplify-hosted dev branch origin. |
| `https://api.example.org` | API Gateway origin. |

CORS settings are currently static and do not branch on environment:

```python
allow_methods=["*"]
allow_headers=["*"]
allow_credentials=False
max_age=86400
```

Several route files contain comments such as `# Put behind bearer token`, but the current backend code does not enforce a bearer token on those routes. Four inbound machine-style routes enforce a shared password check outside local runtime:

- `POST /nvflare/client/emit_progress`
- `POST /nvflare/jobs/audit/submit`
- `POST /clients/participation/submit`
- `POST /clients/datasource/source`

For those routes, when `EnvironmentProvider.get_env()` is not `Environment.LOCAL`, the request body must contain `$pw` matching the MySQL password from `ResourceConfigProvider.get_mysql_config()`. On mismatch, the route raises `HTTPException(status_code=401, detail="Unauthorized")`.

## Current Endpoint Inventory

| Method | Path | Handler | File |
| --- | --- | --- | --- |
| `GET` | `/health` | `health_check` | `app/main.py` |
| `POST` | `/user/role` | `get_user_role` | `UserRoutes.py` |
| `POST` | `/user/datasource/apply` | `apply_user_datasource_update` | `UserRoutes.py` |
| `POST` | `/clients/connection/status` | `list_clients_connection_status` | `ClientRoutes.py` |
| `POST` | `/clients/content/startup-kit` | `download_client_startup_kit` | `ClientContentRoutes.py` |
| `POST` | `/clients/datasource/source` | `get_client_datasource_source` | `ClientRoutes.py` |
| `POST` | `/clients/participation/status` | `list_clients_status` | `ClientRoutes.py` |
| `POST` | `/clients/participation/submit` | `submit_participation` | `ClientRoutes.py` |
| `POST` | `/filters/fetch_single_filter` | `fetch_single_filter` | `FilterRoutes.py` |
| `POST` | `/filters/fetch_filters` | `fetch_filters` | `FilterRoutes.py` |
| `POST` | `/functions/supported_functions` | `fetch_supported_functions` | `FunctionRoutes.py` |
| `POST` | `/landing/home` | `get_home_landing_data` | `LandingPageRoutes.py` |
| `POST` | `/landing/project` | `get_project_landing_data` | `LandingPageRoutes.py` |
| `POST` | `/nvflare/client/emit_progress` | `emit_progress` | `NVFlareRoutes.py` |
| `POST` | `/nvflare/jobs/history` | `fetch_nvFlare_job_history` | `NVFlareRoutes.py` |
| `POST` | `/nvflare/jobs/results_context` | `fetch_nvflare_results_context` | `NVFlareRoutes.py` |
| `POST` | `/nvflare/jobs/submit` | `submit_nvflare_job` | `NVFlareRoutes.py` |
| `POST` | `/nvflare/jobs/audit/submit` | `submit_audit` | `NVFlareRoutes.py` |
| `WEBSOCKET` | `/jobs/status/ws/{job_id}` | `job_status_ws` | `JobRunnerRoutes.py` |
| `WEBSOCKET` | `/jobs/status/ws/local/{job_id}` | `job_status_ws` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/status/ws/connect` | `job_status_ws_api_gateway_connect` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/status/ws/ack` | `job_status_ws_api_gateway_ack` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/status/ws/disconnect` | `job_status_ws_api_gateway_disconnect` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/status/ws/default` | `job_status_ws_api_gateway_default` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/status` | `job_status` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/info` | `get_nvflare_job_info` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/results` | `get_job_results_by_nvflare_id` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/function/config` | `get_job_function_config` | `JobRunnerRoutes.py` |
| `POST` | `/jobs/results/mapping` | `get_job_results_mapping` | `JobRunnerRoutes.py` |
| `POST` | `/projects/list` | `get_projects_list` | `ProjectRoutes.py` |
| `POST` | `/projects/fhir/source` | `get_project_fhir_source` | `ProjectRoutes.py` |

## Endpoint Details

### `GET /health`

| Item | Detail |
| --- | --- |
| Handler | `health_check` in `app/main.py` |
| Request body | None |
| Success response | Plain text `ok` |
| Status codes | FastAPI default `200` on success |
| Manager/service calls | None |
| Database tables touched | None |
| Frontend caller | Login/session setup; `UserSettingsPage` consumes the returned user/project datasource context through `UserRoleContext`. |
| Auth/security | No authentication enforced. |
| Error behavior | No explicit error handling. |

Example response:

```text
ok
```

### `POST /user/role`

| Item | Detail |
| --- | --- |
| Handler | `get_user_role` in `UserRoutes.py` |
| Request model | Inline Pydantic model `UserLookupRequest` with `username: str` |
| Success response | User role, user id, and project datasource information. |
| Status codes | `200` on success, `404` when `UsersManager.validate_login()` returns no role. Validation errors are handled by FastAPI/Pydantic. |
| Manager/service calls | `UsersManager.validate_login()`, `UsersManager.get_user_id_by_username()`, `UsersManager.get_user_project_datasources()`, `UsersManager.complete()` |
| Database tables touched | `users`, `defined_roles`, `users_fhir_source_by_project`, `defined_projects`, datasource group tables used by `UsersManager` queries. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced in the route. It trusts the submitted `username` string. |
| Error behavior | No route-level `except`; `UsersManager.complete()` is always called in `finally`. |

Example request:

```json
{
  "username": "evan@example.com"
}
```

Example success response shape:

```json
{
  "username": "evan@example.com",
  "role": "admin",
  "user_id": 1,
  "projects": []
}
```

Example not-found response:

```json
{
  "error": "User not found"
}
```

### `POST /user/datasource/apply`

| Item | Detail |
| --- | --- |
| Handler | `apply_user_datasource_update` in `UserRoutes.py` |
| Request model | `UserDatasourceApplyRequest` with `username: str | None`, `user_id: int | None`, and `updates: list[UserDatasourceUpdate]` |
| Success response | User id, updated datasource rows, and refreshed project datasource payload. |
| Status codes | `200` on success, `400` for missing user identity, empty updates, or invalid source format, `404` when the requested user is not found. |
| Manager/service calls | `UsersManager.get_user_id_by_username()`, `UsersManager.upsert_user_project_datasource()`, `UsersManager.get_user_project_datasources()`, `UsersManager.commit()`, `UsersManager.rollback()`, `UsersManager.complete()` |
| Database tables touched | `users`, `users_fhir_source_by_project`, `defined_projects`, `defined_project_datasource_groups` |
| Frontend caller | `UserSettingsPage.tsx` |
| Auth/security | No bearer token is enforced in the route. It trusts the submitted `user_id` or `username`. |
| Error behavior | Validation failures return JSON `{"error":"..."}` and do not commit partial updates. |

The route normalizes/validates datasource values before saving:

| Source shape | Validation |
| --- | --- |
| `http://...` or `https://...` | Must parse as a URL and must end with `/fhir` after trailing slashes are removed. |
| JSON path | Must end with `.json`. |

Example request:

```json
{
  "user_id": 2,
  "updates": [
    {
      "project_id": 2,
      "datasource_group_id": 1,
      "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json"
    }
  ]
}
```

Example response shape:

```json
{
  "user_id": 2,
  "updated_datasources": [],
  "projects": []
}
```

### `POST /clients/connection/status`

| Item | Detail |
| --- | --- |
| Handler | `list_clients_connection_status` in `ClientRoutes.py` |
| Request model | `ClientConnectionStatusRequest` with optional `username: str | None` |
| Success response | `{"clients": [...]}` from `NVFlareClientSnapshot().get_clients(username=username)` |
| Status codes | `200` on success, `500` on exception. Validation errors are handled by FastAPI/Pydantic. |
| Manager/service calls | `NVFlareClientSnapshot.get_clients()` |
| Database tables touched | Route file does not access tables directly. `NVFlareClientSnapshot` performs the backing lookup. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. |
| Error behavior | Catches all exceptions and returns `{"error": "Failed to fetch client status: [...]"}` with status `500`. |

Example request:

```json
{
  "username": "evan@example.com"
}
```

Example response shape:

```json
{
  "clients": [
    {
      "client_name": "site-1"
    }
  ]
}
```

### `POST /clients/datasource/source`

| Item | Detail |
| --- | --- |
| Handler | `get_client_datasource_source` in `ClientRoutes.py` |
| Request body | Raw JSON object with `client_name` or `site`, required `project_id`, optional `datasource_group_id` or `datasource_group`, and `$pw` outside local mode. |
| Success response | `status: SUCCESS`, mapped client/user details, datasource source, source type, datasource group metadata, and datasource record id. |
| Status codes | `200` on success, `400` for malformed/missing fields, `401` outside local mode when `$pw` is invalid, `404` when the client mapping or datasource record does not exist, `500` on unexpected exception. |
| Manager/service calls | `UsersManager.get_user_by_client_name()`, `UsersManager.get_fhir_source_record()`, `UsersManager.complete()` |
| Database tables touched | `nvflare_clients`, `users`, `users_fhir_source_by_project`, `defined_project_datasource_groups` |
| Frontend caller | None. This endpoint is called by NVFlare server-side `DatasourceRequestReceiver`. |
| Auth/security | Local mode skips the internal password check. Non-local mode requires `$pw` to match the backend's MySQL secret password value. |
| Error behavior | Returns `status: FAILURE` and an `error` string for validation/lookup failures. |

Example request:

```json
{
  "client_name": "site1",
  "project_id": 2,
  "datasource_group_id": 2
}
```

Example response shape:

```json
{
  "status": "SUCCESS",
  "requested_client_name": "site1",
  "client_name": "site1",
  "username": "client_site1",
  "user_id": 2,
  "project_id": 2,
  "source": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json",
  "source_type": "json",
  "datasource_group": 1,
  "datasource_group_id": 1,
  "datasource_group_name": "MSKChord",
  "is_default_group": true,
  "datasource_record_id": 15
}
```

This endpoint is the backend side of runtime datasource lookup. The client sends project/group context to the NVFlare server over the `duality.datasource.lookup` aux topic; the server calls this backend route and returns the source to the client.

### `POST /clients/participation/status`

| Item | Detail |
| --- | --- |
| Handler | `list_clients_status` in `ClientRoutes.py` |
| Request body | Raw JSON read from `Request`; malformed/empty JSON is treated as `{}`. |
| Success response | `{"clients": [...]}` with optional participation fields merged into each client. |
| Status codes | `200` on success, `400` when `participation_status.project_id` is required but missing/invalid, `500` on exception. |
| Manager/service calls | `NVFlareClientSnapshot.get_clients()`, `FiltersManager.get_id_by_filters()`, `ParticipationManager.list_client_participation_status()`, `ParticipationManager.complete()` |
| Database tables touched | Filter lookup through `defined_fhir_filters` and `defined_fhir_filter_conditions`; participation lookup through `nvflare_clients`, `nvflare_client_participation`, `nvflare_client_participation_functions`, `defined_functions`, `nvflare_client_participation_function_configs`, function config set tables, and optionally `threshold_configs`. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. |
| Error behavior | Invalid or absent `participation_status` returns only current connection clients. Invalid function payload also returns current clients. Unexpected exceptions return a `500` with traceback lines in the JSON body. |

Example request:

```json
{
  "username": "evan@example.com",
  "include_connection_state": true,
  "participation_status": {
    "project_id": 1,
    "filters": {
      "conditions": []
    },
    "functions": {
      "SURVIVABILITY_ANALYSIS": [
        {
          "model_type": "open_access"
        }
      ]
    },
    "non_contributing_clients": [],
    "exclude_analyzing_clients": [],
    "threshold_config": {
      "method": "PROTECTED",
      "threshold": 2
    }
  }
}
```

Example response shape:

```json
{
  "clients": [
    {
      "client_name": "site-1",
      "participation": "ACCEPT",
      "contributing_party": true,
      "analyzing_party": true
    }
  ]
}
```

### `POST /clients/participation/submit`

| Item | Detail |
| --- | --- |
| Handler | `submit_participation` in `ClientRoutes.py` |
| Required fields | `client_name`, `functions_map`, `filter_id`, `confirmation` |
| Optional fields | `$pw`, `threshold_config` |
| Success response | `{"status": "Participation recorded", "id": <recorded_id>}` |
| Status codes | `200` on success, `400` for missing/invalid request data or persistence exceptions, `401` outside local runtime when `$pw` does not match, `500` when persistence returns no id. |
| Manager/service calls | `_normalize_functions_map()`, `ParticipationManager.record_participation()`, `ParticipationManager.complete()` |
| Database tables touched | `nvflare_client_participation`, `nvflare_client_participation_functions`, `nvflare_client_participation_function_configs`, `nvflare_clients`, `defined_functions`, function config tables, and optionally `threshold_configs`. |
| Frontend caller | Not represented in `backend.zip`. This route is also suitable for NVFlare/client callbacks because it supports non-local `$pw` validation. |
| Auth/security | Shared `$pw` validation is enforced outside local runtime. No bearer token is enforced. |
| Error behavior | Missing fields produce `{"status": "Please provide <field>"}`. Invalid confirmation produces `{"status": "Confirmation must be ACCEPT or REJECT"}`. Exceptions return traceback lines with status `400`. |

Example request:

```json
{
  "$pw": "<non-local shared password>",
  "client_name": "site-1",
  "filter_id": 10,
  "confirmation": "ACCEPT",
  "functions_map": {
    "SURVIVABILITY_ANALYSIS": {
      "model_type": "open_access"
    }
  },
  "threshold_config": {
    "id": 1,
    "method": "PROTECTED",
    "threshold": 2
  }
}
```

Example response:

```json
{
  "status": "Participation recorded",
  "id": 123
}
```

### `POST /filters/fetch_single_filter`

| Item | Detail |
| --- | --- |
| Handler | `fetch_single_filter` in `FilterRoutes.py` |
| Required fields | `filter_id` |
| Success response | `{"status": "SUCCESS", "filter": ...}` |
| Status codes | `200` on success, `400` when `filter_id` is missing or non-integer, `500` on unexpected exception. |
| Manager/service calls | `MySQLRetriever.get_single_filter()`, `MySQLRetriever.complete()` |
| Database tables touched | `defined_fhir_filters`, `defined_fhir_filter_conditions` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Unexpected exceptions are logged and return `{"status": "FAILURE", "error": "Internal error"}`. |

Example request:

```json
{
  "filter_id": 10
}
```

Example response shape:

```json
{
  "status": "SUCCESS",
  "filter": {
    "id": 10,
    "name": "Example Filter",
    "conditions": []
  }
}
```

### `POST /filters/fetch_filters`

| Item | Detail |
| --- | --- |
| Handler | `fetch_filters` in `FilterRoutes.py` |
| Required fields | `project_id` |
| Success response | `{"status": "SUCCESS", "filters": [...]}` |
| Status codes | `200` on success, `400` when `project_id` is missing/invalid, `500` on unexpected exception. |
| Manager/service calls | `MySQLRetriever.get_all_filters(project_id=project_id)`, `MySQLRetriever.complete()` |
| Database tables touched | `defined_fhir_filters`, `defined_fhir_filter_conditions` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Unexpected exceptions are logged and return `{"status": "FAILURE", "error": "Internal error"}`. |

Example request:

```json
{
  "project_id": 1
}
```

Example response shape:

```json
{
  "status": "SUCCESS",
  "filters": []
}
```

### `POST /functions/supported_functions`

| Item | Detail |
| --- | --- |
| Handler | `fetch_supported_functions` in `FunctionRoutes.py` |
| Request body | Accepted but not used. |
| Success response | `{"status": "SUCCESS", "functions": [...]}` |
| Status codes | `200` on success, `500` on unexpected exception. |
| Manager/service calls | `FunctionsManager.get_supported_functions()`, `FunctionsManager.complete()` |
| Database tables touched | `defined_functions` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Unexpected exceptions are logged and return `{"status": "FAILURE", "error": "Internal error"}`. |

Example request:

```json
{}
```

Example response shape:

```json
{
  "status": "SUCCESS",
  "functions": [
    {
      "id": 1,
      "name": "SURVIVABILITY_ANALYSIS",
      "description": "..."
    }
  ]
}
```

### `POST /nvflare/client/emit_progress`

| Item | Detail |
| --- | --- |
| Handler | `emit_progress` in `NVFlareRoutes.py` |
| Request body | JSON body when parseable; otherwise raw request body. JSON must contain `job_id` for manager construction. |
| Success response | `{"status": "ok"}` |
| Status codes | `200` on success, `401` outside local runtime when `$pw` does not match. Other exceptions are not caught by the route. |
| Manager/service calls | `NVFlareClientEmitManager(nvflare_job_id)`, `NVFlareClientEmitManager.log_progress_from_payload()`, `NVFlareClientEmitManager.complete()` |
| Database tables touched | `nvflare_jobs` is queried to resolve `job_runner_id`; progress logging flows into job status/log handling. |
| Frontend caller | Not represented in `backend.zip`; route is structured as an NVFlare/backend webhook receiver. |
| Auth/security | Shared `$pw` validation is enforced outside local runtime. |
| Error behavior | Manager cleanup runs in `finally`; there is no route-level generic error response. |

Example request:

```json
{
  "$pw": "<non-local shared password>",
  "job_id": "job-123",
  "client_name": "site-1",
  "event_type": 1
}
```

Example response:

```json
{
  "status": "ok"
}
```

### `POST /nvflare/jobs/history`

| Item | Detail |
| --- | --- |
| Handler | `fetch_nvFlare_job_history` in `NVFlareRoutes.py` |
| Required fields | `project_id` |
| Optional fields | `function_names`, `filter_mode`, `date_filter`, `create_date` |
| Success response | `{"status": "SUCCESS", "nvflare_jobs": [...]}` |
| Status codes | `200` on success, `400` when `project_id` is missing/invalid, `500` on unexpected exception. |
| Manager/service calls | `NVFlareJobsManager.get_nvflare_jobs()`, `NVFlareJobsManager.complete()` |
| Database tables touched | `nvflare_jobs`, `threshold_configs`, `nvflare_job_functions`, `defined_functions`, `nvflare_job_crypto_audit`, datasource/workflow group log tables used by `NVFlareJobsManager`. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. |
| Error behavior | Unexpected exceptions are logged and return `{"status": "FAILURE", "error": "Internal error"}`. |

`filter_mode` is normalized to `ONLY` only when the submitted value is exactly `ONLY` after trim/uppercase; otherwise it uses `ANY`.

`date_filter` supports `mode` values `ON`, `BEFORE`, and `AFTER` when paired with a non-empty string `create_date`. If that structure is absent, the route falls back to top-level `create_date`.

Example request:

```json
{
  "project_id": 1,
  "function_names": ["SURVIVABILITY_ANALYSIS"],
  "filter_mode": "ANY",
  "date_filter": {
    "mode": "ON",
    "create_date": "2026-05-08"
  }
}
```

Example response shape:

```json
{
  "status": "SUCCESS",
  "nvflare_jobs": []
}
```

### `POST /nvflare/jobs/results_context`

| Item | Detail |
| --- | --- |
| Handler | `fetch_nvflare_results_context` in `NVFlareRoutes.py` |
| Request model | Raw JSON body containing required `nvflare_job_id` string. |
| Success response | `status`, compact `job`, resolved `project`, and optional saved `filter`. |
| Status codes | `200` success, `400` missing job ID, `404` job/project not found, `500` missing project reference or unexpected error. |
| Manager/service calls | `NVFlareJobsManager.get_nvflare_job_by_assigned_id()`, `ProjectsManager.get_project()`, optional `MySQLRetriever.get_single_filter()` |
| Database tables touched | `nvflare_jobs`, job datasource/function tables, project/datasource-group tables, and filter tables. |
| Frontend caller | `ResultsPage` through `fetchResultsContext()` for direct SHARE Client launch entry only. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is currently enforced. The submitted job UUID is not authorization. |
| Error behavior | Returns normalized `FAILURE` JSON for validation/not-found cases and generic `Internal error` for unexpected exceptions. |

Example request:

```json
{
  "nvflare_job_id": "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"
}
```

The response intentionally excludes workflow settings, threshold settings, crypto-audit details, and workflow result bodies. Those remain in their dedicated result/config flows.

### `POST /nvflare/jobs/submit`

| Item | Detail |
| --- | --- |
| Handler | `submit_nvflare_job` in `NVFlareRoutes.py` |
| Required fields | `filters`, `project_id`, `functions_map` |
| Optional fields | `datasource_group`, `workflow_group_data`, `non_contributing_clients`, `exclude_analyzing_clients`, `threshold_config`, `submitter` |
| Success response | `{"job_id": <job_runner_uuid>, "status": "QUEUED"}` |
| Status codes | `200` on success, `400` for missing/invalid payload fields. Unexpected exceptions are not caught by the route. |
| Manager/service calls | `_normalize_functions_map()`, `ThresholdManager.get_or_create()` when `threshold_config` is supplied, `JobRunnerService.get_instance()`, `JobRunnerService.request_job_run()` |
| Database tables touched | Direct route threshold lookup/insert touches `threshold_configs`. The job runner flow records job/log/function/filter/datasource/workflow state through `JobRunnerService`, `NVFlareJobTask`, `NVFlareJobStager`, `NVFlareJobsManager`, `FunctionsManager`, and `FiltersManager`; tables include `job_runner_log`, `nvflare_jobs`, `nvflare_job_functions`, `nvflare_job_function_configs`, function config tables, `defined_fhir_filters`, `defined_fhir_filter_conditions`, `nvflare_job_datasource_log`, `nvflare_job_workflow_groups`, and `nvflare_job_workflow_group_options`. |
| Frontend caller | Not represented in `backend.zip`, but this is the primary job submission endpoint. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. |
| Error behavior | Missing `filters`, missing/invalid `project_id`, missing/invalid `functions_map`, invalid `datasource_group`, invalid `workflow_group_data`, invalid client exclusion arrays, and invalid threshold payloads return `400` with a JSON `status` or `error` message. |

Validation behavior visible in the route:

- `filters` must be truthy: `{"name": <string>, "conditions": [{"filter_type", "column_name", "operator", "value" | "values"}, ...]}` (see `FiltersManager._validate_and_normalize_conditions`).
- `project_id` must be coercible to `int`.
- `datasource_group`, when present, must be coercible to `int`.
- `functions_map` must be an object and normalize into at least one function key.
- `workflow_group_data`, when present, must be an object.
- `non_contributing_clients` and `exclude_analyzing_clients`, when present, must be arrays of strings. Values are trimmed and deduplicated while preserving order.
- `threshold_config.method` or `threshold_config.thresholdMethod` is uppercased and mapped to `ThresholdMethod`; missing method defaults to `PROTECTED`.
- `threshold_config.threshold` must be coercible to `int`.

Example request:

```json
{
  "project_id": 1,
  "submitter": "evan@example.com",
  "datasource_group": 2,
  "filters": {
    "name": "No filters",
    "conditions": []
  },
  "functions_map": {
    "SURVIVAL_ANALYSIS": {
      "model_type": "Open-access"
    }
  },
  "workflow_group_data": {
    "predictive_modeling_method_ids": {
      "group_key": "predictive_modeling_method_ids",
      "selected_values": ["cox_lasso", "logistic_reg"]
    }
  },
  "non_contributing_clients": [],
  "exclude_analyzing_clients": [],
  "threshold_config": {
    "method": "PROTECTED",
    "threshold": 2
  }
}
```

Example response:

```json
{
  "job_id": "7f8d7b4f-0000-0000-0000-000000000000",
  "status": "QUEUED"
}
```

### `POST /nvflare/jobs/audit/submit`

| Item | Detail |
| --- | --- |
| Handler | `submit_audit` in `NVFlareRoutes.py` |
| Required fields | `nvflare_job_id`, `security_level`, `ring_dimension`, `batch_size`, `scale_mod_size`, `multiplicative_depth`, `scaling_technique`, `keyswitch_technique`, `ckks_data_type`, `ind_cpa_noise_bits` |
| Optional fields | `$pw` |
| Success response | `{"status": "Crypto audit recorded", "id": <recorded_id>}` |
| Status codes | `200` on success, `400` for missing/invalid request data or persistence exception, `401` outside local runtime when `$pw` does not match, `500` when persistence returns no id. |
| Manager/service calls | `CryptoAuditManager.log_audit()`, `CryptoAuditManager.complete()` |
| Database tables touched | `nvflare_job_crypto_audit` |
| Frontend caller | Not represented in `backend.zip`; route is structured for internal/NVFlare audit reporting. |
| Auth/security | Shared `$pw` validation is enforced outside local runtime. No bearer token is enforced. |
| Error behavior | Missing fields produce `{"status": "Please provide <field>"}`. Parse failures produce `{"status": "Invalid crypto audit payload"}`. Persistence exceptions return traceback lines with status `400`. |

Example request:

```json
{
  "$pw": "<non-local shared password>",
  "nvflare_job_id": "job-123",
  "security_level": "128-bit",
  "ring_dimension": 8192,
  "batch_size": 4096,
  "scale_mod_size": 53,
  "multiplicative_depth": 3,
  "scaling_technique": "FIXEDAUTO",
  "keyswitch_technique": "HYBRID",
  "ckks_data_type": "real",
  "ind_cpa_noise_bits": 20
}
```

Example response:

```json
{
  "status": "Crypto audit recorded",
  "id": 123
}
```

### `WEBSOCKET /jobs/status/ws/{job_id}` and `WEBSOCKET /jobs/status/ws/local/{job_id}`

| Item | Detail |
| --- | --- |
| Handler | `job_status_ws` in `JobRunnerRoutes.py` |
| Path parameter | `job_id` |
| Success behavior | Accepts the websocket and streams job status payloads when the status payload changes. Sends heartbeat messages when unchanged for `JOB_STATUS_WS_HEARTBEAT_INTERVAL_SECONDS` seconds. |
| Manager/service calls | `JobStatusRetriever.get_status_by_uuid()`, `JobStatusRetriever.complete()` |
| Database tables touched | `job_runner_log`, `nvflare_jobs`, `nvflare_job_functions`, `defined_functions` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. Requires frontend ACK messages for status and heartbeat messages. |
| Error behavior | On frontend ACK timeout, attempts to close with code `1008` and reason `Frontend did not acknowledge websocket message`. On unexpected exception, attempts to send a `job_status_error` message. |

The websocket poll interval is `0.5` seconds. ACK timeout is `5.0` seconds. Heartbeat interval is `10.0` seconds.

Status message shape:

```json
{
  "type": "job_status",
  "message_id": "...",
  "payload": {
    "job_id": "7f8d7b4f-0000-0000-0000-000000000000",
    "status": "RUNNING",
    "log": [],
    "last_update": "2026-05-08T12:00:00",
    "functions": []
  }
}
```

Heartbeat message shape:

```json
{
  "type": "heartbeat",
  "message_id": "...",
  "payload": {
    "job_id": "7f8d7b4f-0000-0000-0000-000000000000"
  }
}
```

Expected ACK shape:

```json
{
  "type": "ack",
  "message_id": "..."
}
```

### `POST /jobs/status/ws/connect`

| Item | Detail |
| --- | --- |
| Handler | `job_status_ws_api_gateway_connect` in `JobRunnerRoutes.py` |
| Request body | API Gateway-style event body or direct JSON containing connection/job fields. |
| Required fields | A resolvable `connectionId`/`connection_id` and `job_id`/`jobId`. |
| Success response | `{"ok": true, "connection_id": ..., "job_id": ..., "management_endpoint": ...}` |
| Status codes | `200` on success, `400` when connection id or job id is missing. |
| Manager/service calls | Starts an internal API Gateway status streaming task. Streaming uses `JobStatusRetriever.get_status_by_uuid()` and API Gateway Management API calls through `boto3`. |
| Database tables touched | Streaming task reads `job_runner_log`, `nvflare_jobs`, `nvflare_job_functions`, `defined_functions`. |
| Frontend caller | Not represented in `backend.zip`; route is designed for API Gateway websocket integration. |
| Auth/security | No authentication enforced. |
| Error behavior | Missing fields return explicit JSON errors. Existing state for the same connection id is removed before the new connection is registered. |

Example direct request:

```json
{
  "connectionId": "abc123",
  "job_id": "7f8d7b4f-0000-0000-0000-000000000000"
}
```

Example response:

```json
{
  "ok": true,
  "connection_id": "abc123",
  "job_id": "7f8d7b4f-0000-0000-0000-000000000000",
  "management_endpoint": "https://ws.example.org/prod"
}
```

### `POST /jobs/status/ws/ack`

| Item | Detail |
| --- | --- |
| Handler | `job_status_ws_api_gateway_ack` in `JobRunnerRoutes.py` |
| Request body | API Gateway-style event body or direct JSON containing connection/message fields. |
| Success response | `{"ok": true, "connection_id": ..., "message_id": ..., "acknowledged": <bool>}` |
| Status codes | `200` always from the handler. |
| Manager/service calls | Updates in-memory API Gateway connection ACK state. |
| Database tables touched | None directly. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Missing or unmatched values result in `acknowledged: false`; route still returns `200`. |

Example request:

```json
{
  "connectionId": "abc123",
  "message_id": "msg-1"
}
```

Example response:

```json
{
  "ok": true,
  "connection_id": "abc123",
  "message_id": "msg-1",
  "acknowledged": true
}
```

### `POST /jobs/status/ws/disconnect`

| Item | Detail |
| --- | --- |
| Handler | `job_status_ws_api_gateway_disconnect` in `JobRunnerRoutes.py` |
| Required fields | A resolvable `connectionId`/`connection_id`. |
| Success response | `{"ok": true, "connection_id": ...}` |
| Status codes | `200` on success, `400` when connection id is missing. |
| Manager/service calls | Removes in-memory API Gateway connection state and stops its streaming task. |
| Database tables touched | None directly. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Missing connection id returns `{"error": "connectionId is required."}`. |

Example request:

```json
{
  "connectionId": "abc123"
}
```

Example response:

```json
{
  "ok": true,
  "connection_id": "abc123"
}
```

### `POST /jobs/status/ws/default`

| Item | Detail |
| --- | --- |
| Handler | `job_status_ws_api_gateway_default` in `JobRunnerRoutes.py` |
| Request body | API Gateway-style event body or direct JSON. |
| Success response | `{"ok": true, "route": <route>}` unless the resolved route is `ack`. |
| Status codes | `200` for default handling. `ack` handling also returns `200`. |
| Manager/service calls | Delegates to ACK handling when route key is `ack`; otherwise none. |
| Database tables touched | None directly. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | No explicit error response except through delegated ACK behavior. |

Example request:

```json
{
  "routeKey": "ping"
}
```

Example response:

```json
{
  "ok": true,
  "route": "ping"
}
```

### `POST /jobs/status`

| Item | Detail |
| --- | --- |
| Handler | `job_status` in `JobRunnerRoutes.py` |
| Required fields | `job_id` |
| Success response | Job status payload from `_build_job_status_response_body()`. If no row is found, status defaults to `QUEUED`. |
| Status codes | `200` on successful lookup/default response, `400` on exception. |
| Manager/service calls | `JobStatusRetriever.get_status_by_uuid()`, `JobStatusRetriever.complete()` |
| Database tables touched | `job_runner_log`, `nvflare_jobs`, `nvflare_job_functions`, `defined_functions` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. |
| Error behavior | Exceptions return `{"job_id": ..., "status": "Exception occured while retrieving job status", "log": [...]}` with status `400`. The misspelling `occured` is present in the current code. |

Example request:

```json
{
  "job_id": "7f8d7b4f-0000-0000-0000-000000000000"
}
```

Example response shape when no status row exists:

```json
{
  "job_id": "7f8d7b4f-0000-0000-0000-000000000000",
  "status": "QUEUED",
  "log": [],
  "last_update": "None",
  "functions": []
}
```

### `POST /jobs/info`

| Item | Detail |
| --- | --- |
| Handler | `get_nvflare_job_info` in `JobRunnerRoutes.py` |
| Required fields | At least one of `nvflare_job_id`, `nvflare_assigned_id`, `job_runner_id`, or `id`. |
| Success response | `{"job": ...}` or `{"job": null}` when no matching row exists. |
| Status codes | `200` on success or no match, `400` when no lookup field is supplied, `500` on exception. |
| Manager/service calls | Uses `MySQLConnectionProvider` directly. |
| Database tables touched | `nvflare_jobs`, `threshold_configs`, `nvflare_job_functions`, `defined_functions` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Exceptions return `{"error": "Failed to fetch NVFlare job information: [...]"}` with status `500`. |

Example request:

```json
{
  "nvflare_job_id": "job-123"
}
```

Example response shape:

```json
{
  "job": {
    "id": 1,
    "project_id": 1,
    "nvflare_assigned_id": "job-123",
    "filter_id": 10,
    "threshold_config_id": 1,
    "status": "DONE",
    "job_path": "...",
    "output_path": "...",
    "job_runner_id": "7f8d7b4f-0000-0000-0000-000000000000",
    "non_contributing_clients": "",
    "exclude_analyzing_clients": "",
    "submit_time": "2026-05-08T12:00:00",
    "run_duration": 60,
    "create_date": "2026-05-08T12:00:00",
    "update_date": "2026-05-08T12:01:00",
    "functions": ["SURVIVABILITY_ANALYSIS"],
    "threshold": {
      "id": 1,
      "method": "PROTECTED",
      "threshold": 2
    }
  }
}
```

### `POST /jobs/results`

| Item | Detail |
| --- | --- |
| Handler | `get_job_results_by_nvflare_id` in `JobRunnerRoutes.py` |
| Required fields | `nvflare_job_id`, `function`, `workflow_id` |
| Success response | `{"job_data": ..., "function_config": ...}` |
| Status codes | `200` on success, `400` for missing required fields, an `nvflare_job_id` that does not match `[A-Za-z0-9_-]+`, or an unsupported function, `500` on exception. |
| Manager/service calls | `SupportedFunction(function_name)`, `NVFlareJobsDataRetriever.retrieve_workflow_data_with_config()`, `taskflow_report.generate_report_for_job()` |
| Database tables touched | `NVFlareJobsDataRetriever` reads result/config metadata; visible SQL includes `nvflare_jobs` and function config tables. It also reads job output artifacts from the NVFlare output structure. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. `nvflare_job_id` is restricted to `[A-Za-z0-9_-]+` because it is used as a filesystem path component. |
| Side effects | After the payload is built, the route calls `taskflow_report.generate_report_for_job()` through `asyncio.to_thread(...)` inside a bare `try`/`except: pass`, so taskflow report generation cannot change or fail the response. |
| Error behavior | Missing fields return explicit JSON errors. An `nvflare_job_id` outside the allowed charset returns `{"error": "Invalid nvflare_job_id."}` with status `400`. Unsupported functions return `{"error": "Unsupported function '<name>'"}`. Exceptions return traceback lines with status `500`. |

Example request:

```json
{
  "nvflare_job_id": "job-123",
  "function": "SURVIVABILITY_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Example response shape:

```json
{
  "job_data": {},
  "function_config": {}
}
```

Taskflow report side effect:

The route offloads `taskflow_report.generate_report_for_job(nvflare_job_id, case_label=f"{function_name} ({nvflare_job_id})")` to a worker thread after the response payload has been assembled. That helper merges any `trace.jsonl` streams reachable for the job and writes taskflow artifacts under `<job save location>/<nvflare_job_id>/taskflow/`. It is fire-and-forget: the call is wrapped in `try`/`except: pass`, the helper itself returns `None` instead of raising, and it skips regeneration when a report or `.no-trace` marker already exists. Report generation never affects the status code or body of `/jobs/results`.

### `POST /jobs/function/config`

| Item | Detail |
| --- | --- |
| Handler | `get_job_function_config` in `JobRunnerRoutes.py` |
| Required fields | `nvflare_job_id`, `function`, `workflow_id` |
| Success response | `{"function_config": ...}` |
| Status codes | `200` on success, `400` for missing required fields, an `nvflare_job_id` that does not match `[A-Za-z0-9_-]+`, or an unsupported function, `500` on exception. |
| Manager/service calls | `SupportedFunction(function_name)`, `NVFlareJobsDataRetriever.retrieve_function_config()` |
| Database tables touched | Function config lookup through `nvflare_jobs`, `nvflare_job_function_configs`, `defined_function_config_sets`, `defined_functions`, `defined_function_config_set_members`, and `defined_function_config_properties`. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | Comment says to put behind bearer token, but no bearer token is enforced. `nvflare_job_id` is restricted to `[A-Za-z0-9_-]+` because it is used as a filesystem path component. |
| Error behavior | Missing fields return explicit JSON errors. An `nvflare_job_id` outside the allowed charset returns `{"error": "Invalid nvflare_job_id."}` with status `400`. Unsupported functions return `{"error": "Unsupported function '<name>'"}`. Exceptions return traceback lines with status `500`. |

Example request:

```json
{
  "nvflare_job_id": "job-123",
  "function": "SURVIVABILITY_ANALYSIS",
  "workflow_id": "workflow_stat_analytics__cox_lasso"
}
```

Example response shape:

```json
{
  "function_config": {}
}
```

### `POST /jobs/results/mapping`

| Item | Detail |
| --- | --- |
| Handler | `get_job_results_mapping` in `JobRunnerRoutes.py` |
| Required fields | `nvflare_job_id`, `function` |
| Success response | `{"workflow_dirs": [...]}` and, when available, `profile_summary`. |
| Status codes | `200` on success, `400` for missing required fields or unsupported function, `500` on exception. |
| Manager/service calls | `SupportedFunction.from_name()`, `NVFlareJobsDataRetriever.list_workflow_dirs()`, `NVFlareJobsDataRetriever.get_profile_summary()` |
| Database tables touched | The route does not directly query tables. `NVFlareJobsDataRetriever` uses NVFlare job result/output paths and function context. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. This route does not pre-validate the `nvflare_job_id` charset; `NVFlareJobsDataRetriever.__init__` performs the same `[A-Za-z0-9_-]+` check and raises `ValueError`. |
| Error behavior | Missing fields return explicit JSON errors. Unsupported functions return `{"error": "Unsupported function '<name>'"}`. Exceptions, including the retriever's invalid-id `ValueError`, return traceback lines with status `500`. |

Example request:

```json
{
  "nvflare_job_id": "job-123",
  "function": "SURVIVABILITY_ANALYSIS"
}
```

Example response shape:

```json
{
  "workflow_dirs": ["workflow_stat_analytics__cox_lasso"],
  "profile_summary": {}
}
```

### `POST /landing/home`

| Item | Detail |
| --- | --- |
| Handler | `get_home_landing_data` in `LandingPageRoutes.py` |
| Request model | `HomeLandingRequest` |
| Request body | `{ "username": "<current username>" }` |
| Success response | `{ "status": "SUCCESS", "home": { ... } }` |
| Manager/service calls | `LandingPageManager.get_home_summary(username)` |
| Database tables touched | `nvflare_jobs`, `defined_roles`, `users`, `defined_functions` |
| Frontend caller | `src/components/SHAREHomeDashboard.tsx` |
| Auth/security | No route-level bearer-token enforcement in this file. |
| Error behavior | HTTP 500 with `{ "status": "FAILURE", "error": "Internal error" }`; manager is closed in `finally`. |

The `home` object is role-aware. `CLIENT` users receive `total_jobs`, `total_functions`, and the defined function catalog only. Non-client roles additionally receive `total_users`, grouped `job_statuses`, and grouped `user_roles`. Unknown usernames return HTTP 404. The frontend omits any statistic/chart whose field is absent and filters the function catalog through its function metadata before presenting the supported-function count.

### `POST /landing/project`

| Item | Detail |
| --- | --- |
| Handler | `get_project_landing_data` in `LandingPageRoutes.py` |
| Request model | `ProjectLandingRequest` |
| Request body | `{ "project_id": <int> }` |
| Success response | `{ "status": "SUCCESS", "project": { ... }, "recent_jobs": [ ... ] }` |
| Manager/service calls | `LandingPageManager.get_project_landing_summary(project_id)` |
| Database tables touched | `defined_projects`, `defined_filter_system`, `nvflare_jobs`, `users_fhir_source_by_project`, project function restriction tables, datasource-group tables, recent-job function/config tables |
| Frontend caller | `src/components/ProjectListComponent.tsx` |
| Auth/security | No route-level bearer-token enforcement in this file. |
| Error behavior | HTTP 404 for unknown project; HTTP 500 for unexpected errors; manager closed in `finally`. |

The response is intentionally optimized for the project landing page. It includes the total job count, registered-user count, datasource groups/default group, project function capabilities, and only the five most recent jobs. It does not call the full Job History manager path. See `24-landing-page-summary-endpoints.md`.

### `POST /projects/list`

| Item | Detail |
| --- | --- |
| Handler | `get_projects_list` in `ProjectRoutes.py` |
| Request body | None required. |
| Success response | `{"projects": [...]}` |
| Status codes | `200` on success. Unexpected exceptions are not caught by the route. |
| Manager/service calls | `ProjectsManager.get_project_list()`, `ProjectsManager.complete()` |
| Database tables touched | `defined_projects`, plus related project configuration tables used by `ProjectsManager`, including filter system, allowed filter types, project function restrictions, datasource groups, and workflow groups/options. |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. |
| Error behavior | Manager cleanup runs in `finally`; no route-level generic error response. |

Example request:

```json
{}
```

Example response shape:

```json
{
  "projects": [
    {
      "id": 1,
      "name": "Example Project"
    }
  ]
}
```

### `POST /projects/fhir/source`

| Item | Detail |
| --- | --- |
| Handler | `get_project_fhir_source` in `ProjectRoutes.py` |
| Request model | `ProjectFHIRSourceRequest` with `username: str`, `project_id: int`, `datasource_group: int | None = None`, and `execute_query: str | None = None` |
| Success response | User/project datasource details and optional upstream query result. |
| Status codes | `200` on success, `404` when username is not found or no FHIR source record matches, FastAPI/Pydantic validation errors for invalid model input. Upstream FHIR server status is embedded in `query_status_code`; it is not used as the HTTP status of this backend response. |
| Manager/service calls | `UsersManager.get_user_id_by_username()`, `UsersManager.get_fhir_source_record()`, `ProjectsManager.get_project_datasource_group_summary()`, `requests.get()` when `execute_query` is supplied for a FHIR server source, `UsersManager.complete()`, `ProjectsManager.complete()` |
| Database tables touched | `users`, `users_fhir_source_by_project`, `defined_projects`, `defined_project_datasource_groups` |
| Frontend caller | Not represented in `backend.zip`. |
| Auth/security | No authentication enforced. It trusts the submitted `username`. Upstream query requests are sent with `Accept: application/fhir+json, application/json` and `timeout=60`. |
| Error behavior | Missing user or source record returns `404` with a `message`. Upstream query JSON parsing falls back to text if the response body is not JSON. There is no route-level generic `except`; manager cleanup runs in `finally`. |

`source_type` is set to `json` when the source string lowercased ends with `.json`; otherwise it is set to `fhir_server`.

When `execute_query` is present and the source is a JSON file, no upstream query is executed and the response includes:

```json
{
  "query_executed": false,
  "query_execution_message": "Query execution skipped because source is a json file."
}
```

When `execute_query` is present and the source is a FHIR server, the route normalizes the query path, joins it to the configured source URL, executes a GET request, and includes `query_executed`, `executed_url`, `query_status_code`, and `query_results`.

Example request:

```json
{
  "username": "evan@example.com",
  "project_id": 1,
  "datasource_group": 2,
  "execute_query": "/Patient?_count=1"
}
```

Example response shape:

```json
{
  "username": "evan@example.com",
  "user_id": 1,
  "project_id": 1,
  "source": "https://example-fhir-server/fhir",
  "source_type": "fhir_server",
  "datasource_group": 2,
  "datasource_group_name": "Example Group",
  "is_default_group": false,
  "datasource_groups_defined": true,
  "datasource_groups": [],
  "default_datasource_group": null,
  "query_executed": true,
  "executed_url": "https://example-fhir-server/fhir/Patient?_count=1",
  "query_status_code": 200,
  "query_results": {}
}
```

## Endpoint Group Notes

### User Routes

User routes expose login/session context and user datasource setting updates. `/user/role` returns role, user id, and project datasource assignments. `/user/datasource/apply` persists changed datasource settings from `UserSettingsPage` and returns refreshed project datasource context.

### Client Routes

Client routes provide the current NVFlare client connection snapshot, runtime datasource lookup for NVFlare server-side code, merge stored participation state into that snapshot, and accept participation confirmations. Participation matching is based on project/filter/function configuration and optionally threshold configuration. Participation rows are also filtered against selected contributing/analyzing roles so stale rows for different role selections are not treated as current matches.

### Filter and Function Routes

Filter routes read defined FHIR filters and filter conditions. Function routes read supported function metadata from `defined_functions`. These endpoints support frontend job configuration screens by exposing available filters and functions.

### NVFlare Routes

NVFlare routes cover inbound progress logging, job history lookup, job submission, and crypto audit logging. `/nvflare/jobs/submit` is the primary submission endpoint and hands off to `JobRunnerService.request_job_run()` after validating and normalizing the payload.

### Job Runner Routes

Job runner routes expose polling and websocket status, job metadata, workflow result payloads, function configs, and workflow result directory mapping. Websocket support exists in two forms: direct FastAPI websocket paths and API Gateway-compatible POST endpoints that manage in-memory connection state and publish through the API Gateway Management API.

### Landing Page Routes

`LandingPageRoutes.py` is a read-only summary API for the frontend landing environment. Its manager is intentionally optimized separately from full project and Job History retrieval.

### Project Routes

Project routes expose project metadata and user-specific FHIR datasource resolution. `/projects/list` supplies datasource group metadata to `UserSettingsPage`. `/projects/fhir/source` can also test an upstream FHIR query when the configured source is not a local JSON file.

## Current Gaps and Security Assumptions

- Route-level bearer authentication is not implemented in the backend code, even where comments indicate it should be added.
- `/user/role` and `/projects/fhir/source` trust the submitted `username` value.
- Most feature routes are hidden from generated OpenAPI schema via `include_in_schema=False`.
- Frontend caller names and component references cannot be verified from `backend.zip` because the frontend code is not included in this archive.
- Several routes rely on broad `except Exception` handling and return traceback lines to callers. Others do not catch unexpected exceptions at the route level.


## Client Startup-Kit Delivery

### `POST /clients/content/startup-kit`

Request:

```json
{
  "client_name": "site1"
}
```

A successful response is a binary `application/gzip` payload rather than JSON. The response includes:

```text
Content-Disposition: attachment; filename="share-client-site1-startup-kit.tar.gz"
X-SHARE-Client-Site: site1
X-SHARE-Artifact-SHA256: <sha256>
X-SHARE-Artifact-Size: <bytes>
```

Status behavior:

| Status | Meaning |
| --- | --- |
| `200` | Archive generated and returned. |
| `400` | Invalid client identifier. |
| `404` | Site folder not found. |
| `409` | Site folder does not contain a valid NVFlare startup directory. |
| `500` | Local or remote archive preparation failed. |

Environment behavior:

- `SHARE_ENV=local`: package the locally available NVFlare workspace.
- Any non-local environment: SSH to the configured NVFlare EC2 host, build the tar there, atomically replace the stable remote tar, download the request-specific archive over SFTP, and return it.

The HTTP response uses a background cleanup task to remove only the API container's temporary copy after transmission.

This endpoint currently accepts the requested `client_name` directly. It must be protected by server-side authorization before startup kits containing site credentials are distributed beyond a controlled environment.
