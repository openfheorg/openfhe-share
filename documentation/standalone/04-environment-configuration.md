# Environment Configuration

## Current Datasource Runtime Model

Standalone client utilities use datasource environment values as host-side staging paths for local JSON files. Those files are copied into client containers under `/data/client/`. The running client does not use retired `DUALITY_FHIR_BASE_CONFIG.json` or retired `DUALITY_NVFLARE_FHIR_BASE_CONFIG`; it requests its datasource from the NVFlare server, which resolves the value through backend user settings.

See `09-local-datasource-staging-and-runtime-lookup.md` for the full current flow.

## Files Covered

| File | Role |
| --- | --- |
| `default.env.local` | Default environment template used to create `.env.local` when the active local env file is reset or missing. |
| `.env.local` | Active standalone environment file used by local orchestration, Docker Compose, NVFlare provisioning, MySQL checks, and client creation. |
| `utils/environment_utils.py` | Minimal environment loader used by `main.py`. |
| `utils/ip_utils.py` | Local IPv4 detection helper used when `DUALITY_NVFLARE_HOST` is `auto` or blank during `.env.local` seeding. |
| `main.py` | Seeds `.env.local`, resolves host values, loads environment values, and passes configuration into orchestration stages. |
| `docker_stage/docker-compose.yml` | Main Docker Compose stack for MySQL, backend, frontend, and NVFlare. |
| `docker_stage/container_builder.py` | Docker Compose wrapper that reads selected env values, writes frontend build env, controls MySQL wipe behavior, and rebuilds/restarts selected services. |
| `client_utils/create_client.py` | Reads per-site datasource environment values, stages local JSON data, registers client records, and starts per-site client containers. |
| `client_utils/docker-compose.client-template.yml` | Template Compose file rendered into a per-site client Compose file at runtime. |
| `mysql_stage/mysql_check_or_install.py` | Host MySQL check/install stage used only when `DUALITY_DB_MODE=host`. |
| `nvflare_stage/nvflare_install_and_provision.py` | NVFlare install/provisioning stage that reads NVFlare env values and writes `DUALITY_ADMIN_TAR` back to `.env.local`. |

## Environment File Flow

The standalone runtime uses `.env.local` as the active machine-specific environment file.

`default.env.local` is the baseline template. It is checked in so a developer can restore or regenerate local configuration without manually recreating every variable.

At startup, `main.py` calls `_ensure_env_local_seed()`. The current implementation copies `default.env.local` to `.env.local` every time `main.py` runs, then resolves selected defaults such as `DUALITY_NVFLARE_HOST` and `DUALITY_DB_MODE`. This means local edits in `.env.local` can be overwritten by the template unless the template is also updated or the command path bypasses the orchestrator seeding behavior.

After seeding, `main.py` resolves the env file path through `_resolve_env_file()`:

| Case | Behavior |
| --- | --- |
| `--env-file <path>` provided | Use the provided env file path. |
| No `--env-file`, `.env.local` exists | Use `<standalone>/.env.local`. |
| No `--env-file`, `.env.local` missing | Return `None` until seeding recreates `.env.local`. |

`main.py` then loads the env file through `utils.environment_utils.load_env_file()`. The loader reads simple `KEY=VALUE` lines, skips blank lines and comments, and uses `os.environ.setdefault()`. Existing process-level environment variables therefore win over values in the file.

Several stage scripts have their own local env loaders. They follow the same general rule: parse simple `KEY=VALUE` lines, skip comments/blanks, and do not overwrite already-set environment variables.

## Host Resolution

`DUALITY_NVFLARE_HOST` can be configured as:

| Value | Behavior |
| --- | --- |
| Explicit host/IP | Used as configured. |
| `auto` | Replaced in `.env.local` with the detected local IPv4 address during seeding. |
| blank | Replaced in `.env.local` with the detected local IPv4 address during seeding. |

`utils/ip_utils.py` detects the host in this order:

1. Open a UDP socket to `8.8.8.8:80` and read the local socket address.
2. Open a UDP socket to `1.1.1.1:80` and read the local socket address.
3. On Linux-like systems, run `ip route get 8.8.8.8` and parse the `src` address.
4. On macOS, run `ipconfig getifaddr en0`, then `ipconfig getifaddr en1`.
5. Use `socket.gethostbyname(socket.gethostname())`.
6. Fall back to `127.0.0.1`.

The helper accepts IPv4 values only when they match an IPv4 pattern, all octets are in range, and the value is not `0.0.0.0` or `127.0.0.1`. The final fallback can still return `127.0.0.1` when no better address is found.

