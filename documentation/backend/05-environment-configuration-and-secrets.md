# Environment Configuration and Secrets

## Files Covered

| File | Role |
| --- | --- |
| `app/core/EnvironmentManager.py` | Environment enum, required `SHARE_ENV` lookup, and cached environment selection. |
| `app/core/aws/ResourceConfigProvider.py` | Central provider for MySQL and NVFlare EC2 SSH configuration. |
| `app/core/aws/SecretsManager.py` | AWS Secrets Manager helper for MySQL credentials. |
| `app/core/mysql/MySQLConnectionProvider.py` | MySQL pool creation and schema initialization using resolved resource config. |
| `app/core/ssh/SSHConnectionProvider.py` | NVFlare EC2 SSH connection pooling and SSH private key secret retrieval. |
| `app/core/nvflare/NVFlareServerProvider.py` | NVFlare workspace/admin/server/result path resolution. |
| `app/core/nvflare/NVFlareAdminKitManager.py` | NVFlare admin kit tarball resolution from local path or S3. |
| `app/core/mysql/job_tracking/NVFlareJobsDataRetriever.py` | Local versus remote NVFlare result retrieval path handling. |
| `app/core/job_runner/nvflare_jobs/apis/FHIRBaseConfigResolver.py` | Runtime FHIR base/source resolution for NVFlare job code. |
| `app/core/job_runner/nvflare_jobs/apis/utils.py` | Biomarker model directory resolution for NVFlare jobs and simulator runs. |
| `app/core/job_runner/nvflare_jobs/jobs/nvflare_job_template/app_server/custom/*.py` | NVFlare server-side webhook/audit/progress code using backend URL and secrets. |
| `app/core/job_runner/nvflare_jobs/jobs/participation_confirmation/app_server/custom/*.py` | Participation confirmation aggregator and backend submission code. |
| `.env` | Present in the backend package but currently empty. |
| `Dockerfile`, `Dockerfile_alpine` | Container build/runtime defaults. |

## Environment Selection

`app/core/EnvironmentManager.py` defines the supported backend environment values:

| Enum | Value |
| --- | --- |
| `Environment.DEV` | `dev` |
| `Environment.TEST` | `test` |
| `Environment.PROD` | `prod` |
| `Environment.LOCAL` | `local` |

The backend reads the active environment from `SHARE_ENV` through `EnvironmentProvider.get_env()`.

`SHARE_ENV` is required. If it is missing, the process prints an error listing the valid values and exits with `os._exit(1)`. If it is set to a value outside `dev`, `test`, `prod`, or `local`, the process prints an invalid-value error and exits with `os._exit(1)`.

The resolved environment is cached in `EnvironmentProvider._cached_env`. After the first successful lookup, later calls return the cached enum value instead of reading the environment variable again.

## Local and Deployed Behavior

The current backend uses `Environment.LOCAL` as a distinct runtime mode. Any value other than `local` is treated as a deployed/non-local runtime by most code paths, but `ResourceConfigProvider` currently contains concrete AWS resource mappings only for `dev`.

| Runtime | Current behavior |
| --- | --- |
| `local` | MySQL settings are read from local `DUALITY_MYSQL_*` variables with hardcoded defaults. NVFlare paths are resolved from local workspace variables. Some backend webhook password checks are skipped. Result retrieval reads directly from the local filesystem. |
| `dev` | MySQL credentials are fetched from AWS Secrets Manager, then combined with a hardcoded dev Aurora host/database. NVFlare workspace paths target a hardcoded EC2 workspace. SSH uses a hardcoded EC2 host and `/app/keys/nvflare.pem`. Backend webhook endpoints require a `$pw` value matching the MySQL password. |
| `test` | Enum value exists, but `ResourceConfigProvider.get_mysql_config()` and `ResourceConfigProvider.get_nvflare_ec2_ssh_config()` do not currently return test resource config. Code paths requiring those providers will receive `None` and fail downstream. |
| `prod` | Enum value exists, but `ResourceConfigProvider.get_mysql_config()` and `ResourceConfigProvider.get_nvflare_ec2_ssh_config()` do not currently return prod resource config. Code paths requiring those providers will receive `None` and fail downstream. |

## Container Runtime Context

`Dockerfile` builds from `python:3.12-slim`. It installs system dependencies, installs `requirements.txt`, installs `nvflare`, copies `./app` into the image, exposes port `8000`, and starts:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`Dockerfile_alpine` builds from `python:3.12-alpine`, installs Alpine package equivalents, installs the same Python dependencies plus `nvflare`, copies `./app`, exposes port `8000`, and starts the same Uvicorn command.

