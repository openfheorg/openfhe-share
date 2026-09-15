# Main Orchestrator CLI

## Current Datasource Runtime Model

Standalone client utilities use datasource environment values as host-side staging paths for local JSON files. Those files are copied into client containers under `/data/client/`. The running client does not use retired `DUALITY_FHIR_BASE_CONFIG.json` or retired `DUALITY_NVFLARE_FHIR_BASE_CONFIG`; it requests its datasource from the NVFlare server, which resolves the value through backend user settings.

See `09-local-datasource-staging-and-runtime-lookup.md` for the full current flow.

## Files Covered

| File | Role |
| --- | --- |
| `main.py` | Main standalone CLI and orchestration entrypoint. |
| `LAUNCH_ME_LINUX.sh` | Linux launcher for the standalone interactive UI. |
| `LAUNCH_ME_MAC.command` | macOS launcher for the standalone interactive UI. |
| `LAUNCH_ME_WIN.bat` | Windows launcher for the standalone interactive UI. |
| `requirements.txt` | Python package requirements used by the standalone orchestration code. |
| `utils/environment_utils.py` | Shared `.env.local` loader used by the orchestrator. |
| `utils/ip_utils.py` | Local IPv4 detection helper used when seeding `DUALITY_NVFLARE_HOST`. |
| `utils/mysql_driver_utils.py` | MySQL driver selection helper used by UI status checks and client registration. |
| `utils/wheel_utils.py` | Utility module retained in the standalone source tree. The current local container flow does not bake `duality_nvflare_lib` into server/client images. |
| `codebase_stage/establish_code_base.py` | Source tree verification stage for sibling `backend` and `frontend` directories. |
| `mysql_stage/mysql_check_or_install.py` | Host MySQL check/install stage used only when `DUALITY_DB_MODE=host`. |
| `nvflare_stage/nvflare_install_and_provision.py` | NVFlare install/provisioning stage and admin startup kit tar generation. |
| `docker_stage/container_builder.py` | Docker Compose build/start/rebuild/update helper used by the orchestrator. |
| `docker_stage/docker-compose.yml` | Compose definition for the local MySQL, backend, frontend, and NVFlare services. |
| `client_utils/create_client.py` | Per-site client startup kit packaging, datasource staging, database registration, and client container creation. |
| `client_utils/docker-compose.client-template.yml` | Compose template rendered into a temporary per-site client service file. |

## CLI Role

`main.py` is the standalone control script for the local SHARE/Duality development stack.

It coordinates environment seeding, environment loading, host/container MySQL behavior, backend/frontend source verification, NVFlare workspace provisioning, Docker Compose operations, client registration, per-site client container creation, NVFlare runtime redeployment, and the interactive status/rebuild dashboard.

The script can be run directly:

```bash
python3 main.py
```

It can also be launched through the OS-specific scripts:

```bash
./LAUNCH_ME_LINUX.sh
./LAUNCH_ME_MAC.command
LAUNCH_ME_WIN.bat
```

The launchers call the interactive UI command rather than the no-argument full setup flow.

## Repository Layout Assumptions

The standalone directory is expected to sit beside the main application source trees:

```text
<workspace>/
  backend/
  frontend/
  standalone/
    main.py
    .env.local
    docker_stage/
    client_utils/
    nvflare_stage/
```

`codebase_stage/establish_code_base.py` checks only for directory existence. It expects:

| Source | Expected Path |
| --- | --- |
| Backend | `<workspace>/backend` |
| Frontend | `<workspace>/frontend` |

If the requested source directory is missing, the codebase stage returns `100`. It does not clone repositories or switch branches.

## Environment File Behavior

The orchestrator uses `.env.local` in the standalone root unless `--env-file` is passed.

At startup, `main.py` always calls `_ensure_env_local_seed()` before executing the selected command. That function:

1. Requires `default.env.local` to exist.
2. Copies `default.env.local` over `.env.local`.
3. Reads `DUALITY_NVFLARE_HOST` from the newly seeded `.env.local`.
4. If `DUALITY_NVFLARE_HOST` is missing, blank, or `auto`, detects a local IPv4 address and writes it into `.env.local`.
5. Ensures `DUALITY_DB_MODE=container` is present when the key is absent or blank.

