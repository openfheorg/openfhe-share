# Security, Auth, CORS, and Access Control

## Files Covered

| File | Role |
| --- | --- |
| `app/main.py` | FastAPI application setup, CORS allowlist, `/health`, and `/user/role`. |
| `app/api/AppRoutes.py` | Route module assembly. |
| `app/api/routes/ClientRoutes.py` | Client connection status, participation status, participation submission, and non-local participation callback password check. |
| `app/api/routes/FilterRoutes.py` | Filter lookup endpoints with bearer-token TODO comments but no implemented bearer-token enforcement. |
| `app/api/routes/FunctionRoutes.py` | Supported function metadata endpoint. |
| `app/api/routes/JobRunnerRoutes.py` | Job status polling, websocket status streams, API Gateway websocket callback helpers, job info, results, function config, and result mapping endpoints. |
| `app/api/routes/NVFlareRoutes.py` | NVFlare progress emission, job history, job submission, and crypto audit submission. |
| `app/api/routes/ProjectRoutes.py` | Project listing and FHIR datasource lookup/query proxying. |
| `app/core/EnvironmentManager.py` | Runtime environment selection from `SHARE_ENV`. |
| `app/core/aws/ResourceConfigProvider.py` | Local and deployed MySQL/SSH configuration selection. |
| `app/core/aws/SecretsManager.py` | AWS Secrets Manager lookup and cached MySQL secret retrieval. |
| `app/core/mysql/managers/UsersManager.py` | Username-to-role lookup and project datasource lookup. |
| `app/core/mysql/managers/RolesManager.py` | Role-name lookup by role ID. |
| `app/core/mysql/MySQLConnectionProvider.py` | User, role, datasource, job, participation, and audit schema plus seed data. |
| `app/core/ssh/SSHConnectionProvider.py` | SSH private key retrieval from Secrets Manager for NVFlare EC2 access. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/sm.py` | Runtime job helper for fetching the MySQL password from Secrets Manager. |
| `app/core/job_runner/nvflare_jobs/jobs/participation_confirmation/app_server/custom/sm.py` | Participation job helper for fetching the MySQL password from Secrets Manager. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/backend_webhook_writer.py` | Server-side job runtime callback writer for `/nvflare/client/emit_progress`. |
| `app/core/job_runner/nvflare_jobs/jobs/participation_confirmation/app_server/custom/response_aggregator.py` | Participation confirmation callback writer for `/clients/participation/submit`. |

## Current Security Model

The backend currently has a lightweight application-level role lookup, a static CORS allowlist, and password-protected internal callback endpoints for non-local runtime paths. It does not currently implement request-wide bearer-token validation, JWT validation, session validation, or route-level permission checks.

Several route files include comments such as `Put behind bearer token`. These comments are present in the code, but there is no FastAPI dependency, middleware, OAuth2 handler, JWT parser, OIDC verifier, or `Authorization` header enforcement wired into the current route implementations.

The practical current-state access model is:

1. Browser access is limited by the static CORS origin list for browser-enforced cross-origin requests.
2. `/user/role` resolves a role by username through the database, but it does not authenticate a password or validate an identity-provider token.
3. Most application endpoints accept request payloads directly once the request reaches the backend.
4. `/nvflare/client/emit_progress`, `/clients/participation/submit`, and `/nvflare/jobs/audit/submit` require a `$pw` value in non-local environments.
5. The `$pw` value is compared to the current MySQL password from `ResourceConfigProvider.get_mysql_config()`.
6. Local runtime bypasses the `$pw` check for those callback-style endpoints.
7. Secrets are retrieved from AWS Secrets Manager for deployed MySQL and SSH usage.

## Runtime Environment Selection

`EnvironmentProvider.get_env()` reads `SHARE_ENV` and caches the resolved enum value.

Supported values are:

| Value | Enum | Behavior |
| --- | --- | --- |
| `local` | `Environment.LOCAL` | Uses local MySQL environment variables/defaults and bypasses the `$pw` callback password checks. |
| `dev` | `Environment.DEV` | Uses the hardcoded DEV RDS secret name, hardcoded DEV RDS host, and DEV NVFlare EC2 SSH settings. |
| `test` | `Environment.TEST` | Defined in the enum, but no separate MySQL or SSH configuration branch is implemented in `ResourceConfigProvider.py`. |
| `prod` | `Environment.PROD` | Defined in the enum, but no separate MySQL or SSH configuration branch is implemented in `ResourceConfigProvider.py`. |

If `SHARE_ENV` is not set, `EnvironmentProvider.get_env()` prints an error and exits the process with `os._exit(1)`. If the value is not one of the enum values, it also prints an error and exits.

## CORS Configuration

CORS is configured in `app/main.py` through `CORSMiddleware`.

Current middleware values:

| Setting | Current Value |
| --- | --- |
| `allow_origins` | Static `ALLOWED_ORIGINS` list from `app/main.py`. |
| `allow_methods` | `['*']` |
| `allow_headers` | `['*']` |
| `allow_credentials` | `False` |
| `max_age` | `86400` |

Current allowed origins:

| Origin | Current Purpose / Runtime Association |
| --- | --- |
| `http://localhost:3000` | Local frontend development on port 3000. |
| `http://127.0.0.1:3000` | Local frontend development using loopback IP instead of `localhost`. |
| `http://api.example.org` | Deployed backend ALB URL included in the allowlist. |
| `https://app.example.org` | Amplify-hosted frontend main/prod-style branch URL included in the allowlist. |
| `https://dev-app.example.org` | Amplify-hosted frontend dev branch URL included in the allowlist. |
| `https://api.example.org` | API Gateway URL included in the allowlist. |

The code does not load CORS origins from environment variables. The same CORS list is used for local and deployed runtime unless `app/main.py` is changed.

Because `allow_credentials=False`, the CORS layer is not configured for browser credentialed requests such as cookie-based sessions. This matches the current absence of server-side session/cookie authentication.

## User Role Flow

`POST /user/role` is defined directly in `app/main.py`.

Request body:

```json
{
  "username": "initiator"
}
```

Current processing:

1. Pydantic parses the body with `UserLookupRequest`, which requires `username` as a string.
2. `UsersManager.validate_login(username)` looks up the user by username in `users`.
3. `UsersManager.validate_login` reads the user `role_id` and resolves the role name through `RolesManager.get_role_name(role_id)`.
4. `UsersManager.get_user_id_by_username(username)` retrieves the user ID.
5. `UsersManager.get_user_project_datasources(user_id)` retrieves project datasource assignments for that user.
6. The route returns the username, role name, user ID, and project datasource list.

Successful response shape:

```json
{
  "username": "initiator",
  "role": "INITIATOR",
  "user_id": 4,
  "projects": [
    {
      "project_id": 1,
      "project_name": "Biomarker Model Validation for Cancer Prognosis",
      "datasources": [
        {
          "source": "...",
          "datasource_group_id": 1,
          "datasource_group_name": "MSKChord",
          "is_default_group": true
        }
      ]
    }
  ]
}
```

Missing user response:

```json
{
  "error": "User not found"
}
```

The missing-user status code is `404`.

### Current Role Records

Default role seeding uses values from `UserRole.py` and the database table `defined_roles`.

Current seeded roles are:

| Role | Current Use |
| --- | --- |
| `CLIENT` | Default role for client users such as `client`, `client_site1`, and `client_site2`. |
| `INITIATOR` | Default role for initiator users such as `initiator`. |
| `OBSERVER` | Default role for observer users such as `observer`. |

The current backend resolves and returns role names, but it does not enforce endpoint authorization based on those roles.

### Current User Records

`MySQLConnectionProvider.py` seeds test users and NVFlare client users with `password_hash = 'DISABLED'`.

Current seeded user behavior includes:

| Seed Routine | Users / Records |
| --- | --- |
| `_ensure_test_users_exist()` | Creates lowercase users for `client`, `initiator`, and `observer` when the matching roles exist. |
| `_ensure_default_nvflare_clients()` | Creates or reuses `client_site1`, `client_site2`, and `initiator`; maps `site1`, `site2`, and `site3` into `nvflare_clients`. |