Only `Dockerfile` sets a container-level environment value directly:

| Variable | Value | File |
| --- | --- | --- |
| `PYTHONUNBUFFERED` | `1` | `Dockerfile` |

Neither Dockerfile sets `SHARE_ENV`. The runtime environment must provide it through Docker, Docker Compose, ECS task definition environment variables, or another deployment mechanism.

The backend `.env` file exists but is empty in the current package. The Dockerfiles do not copy or load `.env` explicitly. A local `.env` file only affects runtime if the developer's local execution method or compose file loads it.

## Resource Configuration Provider

`app/core/aws/ResourceConfigProvider.py` defines two resource config dataclasses/providers:

| Object | Fields |
| --- | --- |
| `MySQLSecret` | `username`, `password`, `host`, `port`, `dbname` |
| `SSHSecret` | `host`, `username`, `port`, `private_key_path`, `private_key_content` |

### MySQL Config

`ResourceConfigProvider.get_mysql_config(env=None, check_cached=True)` resolves the environment through `EnvironmentProvider.get_env()` when no environment is passed.

For `local`, it returns a `MySQLSecret` from local environment variables with defaults:

| Field | Environment variable | Default |
| --- | --- | --- |
| `host` | `DUALITY_MYSQL_HOST` | `127.0.0.1` |
| `port` | `DUALITY_MYSQL_PORT` | `3306` |
| `username` | `DUALITY_MYSQL_USER` | `root` |
| `password` | `DUALITY_MYSQL_PASSWORD` | `duality_mysql_pass` |
| `dbname` | `DUALITY_MYSQL_DB` | `duality_dev` |

For `dev`, it fetches the AWS secret named `example-database-secret`, then returns a `MySQLSecret` using:

| Field | Current value/source |
| --- | --- |
| `username` | From AWS secret `username` |
| `password` | From AWS secret `password` |
| `host` | `database.example.org` |
| `port` | `3306` |
| `dbname` | `duality_dev` |

The `host`, `port`, and `dbname` values contained in the AWS secret are parsed by `SecretsManager`, but the dev provider currently overrides host, port, and database with the hardcoded dev values above.

There is no return branch for `test` or `prod` in the current provider.

### NVFlare EC2 SSH Config

`ResourceConfigProvider.get_nvflare_ec2_ssh_config(env=None, check_cached=True)` resolves the environment through `EnvironmentProvider.get_env()` when no environment is passed.

For `local`, it returns an empty host/user config with port `22` and an empty key path.

For `dev`, it returns:

| Field | Current value |
| --- | --- |
| `host` | `nvflare.example.org` |
| `username` | `ubuntu` |
| `port` | `22` |
| `private_key_path` | `/app/keys/nvflare.pem` |

There is no return branch for `test` or `prod` in the current provider.

## Secrets Manager

`app/core/aws/SecretsManager.py` creates a boto3 Secrets Manager client at import time using:

| Variable | Default |
| --- | --- |
| `AWS_REGION` | `us-east-1` |

`SecretsManager.get_mysql_secret(secret_name, check_cached=True)` retrieves a secret from AWS Secrets Manager and normalizes it into a `MySQLSecret`.

Expected JSON structure:

```json
{
  "username": "database_user",
  "password": "database_password",
  "host": "optional_host",
  "port": 3306,
  "dbname": "optional_database_name"
}
```

Required fields:

| Field | Required by current code |
| --- | --- |
| `username` | Yes |
| `password` | Yes |
| `host` | No; defaults to empty string |
| `port` | No; defaults to `3306` |
| `dbname` | No; defaults to `duality_dev` |

Caching behavior:

- `_cached_mysql_secret` stores the last successfully loaded MySQL secret.
- If `check_cached=True` and `_cached_mysql_secret` is present, the cached secret is returned.
- If `check_cached=False`, the secret is fetched again and the cache is replaced.

Failure behavior:

| Failure | Current behavior |
| --- | --- |
| Missing `secret_name` | Raises `ValueError`. |
| Empty `SecretString` | Raises `RuntimeError` inside the retry loop. |
| Invalid JSON | Caught by retry loop, retried up to three attempts. |
| Missing `username` or `password` | Raises `KeyError` inside the retry loop. |
| AWS/client failure | Retried up to three attempts. |
| All attempts fail | Raises `RuntimeError` chained from the last exception. |