`utils/environment_utils.load_env_file()` then loads simple `KEY=VALUE` lines into `os.environ`. It ignores blank lines and comments and uses `os.environ.setdefault`, so values already present in the process environment are not overwritten by the file loader.

`utils/ip_utils.get_ip()` detects the local IP by trying, in order:

1. UDP socket routing toward `8.8.8.8` and `1.1.1.1`.
2. Linux `ip route get 8.8.8.8` parsing.
3. macOS `ipconfig getifaddr en0` and `en1`.
4. `socket.gethostbyname(socket.gethostname())`.
5. Final fallback to `127.0.0.1`.

The helper rejects `0.0.0.0` and `127.0.0.1` during normal detection, but still returns `127.0.0.1` as the last-resort fallback.

## Default Command Behavior

Running `python3 main.py` with no subcommand starts the default full local setup flow.

The exact flow is:

1. If the first CLI argument is not the special early-dispatch `client` command, build the main `argparse` parser.
2. Seed `.env.local` from `default.env.local`.
3. Resolve the env file path. If `--env-file` was supplied, use it. Otherwise use `<standalone>/.env.local` when present.
4. Load the env file into the process environment. On hosts that expose `os.getuid`, also seed `DUALITY_HOST_UID` and `DUALITY_HOST_GID` from `os.getuid()`/`os.getgid()` with `setdefault`, so Compose can pass the host identity into the containers.
5. Because no subcommand was provided, call `_run_full_pipeline(args, env_file_path)`.
6. `_run_full_pipeline()` first verifies Docker access with `docker ps`.
7. It checks whether any existing container name starts with `duality-`.
8. It runs `cmd_mysql()`.
9. `cmd_mysql()` skips host MySQL setup when `DUALITY_DB_MODE=container`; otherwise it runs `mysql_stage/mysql_check_or_install.py`.
10. It runs `cmd_codebase()` with `only=all`, verifying both sibling source trees.
11. If existing `duality-*` containers are present, it creates a `ContainerBuilder` and rebuilds `mysql`, `backend`, `frontend`, and `nvflare`.
12. If MySQL wipe was requested by the UI path, the rebuild can remove the `duality_mysql_data` volume before rebuilding MySQL. The no-argument path passes `wipe_mysql=False`.
13. After rebuilding the main services, it redeploys any currently running client containers whose names begin with `duality-client-`.
14. If no existing `duality-*` containers are present, it constructs an internal Docker `run` action and calls `cmd_docker()`.
15. `cmd_docker()` runs NVFlare provisioning for the `run` action, loads the env file again, creates a `ContainerBuilder`, and calls `builder.run_all()`.
16. `builder.run_all()` runs Compose `down --remove-orphans`, writes the frontend `.env.production.local`, builds the stack, and starts the stack.

The main stack consists of the Compose services `mysql`, `backend`, `frontend`, and `nvflare`.

## Argparse Commands

The current `argparse` parser registers these commands:

| Command | Arguments | Purpose |
| --- | --- | --- |
| `codebase` | Optional positional `only` with choices `backend`, `frontend`, `all`; default `all` | Verify sibling source directories. |
| `mysql` | None | Run host MySQL check/install unless `DUALITY_DB_MODE=container`, in which case the command is a no-op. |
| `nvflare` | None | Install/use NVFlare and provision the local workspace when needed; always repack the admin startup kit tar. |
| `rebuild` | Positional `services...` with choices `frontend`, `backend`, `nvflare`, `mysql`; optional `--no-cache` | Rebuild selected Compose services and restart them. |
| `update` | Positional `services...` with choices `frontend`, `backend`; optional `--no-cache` | Run `git pull` for selected source repos, then rebuild/restart those services. |
| `wheel` | Optional `--no-cache` | Rebuild/relaunch the `nvflare` service and redeploy already-running client containers. The submitted NVFlare job installs or updates `duality_nvflare_lib` at job runtime. |
| `clientdb` | Required `--site <site>` | Ensure a database user/client mapping exists for the site. |
| `client` | Required mutually exclusive `--site <site>` or `--tar-file <path>`; optional `--tar-kit`, `--compose-file`, `--project` | Create a client startup kit tar or build/start a per-site client container. |
| `ui` | None | Open the interactive status dashboard and rebuild menu. |

