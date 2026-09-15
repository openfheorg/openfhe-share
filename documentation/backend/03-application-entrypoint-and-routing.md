# Application Entrypoint and Routing

## Files Covered

| File | Role |
| --- | --- |
| `app/main.py` | FastAPI app creation, CORS setup, backend health endpoint, user role endpoint, and top-level route registration. |
| `app/api/AppRoutes.py` | Shared API router assembly. |
| `app/api/routes/*.py` | Feature-specific route modules included by `AppRoutes.py`. |

## `app/main.py`

`app/main.py` is the FastAPI application entrypoint for the backend container.

It creates the app with:

```python
app = FastAPI(title="Duality NVFlare Backend")
```

Current startup responsibilities include:

- Instantiate the FastAPI application.
- Define the fixed list of allowed CORS origins.
- Register `CORSMiddleware`.
- Expose `GET /health`.
- Expose `POST /user/role`.
- Include the shared `api_router` from `app/api/AppRoutes.py`.

The backend is started by the Docker image with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The Dockerfile exposes port `8000`. There is no Docker `HEALTHCHECK` instruction in the submitted backend package, so `/health` is available for a container, ALB, ECS, local Docker, or external monitor to call, but the repository itself does not prove that any one of those runtimes is currently wired to it.

## CORS Configuration

`app/main.py` defines `ALLOWED_ORIGINS` directly in code:

```python
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://api.example.org",
    "https://app.example.org",
    "https://dev-app.example.org",
    "https://api.example.org"
]
```

Current origin purposes:

| Origin | Purpose |
| --- | --- |
| `http://localhost:3000` | Local frontend development using the common React/Next/Vite dev-server port. |
| `http://127.0.0.1:3000` | Local frontend development when the browser uses loopback IP instead of `localhost`. |
| `http://api.example.org` | AWS Application Load Balancer origin for the FastAPI container. This is an HTTP ALB endpoint. |
| `https://app.example.org` | Amplify-hosted frontend for the `main` branch environment. |
| `https://dev-app.example.org` | Amplify-hosted frontend for the `dev` branch environment. |
| `https://api.example.org` | API Gateway origin present in the allowed browser origin list. The backend code does not identify the specific caller, but the origin matches the API Gateway endpoint used by this stack. |

The middleware is registered as:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
    max_age=86400,
)
```

Important behavior:

- CORS is not environment-specific in the current code. Local, dev, test, and deployed runtime all receive the same hardcoded origin list.
- There is no wildcard origin.
- All methods and headers are allowed for accepted origins.
- `allow_credentials=False`, so browser credentialed requests such as cookie-based authentication are not enabled through CORS.
- Preflight responses may be cached by the browser for up to `86400` seconds.

The current implementation keeps these origins in source code rather than environment-specific configuration.

## `/health`

`GET /health` is defined directly in `app/main.py`:

```python
@app.get("/health", response_class=PlainTextResponse)
def health_check():
    return "ok"
```

Response:

```text
ok
```

Current behavior:

- Returns plain text, not JSON.
- Does not check database connectivity.
- Does not check NVFlare connectivity.
- Does not check S3, API Gateway, OpenFHE, or downstream service availability.
- Is suitable as a lightweight process-level availability check.

Because it only returns `ok`, this endpoint should be treated as a shallow liveness endpoint, not a full readiness check.

## `/user/role`

`POST /user/role` is defined directly in `app/main.py`, not in `app/api/routes/`.

Request model:

```python
class UserLookupRequest(BaseModel):
    username: str
```

Handler:

```python
@app.post("/user/role")
def get_user_role(request: UserLookupRequest):
    manager = UsersManager()
    try:
        role_name = manager.validate_login(request.username)
        if not role_name:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        user_id = manager.get_user_id_by_username(request.username)
        projects = manager.get_user_project_datasources(user_id) if user_id is not None else []

        return {
            "username": request.username,
            "role": role_name,
            "user_id": user_id,
            "projects": projects,
        }
    finally:
        manager.complete()
```

### Request Example

```json
{
  "username": "alice@example.com"
}
```

### Successful Response Shape

```json
{
  "username": "alice@example.com",
  "role": "admin",
  "user_id": 1,
  "projects": [
    {
      "project_id": 1,
      "project_name": "Example Project",
      "datasources": [
        {
          "source": "https://example-fhir-server/fhir",
          "datasource_group_id": null,
          "datasource_group_name": "DEFAULT",
          "is_default_group": true
        }
      ]
    }
  ]
}
```

Actual `role`, `user_id`, project names, datasource URLs, and datasource groups depend on database contents.

### User Not Found Response

```json
{
  "error": "User not found"
}
```

Status code: `404`.

### Data Access Flow

The endpoint uses `UsersManager`.

The role lookup flow is:

1. `UsersManager.validate_login(username)` queries the `users` table for the user's `role_id`.
2. `RolesManager.get_role_name(role_id)` resolves the role name.
3. `UsersManager.get_user_id_by_username(username)` retrieves the user ID.
4. `UsersManager.get_user_project_datasources(user_id)` retrieves project and datasource records grouped by project.
5. `manager.complete()` closes the cursor and database connection in a `finally` block.

`UsersManager.validate_login()` contains a code comment stating that it is not for production use and is currently a simple lookup. There is no password verification, bearer-token validation, JWT validation, session validation, or role claim validation in this route.

Detailed user, role, project, and datasource behavior belongs in `08-users-roles-projects-and-datasources.md`.

## API Router Assembly

`app/api/AppRoutes.py` creates a shared `APIRouter` and includes feature route modules.

Current file contents:

```python
from fastapi import APIRouter
from app.api.routes import (
    ClientContentRoutes, ClientRoutes, FilterRoutes, FunctionRoutes,
    JobRunnerRoutes, LandingPageRoutes, NVFlareRoutes, ProjectRoutes, UserRoutes,
)

