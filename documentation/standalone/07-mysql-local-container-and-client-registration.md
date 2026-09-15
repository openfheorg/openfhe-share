# MySQL Local Container and Client Registration

## Current Datasource Runtime Model

Standalone client utilities use datasource environment values as host-side staging paths for local JSON files. Those files are copied into client containers under `/data/client/`. The running client does not use retired `DUALITY_FHIR_BASE_CONFIG.json` or retired `DUALITY_NVFLARE_FHIR_BASE_CONFIG`; it requests its datasource from the NVFlare server, which resolves the value through backend user settings.

See `09-local-datasource-staging-and-runtime-lookup.md` for the full current flow.

## Files Covered

| File/Directory | Role |
| --- | --- |
| `mysql_stage/` | Host MySQL setup/check helper area used only when `DUALITY_DB_MODE=host`. |
| `mysql_stage/mysql_check_or_install.py` | Host MySQL connectivity/install script. Loads `.env.local`, checks TCP/auth, installs MySQL on supported host OSes, and reports status codes. |
| `docker_stage/docker-compose.yml` | Defines the Compose-managed MySQL service used by the normal standalone container mode. |
| `docker_stage/mysql.Dockerfile` | Builds the local MySQL image from `mysql:8.0.41` and applies server defaults. |
| `main.py` | Seeds `.env.local`, chooses container-vs-host DB behavior, starts/rebuilds MySQL through Docker Compose, and exposes `mysql`, `clientdb`, `client`, `rebuild`, and `ui` flows. |
| `default.env.local` | Baseline standalone environment file copied into `.env.local` at startup. Defines DB mode, MySQL host/port/user/password/database, root password, wipe toggle, and client datasource settings. |
| `.env.local` | Active environment file loaded by the orchestrator, Compose stack, MySQL stage, and client registration flow. |
| `utils/mysql_driver_utils.py` | Helper that finds or installs a Python MySQL driver into `.deps/python`. Used by client registration and MySQL status probing. |
| `client_utils/create_client.py` | Builds per-site NVFlare clients and ensures MySQL client/user mappings exist. |
| `client_utils/docker-compose.client-template.yml` | Per-client Compose template. Client containers are separate from the main MySQL/backend/frontend/NVFlare Compose stack. |
| `client_utils/client.Dockerfile` | Per-client Dockerfile. It copies staged local JSON files into the client image. |

## MySQL Role in Standalone

The standalone runtime needs MySQL so the backend can initialize and persist local application state.

In the normal local path, MySQL is started as a Docker Compose service named `mysql` with container name `duality-mysql`. The backend service waits for that MySQL service to become healthy, then connects through Compose DNS using host `mysql` and port `3306`.

The database supports backend behavior such as users, roles, projects, datasource assignments, datasource groups, workflow groups, NVFlare client records, job records, participation records, job status/history, and result metadata. The standalone scripts do not create the full backend schema directly. They start MySQL and backend, and the backend performs its own schema/default-data initialization when it starts and when initialization-triggering endpoints are called.

## Database Modes

The active database mode comes from `DUALITY_DB_MODE`.

| Mode | Behavior |
| --- | --- |
| `DUALITY_DB_MODE=container` | Default standalone mode. `python3 main.py mysql` is a no-op and prints that the Compose `mysql` service will be used. Docker Compose starts `duality-mysql`. |
| `DUALITY_DB_MODE=host` | Host-installed MySQL mode. `python3 main.py mysql` runs `mysql_stage/mysql_check_or_install.py`, which checks or installs host MySQL where supported. |

`default.env.local` sets:

```env
DUALITY_DB_MODE=container
```

`main.py` also forces an empty/missing `DUALITY_DB_MODE` in the seeded `.env.local` to `container`.

Important implementation detail: `main.py` calls `_ensure_env_local_seed()` on startup. That function copies `default.env.local` over `.env.local` each time the orchestrator starts, then resolves `DUALITY_NVFLARE_HOST` and fills `DUALITY_DB_MODE` if blank. Local DB setting changes should be made in `default.env.local` or the seeding behavior should be changed before relying on persistent edits to `.env.local`.

## Container MySQL Service

The main Compose stack defines the local database service in `docker_stage/docker-compose.yml`.