A global `--env-file <path>` argument is also available. It defaults to `.env.local` in the standalone root when omitted.

## Docker Command Status

`main.py` contains a `cmd_docker()` implementation, but the current `argparse` setup does not register a `docker` subcommand. The Docker action behavior is still used internally by the no-argument default setup flow, which constructs an internal action namespace with `action="run"`.

The implemented Docker action values inside `cmd_docker()` are:

| Action | ContainerBuilder Method | Behavior |
| --- | --- | --- |
| `build` | `build()` | Build all or selected Compose services. Runs NVFlare provisioning first. |
| `up` | `up()` | Start all or selected Compose services. Runs NVFlare provisioning first. |
| `down` | `down()` | Stop/remove the Compose stack; can remove volumes when requested. |
| `logs` | `logs()` | Show Compose logs; can follow logs. |
| `ps` | `ps()` | Show Compose project containers. |
| `pull` | `pull()` | Run Compose pull for all or selected services. |
| `run` | `run_all()` | Reset the Compose project, build, and start the stack. Runs NVFlare provisioning first. |

The implemented action flags expected by `cmd_docker()` are `services`, `no_cache`, `attach`, `no_build`, `volumes`, `follow`, and `env_file`. These are used by the internal default flow, but no public `docker` parser currently exposes them.

## Main Docker Compose Services

`docker_stage/docker-compose.yml` defines these services:

| Service | Container Name | Host Port(s) | Notes |
| --- | --- | --- | --- |
| `mysql` | `duality-mysql` | `3307:3306` | Compose-managed MySQL with persistent named volume `mysql_data`; initialized from `../mysql_stage/init` when SQL files are present. |
| `backend` | `duality-backend` | `8000:8000` | FastAPI backend container; depends on healthy MySQL and started NVFlare; mounts `../nvflare_workspace` and `../job-results`. |
| `frontend` | `frontend` | `3000:3000` | Frontend container; uses `NEXT_PUBLIC_BACKEND_URL=http://localhost:8000`; depends on backend. |
| `nvflare` | `duality-nvflare` | `${DUALITY_NVFLARE_FED_PORT:-8002}:8002`, `${DUALITY_NVFLARE_ADMIN_PORT:-8003}:8003`, `8004:8004` | NVFlare server container; mounts `../nvflare_workspace`. |

The Compose project name used by `ContainerBuilder` is `duality`. This means the named MySQL volume is `duality_mysql_data`.

## ContainerBuilder Behavior

`ContainerBuilder` uses `<standalone>/docker_stage` as the Compose project directory and `<standalone>/docker_stage/docker-compose.yml` as the Compose file.

Before Compose operations, it checks:

1. Docker or docker-compose is available on `PATH`.
2. `docker info` succeeds, proving the daemon is reachable.
3. The Compose file exists.

It prefers `docker compose` when `docker` is available and falls back to `docker-compose` only when `docker` is not available.

For source-backed services, it verifies source directories before build/up/pull/rebuild/update:

| Service | Source Check |
| --- | --- |
| `backend` | `<workspace>/backend` must exist. |
| `frontend` | `<workspace>/frontend` must exist. |
| `mysql` | No sibling source directory required. |
| `nvflare` | No sibling source directory required. |

When frontend is part of a build/up/rebuild/update action, the builder writes `<workspace>/frontend/.env.production.local` with:

```text
REACT_APP_API_BASE=<REACT_APP_API_BASE or NEXT_PUBLIC_BACKEND_URL or http://localhost:8000>
REACT_APP_BUILD_FLAVOR=<REACT_APP_BUILD_FLAVOR or local>
```

