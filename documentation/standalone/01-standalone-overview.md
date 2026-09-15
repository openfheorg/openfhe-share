# Standalone Overview

## Standalone Documentation Map

The standalone documentation is organized around the local orchestration code that brings up the SHARE application stack on a developer machine.

| Area | Primary files/directories | Detailed file |
| --- | --- | --- |
| Repository and runtime layout | standalone root files, `utils/`, `docker_stage/`, `client_utils/`, `nvflare_stage/`, `mysql_stage/`, `codebase_stage/` | `02-repository-and-runtime-layout.md` |
| Main orchestrator CLI | `main.py`, launch scripts | `03-main-orchestrator-cli.md` |
| Environment configuration | `default.env.local`, `.env.local`, environment loading utilities | `04-environment-configuration.md` |
| Docker Compose and container builds | `docker_stage/docker-compose.yml`, Dockerfiles, `container_builder.py` | `05-docker-compose-and-container-builds.md` |
| NVFlare provisioning and client containers | `nvflare_stage/`, `project.yml`, `project.local.yml`, `dist/`, `client_utils/` | `06-nvflare-provisioning-and-client-containers.md` |
| MySQL local/container behavior and client registration | `mysql_stage/`, MySQL env vars, `client_utils/create_client.py` registration helpers | `07-mysql-local-container-and-client-registration.md` |
| Troubleshooting and operations | `main.py ui`, Docker status helpers, MySQL probes, NVFlare status checks, rebuild/update commands | `08-troubleshooting-and-operations.md` |
| Local datasource staging and runtime lookup | `.env.local`, `client_utils/create_client.py`, client Dockerfile, backend datasource settings | `09-local-datasource-staging-and-runtime-lookup.md` |

## Standalone Role

The standalone package is the local deployment/orchestration layer for SHARE.

It is responsible for bringing up the local application stack by coordinating:

- frontend container
- backend container
- NVFlare server container
- NVFlare client containers
- MySQL database container or host MySQL mode
- NVFlare workspace provisioning
- client startup kit creation
- client datasource injection
- backend/frontend source checks
- rebuild/update workflows

The standalone code is not the frontend or backend application itself. It wraps those application codebases and makes them runnable together in a local developer environment.

## Main Runtime Flow

The primary entrypoint is:

    python3 main.py

When run with no subcommand, the orchestrator:

1. Seeds `.env.local` from `default.env.local`.
2. Sets `DUALITY_NVFLARE_HOST` to the local machine IP when configured as `auto` or blank.
3. Loads environment values.
4. Runs the MySQL stage unless `DUALITY_DB_MODE=container`.
5. Verifies the backend/frontend source trees.
6. Provisions NVFlare when required by the Docker action.
7. Builds and starts the Docker Compose stack.

The main local stack is defined in:

    docker_stage/docker-compose.yml

That Compose stack includes:

- `mysql`
- `backend`
- `frontend`
- `nvflare`

NVFlare clients are created separately through the `client` command because each client is rendered as its own per-site Compose service.

## Core Services

| Service | Container name | Purpose |
| --- | --- | --- |
| `mysql` | `duality-mysql` | Local MySQL database for backend application state. |
| `backend` | `duality-backend` | FastAPI backend container. |
| `frontend` | `frontend` | React frontend container. |
| `nvflare` | `duality-nvflare` | Local NVFlare server/runtime container. |
| client containers | `duality-client-<site>` | Per-site NVFlare client containers created by `python3 main.py client --site <site>`. |

## Main Commands

The top-level CLI supports these command groups:

| Command | Purpose |
| --- | --- |
| `python3 main.py` | Runs the default local setup pipeline. |
| `python3 main.py codebase` | Verifies local backend/frontend source directories. |
| `python3 main.py mysql` | Checks host MySQL when host DB mode is enabled. |
| `python3 main.py nvflare` | Installs/provisions NVFlare workspace. |
| `python3 main.py docker ...` | Runs direct Docker Compose operations. |
| `python3 main.py rebuild ...` | Rebuilds and restarts selected services. |
| `python3 main.py update ...` | Runs `git pull` for selected local repos and rebuilds them. |
| `python3 main.py wheel` | Rebuilds the NVFlare runtime wheel and redeploys running NVFlare/client containers. |
| `python3 main.py clientdb --site <site>` | Ensures a site/client record exists in MySQL. |
| `python3 main.py client --site <site>` | Builds and starts a per-site NVFlare client container. |
| `python3 main.py ui` | Opens the interactive local status/rebuild dashboard. |

## Local Source Assumption

The standalone package expects the application source trees to live next to it in the unified repository/workspace layout.

The Docker build context is set up so the standalone Dockerfiles can build the backend and frontend containers from local source.

The codebase stage verifies local source directories rather than treating standalone as a self-contained application copy.

## NVFlare Workspace and Startup Kits

NVFlare provisioning uses:

- `project.yml`
- `project.local.yml`
- `nvflare_stage/nvflare_install_and_provision.py`
- `dist/admin_startup_kit.tar`
- `dist/client_site*_startup_kit.tar`
- `nvflare_workspace/`

The provisioning flow produces startup kits and a local workspace that the backend and NVFlare container share through mounted volumes.

Client containers are created from client startup kits.

## MySQL Mode

The standalone supports two database modes:

| Mode | Behavior |
| --- | --- |
| `DUALITY_DB_MODE=container` | Default mode. The `mysql` Compose service provides the database. The `python3 main.py mysql` stage is skipped. |
| `DUALITY_DB_MODE=host` | The standalone expects a host-installed MySQL instance. The MySQL stage verifies or attempts installation on supported platforms. |

The Compose-managed MySQL service maps container port `3306` to host port `3307`.

## Client Datasource Configuration

Client datasource configuration is driven by environment variables in `.env.local`.

The pattern supports project-level and datasource-group-level entries, such as:

    DUALITY_CLIENT_SITE1_DATASOURCE_1=...
    DUALITY_CLIENT_SITE1_DATASOURCE_2_1=...

Client creation reads those values as host-side staging locations, stages local JSON datasource files into the client Docker build context, and copies those files into the client image under `/data/client/`. Runtime datasource selection is resolved from backend user/project settings through the NVFlare server; no client-side `DUALITY_FHIR_BASE_CONFIG.json` is generated or required.

## Documentation Build-Out Rule

Each standalone document should connect:

- command or script
- files used
- environment variables required
- generated files/directories
- Docker service affected
- NVFlare workspace/client artifact affected
- MySQL state affected
- common failure modes
- recovery command

## Relationship to Client Supervisor

`share/client-supervisor` is the client-site operator application. It is not part of the main standalone Compose stack, but it reuses two standalone inputs:

- `standalone/.env.local` for datasource mappings
- `standalone/nvflare_stage/data` for actual local datasource JSON or ZIP files

The client supervisor downloads site startup kits from the backend and installs them under `~/.duality-client/<site>` rather than using the standalone `dist/` directory as its normal delivery path.