This host value matters because NVFlare provisioning rewrites the local project file with that host as the server participant name and endpoint. The NVFlare server and client containers use the generated startup kits and must agree on the host/participant names and ports.

## Default Environment Variable Table

The following variables are defined in `default.env.local`.

| Variable | Default value | Used by | Purpose |
| --- | --- | --- | --- |
| `DUALITY_DB_MODE` | `container` | `main.py`, MySQL stage logic, status UI | Selects container MySQL or host MySQL mode. |
| `DUALITY_MYSQL_HOST` | `localhost` | MySQL stage, status UI, client DB registration; Compose remaps backend to `mysql` inside backend container | Host used for local/orchestration-side MySQL connections. |
| `DUALITY_MYSQL_PORT` | `3307` | MySQL stage, status UI, client DB registration; Compose remaps backend to `3306` inside backend container | Host port used when connecting to Compose MySQL from the host. |
| `DUALITY_MYSQL_USER` | `duality` | MySQL stage, Compose MySQL/backend, client DB registration, status UI | Application database user. |
| `DUALITY_MYSQL_PASSWORD` | `duality_pass` | MySQL stage, Compose MySQL/backend, client DB registration, status UI | Application database password. |
| `DUALITY_MYSQL_DB` | `duality_dev` | MySQL stage, Compose MySQL/backend, client DB registration, status UI | Application database/schema name. |
| `MYSQL_ROOT_PASSWORD` | `rootpass` | Compose MySQL service | Root password passed to the MySQL container entrypoint. |
| `DUALITY_NVFLARE_HOST` | `auto` | `main.py`, NVFlare provisioning, Compose backend/nvflare, status UI | Local NVFlare server host/participant name. Auto-resolved to local IPv4 by `main.py`. |
| `DUALITY_NVFLARE_FED_PORT` | `8002` | NVFlare provisioning, Compose backend/nvflare | NVFlare federated learning port. |
| `DUALITY_NVFLARE_ADMIN_PORT` | `8003` | NVFlare provisioning, Compose backend/nvflare | NVFlare admin port. |
| `DUALITY_NVFLARE_PROJECT_FILE` | `project.yml` | NVFlare provisioning | Source NVFlare project YAML file to rewrite/provision. |
| `DUALITY_NVFLARE_WORKSPACE` | `./nvflare_workspace` | NVFlare provisioning, main status UI, client creation, Compose volume mounts | Local NVFlare workspace root. |
| `DUALITY_NVFLARE_ADMIN_NAME` | `admin@share.local` | NVFlare provisioning, Compose backend | Admin participant name used to locate and tar the admin startup kit. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `./job-results` | Compose backend, local job result convention | Host-side job results location. Backend container receives `/job-results`. |
| `DUALITY_DB_WIPE_ON_REBUILD` | `false` | `ContainerBuilder.rebuild()` | Enables MySQL volume wipe during MySQL rebuild when set to `1`, `true`, or `yes`. |
| `DUALITY_CLIENT_SITE3_DATASOURCE_1` | `nvflare_stage/data/Survivability_FHIR_Data_part1.json` | Client creation | Site 3 datasource for project `1` (General Statistics). |
| `DUALITY_CLIENT_SITE1_DATASOURCE_1` | `nvflare_stage/data/Survivability_FHIR_Data_part2.json` | Client creation | Site 1 datasource for project `1` (General Statistics). |
| `DUALITY_CLIENT_SITE2_DATASOURCE_1` | `nvflare_stage/data/Survivability_FHIR_Data_part3.json` | Client creation | Site 2 datasource for project `1` (General Statistics). |
| `DUALITY_CLIENT_SITE3_DATASOURCE_2_1` | `nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_training_bundle.json` | Client creation | Site 3 datasource for project `2`, group `1` (MSKChord). |
| `DUALITY_CLIENT_SITE1_DATASOURCE_2_1` | `nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json` | Client creation | Site 1 datasource for project `2`, group `1` (MSKChord). |
| `DUALITY_CLIENT_SITE2_DATASOURCE_2_1` | `nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json` | Client creation | Site 2 datasource for project `2`, group `1` (MSKChord). |

The uploaded `.env.local` in the current standalone archive has the same structure, but includes machine-specific values such as `DUALITY_NVFLARE_HOST=192.168.0.29` and `DUALITY_MYSQL_DB=duality_local`.

## Additional Environment Variables Read by Code

These variables are read by code even though they are not all present in `default.env.local`.

