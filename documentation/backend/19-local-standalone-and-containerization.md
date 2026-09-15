# Local Standalone and Containerization

## Local Runtime Datasource Lookup

Standalone client containers no longer need a generated FHIR base config file. Local JSON data files are still copied into the client image under `/data/client/`, but datasource selection comes from backend user settings at job runtime.

For biomarker local JSON runs, backend `users_fhir_source_by_project.source` values must be `/data/client/<filename>.json`. The `.env.local` values under `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT>_<GROUP>` are host-side staging paths used by client utilities to find and copy source JSON files.

`DUALITY_NVFLARE_FHIR_BASE_CONFIG` and `DUALITY_FHIR_BASE_CONFIG.json` are not required by standalone client containers.

## Files Covered

| File | Role |
| --- | --- |
| `Dockerfile` | Primary backend container build definition based on `python:3.12-slim`. |
| `Dockerfile_alpine` | Alternate backend container build definition based on `python:3.12-alpine`. |
| `requirements.txt` | Python dependency pinning for the FastAPI backend and runtime support libraries. |
| `.env` | Local/runtime environment file placeholder. The checked-in file is empty in the current backend package. |
| `app/main.py` | FastAPI application entrypoint started by Uvicorn in both container images. |
| `app/core/EnvironmentManager.py` | Runtime environment selection through `SHARE_ENV`. |
| `app/core/aws/ResourceConfigProvider.py` | Local/deployed MySQL and SSH resource configuration. |
| `app/core/aws/SecretsManager.py` | AWS Secrets Manager wrapper used outside local mode for MySQL secrets. |
| `app/core/mysql/MySQLConnectionProvider.py` | MySQL connection pool and startup database/schema/default-data initialization. |
| `app/core/nvflare/NVFlareServerProvider.py` | Local/deployed NVFlare workspace path resolution. |
| `app/core/nvflare/NVFlareAdminKitManager.py` | NVFlare admin kit extraction and command execution support. |
| `app/core/ssh/SSHConnectionProvider.py` | SSH connection pool used for non-local NVFlare/server file access. |
| `app/core/mysql/job_tracking/NVFlareJobsDataRetriever.py` | Local/deployed result path resolution for job result reads. |
| `app/core/job_runner/nvflare_jobs/scripts/run_simulator.py` | Local NVFlare simulator helper for runtime job code. |
| `app/core/job_runner/nvflare_jobs/README.md` | Runtime simulator notes for datasource/model environment variables. |

## Runtime Shape

The backend is a FastAPI service launched through Uvicorn. Both container definitions copy `requirements.txt`, install Python dependencies, copy `./app` into `/app/app`, expose port `8000`, and start:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The application entrypoint is `app/main.py`. It creates `FastAPI(title="Duality NVFlare Backend")`, configures CORS, exposes `GET /health`, exposes `POST /user/role`, and includes the shared API router from `app/api/AppRoutes.py`.

The container does not copy the repository root `.env` file into the image. Runtime environment variables must be supplied by the shell, Docker run command, Docker Compose file, ECS task definition, or hosting platform. The checked-in `.env` file in the backend package is empty.

## Primary Dockerfile

`Dockerfile` uses `python:3.12-slim`.

It installs these Debian packages before installing Python dependencies:

| Package | Purpose in current backend context |
| --- | --- |
| `build-essential` | Native build support for Python packages with compiled extensions. |
| `default-libmysqlclient-dev` | MySQL client headers/libraries for `mysqlclient`. |
| `libxml2-dev`, `libxslt-dev` | XML/XSLT native dependencies used by packages that need XML parsing support. |
| `libsodium-dev` | Native crypto support used by encrypted/OpenFHE-adjacent runtime dependencies. |
| `openssh-client` | SSH tooling available inside the backend container. |
| `pkg-config` | Native library discovery during pip builds. |

The file sets `PYTHONUNBUFFERED=1`, which keeps Python output unbuffered so container logs appear immediately.

After package installation, it runs:

```bash
pip install --no-cache-dir -r requirements.txt
pip install --no-cache-dir nvflare
```

`requirements.txt` already pins `nvflare==2.7.2`, so the second `pip install nvflare` is a second install command for NVFlare rather than the only source of the package.

## Alternate Alpine Dockerfile