Retry behavior is three attempts with exponential sleep intervals of `1`, `2`, and `4` seconds because the loop sleeps with `time.sleep(2 ** attempt)` for attempts `0`, `1`, and `2`.

## AWS Secret Names

| Secret name | Used by | Expected content |
| --- | --- | --- |
| `example-database-secret` | `ResourceConfigProvider.get_mysql_config()` for `dev`; NVFlare job-template cloud fallback code. | JSON object with at least `username` and `password`; optional `host`, `port`, `dbname`. |
| `nvflare/ssh_key` | `SSHConnectionProvider._ensure_key_file()` | Raw private key string in `SecretString`, not JSON. |

The NVFlare job template also contains `ParticipationSecretsManager.get_mysql_password(secret_name)`, which expects a JSON secret containing a `password` field. That helper is used by server-side NVFlare job custom code when no `DUALITY_BACKEND_URL` is provided and the code switches to its cloud fallback mode.

## MySQL Connection Setup

`app/core/mysql/MySQLConnectionProvider.py` is the central MySQL connection lifecycle class.

Startup sequence:

1. Calls `ResourceConfigProvider.get_mysql_config(check_cached=False)`.
2. Saves host, username, password, database, and port onto the provider instance.
3. Opens a raw MySQL connection without selecting a database.
4. Runs `CREATE DATABASE IF NOT EXISTS {dbname};`.
5. Builds a `dbutils.PooledDB` pool with `maxconnections=150`, `mincached=15`, `maxcached=45`, `blocking=True`, `autocommit=True`, `CLIENT.MULTI_STATEMENTS`, and dict cursors.
6. Runs table/schema creation and compatibility alters.
7. Seeds default functions, roles, filter systems, projects, datasource groups, workflow groups, test users, and user FHIR sources.
8. Seeds default NVFlare clients only when `SHARE_ENV` is not `local`.

If the raw connection fails during database creation, it forces a fresh resource config lookup by calling `ResourceConfigProvider.get_mysql_config(check_cached=False)` again, updates the local connection fields, and retries the raw connection once.

## NVFlare Workspace Configuration

`app/core/nvflare/NVFlareServerProvider.py` returns an `NVFlareProvision` with:

| Field | Meaning |
| --- | --- |
| `base_location` | NVFlare workspace root. |
| `admin_location` | Admin kit location under the workspace. |
| `server_location` | Server workspace location. |
| `client_to_server_job_save_location` | Job results location used for client/server result retrieval. |

For `local`, values are resolved from:

| Variable | Default | Use |
| --- | --- | --- |
| `DUALITY_NVFLARE_HOST` | `127.0.0.1` | Local server folder name under the workspace. |
| `DUALITY_NVFLARE_WORKSPACE` | `./nvflare_workspace` | Base workspace root, converted to an absolute path. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `{workspace}/job-results` | Job result root, converted to an absolute path. |

Local derived paths:

| Field | Current local formula |
| --- | --- |
| `admin_location` | `{base}/admin@share.local` |
| `server_location` | `{base}/{DUALITY_NVFLARE_HOST}` |
| `client_to_server_job_save_location` | `DUALITY_NVFLARE_JOB_SAVE_LOCATION` or `{base}/job-results` |

For `dev`, values are hardcoded:

| Field | Current dev value |
| --- | --- |
| `base_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` |
| `admin_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/admin@share.local` |
| `server_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/nvflare.example.org` |
| `client_to_server_job_save_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/site3/job-results` |

There is no return branch for `test` or `prod` in the current provider.

## NVFlare Result Retrieval

`app/core/mysql/job_tracking/NVFlareJobsDataRetriever.py` chooses local filesystem access or SSH based on `SHARE_ENV`.

| Environment | Result retrieval mode |
| --- | --- |
| `local` | Reads JSON result files directly from the filesystem. |
| Non-local | Uses `SSHConnectionProvider` to read result files from the NVFlare server. |

For local result lookup, `_local_jobs_root()` uses:

| Variable | Behavior |
| --- | --- |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | If set, used directly as the job result root. |
| `DUALITY_NVFLARE_WORKSPACE` | Used when explicit job save location is not set; defaults to `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00`. |
| `DUALITY_NVFLARE_HOST` | Appended between workspace and `job-results` when explicit job save location is not set. |

