# Troubleshooting and Operations

## Current Datasource Runtime Model

Standalone client utilities use datasource environment values as host-side staging paths for local JSON files. Those files are copied into client containers under `/data/client/`. The running client does not use retired `DUALITY_FHIR_BASE_CONFIG.json` or retired `DUALITY_NVFLARE_FHIR_BASE_CONFIG`; it requests its datasource from the NVFlare server, which resolves the value through backend user settings.

See `09-local-datasource-staging-and-runtime-lookup.md` for the full current flow.

## Files Covered

| File/Directory | Role |
| --- | --- |
| `main.py` | Main CLI, default startup pipeline, interactive UI, status probes, rebuild/update/wheel/client/clientdb commands. |
| `LAUNCH_ME_LINUX.sh` | Linux UI launcher. Runs from the standalone directory, selects Python, checks Docker access, then invokes `main.py ui`. |
| `LAUNCH_ME_MAC.command` | macOS UI launcher. Runs from the standalone directory, selects Python, invokes `main.py ui`, and leaves the terminal window open after exit. |
| `LAUNCH_ME_WIN.bat` | Windows UI launcher. Runs from the standalone directory, selects `py` or `python`, invokes `main.py ui`, and pauses after exit. |
| `default.env.local` | Baseline environment template copied into `.env.local` during startup. |
| `.env.local` | Active runtime environment file consumed by the standalone Python scripts and Docker Compose. |
| `docker_stage/container_builder.py` | Docker Compose helper for build, up, down, logs, ps, pull, rebuild, update, reset, frontend env writing, and MySQL volume wiping. |
| `docker_stage/docker-compose.yml` | Main local service stack: `mysql`, `backend`, `frontend`, and `nvflare`. |
| `docker_stage/*.Dockerfile` | Build definitions for MySQL, backend, frontend, and NVFlare server containers. |
| `client_utils/create_client.py` | Per-site client startup kit tar creation, datasource JSON staging, MySQL client registration, and client container build/start behavior. |
| `client_utils/client.Dockerfile` | Per-site NVFlare client image definition. |
| `client_utils/docker-compose.client-template.yml` | Template rendered into a temporary per-site client Compose file. |
| `utils/environment_utils.py` | Environment file loader used by the CLI and client scripts. |
| `utils/ip_utils.py` | Local IP detection helper used when `DUALITY_NVFLARE_HOST` is `auto` or blank. |
| `utils/mysql_driver_utils.py` | Local MySQL Python driver helper. Installs `mysql-connector-python` and `PyMySQL` into `.deps/python` if neither driver is importable. |
| `utils/wheel_utils.py` | Utility module retained in the standalone source tree. Current server/client images do not bake in the `duality_nvflare_lib` wheel. |
| `mysql_stage/` | Host MySQL setup/check path used only when `DUALITY_DB_MODE=host`. |
| `nvflare_stage/` | NVFlare install/provisioning script and related workspace support files. |

## Operations Role

The standalone package is the local operations wrapper for running SHARE with local containers. It starts and rebuilds the local MySQL database, backend, frontend, NVFlare server, and per-site NVFlare clients.

The main day-to-day entrypoint is:

```bash
python3 main.py ui
```

The OS-specific launchers all invoke the same UI command.

| Launcher | Command invoked |
| --- | --- |
| `LAUNCH_ME_LINUX.sh` | `python3 main.py ui`, or `$PYTHON_BIN main.py ui` when `PYTHON_BIN` is set. |
| `LAUNCH_ME_MAC.command` | `python3 main.py ui`, or `$PYTHON_BIN main.py ui` when `PYTHON_BIN` is set. |
| `LAUNCH_ME_WIN.bat` | `py main.py ui` if available, otherwise `python main.py ui`, or `%PYTHON_BIN% main.py ui` when `PYTHON_BIN` is set. |

## Important CLI Availability Note

`main.py` contains an internal `cmd_docker()` helper, but the current `argparse` setup does not register a public `docker` subcommand. Do not document or rely on `python3 main.py docker ...` as an available command unless the parser is updated later.

Use the interactive UI for Docker operations, or run Docker Compose directly from `standalone/docker_stage`.

## Common Commands