| Variable | Default/fallback | Used by | Purpose |
| --- | --- | --- | --- |
| `DUALITY_ADMIN_TAR` | Written as `<standalone>/dist/admin_startup_kit.tar` | NVFlare provisioning writes it; backend Compose also sets `DUALITY_ADMIN_TAR=/kits/admin_startup_kit.tar` inside container | Records the generated admin startup kit tar path after provisioning. |
| `DUALITY_NVF_WSL_TIMEOUT_SECS` | `900` | NVFlare provisioning | Timeout for Windows WSL provisioning command. Read at module import time. |
| `DUALITY_NVF_LOCAL_TIMEOUT_SECS` | `600` | NVFlare provisioning | Timeout for local non-Windows provisioning attempts. Read at module import time. |
| `REACT_APP_API_BASE` | `http://localhost:8000` | `ContainerBuilder._write_frontend_env()` | Preferred frontend API base when writing `../frontend/.env.production.local`. |
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` | `ContainerBuilder._write_frontend_env()`, Compose frontend | Backend URL for frontend build/runtime. Used as fallback for `REACT_APP_API_BASE`; Compose sets it to `http://localhost:8000`. |
| `REACT_APP_BUILD_FLAVOR` | `local` | `ContainerBuilder._write_frontend_env()` | Frontend build flavor written to `../frontend/.env.production.local`. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE` | none | Client creation | Legacy/simple per-site datasource override. If set, maps project `1` to that datasource. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT>` | none | Client creation | Ungrouped datasource for a specific site and project. Example: `DUALITY_CLIENT_SITE1_DATASOURCE_1`. |
| `DUALITY_BACKEND_URL` | `http://localhost:8000` | Client creation | URL used by `ping_backend_login()` to call `/user/role` before client registration. |
| `PYTHON_BIN` | launcher-specific Python discovery | Launcher scripts | Optional override for the Python executable used by launcher scripts. |
| `DOCKER_DEFAULT_PLATFORM` | `linux/amd64` for client creation | Client creation | Forces client image build platform unless the caller overrides the environment. |
| `DOCKER_BUILDKIT` | `1` for client creation | Client creation | Enables BuildKit for client image build unless the caller overrides the environment. |

## Database Mode

The standalone supports database mode selection through `DUALITY_DB_MODE`.

| Value | Behavior |
| --- | --- |
| `container` | Default mode. `main.py mysql` skips host MySQL checks. The main Compose stack starts the `mysql` service. Host-side tools connect through `localhost:3307`; backend container connects to Compose service `mysql:3306`. |
| `host` | `main.py mysql` runs `mysql_stage/mysql_check_or_install.py`. The script checks TCP reachability and authentication using `DUALITY_MYSQL_HOST`, `DUALITY_MYSQL_PORT`, `DUALITY_MYSQL_USER`, and `DUALITY_MYSQL_PASSWORD`. If the port is not reachable, it attempts platform-specific installation on macOS or Windows. |

The Compose MySQL service maps container port `3306` to host port `3307`:

```text
3307:3306
```

The backend container does not use `DUALITY_MYSQL_HOST=localhost` from `.env.local`. Compose overrides the backend environment so the container connects to:

```text
DUALITY_MYSQL_HOST=mysql
DUALITY_MYSQL_PORT=3306
```

Client registration runs from the host-side Python process, so it uses the host-facing MySQL settings from `.env.local`, normally `localhost:3307` for container mode.

## Docker Compose Environment Use

`docker_stage/docker-compose.yml` uses `env_file: ../.env.local` for all four main services, then overrides or maps selected values inside each service.

### `mysql` Service

| Compose setting | Source | Container value / behavior |
| --- | --- | --- |
| `MYSQL_DATABASE` | `${DUALITY_MYSQL_DB:-duality_local}` | Initializes the application database. |
| `MYSQL_USER` | `${DUALITY_MYSQL_USER:-duality}` | Initializes the application user. |
| `MYSQL_PASSWORD` | `${DUALITY_MYSQL_PASSWORD:-dualitypass}` | Initializes the application user password. |
| `MYSQL_ROOT_PASSWORD` | `${MYSQL_ROOT_PASSWORD:-rootpass}` | Initializes root password. |
| Port mapping | hardcoded | Host `3307` to container `3306`. |
| Volume | `mysql_data` | Persists MySQL files at `/var/lib/mysql`. |
| Init mount | `../mysql_stage/init:/docker-entrypoint-initdb.d` | Runs optional initialization SQL files on first startup. |

### `backend` Service