When no explicit job save location is set, the fallback formula is:

```text
{DUALITY_NVFLARE_WORKSPACE}/{DUALITY_NVFLARE_HOST}/job-results
```

If `DUALITY_NVFLARE_HOST` is unset in this fallback path, Python joins the workspace, `None`, and `job-results`, which will fail because `os.path.join()` does not accept `None` path components. Local result retrieval should set either `DUALITY_NVFLARE_JOB_SAVE_LOCATION` or `DUALITY_NVFLARE_HOST`.

## SSH Configuration and SSH Key Secret

`app/core/ssh/SSHConnectionProvider.py` obtains host/user/port/key path from `ResourceConfigProvider.get_nvflare_ec2_ssh_config(check_cached=False)`.

Current behavior:

1. The provider uses the returned SSH host, username, port, and PEM path.
2. If the PEM file does not exist at `private_key_path`, it fetches AWS secret `nvflare/ssh_key`.
3. The secret value is written to the PEM path.
4. The PEM file is chmodded to `0400`.
5. A Paramiko connection pool of up to five SSH clients is built.

The SSH key secret is expected to have the raw private key text directly in `SecretString`. It is not parsed as JSON.

`AWS_REGION` controls the Secrets Manager region for the SSH key lookup and defaults to `us-east-1`.

## NVFlare Admin Kit Configuration

`app/core/nvflare/NVFlareAdminKitManager.py` requires `DUALITY_ADMIN_TAR`.

| Variable | Required | Behavior |
| --- | --- | --- |
| `DUALITY_ADMIN_TAR` | Yes | Local filesystem tar/tar.gz path in `local`; S3 URI in non-local. |
| `DUALITY_NVFLARE_ADMIN_NAME` | Conditional | Sent to `fl_admin.sh` if the admin console prompts for a username. |
| `AWS_REGION` | Non-local defaultable | Used for S3 client region when not local. |
| `AWS_DEFAULT_REGION` | Non-local fallback | Used if `AWS_REGION` is not set. |

If `DUALITY_ADMIN_TAR` is missing, initialization raises `ValueError("DUALITY_ADMIN_TAR is not set")`.

In `local`, the tarball fingerprint is based on file size and mtime. In non-local environments, the tarball is expected to be an S3 URI and the fingerprint comes from the S3 object's ETag.

Admin kits are extracted under `/app/nvflare/admin`. The manager searches extracted folders for `startup/fl_admin.sh`, hardens execute permissions and line endings, then runs admin commands through `pexpect`.

## Backend Webhook Password Behavior

Several backend routes use a shared current-state password check in non-local environments. The route request body must include `$pw` matching the resolved MySQL password. If it does not match, the backend refreshes MySQL config once and checks again. If the refreshed password still does not match, the route raises `401 Unauthorized`.

Routes using this behavior:

| Route | File |
| --- | --- |
| `POST /nvflare/client/emit_progress` | `app/api/routes/NVFlareRoutes.py` |
| `POST /nvflare/jobs/audit/submit` | `app/api/routes/NVFlareRoutes.py` |
| `POST /clients/participation/submit` | `app/api/routes/ClientRoutes.py` |

In `local`, this `$pw` check is skipped.

The `$pw` value is currently coupled to the MySQL password, not a separate API secret.

## NVFlare Job Template Backend URL Behavior

NVFlare server-side custom code uses `DUALITY_BACKEND_URL` for backend callbacks.

Files using this variable include:

| File | Endpoint usage |
| --- | --- |
| `analytics_aggregator.py` | `POST /nvflare/client/emit_progress` |
| `analytics_persistor.py` | `POST /nvflare/client/emit_progress`; `POST /nvflare/jobs/audit/submit` |
| `backend_webhook_receiver.py` | Backend progress forwarding. |
| `backend_webhook_writer.py` | Backend progress forwarding. |
| `participation_confirmation/app_server/custom/response_aggregator.py` | `POST /clients/participation/submit` |

Current behavior:

| `DUALITY_BACKEND_URL` state | Behavior |
| --- | --- |
| Set | Code treats the job as local-build/backend-explicit mode and posts to `{DUALITY_BACKEND_URL}{endpoint}`. |
| Missing | Code switches to cloud fallback mode, uses `https://api.example.org` as the API base, and uses secret name `example-database-secret` for password lookup. |

The job-template code uses `DUALITY_NVFLARE_LOG_PATH`, defaulting to `./logs/duality_nvflare.log`, for fallback logging.