| Command | Use |
| --- | --- |
| `python3 main.py` | Run the default local pipeline. Seeds `.env.local`, loads env, runs MySQL/codebase checks, provisions NVFlare when needed, then builds/starts or rebuilds the main stack. |
| `python3 main.py ui` | Open the interactive standalone status and rebuild dashboard. |
| `python3 main.py codebase [backend|frontend|all]` | Verify expected source directories under the workspace root. Defaults to `all`. |
| `python3 main.py mysql` | Run host MySQL setup/check behavior when `DUALITY_DB_MODE=host`. Skips host setup when `DUALITY_DB_MODE=container`. |
| `python3 main.py nvflare` | Run NVFlare install/provisioning. |
| `python3 main.py rebuild backend` | Rebuild and restart backend only. |
| `python3 main.py rebuild frontend` | Rebuild and restart frontend only. |
| `python3 main.py rebuild nvflare` | Rebuild and restart NVFlare server only. |
| `python3 main.py rebuild mysql` | Rebuild and restart MySQL only. May wipe the MySQL volume when `DUALITY_DB_WIPE_ON_REBUILD=true`. |
| `python3 main.py rebuild mysql backend` | Rebuild MySQL and backend together. Use this after a MySQL data wipe so backend reconnects and recreates schema/default data. |
| `python3 main.py rebuild backend --no-cache` | Rebuild backend without Docker build cache. |
| `python3 main.py update backend` | Run `git pull` in `../backend`, then rebuild and restart backend. |
| `python3 main.py update frontend` | Run `git pull` in `../frontend`, then rebuild and restart frontend. |
| `python3 main.py wheel` | Rebuild/relaunch NVFlare, then rebuild already-running client containers. Runtime wheel updates happen inside submitted jobs. Requires NVFlare and at least one client container to already be running. |
| `python3 main.py wheel --no-cache` | Same as `wheel`, but disables Docker build cache for the NVFlare rebuild. |
| `python3 main.py client --site site1` | Create/rebuild/start the `site1` client container and ensure its MySQL client record exists. |
| `python3 main.py client --site site1 --tar-kit` | Create the `dist/client_site1_startup_kit.tar` only, then optionally ensure the MySQL client record. |
| `python3 main.py client --tar-file /path/to/client_site1_startup_kit.tar` | Build/start a client from an existing startup kit tar. The site is inferred from the tar filename. |
| `python3 main.py clientdb --site site1` | Ensure the MySQL user/client mapping exists for `site1` without rebuilding the client container. |
| `python3 main.py --env-file /path/to/env ui` | Use an explicit env file instead of the default `.env.local`. |

## Accepted Service Names

The main Compose helper accepts these service names for rebuild/build/log operations:

| Service | Container | Notes |
| --- | --- | --- |
| `mysql` | `duality-mysql` | Main local database. Rebuild preserves the `duality_mysql_data` Docker volume unless wiping is enabled. |
| `backend` | `duality-backend` | FastAPI backend. Source is expected at `../backend` relative to `standalone`. |
| `frontend` | `frontend` | React frontend. Source is expected at `../frontend` relative to `standalone`. |
| `nvflare` | `duality-nvflare` | Local NVFlare server/runtime container. Runtime wheel installation occurs inside submitted jobs. |

The `update` command only accepts:

- `backend`
- `frontend`

Client containers are handled separately through `python3 main.py client --site <site>` and are named `duality-client-<site>`.

## Default Startup Pipeline

Running `python3 main.py` with no command performs the main local startup pipeline.

The pipeline does this:

1. Copies `default.env.local` to `.env.local`.
2. Resolves `DUALITY_NVFLARE_HOST` if it is blank or `auto`, then writes the detected local IP into `.env.local`.
3. Ensures `DUALITY_DB_MODE=container` exists when missing.
4. Loads the env file into the Python process.
5. Checks Docker access before running the full pipeline.
6. Runs the MySQL stage.
   - In `container` mode, this is a no-op and the Compose `mysql` service is used.
   - In `host` mode, `mysql_stage/mysql_check_or_install.py` runs.
7. Runs the codebase stage to verify backend/frontend source directories.
8. Checks whether any existing container name starts with `duality-`.
9. If existing containers are found, rebuilds `mysql`, `backend`, `frontend`, and `nvflare`, then redeploys already-running client containers.
10. If existing containers are not found, runs the internal Docker `run` action, which provisions NVFlare, resets the Compose project, builds all services, and starts the stack.

Operational caution: `_ensure_env_local_seed()` copies `default.env.local` to `.env.local` on startup. Local edits made only in `.env.local` can be overwritten by rerunning `main.py`. Put durable local defaults into `default.env.local` or adjust the seeding behavior if this is not intended.

## Interactive UI Walkthrough

Run:

```bash
python3 main.py ui
```

The UI clears the terminal and prints a `Duality Standalone Status` banner.

### Status Banner

The banner shows:

| Section | Values shown |
| --- | --- |
| Project | Compose project name. Defaults to `duality`. |
| Docker | Shows a failure line when Docker is unavailable or inaccessible. |
| Containers | Status for `mysql`, `backend`, `frontend`, `nvflare`, and running client containers. |
| MySQL | Host, port, user, database, driver, connection status, and registered clients from `nvflare_clients`. |
| NVFLARE | Workspace path, computed root path, and whether the workspace is provisioned. |

Container status is read from:

```bash
docker ps --filter label=com.docker.compose.project=duality --format '{{.Label "com.docker.compose.service"}}|{{.Status}}'
```

Running clients are detected by scanning running Docker container names that start with:

```text
duality-client-
```

MySQL status is checked by connecting with values from the environment:

| Env var | Meaning |
| --- | --- |
| `DUALITY_MYSQL_HOST` | MySQL host for the standalone Python scripts. Defaults to `localhost`. |
| `DUALITY_MYSQL_PORT` | MySQL port for the standalone Python scripts. Defaults to `3306` if parsing fails. |
| `DUALITY_MYSQL_USER` | MySQL app user. |
| `DUALITY_MYSQL_PASSWORD` | MySQL app password. |
| `DUALITY_MYSQL_DB` | MySQL database. |

When `DUALITY_DB_MODE=container` and the MySQL container is not running, the UI reports MySQL as failed with:

```text
MySQL container not running (DUALITY_DB_MODE=container)
```

NVFlare provisioning status is checked by looking for:

```text
<DUALITY_NVFLARE_WORKSPACE>/duality_nvflare/prod_00
```

### UI Menu Options

| Option | Label | Behavior |
| --- | --- | --- |
| `1` | `Provision workspace & build all`, `Reset & rebuild all`, or `Build all` | Label depends on current state. Runs the full pipeline. If containers already exist, prompts whether to wipe the MySQL data volume before rebuilding all main services. On success, seeds the default clients by calling the backend, then prints the registered client names or a warning that the backend was not reachable yet. |
| `2` | `Rebuild backend` | Runs `builder.rebuild(["backend"])`. |
| `3` | `Rebuild frontend` | Runs `builder.rebuild(["frontend"])`. |
| `4` | `Rebuild nvflare` | Runs `builder.rebuild(["nvflare"])`. |
| `5` | `Rebuild mysql` | Prompts whether to wipe MySQL data volume, then runs `builder.rebuild(["mysql"], wipe_mysql=<answer>)`. |
| `6` | `Create/Rebuild USER SPECIFIED client container (includes persist to MySQL)` | Prompts for a site name, then runs `python main.py client --site <site>`. Pressing Enter without a site name seeds the default clients through the backend and runs that command for every client registered in MySQL. |
| `7` | `Persist USER SPECIFIED client to MySQL` | Prompts for a site name, then runs `python main.py clientdb --site <site>`. |
| `8` | `Rebuild ALREADY RUNNING client containers` | Detects running `duality-client-*` containers and reruns the client command for each detected site. |
| `9` | `Redeploy ALREADY RUNNING NVFlare Server/Client` | Runs the `wheel` command. Requires `duality-nvflare` and at least one client container to be running. |
| `r` or Enter | `Refresh` | Redraws status. |
| `q`, `quit`, or `x` | `Quit` | Exits the UI. |

The option `1` label is computed as follows:

| Condition | Label |
| --- | --- |
| NVFlare workspace root is missing | `Provision workspace & build all` |
| Workspace exists and a container name starts with `duality-` | `Reset & rebuild all` |
| Workspace exists and no `duality-` containers exist | `Build all` |

## Docker Compose Commands Used Internally

The `ContainerBuilder` prefers:

```bash
docker compose
```

It falls back to:

```bash
docker-compose
```

Every main stack command adds the Compose project name:

```bash
-p duality
```

When an env file is resolved, every main stack command also adds:

```bash
--env-file /absolute/path/to/.env.local
```

All main stack Docker Compose commands run with working directory:

```text
standalone/docker_stage
```

### Main Compose Operation Map

| Helper operation | Docker command shape |
| --- | --- |
| Build | `docker compose -p duality --env-file <env> build [--no-cache] [services...]` |
| Up | `docker compose -p duality --env-file <env> up -d --build [services...]` |
| Down | `docker compose -p duality --env-file <env> down [-v]` |
| Logs | `docker compose -p duality --env-file <env> logs [-f] [services...]` |
| PS | `docker compose -p duality --env-file <env> ps` |
| Pull | `docker compose -p duality --env-file <env> pull [services...]` |
| Reset | `docker compose -p duality --env-file <env> down --remove-orphans` |
| Rebuild | `build`, then `rm -f -s <services>`, then `up -d --no-deps <services>` |
| Update | `git pull`, then the same build/rm/up sequence as rebuild. |
| MySQL volume wipe | `docker compose ... stop mysql`, `docker compose ... rm -f -s mysql`, then `docker volume rm -f duality_mysql_data`. |

### Direct Compose Commands

Use these when bypassing the UI.

```bash
cd standalone/docker_stage
```

Show main stack status:

```bash
docker compose -p duality --env-file ../.env.local ps
```

Show all main stack logs:

```bash
docker compose -p duality --env-file ../.env.local logs
```

Follow backend logs:

```bash
docker compose -p duality --env-file ../.env.local logs -f backend
```

Follow frontend logs:

```bash
docker compose -p duality --env-file ../.env.local logs -f frontend
```

Follow NVFlare logs:

```bash
docker compose -p duality --env-file ../.env.local logs -f nvflare
```

Follow MySQL logs:

```bash
docker compose -p duality --env-file ../.env.local logs -f mysql
```

Restart the main stack without deleting volumes:

```bash
docker compose -p duality --env-file ../.env.local down --remove-orphans
docker compose -p duality --env-file ../.env.local up -d --build
```

Stop and delete the main stack containers but preserve named volumes:

```bash
docker compose -p duality --env-file ../.env.local down --remove-orphans
```

Stop and delete the main stack containers and named volumes:

```bash
docker compose -p duality --env-file ../.env.local down --remove-orphans -v
```

## Container, Port, and Volume Reference

### Main Containers

| Service | Container | Purpose |
| --- | --- | --- |
| `mysql` | `duality-mysql` | Local MySQL 8.0.41 database. |
| `backend` | `duality-backend` | FastAPI backend on port `8000`. |
| `frontend` | `frontend` | React static app served on port `3000`. |
| `nvflare` | `duality-nvflare` | Local NVFlare server/runtime. |
| Client | `duality-client-<site>` | Per-site NVFlare client container. |
| Client results agent | `duality-client-results-<site>` | Per-site FastAPI results agent. Started for every site except the initiator site `site3`. |