| Compose setting | Source | Container value / behavior |
| --- | --- | --- |
| `SHARE_ENV` | hardcoded | `local`. |
| `DUALITY_MYSQL_HOST` | hardcoded | `mysql`, the Compose service name. |
| `DUALITY_MYSQL_PORT` | hardcoded | `3306`, the container port. |
| `DUALITY_MYSQL_USER` | `${DUALITY_MYSQL_USER:-duality}` | Backend database user. |
| `DUALITY_MYSQL_PASSWORD` | `${DUALITY_MYSQL_PASSWORD:-dualitypass}` | Backend database password. |
| `DUALITY_MYSQL_DB` | `${DUALITY_MYSQL_DB:-duality_local}` | Backend database/schema. |
| `DUALITY_NVFLARE_HOST` | `${DUALITY_NVFLARE_HOST}` | NVFlare host/participant value. |
| `DUALITY_NVFLARE_FED_PORT` | `${DUALITY_NVFLARE_FED_PORT}` | NVFlare federated learning port. |
| `DUALITY_NVFLARE_ADMIN_PORT` | `${DUALITY_NVFLARE_ADMIN_PORT}` | NVFlare admin port. |
| `DUALITY_NVFLARE_WORKSPACE` | hardcoded | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00`. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | hardcoded | `/job-results`. |
| `DUALITY_NVFLARE_SUBMITTED_JOBS_LOCATION` | composed from host and workspace | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/${DUALITY_NVFLARE_HOST}/submitted_jobs`. |
| `DUALITY_NVFLARE_ADMIN_NAME` | `${DUALITY_NVFLARE_ADMIN_NAME}` | Admin participant name. |
| `DUALITY_ADMIN_TAR` | hardcoded | `/kits/admin_startup_kit.tar`. |
| `DUALITY_HOST_UID` | `${DUALITY_HOST_UID:-}` | Host user ID used when handing ownership of bind-mount output back to the host user. Blank is a no-op. |
| `DUALITY_HOST_GID` | `${DUALITY_HOST_GID:-}` | Host group ID paired with `DUALITY_HOST_UID`. Blank falls back to the UID value. |
| Workspace mount | `../nvflare_workspace` | Mounted at `/home/ubuntu/nvflare/workspace`. |
| Job results mount | `../job-results` | Mounted at `/job-results`. |
| Port mapping | hardcoded | Host `8000` to container `8000`. |

### `frontend` Service

| Compose setting | Source | Container value / behavior |
| --- | --- | --- |
| `NEXT_PUBLIC_BACKEND_URL` | hardcoded in Compose | `http://localhost:8000`. |
| Port mapping | hardcoded | Host `3000` to container `3000`. |
| `env_file` | `../.env.local` | General env values are loaded, but Compose explicitly sets `NEXT_PUBLIC_BACKEND_URL`. |

`ContainerBuilder._write_frontend_env()` also writes a file into the sibling frontend source tree:

```text
../frontend/.env.production.local
```

The generated file contains:

```text
REACT_APP_API_BASE=<REACT_APP_API_BASE or NEXT_PUBLIC_BACKEND_URL or http://localhost:8000>
REACT_APP_BUILD_FLAVOR=<REACT_APP_BUILD_FLAVOR or local>
```

### `nvflare` Service

| Compose setting | Source | Container value / behavior |
| --- | --- | --- |
| `DUALITY_NVFLARE_HOST` | `${DUALITY_NVFLARE_HOST}` | NVFlare host/participant value. |
| `NVFLARE_SERVER_BASE` | hardcoded | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00`. |
| `DUALITY_BACKEND_URL` | hardcoded | `http://backend:8000`. |
| `DUALITY_TRACE_SINK_DIR` | hardcoded | `/trace-sink`. The job profiler copies the server trace to `<sink>/traces/<job-id>/<site>/trace.jsonl` for the backend report generator. Code falls back to `/job-results` when unset. |
| `DUALITY_HOST_UID` | `${DUALITY_HOST_UID:-}` | Host user ID used when handing ownership of bind-mount output back to the host user. Blank is a no-op. |
| `DUALITY_HOST_GID` | `${DUALITY_HOST_GID:-}` | Host group ID paired with `DUALITY_HOST_UID`. Blank falls back to the UID value. |
| Workspace mount | `../nvflare_workspace` | Mounted at `/home/ubuntu/nvflare/workspace`. |
| Trace sink mount | `../job-results` | Mounted at `/trace-sink`, used only as the profiler trace-sink target. |
| Fed port mapping | `${DUALITY_NVFLARE_FED_PORT:-8002}:8002` | Host to container NVFlare fed port. |
| Admin port mapping | `${DUALITY_NVFLARE_ADMIN_PORT:-8003}:8003` | Host to container NVFlare admin port. |
| Status port mapping | hardcoded | Host `8004` to container `8004`. |

## Variables Read by `main.py`

