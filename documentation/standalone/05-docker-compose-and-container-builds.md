# Docker Compose and Container Builds

## Current Datasource Runtime Model

Standalone client utilities use datasource environment values as host-side staging paths for local JSON files. Those files are copied into client containers under `/data/client/`. The running client does not use retired `DUALITY_FHIR_BASE_CONFIG.json` or retired `DUALITY_NVFLARE_FHIR_BASE_CONFIG`; it requests its datasource from the NVFlare server, which resolves the value through backend user settings.

See `09-local-datasource-staging-and-runtime-lookup.md` for the full current flow.

## Files Covered

| File | Role |
| --- | --- |
| `docker_stage/docker-compose.yml` | Main Docker Compose file for the local standalone stack. |
| `docker_stage/mysql.Dockerfile` | MySQL image definition used by the Compose-managed database service. |
| `docker_stage/backend.Dockerfile` | Backend container build definition used by standalone. |
| `docker_stage/frontend.Dockerfile` | Frontend container build definition used by standalone. |
| `docker_stage/nvflare.Dockerfile` | NVFlare server/runtime container build definition used by standalone. |
| `docker_stage/container_builder.py` | Python helper for Docker Compose build/start/rebuild/update/reset/log/status operations. |
| `docker_stage/nvflare.Dockerfile` | NVFlare server image build. Installs fixed runtime dependencies; the `duality_nvflare_lib` wheel is installed by submitted jobs at runtime. |
| `client_utils/client.Dockerfile` | Per-site NVFlare client container Dockerfile. |
| `client_utils/client-results-agent/` | FastAPI results agent image and app served next to each non-initiator client container. |
| `client_utils/docker-compose.client-template.yml` | Template used to generate temporary per-site client Compose files. Defines both the `client` and `results-agent` services. |
| `client_utils/create_client.py` | Per-site client startup kit tar, datasource staging, client image build, container creation, and MySQL client registration helper. |
| `utils/wheel_utils.py` | Utility module retained in the standalone source tree. `duality_nvflare_lib` reaches the containers through the `local_wheels` mounts or the submitted job's runtime install, not through this helper. |
| `main.py` | CLI entrypoint that delegates stack rebuild, update, wheel, client, and UI operations to the Docker/client helpers. |

## Main Compose Stack

The main standalone Docker stack is defined in:

```text
docker_stage/docker-compose.yml
```

The Compose project name used by `ContainerBuilder` is `duality` unless changed in code. Compose resources are therefore grouped under the `duality` project, and the named MySQL volume is expected to be:

```text
duality_mysql_data
```

The main stack contains four services.

| Service | Container name | Purpose |
| --- | --- | --- |
| `mysql` | `duality-mysql` | Local MySQL database used by the backend when `DUALITY_DB_MODE=container`. |
| `backend` | `duality-backend` | FastAPI backend container. |
| `frontend` | `frontend` | React production frontend container served by `serve`. |
| `nvflare` | `duality-nvflare` | Local NVFlare server/runtime container. |

The Compose file uses this working layout:

```text
workspace-root/
  backend/
  frontend/
  standalone/
    .env.local
    docker_stage/
      docker-compose.yml
      *.Dockerfile
    nvflare_workspace/
    job-results/
    mysql_stage/init/
```

The build context for all main stack images is `../..` from `standalone/docker_stage`, which resolves to the workspace root containing `backend`, `frontend`, and `standalone`.

## Important CLI Availability Note

`main.py` contains an internal `cmd_docker()` function that supports lower-level Docker actions, but the current `argparse` setup does not register a public `docker` subcommand. That means commands such as the following are not currently available through the CLI parser:

```text
python3 main.py docker run
python3 main.py docker build
python3 main.py docker up
```

The default no-argument flow still calls `cmd_docker()` internally through `_run_full_pipeline()` when no project containers exist. Rebuild, update, wheel, client, clientdb, and ui are public commands.

## MySQL Service

The MySQL service is named `mysql` and uses:

```text
container_name: duality-mysql
build.context: ../..
build.dockerfile: standalone/docker_stage/mysql.Dockerfile
env_file: ../.env.local
```

The MySQL image is built from `mysql:8.0.41`. The Dockerfile sets default values for `MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD`, and writes a minimal MySQL configuration file that uses `utf8mb4`, `utf8mb4_0900_ai_ci`, and strict SQL mode.

Compose maps the application-oriented Duality environment values to MySQL entrypoint values:

| Compose/MySQL variable | Value source | Default in Compose/Dockerfile | Purpose |
| --- | --- | --- | --- |
| `MYSQL_DATABASE` | `${DUALITY_MYSQL_DB}` | `duality_local` | Database created by the MySQL entrypoint on first startup. |
| `MYSQL_USER` | `${DUALITY_MYSQL_USER}` | `duality` | Application database user created on first startup. |
| `MYSQL_PASSWORD` | `${DUALITY_MYSQL_PASSWORD}` | `dualitypass` | Password for the application database user. |
| `MYSQL_ROOT_PASSWORD` | `${MYSQL_ROOT_PASSWORD}` | `rootpass` | Root password for administrative access. |

The service mounts:

| Mount | Container path | Purpose |
| --- | --- | --- |
| `mysql_data` | `/var/lib/mysql` | Persistent MySQL data volume. |
| `../mysql_stage/init` | `/docker-entrypoint-initdb.d` | Optional first-start initialization SQL directory. |

Port behavior:

| Host port | Container port | Purpose |
| --- | --- | --- |
| `3307` | `3306` | Allows host tools such as Workbench to connect to the Compose MySQL service without conflicting with a host MySQL server on `3306`. |

The service has a Compose health check:

```text
mysqladmin ping -h 127.0.0.1
```

with interval `10s`, timeout `5s`, and `5` retries. The backend waits for this health check through `depends_on.mysql.condition: service_healthy`.

## Backend Service

The backend service is named `backend` and uses:

```text
container_name: duality-backend
build.context: ../..
build.dockerfile: standalone/docker_stage/backend.Dockerfile
env_file: ../.env.local
```

The backend image is built from `python:3.12-slim`. It installs system dependencies for Python packaging, MySQL client support, Git, curl, certificates, and bash. It copies `backend/requirements.txt`, installs backend Python requirements, installs `boto3`, copies the admin startup kit tar into `/kits/admin_startup_kit.tar`, and then copies the backend source into `/app`.

The backend starts with:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Port behavior:

| Host port | Container port | Purpose |
| --- | --- | --- |
| `8000` | `8000` | Exposes the FastAPI backend to the host frontend/browser and local tooling. |

Backend environment values passed by Compose:

| Variable | Value | Purpose |
| --- | --- | --- |
| `SHARE_ENV` | `local` | Marks the runtime as local standalone. |
| `DUALITY_MYSQL_HOST` | `mysql` | Uses Compose service DNS inside the Docker network. |
| `DUALITY_MYSQL_PORT` | `3306` | Uses the container-internal MySQL port. |
| `DUALITY_MYSQL_USER` | `${DUALITY_MYSQL_USER:-duality}` | App database user. |
| `DUALITY_MYSQL_PASSWORD` | `${DUALITY_MYSQL_PASSWORD:-dualitypass}` | App database password. |
| `DUALITY_MYSQL_DB` | `${DUALITY_MYSQL_DB:-duality_local}` | App database name. |
| `DUALITY_NVFLARE_HOST` | `${DUALITY_NVFLARE_HOST}` | Host folder/name used by the NVFlare workspace. |
| `DUALITY_NVFLARE_FED_PORT` | `${DUALITY_NVFLARE_FED_PORT}` | NVFlare federation port. |
| `DUALITY_NVFLARE_ADMIN_PORT` | `${DUALITY_NVFLARE_ADMIN_PORT}` | NVFlare admin port. |
| `DUALITY_NVFLARE_WORKSPACE` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` | In-container workspace path shared with the NVFlare service. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `/job-results` | In-container job result path mounted from `standalone/job-results`. |
| `DUALITY_NVFLARE_SUBMITTED_JOBS_LOCATION` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/${DUALITY_NVFLARE_HOST}/submitted_jobs` | In-container submitted jobs path for the provisioned NVFlare server workspace. |
| `DUALITY_NVFLARE_ADMIN_NAME` | `${DUALITY_NVFLARE_ADMIN_NAME}` | Admin identity used by backend NVFlare admin behavior. |
| `DUALITY_ADMIN_TAR` | `/kits/admin_startup_kit.tar` | Admin startup kit tar baked into the image. |
| `DUALITY_HOST_UID` | `${DUALITY_HOST_UID:-}` | Host user ID used to hand ownership of files the container writes to bind mounts back to the host user. Blank is a no-op. |
| `DUALITY_HOST_GID` | `${DUALITY_HOST_GID:-}` | Host group ID paired with `DUALITY_HOST_UID`. Blank falls back to the UID value. |