### Ports

| Port | Mapping | Used by |
| --- | --- | --- |
| `3307` | Host to MySQL container `3306` | Host tools connecting to container MySQL. |
| `3306` | MySQL internal container port | Backend container uses `mysql:3306` on Compose network. |
| `8000` | Host to backend `8000` | Backend API. |
| `3000` | Host to frontend `3000` | Browser access to frontend. |
| `${DUALITY_NVFLARE_FED_PORT:-8002}` | Host to NVFlare server `8002` | NVFlare federation port. |
| `${DUALITY_NVFLARE_ADMIN_PORT:-8003}` | Host to NVFlare server `8003` | NVFlare admin port. |
| `8004` | Host to NVFlare server `8004` | Optional status page if enabled. |
| `8088 + <site number>` | `127.0.0.1` to results agent `8088` | Per-site client results agent, for example `8089` for `site1`. Bound to loopback only. The base port can be changed with `DUALITY_CLIENT_RESULTS_BASE_PORT`. |

### Volumes and Mounts

| Mount | Used by | Behavior |
| --- | --- | --- |
| `mysql_data:/var/lib/mysql` | MySQL | Persistent named Docker volume. With project name `duality`, volume name is `duality_mysql_data`. |
| `../mysql_stage/init:/docker-entrypoint-initdb.d` | MySQL | Optional first-start initialization SQL location. The directory may be absent or empty. |
| `../nvflare_workspace:/home/ubuntu/nvflare/workspace` | Backend and NVFlare | Shared local NVFlare workspace. |
| `../job-results:/job-results` | Backend | Local job result storage exposed to backend. |
| `./local_wheels:/opt/duality/local_wheels:ro` | NVFlare | Optional local `duality_nvflare_lib-*.whl` installed at image build time. |
| `../job-results:/trace-sink` | NVFlare | Profiler trace-sink target named by `DUALITY_TRACE_SINK_DIR`. Puts the server trace next to the client traces for the report generator. |
| `${CLIENT_TAR}:/kits/client_startup_kit.tar:ro` | Client containers | Per-site startup kit tar mounted read-only. |
| `${JOB_RESULTS_DIR}:/job-results` | Client containers | Site results mount. `standalone/job-results` for `site3`, `standalone/job-results/<site>` for other sites. |
| `./local_wheels:/opt/duality/local_wheels:ro` | Client containers | Optional local `duality_nvflare_lib-*.whl` installed at container start. |
| `${JOB_RESULTS_DIR}:/job-results:ro` | Client results agents | Read-only view of the same site results directory. |

## Health and Status Commands

### Docker Access

```bash
docker info
```

```bash
docker ps --format '{{.Names}}'
```

If Linux reports permission denied on `/var/run/docker.sock`, rerun the Linux launcher with `sudo` or fix Docker group permissions.

### Main Containers

```bash
docker ps --filter label=com.docker.compose.project=duality
```

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local ps
```

### Client Containers

```bash
docker ps --format '{{.Names}}' | grep '^duality-client-'
```

```bash
docker logs -f duality-client-site1
```

```bash
docker logs -f duality-client-site2
```

```bash
docker logs -f duality-client-site3
```

### Backend Health

The backend container starts Uvicorn with:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

First checks:

```bash
curl http://localhost:8000/health
```

If `/health` is not implemented or not routed in the backend branch, use a known backend route such as:

```bash
curl -X POST http://localhost:8000/user/role \
  -H 'Content-Type: application/json' \
  -d '{"username":"client"}'
```

The client registration flow itself calls `/user/role` to force backend database/schema initialization before inserting client records.

### Frontend Browser Access

```text
http://localhost:3000
```

The Compose file passes:

```text
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

`ContainerBuilder` also writes `../frontend/.env.production.local` before frontend builds. It chooses `REACT_APP_API_BASE` from `.env.local`, then `NEXT_PUBLIC_BACKEND_URL`, then process env, and finally defaults to `http://localhost:8000`.

### MySQL Host Access

Container mode maps host port `3307` to MySQL container port `3306`:

```bash
mysql -h 127.0.0.1 -P 3307 -u duality -p duality_local
```

Use the password from:

```text
DUALITY_MYSQL_PASSWORD
```

Inside the Compose network, backend connects to:

```text
DUALITY_MYSQL_HOST=mysql
DUALITY_MYSQL_PORT=3306
```

### NVFlare Workspace Check

```bash
ls -la standalone/nvflare_workspace/duality_nvflare/prod_00
```

If `DUALITY_NVFLARE_HOST` was resolved to a local IP, the server startup directory is expected below:

```text
standalone/nvflare_workspace/duality_nvflare/prod_00/<DUALITY_NVFLARE_HOST>/startup
```

The NVFlare container searches that host-specific startup folder first, then falls back to the first `startup` directory found under the server base.

## Default Startup Failures

### Docker is unavailable

Symptoms:

- UI shows `Docker : FAILED`.
- Launcher prints `Cannot connect to Docker daemon`.
- Linux launcher reports permission denied for `/var/run/docker.sock`.

Checks:

```bash
docker info
```

```bash
docker ps
```

Recovery:

- Start Docker Desktop or the Docker daemon.
- On Linux, rerun `sudo ./LAUNCH_ME_LINUX.sh` if this machine requires elevated Docker access.
- Fix Docker group permissions if sudo is not desired.