| Field | Value |
| --- | --- |
| Compose service | `mysql` |
| Container name | `duality-mysql` |
| Build context | `../..` from `docker_stage/` |
| Dockerfile | `standalone/docker_stage/mysql.Dockerfile` |
| Env file | `../.env.local` |
| Container port | `3306` |
| Host port | `3307` |
| Volume | `mysql_data:/var/lib/mysql` |
| Init SQL mount | `../mysql_stage/init:/docker-entrypoint-initdb.d` |
| Health check | `mysqladmin ping -h 127.0.0.1` |
| Health interval | `10s` |
| Health timeout | `5s` |
| Health retries | `5` |
| Restart policy | `unless-stopped` |

The host port mapping is:

```yaml
ports:
  - "3307:3306"
```

That means host tools connect to:

```text
127.0.0.1:3307
```

The backend container connects inside Compose to:

```text
mysql:3306
```

## MySQL Image

`docker_stage/mysql.Dockerfile` builds from:

```dockerfile
FROM mysql:8.0.41
```

It defines fallback defaults that Compose can override:

| Dockerfile ENV | Default |
| --- | --- |
| `MYSQL_ROOT_PASSWORD` | `rootpass` |
| `MYSQL_DATABASE` | `duality_local` |
| `MYSQL_USER` | `duality` |
| `MYSQL_PASSWORD` | `dualitypass` |

The Dockerfile writes `/etc/mysql/conf.d/charset.cnf` with:

```ini
[mysqld]
character-set-server=utf8mb4
collation-server=utf8mb4_0900_ai_ci
sql_mode=STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION
```

It also exposes `3306` and defines a matching `mysqladmin ping` health check.

The Dockerfile does not copy initialization SQL into the image. Runtime initialization is handled by the Compose mount:

```yaml
../mysql_stage/init:/docker-entrypoint-initdb.d
```

In the uploaded standalone package, `mysql_stage/init` is not present. That is acceptable for the current local flow because the backend is expected to initialize application tables/default rows.

## MySQL Environment Variables

`default.env.local` defines the local database values used by host tools, standalone scripts, and Docker Compose substitution.

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `DUALITY_DB_MODE` | `container` | `main.py` | Selects Compose MySQL vs host MySQL stage. |
| `DUALITY_MYSQL_HOST` | `localhost` | Host scripts/client registration/status checks | In container mode, this points host-side scripts at the host port. Compose overrides backend container host to `mysql`. |
| `DUALITY_MYSQL_PORT` | `3307` | Host scripts/client registration/status checks | Host-mapped port for the Compose MySQL service. Compose overrides backend container port to `3306`. |
| `DUALITY_MYSQL_USER` | `duality` | Compose, backend, scripts | Application DB user. |
| `DUALITY_MYSQL_PASSWORD` | `duality_pass` | Compose, backend, scripts | Application DB password. |
| `DUALITY_MYSQL_DB` | `duality_dev` | Compose, backend, scripts | Application database name. |
| `MYSQL_ROOT_PASSWORD` | `rootpass` | Compose/MySQL image | Root password used when the container initializes the MySQL data directory. |
| `DUALITY_DB_WIPE_ON_REBUILD` | `false` | `ContainerBuilder.rebuild()` | When true, `rebuild mysql` removes the named MySQL volume before rebuilding. |

Compose maps these values into MySQL’s official container entrypoint variables:

| Compose variable | Source |
| --- | --- |
| `MYSQL_DATABASE` | `${DUALITY_MYSQL_DB:-duality_local}` |
| `MYSQL_USER` | `${DUALITY_MYSQL_USER:-duality}` |
| `MYSQL_PASSWORD` | `${DUALITY_MYSQL_PASSWORD:-dualitypass}` |
| `MYSQL_ROOT_PASSWORD` | `${MYSQL_ROOT_PASSWORD:-rootpass}` |

Backend receives a Compose-specific connection block:

| Backend container variable | Value |
| --- | --- |
| `DUALITY_MYSQL_HOST` | `mysql` |
| `DUALITY_MYSQL_PORT` | `3306` |
| `DUALITY_MYSQL_USER` | `${DUALITY_MYSQL_USER:-duality}` |
| `DUALITY_MYSQL_PASSWORD` | `${DUALITY_MYSQL_PASSWORD:-dualitypass}` |
| `DUALITY_MYSQL_DB` | `${DUALITY_MYSQL_DB:-duality_local}` |

This split is intentional. Host-side Python scripts use `localhost:3307`, while the backend container uses `mysql:3306`.

## Default Container Flow

Running the default standalone setup through `python3 main.py` does the database work in this order:

1. `_ensure_env_local_seed()` copies `default.env.local` to `.env.local`.
2. `DUALITY_NVFLARE_HOST` is resolved from `auto` or blank to the detected local IP.
3. `.env.local` is loaded into the current process.
4. `_run_full_pipeline()` calls `cmd_mysql()`.
5. `cmd_mysql()` checks `DUALITY_DB_MODE`.
6. If the mode is `container`, host MySQL setup is skipped.
7. The codebase stage verifies local backend/frontend source directories.
8. If standalone containers already exist, `ContainerBuilder.rebuild()` rebuilds `mysql`, `backend`, `frontend`, and `nvflare`.
9. If standalone containers do not exist, the internal `cmd_docker()` path provisions NVFlare and runs the full Compose build/up flow.
10. Compose starts MySQL.
11. Compose waits for the MySQL health check before starting backend.
12. Backend starts and initializes the database schema/default rows through backend startup/endpoint behavior.
13. When the pipeline is run from the UI, option `1` then calls `_seed_default_clients_via_backend()` so the default client rows exist before the dashboard reports registered clients.

## Backend Database Initialization

The standalone MySQL container only creates the database and database user through the official MySQL image entrypoint.

Application tables are expected to be created by the backend. `client_utils/create_client.py` intentionally calls backend before client registration:

```text
POST http://localhost:8000/user/role
{"username":"client"}
```

That call is made by `ping_backend_login()` to trigger/verify backend database initialization before the script inserts client mappings. The function returns `True` only for an HTTP `200` response, and it accepts `quiet=True` to suppress its own per-attempt output for callers that poll it and report an aggregate outcome.

The warning path is non-fatal. If the backend cannot be contacted, the script prints:

```text
Could not contact backend at http://localhost:8000/user/role. Try backend rebuild
```

Then it still attempts MySQL registration. If the backend tables do not exist yet, registration fails when the insert/select statements hit missing tables.

### Default Client Seeding From the Launcher

Backend database initialization also inserts the default clients. In the `LOCAL` and `DEV` environments the backend adds `site1`, `site2`, and `site3` to `nvflare_clients` while its connection provider initializes, which happens on the backend's first database-touching request.

The launcher's status panel queries MySQL directly, so it never causes that first request. On a fresh build the dashboard would therefore show no registered clients even though the stack is healthy. `main.py._seed_default_clients_via_backend()` closes that gap:

1. It calls `ping_backend_login(quiet=True)` to `POST /user/role`.
2. It re-probes MySQL for `nvflare_clients.client_name` values.
3. It retries up to `10` times with `1.5` seconds between attempts while the backend is still starting.

The UI calls it after a successful full pipeline (option `1`) and before launching all registered clients (option `6` with an empty site prompt). Clients registered this way still go through `ensure_client_registered()` when their containers are created.

## Host MySQL Stage

The host MySQL path lives in `mysql_stage/mysql_check_or_install.py` and is only used when `DUALITY_DB_MODE=host`.

The script behavior is:

1. Load `.env.local` from the repo root.
2. Install/check Python MySQL dependencies: `mysqlclient` and `PyMySQL`.
3. Read connection settings:
   - `DUALITY_MYSQL_HOST`, default `localhost`
   - `DUALITY_MYSQL_PORT`, default `3306`
   - `DUALITY_MYSQL_USER`
   - `DUALITY_MYSQL_PASSWORD`
4. Check TCP reachability using `socket.create_connection()`.
5. Try auth with `MySQLdb` or `pymysql`.
6. If TCP and auth both work, return `0`.
7. If TCP works but auth fails, return `2`.
8. If TCP fails, attempt host installation.
9. After installation, wait up to 180 seconds for `127.0.0.1:3306`.
10. Retry authentication.

Supported host install flows:

| OS | Behavior |
| --- | --- |
| macOS / Darwin | Requires Homebrew. Runs `brew install mysql@8.0`, then `brew services start mysql@8.0`. |
| Windows | Requires Chocolatey. If Chocolatey is missing, imports `utils.windows_choco_installer.install_chocolatey()` and attempts installation. Then runs `choco install -y mysql` and attempts to start `MySQL80` or `mysql` services. |
| Linux/other | Not supported by this script. It exits with an unsupported OS error. |

Return codes from the host stage:

| Return code | Meaning |
| --- | --- |
| `0` | MySQL reachable and auth succeeded, or install succeeded and auth succeeded. |
| `1` | Missing `.env.local` or unsupported install prerequisite/OS path. |
| `2` | MySQL TCP reachable but authentication failed. |
| `3` | MySQL did not become reachable after install/start. |
| `4` | MySQL installed/reachable but authentication failed after install. |