| Variable | Used in | Behavior |
| --- | --- | --- |
| `DUALITY_DB_MODE` | `cmd_mysql()`, `_gather_status()` | `container` skips host MySQL setup and treats missing MySQL container as status failure; `host` runs host MySQL checks. |
| `DUALITY_NVFLARE_HOST` | `_ensure_env_local_seed()` | If `auto` or blank after template copy, replaced with detected local IPv4. |
| `DUALITY_MYSQL_HOST` | `_probe_mysql()`, `_gather_status()` | Displayed in UI and used for status DB connection. |
| `DUALITY_MYSQL_PORT` | `_probe_mysql()`, `_gather_status()` | Displayed in UI and parsed for status DB connection. |
| `DUALITY_MYSQL_USER` | `_probe_mysql()`, `_gather_status()` | Displayed in UI and used for status DB connection. |
| `DUALITY_MYSQL_PASSWORD` | `_probe_mysql()` | Used for status DB connection. |
| `DUALITY_MYSQL_DB` | `_probe_mysql()`, `_gather_status()` | Displayed in UI and used for status DB connection. |
| `DUALITY_NVFLARE_WORKSPACE` | `_nvflare_status()` | Determines displayed workspace and checks whether `<workspace>/duality_nvflare/prod_00` exists. |
| `DUALITY_HOST_UID` | `main()` | Seeded with `os.environ.setdefault("DUALITY_HOST_UID", str(os.getuid()))` after the env file is loaded, on hosts that expose `os.getuid`. An already-exported value is preserved. |
| `DUALITY_HOST_GID` | `main()` | Seeded the same way from `os.getgid()`. Compose passes both into the backend and NVFlare containers. |

`main.py` uses `.env.local` before running the default pipeline, explicit subcommands, UI, client creation, client DB registration, and wheel rebuild. It passes the resolved env file path to `ContainerBuilder` so Docker Compose receives the same file through `--env-file`.

## Variables Read by `client_utils/create_client.py`

| Variable/pattern | Behavior |
| --- | --- |
| `DUALITY_NVFLARE_WORKSPACE` | Finds the provisioned participant directory for a requested site. Defaults to `<standalone>/nvflare_workspace`. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT>` | Defines an ungrouped datasource for a project. Example: `DUALITY_CLIENT_SITE1_DATASOURCE_1`. |
| `DUALITY_CLIENT_<SITE>_DATASOURCE` | Legacy/simple override. If present and no structured matches exist, maps project `1` to that datasource. |
| `DUALITY_MYSQL_HOST` | Host for client DB registration. Defaults to `localhost`. |
| `DUALITY_MYSQL_PORT` | Port for client DB registration. Defaults to `3306`. |
| `DUALITY_MYSQL_USER` | User for client DB registration. Defaults to `root`. |
| `DUALITY_MYSQL_PASSWORD` | Password for client DB registration. Defaults to blank. |
| `DUALITY_MYSQL_DB` | Database for client DB registration. Defaults to `duality_dev`. |
| `DUALITY_BACKEND_URL` | Base URL for `/user/role` preflight call. Defaults to `http://localhost:8000`. |
| `DOCKER_DEFAULT_PLATFORM` | Client creation sets `linux/amd64` in the subprocess environment. |
| `DOCKER_BUILDKIT` | Client creation sets `1` in the subprocess environment. |
| `DUALITY_CLIENT_RESULTS_BASE_PORT` | Base port for the per-site results agent. Defaults to `8088`; the published port is this value plus the site number. |
| `DUALITY_UI_ORIGINS` | Passed through to the results agent as extra CORS origins. Defaults to blank. |
| `DUALITY_DOCKER_NETWORK` | Name of the pre-existing Docker network the client services join. Defaults to `duality_default`. |
| `DUALITY_LOCAL_WHEEL_PATH` | Optional path to a `duality_nvflare_lib-*.whl` staged into `client_utils/local_wheels/` before the client build. Exits with status `20` when the path is missing or is not a `duality_nvflare_lib` wheel. |
| `DUALITY_HOST_UID` | Client creation sets `str(os.getuid())` in the subprocess environment with `setdefault`, on hosts that expose `os.getuid`. Passed into the client container so it can hand ownership of files written to `/job-results` back to the host user. |
| `DUALITY_HOST_GID` | Client creation sets `str(os.getgid())` in the subprocess environment with `setdefault`, on hosts that expose `os.getuid`. Used with `DUALITY_HOST_UID`. |