## Runtime Datasource Resolution Variables

`app/core/job_runner/nvflare_jobs/apis/FHIRBaseConfigResolver.py` now supports runtime datasource mappings registered by the client after the NVFlare server returns a backend-resolved datasource. The client-side runtime does not require a generated FHIR base config file.

| Variable | Default | Behavior |
| --- | --- | --- |
| `DUALITY_BACKEND_URL` | Cloud fallback API Gateway URL when missing in server-side custom code | Used by NVFlare server-side datasource and progress/audit components to call the backend. In standalone local runs this should resolve to the backend container, usually `http://backend:8000`. |
| `DUALITY_NVFLARE_FHIR_BASE` | Empty string | Fallback source value for resolver paths that do not receive a runtime project mapping. |
| `FL_IS_SIMULATOR` | Empty string | Simulator mode when value is one of `1`, `true`, `yes`, or `on`. Simulator mode can still use simulator datasource variables. |
| `DUALITY_SIM_DATASOURCE_VERSION` | `2_1` | Suffix for simulator datasource variables. |
| `DUALITY_SERVER_DATASOURCE_<suffix>` | None | Simulator source path for the server/initiator. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<suffix>` | None | Simulator source path for a client. Site names such as `site-1` normalize to `SITE1`. |
| `DUALITY_SIM_DATASOURCE_BASE` | None | Optional base directory for resolving relative simulator datasource paths. |

Retired client config runtime values:

```text
DUALITY_NVFLARE_FHIR_BASE_CONFIG
DUALITY_FHIR_BASE_CONFIG.json
```

Datasource source-of-truth is `users_fhir_source_by_project`. During an NVFlare job, the client sends project/datasource-group context to the server, the server calls `/clients/datasource/source`, and the returned datasource is registered into `FHIRBaseConfigResolver` in memory for downstream code.

In simulator mode, per-site simulator datasource environment variables still take precedence for simulator-only execution paths.

## Biomarker Model Source Variables

Normal backend-driven NVFlare jobs no longer use backend-local model directory variables. Model-file source locations are saved in backend user settings for the initiator user and staged into `app_client/custom/model_file_sources.json`. The initiator/leader site resolves those paths on its own filesystem during `workflow_model_upload__<model_key>`.

Simulator-only utilities can still use simulator model directory environment variables when running outside the normal backend/User Settings flow. Those variables are for simulator execution paths only and should not be treated as the source of truth for submitted backend jobs.

| Variable | Default | Behavior |
| --- | --- | --- |
| `FL_IS_SIMULATOR` | Empty string | Enables simulator-specific lookup behavior when truthy. |
| `DUALITY_SIM_BIOMARKER_MODELS_ROOT` | None | Optional root directory used by simulator-only model resolution. |
| `DUALITY_SIM_DATASOURCE_VERSION` | `2_1` | Suffix used by simulator datasource/model helper code. |
| `DUALITY_SIM_DATASOURCE_BASE` | None | Optional base directory for resolving relative simulator paths. |

For submitted jobs, verify User Settings model-file rows instead of backend environment variables.

## Simulator Runner Variables

`app/core/job_runner/nvflare_jobs/scripts/run_simulator.py` sets and reads simulator-specific variables:

| Variable | Default/behavior |
| --- | --- |
| `FL_IS_SIMULATOR` | Set to `true` by the script. |
| `DUALITY_BACKEND_URL` | Defaults to `http://127.0.0.1:1` to avoid accidental cloud-mode behavior. |
| `DUALITY_SIM_DATASOURCE_VERSION` | Defaults to script constant `2_1`; can be overridden by the environment or CLI `--datasource-version`. |
| `DUALITY_SIM_ENV_FILE` | Optional explicit env file path loaded by the simulator script. |
| `DUALITY_SIM_DATASOURCE_BASE` | Set to the parent of a located env file when applicable. |

The simulator webhooks skip HTTP posting by default when `FL_IS_SIMULATOR` is truthy. To enable real backend HTTP calls during simulator runs, set:

```bash
DUALITY_SIM_ENABLE_BACKEND_HTTP=1
DUALITY_BACKEND_URL=http://localhost:8000
```

Truthy values recognized for `DUALITY_SIM_ENABLE_BACKEND_HTTP` are `1`, `true`, `yes`, and `on`.

## Complete Environment Variable Table