Container mode is preferred for the standalone package because it avoids host MySQL installer differences and keeps the database state tied to the Compose project volume.

## MySQL Driver Utility

`utils/mysql_driver_utils.py` is used when standalone Python needs to talk directly to MySQL, including client registration and UI/status probing.

`ensure_mysql_driver()` does the following:

1. Creates `.deps/python` under the standalone repo.
2. Adds that directory to Python’s site path with `site.addsitedir()`.
3. Tries to import `mysql.connector`.
4. If that fails, tries to import `pymysql`.
5. If neither driver is available, runs:

```text
python -m pip install --upgrade --target <standalone>/.deps/python mysql-connector-python PyMySQL
```

6. Adds `.deps/python` again.
7. Retries `mysql.connector`, then `pymysql`.
8. Returns `(module, driver_name)` or `(None, None)`.

It does not perform database retries. It only handles local dependency availability.

## Client Registration Commands

The standalone exposes client registration through:

```bash
python3 main.py clientdb --site <site>
```

The full client container flow also performs registration automatically:

```bash
python3 main.py client --site <site>
```

For `clientdb`, `main.py` does the following:

1. Requires `--site`.
2. Loads the selected env file or `.env.local`.
3. Calls `ping_backend_login()` to hit backend `/user/role`.
4. Calls `ensure_client_registered(site)`.
5. Prints the ensured `client_id` and `user_id`.

For `client`, `client_utils/create_client.py` does the following before building the container:

1. Loads `.env.local` without overwriting already-set process environment variables.
2. Locates or creates the requested client startup kit.
3. Collects datasource configuration for the site.
4. Calls `ping_backend_login()`.
5. Calls `ensure_client_registered(site)`.
6. Stages local datasource JSON files into the client build context.
7. Stages local JSON datasource files.
8. Starts the client container without baking in `duality_nvflare_lib`; submitted jobs install/update the wheel at runtime.
9. Builds/starts the per-site client container.

## Tables Touched During Client Registration

`ensure_client_registered(site)` directly touches exactly these MySQL tables:

| Table | Operation | Purpose |
| --- | --- | --- |
| `nvflare_clients` | `SELECT` joined to `users` | Checks whether `client_name = <site>` already has a user mapping. |
| `defined_roles` | `INSERT ... ON DUPLICATE KEY UPDATE` | Ensures the `client` role exists for non-`site3` clients. |
| `users` | `INSERT ... ON DUPLICATE KEY UPDATE` for non-`site3`; `SELECT` for `site3` | Ensures or reuses the user account mapped to the NVFlare client. |
| `nvflare_clients` | `INSERT ... ON DUPLICATE KEY UPDATE` | Ensures the NVFlare client record points at the correct user. |

No datasource, project, workflow group, job, or participation tables are inserted by `clientdb` or by `ensure_client_registered()`.

## Site-to-User Mapping

Site naming behavior is hardcoded in `client_utils/create_client.py`.

| Site | Username behavior |
| --- | --- |
| `site3` | Uses existing backend user `initiator`. If `initiator` is missing from `users`, registration fails. |
| Any other site | Uses username `client_<site>`, such as `client_site1` or `client_site2`. |

For non-`site3` sites, the script ensures role `client` exists in `defined_roles`, then inserts or updates the `users` row with:

| Column | Value |
| --- | --- |
| `username` | `client_<site>` |
| `password_hash` | `DISABLED` |
| `role_id` | ID of `defined_roles.name = 'client'` |

It then inserts or updates `nvflare_clients` with:

| Column | Value |
| --- | --- |
| `client_name` | CLI site value, such as `site1` |
| `user_id` | Ensured/resolved user ID |
| `description` | `Auto-created for <site>` |

The SQL uses `ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)` so the function can return the existing row ID when the row already exists.

## Client Datasource Configuration

Client datasource values are read from environment variables as host-side staging values. Backend runtime datasource values are stored in `users_fhir_source_by_project` and resolved through `/clients/datasource/source`.

The primary pattern is:

```text
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>=<value>
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>_<DATASOURCE_GROUP_ID>=<value>
```

Examples from `default.env.local`:

```env
DUALITY_CLIENT_SITE3_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part1.json
DUALITY_CLIENT_SITE1_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part2.json
DUALITY_CLIENT_SITE2_DATASOURCE_1=nvflare_stage/data/Survivability_FHIR_Data_part3.json

DUALITY_CLIENT_SITE3_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_training_bundle.json
DUALITY_CLIENT_SITE1_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site1.json
DUALITY_CLIENT_SITE2_DATASOURCE_2_1=nvflare_stage/data/Biomarker_MSKChord_FHIR_Data_testing_bundle_site2.json
```

Parsing behavior:

| Pattern | Parsed as |
| --- | --- |
| `DUALITY_CLIENT_SITE1_DATASOURCE_1` | Project `1`, ungrouped datasource. |
| `DUALITY_CLIENT_SITE1_DATASOURCE_2_1` | Project `2`, datasource group `1`. |
| `DUALITY_CLIENT_SITE1_DATASOURCE_2_1` | Project `2`, datasource group `1` (MSKChord). |
| `DUALITY_CLIENT_SITE1_DATASOURCE` | Legacy fallback. Treated as project `1`. |

Grouped and ungrouped datasource entries cannot be mixed for the same project/site. If both styles are detected for one project, the script exits with code `18`.

Runtime datasource handling:

- FHIR URL values are stored in backend user datasource settings and returned to clients at job runtime.
- Local JSON env values are host-side staging paths only.
- Local JSON files are copied into `client_utils/injected_datasources/` before the Docker build.
- The client Dockerfile copies staged JSON files into `/data/client/`.
- Duplicate local datasource filenames for the same client are rejected with exit code `17`.
- The backend local runtime datasource value should be `/data/client/<filename>.json`.

## Local Datasource Values in MySQL

The local backend stores datasource values that are valid inside the running client container. For local JSON biomarker data, those values use `/data/client/<filename>.json`.

The env values used by `client_utils/create_client.py` are host-side staging paths such as `nvflare_stage/data/<filename>.json`. Those staging paths are only used to copy JSON files into the client image.

At runtime:

```text
users_fhir_source_by_project.source
  -> /data/client/<filename>.json

client job
  -> asks server for datasource

server
  -> calls /clients/datasource/source

client analytics code
  -> reads /data/client/<filename>.json
```

## Client Container Database Relationship

Client containers do not connect to MySQL for registration. The host-side Python script performs registration before the client container is built and started.

The client container receives local JSON datasource files through `client_utils/client.Dockerfile`:

```dockerfile
COPY injected_datasources/ /data/client/
```

Datasource selection itself is resolved at job runtime through the NVFlare server and backend `/clients/datasource/source`.

The client Compose template starts containers named:

```text
duality-client-<site>
```

The client startup kit is mounted at:

```text
/kits/client_startup_kit.tar
```

The generated client container service is rendered as:

```text
client-<site>
```

The default client Compose project is:

```text
duality-client
```

## Common MySQL Operations

### Start the full local stack

```bash
python3 main.py
```

This starts MySQL through Compose in container mode and starts the rest of the local services.

### Check host MySQL stage behavior

```bash
python3 main.py mysql
```

In the default container mode, this prints that host MySQL is skipped. In host mode, it checks/install host MySQL.

### Rebuild MySQL without wiping data

```bash
python3 main.py rebuild mysql
```

This rebuilds and restarts only the MySQL service. Existing data remains in the named Docker volume unless wipe behavior is enabled.

### Rebuild MySQL and backend after a reset prompt from UI

```bash
python3 main.py ui
```

Choose the MySQL rebuild option and answer the wipe prompt as needed. The UI warns that if backend is running during MySQL reset, backend should be rebuilt next to re-establish the connection.

### Register a client row

```bash
python3 main.py clientdb --site site1
python3 main.py clientdb --site site2
python3 main.py clientdb --site site3
```

### Build/start a client and register it

```bash
python3 main.py client --site site1
```

### Connect from host tools

Use these values in MySQL Workbench, CLI, or another host client:

| Field | Value |
| --- | --- |
| Host | `127.0.0.1` or `localhost` |
| Port | `3307` |
| User | `duality` |
| Password | `duality_pass` |
| Database | `duality_dev` |

Example:

```bash
mysql -h 127.0.0.1 -P 3307 -u duality -p duality_dev
```

### Connect from another Compose service

Inside the main Compose network, use:

| Field | Value |
| --- | --- |
| Host | `mysql` |
| Port | `3306` |
| Database | `${DUALITY_MYSQL_DB}` |
| User | `${DUALITY_MYSQL_USER}` |
| Password | `${DUALITY_MYSQL_PASSWORD}` |