The current login validation does not read or compare `password_hash`. The field exists in the schema, but the current `/user/role` flow is username lookup only.

## Endpoint Auth Status

| Method | Path | Current Enforcement |
| --- | --- | --- |
| `GET` | `/health` | No auth. Returns plain text `ok`. |
| `POST` | `/user/role` | No token/password auth. Resolves role by username. |
| `POST` | `/clients/connection/status` | No implemented auth. Nearby code comment says `Put behind bearer token`. |
| `POST` | `/clients/participation/status` | No implemented auth. Nearby code comment says `Put behind bearer token`. |
| `POST` | `/clients/participation/submit` | Non-local `$pw` check against MySQL password. Local bypasses this check. Code comment says `Put behind bearer token`. |
| `POST` | `/filters/fetch_single_filter` | No implemented auth. Code comment says `Put behind bearer token`. |
| `POST` | `/filters/fetch_filters` | No implemented auth. Code comment says `Put behind bearer token`. |
| `POST` | `/functions/supported_functions` | No implemented auth. |
| `POST` | `/nvflare/client/emit_progress` | Non-local `$pw` check against MySQL password. Local bypasses this check. |
| `POST` | `/nvflare/jobs/history` | No implemented auth. Code comment says `Put behind bearer token`. |
| `POST` | `/nvflare/jobs/results_context` | No implemented auth. Resolves job/project/filter context by submitted NVFlare job UUID. Code comment says `Put behind bearer token`. |
| `POST` | `/nvflare/jobs/submit` | No implemented auth. Code comment says `Put behind bearer token`. Validates payload structure before queuing a job. |
| `POST` | `/nvflare/jobs/audit/submit` | Non-local `$pw` check against MySQL password. Local bypasses this check. Code comment says `Put behind bearer token`. |
| `WEBSOCKET` | `/jobs/status/ws/{job_id}` | No token/password auth. Streams status for the supplied job ID. |
| `WEBSOCKET` | `/jobs/status/ws/local/{job_id}` | No token/password auth. Streams status for the supplied job ID. |
| `POST` | `/jobs/status/ws/connect` | No token/password auth. Handles API Gateway websocket connection registration payload. |
| `POST` | `/jobs/status/ws/ack` | No token/password auth. Handles API Gateway websocket acknowledgement payload. |
| `POST` | `/jobs/status/ws/disconnect` | No token/password auth. Handles API Gateway websocket disconnect payload. |
| `POST` | `/jobs/status/ws/default` | No token/password auth. Routes API Gateway default websocket payloads and treats route key `ack` as an acknowledgement. |
| `POST` | `/jobs/status` | No implemented auth. Code comment says `Put behind bearer token`. Reads status by submitted `job_id`. |
| `POST` | `/jobs/info` | No implemented auth. Reads job info by `nvflare_job_id`, `job_runner_id`, or internal `id`. |
| `POST` | `/jobs/results` | No implemented auth. Code comment says `Put behind bearer token`. Reads result data by `nvflare_job_id`, `function`, and `workflow_id`. |
| `POST` | `/jobs/function/config` | No implemented auth. Code comment says `Put behind bearer token`. Reads function config by `nvflare_job_id`, `function`, and `workflow_id`. |
| `POST` | `/jobs/results/mapping` | No implemented auth. Reads workflow directory/result mapping metadata by `nvflare_job_id` and `function`. |
| `POST` | `/projects/list` | No implemented auth. Lists projects. |
| `POST` | `/projects/fhir/source` | No implemented token/password auth. Requires `username` and `project_id`; resolves datasource assignment for that username/project. Can proxy a FHIR query when `execute_query` is supplied and the source is not a JSON file. |

## Password-Protected Internal Callback Pattern

Three endpoints implement the same non-local password pattern:

| Endpoint | Caller / Runtime Context | Password Field | Secret Source |
| --- | --- | --- | --- |
| `/nvflare/client/emit_progress` | NVFlare job runtime server-side callback writer. | `$pw` | MySQL password from `ResourceConfigProvider.get_mysql_config()`. |
| `/clients/participation/submit` | Participation confirmation job runtime server-side response aggregator. | `$pw` | MySQL password from `ResourceConfigProvider.get_mysql_config()`. |
| `/nvflare/jobs/audit/submit` | Encrypted/OpenFHE job runtime audit callback. | `$pw` | MySQL password from `ResourceConfigProvider.get_mysql_config()`. |

Current behavior:

1. The route reads the request body.
2. The route checks `EnvironmentProvider.get_env()`.
3. If the environment is `local`, the password check is skipped.
4. If the environment is not `local`, the route reads `$pw` from the request body.
5. The route compares `$pw` to the MySQL password returned by `ResourceConfigProvider.get_mysql_config()`.
6. If the first comparison fails, the route refreshes the MySQL config with `check_cached=False` and compares again.
7. If the refreshed comparison still fails, the route raises `HTTPException(status_code=401, detail='Unauthorized')`.

The password used for callback protection is the database password. There is no separate callback signing key or endpoint-specific shared secret in the current backend code.

## Secrets and Sensitive Configuration

### Local MySQL Configuration

For `SHARE_ENV=local`, `ResourceConfigProvider.get_mysql_config()` reads local MySQL configuration from environment variables with defaults.

| Environment Variable | Default | Used For |
| --- | --- | --- |
| `DUALITY_MYSQL_HOST` | `127.0.0.1` | Local MySQL host. |
| `DUALITY_MYSQL_PORT` | `3306` | Local MySQL port. |
| `DUALITY_MYSQL_USER` | `root` | Local MySQL username. |
| `DUALITY_MYSQL_PASSWORD` | `duality_mysql_pass` | Local MySQL password. |
| `DUALITY_MYSQL_DB` | `duality_dev` | Local MySQL database name. |

### Deployed MySQL Secret

For `SHARE_ENV=dev`, `ResourceConfigProvider.get_mysql_config()` uses the hardcoded secret name:

```text
example-database-secret
```

The DEV branch then returns a `MySQLSecret` with:

| Field | Current Value / Source |
| --- | --- |
| `username` | From the Secrets Manager JSON `username` field. |
| `password` | From the Secrets Manager JSON `password` field. |
| `host` | Hardcoded to `database.example.org`. |
| `port` | Hardcoded to `3306`. |
| `dbname` | Hardcoded to `duality_dev`. |

`SecretsManager.get_mysql_secret()` expects a JSON secret with this shape:

```json
{
  "username": "database_user",
  "password": "database_password",
  "host": "optional_host_value",
  "port": 3306,
  "dbname": "duality_dev"
}
```

The current DEV resource provider ignores the secret's `host`, `port`, and `dbname` when returning the final config, because it replaces those values with hardcoded DEV settings. The secret's `host`, `port`, and `dbname` are still parsed by `SecretsManager` before the provider returns the final DEV object.

`SecretsManager` caches the MySQL secret in `_cached_mysql_secret` when `check_cached=True`. The callback password checks pass `check_cached=False` on retry to handle rotated or stale cached database passwords.

### AWS Region

| Environment Variable | Default | Used By |
| --- | --- | --- |
| `AWS_REGION` | `us-east-1` | `SecretsManager`, NVFlare runtime `sm.py` helpers, and `SSHConnectionProvider`. |
| `AWS_DEFAULT_REGION` | None, fallback path only | `NVFlareAdminKitManager` uses `AWS_REGION` or `AWS_DEFAULT_REGION`, then falls back to `us-east-1`. |

### SSH Secret

`SSHConnectionProvider._ensure_key_file()` retrieves the SSH private key from Secrets Manager using this secret name:

```text
nvflare/ssh_key
```

The secret value is expected to be the raw private key string. The provider writes the key to the configured PEM path and sets permissions to `0400`.

For `SHARE_ENV=dev`, `ResourceConfigProvider.get_nvflare_ec2_ssh_config()` returns:

| Field | Value |
| --- | --- |
| `host` | `nvflare.example.org` |
| `username` | `ubuntu` |
| `port` | `22` |
| `private_key_path` | `/app/keys/nvflare.pem` |