`Dockerfile_alpine` uses `python:3.12-alpine`.

It installs Alpine packages for shell support, certificates, C/Rust build tooling, MariaDB/MySQL headers, XML/XSLT libraries, OpenSSL/libffi, libsodium, pkgconfig, and OpenSSH:

```text
bash, ca-certificates, gcc, musl-dev, mariadb-dev, libxml2-dev, libxslt-dev,
libffi-dev, openssl-dev, libsodium-dev, cargo, rust, pkgconfig, openssh
```

It then installs requirements and NVFlare, copies `./app`, exposes `8000`, and starts Uvicorn with the same app target.

The Alpine image has a smaller base image but more native-build risk because packages such as `mysqlclient`, crypto libraries, and scientific/analytics dependencies can be more sensitive to musl-based builds. The slim Dockerfile is the safer default for backend parity unless the Alpine image is explicitly tested for the target deployment.

## Python Dependencies

`requirements.txt` currently pins:

| Package | Version | Current use area |
| --- | ---: | --- |
| `boto3` | `1.34.113` | AWS Secrets Manager and S3/admin kit access. |
| `dbutils` | `3.0.2` | MySQL pooled database connections. |
| `fastapi` | `0.115.2` | API framework. |
| `mysqlclient` | `2.2.4` | MySQLdb driver used by `MySQLConnectionProvider`. |
| `pymysql` | `1.1.0` | MySQL client dependency available to the runtime. |
| `uvicorn[standard]` | `0.30.1` | ASGI server. |
| `paramiko` | `4.0.0` | SSH command/file access in `SSHConnectionProvider`. |
| `pexpect` | `4.9.0` | Interactive NVFlare admin shell automation. |
| `lifelines` | `0.30.0` | Survival/statistical analytics runtime. |
| `nvflare` | `2.7.2` | NVFlare job execution/admin/runtime support. |

The analytics runtime also imports additional libraries from packaged runtime code paths, including standard scientific/data libraries used by the generated job code. The container dependency list should remain aligned with what the backend imports at startup and what the packaged job code imports when executed in this runtime context.

## Required Runtime Environment Variables

`SHARE_ENV` is the required environment selector. `EnvironmentProvider.get_env()` reads this value, caches it, and terminates the process with `os._exit(1)` if it is missing or not one of the defined values.

| Variable | Required | Values/default | Used by | Behavior |
| --- | --- | --- | --- | --- |
| `SHARE_ENV` | Yes | `local`, `dev`, `test`, `prod` | `EnvironmentProvider` | Selects local/deployed behavior. Missing or invalid values terminate the backend process. |
| `AWS_REGION` | No | Defaults to `us-east-1` where used | `SecretsManager`, `NVFlareAdminKitManager`, `SSHConnectionProvider` | AWS client region. |
| `AWS_DEFAULT_REGION` | No | Used as fallback by admin kit manager | `NVFlareAdminKitManager` | Fallback region for non-local admin kit S3 access. |

Only `local` and `dev` have concrete resource configuration in the current code. `test` and `prod` are valid enum values, but `ResourceConfigProvider.get_mysql_config()` and `ResourceConfigProvider.get_nvflare_ec2_ssh_config()` do not currently return explicit configs for those environments.

## Local MySQL Environment Variables

In `SHARE_ENV=local`, `ResourceConfigProvider.get_mysql_config()` builds the MySQL connection from local environment variables with defaults.

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `DUALITY_MYSQL_HOST` | `127.0.0.1` | `ResourceConfigProvider.get_mysql_config()` | MySQL host for local backend runtime. |
| `DUALITY_MYSQL_PORT` | `3306` | `ResourceConfigProvider.get_mysql_config()` | Parsed with `int(...)`; invalid non-numeric values will raise during config construction. |
| `DUALITY_MYSQL_USER` | `root` | `ResourceConfigProvider.get_mysql_config()` | Local MySQL username. |
| `DUALITY_MYSQL_PASSWORD` | `duality_mysql_pass` | `ResourceConfigProvider.get_mysql_config()` | Local MySQL password. |
| `DUALITY_MYSQL_DB` | `duality_dev` | `ResourceConfigProvider.get_mysql_config()` | Database name created/used by `MySQLConnectionProvider`. |

A safe local `.env` or Compose environment block for the backend currently looks like:

```env
SHARE_ENV=local
DUALITY_MYSQL_HOST=127.0.0.1
DUALITY_MYSQL_PORT=3306
DUALITY_MYSQL_USER=root
DUALITY_MYSQL_PASSWORD=duality_mysql_pass
DUALITY_MYSQL_DB=duality_dev
DUALITY_NVFLARE_HOST=127.0.0.1
DUALITY_NVFLARE_WORKSPACE=./nvflare_workspace
DUALITY_NVFLARE_JOB_SAVE_LOCATION=./nvflare_workspace/job-results
```

The repository does not currently include a Docker Compose file. If Compose is used for standalone local development, these values should be supplied under the backend service `environment:` or `env_file:` section.

## Deployed MySQL and Secrets Manager Behavior

In non-local code paths, MySQL configuration is currently implemented for `Environment.DEV`.

For `dev`, `ResourceConfigProvider.get_mysql_config()`:

1. Uses secret name `example-database-secret`.
2. Calls `SecretsManager.get_mysql_secret(...)`.
3. Returns a `MySQLSecret` using the secret username/password, fixed host `database.example.org`, port `3306`, and database `duality_dev`.

`SecretsManager.get_mysql_secret()` expects a JSON secret string containing:

```json
{
  "username": "...",
  "password": "...",
  "host": "...",
  "port": 3306,
  "dbname": "duality_dev"
}
```

Only `username` and `password` are required by direct key access. `host`, `port`, and `dbname` have fallback handling inside `SecretsManager`, although the current dev config overrides host, port, and dbname after loading the secret.

The secret is cached in memory as `_cached_mysql_secret` when `check_cached=True`. Retrieval is attempted up to three times with exponential backoff before raising a `RuntimeError`.

## MySQL Startup Initialization

`MySQLConnectionProvider` is not only a connection factory. Its constructor performs runtime database setup.

Startup behavior is:

1. Resolve MySQL connection settings through `ResourceConfigProvider.get_mysql_config()`.
2. Ensure the configured database exists.
3. Create a pooled DBUtils `PooledDB` connection pool with `maxconnections=150`.
4. Create tables from the central `create_tables_str` block.
5. Run schema checks/ALTERs for `users_fhir_source_by_project`.
6. Ensure lookup indexes/columns for participation and function config tables.
7. Insert default supported functions.
8. Insert default roles.
9. Insert default filter systems.
10. Insert default projects.
11. Insert test users.
12. In local mode, insert default NVFlare clients.
13. Insert default project datasource groups.
14. Insert default project workflow groups.
15. Insert default user FHIR sources.

Because initialization runs from the connection provider constructor, any route/manager path that creates the provider can trigger database/schema/default-data checks. Local startup therefore requires MySQL to be reachable before database-backed endpoints can complete successfully.

## Local NVFlare Environment Variables

`NVFlareProvisionProvider.get_nvflare_instance()` resolves local NVFlare paths when `SHARE_ENV=local`.

| Variable | Default | Used by | Behavior |
| --- | --- | --- | --- |
| `DUALITY_NVFLARE_HOST` | `127.0.0.1` | `NVFlareServerProvider`, `NVFlareJobsDataRetriever` | Used as the server/host folder name under the local workspace. |
| `DUALITY_NVFLARE_WORKSPACE` | `./nvflare_workspace` | `NVFlareServerProvider`, `NVFlareJobsDataRetriever` | Local workspace base path. Converted to an absolute path by `NVFlareServerProvider`. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `<workspace>/job-results` in `NVFlareServerProvider`; `<workspace>/<host>/job-results` in `NVFlareJobsDataRetriever._local_jobs_root()` when unset | NVFlare provision/result retrieval | Explicit job result root. Set this explicitly in local standalone mode to avoid provider/retriever default path differences. |

For local mode, `NVFlareProvisionProvider` returns:

| Field | Local value |
| --- | --- |
| `base_location` | Absolute `DUALITY_NVFLARE_WORKSPACE` or `./nvflare_workspace`. |
| `admin_location` | `<base>/admin@share.local`. |
| `server_location` | `<base>/<DUALITY_NVFLARE_HOST>`. |
| `client_to_server_job_save_location` | Absolute `DUALITY_NVFLARE_JOB_SAVE_LOCATION` or `<base>/job-results`. |