### `.env.local` values are wrong or keep changing

Symptoms:

- NVFlare host changes unexpectedly.
- Ports or datasource paths reset after rerunning the CLI.
- MySQL settings appear to revert.

Cause:

`main.py` copies `default.env.local` to `.env.local` every startup.

Recovery:

- Put durable standalone defaults into `default.env.local`.
- Then rerun `python3 main.py ui` or `python3 main.py`.

### `DUALITY_NVFLARE_HOST` is unreachable

Symptoms:

- NVFlare server starts, but clients cannot connect.
- Startup kits were generated for one host/IP but containers now use another.

Checks:

```bash
grep DUALITY_NVFLARE_HOST standalone/.env.local
```

```bash
docker logs -f duality-nvflare
```

```bash
docker logs -f duality-client-site1
```

Recovery:

1. Set `DUALITY_NVFLARE_HOST` to the intended reachable host/IP in `default.env.local`.
2. Re-provision NVFlare:

```bash
python3 main.py nvflare
```

3. Rebuild NVFlare:

```bash
python3 main.py rebuild nvflare
```

4. Rebuild clients:

```bash
python3 main.py client --site site1
python3 main.py client --site site2
python3 main.py client --site site3
```

### Required ports are already in use

Symptoms:

- Compose fails to bind a port.
- Frontend/backend/NVFlare/MySQL container exits during startup.

Check Windows:

```bat
netstat -ano | findstr :8000
netstat -ano | findstr :3000
netstat -ano | findstr :3307
netstat -ano | findstr :8002
netstat -ano | findstr :8003
```

Check macOS/Linux:

```bash
lsof -i :8000
lsof -i :3000
lsof -i :3307
lsof -i :8002
lsof -i :8003
```

Recovery:

- Stop the conflicting process.
- Or change the relevant Compose/env port and rebuild the affected container.
- For frontend/backend URL changes, rebuild frontend so its built API URL matches the new backend URL.

## MySQL Troubleshooting

### Container MySQL is not healthy

Checks:

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local ps mysql
docker compose -p duality --env-file ../.env.local logs -f mysql
```

Common causes:

- Bad credentials after an existing volume was initialized with older credentials.
- Port conflict on host port `3307`.
- MySQL volume corruption or incompatible data.
- `MYSQL_USER=root` or app user configured as `root` in container mode.

Recovery without deleting data:

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local restart mysql
```

Recovery with database reset:

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local stop mysql
docker compose -p duality --env-file ../.env.local rm -f -s mysql
docker volume rm -f duality_mysql_data
docker compose -p duality --env-file ../.env.local up -d --build mysql
```

Then rebuild backend:

```bash
python3 main.py rebuild backend
```

### Host tool cannot connect to MySQL

Use host port `3307`, not `3306`, when `DUALITY_DB_MODE=container`.

```bash
mysql -h 127.0.0.1 -P 3307 -u duality -p duality_local
```

### Backend cannot connect to MySQL

Checks:

```bash
docker logs -f duality-backend
```

```bash
docker exec -it duality-backend env | grep DUALITY_MYSQL
```

Expected backend container values in container mode:

```text
DUALITY_MYSQL_HOST=mysql
DUALITY_MYSQL_PORT=3306
```

Recovery:

```bash
python3 main.py rebuild mysql backend
```

If the database was wiped, use `/user/role` or load the frontend once so backend initializes tables/default data.

### Backend tables are missing

The standalone code does not own the full schema creation. Backend startup and backend routes initialize the database through backend code.

Recovery:

1. Ensure MySQL is healthy.
2. Rebuild/restart backend.
3. Trigger backend initialization:

```bash
curl -X POST http://localhost:8000/user/role \
  -H 'Content-Type: application/json' \
  -d '{"username":"client"}'
```

4. Rerun client registration:

```bash
python3 main.py clientdb --site site1
```

## Backend Troubleshooting

### Backend build fails

Checks:

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local build backend
```

Common causes:

- `../backend` source tree is missing.
- `backend/requirements.txt` install failure.
- Docker is not running.
- Backend source has syntax/import errors.

Recovery:

```bash
python3 main.py codebase backend
python3 main.py rebuild backend --no-cache
```

### Backend starts but API calls fail

Checks:

```bash
docker logs -f duality-backend
curl http://localhost:8000/health
curl -X POST http://localhost:8000/user/role -H 'Content-Type: application/json' -d '{"username":"client"}'
```

Confirm frontend is using the same API base:

```bash
cat ../frontend/.env.production.local
```

Recovery:

- Rebuild backend if it cannot import modules or connect to MySQL.
- Rebuild frontend if browser calls are pointed at the wrong backend URL.
- Rebuild NVFlare if job submission fails because the workspace/admin startup kit is missing.

### Backend cannot find NVFlare admin kit or workspace

Expected backend container values:

```text
DUALITY_ADMIN_TAR=/kits/admin_startup_kit.tar
DUALITY_NVFLARE_WORKSPACE=/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00
DUALITY_NVFLARE_JOB_SAVE_LOCATION=/job-results
```

Checks:

```bash
docker exec -it duality-backend ls -la /kits
docker exec -it duality-backend ls -la /home/ubuntu/nvflare/workspace/duality_nvflare/prod_00
docker exec -it duality-backend ls -la /job-results
```