`DUALITY_HOST_UID` and `DUALITY_HOST_GID` are described in [Host File Ownership Variables](#host-file-ownership-variables).

Backend mounts:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `../nvflare_workspace` | `/home/ubuntu/nvflare/workspace` | Shared EC2-style NVFlare workspace root. |
| `../job-results` | `/job-results` | Shared local job results directory. |

Backend dependencies:

| Dependency | Condition |
| --- | --- |
| `mysql` | `service_healthy` |
| `nvflare` | `service_started` |

## Frontend Service

The frontend service is named `frontend` and uses:

```text
container_name: frontend
build.context: ../..
build.dockerfile: standalone/docker_stage/frontend.Dockerfile
env_file: ../.env.local
```

The frontend image uses a two-stage Node build:

1. `node:18-bullseye` build stage.
2. Installs dependencies with `npm ci` from `frontend/package*.json`.
3. Writes `.env.production` during the image build using build args `REACT_APP_API_BASE` and `REACT_APP_BUILD_FLAVOR`.
4. Copies `frontend/` source into `/app`.
5. Runs `npm run build`.
6. Uses a second `node:18-bullseye` runtime stage.
7. Copies `/app/build` into the runtime image.
8. Installs `serve` globally.
9. Serves the production build with `serve -s build -l 3000`.

Port behavior:

| Host port | Container port | Purpose |
| --- | --- | --- |
| `3000` | `3000` | Exposes the local frontend. |

Compose passes this runtime environment value:

| Variable | Value | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` | Browser-facing backend URL. |

`ContainerBuilder` also writes this file into the external frontend source tree before frontend builds when frontend is included:

```text
../frontend/.env.production.local
```

That generated file contains:

```text
REACT_APP_API_BASE=<value>
REACT_APP_BUILD_FLAVOR=<value>
```

`REACT_APP_API_BASE` is resolved from `.env.local` by checking `REACT_APP_API_BASE`, then `NEXT_PUBLIC_BACKEND_URL`, then process environment values, then falling back to `http://localhost:8000`. `REACT_APP_BUILD_FLAVOR` defaults to `local`.

The frontend depends on the backend with `depends_on.backend.condition: service_started`.

## NVFlare Service

The NVFlare service is named `nvflare` and uses:

```text
container_name: duality-nvflare
build.context: ../..
build.dockerfile: standalone/docker_stage/nvflare.Dockerfile
env_file: ../.env.local
shm_size: 4g
```

The NVFlare image is built from `ubuntu:24.04`. It installs Python 3, venv/pip, shell/network tools, Git, CMake, Ninja, build essentials, OpenSSL development headers, `libgomp1`, and builds/install `liboqs` from the Open Quantum Safe GitHub repository into `/usr/local`.

The image installs the fixed Python/runtime dependencies required by NVFlare jobs and installs the public `duality_nvflare_lib` snapshot from the local-wheel mount. The public job bootstrap wrappers never update that package from a registry; a missing local wheel is a startup/configuration error rather than a signal to download one.

NVFlare environment values passed by Compose:

| Variable | Value | Purpose |
| --- | --- | --- |
| `DUALITY_NVFLARE_HOST` | `${DUALITY_NVFLARE_HOST}` | Used to locate the provisioned server startup directory under the mounted workspace. |
| `NVFLARE_SERVER_BASE` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` | Base directory that contains provisioned NVFlare participants. |
| `DUALITY_BACKEND_URL` | `http://backend:8000` | Backend URL reachable from inside the Compose network. |
| `OPENFHE_BIOMARKER_MAX_WORKERS` | `${OPENFHE_BIOMARKER_MAX_WORKERS:-}` | Optional override for the biomarker HE dot-product `ProcessPool` worker count. Left unset, the count is `min(cpu_cores, cap, memory budget)`; a value set here is honored verbatim and is not capped to the core count. |
| `DUALITY_NVFLARE_LIB_UPDATE_DISABLED` | `${DUALITY_NVFLARE_LIB_UPDATE_DISABLED:-}` | Legacy/test passthrough. The public runtime is local-wheel-only regardless; simulator helpers may still set this defensively. |
| `DUALITY_TRACE_SINK_DIR` | `/trace-sink` | Directory the job profiler copies the server's trace into, so the backend report generator can collect it. Points at the `../job-results:/trace-sink` mount below. |
| `DUALITY_HOST_UID` | `${DUALITY_HOST_UID:-}` | Host user ID used to hand ownership of files the container writes to bind mounts back to the host user. Blank is a no-op. |
| `DUALITY_HOST_GID` | `${DUALITY_HOST_GID:-}` | Host group ID paired with `DUALITY_HOST_UID`. Blank falls back to the UID value. |

The server's primary trace is written under the internal `nvflare_workspace` mount, which the backend does not read. `DUALITY_TRACE_SINK_DIR` therefore exports a second copy into the shared job-results tree, next to the clients' traces. The profiler writes the copy to:

```text
<sink>/traces/<job-id>/<site>/trace.jsonl
```

Without the sink, the server's aggregation trace never reaches the taskflow report. When the variable is unset, the profiler falls back to `/job-results` in code.

`DUALITY_HOST_UID` and `DUALITY_HOST_GID` are described in [Host File Ownership Variables](#host-file-ownership-variables).

The service also sets `mem_limit: "${DUALITY_NVFLARE_MEM_LIMIT:-16g}"` (sized for the biomarker HE worker pool) and `shm_size: "4g"`.

NVFlare mounts:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `../nvflare_workspace` | `/home/ubuntu/nvflare/workspace` | Provisioned NVFlare workspace shared with backend. |
| `./local_wheels` | `/opt/duality/local_wheels` (`:ro`) | Optional local `duality_nvflare_lib-*.whl` installed at image build time (see Runtime Wheel Model). |
| `../job-results` | `/trace-sink` | Shared job-results directory, used only as the profiler trace-sink target named by `DUALITY_TRACE_SINK_DIR`. |

Port behavior:

| Host port | Container port | Purpose |
| --- | --- | --- |
| `${DUALITY_NVFLARE_FED_PORT:-8002}` | `8002` | NVFlare federation port. |
| `${DUALITY_NVFLARE_ADMIN_PORT:-8003}` | `8003` | NVFlare admin port. |
| `8004` | `8004` | Optional HTTP/status page port if enabled by NVFlare runtime behavior. |

The NVFlare container start command:

1. Exports `LD_LIBRARY_PATH` and `OQS_INSTALL_PATH`.
2. Creates a virtual environment at `/opt/nvflare/.venv`.
3. Installs/upgrades `pip`.
4. Installs fixed runtime dependencies required by submitted jobs.
5. Ensures `NVFLARE_SERVER_BASE` exists.
6. Finds the server startup directory. It prefers `$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST/startup` when it exists. Otherwise it searches under `$NVFLARE_SERVER_BASE` for the first `startup` directory.
7. Fails with exit code `2` if no server startup directory can be found.
8. Removes stale `daemon_pid.fl` files and kills the stale daemon process if the pid still exists.
9. Runs `stop_fl.sh` when present, waits briefly, then runs `start.sh`.
9. Keeps the container alive with `tail -f /dev/null`.

The provisioned workspace itself is generated by `nvflare_stage/nvflare_install_and_provision.py` before default stack startup or internal Docker run/build/up actions that require provisioning. The user-provided standalone package may omit the generated provisioned workspace; that omission is acceptable for documentation because the code expects it to be created by the provisioning stage.

## Host File Ownership Variables

The containers run as root, so files they write into bind-mounted host directories such as `job-results` are root-owned on the host and cannot be removed without `sudo`. `DUALITY_HOST_UID` and `DUALITY_HOST_GID` let container-side writers hand those files back to the host user.

Where the values come from:

| Setter | Behavior |
| --- | --- |
| `main.py` | After loading the env file, calls `os.environ.setdefault("DUALITY_HOST_UID", str(os.getuid()))` and the matching `DUALITY_HOST_GID` from `os.getgid()`, guarded by `hasattr(os, "getuid")`. Compose then receives them from the process environment. |
| `client_utils/create_client.py` | Applies the same `setdefault` pair to `DEF_ENV`, the environment used for every Docker/Compose subprocess it runs, so per-site client containers get the same values. |

Because both use `setdefault`, an explicitly exported `DUALITY_HOST_UID`/`DUALITY_HOST_GID` is preserved. On platforms without `os.getuid` the variables stay unset and Compose substitutes empty strings.

Where the values are consumed:

| Consumer | Behavior |
| --- | --- |
| Job profiler (`apis/profiler.py`) | Recursively chowns the written `traces/<job-id>` directory after dumping `trace.jsonl` to the trace sink. |
| Taskflow report generator (`taskflow_report.py`) | Recursively chowns the written report output directory. |

Both helpers are no-ops unless the process is running as root and `DUALITY_HOST_UID` is non-empty. `DUALITY_HOST_GID` falls back to the UID value when blank.

## Full Compose Service Definitions

### `mysql`

```yaml
mysql:
  container_name: duality-mysql
  build:
    context: ../..
    dockerfile: standalone/docker_stage/mysql.Dockerfile
  env_file:
    - ../.env.local
  environment:
    MYSQL_DATABASE: ${DUALITY_MYSQL_DB:-duality_local}
    MYSQL_USER: ${DUALITY_MYSQL_USER:-duality}
    MYSQL_PASSWORD: ${DUALITY_MYSQL_PASSWORD:-dualitypass}
    MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-rootpass}
  volumes:
    - mysql_data:/var/lib/mysql
    - ../mysql_stage/init:/docker-entrypoint-initdb.d
  ports:
    - "3307:3306"
  healthcheck:
    test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1"]
    interval: 10s
    timeout: 5s
    retries: 5
  restart: unless-stopped
```

### `backend`

```yaml
backend:
  container_name: duality-backend
  build:
    context: ../..
    dockerfile: standalone/docker_stage/backend.Dockerfile
  env_file:
    - ../.env.local
  environment:
    SHARE_ENV: local
    DUALITY_MYSQL_HOST: mysql
    DUALITY_MYSQL_PORT: 3306
    DUALITY_MYSQL_USER: ${DUALITY_MYSQL_USER:-duality}
    DUALITY_MYSQL_PASSWORD: ${DUALITY_MYSQL_PASSWORD:-dualitypass}
    DUALITY_MYSQL_DB: ${DUALITY_MYSQL_DB:-duality_local}
    DUALITY_NVFLARE_HOST: ${DUALITY_NVFLARE_HOST}
    DUALITY_NVFLARE_FED_PORT: ${DUALITY_NVFLARE_FED_PORT}
    DUALITY_NVFLARE_ADMIN_PORT: ${DUALITY_NVFLARE_ADMIN_PORT}
    DUALITY_NVFLARE_WORKSPACE: /home/ubuntu/nvflare/workspace/duality_nvflare/prod_00
    DUALITY_NVFLARE_JOB_SAVE_LOCATION: /job-results
    DUALITY_NVFLARE_SUBMITTED_JOBS_LOCATION: /home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/${DUALITY_NVFLARE_HOST}/submitted_jobs
    DUALITY_NVFLARE_ADMIN_NAME: ${DUALITY_NVFLARE_ADMIN_NAME}
    DUALITY_ADMIN_TAR: /kits/admin_startup_kit.tar
    DUALITY_HOST_UID: ${DUALITY_HOST_UID:-}
    DUALITY_HOST_GID: ${DUALITY_HOST_GID:-}
  volumes:
    - ../nvflare_workspace:/home/ubuntu/nvflare/workspace
    - ../job-results:/job-results
  ports:
    - "8000:8000"
  depends_on:
    mysql:
      condition: service_healthy
    nvflare:
      condition: service_started
  restart: unless-stopped
```

### `frontend`

```yaml
frontend:
  container_name: frontend
  build:
    context: ../..
    dockerfile: standalone/docker_stage/frontend.Dockerfile
  env_file:
    - ../.env.local
  environment:
    NEXT_PUBLIC_BACKEND_URL: http://localhost:8000
  ports:
    - "3000:3000"
  depends_on:
    backend:
      condition: service_started
  restart: unless-stopped
```

### `nvflare`

```yaml
nvflare:
  container_name: duality-nvflare
  build:
    context: ../..
    dockerfile: standalone/docker_stage/nvflare.Dockerfile
  shm_size: "4g"
  mem_limit: "${DUALITY_NVFLARE_MEM_LIMIT:-16g}"
  env_file:
    - ../.env.local
  environment:
    DUALITY_NVFLARE_HOST: ${DUALITY_NVFLARE_HOST}
    OPENFHE_BIOMARKER_MAX_WORKERS: "${OPENFHE_BIOMARKER_MAX_WORKERS:-}"
    NVFLARE_SERVER_BASE: /home/ubuntu/nvflare/workspace/duality_nvflare/prod_00
    DUALITY_BACKEND_URL: http://backend:8000
    DUALITY_NVFLARE_LIB_UPDATE_DISABLED: "${DUALITY_NVFLARE_LIB_UPDATE_DISABLED:-}"
    DUALITY_TRACE_SINK_DIR: /trace-sink
    DUALITY_HOST_UID: ${DUALITY_HOST_UID:-}
    DUALITY_HOST_GID: ${DUALITY_HOST_GID:-}
  volumes:
    - ../nvflare_workspace:/home/ubuntu/nvflare/workspace
    - ./local_wheels:/opt/duality/local_wheels:ro
    - ../job-results:/trace-sink
  ports:
    - "${DUALITY_NVFLARE_FED_PORT:-8002}:8002"
    - "${DUALITY_NVFLARE_ADMIN_PORT:-8003}:8003"
    - "8004:8004"
  restart: unless-stopped
```

## Environment Variable Table by Service

| Variable | Consumed by | Notes |
| --- | --- | --- |
| `DUALITY_DB_MODE` | Python orchestration, MySQL stage | `container` skips host MySQL setup; `host` runs host MySQL setup/check behavior. |
| `DUALITY_MYSQL_HOST` | `.env.local`, client registration helper, host mode | In Compose backend this is overridden to `mysql`. Host tools use `.env.local` value such as `localhost`. |
| `DUALITY_MYSQL_PORT` | `.env.local`, client registration helper, host mode | In Compose backend this is overridden to `3306`. Host tools use `.env.local` value such as `3307`. |
| `DUALITY_MYSQL_USER` | MySQL service, backend, client registration helper | App database user. |
| `DUALITY_MYSQL_PASSWORD` | MySQL service, backend, client registration helper | App database password. |
| `DUALITY_MYSQL_DB` | MySQL service, backend, client registration helper | App database name. |
| `MYSQL_ROOT_PASSWORD` | MySQL service | Root password for MySQL container initialization. |
| `DUALITY_DB_WIPE_ON_REBUILD` | `ContainerBuilder.rebuild()` | If true-like and mysql is included in a rebuild, the MySQL named volume is removed before rebuild unless an explicit wipe option overrides it. |
| `DUALITY_NVFLARE_HOST` | main.py, backend, nvflare, provisioning, client containers | May be auto-resolved to a local IP before runtime. Also used to locate the provisioned server workspace folder. |
| `DUALITY_NVFLARE_FED_PORT` | backend, nvflare Compose port mapping | Defaults to `8002` in Compose port mapping if omitted. |
| `DUALITY_NVFLARE_ADMIN_PORT` | backend, nvflare Compose port mapping | Defaults to `8003` in Compose port mapping if omitted. |
| `DUALITY_NVFLARE_PROJECT_FILE` | NVFlare provisioning stage | Project file used when generating workspace resources. |
| `DUALITY_NVFLARE_WORKSPACE` | client creation helper, provisioning/staging flows | Defaults to `./nvflare_workspace` in env. Client creation uses this to find the site participant directory. |
| `DUALITY_NVFLARE_ADMIN_NAME` | backend | Admin identity used for NVFlare admin flows. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | backend, client containers, results agents | Backend Compose overrides to `/job-results`; every client container and results agent also uses `/job-results`, backed by a per-site host directory for non-initiator sites. |
| `DUALITY_UI_ORIGINS` | client results agents | Comma-separated extra CORS origins appended to the results agent allow list. Passed through by `create_client.py`; blank by default. |
| `DUALITY_CLIENT_RESULTS_BASE_PORT` | `create_client.py` | Base port for per-site results agents. Defaults to `8088`; the published port is this value plus the site number. |
| `DUALITY_DOCKER_NETWORK` | client Compose template | Name of the pre-existing Docker network client containers join. Defaults to `duality_default`. |
| `DUALITY_LOCAL_WHEEL_PATH` | `create_client.py` | Optional path to a `duality_nvflare_lib-*.whl` staged into `client_utils/local_wheels/` before the client build. |
| `DUALITY_BACKEND_URL` | nvflare container, client helper backend ping | Compose sets `http://backend:8000` for NVFlare; client helper defaults to `http://localhost:8000` unless env overrides. |
| `DUALITY_TRACE_SINK_DIR` | nvflare container job profiler | Compose sets `/trace-sink`, backed by the `../job-results` bind mount. The profiler writes `<sink>/traces/<job-id>/<site>/trace.jsonl`. Code falls back to `/job-results` when unset. |
| `DUALITY_HOST_UID` | backend, nvflare, client containers | Seeded by `main.py` and `create_client.py` from `os.getuid()`. Container writers chown bind-mount output back to this user. Blank is a no-op. |
| `DUALITY_HOST_GID` | backend, nvflare, client containers | Seeded by `main.py` and `create_client.py` from `os.getgid()`. Used with `DUALITY_HOST_UID`; blank falls back to the UID value. |
| `NEXT_PUBLIC_BACKEND_URL` | frontend container runtime, frontend env helper | Compose sets `http://localhost:8000`. |
| `REACT_APP_API_BASE` | `ContainerBuilder._write_frontend_env()`, frontend Dockerfile build arg support | Used by CRA-style frontend builds when present. |
| `REACT_APP_BUILD_FLAVOR` | `ContainerBuilder._write_frontend_env()`, frontend Dockerfile build arg support | Defaults to `local`. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE` | `client_utils/create_client.py` | Legacy single datasource pattern mapped to project `1`. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>` | `client_utils/create_client.py` | Ungrouped datasource for a project. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>_<DATASOURCE_GROUP_ID>` | `client_utils/create_client.py` | Grouped datasource for a project/datasource group. |

## Port Mapping Table

| Service | Host port | Container port | Configurable | Purpose |
| --- | --- | --- | --- | --- |
| `mysql` | `3307` | `3306` | No, hardcoded in Compose | Host access to Compose MySQL without occupying host `3306`. |
| `backend` | `8000` | `8000` | No, hardcoded in Compose | FastAPI backend. |
| `frontend` | `3000` | `3000` | No, hardcoded in Compose | Frontend web app. |
| `nvflare` | `${DUALITY_NVFLARE_FED_PORT:-8002}` | `8002` | Yes, env fallback | NVFlare federation. |
| `nvflare` | `${DUALITY_NVFLARE_ADMIN_PORT:-8003}` | `8003` | Yes, env fallback | NVFlare admin. |
| `nvflare` | `8004` | `8004` | No, hardcoded in Compose | Optional NVFlare status/HTTP page. |

## Volume and Mount Table

| Service | Source | Target | Type | Purpose |
| --- | --- | --- | --- | --- |
| `mysql` | `mysql_data` | `/var/lib/mysql` | Named volume | Persistent MySQL data. |
| `mysql` | `../mysql_stage/init` | `/docker-entrypoint-initdb.d` | Bind mount | Optional first-start schema/seed SQL scripts. |
| `backend` | `../nvflare_workspace` | `/home/ubuntu/nvflare/workspace` | Bind mount | Shared NVFlare workspace. |
| `backend` | `../job-results` | `/job-results` | Bind mount | Shared job result files. |
| `nvflare` | `../nvflare_workspace` | `/home/ubuntu/nvflare/workspace` | Bind mount | Shared NVFlare workspace. |
| `nvflare` | `./local_wheels` | `/opt/duality/local_wheels` | Read-only bind mount | Optional local `duality_nvflare_lib-*.whl` installed at image build time. |
| `nvflare` | `../job-results` | `/trace-sink` | Bind mount | Profiler trace-sink target only, named by `DUALITY_TRACE_SINK_DIR`. |
| client containers | `${CLIENT_TAR}` | `/kits/client_startup_kit.tar` | Read-only bind mount | Per-site client startup kit tar. |
| client containers | `${JOB_RESULTS_DIR}` | `/job-results` | Bind mount | Site results directory, symlinked into the participant workspace at container start. |
| client containers | `./local_wheels` | `/opt/duality/local_wheels` | Read-only bind mount | Optional local `duality_nvflare_lib-*.whl` installed at container start. |
| client results agents | `${JOB_RESULTS_DIR}` | `/job-results` | Read-only bind mount | Read-only view of the same site results directory. |

## Container Builder Behavior

`docker_stage/container_builder.py` provides the `ContainerBuilder` class used by `main.py`.

### Initialization

`main.py` creates the builder with:

```python
ContainerBuilder(project_dir=REPO_ROOT / "docker_stage", env_file=<resolved env file>)
```

The builder:

- resolves the Compose file as `docker_stage/docker-compose.yml`
- uses Compose project name `duality`
- treats `frontend`, `backend`, `nvflare`, and `mysql` as known services
- resolves the standalone repo root as `standalone/`
- resolves the workspace root as the parent of `standalone/`, where `backend/` and `frontend/` are expected

### Docker and Compose Detection

Before Compose work, `_check_files()` calls `_ensure_docker_running()` and checks that the Compose file exists.

Docker validation:

1. Looks for `docker` or `docker-compose` on `PATH`.
2. Runs `docker info`.
3. Produces a specific permission-denied error if access to `/var/run/docker.sock` is denied.
4. Otherwise reports that the Docker daemon does not appear to be running.

Compose command selection:

1. Prefer `docker compose` when `docker` exists.
2. Fall back to `docker-compose` when `docker` is not found but `docker-compose` is found.
3. Add `-p duality`.
4. Add `--env-file <path>` when an env file is resolved.

### Source Verification

Backend and frontend are the only services with external source directories checked by `ContainerBuilder`.

Expected source directories:

| Service | Expected source path |
| --- | --- |
| `backend` | `<workspace-root>/backend` |
| `frontend` | `<workspace-root>/frontend` |

If a requested backend/frontend source directory is missing, the builder runs:

```text
python main.py codebase backend
python main.py codebase frontend
```

as needed. If the source directory still does not exist afterward, the operation fails.

### Frontend Env File Generation

When frontend is included in a build/rebuild/up operation, the builder writes:

```text
<workspace-root>/frontend/.env.production.local
```

with:

```text
REACT_APP_API_BASE=<resolved-api-base>
REACT_APP_BUILD_FLAVOR=<resolved-build-flavor>
```

The API base is resolved in this order:

1. `REACT_APP_API_BASE` from the env file
2. `NEXT_PUBLIC_BACKEND_URL` from the env file
3. process `REACT_APP_API_BASE`
4. process `NEXT_PUBLIC_BACKEND_URL`
5. `http://localhost:8000`

The build flavor is resolved from `REACT_APP_BUILD_FLAVOR` or defaults to `local`.

### Runtime Wheel Model

`ContainerBuilder` verifies Docker access, source folders, Compose files, frontend env output, and MySQL wipe behavior, then runs normal Compose build/restart commands.

The public standalone runtime always uses a local `duality_nvflare_lib` wheel. The bundled snapshot is staged into the local-wheel mounts before the NVFlare server/client starts; the job-bundled wrappers only verify/import the installed package:

| Container | Wheel source on the host | When it is installed |
| --- | --- | --- |
| `nvflare` | `standalone/docker_stage/local_wheels/` | Image **build** time (`pip install --no-deps`). |
| client containers | `standalone/client_utils/local_wheels/`, staged by `create_client.py` from `DUALITY_LOCAL_WHEEL_PATH` | Container **start**, which installs the newest matching wheel found on the mount. |

No per-job package-index upgrade occurs in the public runtime, so the installed snapshot cannot be silently replaced by a published wheel.

## Supported ContainerBuilder Actions

Even though the public `docker` subcommand is not registered, these actions exist in `cmd_docker()` and `ContainerBuilder`.

| Internal action | ContainerBuilder method | Behavior |
| --- | --- | --- |
| `build` | `build(services=None, no_cache=False)` | Runs Compose build for all or selected services. Writes frontend env when needed. |
| `up` | `up(services=None, detach=True, build=True)` | Runs Compose up, usually with `-d --build`. Writes frontend env when needed. |
| `down` | `down(remove_volumes=False)` | Runs Compose down. Adds `-v` when volume removal is requested. |
| `logs` | `logs(services=None, follow=False)` | Runs Compose logs. Adds `-f` when follow is requested. |
| `ps` | `ps()` | Runs Compose ps. |
| `pull` | `pull(services=None)` | Runs Compose pull for all or selected services. |
| `run` | `run_all(no_cache=False, clean_volumes=False)` | Runs reset, optional volume cleanup, frontend env write, build, then up. |
| reset helper | `reset(remove_volumes=False)` | Runs `docker compose down --remove-orphans`, optionally with `-v`. |
| MySQL wipe helper | `wipe_mysql_storage()` | Stops/removes the MySQL container and removes the named volume `duality_mysql_data`. |

All subprocess calls print their working directory and command before execution, then stream captured stdout/stderr back to the console.

## Default Startup Behavior and Existing Containers

When `python3 main.py` is run with no subcommand, `main.py` calls `_run_full_pipeline()`.

That flow:

1. Checks Docker access.
2. Detects whether any main project containers already exist.
3. Runs the MySQL stage. This is skipped by the MySQL stage when `DUALITY_DB_MODE=container`.
4. Runs the codebase stage.
5. If main project containers already exist:
   - rebuilds `mysql`, `backend`, `frontend`, and `nvflare`
   - optionally wipes MySQL if explicitly requested by the UI/default-flow path
   - redeploys already-running client containers
6. If no main project containers exist:
   - internally calls `cmd_docker()` with action `run`
   - `cmd_docker()` runs NVFlare provisioning first
   - `ContainerBuilder.run_all()` resets Compose resources without volumes, writes the frontend env file, builds the stack, and starts it

## Rebuild Behavior

The public rebuild command is:

```text
python3 main.py rebuild <service> [<service> ...] [--no-cache]
```

Supported rebuild service names:

| Service | Behavior |
| --- | --- |
| `frontend` | Verifies frontend source, writes frontend env file, rebuilds frontend image, removes old frontend container, starts frontend with `--no-deps`. |
| `backend` | Verifies backend source, rebuilds backend image, removes old backend container, starts backend with `--no-deps`. |
| `nvflare` | Rebuilds NVFlare image, removes old NVFlare container, starts NVFlare with `--no-deps`. The submitted job installs or updates `duality_nvflare_lib` at runtime. |
| `mysql` | Rebuilds MySQL image, removes old MySQL container, starts MySQL with `--no-deps`. Can optionally wipe the named MySQL volume first. |

Rebuild command sequence:

```text
docker compose -p duality --env-file <env> build [--no-cache] <services...>
docker compose -p duality --env-file <env> rm -f -s <services...>
docker compose -p duality --env-file <env> up -d --no-deps <services...>
```

The rebuild path intentionally uses `--no-deps` for the final `up`, so dependencies are not automatically restarted as part of a targeted service rebuild.

MySQL data is preserved by default. It is wiped only when:

- `DUALITY_DB_WIPE_ON_REBUILD` is true-like (`1`, `true`, or `yes`) and `mysql` is in the rebuild service list, or
- the UI explicitly passes a MySQL wipe option after prompting the user

Client containers are not part of the main rebuild command. The UI has separate options for creating/rebuilding a specified client or rebuilding already-running clients.

Examples:

```text
python3 main.py rebuild backend
python3 main.py rebuild frontend
python3 main.py rebuild nvflare
python3 main.py rebuild mysql
python3 main.py rebuild backend frontend --no-cache
```

## Update Behavior

The public update command is:

```text
python3 main.py update <service> [<service> ...] [--no-cache]
```

Supported update service names are only:

| Service | Source directory pulled |
| --- | --- |
| `frontend` | `<workspace-root>/frontend` |
| `backend` | `<workspace-root>/backend` |

Although `ContainerBuilder.update()` has logic that can skip non-source services, the public `argparse` choices only allow `frontend` and `backend`.

Update behavior:

1. Validate requested services.
2. For each requested source-backed service, run `git pull` in the expected source directory.
3. If `git pull` fails, print an error and return status `2`.
4. Write frontend env if frontend is included.
5. Run Compose build for the requested services.
6. Remove the old containers with `docker compose rm -f -s`.
7. Start the requested services with `docker compose up -d --no-deps`.

Examples:

```text
python3 main.py update backend
python3 main.py update frontend
python3 main.py update backend frontend --no-cache
```

## Runtime Wheel Behavior

The public standalone containers use the committed local snapshot wheel rather than a
package registry. Server and client startup install
`duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl` from their local-wheel mount
with dependency resolution disabled. The submitted job wrappers then verify/import that
installed package and never run an online upgrade.

This makes the wheel used by a public checkout deterministic: changing runtime logic
requires rebuilding/replacing the bundled snapshot and rebuilding/redeploying the
containers.

### Public Wheel Command

The public command is:

```text
python3 main.py wheel [--no-cache]
```

The command name is retained for the NVFlare runtime redeploy flow. It does not run a local wheel builder.

Behavior:

1. Resolve the env file and load it.
2. Check that the main `nvflare` container is running.
3. Check that at least one `duality-client-*` container is running.
4. Rebuild/relaunch the main `nvflare` service through `builder.rebuild(["nvflare"], no_cache=<flag>)`.
5. Redeploy each already-running client container.

The command intentionally requires already-running NVFlare and client containers. If NVFlare is not running, or if no client containers are running, it exits with status `2` and prints an error.

### Rebuilding the Runtime Wheel

The public snapshot ships a prebuilt wheel at `standalone/wheels/duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl`. After changing `apis/` or `workflows/`, rebuild it with the included wheel tooling:

```bash
python3 backend/app/core/job_runner/nvflare_jobs/wheels/APIWheelBuilderCI.py
```

The builder produces:

```text
duality_nvflare_lib-0+phase1.snapshot-py3-none-any.whl
```

Copy it over the bundled file under `standalone/wheels/` (or point `DUALITY_LOCAL_WHEEL_PATH` at it) and run `python3 main.py wheel` to redeploy it to the running NVFlare server and client containers. There is no package registry in the public snapshot; containers only ever install the wheel staged on their `local_wheels` mount.

## Client Container Builds

Client containers are separate from the main `docker_stage/docker-compose.yml` stack. They are created per site by:

```text
client_utils/create_client.py
```

The public entrypoint is:

```text
python3 main.py client --site <site>
python3 main.py client --tar-file <path-to-client_siteX_startup_kit.tar>
```

There is also a direct script parser inside `client_utils/create_client.py`; `main.py client ...` forwards arguments to that parser before the main parser handles other commands.

### Client Arguments

| Argument | Required | Purpose |
| --- | --- | --- |
| `--site <site>` | Mutually exclusive with `--tar-file` | Site name such as `site1`, `site2`, or `site3`. Used to locate a provisioned participant directory and create `dist/client_<site>_startup_kit.tar`. |
| `--tar-file <path>` | Mutually exclusive with `--site` | Existing client startup kit tar. Site name is inferred from filenames like `client_site2_startup_kit.tar`. |
| `--tar-kit` | Optional, only with `--site` | Only creates the client startup kit tar, optionally ensures the MySQL client entry, and exits. |
| `--compose-file <path>` | Optional | Compose template path. Defaults to `client_utils/docker-compose.client-template.yml`. |
| `--project <name>` | Optional | Compose project name for client resources. Defaults to `duality-client`. |
| `--env-file <path>` | Optional in direct script parser | Optional env file. Defaults to `standalone/.env.local` when present. |
| `--no-cache` | Optional | Build the selected client image, and the site's results-agent image when one applies, with `docker compose build --no-cache` before the `up`. |
| `--stop` | Optional, only with `--site` | Stop the site's NVFlare client container and any companion results-agent container, then exit without building. |

### Client Build Flow

For `python3 main.py client --site site1`, the flow is:

1. Ensure `.env.local` is seeded.
2. Load env values without overwriting already-set process env vars.
3. Check Docker access with `docker info`.
4. Resolve `DUALITY_NVFLARE_WORKSPACE`, defaulting to `standalone/nvflare_workspace` if not set.
5. Search that workspace recursively for a participant directory named exactly `site1`.
6. Create `standalone/dist/client_site1_startup_kit.tar` from that participant directory.
7. Collect datasource env values for the site.
8. Verify `client.Dockerfile` and the Compose template exist, plus `client-results-agent/Dockerfile` for non-initiator sites.
9. Ping backend `/user/role` to help initialize backend DB/table behavior.
10. Ensure the site is registered in MySQL.
11. Stage local datasource JSON files into `client_utils/injected_datasources/`.
12. Stage an optional local wheel into `client_utils/local_wheels/`.
13. Create the site results directory, `standalone/job-results/site1` for non-initiator sites and `standalone/job-results` for `site3`, and derive the site's results port.
14. Render a temporary per-site Compose file from `docker-compose.client-template.yml`.
15. Remove any existing containers named `duality-client-<site>` and `duality-client-results-<site>`.
16. Run, adding `results-agent-<site>` for non-initiator sites:

```text
docker compose -p duality-client -f <temporary-compose-file> up -d --build client-<site> [results-agent-<site>]
```

17. Delete generated build artifacts after Compose starts:

```text
client_utils/injected_datasources/
client_utils/docker-compose.client.<site>.<pid>.yml
```

`client_utils/local_wheels/` is not deleted by that cleanup. It is emptied of old `duality_nvflare_lib-*.whl` files and repopulated at the start of each build, and it stays in place because the client Compose service bind-mounts it.

### Client Compose Generation

The template defines two service keys, `client` and `results-agent`. Because Compose does not support environment-variable substitution in service keys, `create_client.py` renders a temporary file and rewrites both:

```yaml
services:
  client:
  ...
  results-agent:
```

to:

```yaml
services:
  client-<site>:
  ...
  results-agent-<site>:
```

If either rewrite fails, the script exits with status `14`. Per-site service names let several simulated sites share one Compose project.

The templates still set fixed container names:

```yaml
container_name: "duality-client-${SITE}"
container_name: "duality-client-results-${SITE}"
```

So the generated container names are predictable, for example:

```text
duality-client-site1
duality-client-results-site1
duality-client-site2
duality-client-results-site2
duality-client-site3
```

The `up` command lists `client-<site>` for every site and adds `results-agent-<site>` for every site except `site3`. `site3` is the initiator, and its results are already served by the backend through the existing `job-results` mount, so no companion results agent is started for it. For non-initiator sites, `create_client.py` also requires `client_utils/client-results-agent/Dockerfile` to exist and exits with status `12` when it is missing.

The client image is built from `client_utils/client.Dockerfile` with build context `client_utils/` and `platform: linux/amd64`.

### Client Compose Template

The generated client service uses these environment values inside the container:

| Variable | Value | Purpose |
| --- | --- | --- |
| `NVFLARE_VENV_DIR` | `/opt/nvflare/.venv` | Python venv location. |
| `NVFLARE_SERVER_BASE` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` | Workspace base inside the client container. |
| `DUALITY_NVFLARE_HOST` | `${SITE}` | Logical participant folder name for the client. |
| `NVFLARE_SERVER_TAR_PATH` | `/kits/client_startup_kit.tar` | Startup kit tar path inside the container. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `${CLIENT_JOB_SAVE_LOCATION}` | `/job-results` for every site. |
| `DUALITY_ENABLE_JOB_RESULTS_SYMLINK` | `${ENABLE_JOB_RESULTS_SYMLINK}` | `true` for every site, so the participant `job-results` folder is symlinked to `/job-results`. |
| `DUALITY_NVFLARE_LIB_UPDATE_DISABLED` | `${DUALITY_NVFLARE_LIB_UPDATE_DISABLED:-}` | Legacy/test passthrough; the public job runtime is always local-wheel-only. |
| `DUALITY_HOST_UID` | `${DUALITY_HOST_UID:-}` | Host user ID used to hand ownership of files written to the bind-mounted `/job-results` tree back to the host user. Blank is a no-op. |
| `DUALITY_HOST_GID` | `${DUALITY_HOST_GID:-}` | Host group ID paired with `DUALITY_HOST_UID`. Blank falls back to the UID value. |

See [Host File Ownership Variables](#host-file-ownership-variables) for how the values are produced and consumed.

Client volumes:

| Runtime env | Target | Purpose |
| --- | --- | --- |
| `${CLIENT_TAR}` | `/kits/client_startup_kit.tar:ro` | Startup kit tar mounted read-only. |
| `${JOB_RESULTS_DIR}` | `/job-results` | Site results directory on the host. |
| `./local_wheels` | `/opt/duality/local_wheels:ro` | Optional local `duality_nvflare_lib-*.whl` staged by `create_client.py`. The client start command installs the newest matching wheel from this mount at container start. |

### Client Results Agent Service

Every non-initiator site also runs a small FastAPI results agent so the browser can read that site's local results without going through the backend.

| Property | Value |
| --- | --- |
| Service key | `results-agent`, rendered as `results-agent-<site>` |
| Container name | `duality-client-results-${SITE}` |
| Build context | `./client-results-agent` with `Dockerfile` |
| Image | `python:3.11-slim` running `uvicorn app.main:app --host 0.0.0.0 --port 8088` |
| Restart policy | `unless-stopped` |

Results agent environment values:

| Variable | Value | Purpose |
| --- | --- | --- |
| `DUALITY_CLIENT_SITE` | `${SITE}` | Site name reported by the agent's `/health` response. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `/job-results` | In-container path the agent reads job results from. |
| `DUALITY_UI_ORIGINS` | `${DUALITY_UI_ORIGINS:-}` | Comma-separated extra CORS origins appended to the agent's built-in allow list. Blank adds nothing. |

Results agent volume and port:

| Compose entry | Purpose |
| --- | --- |
| `${JOB_RESULTS_DIR}:/job-results:ro` | Read-only view of the same site results directory the client writes. |
| `127.0.0.1:${CLIENT_RESULTS_PORT}:8088` | Publishes the agent on loopback only, so it is reachable from the browser on the same host but not from the network. |

The published port is derived per site by `get_site_results_port()`: `DUALITY_CLIENT_RESULTS_BASE_PORT` (default `8088`) plus the numeric part of the site name, so `site1` uses `8089` and `site2` uses `8090`. The helper raises when the site name is not `site<N>` or when the derived port falls outside `1`-`65535`. This matches the frontend's `getClientApiBase()` resolution for `CLIENT` sessions.

### Client Compose Network

The template declares its default network as pre-existing:

```yaml
networks:
  default:
    name: "${DUALITY_DOCKER_NETWORK:-duality_default}"
    external: true
```

Client containers therefore join the main stack's Compose network instead of creating their own, which is how they reach the `nvflare` and `backend` services by name. Because the network is declared `external`, the main `duality` project must already be up so that `duality_default` exists.

### Client Compose-Time Values

Compose-time environment values set by `create_client.py`:

| Compose-time env | Value |
| --- | --- |
| `SITE` | requested/inferred site name |
| `CLIENT_TAR` | resolved path to `dist/client_<site>_startup_kit.tar` or the provided tar file |
| `JOB_RESULTS_DIR` | `standalone/job-results` for `site3`; `standalone/job-results/<site>` for every other site, so simulated sites cannot overwrite each other's result files |
| `CLIENT_JOB_SAVE_LOCATION` | `/job-results` |
| `ENABLE_JOB_RESULTS_SYMLINK` | `true` |
| `CLIENT_RESULTS_PORT` | derived per site by `get_site_results_port()`; `8088` is substituted as a placeholder for `site3`, whose results-agent service is never started |
| `DUALITY_UI_ORIGINS` | passthrough of the host `DUALITY_UI_ORIGINS` value, or blank |
| `DUALITY_HOST_UID` | `str(os.getuid())` on POSIX hosts, applied with `setdefault` so an exported value wins |
| `DUALITY_HOST_GID` | `str(os.getgid())` on POSIX hosts, applied with `setdefault` so an exported value wins |

Compose interpolates the whole template even when only the client service is started, which is why `site3` still needs a valid `CLIENT_RESULTS_PORT` placeholder.

### Client Dockerfile

`client_utils/client.Dockerfile` builds from `ubuntu:24.04`, installs Python 3, venv/pip, shell/network tools, Git, CMake, Ninja, build essentials, OpenSSL development headers, and `libgomp1`, then builds/installs `liboqs` into `/usr/local`.

It copies these build-context artifacts:

| Build context source | Image target | Purpose |
| --- | --- | --- |
| `injected_datasources/` | `/data/client/` | Local JSON datasource files staged into the image. |

Client startup behavior:

1. Exports OQS/liboqs library paths.
2. Creates a Python virtual environment.
3. Installs/upgrades `pip`.
4. Installs the fixed runtime dependencies, then installs the newest `duality_nvflare_lib-*.whl` found on the `/opt/duality/local_wheels` mount when one is present.
5. Clears and recreates the workspace base.
6. Extracts the mounted startup kit tar into the workspace base.
7. Makes startup scripts executable and normalizes Windows CRLF line endings.
8. If `DUALITY_ENABLE_JOB_RESULTS_SYMLINK=true`, symlinks the site workspace `job-results` path to `/job-results`.
9. Runs the site's `startup/start.sh`.
10. Keeps the container alive with `tail -f /dev/null`.

The startup command currently runs `./start.sh || true`, so the container can remain alive even if NVFlare client startup returns non-zero.

## Client Datasource Staging

Datasource values are collected from env vars using these patterns:

```text
DUALITY_CLIENT_<SITE>_DATASOURCE
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>_<DATASOURCE_GROUP_ID>
```

Examples from `default.env.local`:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part2.json
DUALITY_CLIENT_SITE1_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json
```

Remote datasource detection:

- `http` or `https` URLs with a network location are treated as remote datasource URLs unless the URL path ends with `.json`.
- Remote FHIR URLs are returned from backend user datasource settings at runtime.
- Local paths are resolved relative to `standalone/` when not absolute.
- Local `.json` values can be backed by a same-name `.zip`; if the JSON file is missing and a zip with the same stem exists, the helper tries to extract the JSON.

Grouped and ungrouped datasource entries cannot be mixed for the same site/project. The script exits with status `18` if it detects a mix such as `DUALITY_CLIENT_SITE1_DATASOURCE_2` and `DUALITY_CLIENT_SITE1_DATASOURCE_2_1` for the same project.

Generated config example:

```json
{
  "projects": {
    "1": "/data/client/Survivability_FHIR_Data_part2.json",
    "2": {
      "1": "/data/client/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json"
    }
  }
}
```

Local JSON datasource files are copied into `client_utils/injected_datasources/` before the client image build and then copied into `/data/client/` by the client Dockerfile. Remote FHIR URLs are not copied; they are passed through in the generated JSON config.

The user-provided standalone package may omit raw local test data files. That omission is acceptable for documentation because `create_client.py` validates and stages those files only when the corresponding env values point to local JSON files.

## Client MySQL Registration

The client creation flow ensures each client exists in MySQL before container creation. The separate public command is:

```text
python3 main.py clientdb --site <site>
```

Registration behavior:

| Site | Username behavior |
| --- | --- |
| `site3` | Uses existing user `initiator`; fails if that user does not exist. |
| all other sites | Ensures role `client`, ensures user `client_<site>` with password hash `DISABLED`, and maps `nvflare_clients.client_name` to that user. |

Tables touched by the registration helper:

- `defined_roles`
- `users`
- `nvflare_clients`

The helper uses `ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)` patterns so existing records are reused and their IDs are returned.

Database connection values are read from environment:

| Variable | Default |
| --- | --- |
| `DUALITY_MYSQL_HOST` | `localhost` |
| `DUALITY_MYSQL_PORT` | `3306` |
| `DUALITY_MYSQL_USER` | `root` |
| `DUALITY_MYSQL_PASSWORD` | empty string |
| `DUALITY_MYSQL_DB` | `duality_dev` |

`create_client.py` uses `utils/mysql_driver_utils.ensure_mysql_driver()` and supports either `mysql.connector` or a PyMySQL-style driver returned by that helper.

## UI Dashboard Docker Operations

The public UI command is:

```text
python3 main.py ui
```

The interactive menu displays:

```text
[1] Reset & rebuild all
[2] Rebuild backend
[3] Rebuild frontend
[4] Rebuild nvflare
[5] Rebuild mysql
[6] Create/Rebuild USER SPECIFIED client container (includes persist to MySQL)
[7] Persist USER SPECIFIED client to MySQL
[8] Rebuild ALREADY RUNNING client containers
[9] Redeploy ALREADY RUNNING NVFlare Server/Client
[r] Refresh
[q] Quit
```

Important UI behavior:

- Full reset/rebuild checks whether main project containers already exist.
- When containers already exist, the UI prompts before wiping MySQL data because wiping data requires re-adding clients.
- After a successful full reset/rebuild, the UI seeds the default clients by poking the backend and then prints the registered client names, or warns when the backend is not reachable yet.
- Backend, frontend, NVFlare, and MySQL rebuild options call `builder.rebuild()` for the selected service.
- MySQL rebuild prompts separately for data wipe.
- User-specified client rebuild prompts for a site name, then runs the client creation flow. Pressing Enter without a site name launches every client registered in MySQL instead.
- Running client rebuild detects currently running containers named `duality-client-*` and recreates each detected site.
- Option `9` calls the public `wheel` command flow, rebuilding/relaunching NVFlare and redeploying already-running clients.
- Docker access problems are surfaced before rebuild actions.

## Safe Reset Procedures

### Restart/Rebuild Without Deleting MySQL Data

Use this when containers or images need to be refreshed but the database should remain intact:

```text
python3 main.py rebuild backend frontend nvflare
```

or use UI option `1` and answer `N` to the MySQL wipe prompt if prompted.

This preserves the `duality_mysql_data` volume.

### Rebuild MySQL Without Wiping Data

```text
python3 main.py rebuild mysql
```

This rebuilds the image and recreates the MySQL container, but preserves `duality_mysql_data` unless `DUALITY_DB_WIPE_ON_REBUILD` is set to a true-like value.

### Wipe MySQL Data Through the UI

Use:

```text
python3 main.py ui
```

Then choose option `5` for MySQL rebuild or option `1` for full reset/rebuild and answer `y` to the data wipe prompt.

After wiping MySQL data, clients must be re-added through:

```text
python3 main.py clientdb --site site1
python3 main.py clientdb --site site2
python3 main.py clientdb --site site3
```

or by recreating the client containers with `python3 main.py client --site <site>`.

### Manual Compose Reset Without Volume Deletion

From `standalone/docker_stage`:

```text
docker compose -p duality --env-file ../.env.local down --remove-orphans
```

### Manual Compose Reset With Volume Deletion

From `standalone/docker_stage`:

```text
docker compose -p duality --env-file ../.env.local down --remove-orphans -v
```

This removes the Compose named volume and deletes MySQL data. Do not use this unless a clean database reset is intended.

### Manual Client Container Removal

Client containers are named by site:

```text
docker rm -f duality-client-site1
docker rm -f duality-client-site2
docker rm -f duality-client-site3
```

Recreate them with:

```text
python3 main.py client --site site1
python3 main.py client --site site2
python3 main.py client --site site3
```

## Practical Command Examples

| Goal | Command |
| --- | --- |
| Start or refresh the full standalone stack | `python3 main.py` |
| Open the local operations dashboard | `python3 main.py ui` |
| Rebuild backend only | `python3 main.py rebuild backend` |
| Rebuild frontend only | `python3 main.py rebuild frontend` |
| Rebuild NVFlare server only | `python3 main.py rebuild nvflare` |
| Rebuild MySQL container without wiping data | `python3 main.py rebuild mysql` |
| Rebuild backend and frontend without cache | `python3 main.py rebuild backend frontend --no-cache` |
| Pull backend source and rebuild backend | `python3 main.py update backend` |
| Pull frontend source and rebuild frontend | `python3 main.py update frontend` |
| Redeploy running NVFlare/client containers | `python3 main.py wheel` |
| Create/rebuild site1 client | `python3 main.py client --site site1` |
| Create only a site1 startup kit tar | `python3 main.py client --site site1 --tar-kit` |
| Register site1 in MySQL only | `python3 main.py clientdb --site site1` |
