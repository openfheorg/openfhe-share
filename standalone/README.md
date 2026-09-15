# Duality Standalone Secure Data Collaboration Framework — README

A single command–line orchestrator to bring up a local Duality stack:

- Verifies/installs **MySQL** (macOS/Windows).
- Uses the local **backend** and **frontend** source trees at `../backend` and `../frontend` (or falls back to images).
- Installs **NVFLARE** and **provisions** a local workspace.
- Builds and runs **Docker Compose** services.
- Creates and runs **NVFLARE client containers** via a unified `client` command.

> This project uses a **`.env.local`** configuration file at the repo root.  

---

## Contents

- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Commands & Usage](#commands--usage)
  - [`codebase`](#codebase)
  - [`mysql`](#mysql)
  - [`nvflare`](#nvflare)
  - [`rebuild`](#rebuild)
  - [`update`](#update)
  - [`wheel`](#wheel)
  - [`client`](#client-new)
  - [`clientdb`](#clientdb-new)
  - [No-subcommand default flow](#no-subcommand-default-flow)
- [Configuration (`default.env.local`)](#configuration-defaultenvlocal)
  - [Variable reference (complete)](#variable-reference-complete)
  - [How seeding works](#how-seeding-works)
- [File/Folder Layout](#filefolder-layout)
- [Advanced: NVFLARE Admin kit & client utilities](#advanced-nvflare-admin-kit--client-utilities)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

This is the minimal flow for first–time use on a new machine.

### 1. Bring up the core Duality stack

From the repo root:

```bash
python3 main.py
```

This will:

1. Seed `./.env.local` from `./default.env.local` (overwriting any existing `.env.local`).
2. Fill `DUALITY_NVFLARE_HOST` with your current IP if it’s empty or set to `auto`.
3. Run the **MySQL** stage (host or container depending on `DUALITY_DB_MODE`).
4. Run the **codebase** stage (clone backend/frontend if repos are configured).
5. Run the **docker** stage (reset + build + up) to start the stack.

After this, you should have backend/frontend (and optionally NVFLARE) running via Docker Compose.

### 2. Create and run a client.

Once the stack and NVFLARE workspace are ready, you can create and run a client with a single command.  
For example, to run `site1`:

```bash
python3 main.py client --site site1
```

This will:

- Locate the provisioned NVFLARE workspace (e.g., `site1` folder).
- Build a client startup kit tar for that site if needed.
- Ensure a matching **MySQL client entry** exists.
- Build and start the **client container** via a per-site docker-compose file.
- Use datasources defined by defaults or `DUALITY_CLIENT_SITE*_DATASOURCE` overrides.

To just prepare the client kit and DB entry **without** running a container:

```bash
python3 main.py client --site site1 --tar-kit
```

To run a client from an already-built tar:

```bash
python3 main.py client --tar-file ./dist/client_site1_startup_kit.tar
```

> Note: The name `site1`/`site2` should correspond to sites defined in your NVFLARE `project.yml`.

---

## Requirements

- **Python 3.10+** (used by all stages, installs `nvflare` when needed).
- **Python packages**: `pip install -r requirements.txt` from this directory. The launchers do not install them; `main.py client` needs `PyMySQL`.
- **Docker**:
  - Docker Desktop (macOS/Windows) or Docker + Compose v2 CLI (`docker compose`) or legacy `docker-compose`.
- **Git** (for cloning when using local source).
- **MySQL**:
  - If not present, the orchestrator can install it on **macOS** (Homebrew) and **Windows** (Chocolatey).
  - Linux MySQL auto-install is **not** supported by the scripts (bring your own MySQL).
- **Windows + NVFLARE**: Requires **WSL** (Windows Subsystem for Linux) with a distro (Ubuntu recommended).
- **NVFlare 2.7.2**: Version 2.7.2 is necessary on the host machine to properly provision the workspace. Run `pip install nvflare==2.7.2`.

---

## Commands & Usage

All commands are subcommands of the top-level CLI. Run `-h` on any to see flags.

### `codebase`

Verify that the local backend and frontend source trees are present.

```bash
python3 main.py codebase
```

- Uses local source from `../backend` and `../frontend`.
- If those directories are missing, returns **100**.

### `mysql`

Check MySQL reachability and attempt installation if missing.

```bash
python3 main.py mysql
```

- macOS: installs via **Homebrew**.
- Windows: installs via **Chocolatey** (will prompt for elevation).
- Linux: **not** auto-installed; script will error if not reachable.
- Uses:
  - `DUALITY_MYSQL_HOST`, `DUALITY_MYSQL_PORT`, `DUALITY_MYSQL_USER`, `DUALITY_MYSQL_PASSWORD`.

**DB mode: host vs container (simple)**  
- `DUALITY_DB_MODE=container` (default): the stack uses a containerized MySQL managed by Compose; the `mysql` step is a no-op.
- `DUALITY_DB_MODE=host`: the stack expects a host-installed MySQL; the `mysql` step verifies/installs it.

### `nvflare`

Install NVFLARE (if needed) and **provision** a local workspace.

```bash
python3 main.py nvflare
```

- Non-Windows: attempts local Python provision (installs `nvflare==2.7.2` if needed).
- Windows: provisions **inside WSL** automatically.
- Produces: `dist/admin_startup_kit.tar` and writes its path to `DUALITY_ADMIN_TAR` in `.env.local`.
- Uses:
  - `DUALITY_NVFLARE_HOST`, `DUALITY_NVFLARE_FED_PORT`, `DUALITY_NVFLARE_ADMIN_PORT`,
    `DUALITY_NVFLARE_PROJECT_FILE`, `DUALITY_NVFLARE_WORKSPACE`, `DUALITY_NVFLARE_ADMIN_NAME`,
    `DUALITY_NVF_LOCAL_TIMEOUT_SECS`, `DUALITY_NVF_WSL_TIMEOUT_SECS`.

### `rebuild`

Rebuild and restart **selected** services using local source (no deps).

```bash
python3 main.py rebuild frontend
python3 main.py rebuild backend
```

**MySQL wipe on rebuild (container mode)**  
Set in `default.env.local`:

```bash
DUALITY_DB_WIPE_ON_REBUILD=true
```

Then include `mysql` in your rebuild so it restarts after the wipe:

```bash
python3 main.py rebuild mysql
# or, if rebuilding app code too:
python3 main.py rebuild backend mysql
```

(If you omit `mysql`, the DB is wiped but not restarted because `rebuild` uses `--no-deps`.)

### `update`

Pull the local service repos, then rebuild and restart (no deps).

```bash
python3 main.py update frontend backend
```

- Runs `git pull` in the SHARE checkout that contains `../backend` and `../frontend`, then triggers a build and restart for those services.

### `wheel`

Build the local **`duality_nvflare_lib`** wheel from the working tree and redeploy it to the **already-running** NVFlare server and client containers — without a full stack reset. This is the fast loop for iterating on packaged **`apis/`** / **`workflows/`** code or job **`custom/`** code during local development.

```bash
python3 main.py wheel
python3 main.py wheel --no-cache              # disable build cache for the NVFLARE redeploy
python3 main.py wheel --wheel-version 1.2.7.13.0
```

This will:

- Build the wheel via `backend/.../nvflare_jobs/wheels/APIWheelBuilderCI.py`.
- Stage it into the `nvflare` and client build contexts and rebuild/redeploy those containers.
- Redeploy the containers so they install the freshly built wheel from their `local_wheels` mount. The job runtime (`duality_wheel_runtime.py`) only ever uses the wheel installed in the container and never contacts a package registry, so the redeployed build is what every subsequent job runs.

> Requires the `nvflare` service and at least one client container to already be running. This is also exposed as **option `[9]` ("Build Wheel & Redeploy ALREADY RUNNING NVFlare Server/Client")** in the interactive launcher menu (`LAUNCH_ME_LINUX.sh`).

### `client` (new)

Create and/or run a **NVFLARE client container** via Docker Compose, using the provisioned workspace and client startup kits.

#### Run a client for a workspace site

```bash
python3 main.py client --site site1
```

This will:

- Find the provisioned workspace directory for `site1` (under `DUALITY_NVFLARE_WORKSPACE`).
- Build a `client_site1_startup_kit.tar` into `dist/` if needed.
- Ensure MySQL has:
  - a `defined_roles` row for role `client`,
  - a `users` row `client_site1`,
  - an `nvflare_clients` row with `client_name=site1`.
- Inject the latest `duality_nvflare_lib` wheel into the client Docker build context.
- Render a per-site compose file (`client-<site>` service) and bring up the client container.

#### Tar-only mode (build kit, optional DB entry, no container)

```bash
python3 main.py client --site site1 --tar-kit
```

- Builds `dist/client_site1_startup_kit.tar` from the workspace.
- Prompts whether to also register the client in MySQL.
- Exits without starting any containers.

#### Run from an existing client tar

```bash
python3 main.py client --tar-file ./dist/client_site1_startup_kit.tar
```

- Infers the site name from the tar filename (`client_siteX_startup_kit.tar`).
- Uses default or overridden datasource JSON for that site.
- Registers the client in MySQL if needed.
- Builds and starts the client container via Compose.

Additional flags:

- `--env-file` — optional env file to load instead of the repo `.env.local`.
- `--compose-file` — override the client compose template (`client_utils/docker-compose.client-template.yml`).
- `--project` — Compose project name (defaults to `duality`).

### `clientdb` (new)

Create/ensure a **NVFLARE client** entry in MySQL so a site can receive **broadcasted jobs**.

> Note: `site1` in the example below corresponds to a site defined in the NVFLARE project file. 

```bash
# Register site1 in the DB
python3 main.py clientdb --site site1
```

- Reuses the same logic as the client utility: it upserts a `defined_roles` row (`client`), a `users` row (`client_<site>`), and an `nvflare_clients` row (`client_name=<site>`), returning existing IDs if already present.
- Uses MySQL connection details from `.env.local`.

### No-subcommand default flow

If you run `main.py` with **no subcommand**:

```bash
python3 main.py
```

The orchestrator runs:

1. `mysql` — host or container DB setup based on `DUALITY_DB_MODE`.
2. `codebase` — verify local source or signal “use images” if source directories are missing.
3. `docker run` — reset, build, and bring up the stack (frontend/backend/NVFLARE services as defined in `docker-compose.yml`).

Clients are **not** started by this default flow; use `python3 main.py client ...` separately.

---

## Configuration (`default.env.local`)

### How seeding works

- On **every run**, the orchestrator **overwrites** `./.env.local` with `./default.env.local`.
- It then sets `DUALITY_NVFLARE_HOST` in `.env.local` to your machine’s IP if the value is empty or `auto`.
- It also ensures a sane default `DUALITY_DB_MODE=container` if unset.
- **Recommendation:** Put your persistent defaults in `default.env.local`. If you manually edit `.env.local`, your changes will be replaced next run unless you also update `default.env.local`.

### Variable reference (complete)

> Defaults shown are typical; consult your `default.env.local`.

#### MySQL

| Variable | Default | What it does | Effects of changing |
|---|---|---|---|
| `DUALITY_DB_MODE` | `container` | Selects DB mode: `container` uses Docker Compose `mysql` service; `host` uses a locally installed MySQL. | Set to `host` if you run your own MySQL outside Docker. |
| `DUALITY_DB_WIPE_ON_REBUILD` | *(unset/false)* | When `true`, a `rebuild` triggers a wipe of the Compose MySQL volume before rebuilding. | Use with `python3 main.py rebuild mysql` so the DB restarts after the wipe. |
| `DUALITY_MYSQL_HOST` | `localhost` | Hostname/IP for MySQL reachability and auth checks. | Point to a remote DB by setting an IP/DNS name. Use `127.0.0.1` to avoid localhost edge cases. |
| `DUALITY_MYSQL_PORT` | `3307` (`container` mode) | TCP port for MySQL. The Compose `mysql` service publishes 3307 on the host to avoid clashing with a local 3306. | In `host` mode set it to your MySQL port (usually `3306`). |
| `DUALITY_MYSQL_USER` | *(blank)* | Username used for a test connection. | Must match a valid DB user; otherwise auth step will fail. |
| `DUALITY_MYSQL_PASSWORD` | *(blank)* | Password used for a test connection. | Must match the user’s password. |

#### Codebase (local source)

The codebase stage expects these workspace directories:

- `../backend`
- `../frontend`

They are used directly by Docker builds from the workspace root.

#### NVFLARE (provisioning)

| Variable | Default | What it does | Effects of changing |
|---|---|---|---|
| `DUALITY_NVFLARE_HOST` | `auto` (resolved to your IP at seed time) | Hostname published in the NVFLARE project server block and `sp_end_point`. | Set to a resolvable hostname or static IP accessible by clients. |
| `DUALITY_NVFLARE_FED_PORT` | `8002` | Federated learning port in project config. | Change if port is in use or for multi-instance setups. |
| `DUALITY_NVFLARE_ADMIN_PORT` | `8003` | Admin port in project config. | Change if port is in use or for multi-instance setups. |
| `DUALITY_NVFLARE_PROJECT_FILE` | `project.yml` | Path to the NVFLARE project file used for provisioning. | Point to a custom project file; the script writes a `.local.yml` variant with host/ports. |
| `DUALITY_NVFLARE_WORKSPACE` | `nvflare_workspace` | Output workspace directory for provisioned kits. | Move it elsewhere if you need a different location (absolute or relative). |
| `DUALITY_NVFLARE_ADMIN_NAME` | `admin@share.local` | Folder name under the provisioned workspace that holds the admin kit. | Set if your project uses a different admin identity. |
| `DUALITY_ADMIN_TAR` | *(auto-written)* | **Written by the nvflare stage**: absolute path to `dist/admin_startup_kit.tar`. | Consumers can read this to mount/use the admin kit; do not edit manually. |
| `DUALITY_NVF_LOCAL_TIMEOUT_SECS` | `600` | Timeout for local provisioning attempts. | Increase on slow networks/machines. |
| `DUALITY_NVF_WSL_TIMEOUT_SECS` | `900` | Timeout for WSL provisioning on Windows. | Increase if provisioning hits timeouts under WSL. |

#### Frontend build (written into frontend repo)

| Variable | Default | What it does | Effects of changing |
|---|---|---|---|
| `REACT_APP_API_BASE` | `http://localhost:8000` | **Preferred** API base URL injected into `frontend/.env.production.local`. | Point the UI at a different backend (e.g., `https://staging.example.com`). |
| `NEXT_PUBLIC_BACKEND_URL` | *(unset)* | **Fallback** key; used if `REACT_APP_API_BASE` is not set. | Same effect as above; supports Next.js style envs. |
| `REACT_APP_BUILD_FLAVOR` | `local` | Label for frontend builds (e.g., `local`, `staging`, `prod`). | Can drive UI behavior or labeling if the app uses it. |

#### NVFLARE client utility & client command

If you use the **client** command / utility to package and run client startup kits:

| Variable | Default | What it does | Effects of changing |
|---|---|---|---|
| `DUALITY_CLIENT_SITE<n>_DATASOURCE_<project>_<group>` | see `default.env.local` | Datasource for `site<n>` in project `<project>`, datasource group `<group>` (for example `DUALITY_CLIENT_SITE1_DATASOURCE_2_1`). A FHIR URL, or a path (relative to `standalone/` or absolute) to a JSON bundle. Project 1 has no groups: `DUALITY_CLIENT_SITE<n>_DATASOURCE_1`. | Each variable becomes one datasource row for that site in MySQL and, for JSON bundles, one file staged into the client image. |
| `DUALITY_CLIENT_SITE<n>_DATASOURCE` | *(unset)* | Legacy single-datasource override for project 1, used only when no suffixed variable exists for the site. | Prefer the suffixed form. |

> The JSON bundles referenced by the defaults are extracted from the zips in `nvflare_stage/data/` on first use.

---

## File/Folder Layout

```text
repo/
├─ main.py                         # top-level orchestrator CLI
├─ default.env.local               # template config (OVERWRITES .env.local on run)
├─ .env.local                      # effective config used by stages (autogenerated)
├─ codebase_stage/
│  └─ establish_code_base.py       # verifies backend/frontend source directories exist
├─ mysql_stage/
│  └─ mysql_check_or_install.py    # checks/installs MySQL, verifies auth
├─ nvflare_stage/
│  └─ nvflare_install_and_provision.py   # installs NVFLARE, provisions workspace, writes admin tar
├─ docker_stage/
│  ├─ container_builder.py         # wraps docker compose (build/up/down/logs/ps/pull)
│  └─ docker-compose.yml           # services definition (edit to suit)
├─ client_utils/
│  ├─ create_client.py             # build/run NVFLARE client container; also supports tar-only + DB registration
│  └─ docker-compose.client-template.yml # template used when running client containers
├─ utils/
│  ├─ environment_utils.py         # load_env_file for dotenv-style files
│  ├─ ip_utils.py                  # get_ip helper (used to seed host)
│  └─ wheel_utils.py               # shared helper to inject latest duality_nvflare_lib wheel
├─ backend/                        # local backend source used directly by Docker builds
├─ frontend/                       # local frontend source used directly by Docker builds
└─ dist/
   ├─ admin_startup_kit.tar        # created by nvflare stage
   └─ client_siteX_startup_kit.tar # created by client command/utility
```

---

## Advanced: NVFLARE Admin kit & client utilities

### Admin kit

- Running `python3 main.py nvflare` creates `dist/admin_startup_kit.tar` and writes `DUALITY_ADMIN_TAR` to `.env.local`.
- This tar contains the admin’s `startup/` and `local/` directories with executable scripts normalized for Unix line endings.

### NVFLARE client container (client utility)

The repo includes a client utility (`client_utils/create_client.py`) which is now wired through the main orchestrator as the `client` subcommand.

Preferred usage (via main orchestrator):

```bash
# Build and run a client for site1
python3 main.py client --site site1

# Build only the startup kit (plus optional DB registration)
python3 main.py client --site site1 --tar-kit

# Run a client from an existing tar
python3 main.py client --tar-file ./dist/client_site1_startup_kit.tar
```

You can still call the client utility directly if needed:

```bash
python3 client_utils/create_client.py --site site1
```

but the behavior and options are identical to `python3 main.py client ...`, and the latter is the recommended entrypoint so all tooling flows through the same CLI.

**Registering later** (manual DB entry without running a container):

```bash
# add/ensure a DB entry so a site can receive broadcasted jobs
python3 main.py clientdb --site site1
```

Environment variables that influence the client utility / client command:

- `DUALITY_NVFLARE_WORKSPACE` — where to find the provisioned `site1/` or `site2/` folders.
- `DUALITY_CLIENT_SITE<n>_DATASOURCE_<project>_<group>` — per-project, per-group datasources for `site<n>` (see the client variable table above).

---

## Troubleshooting

- **`.env.local` keeps changing:** This is by design. The orchestrator **always** seeds it from `default.env.local`. Move your durable changes into `default.env.local`.
- **MySQL on Linux:** The script doesn’t auto-install on Linux. Install MySQL yourself and set `DUALITY_MYSQL_*` accordingly.
- **Docker errors about missing services:** Confirm service names in `docker_stage/docker-compose.yml` and pass matching names to `docker` commands.
- **Frontend can’t reach backend:** Check `REACT_APP_API_BASE` (or `NEXT_PUBLIC_BACKEND_URL`). The orchestrator writes them into `frontend/.env.production.local` before builds.
- **Windows NVFLARE provisioning fails:** Ensure WSL is installed and a distro is registered (`wsl --status`). Increase `DUALITY_NVF_WSL_TIMEOUT_SECS` if needed.
- **Windows containers cannot reach published ports:** In an elevated PowerShell run `Set-NetNatGlobal -InterRoutingDomainHairpinningMode Local`, then restart.
- **Codebase check fails:** Make sure the local `backend/` and `frontend/` directories exist at the workspace root.
- **Falling back to images:** If local source directories are missing, the codebase stage returns **100**. The `docker` stage will still run using images defined in your compose file.
- **Client DB entry already exists:** The `clientdb` command and the client utility will report the existing mapping; no duplication occurs.