router = APIRouter()
router.include_router(FilterRoutes.router)
router.include_router(FunctionRoutes.router)
router.include_router(NVFlareRoutes.router)
router.include_router(JobRunnerRoutes.router)
router.include_router(LandingPageRoutes.router)
router.include_router(ClientRoutes.router)
router.include_router(ClientContentRoutes.router)
router.include_router(ProjectRoutes.router)
router.include_router(UserRoutes.router)
```

Current route registration order:

1. `FilterRoutes.router`
2. `FunctionRoutes.router`
3. `NVFlareRoutes.router`
4. `JobRunnerRoutes.router`
5. `LandingPageRoutes.router`
6. `ClientRoutes.router`
7. `ClientContentRoutes.router`
8. `ProjectRoutes.router`
9. `UserRoutes.router`

`app/main.py` then attaches the shared router with:

```python
app.include_router(api_router)
```

No prefix is supplied to `include_router`, so every path declared in the route modules is mounted exactly as written.

## Current Route Modules

### `FilterRoutes.py`

Purpose: filter retrieval.

Registered endpoints:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `POST` | `/filters/fetch_single_filter` | `fetch_single_filter` | Fetches one saved filter by `filter_id`. |
| `POST` | `/filters/fetch_filters` | `fetch_filters` | Fetches saved filters for a required `project_id`. |

Both endpoints are registered with `include_in_schema=False`.

The file has `# Put behind bearer token` comments, but there is no bearer-token enforcement in the route code.

### `FunctionRoutes.py`

Purpose: supported function lookup.

Registered endpoint:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `POST` | `/functions/supported_functions` | `fetch_supported_functions` | Retrieves configured/supported analysis functions from `FunctionsManager`. |

The endpoint is registered with `include_in_schema=False`.

### `NVFlareRoutes.py`

Purpose: NVFlare job submission, job history, audit submission, and client progress ingestion.

Registered endpoints:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `POST` | `/nvflare/client/emit_progress` | `emit_progress` | Receives progress payloads from NVFlare client/job execution. |
| `POST` | `/nvflare/jobs/history` | `fetch_nvFlare_job_history` | Fetches NVFlare job history, filtered by project and other request fields. |
| `POST` | `/nvflare/jobs/submit` | `submit_nvflare_job` | Submits an NVFlare job through `JobRunnerService`. |
| `POST` | `/nvflare/jobs/audit/submit` | `submit_audit` | Submits/records crypto audit details. |

All endpoints are registered with `include_in_schema=False`.

Authentication/security notes:

- `/nvflare/client/emit_progress` checks a `$pw` field against the configured MySQL password when the environment is not `LOCAL`.
- `/nvflare/jobs/audit/submit` also checks `$pw` against the configured MySQL password when the environment is not `LOCAL`.
- `/nvflare/jobs/history` and `/nvflare/jobs/submit` have `# Put behind bearer token` comments, but no bearer-token enforcement is implemented in the route code.

### `JobRunnerRoutes.py`

Purpose: job status, WebSocket status streaming, API Gateway WebSocket callbacks, job metadata, result retrieval, and function config retrieval.

Registered endpoints:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `WEBSOCKET` | `/jobs/status/ws/{job_id}` | `job_status_ws` | Direct FastAPI WebSocket status stream for a job. |
| `WEBSOCKET` | `/jobs/status/ws/local/{job_id}` | `job_status_ws` | Local-path alias for the same WebSocket status handler. |
| `POST` | `/jobs/status/ws/connect` | `job_status_ws_api_gateway_connect` | API Gateway WebSocket connect callback. |
| `POST` | `/jobs/status/ws/ack` | `job_status_ws_api_gateway_ack` | API Gateway WebSocket acknowledgement callback. |
| `POST` | `/jobs/status/ws/disconnect` | `job_status_ws_api_gateway_disconnect` | API Gateway WebSocket disconnect callback. |
| `POST` | `/jobs/status/ws/default` | `job_status_ws_api_gateway_default` | API Gateway WebSocket default route callback. |
| `POST` | `/jobs/status` | `job_status` | Polling endpoint for job status and log data. |
| `POST` | `/jobs/info` | `get_nvflare_job_info` | Retrieves job metadata by NVFlare assigned ID, job runner ID, or internal job ID. |
| `POST` | `/jobs/results` | `get_job_results_by_nvflare_id` | Retrieves results for a specific NVFlare job, function, and workflow ID. |
| `POST` | `/jobs/function/config` | `get_job_function_config` | Retrieves the function config for a specific NVFlare job, function, and workflow ID. |
| `POST` | `/jobs/results/mapping` | `get_job_results_mapping` | Retrieves result mapping metadata for a job/function. |