For `dev`, the provider uses `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00`, admin path `admin@share.local`, server folder `nvflare.example.org`, and result path under `site3/job-results`.

## NVFlare Admin Kit Environment Variables

`NVFlareAdminKitManager` requires an admin kit tarball path.

| Variable | Required | Used by | Behavior |
| --- | --- | --- | --- |
| `DUALITY_ADMIN_TAR` | Yes when admin kit manager is used | `NVFlareAdminKitManager` | Local mode treats this as a local tar path. Non-local mode uses S3 download behavior. Missing value raises `ValueError("DUALITY_ADMIN_TAR is not set")`. |
| `DUALITY_NVFLARE_ADMIN_NAME` | Conditional | `NVFlareAdminKitManager.run()` | Sent to `fl_admin.sh` when the admin shell prompts for a username. |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | No | `NVFlareAdminKitManager` | Region for non-local S3 access. Defaults to `us-east-1`. |

The manager extracts the admin kit under `/app/nvflare/admin`, tracks the current tarball fingerprint with `.etag`, locates `startup/fl_admin.sh`, and runs commands through `pexpect`.

## SSH Environment and Secret Behavior

`SSHConnectionProvider` is used for non-local result/file/server operations. It gets host/user/port/key path from `ResourceConfigProvider.get_nvflare_ec2_ssh_config()`.

For `local`, the resource provider returns blank SSH host/user/key path values and port `22`; local result readers avoid SSH by checking `Environment.LOCAL`.

For `dev`, the resource provider returns:

| Field | Value |
| --- | --- |
| Host | `nvflare.example.org` |
| Username | `ubuntu` |
| Port | `22` |
| Private key path | `/app/keys/nvflare.pem` |

If the PEM file is not present, `SSHConnectionProvider` fetches the secret `nvflare/ssh_key` from AWS Secrets Manager, writes it to the configured key path, and chmods it to `0400`. It pre-populates a pool of five Paramiko SSH connections.

## FHIR and Simulator Runtime Environment Variables

The packaged NVFlare runtime and simulator scripts use additional variables when running analytics jobs or simulator runs.

| Variable | Used by | Behavior |
| --- | --- | --- |
| `DUALITY_NVFLARE_FHIR_BASE` | `FHIRBaseConfigResolver` | Optional single FHIR base/source override. |
| `FL_IS_SIMULATOR` | FHIR resolver, analytics runtime, simulator helpers | Enables simulator behavior when set to truthy values such as `1`, `true`, `yes`, or `on`. |
| `DUALITY_SIM_DATASOURCE_VERSION` | FHIR resolver, simulator helpers, model resolution | Suffix used for per-site datasource/model variables. Defaults to `2_1` in `FHIRBaseConfigResolver` and runtime utilities; `run_simulator.py` has its own `DEFAULT_SIM_DATASOURCE_VERSION`. |
| `DUALITY_SERVER_DATASOURCE_<suffix>` | FHIR resolver | Per-site simulator datasource path for the server/initiator. |
| `DUALITY_CLIENT_SITE1_DATASOURCE_<suffix>` | FHIR resolver | Per-site simulator datasource path for `site-1`/`site1`. Additional site numbers follow the same pattern. |
| `DUALITY_SIM_DATASOURCE_BASE` | FHIR resolver and simulator helpers | Base path for resolving relative simulator datasource paths. |
| `DUALITY_SIM_ENV_FILE` | `run_simulator.py` | Explicit `.env.local` file loaded by the simulator helper without overwriting existing shell variables. |
| `DUALITY_SIM_BIOMARKER_MODELS_ROOT` | Runtime utility code, `tests/conftest.py` | Optional biomarker model root override. On a full public checkout, direct tests default to `standalone/client_utils/model_files/project_2`; datasource `2_1` resolves `datasource_group_1`. |
| `DUALITY_SIM_CKKS_RING_DIM` | `openfhe_manager.py`, `tests/conftest.py`, `docker_simulator_runner/run_simulator_sweep.py` | Pins the CKKS ring dimension for every party of a simulator run. An explicitly set value always wins and is forwarded into the sweep container. When unset, `tests/conftest.py` applies `4096` (`LEAN_CKKS_RING_DIM`) at import time if `DUALITY_SWEEP_MODE` is explicitly `lean`, and otherwise leaves it unset so the parties build a full `HEStd_128_classic` context. Pinning any ring forces the security level to `HEStd_NotSet`, so a reduced ring is insecure and test-only. |
| `DUALITY_SWEEP_MODE` | `tests/conftest.py`, `docker_simulator_runner/run_simulator_sweep.py`, `docker_simulator_runner/container_entrypoint.py` | Simulator sweep run mode, `lean` or `full`, exported by the sweep runner from `--mode`. Only an explicit `lean` enables the lean-only behavior (reduced ring default, stripping profiler/trace components from staged configs, workspace pruning), so a bare-host `pytest` run is unaffected. |
| `DUALITY_SWEEP_JOBS` | `docker_simulator_runner/run_simulator_sweep.py`, `docker_simulator_runner/container_entrypoint.py` | Requested `pytest-xdist` worker count (`-n`) for lean sweeps, exported from `--jobs`. `0` or less means auto; any value is capped at runtime by CPU cores and the memory budget. Ignored in full mode, which always runs serially. |
| `DUALITY_BACKEND_URL` | Packaged job webhook/runtime files | Backend API base for progress/audit/response webhooks. Simulator defaults this to `http://127.0.0.1:1`. |
| `DUALITY_SIM_ENABLE_BACKEND_HTTP` | Packaged job webhook/runtime files | Enables simulator HTTP POSTs to `DUALITY_BACKEND_URL`; simulator runs skip these POSTs by default. |
| `DUALITY_NVFLARE_LOG_PATH` | Packaged job webhook/runtime files | Runtime log path, defaulting to `./logs/duality_nvflare.log` in the job custom code. |
| `FILTERS_PATH` | Participation confirmation response aggregator | Defaults to `custom/filters.json`. |
| `OPENFHE_BIOMARKER_MAX_WORKERS` | `openfhe_manager.py` | Optional worker limit for OpenFHE biomarker processing. |
| `OMP_NUM_THREADS` | `openfhe_manager.py` | Temporarily controlled by OpenFHE runtime code in selected execution paths. |