The standalone Docker build stages the bundled `duality_nvflare_lib` snapshot wheel from `standalone/wheels/` into `docker_stage/local_wheels/` (NVFlare server) and `client_utils/local_wheels/` (clients). The NVFlare server and client images install fixed runtime dependencies such as NVFlare, OpenFHE, scientific Python packages, and OQS support, then install that wheel. The submitted NVFlare job template only verifies the wheel is present; it never contacts a package registry.

## Rebuild Command

Usage:

```bash
python3 main.py rebuild <service> [<service> ...] [--no-cache]
```

Supported service names are:

| Service | Rebuild Behavior |
| --- | --- |
| `frontend` | Verifies frontend source, writes `.env.production.local`, builds `frontend`, removes the old container, and starts it with `up -d --no-deps frontend`. |
| `backend` | Verifies backend source, builds `backend`, removes the old container, and starts it with `up -d --no-deps backend`. |
| `nvflare` | Builds `nvflare`, removes the old container, and starts it with `up -d --no-deps nvflare`. The runtime wheel is resolved by submitted jobs, not baked into the image. |
| `mysql` | Builds `mysql`, removes the old container, and starts it with `up -d --no-deps mysql`. |

The rebuild command does not include client containers. Client containers are handled by the `client` command, the UI client options, or automatic redeploy during the full pipeline/wheel flow.

The rebuild implementation uses `docker compose build`, then `docker compose rm -f -s`, then `docker compose up -d --no-deps`. Because `--no-deps` is used on the final `up`, dependency containers are not restarted by that final step.

MySQL data is preserved by default. MySQL storage is wiped only when both of these are true:

1. `mysql` is included in the services being rebuilt.
2. Either the caller explicitly passes `wipe_mysql=True` internally, or `DUALITY_DB_WIPE_ON_REBUILD` is set to `1`, `true`, or `yes`.

When wiping is enabled, the builder stops/removes the MySQL container and removes the named Docker volume:

```text
duality_mysql_data
```

The interactive UI asks for confirmation before setting `wipe_mysql=True` for full reset/rebuild or MySQL rebuild.

## Update Command

Usage:

```bash
python3 main.py update <frontend|backend> [frontend|backend] [--no-cache]
```

Supported service names are only:

| Service | Source Directory |
| --- | --- |
| `frontend` | `<workspace>/frontend` |
| `backend` | `<workspace>/backend` |

For each selected service, the update command runs:

```bash
git pull
```

inside that service's source directory.

If any `git pull` exits non-zero, the update command prints an error and returns `2` without continuing to the Compose build/restart portion.

After successful pulls, it follows the same rebuild pattern as `rebuild`:

1. Write frontend `.env.production.local` if frontend is selected.
2. Run `docker compose build` with `--no-cache` when requested.
3. Run `docker compose rm -f -s` for the selected services.
4. Run `docker compose up -d --no-deps` for the selected services.

Frontend and backend can be updated independently or together.

## Wheel Command

Usage:

```bash
python3 main.py wheel [--no-cache]
```

The command name remains `wheel`, but the current standalone behavior is a redeploy of the already-running NVFlare server/client runtime. It does not build `duality_nvflare_lib` locally and does not copy a wheel into Docker build contexts.

The exact flow is:

1. Create a `ContainerBuilder` for the main Compose project.
2. Resolve/load the env file.
3. Check the main Compose project status for the `nvflare` service.
4. Exit with an error if the NVFlare container is not running.
5. Find running client containers by scanning `docker ps` names beginning with `duality-client-`.
6. Exit with an error if no running client containers are found.
7. Rebuild the `nvflare` service through `builder.rebuild(services=["nvflare"], no_cache=<flag>)`.
8. Redeploy each running client site by invoking `python main.py client --site <site>`.

At job execution time, the submitted NVFlare job template requires the locally installed `duality_nvflare_lib` snapshot wheel and imports the wheel-backed API/workflow code from it; it never contacts a package registry.

## ClientDB Command

Usage:

```bash
python3 main.py clientdb --site <site>
```

The `--site` value must be a non-empty string such as `site1`, `site2`, or `site3`.

The command:

1. Loads the env file.
2. Calls backend `/user/role` with payload `{"username": "client"}` to encourage backend DB/table initialization.
3. Connects to MySQL using `DUALITY_MYSQL_HOST`, `DUALITY_MYSQL_PORT`, `DUALITY_MYSQL_USER`, `DUALITY_MYSQL_PASSWORD`, and `DUALITY_MYSQL_DB`.
4. Ensures a database mapping exists between the NVFlare site name and a backend user.

Site-to-user mapping:

| Site | Username Behavior |
| --- | --- |
| `site3` | Maps to existing user `initiator`. If that user does not exist, registration fails. |
| Any other site | Maps to username `client_<site>`. |

For non-`site3` sites, `ensure_client_registered()` also ensures role `client` exists in `defined_roles`, creates/updates the `users` row with password hash `DISABLED`, and creates/updates the `nvflare_clients` row.

The database inserts use `ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)` style behavior, so running the command again reuses or updates the existing record rather than creating a duplicate.

This command does not insert project or datasource rows. It only ensures role/user/client mapping records.

## Client Command

Usage with a site name:

```bash
python3 main.py client --site <site>
```

Usage with an existing tar:

```bash
python3 main.py client --tar-file <path-to-client_siteX_startup_kit.tar>
```

Additional options:

| Option | Behavior |
| --- | --- |
| `--tar-kit` | With `--site`, only create `dist/client_<site>_startup_kit.tar` and optionally ensure the MySQL client record. It does not build/start the client container. |
| `--compose-file <path>` | Override the client Compose template. Defaults to `<standalone>/client_utils/docker-compose.client-template.yml`. |
| `--project <name>` | Override the client Compose project name. Defaults to `duality-client`. |
| `--env-file <path>` | Load a specific env file instead of the default `.env.local`. |
| `--no-cache` | Build the client image from scratch (`docker compose build --no-cache`), bypassing the layer cache. |

There is also an early-dispatch path in `main.py`: when the first argument is exactly `client`, `main.py` seeds `.env.local` and then immediately delegates to `client_utils.create_client.main()` before constructing the main parser.

### Client Startup Kit Handling

When `--site <site>` is used, the command searches `DUALITY_NVFLARE_WORKSPACE` for a participant directory named exactly like the site. It then creates:

```text
<standalone>/dist/client_<site>_startup_kit.tar
```

When `--tar-file <path>` is used, the tar must already exist and the site name is inferred from the filename pattern:

```text
client_<site>_startup_kit.tar
```

The inference pattern accepts names like:

```text
client_site1_startup_kit.tar
client_site2_startup_kit.tar
client_site3_startup_kit.tar
```

### Client Datasource Staging and Runtime Lookup

Client datasource staging is read from env vars.

Preferred grouped/explicit pattern:

```text
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>=<path-or-url>
DUALITY_CLIENT_<SITE>_DATASOURCE_<PROJECT_ID>_<DATASOURCE_GROUP_ID>=<path-or-url>
```

Fallback single-source pattern:

```text
DUALITY_CLIENT_<SITE>_DATASOURCE=<path-or-url>
```

When the fallback single-source pattern is used, it maps to project `1`.

Local datasource paths are host-side staging paths. They are resolved relative to the standalone root unless absolute. If the value points to a `.json` path that does not exist, the client utility also looks for a sibling `.zip` with the same base name and attempts to extract a JSON file from it.

Local JSON datasource files are copied into this temporary build-context directory:

```text
<standalone>/client_utils/injected_datasources/
```

The client Dockerfile copies those files into the image under:

```text
/data/client/
```

Duplicate local datasource filenames are rejected because they would collide inside the Docker image.

The client command does not generate a FHIR base config file. Runtime datasource selection comes from backend user settings. During the job, the client reads `custom/filters.json`, asks the NVFlare server for the datasource, and the server resolves it through `POST /clients/datasource/source`.

Remote FHIR URLs are not staged into the Docker image. They are stored in backend user datasource settings and returned to the client at job runtime.

### Client Build and Container Naming

Before building the client image, the command:

1. Verifies Docker is reachable.
2. Verifies `client_utils/client.Dockerfile` exists.
3. Verifies `client_utils/docker-compose.client-template.yml` exists.
4. Verifies `client_utils/client-results-agent/Dockerfile` exists for every site except `site3`.
5. Calls backend `/user/role`.
6. Ensures the MySQL client record exists.
7. Stages local datasource JSON files into the client build context.
8. Stages an optional local `duality_nvflare_lib-*.whl` into `client_utils/local_wheels/`.
9. Creates the site results directory under `<standalone>/job-results` if needed.
10. Renders a temporary Compose file where services `client` and `results-agent` become `client-<site>` and `results-agent-<site>`.
11. Removes any existing containers named `duality-client-<site>` and `duality-client-results-<site>`.
12. Runs `docker compose -p <project> -f <temp-compose> up -d --build <services>`.
13. Deletes generated temporary build artifacts after Compose starts.

The per-site container names are:

```text
duality-client-<site>
duality-client-results-<site>
```

The default client Compose project is:

```text
duality-client
```

The rendered service names are:

```text
client-<site>
results-agent-<site>
```

Every site receives:

```text
CLIENT_JOB_SAVE_LOCATION=/job-results
ENABLE_JOB_RESULTS_SYMLINK=true
```

`site3` is the initiator. It writes into the shared `<standalone>/job-results` directory and starts no results agent, because the backend already serves that directory. Every other site gets an isolated `<standalone>/job-results/<site>` directory plus a companion results agent published on `127.0.0.1:<8088 + site number>`.

## NVFlare Command

Usage:

```bash
python3 main.py nvflare
```

The NVFlare stage:

1. Loads `.env.local`.
2. Deletes and recreates `<standalone>/dist` so generated startup kit tars are current.
3. Reads `DUALITY_NVFLARE_HOST`, `DUALITY_NVFLARE_FED_PORT`, `DUALITY_NVFLARE_ADMIN_PORT`, `DUALITY_NVFLARE_PROJECT_FILE`, `DUALITY_NVFLARE_WORKSPACE`, and `DUALITY_NVFLARE_ADMIN_NAME`.
4. Checks whether `<workspace>/duality_nvflare/prod_00` already exists.
5. If the workspace already exists, skips provisioning.
6. If the workspace is not provisioned, installs `nvflare==2.7.2` on non-Windows when needed, rewrites `project.yml` to a local project file, and runs NVFlare provisioning.
7. Finds the admin participant folder by admin name.
8. Packs `<standalone>/dist/admin_startup_kit.tar`.
9. Updates `.env.local` with `DUALITY_ADMIN_TAR=<standalone>/dist/admin_startup_kit.tar`.

On non-Windows systems, provisioning tries local commands in this order:

1. `nvflare provision -p <project> -w <workspace>` when `nvflare` is on `PATH`.
2. `provision -p <project> -w <workspace>` when `provision` is on `PATH`.
3. `python -m nvflare.cli provision -p <project> -w <workspace>`.

On Windows, the stage skips local Python provisioning and requires WSL. It runs a root WSL command that installs `python3-venv` and `python3-pip`, creates `/root/.nvf_venv`, installs `nvflare==2.7.2`, and provisions from the WSL-mounted standalone directory.

The default timeouts are:

| Env Var | Default |
| --- | --- |
| `DUALITY_NVF_WSL_TIMEOUT_SECS` | `900` |
| `DUALITY_NVF_LOCAL_TIMEOUT_SECS` | `600` |

## MySQL Command

Usage:

```bash
python3 main.py mysql
```

When `DUALITY_DB_MODE=container`, this command prints an informational skip message and returns success. In that mode, the Compose `mysql` service owns local database startup.

When `DUALITY_DB_MODE=host`, the host MySQL stage:

1. Loads `.env.local`.
2. Attempts to install/use Python MySQL drivers.
3. Reads `DUALITY_MYSQL_HOST`, `DUALITY_MYSQL_PORT`, `DUALITY_MYSQL_USER`, and `DUALITY_MYSQL_PASSWORD`.
4. Checks TCP reachability for the configured host/port, treating `localhost` as `127.0.0.1` for TCP checks.
5. Attempts authentication using `mysqlclient` or `PyMySQL`.
6. If MySQL is not reachable, attempts platform-specific installation.