Recovery:

```bash
python3 main.py nvflare
python3 main.py rebuild backend nvflare
```

## Frontend Troubleshooting

### Frontend build fails

Checks:

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local build frontend
```

Common causes:

- `../frontend` source tree is missing.
- `npm ci` fails because `package-lock.json`/dependencies are inconsistent.
- Node 18 build incompatibility with the frontend branch.
- Frontend API env file was not written.

Recovery:

```bash
python3 main.py codebase frontend
python3 main.py rebuild frontend --no-cache
```

### Frontend loads but API calls fail

Checks:

- Browser console.
- Browser Network tab.
- Backend availability at `http://localhost:8000`.
- Built frontend env values.

```bash
cat ../frontend/.env.production.local
curl http://localhost:8000/health
```

Recovery:

- Set `REACT_APP_API_BASE` or `NEXT_PUBLIC_BACKEND_URL` in the env template.
- Rebuild frontend.

```bash
python3 main.py rebuild frontend
```

### Frontend assets/config files are missing

Symptoms:

- Page renders but project list, filters, local test data, or job runner config fails.
- Browser Network tab shows `404` for public files.

Checks:

- Confirm omitted raw test data files are actually present when a local workflow needs them.
- Confirm frontend public asset paths match the files in the frontend source branch.
- Confirm local JSON/zip datasource paths configured in `default.env.local` exist when client containers are built.

Recovery:

- Restore required local test/config files.
- Rebuild frontend or client containers depending on which context consumes the file.

## NVFlare Troubleshooting

### NVFlare workspace is not provisioned

Symptoms:

- UI shows `NVFLARE status: NOT PROVISIONED`.
- `duality-nvflare` cannot find a server startup directory.
- Backend job submission cannot find NVFlare workspace/admin kit.

Checks:

```bash
ls -la standalone/nvflare_workspace/duality_nvflare/prod_00
ls -la standalone/dist
```

Recovery:

```bash
python3 main.py nvflare
python3 main.py rebuild nvflare
```

Then rebuild clients:

```bash
python3 main.py client --site site1
python3 main.py client --site site2
python3 main.py client --site site3
```

### Startup kits are stale after host/IP change

Symptoms:

- Server starts with one host/IP but clients look for another.
- Clients cannot connect to server.
- `DUALITY_NVFLARE_HOST` differs from the generated workspace folder name.

Recovery:

1. Stop server and clients.
2. Set the intended host/IP in `default.env.local`.
3. Re-provision NVFlare.
4. Rebuild server and clients.

```bash
docker stop duality-client-site1 duality-client-site2 duality-client-site3 2>/dev/null || true
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local stop nvflare
cd ..
python3 main.py nvflare
python3 main.py rebuild nvflare
python3 main.py client --site site1
python3 main.py client --site site2
python3 main.py client --site site3
```

### NVFlare container starts then sits idle

The NVFlare server Dockerfile starts the server and then runs `tail -f /dev/null` to keep the container alive. A running container does not guarantee the NVFlare server started correctly.

Check logs:

```bash
docker logs -f duality-nvflare
```

Check startup directory inside the container:

```bash
docker exec -it duality-nvflare bash
ls -la /home/ubuntu/nvflare/workspace/duality_nvflare/prod_00
```

Recovery:

```bash
python3 main.py nvflare
python3 main.py rebuild nvflare --no-cache
```

## Client Container Troubleshooting

### Requested site has no startup kit or workspace participant folder

Symptoms:

- `python3 main.py client --site site1` exits with `Could not find client folder`.

Checks:

```bash
ls -la standalone/nvflare_workspace/duality_nvflare/prod_00
```

Recovery:

```bash
python3 main.py nvflare
python3 main.py client --site site1
```

### Datasource environment is missing

Symptoms:

- Client creation exits with `No datasource configuration found for site '<site>'`.

Required env patterns:

```text
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>=<path-or-url>
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>_<DATASOURCE_GROUP_ID>=<path-or-url>
```