These variables are primarily for packaged job runtime/simulator behavior rather than FastAPI startup, but they matter for local standalone testing because the backend packages and launches jobs that may depend on them.

The `DUALITY_SWEEP_*` variables belong to the containerized simulator sweep harness, which is documented in `app/core/job_runner/nvflare_jobs/tests/docker_simulator_runner/README.md`.

The public simulator path is local-wheel-only. The Docker sweep builds/installs a local snapshot, while direct Linux pytest runs require the committed `standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl`. `tests/conftest.py` checks the installed version and fails instead of allowing a package-registry replacement.

## Local Startup

A direct local backend startup uses the same Uvicorn target as the container:

```bash
export SHARE_ENV=local
export DUALITY_MYSQL_HOST=127.0.0.1
export DUALITY_MYSQL_PORT=3306
export DUALITY_MYSQL_USER=root
export DUALITY_MYSQL_PASSWORD=duality_mysql_pass
export DUALITY_MYSQL_DB=duality_dev
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

A local Docker run follows the same environment requirements:

```bash
docker build -t duality-backend-local .
docker run --rm -p 8000:8000 \
  -e SHARE_ENV=local \
  -e DUALITY_MYSQL_HOST=host.docker.internal \
  -e DUALITY_MYSQL_PORT=3306 \
  -e DUALITY_MYSQL_USER=root \
  -e DUALITY_MYSQL_PASSWORD=duality_mysql_pass \
  -e DUALITY_MYSQL_DB=duality_dev \
  duality-backend-local