Supported host install paths:

| OS | Install Path |
| --- | --- |
| macOS | Requires Homebrew, installs `mysql@8.0`, starts `mysql@8.0` through `brew services`. |
| Windows | Requires or attempts to install Chocolatey, installs `mysql`, and attempts to start `MySQL80` or `mysql` service. |
| Linux/Other | Not supported by this host installer. |

For the current default standalone mode, `DUALITY_DB_MODE=container`, host MySQL installation is not used.

## UI Command

Usage:

```bash
python3 main.py ui
```

The UI command opens an interactive terminal dashboard. It repeatedly gathers and displays:

| Section | Data Displayed |
| --- | --- |
| Docker | Docker access failure if `docker ps` fails. |
| Containers | Status for Compose services `mysql`, `backend`, `frontend`, and `nvflare`. |
| Client containers | Running client sites inferred from container names starting with `duality-client-`. Names whose remaining suffix starts with `results-` are skipped, so per-site results containers named `duality-client-results-<site>` are not reported as sites. |
| MySQL | Host, port, user, database, connection status, selected Python driver, and `nvflare_clients.client_name` values when queryable. |
| NVFlare | Workspace path, expected root path, and whether `<workspace>/duality_nvflare/prod_00` exists. |

The UI menu options are:

| Option | Label | Behavior |
| --- | --- | --- |
| `1` | `Provision workspace & build all`, `Reset & rebuild all`, or `Build all` | Runs the full pipeline. If existing `duality-*` containers are present, asks whether to wipe MySQL data first. On success, calls `_seed_default_clients_via_backend()` and prints the resulting registered client names, or warns when the backend is not reachable yet. |
| `2` | `Rebuild backend` | Runs `builder.rebuild(["backend"])`. |
| `3` | `Rebuild frontend` | Runs `builder.rebuild(["frontend"])`. |
| `4` | `Rebuild nvflare` | Runs `builder.rebuild(["nvflare"])`. |
| `5` | `Rebuild mysql` | Asks whether to wipe MySQL data, then runs `builder.rebuild(["mysql"], wipe_mysql=<answer>)`. |
| `6` | `Create/Rebuild USER SPECIFIED client container (includes persist to MySQL)` | Prompts with `Enter site name (e.g., site1), or press Enter to launch all registered clients:`. A site name runs `python main.py client --site <site>`. Empty input seeds the default clients through the backend, then runs the client flow once for every client registered in MySQL. |
| `7` | `Persist USER SPECIFIED client to MySQL` | Prompts for a site name and runs `python main.py clientdb --site <site>`. |
| `8` | `Rebuild ALREADY RUNNING client containers` | Finds running client site names and reruns `python main.py client --site <site>` for each. |
| `9` | `Redeploy ALREADY RUNNING NVFlare Server/Client` | Runs the `wheel` command flow. |
| `r` or blank | `Refresh` | Refreshes dashboard status. |
| `q`, `quit`, or `x` | `Quit` | Exits the UI. |

The UI surfaces command completion status through terminal messages and waits for Enter before returning to the dashboard after actions.

### Default Client Seeding

`_seed_default_clients_via_backend()` exists because the backend seeds the default clients lazily. In `LOCAL` and `DEV` environments the backend inserts `site1`, `site2`, and `site3` into `nvflare_clients` while its database connection provider initializes, and that only happens on the backend's first database-touching request. The launcher's status panel reads MySQL directly, so it never triggers that initialization and a freshly built stack shows no registered clients.

The helper works around this:

1. Imports `ping_backend_login()` from `client_utils/create_client.py`. If the import fails, it returns `False`.
2. Calls `ping_backend_login(quiet=True)` to `POST /user/role`, then re-runs `_probe_mysql()`.
3. Returns `True` as soon as `_probe_mysql()` reports client names.
4. Otherwise retries, printing `waiting for backend to come up...` once, up to `attempts` times (default `10`) with `delay` seconds between attempts (default `1.5`).
5. Returns the result of a final `_probe_mysql()` check when the attempts are exhausted.

Menu option `1` calls it after a successful full pipeline and menu option `6` calls it before listing registered clients for an empty site prompt.