Examples:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_1=http://example/fhir
DUALITY_CLIENT_SITE1_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json
```

Recovery:

- Add the missing datasource variable to `default.env.local`.
- Rerun client creation.

```bash
python3 main.py client --site site1
```

### Local JSON datasource path does not exist

The client builder warns if a resolved local JSON path does not exist. It also attempts to unzip a sibling `.zip` file when a configured `.json` file is missing and a same-name `.zip` exists.

Example:

```text
nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json
```

If the JSON is missing, the script checks for:

```text
nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.zip
```

Recovery:

- Restore the raw JSON file, or restore the corresponding zip file.
- Rerun the client command so `injected_datasources/` is rebuilt and copied into the client image.

```bash
python3 main.py client --site site1
```

### Remote FHIR URL is not reachable

Remote datasource values are stored in backend user datasource settings and returned at job runtime. They are not copied into the client image.

Checks:

```bash
curl <remote-fhir-url>/metadata
```

Recovery:

- Correct the URL in `default.env.local`.
- Rerun client creation.

### Client record is missing in MySQL

Run:

```bash
python3 main.py clientdb --site site1
```

This calls backend `/user/role` first to encourage DB/table initialization, then inserts/updates:

| Table | Behavior |
| --- | --- |
| `roles` | Ensures `client` role for non-`site3` clients. |
| `users` | Inserts `client_<site>` with status `DISABLED` for non-`site3` clients. |
| `nvflare_clients` | Inserts or updates the `client_name -> user_id` mapping. |

Special case:

| Site | Username behavior |
| --- | --- |
| `site3` | Maps to existing `initiator` user. The script expects `users.username='initiator'` to already exist. |
| Other sites | Maps to `client_<site>`, such as `client_site1`. |

### Client container is running but not connected

Checks:

```bash
docker logs -f duality-client-site1
docker logs -f duality-nvflare
```

Confirm host/site consistency:

```bash
grep DUALITY_NVFLARE_HOST standalone/.env.local
```

Client containers set `DUALITY_NVFLARE_HOST` to the site name inside the client container, because that value selects the site folder after unpacking the client startup kit. The server uses the standalone `DUALITY_NVFLARE_HOST` value from `.env.local`.

Recovery:

```bash
python3 main.py nvflare
python3 main.py rebuild nvflare
python3 main.py client --site site1
```

### Client creation fails with `PermissionError` on `job-results`

`python3 main.py client --site site1` creates `standalone/job-results/site1` on the host. If `standalone/job-results` was first created by the Docker daemon (it is bind-mounted into the backend and NVFlare containers), it is owned by root and the client utility fails with `PermissionError`. The standalone launcher (`ContainerBuilder._ensure_job_results_dir`, reached from every `main.py` path that runs `docker compose up`: `run`, `docker up`, `rebuild`, `update`) now creates the directory as the invoking user first, so a fresh checkout never hits this. On a checkout where the daemon already created it, reclaim it:

```bash
sudo chown -R $(id -un):$(id -gn) standalone/job-results
```

## Runtime Wheel Troubleshooting

### Published wheel update is needed

The `wheel` command does not run a local wheel builder. It rebuilds/relaunches the NVFlare service and redeploys already-running clients.

Published wheel updates are picked up by the submitted job bootstrap. To publish a new wheel version, tag the backend commit that contains the `apis/` or `workflows/` change:

```bash
git tag v1.2.7.13
git push origin v1.2.7.13
```

Confirm the package under:

```text
Project -> Deploy -> Package registry
```

Then submit a new NVFlare job. The job bootstrap installs or updates `duality_nvflare_lib` at job startup.

### Wheel command refuses to run

`python3 main.py wheel` requires:

- A running `nvflare` container in the `duality` Compose project.
- At least one running container named `duality-client-<site>`.

If either is missing, it exits with an error.

Recovery:

```bash
python3 main.py rebuild nvflare
python3 main.py client --site site1
python3 main.py wheel
```

### Runtime wheel install fails during job startup

The public standalone runtime is local-wheel-only. Server and client containers install
`duality_nvflare_lib-0+phase1.snapshot` from the wheel bundled with the checkout. The
submitted job wrappers only verify that the package is installed; they never query
GitLab or another package index.

If a job fails before analytics execution begins, check the server/client job logs for
`DualityWheelRuntime` messages and verify the installed version:

```bash
python -c "import importlib.metadata; print(importlib.metadata.version('duality_nvflare_lib'))"
```

The expected public snapshot version is `0+phase1.snapshot`. If it is missing or wrong,
rebuild/redeploy the standalone NVFlare/client containers so they reinstall the bundled
wheel.

### Verify active wheel in a container

The package can be checked in the Python environment used by the NVFlare process or job runtime:

```bash
python -c "import importlib.metadata; print(importlib.metadata.version('duality_nvflare_lib'))"
```

Inside the standalone NVFlare container:

```bash
docker exec -it duality-nvflare bash
. /opt/nvflare/.venv/bin/activate
python -c "import importlib.metadata; print(importlib.metadata.version('duality_nvflare_lib'))"
```

Inside a client container:

```bash
docker exec -it duality-client-site1 bash
. /opt/nvflare/.venv/bin/activate
python -c "import importlib.metadata; print(importlib.metadata.version('duality_nvflare_lib'))"
```

A newly submitted job should log the `DualityWheelRuntime` install/check output before importing wheel-backed modules.

## Update Troubleshooting

### `git pull` fails during update

The `update` command runs `git pull` only for source-backed services:

| Service | Git directory |
| --- | --- |
| `backend` | `../backend` |
| `frontend` | `../frontend` |

If `git pull` exits non-zero, the update command prints the failure and exits with status `2`. It does not continue to rebuild.

Recovery:

```bash
cd ../backend
git status
git pull
```

or:

```bash
cd ../frontend
git status
git pull
```

Resolve conflicts or local changes, then rerun:

```bash
python3 main.py update backend
```

## Safe Reset Procedures

### Restart stack without data loss

Preserves MySQL data volume, generated workspace, dist files, job results, and client contexts.

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local down --remove-orphans
docker compose -p duality --env-file ../.env.local up -d --build
```

### Rebuild backend only

Preserves MySQL data, frontend image, NVFlare workspace, clients, and job results.

```bash
python3 main.py rebuild backend
```

### Rebuild frontend only

Preserves backend, MySQL, NVFlare, clients, and data.

```bash
python3 main.py rebuild frontend
```

### Rebuild NVFlare only