| Variable | Used by | Required | Default | Current purpose |
| --- | --- | --- | --- | --- |
| `SHARE_ENV` | `EnvironmentProvider` | Yes | None | Selects `local`, `dev`, `test`, or `prod`. |
| `DUALITY_MYSQL_HOST` | `ResourceConfigProvider` | Local only if default not suitable | `127.0.0.1` | Local MySQL host. |
| `DUALITY_MYSQL_PORT` | `ResourceConfigProvider` | Local only if default not suitable | `3306` | Local MySQL port. |
| `DUALITY_MYSQL_USER` | `ResourceConfigProvider` | Local only if default not suitable | `root` | Local MySQL user. |
| `DUALITY_MYSQL_PASSWORD` | `ResourceConfigProvider` | Local only if default not suitable | `duality_mysql_pass` | Local MySQL password. |
| `DUALITY_MYSQL_DB` | `ResourceConfigProvider` | Local only if default not suitable | `duality_dev` | Local MySQL database name. |
| `AWS_REGION` | Secrets Manager, SSH key lookup, admin kit S3, job-template secret helper | Non-local AWS calls | `us-east-1` in most callers | AWS region for Secrets Manager/S3 clients. |
| `AWS_DEFAULT_REGION` | `NVFlareAdminKitManager` | No | Used before fallback to `us-east-1` if `AWS_REGION` absent | Fallback AWS region for admin kit S3 client. |
| `DUALITY_ADMIN_TAR` | `NVFlareAdminKitManager` | Yes when admin kit manager is used | None | Local tar path or non-local S3 URI for NVFlare admin kit. |
| `DUALITY_NVFLARE_ADMIN_NAME` | `NVFlareAdminKitManager` | Only if `fl_admin.sh` prompts | Empty string | Admin username sent to NVFlare admin console. |
| `DUALITY_NVFLARE_HOST` | `NVFlareServerProvider`, `NVFlareJobsDataRetriever` | Local result lookup needs it unless explicit job save path is set | `127.0.0.1` in provider; none in retriever fallback | NVFlare server host/folder name. |
| `DUALITY_NVFLARE_WORKSPACE` | `NVFlareServerProvider`, `NVFlareJobsDataRetriever` | Local only if default not suitable | `./nvflare_workspace` in provider; `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` in retriever fallback | NVFlare workspace root. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `NVFlareServerProvider`, `NVFlareJobsDataRetriever` | No | `{workspace}/job-results` in provider | Explicit job result root. |
| `DUALITY_BACKEND_URL` | NVFlare job custom server code | Required to avoid cloud fallback in job custom code | Cloud fallback API Gateway URL if missing in job custom code | Backend API base for NVFlare progress/audit/participation callbacks. |
| `DUALITY_NVFLARE_LOG_PATH` | NVFlare job custom server code | No | `./logs/duality_nvflare.log` | Log file path for NVFlare custom code fallback logging. |
| `DUALITY_TRACE_SINK_DIR` | `apis/profiler.py` | No | `/job-results` | Shared sink root for per-party `trace.jsonl` copies, written to `<sink>/traces/<job_id>/<site>/`. |
| `DUALITY_HOST_UID` | `apis/profiler.py`, `taskflow_report.py` | No | None | When set and running as root, written trace/report directories are chowned back to this uid so the host can manage them. |
| `DUALITY_HOST_GID` | `apis/profiler.py`, `taskflow_report.py` | No | Falls back to `DUALITY_HOST_UID` | Group used by the same chown behavior. |
| `DUALITY_NVFLARE_FHIR_BASE` | `FHIRBaseConfigResolver` | No | Empty string | Default FHIR base/source value. |
| `FL_IS_SIMULATOR` | FHIR resolver, simulator/job custom code, stat analytics utilities | Simulator only | Empty string; simulator script sets `true` | Enables simulator-specific source/model behavior. |
| `DUALITY_SIM_DATASOURCE_VERSION` | FHIR resolver, simulator script, simulator-only biomarker utilities | Simulator-only | `2_1` | Suffix for simulator datasource/model helper variables. |
| `DUALITY_SERVER_DATASOURCE_<suffix>` | `FHIRBaseConfigResolver` | Simulator server source when needed | None | Simulator datasource path for server/initiator. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<suffix>` | `FHIRBaseConfigResolver` | Simulator client source when needed | None | Simulator datasource path for a client site. |
| `DUALITY_SIM_DATASOURCE_BASE` | FHIR resolver, simulator script, simulator-only biomarker utilities | No | Inferred by simulator env loader when possible | Base path for resolving relative simulator data/model paths. |
| `DUALITY_SIM_BIOMARKER_MODELS_ROOT` | Simulator-only biomarker utilities | No | Search paths | Root path for simulator biomarker model directories. |
| `DUALITY_SIM_ENV_FILE` | Simulator script | No | Auto-discovery behavior | Explicit env file for simulator runs. |
| `DUALITY_SIM_ENABLE_BACKEND_HTTP` | NVFlare job custom server code | No | Disabled in simulator mode | Allows simulator runs to POST progress/audit/participation to a real backend. |
| `FILTERS_PATH` | Participation response aggregator | No | `custom/filters.json` | Relative or absolute path to staged filters payload. |
| `OPENFHE_BIOMARKER_MAX_WORKERS` | `openfhe_manager.py` | No | Code-defined behavior | Controls OpenFHE biomarker worker parallelism. |
| `OMP_NUM_THREADS` | `openfhe_manager.py` | No | Runtime/library default | Controls OpenMP thread count for OpenFHE/native math paths. |
| `PYTHONUNBUFFERED` | Dockerfile runtime | No | `1` in slim Dockerfile | Forces unbuffered Python logs. |

CGI/WSGI-style variables such as `PATH_INFO`, `REQUEST_METHOD`, `QUERY_STRING`, and `CONTENT_LENGTH` are read by the embedded participation client executor HTTP handler and are not backend deployment configuration values.

## Safe Local `.env` Example

The checked-in `.env` file is empty. A local development env file can use safe placeholders like:

```bash
SHARE_ENV=local