The client creation flow rejects mixed grouped and ungrouped datasource configuration for the same site/project. For example, do not set both:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_2=...
```

for the same site and project.

## Client Datasource Staging Variables

Datasource env variable names are tied to the site name passed through `main.py client --site <site>` or the UI.

For a site named `site1`, the prefix is:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_
```

For a custom site named `harvardA`, the prefix would be:

```text
DUALITY_CLIENT_HARVARDA_DATASOURCE_
```

The suffix controls the project and optional datasource group:

| Pattern | Meaning |
| --- | --- |
| `DUALITY_CLIENT_SITE1_DATASOURCE_1=<value>` | Site 1, project `1`, ungrouped/default datasource staging value. |
| `DUALITY_CLIENT_SITE1_DATASOURCE_2_1=<value>` | Site 1, project `2`, datasource group `1` staging value. |
| `DUALITY_CLIENT_SITE1_DATASOURCE=<value>` | Legacy override for site 1, project `1`, used only when no structured datasource keys are found. |

Client creation sorts datasource keys by numeric project ID, numeric group ID, and raw suffix.

Local JSON datasource values are host-side source paths. They are resolved to host paths, staged into:

```text
client_utils/injected_datasources/
```

and copied into the client image under:

```text
/data/client/<filename>.json
```

If the requested `.json` file is missing but a `.zip` file with the same base name exists, `create_client.py` attempts to unzip it and locate the JSON. This allows large test data JSON files to be omitted from the working tree and supplied as zip archives when needed.

Remote FHIR datasource values are not copied into the Docker build context. They are stored in backend user datasource settings and returned to clients at job runtime.

After Docker starts the client, the injected datasource directory and temporary per-site compose file are deleted from `client_utils`.

The client command does not generate or copy `DUALITY_FHIR_BASE_CONFIG.json`, and the client container does not need `DUALITY_NVFLARE_FHIR_BASE_CONFIG`. Runtime datasource lookup uses the NVFlare server and backend `/clients/datasource/source` endpoint.

## Client/Site Naming

A CLI site argument maps to multiple artifacts.

| Input/site | Derived value |
| --- | --- |
| `--site site1` | Looks for a provisioned participant directory named `site1` under `DUALITY_NVFLARE_WORKSPACE`. |
| `site1` | Uses env prefix `DUALITY_CLIENT_SITE1_DATASOURCE_`. |
| `site1` | Creates `dist/client_site1_startup_kit.tar`. |
| `site1` | Renders a temporary Compose service named `client-site1`. |
| `site1` | Uses client container name `duality-client-site1`. |
| `site1` | Registers `nvflare_clients.client_name='site1'`. |
| `site1` | Creates/uses user `client_site1`. |
| `site3` | Registers client mapping to existing user `initiator`. |

The client Compose project defaults to:

```text
duality-client
```

This is separate from the main Compose project, which defaults to:

```text
duality
```

The runtime client Compose file is generated from `client_utils/docker-compose.client-template.yml` by replacing the service key `client:` with `client-<site>:`. This is done because Compose does not support environment variable substitution in service keys.

## Variables Read by MySQL Stage Scripts

`mysql_stage/mysql_check_or_install.py` is used only when `DUALITY_DB_MODE=host`.

| Variable | Default | Behavior |
| --- | --- | --- |
| `DUALITY_MYSQL_HOST` | `localhost` | Host checked for TCP and auth. If `localhost`, auth also tries `127.0.0.1`. |
| `DUALITY_MYSQL_PORT` | `3306` | Port checked for TCP and auth. |
| `DUALITY_MYSQL_USER` | blank | User used for auth check. |
| `DUALITY_MYSQL_PASSWORD` | blank | Password used for auth check. |

The host MySQL script loads `.env.local` from the standalone repo root by default. It attempts to install Python MySQL dependencies (`mysqlclient`, `PyMySQL`) before auth checks. If MySQL is unreachable, it attempts MySQL installation through Homebrew on macOS or Chocolatey on Windows. Linux host installation is not implemented in this script.

## Variables Read by NVFlare Provisioning Scripts

`nvflare_stage/nvflare_install_and_provision.py` reads `.env.local` and provisions only when the expected workspace root does not already exist.