Preserves MySQL data and frontend/backend containers. Does not automatically rebuild clients unless using option `9` or the `wheel` command.

```bash
python3 main.py rebuild nvflare
```

### Rebuild MySQL without deleting data

Preserves the `duality_mysql_data` volume.

```bash
python3 main.py rebuild mysql
```

### Rebuild MySQL and delete database data

Deletes the `duality_mysql_data` Docker volume. This requires reinitializing backend tables/default data and re-adding clients.

UI path:

1. Run `python3 main.py ui`.
2. Choose option `5` or option `1` when containers already exist.
3. Answer `y` to the MySQL wipe prompt.
4. Rebuild backend afterward if it was running during reset.

Direct path:

```bash
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local stop mysql
docker compose -p duality --env-file ../.env.local rm -f -s mysql
docker volume rm -f duality_mysql_data
cd ..
python3 main.py rebuild mysql backend
```

### Rebuild one client

Preserves main stack and other clients. Regenerates that site’s startup kit tar from the workspace, stages local datasource files, removes the existing `duality-client-<site>` container, then builds/starts the client.

```bash
python3 main.py client --site site1
```

### Clear one generated client container

```bash
docker stop duality-client-site1 2>/dev/null || true
docker rm -f duality-client-site1 2>/dev/null || true
python3 main.py client --site site1
```

### Clear generated client build artifacts

Generated client build/runtime artifacts live under `standalone/client_utils`, including:

- `injected_datasources/`
- temporary rendered Compose files matching `docker-compose.client-*.runtime.yml` while a build is running

Safe cleanup:

```bash
rm -rf standalone/client_utils/injected_datasources
rm -f standalone/client_utils/docker-compose.client-*.runtime.yml
python3 main.py client --site site1
```

### Clear NVFlare workspace/startup kits

Deletes generated NVFlare artifacts. Requires re-provisioning and rebuilding server/clients.

```bash
docker stop duality-client-site1 duality-client-site2 duality-client-site3 2>/dev/null || true
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local stop nvflare
cd ..
rm -rf nvflare_workspace
rm -rf dist
python3 main.py nvflare
python3 main.py rebuild nvflare
python3 main.py client --site site1
python3 main.py client --site site2
python3 main.py client --site site3
```

### Full local reset

Deletes main containers, the MySQL named volume, generated NVFlare workspace, generated startup kits, generated client artifacts, and client containers. It preserves source repos and env template files.

```bash
docker rm -f duality-client-site1 duality-client-site2 duality-client-site3 2>/dev/null || true
cd standalone/docker_stage
docker compose -p duality --env-file ../.env.local down --remove-orphans -v
cd ..
rm -rf nvflare_workspace
rm -rf dist
rm -rf client_utils/injected_datasources
rm -f client_utils/docker-compose.client-*.runtime.yml
python3 main.py
```

Do not delete raw test data or locally restored datasource files unless the intent is to rebuild those inputs from scratch.

## Troubleshooting Decision Tree

### UI will not open

1. Run `python3 --version` or `py --version`.
2. Run `python3 main.py ui` directly from the standalone directory.
3. Run `docker info`.
4. If Linux Docker permission fails, rerun `sudo ./LAUNCH_ME_LINUX.sh` or fix Docker group access.

### UI opens but all containers show `-`

1. Choose option `1`.
2. If option `1` fails, run:

```bash
python3 main.py codebase all
python3 main.py nvflare
```

3. Then rerun option `1`.

### MySQL shows failed

1. Check `docker logs -f duality-mysql`.
2. Confirm host tools use port `3307`.
3. Confirm backend uses `mysql:3306` internally.
4. If credentials or volume are stale, wipe `duality_mysql_data` and rebuild `mysql backend`.

### Backend is down or frontend cannot load data

1. Check backend logs.
2. Confirm MySQL is healthy.
3. Hit `/user/role` to initialize DB/tables.
4. Rebuild backend.
5. Rebuild frontend if the browser is calling the wrong backend URL.

### NVFlare jobs do not run

1. Confirm `duality-nvflare` is running.
2. Check `docker logs -f duality-nvflare`.
3. Confirm clients are running with `docker ps | grep duality-client`.
4. Check each client log.
5. Re-provision if host/IP or startup kits changed.
6. Rebuild NVFlare and clients.

### Client does not receive jobs

1. Run `python3 main.py clientdb --site <site>`.
2. Check MySQL UI status for registered clients.
3. Rebuild the client with `python3 main.py client --site <site>`.
4. Confirm datasource variables exist for that site.
5. Confirm startup kit/site names match the NVFlare project config.

### Wheel changes are not reflected

1. Confirm NVFlare and at least one client are running.
2. Run `python3 main.py wheel --no-cache`.
3. Check `pip show duality-nvflare-lib` inside NVFlare/client containers.
4. Rebuild individual clients if needed.

## Known Operational Limitations

- The public parser does not currently expose the internal `docker` command helper.
- `.env.local` is reseeded from `default.env.local` on `main.py` startup.
- The `wheel` command requires both NVFlare and at least one client container to be running before it will run.
- `site3` client registration depends on an existing `initiator` user row.
- Local JSON datasource files and the generated/provisioned NVFlare workspace may be intentionally omitted from a slim zip; restore or regenerate them before running workflows that require them.