DUALITY_MYSQL_HOST=127.0.0.1
DUALITY_MYSQL_PORT=3306
DUALITY_MYSQL_USER=root
DUALITY_MYSQL_PASSWORD=duality_mysql_pass
DUALITY_MYSQL_DB=duality_dev

DUALITY_NVFLARE_HOST=127.0.0.1
DUALITY_NVFLARE_WORKSPACE=./nvflare_workspace
DUALITY_NVFLARE_JOB_SAVE_LOCATION=./nvflare_workspace/job-results
DUALITY_ADMIN_TAR=./local-secrets/admin.tar.gz
DUALITY_NVFLARE_ADMIN_NAME=admin@share.local

DUALITY_BACKEND_URL=http://localhost:8000
DUALITY_NVFLARE_LOG_PATH=./logs/duality_nvflare.log

DUALITY_NVFLARE_FHIR_BASE=
FL_IS_SIMULATOR=true
DUALITY_SIM_DATASOURCE_VERSION=2_1
DUALITY_SIM_DATASOURCE_BASE=/path/to/share/standalone
DUALITY_CLIENT_SITE3_DATASOURCE_2_1=nvflare_stage/data/Biomarker_RandomSplit_FHIR_Data_training-bundle.json
DUALITY_CLIENT_SITE1_DATASOURCE_2_1=nvflare_stage/data/Biomarker_RandomSplit_FHIR_Data_p3-p3.1.json
DUALITY_CLIENT_SITE2_DATASOURCE_2_1=nvflare_stage/data/Biomarker_RandomSplit_FHIR_Data_p1-p2.json
DUALITY_SIM_ENABLE_BACKEND_HTTP=0
```

This file is not automatically loaded by the Dockerfiles. The local run command, Docker Compose file, IDE run configuration, or shell session must load these variables.

## Local Run Examples

Local shell run:

```bash
export SHARE_ENV=local
export DUALITY_MYSQL_HOST=127.0.0.1
export DUALITY_MYSQL_PORT=3306
export DUALITY_MYSQL_USER=root
export DUALITY_MYSQL_PASSWORD=duality_mysql_pass
export DUALITY_MYSQL_DB=duality_dev
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Local Docker run with an env file:

```bash
docker build -t duality-backend-local .
docker run --env-file .env -p 8000:8000 duality-backend-local
```

## Deployed Dev Runtime Values

Current dev resource bindings are hardcoded in backend Python code rather than fully externalized.

| Resource | Current dev value |
| --- | --- |
| MySQL secret | `example-database-secret` |
| MySQL host | `database.example.org` |
| MySQL database | `duality_dev` |
| MySQL tunnel RDS endpoint | `database.example.org` |
| MySQL tunnel local port | `13306` |
| NVFlare EC2 host | `nvflare.example.org` |
| NVFlare EC2 SSH user | `ubuntu` |
| NVFlare SSH key path | `/app/keys/nvflare.pem` |
| NVFlare SSH key secret | `nvflare/ssh_key` |
| NVFlare workspace | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` |
| NVFlare backend callback fallback URL in job custom code | `https://api.example.org` |