## Preserving Local Data Across Rebuilds

MySQL data is stored in the Compose named volume:

```text
duality_mysql_data
```

The volume name comes from the Compose project name `duality` plus the declared volume `mysql_data`.

These operations preserve database data:

```bash
python3 main.py rebuild mysql
python3 main.py rebuild backend
python3 main.py rebuild frontend
python3 main.py
```

Data is preserved as long as the MySQL volume is not removed.

## Safe Local Database Reset

Use this when the local schema/data should be recreated from scratch.

1. Stop any active standalone/client work.
2. Remove or rebuild the MySQL container with volume wipe.
3. Rebuild backend so it reconnects cleanly and initializes schema/default rows.
4. Re-register clients with `clientdb` or rebuild clients with `client`.

The code-supported reset path is through `ContainerBuilder.wipe_mysql_storage()`, which:

1. Stops the `mysql` service.
2. Removes the `mysql` container.
3. Removes the named volume `duality_mysql_data`.

The UI exposes this through the full pipeline and MySQL rebuild prompts.

Manual equivalent:

```bash
cd standalone/docker_stage
docker compose -p duality down --remove-orphans
docker volume rm -f duality_mysql_data
cd ..
python3 main.py
python3 main.py clientdb --site site1
python3 main.py clientdb --site site2
python3 main.py clientdb --site site3
```

If backend was running while MySQL was wiped, rebuild backend:

```bash
python3 main.py rebuild backend
```

## Troubleshooting

### Port `3307` is already in use

The MySQL service maps host `3307` to container `3306`. If another process is using host `3307`, the Compose service will fail to start.

Options:

- Stop the process using host port `3307`.
- Change the Compose port mapping in `docker_stage/docker-compose.yml`.
- Keep `DUALITY_MYSQL_PORT` aligned with the host-side port used by scripts.

### MySQL container is unhealthy

Check logs:

```bash
cd standalone/docker_stage
docker compose -p duality logs mysql
```

Common causes:

- Bad or changed initialization credentials with an existing volume.
- Existing `duality_mysql_data` volume initialized with different values.
- Port conflict.
- MySQL startup still in progress.

When credentials changed after the volume was already initialized, reset the volume or restore the previous credentials.

### Bad credentials from host scripts

Host-side scripts use `DUALITY_MYSQL_HOST`, `DUALITY_MYSQL_PORT`, `DUALITY_MYSQL_USER`, `DUALITY_MYSQL_PASSWORD`, and `DUALITY_MYSQL_DB` from `.env.local`/`default.env.local`.

For default container mode, those should match:

```env
DUALITY_MYSQL_HOST=localhost
DUALITY_MYSQL_PORT=3307
DUALITY_MYSQL_USER=duality
DUALITY_MYSQL_PASSWORD=duality_pass
DUALITY_MYSQL_DB=duality_dev
```

If the MySQL volume was initialized with different credentials, reset the volume or restore the matching values.

### `clientdb` fails with missing tables

`clientdb` directly inserts/selects from `defined_roles`, `users`, and `nvflare_clients`. Those tables must already exist.

Recovery:

```bash
python3 main.py rebuild backend
python3 main.py clientdb --site site1
```

If the backend still cannot initialize tables, inspect backend logs:

```bash
cd standalone/docker_stage
docker compose -p duality logs backend
```

### `site3` registration fails

`site3` maps to the existing backend user `initiator`. The script does not create `initiator`. It fails if that user is missing.

Recovery:

1. Start/rebuild backend.
2. Confirm backend default-data initialization completed.
3. Retry:

```bash
python3 main.py clientdb --site site3
```

### Python MySQL driver is missing

`utils/mysql_driver_utils.py` attempts to install `mysql-connector-python` and `PyMySQL` into:

```text
standalone/.deps/python
```

If installation fails, install one manually in the active Python environment or fix local pip/network access, then retry `clientdb`.

### Docker permission denied on Linux

`main.py` detects Docker daemon permission failures and prints that the Linux launcher may need to be rerun with `sudo` if Docker requires elevated access.

The underlying issue is access to `/var/run/docker.sock`.

### Host MySQL install fails

Host mode only has explicit installer paths for macOS and Windows.

- macOS requires Homebrew.
- Windows requires Chocolatey or permission to install Chocolatey.
- Linux is not supported by `mysql_stage/mysql_check_or_install.py`.

For standalone local development, switch back to:

```env
DUALITY_DB_MODE=container
```

and use the Compose-managed MySQL service.