For `SHARE_ENV=local`, the SSH config has blank host, username, and key path values. Code paths that instantiate `SSHConnectionProvider` still call `_ensure_key_file()`, so local flows should avoid SSH-backed behavior unless local SSH configuration is added.

### NVFlare Runtime Callback Secret Helpers

Packaged NVFlare runtime files include small `sm.py` helpers that call AWS Secrets Manager and return only the MySQL password. These helpers are used by job runtime callback code when the job is not in local-build mode.

Relevant runtime files:

| File | Secret Behavior |
| --- | --- |
| `jobs/nvflare_job_template/app_server/custom/sm.py` | Reads the named secret and returns `secret_dict['password']`. |
| `jobs/participation_confirmation/app_server/custom/sm.py` | Reads the named secret and returns `secret_dict['password']`. |
| `jobs/nvflare_job_template/app_server/custom/backend_webhook_writer.py` | Adds `$pw` to `/nvflare/client/emit_progress` payloads when not local build. |
| `jobs/participation_confirmation/app_server/custom/response_aggregator.py` | Adds `$pw` to `/clients/participation/submit` payloads when not local build. |

The runtime helpers require a JSON secret containing a `password` field. If `password` is absent, they raise a `KeyError`.

## Identity Provider and Token Status

There is no current OAuth2, OIDC, JWT, session-cookie, or bearer-token validation implemented in the FastAPI backend.

Current code search results show no route dependency using FastAPI `Depends` for auth, no `Authorization` header parsing, and no JWT verification logic. The only auth-like checks in route code are the non-local `$pw` checks on the internal callback-style endpoints.

## Route-Level Access Assumptions

### Frontend-Facing Endpoints

The current frontend-facing endpoints assume the caller is trusted once the request reaches the backend:

- project list
- project datasource lookup
- supported functions
- filter lookup
- job submission
- job history
- direct-results context bootstrap
- job status polling
- job results
- job function config
- job result mapping
- client connection status
- participation status

Some of these routes have inline TODO comments to put them behind bearer-token auth, but those comments do not currently change request handling.

### Username-Based Context

Several routes accept `username` as request data and use it as application context:

| Endpoint | Username Use |
| --- | --- |
| `/user/role` | Resolves role and project datasource assignments. |
| `/clients/connection/status` | Marks matching client rows as belonging to the submitted user via `is_submitted_user`. |
| `/clients/participation/status` | Uses username when retrieving the NVFlare client snapshot. |
| `/projects/fhir/source` | Resolves the user ID and datasource assignment for the submitted username/project. |
| `/nvflare/jobs/submit` | Accepts optional `submitter` and passes it into `JobRunnerService.request_job_run`. |

The backend does not currently compare submitted usernames against an authenticated principal.

### FHIR Query Proxying

`/projects/fhir/source` can execute a FHIR query when `execute_query` is supplied and the configured datasource is not a `.json` source.

Current behavior:

1. The backend resolves the user's configured source for `username`, `project_id`, and optional `datasource_group`.
2. If `source` ends with `.json`, query execution is skipped.
3. Otherwise, `execute_query` is normalized to a path and joined to the configured source URL.
4. The backend sends `requests.get(full_url, headers={'Accept': 'application/fhir+json, application/json'}, timeout=60)`.
5. The response status and body are returned to the caller.

There is no token enforcement on this route and no allowlist beyond the datasource URL stored for that user/project. The effective upstream target is controlled by the datasource assignment in `users_fhir_source_by_project`.

## Data Exposure Considerations in Current Routes

The following current behaviors affect data exposure boundaries:

| Area | Current Behavior |
| --- | --- |
| Job status | `/jobs/status` and websocket status routes read by submitted job ID. |
| Job info | `/jobs/info` reads by `nvflare_job_id`, `job_runner_id`, or internal job table ID. |
| Direct Results context | `/nvflare/jobs/results_context` resolves job, project, datasource-group, and filter context from an NVFlare-assigned UUID. |
| Job results | `/jobs/results` reads by `nvflare_job_id`, `function`, and `workflow_id`. |
| Job mapping | `/jobs/results/mapping` lists workflow directories and optional profile summary by job/function. |
| Project datasources | `/projects/fhir/source` returns the configured datasource for submitted username/project context. |
| Client status | Client status routes expose NVFlare client connection/participation state. |
| Job history | `/nvflare/jobs/history` filters by project and optional functions/date filters. |