## Launcher Scripts

### `LAUNCH_ME_LINUX.sh`

The Linux launcher:

1. Uses `set -euo pipefail`.
2. Changes the working directory to the directory containing the launcher.
3. Uses `PYTHON_BIN` when set.
4. Otherwise prefers `python3`, then falls back to `python`.
5. Fails if no Python executable is found.
6. If Docker is on `PATH`, runs a preflight `docker ps` check.
7. If Docker access fails due to daemon socket permission and the script is not running as root, prints a `sudo ./LAUNCH_ME_LINUX.sh` hint and exits.
8. Executes `main.py ui` with any extra launcher arguments forwarded.

It does not create a virtual environment and does not install `requirements.txt`.

### `LAUNCH_ME_MAC.command`

The macOS launcher:

1. Changes the working directory to the directory containing the launcher.
2. Uses `PYTHON_BIN` when set.
3. Otherwise prefers `python3`, then falls back to `python`.
4. Fails if no Python executable is found.
5. Runs `main.py ui` with any extra launcher arguments forwarded.
6. Prints the exit status and waits for Enter before closing the terminal window.

It does not create a virtual environment, does not install `requirements.txt`, and does not perform a Docker preflight check before invoking the UI.

### `LAUNCH_ME_WIN.bat`

The Windows launcher:

1. Changes the working directory to the directory containing the launcher.
2. Uses `PYTHON_BIN` when set.
3. Otherwise prefers the Windows `py` launcher.
4. Falls back to `python` when `py` is not found.
5. Fails if no Python executable is found.
6. Runs `main.py ui` with all extra batch arguments forwarded.
7. Pauses before closing and returns the Python process exit code.

It does not create a virtual environment, does not install `requirements.txt`, and does not perform a Docker preflight check before invoking the UI.

## Requirements

`requirements.txt` contains:

```text
fastapi==0.115.2
uvicorn[standard]==0.30.6
python-dotenv==1.0.1
requests==2.32.3
PyMySQL==1.1.1
DBUtils==3.1.0
mysqlclient==2.2.4
wheel
```

The launcher scripts do not install these automatically. The user running the standalone scripts must ensure the Python environment already has the needed packages, or install them manually before running the orchestrator.

## Expected Generated and External Assets

The standalone code expects or creates several generated assets:

| Path | Created By | Purpose |
| --- | --- | --- |
| `.env.local` | `main.py` from `default.env.local` | Local runtime configuration. |
| `project.local.yml` | NVFlare stage | Rewritten local NVFlare project file. |
| `nvflare_workspace/` | NVFlare provisioning | Provisioned NVFlare workspace. This may be omitted from source archives because it is generated. |
| `dist/admin_startup_kit.tar` | NVFlare stage | Admin startup kit tar used by the NVFlare Docker image. |
| `dist/client_<site>_startup_kit.tar` | Client command | Per-site client startup kit tar. |
| `client_utils/injected_datasources/` | Client command | Temporary local datasource staging directory copied into the client image. Raw test data may be omitted from source archives. |
| `job-results/` | Compose/client command | Shared local job result directory. |
| `duality_nvflare_lib` package | `standalone/wheels/` (bundled snapshot) | Runtime wheel staged into the NVFlare and client images at build time; the job bootstrap only checks it is installed. |

Temporary client artifacts are cleaned up after the client Compose command starts.

## Current Caveats

- The file header in `main.py` mentions a public `docker` subcommand, and `cmd_docker()` is implemented, but the current parser does not register a `docker` subcommand.
- `main.py` always reseeds `.env.local` from `default.env.local` at startup. Local manual edits to `.env.local` can be overwritten unless they are supplied from the parent process environment or handled through a separate `--env-file` workflow.
- `codebase_stage/establish_code_base.py` verifies only that sibling `backend` and `frontend` directories exist. It does not clone, pull, or repair those source trees.
- The launcher scripts do not install Python dependencies from `requirements.txt`.
- Missing provisioned NVFlare workspace and raw datasource JSON files are expected in trimmed handoff archives when those assets are generated locally or too large to include.