## Troubleshooting Checklist

### Backend exits immediately on startup

Check `SHARE_ENV`. It must be set to exactly one of:

```text
local, dev, test, prod
```

Missing or invalid `SHARE_ENV` causes `EnvironmentProvider.get_env()` to print an error and terminate the process with `os._exit(1)`.

### Local MySQL connection fails

Check:

- `SHARE_ENV=local`
- `DUALITY_MYSQL_HOST`
- `DUALITY_MYSQL_PORT`
- `DUALITY_MYSQL_USER`
- `DUALITY_MYSQL_PASSWORD`
- `DUALITY_MYSQL_DB`
- MySQL is reachable from the backend container or local Python process.

The backend creates the configured database if the raw MySQL connection succeeds.

### Dev MySQL secret lookup fails

Check:

- `SHARE_ENV=dev`
- AWS credentials are available in the runtime.
- `AWS_REGION` points to the region containing the secret, or is omitted to use `us-east-1`.
- Secret `example-database-secret` exists.
- The secret JSON contains `username` and `password`.

### Test/prod database config fails

`test` and `prod` are valid environment enum values, but the current `ResourceConfigProvider` does not return MySQL or SSH config for them. Any code path expecting those configs can fail with `None` values. Test/prod resource mappings need concrete provider branches before those runtimes can use the current backend resource provider.

### Non-local webhook returns 401 Unauthorized

Check the request body includes `$pw` and that it matches the current MySQL password resolved through `ResourceConfigProvider.get_mysql_config()`.

Affected endpoints:

- `POST /nvflare/client/emit_progress`
- `POST /nvflare/jobs/audit/submit`
- `POST /clients/participation/submit`

The backend retries once with a refreshed secret before returning `401`.

### NVFlare admin kit initialization fails

Check:

- `DUALITY_ADMIN_TAR` is set.
- In `local`, `DUALITY_ADMIN_TAR` points to an existing local tar or tar.gz file.
- In non-local, `DUALITY_ADMIN_TAR` is an S3 URI in the form `s3://bucket/key`.
- AWS credentials can read the S3 object in non-local runtime.
- The extracted archive contains `startup/fl_admin.sh`.

### SSH result retrieval fails in dev/non-local runtime

Check:

- `SHARE_ENV=dev`
- AWS credentials can read secret `nvflare/ssh_key`.
- The secret contains the raw private key text.
- The container can write `/app/keys/nvflare.pem`.
- The EC2 host `nvflare.example.org` is reachable on port `22`.
- The SSH username is `ubuntu`.

### Local result retrieval fails

Set either:

```bash
DUALITY_NVFLARE_JOB_SAVE_LOCATION=/absolute/path/to/job-results
```

or set both:

```bash
DUALITY_NVFLARE_WORKSPACE=/absolute/path/to/workspace
DUALITY_NVFLARE_HOST=127.0.0.1
```

The safest local configuration is to set `DUALITY_NVFLARE_JOB_SAVE_LOCATION` explicitly.

### NVFlare job custom code posts to the wrong backend

Set `DUALITY_BACKEND_URL` explicitly in the NVFlare job/runtime environment. If it is missing, job custom code falls back to:

```text
https://api.example.org
```

For simulator runs, backend HTTP calls are skipped by default when `FL_IS_SIMULATOR` is truthy. Set `DUALITY_SIM_ENABLE_BACKEND_HTTP=1` to enable actual backend posting from simulator code.

### Biomarker model files are not resolved by the initiator

Check:

- The User Settings page has model-file source rows for the selected project and datasource group.
- The saved paths are paths on the initiator/leader site's filesystem, not backend container paths.
- The initiator site is included in the job and receives `task_model_upload`.
- `workflow_model_upload__<model_key>` runs before model-consuming workflows.
- Default filenames follow `{model_key}_{lookup_value}_{artifact_type}.csv`, for example `logistic_reg_Non-Small Cell Lung Cancer_cutoff.csv`.
- For encrypted Exceptional Response Discrimination, model upload should create the server-side compatibility cutoff CSV containing `ER_threshold` before meta-analysis runs.