| Variable | Default | Behavior |
| --- | --- | --- |
| `DUALITY_NVFLARE_HOST` | blank | Used to rewrite server participant name and `sp_end_point` in `project.local.yml`. |
| `DUALITY_NVFLARE_FED_PORT` | `8002` | Used to rewrite `fed_learn_port`. |
| `DUALITY_NVFLARE_ADMIN_PORT` | `8003` | Used to rewrite `admin_port`. |
| `DUALITY_NVFLARE_PROJECT_FILE` | `project.yml` | Source project file to rewrite. |
| `DUALITY_NVFLARE_WORKSPACE` | `nvflare_workspace` | Destination workspace directory. Expected provisioned root is `<workspace>/duality_nvflare/prod_00`. |
| `DUALITY_NVFLARE_ADMIN_NAME` | `admin@share.local` | Admin participant folder name searched under the provisioned workspace. |
| `DUALITY_NVF_WSL_TIMEOUT_SECS` | `900` | Timeout for WSL provisioning on Windows. |
| `DUALITY_NVF_LOCAL_TIMEOUT_SECS` | `600` | Timeout for local provisioning attempts on non-Windows platforms. |

Provisioning behavior:

1. Load `.env.local`.
2. Delete and recreate `<standalone>/dist`.
3. Check whether `<DUALITY_NVFLARE_WORKSPACE>/duality_nvflare/prod_00` exists.
4. If already provisioned, skip the provision command.
5. If not provisioned, install `nvflare==2.7.2` locally on non-Windows when missing.
6. Rewrite `project.yml` to `project.local.yml` using the configured host and ports.
7. Provision locally on non-Windows using `nvflare`, `provision`, or `python -m nvflare.cli`.
8. Provision through WSL on Windows.
9. Tar the admin startup kit to `<standalone>/dist/admin_startup_kit.tar`.
10. Write `DUALITY_ADMIN_TAR=<standalone>/dist/admin_startup_kit.tar` back into `.env.local`.

## Client Compose Environment Use

`client_utils/docker-compose.client-template.yml` is not launched directly. `create_client.py` renders a temporary per-site file and runs:

```text
docker compose -p duality-client -f <temporary-compose-file> up -d --build client-<site> [results-agent-<site>]
```

The following variables are injected by `create_client.py` into the Compose subprocess environment:

| Variable | Value |
| --- | --- |
| `SITE` | Requested site name, such as `site1`. |
| `CLIENT_TAR` | Absolute path to the generated or provided client startup kit tar. |
| `JOB_RESULTS_DIR` | Absolute path to `<standalone>/job-results` for `site3`, or `<standalone>/job-results/<site>` for every other site. |
| `CLIENT_JOB_SAVE_LOCATION` | `/job-results` for every site. |
| `ENABLE_JOB_RESULTS_SYMLINK` | `true` for every site. |
| `CLIENT_RESULTS_PORT` | `DUALITY_CLIENT_RESULTS_BASE_PORT` (default `8088`) plus the site number, so `site1` uses `8089`. `site3` gets the placeholder `8088` because its results-agent service is never started. |
| `DUALITY_UI_ORIGINS` | Passthrough of the host `DUALITY_UI_ORIGINS` value, or blank. |
| `DUALITY_HOST_UID` | `str(os.getuid())` on hosts that expose `os.getuid`, applied with `setdefault` so an exported value wins. |
| `DUALITY_HOST_GID` | `str(os.getgid())` on hosts that expose `os.getuid`, applied with `setdefault` so an exported value wins. |

The client container receives:

| Container env | Value |
| --- | --- |
| `NVFLARE_VENV_DIR` | `/opt/nvflare/.venv` |
| `NVFLARE_SERVER_BASE` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` |
| `DUALITY_NVFLARE_HOST` | The site name, such as `site1`. |
| `NVFLARE_SERVER_TAR_PATH` | `/kits/client_startup_kit.tar` |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `/job-results` |
| `DUALITY_ENABLE_JOB_RESULTS_SYMLINK` | `true` |
| `DUALITY_NVFLARE_LIB_UPDATE_DISABLED` | Legacy/test passthrough. The public runtime is local-wheel-only regardless; simulator helpers may set it defensively. |
| `DUALITY_HOST_UID` | Host user ID used to hand ownership of files written to the bind-mounted `/job-results` tree back to the host user. Blank is a no-op. |
| `DUALITY_HOST_GID` | Host group ID paired with `DUALITY_HOST_UID`. Blank falls back to the UID value. |

The client container mounts:

| Mount | Purpose |
| --- | --- |
| `${CLIENT_TAR}:/kits/client_startup_kit.tar:ro` | Supplies the client startup kit tar. |
| `${JOB_RESULTS_DIR}:/job-results` | Shares the site results directory with the client. |
| `./local_wheels:/opt/duality/local_wheels:ro` | Supplies an optional local `duality_nvflare_lib-*.whl` installed at container start. |

The companion results-agent container, started for every site except `site3`, receives:

| Container env | Value |
| --- | --- |
| `DUALITY_CLIENT_SITE` | The site name, such as `site1`. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | `/job-results` |
| `DUALITY_UI_ORIGINS` | Comma-separated extra CORS origins appended to the agent's built-in allow list. Blank adds nothing. |

It mounts `${JOB_RESULTS_DIR}:/job-results:ro` and publishes `127.0.0.1:${CLIENT_RESULTS_PORT}:8088`.

Both services attach to the network named by `DUALITY_DOCKER_NETWORK`, default `duality_default`, which the template declares `external: true`.

## Environment Utility Behavior

`utils/environment_utils.py` contains one function:

```text
load_env_file(path: str | Path = ".env.local") -> None
```

Behavior:

| Case | Behavior |
| --- | --- |
| File missing | Raises `FileNotFoundError`. |
| Blank line | Ignored. |
| Comment line beginning with `#` after stripping | Ignored. |
| Line without `=` | Ignored. |
| `KEY=VALUE` line | Splits on the first `=`, strips the key and value, and sets `os.environ[KEY]` only if the key is not already set. |
| Duplicate keys in the file | First loaded value wins because `setdefault()` is used. |
| Existing process env var | Preserved and not overwritten. |

