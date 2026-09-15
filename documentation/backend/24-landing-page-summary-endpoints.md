# Landing Page Summary Endpoints

## Purpose

The backend exposes purpose-built read models for the new SHARE Home and project landing pages. They are implemented by:

- `app/api/routes/LandingPageRoutes.py`
- `app/core/mysql/managers/LandingPageManager.py`
- `app/api/AppRoutes.py`
- `app/core/mysql/MySQLConnectionProvider.py`

These endpoints avoid assembling the larger objects used by Job History and workflow execution when the landing pages only need aggregate statistics, project capabilities, and a small recent-job window.

## Route Registration

`LandingPageRoutes.router` is registered in `app/api/AppRoutes.py` and uses:

```python
router = APIRouter(prefix="/landing")
```

Both endpoints are currently `POST` routes and use `include_in_schema=False`, matching the current backend convention for several internal application endpoints.

## `POST /landing/home`

### Request

The requesting username is required so the backend can resolve the current SHARE role before assembling the Home read model.

```json
{
  "username": "initiator"
}
```

### Success Response

```json
{
  "status": "SUCCESS",
  "home": {
    "total_jobs": 94,
    "total_users": 24,
    "total_functions": 7,
    "job_statuses": [
      {"status": "FINISHED:COMPLETED", "count": 72},
      {"status": "RUNNING", "count": 4}
    ],
    "user_roles": [
      {
        "role_id": 1,
        "role": "CLIENT",
        "description": "Client user",
        "count": 19
      }
    ],
    "functions": [
      {
        "id": 1,
        "name": "SURVIVAL_ANALYSIS",
        "description": "..."
      }
    ]
  }
}
```

### Query Strategy

`LandingPageManager.get_home_summary(username)` first resolves the requesting user role from `users` + `defined_roles`, then returns only the fields appropriate for that role.

For non-client roles it loads:

1. grouped counts from `nvflare_jobs` by normalized status
2. roles from `defined_roles` left-joined to `users`, grouped by role
3. the defined function catalog from `defined_functions`

For `CLIENT` users it intentionally returns only `total_jobs`, `total_functions`, and `functions`. It does not return system-wide job-status distribution, registered-user totals, or user-role distribution. The client job total uses a direct `COUNT(*)` query instead of loading the grouped status distribution.


### Role-Aware Visibility

The Home endpoint is a role-aware read model, not a single universal system dashboard payload.

- `CLIENT`: receives total jobs and supported-function information only.
- `INITIATOR`, `OBSERVER`, and `ADMIN`: also receive `job_statuses`, `total_users`, and `user_roles`.
- unknown usernames return HTTP 404 with `User not found`.

The frontend treats the optional fields as capability-driven: if a field is absent, the corresponding statistic or chart is not rendered.

### Function Availability

The backend returns the complete defined-function catalog. It does not currently model the frontend's `Coming soon` state. The frontend intersects this catalog with its `FUNCTION_METADATA` and excludes disabled metadata entries from the displayed supported-function total.

## `POST /landing/project`

### Request Model

`ProjectLandingRequest`:

```json
{
  "project_id": 2
}
```

### Success Response

```json
{
  "status": "SUCCESS",
  "project": {
    "id": 2,
    "name": "General Statistics",
    "description": "...",
    "status": "ACTIVE",
    "fixed": true,
    "function_restrictions_enabled": false,
    "model_file_settings_enabled": false,
    "filter_system_id": 1,
    "filter_system": "DEFAULT",
    "registered_user_count": 3,
    "total_jobs": 28,
    "function_count": 7,
    "datasource_groups_defined": true,
    "datasource_groups": [],
    "default_datasource_group": null,
    "functions": []
  },
  "recent_jobs": []
}
```

A missing project returns:

```http
HTTP 404
```

```json
{
  "status": "FAILURE",
  "error": "Project not found"
}
```

## Project Summary Query Strategy

`LandingPageManager.get_project_landing_summary(project_id)` fetches only the data required by the project landing page.

The project query includes:

- `defined_projects`
- `defined_filter_system`
- correlated count of `nvflare_jobs`
- count of distinct project users in `users_fhir_source_by_project`

It then calls focused helpers for:

- project functions
- datasource groups
- the five most recent jobs

## Project Functions

When `defined_projects.function_restrictions_enabled` is true, the manager loads enabled project function restrictions from:

- `defined_project_function_restrictions`
- `defined_functions`

The response includes configurability and project override/custom configuration JSON.

When restrictions are disabled, the project receives all rows from `defined_functions` as configurable functions with no project-specific override objects.

## Datasource Groups

Datasource groups are read from:

```text
defined_project_datasource_groups
```

They are sorted with the default group first. The manager also returns `default_datasource_group` as the first group with `is_default = true`.

Projects with no datasource groups return an empty list and `datasource_groups_defined = false`.

## Recent Jobs

The recent-job limit is defined by:

```python
LandingPageManager.RECENT_JOB_LIMIT = 5
```

The base query reads from:

- `nvflare_jobs`
- `nvflare_job_datasource_log`
- `defined_project_datasource_groups`

and orders by:

```sql
ORDER BY j.create_date DESC, j.id DESC
LIMIT 5
```

The manager then bulk-loads function membership and function configuration details for only those selected job IDs.

This is intentionally different from calling `NVFlareJobsManager.get_nvflare_jobs()`, which builds the much larger Job History representation and may include crypto audit, workflow-group, and other history-specific data that the landing page does not need.

## Database Indexes

`MySQLConnectionProvider` calls `_ensure_landing_page_indexes()` at startup.

The landing workload uses these indexes:

```sql
nvflare_jobs:
  INDEX idx_nvjobs_project_create (project_id, create_date, id)

users_fhir_source_by_project:
  INDEX idx_ufsbp_project_user (project_id, user_id)
```

The indexes are included in fresh table creation where applicable and are also created for existing databases when missing.

## Connection Lifecycle

`LandingPageManager` follows the backend's explicit connection-ownership pattern:

1. acquire a pooled connection from `MySQLConnectionProvider`
2. create a dictionary cursor
3. execute read-only queries
4. route `finally` calls `manager.complete()`
5. `complete()` closes the cursor and connection

## Error Handling

Both routes catch unexpected exceptions, log the exception, and return:

```json
{
  "status": "FAILURE",
  "error": "Internal error"
}
```

with HTTP 500.

## Frontend Consumers

The frontend contracts live in:

```text
src/types/LandingPage.tsx
```

and endpoint constants live in:

```text
src/constants/Constants.tsx
```

The global Home consumer is `SHAREHomeDashboard.tsx` and the project landing consumer is `ProjectListComponent.tsx`.

The existing `/projects/list` endpoint remains in use for the full project definitions required by navigation, Job Runner setup, and public filter-schema hydration.