All POST endpoints in this module are registered with `include_in_schema=False`. The WebSocket routes are naturally outside the regular OpenAPI POST list.

Authentication/security notes:

- `/jobs/status`, `/jobs/results`, and `/jobs/function/config` have `# Put behind bearer token` comments, but no bearer-token enforcement is implemented in the route code.
- The API Gateway WebSocket callback routes do not enforce route-level authentication in this code file.
- The direct WebSocket routes accept a `job_id` path parameter and begin streaming after `websocket.accept()`.

### `LandingPageRoutes.py`

Purpose: optimized read models for the global Home and per-project landing pages.

Registered endpoints:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `POST` | `/landing/home` | `get_home_landing_data` | Global job/user/function summary for the Home landing page. |
| `POST` | `/landing/project` | `get_project_landing_data` | Project summary, capabilities, datasource groups, counts, and five recent jobs. |

The route module uses `APIRouter(prefix="/landing")` and both endpoints are registered with `include_in_schema=False`. `ProjectLandingRequest` is a small Pydantic request model containing `project_id: int`. Database work is delegated to `LandingPageManager`. See `24-landing-page-summary-endpoints.md`.

### `ClientRoutes.py`

Purpose: NVFlare client connection status, participation status, and participation submission.

Registered endpoints:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `POST` | `/clients/connection/status` | `list_clients_connection_status` | Returns the current NVFlare client connection snapshot. Accepts optional username. |
| `POST` | `/clients/participation/status` | `list_clients_status` | Returns participation status for selected filters/functions/client roles. |
| `POST` | `/clients/participation/submit` | `submit_participation` | Submits a participation decision/request. |

All endpoints are registered with `include_in_schema=False`.

Authentication/security notes:

- All three endpoint blocks have `# Put behind bearer token` comments.
- `/clients/participation/submit` checks a `$pw` field against the configured MySQL password when the environment is not `LOCAL`.
- `/clients/connection/status` and `/clients/participation/status` do not enforce bearer tokens in the route code.

### `ProjectRoutes.py`

Purpose: project listing and user/project FHIR source lookup.

Registered endpoints:

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `POST` | `/projects/list` | `get_projects_list` | Lists defined projects. |
| `POST` | `/projects/fhir/source` | `get_project_fhir_source` | Retrieves a user's FHIR source for a project and optional datasource group. |

Both endpoints are registered with `include_in_schema=False`.

`ProjectFHIRSourceRequest` is defined in this route file:

```python
class ProjectFHIRSourceRequest(BaseModel):
    username: str
    project_id: int
    datasource_group: int | None = None
    execute_query: str | None = None
```

No route-level authentication is enforced in this file.

## Route Registration Pattern

The current route structure keeps `app/main.py` small and places endpoint definitions in feature-focused route files.

When adding new backend endpoints:

1. Add the route to the appropriate file under `app/api/routes/`.
2. Add a request model under `app/api/models/` if the payload is reused or complex.
3. Keep database access inside manager/service classes when possible.
4. Register a new route file in `AppRoutes.py` only when creating a new endpoint group.
5. Update `04-api-endpoints.md`.

Current conventions visible in the code:

- Most endpoints use `POST`, even for read-style operations.
- Most endpoints return `JSONResponse` explicitly.
- Most route handlers parse raw request bodies with `await request.json()` rather than using Pydantic models.
- Reused or structured request models are limited. Examples include `UserLookupRequest`, `ProjectFHIRSourceRequest`, and `ClientConnectionStatusRequest`.
- Most endpoint registrations use `include_in_schema=False`, so the current API surface is intentionally hidden from generated OpenAPI docs.
- Database managers are generally closed in `finally` blocks via `complete()`.
- The mounted route paths have no global `/api` prefix.

## Authentication and Authorization Assumptions

Current code-level reality:

- There is no global authentication middleware in `app/main.py`.
- There is no global dependency enforcing bearer-token validation on `api_router`.
- Many routes include comments saying `# Put behind bearer token`, but the route files do not implement that bearer-token check.
- `/user/role` is a direct username lookup and does not validate a password, JWT, or signed identity claim.
- Some NVFlare/internal submission endpoints use a `$pw` payload field as a non-local guard and compare it to the configured MySQL password.
- `allow_credentials=False` in CORS means browser credential/cookie auth is not currently supported through the configured CORS middleware.

Authentication is incomplete at the route layer. Several routes are marked with `# Put behind bearer token`, but the submitted backend package does not include a shared bearer-token dependency or global authentication middleware. The current code should be treated as requiring an upstream gateway, ALB rule, VPN, private network boundary, external middleware, or later route-level authentication work before it is exposed beyond the intended trusted runtime boundary.