The utility does not support shell-style quoting, variable interpolation, export syntax, multi-line values, or inline comment stripping.

## Safe Reset Procedure for `.env.local`

Use this when local environment configuration becomes inconsistent or when the active file should be regenerated from the baseline template.

1. Stop the standalone stack if it is running:

```bash
python main.py rebuild backend
```

or use the UI to stop/rebuild as needed. The current code does not expose a public `docker down` subcommand through argparse, so direct Compose commands can also be used from `standalone/docker_stage`:

```bash
docker compose -p duality --env-file ../.env.local down
```

2. Back up the current file if there are local values worth preserving:

```bash
cp .env.local .env.local.bak
```

3. Restore from the template:

```bash
cp default.env.local .env.local
```

4. Set machine-specific values. At minimum, confirm:

```text
DUALITY_DB_MODE=container
DUALITY_MYSQL_DB=duality_local or duality_dev
DUALITY_NVFLARE_HOST=auto or <local-ip>
```

5. Run the orchestrator or UI:

```bash
python main.py ui
```

or:

```bash
python main.py
```

6. Let `main.py` resolve `DUALITY_NVFLARE_HOST` if it is `auto` or blank.

7. Rebuild clients after a full reset or MySQL data wipe, because client DB records may need to be recreated:

```bash
python main.py client --site site1
python main.py client --site site2
python main.py client --site site3
```

If the MySQL named volume is intentionally wiped, the UI warns that clients must be re-added. The wipe path removes the Compose volume named:

```text
duality_mysql_data
```

for the default main Compose project name `duality`.

## Local Configuration Rules

Developers should treat `default.env.local` as the source template and `.env.local` as the generated active file. Because the current orchestrator copies `default.env.local` to `.env.local` at startup, durable local defaults should be placed in `default.env.local` unless the seeding behavior is changed.

When adding or changing an environment variable, update the correct places:

| Change type | Required updates |
| --- | --- |
| Python orchestration value | Add/read it in the relevant Python stage and add it to `default.env.local` when it should be configurable. |
| Main Compose service value | Add it to `docker_stage/docker-compose.yml`; use `${VAR:-fallback}` when a default is safe. |
| Frontend build/runtime value | Add it to `ContainerBuilder._write_frontend_env()` if it must be written into `../frontend/.env.production.local`, and/or Compose if the container needs it. |
| Client runtime value | Add it to `client_utils/create_client.py` and `client_utils/docker-compose.client-template.yml` if it must reach client containers. |
| Per-site datasource value | Follow `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT>` or `DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT>_<GROUP>`. |
| Host MySQL value | Confirm both host-side code and Compose backend behavior. Host-side code uses `.env.local`; backend Compose overrides host/port to `mysql:3306`. |
| NVFlare provisioning value | Confirm whether it must be applied before provisioning, written into `project.local.yml`, passed into containers, or written back to `.env.local`. |

## Current Implementation Notes

- `main.py` contains a `cmd_docker()` helper and comments referencing a Docker subcommand, but the current argparse setup does not register a public `docker` subcommand. Docker actions are used internally through the default pipeline and UI.
- `.env.local` is overwritten from `default.env.local` by `_ensure_env_local_seed()` on normal `main.py` startup. This is important when testing local env edits.
- `DUALITY_ADMIN_TAR` is generated/written by the NVFlare stage and is not present in the default template.
- Missing raw JSON datasource files are acceptable if corresponding zip files are available or if the datasource entry points to a remote FHIR URL.
- The provisioned NVFlare workspace is generated state. It does not need to be committed with the standalone package.