The current code does not check that the caller owns or is allowed to view the requested job, datasource, project, or client state.

## Error Handling and Security-Relevant Failure Behavior

| Area | Behavior |
| --- | --- |
| Missing `SHARE_ENV` | Prints an error and exits the process. |
| Invalid `SHARE_ENV` | Prints an error and exits the process. |
| Missing deployed MySQL secret name | `SecretsManager.get_mysql_secret()` raises `ValueError`. |
| Empty deployed MySQL `SecretString` | Raises `RuntimeError`. |
| Missing deployed MySQL fields | Missing `username` or `password` raises during JSON field access. |
| Secret retrieval failure | Retries three times with exponential backoff, then raises `RuntimeError`. |
| Stale cached MySQL password in callback check | Route refreshes config with `check_cached=False` and retries comparison. |
| Bad callback `$pw` | Raises `HTTPException` with status `401` and detail `Unauthorized`. |
| Missing SSH private key secret | Raises if `SecretString` is empty. |
| Existing SSH private key file | Reuses the file and does not fetch the secret again. |
| Missing user in `/user/role` | Returns `404` with `{'error': 'User not found'}`. |
| Missing user in `/projects/fhir/source` | Returns `404` with a message containing the submitted username. |
| Missing datasource in `/projects/fhir/source` | Returns `404` with username, project ID, and datasource group context. |
| Unexpected route exceptions | Most routes return `400` or `500` JSON responses containing error text; some include `traceback.format_exc().splitlines()`. |

Several error responses include traceback details in the JSON payload. This is useful during development but exposes internal file/function details to clients that can reach the endpoint.

## Logging and Sensitive Values

Current logs include request bodies and selected error details in several routes.

Examples of sensitive logging behavior:

| Code Area | Logging Behavior |
| --- | --- |
| `/nvflare/jobs/submit` | Prints the full submitted body. |
| `/nvflare/client/emit_progress` | Prints bad `$pw` values when authorization fails. |
| `/clients/participation/submit` | Prints bad `$pw` values when authorization fails. |
| `/nvflare/jobs/audit/submit` | Prints bad `$pw` values when authorization fails. |
| Failing routes | Several responses/logs include traceback lines. |

Because `$pw` is the MySQL password in non-local runtime, failed callback requests can cause a submitted password value to be printed. The current code does not redact `$pw` before logging the bad value.

## Database Tables Related to Auth and Access Context

| Table | Security / Access Role |
| --- | --- |
| `defined_roles` | Stores role names and descriptions. |
| `users` | Stores usernames, disabled password hashes for seeded users, and role IDs. |
| `users_fhir_source_by_project` | Maps users to project datasource URLs/files and optional datasource groups. |
| `defined_projects` | Stores projects shown to callers. |
| `defined_project_datasource_groups` | Defines datasource groups per project. |
| `nvflare_clients` | Maps NVFlare client names to users. |
| `nvflare_project_client_exclusions` | Stores project/client exclusions. |
| `nvflare_client_participation` | Stores participation confirmation and contributing/analyzing flags. |
| `nvflare_jobs` | Stores job records, submitter username, excluded clients, status, paths, and related IDs. |
| `nvflare_job_crypto_audit` | Stores encrypted workflow audit parameters submitted by callback. |
| `job_runner_log` | Stores job status/log entries used by polling and websocket routes. |

## Current Hardening Gaps Captured by the Code

The current backend codebase contains these current-state security gaps:

| Area | Current Gap |
| --- | --- |
| Bearer-token auth | Multiple routes contain `Put behind bearer token` comments, but bearer-token enforcement is not implemented. |
| Identity verification | Submitted usernames are trusted as request data. |
| Role enforcement | Roles are returned to the frontend but are not used to authorize route access. |
| Job ownership | Job status/result/history endpoints do not verify caller ownership or project access. |
| Callback shared secret | Internal callback endpoints reuse the MySQL password as the `$pw` shared secret. |
| Local callback protection | Local runtime bypasses `$pw` checks on callback endpoints. |
| CORS configuration | CORS origins are hardcoded in `app/main.py`, not environment-specific. |
| Error disclosure | Several error responses return traceback lines. |
| Secret logging | Bad `$pw` values are printed on failed callback authorization. |
| Environment branches | `test` and `prod` enum values exist, but resource-provider branches are currently implemented only for `local` and `dev`. |
| FHIR proxy access | `/projects/fhir/source` can proxy configured FHIR source queries without token enforcement. |

These gaps describe the current backend implementation. They are not blocking comments inside the documentation; they are part of the current security posture a developer needs to understand before wiring identity-provider enforcement or production access control.

## Secure Local Development Notes

For the current local backend:

1. Set `SHARE_ENV=local` before startup.
2. Use local MySQL variables only for local/container development.
3. Treat local callback endpoints as unprotected because the `$pw` check is bypassed in local mode.
4. Do not expose the local backend directly to an untrusted network.
5. Avoid putting real credentials into `.env`; use local-only placeholders or Docker-managed secrets where possible.
6. Be aware that request bodies and traceback details can be logged or returned during failures.

Minimal local environment shape:

```text
SHARE_ENV=local
DUALITY_MYSQL_HOST=127.0.0.1
DUALITY_MYSQL_PORT=3306
DUALITY_MYSQL_USER=root
DUALITY_MYSQL_PASSWORD=duality_mysql_pass
DUALITY_MYSQL_DB=duality_dev
AWS_REGION=us-east-1
```

## Production-Readiness Boundary

The current backend is not using the seeded `users.password_hash` field for login, is not validating tokens, and is not enforcing role-based authorization. The current `/user/role` endpoint is role lookup by username, not authentication. The current `Put behind bearer token` comments identify intended protection points, but actual enforcement is not present in the code.

Any production deployment that exposes these routes beyond a tightly controlled network boundary needs an authentication and authorization layer added before relying on the role values returned by `/user/role`.


## SHARE Client Login and Startup-Kit Authorization Gap

The SHARE Client desktop uses `POST /user/role` to obtain `role`, `username`, `client_id`, `client_name`, and project context. The current development login does not validate the displayed password field and does not return a durable authentication token.

The desktop removes arbitrary site selection and uses the returned `client_name`, but this is a client-side control only. `POST /clients/content/startup-kit` currently accepts `client_name` in the request body. Before production distribution, the backend must authenticate the caller and verify or derive the permitted site server-side before packaging any startup kit.

CORS does not protect this endpoint from non-browser desktop callers. Authorization must be enforced in backend request handling.

## SHARE Client Launch-Link Authentication Gap

The desktop can open SHARE with a reversible zlib/Base64URL payload containing:

- `username` for Explore/prefill
- `username` plus `nvflare_job_id` for direct Results

For the Results form, the frontend automatically calls `/user/role` with the supplied username and then calls `/nvflare/jobs/results_context` with the supplied job UUID. This bypasses the prototype login UI only. Neither field proves identity or authorization.

This version ships no identity-provider integration and is not supported for production use. A deployment that adds real authentication must, at minimum:

1. Authenticate the desktop against the chosen identity provider.
2. Add an authenticated backend endpoint that issues a short-lived launch code after checking the authenticated principal and requested job access.
3. Use an opaque, preferably single-use code in the browser URL instead of a raw username or identity/access token.
4. Exchange the code server-side for the normal browser session and authorized destination context.
5. Bind the code to the authenticated subject, action/scope, optional immutable job ID, project/site authorization, expiration, and unique replay identifier.
6. Remove/consume the code immediately and keep the existing frontend URL cleanup behavior.
7. Enforce bearer/session authorization on `/nvflare/jobs/results_context` and all underlying result endpoints.

Raw identity tokens should not be placed in query parameters because URLs can be retained in history and logs. The current pako-compatible payload may remain as a versioned transport envelope, but it cannot remain the trust mechanism.