```

When MySQL runs in another container on the same Docker network, use that service name instead of `host.docker.internal`.

## Health Check

`GET /health` returns a plain text response:

```text
ok
```

The route is lightweight and does not check MySQL, NVFlare, SSH, Secrets Manager, or the admin kit. A container or ALB health check using `/health` verifies that the FastAPI process is reachable, not that all downstream dependencies are healthy.

## Local/Deployed Behavior Differences

| Area | Local behavior | Deployed/dev behavior |
| --- | --- | --- |
| Environment selection | `SHARE_ENV=local`. | `SHARE_ENV=dev` for the implemented deployed config. |
| MySQL credentials | Read from `DUALITY_MYSQL_*` variables with defaults. | Username/password loaded from AWS Secrets Manager secret `example-database-secret`; host/db fixed in code for dev. |
| Database setup | Creates local database/schema/default rows against configured MySQL. | Same provider initialization pattern against deployed MySQL. |
| Default NVFlare clients | Inserted only when environment is local. | Not inserted by the local-only seed branch. |
| NVFlare workspace | Derived from `DUALITY_NVFLARE_WORKSPACE`, `DUALITY_NVFLARE_HOST`, and `DUALITY_NVFLARE_JOB_SAVE_LOCATION`. | Fixed dev workspace paths under `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00`. |
| Result reading | Reads local JSON files directly. | Uses SSH provider for remote file reads. |
| SSH key | Not used by local result readers. | Fetched from AWS Secrets Manager secret `nvflare/ssh_key` if `/app/keys/nvflare.pem` is absent. |
| Admin kit | `DUALITY_ADMIN_TAR` points to local tar path when admin kit manager is used. | Admin kit manager uses S3-capable behavior with AWS region. |
| Webhook behavior in simulator | Simulator skips backend HTTP by default unless `DUALITY_SIM_ENABLE_BACKEND_HTTP=1`. | Packaged job runtime posts to configured `DUALITY_BACKEND_URL` when not in simulator skip mode. |

## Resetting Local Database State

The backend creates the configured database if it does not exist and creates missing tables/default data on startup. A full local reset is performed outside the application by dropping the configured local database and restarting the backend.

For the default local database:

```sql
DROP DATABASE duality_dev;
```

On the next backend startup with `SHARE_ENV=local`, `MySQLConnectionProvider` recreates the database, tables, indexes/ALTERs, and default rows. This should only be done against a disposable local database.

## Common Startup Failures

| Symptom | Likely cause | Current behavior / fix |
| --- | --- | --- |
| Process exits immediately with environment error | `SHARE_ENV` missing or invalid | Set `SHARE_ENV` to `local`, `dev`, `test`, or `prod`. Only `local` and `dev` have concrete resource configs in current code. |
| MySQL connection failure during first database-backed request | MySQL is not reachable from the container or credentials are wrong | Verify `DUALITY_MYSQL_HOST`, port, username, password, and container networking. For Docker Desktop with host MySQL, use `host.docker.internal`. |
| `invalid literal for int()` while building MySQL config | `DUALITY_MYSQL_PORT` is not numeric | Set `DUALITY_MYSQL_PORT=3306` or another numeric port. |
| AWS secret retrieval fails in dev | AWS credentials/role/region/secret access issue | Verify AWS identity, region, and access to the configured RDS secret. `SecretsManager` retries three times before raising. |
| Admin kit manager raises `DUALITY_ADMIN_TAR is not set` | NVFlare admin operations were invoked without an admin kit tar path | Set `DUALITY_ADMIN_TAR` to the local tar path in local mode or the deployed tar reference expected by the admin kit flow. |
| SSH provider fails to create connections | Missing/invalid `nvflare/ssh_key`, bad EC2 host, blocked network, or wrong IAM permissions | Confirm Secrets Manager access, key content, security group/network path, and `/app/keys/nvflare.pem` permissions. |
| `/health` succeeds but job/status calls fail | `/health` does not validate downstream services | Check MySQL, NVFlare workspace/admin kit, SSH, result paths, and required job runtime variables. |
| Local job results are not found | Result writer and result reader are using different default paths | Set `DUALITY_NVFLARE_JOB_SAVE_LOCATION` explicitly so staging/runtime/result retrieval agree on the job result root. |
| Simulator tries to call a dummy backend URL | Simulator HTTP integration is enabled with an unreachable `DUALITY_BACKEND_URL` | Leave `DUALITY_SIM_ENABLE_BACKEND_HTTP` unset for offline simulator runs, or set it only when a real backend URL is available. |


## Client Supervisor Integration

The local client operator application now lives at `share/client-supervisor`. It is separate from the main standalone stack but reads local datasource mappings and files from `share/standalone/.env.local` and `share/standalone/nvflare_stage/data`.

The supervisor's local result service is `client-supervisor/local-results-api`. It mounts the installed per-user workspace from `~/.duality-client/<site>` at `/nvflare:ro` and reads `/nvflare/job-results`.
