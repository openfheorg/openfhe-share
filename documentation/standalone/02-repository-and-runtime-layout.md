# Repository and Runtime Layout

## Standalone Root

The standalone root contains the local orchestration CLI, launch scripts, environment files, Docker Compose resources, NVFlare provisioning resources, MySQL setup helpers, client container helpers, and utility modules.

| Path | Role |
| --- | --- |
| `.env.local` | Local environment file used by the standalone runtime. |
| `default.env.local` | Default environment template used to seed `.env.local` when needed. |
| `.gitignore` | Standalone-specific ignored files. |
| `LAUNCH_ME_LINUX.sh` | Linux launcher script for the standalone workflow. |
| `LAUNCH_ME_MAC.command` | macOS launcher script for the standalone workflow. |
| `LAUNCH_ME_WIN.bat` | Windows launcher script for the standalone workflow. |
| `main.py` | Main standalone CLI/orchestrator. |
| `project.yml` | NVFlare project/provisioning configuration. |
| `project.local.yml` | Local NVFlare project/provisioning configuration. |
| `README.md` | Existing standalone readme. |
| `requirements.txt` | Python dependencies for the standalone orchestration scripts. |
| `.deps/` | Local dependency/cache directory used by the standalone tooling. |
| `client_utils/` | Client container creation and per-site client Compose template files. |
| `codebase_stage/` | Local backend/frontend source verification stage. |
| `dist/` | Generated NVFlare startup kit artifacts. |
| `docker_stage/` | Dockerfiles, Docker Compose file, container builder, and runtime wheel used for the main local stack. |
| `job-results/` | Local job result/output directory. |
| `mysql_stage/` | Host MySQL setup/check helpers. |
| `nvflare_stage/` | NVFlare install/provisioning helpers and workspace output. |
| `utils/` | Shared standalone utility modules. |

## Main Entrypoint

The main standalone entrypoint is:

    main.py

This file owns the CLI and orchestrates the local setup flow.

When run without a subcommand, it performs the default setup/start flow for the local SHARE stack.

When run with subcommands, it can run specific stages such as Docker operations, NVFlare provisioning, MySQL checks, client setup, wheel rebuilding, source updates, and the interactive UI.

## Launch Scripts

The root launch scripts provide OS-specific ways to start the standalone workflow:

| File | Platform |
| --- | --- |
| `LAUNCH_ME_LINUX.sh` | Linux |
| `LAUNCH_ME_MAC.command` | macOS |
| `LAUNCH_ME_WIN.bat` | Windows |

These scripts should be documented with:

- how they invoke Python
- whether they create or use a virtual environment
- how they install requirements
- what command they ultimately run
- expected working directory

## Environment Files

Standalone environment configuration is stored at the root.

| File | Role |
| --- | --- |
| `default.env.local` | Baseline environment template. |
| `.env.local` | Active local environment file. |

The environment utilities are located in:

    utils/environment_utils.py

Environment behavior is documented in `04-environment-configuration.md`.

## Docker Stage

The main local container stack is defined under:

    docker_stage/

Important files include:

| File | Role |
| --- | --- |
| `docker_stage/docker-compose.yml` | Compose file for the main local stack. |
| `docker_stage/backend.Dockerfile` | Backend container build definition used by standalone. |
| `docker_stage/frontend.Dockerfile` | Frontend container build definition used by standalone. |
| `docker_stage/container_builder.py` | Python helper for Docker Compose build/start/rebuild operations. |
| `docker_stage/` | Main Docker Compose project for MySQL, backend, frontend, and NVFlare. The current NVFlare image does not require a pre-copied `duality_nvflare_lib` wheel. |

The Compose stack includes the primary local services:

- MySQL
- backend
- frontend
- NVFlare server/runtime

Docker behavior is documented in `05-docker-compose-and-container-builds.md`.

## Client Utilities

Client container support lives under:

    client_utils/

Important files include:

| File | Role |
| --- | --- |
| `client_utils/create_client.py` | Creates/updates a per-site NVFlare client container context and registers the client where needed. |
| `client_utils/client.Dockerfile` | Dockerfile for per-site client containers. |
| `client_utils/client-results-agent/` | FastAPI results agent image and app started next to each non-initiator client container. |
| `client_utils/docker-compose.client-template.yml` | Compose template used to create per-site client Compose files. Defines the `client` and `results-agent` services. |
| `client_utils/local_wheels/` | Optional local `duality_nvflare_lib-*.whl` staging directory bind-mounted into client containers. |
| `client_utils/` | Per-site client container build/start utilities. A local wheel is only used when one is staged into `local_wheels/`. |

Client provisioning and client container behavior are documented in `06-nvflare-provisioning-and-client-containers.md`.

Client registration/database behavior is documented in `07-mysql-local-container-and-client-registration.md`.

## Codebase Stage

The codebase stage lives under:

    codebase_stage/

| File | Role |
| --- | --- |
| `codebase_stage/establish_code_base.py` | Verifies or establishes expected local backend/frontend source directories. |

This stage helps ensure the standalone package can find the application source code needed to build the frontend and backend containers.

## MySQL Stage

The MySQL stage lives under:

    mysql_stage/

This area contains host MySQL setup/check helpers.

The standalone supports a container-backed MySQL mode through Docker Compose and a host-backed MySQL mode through this stage.

MySQL behavior is documented in `07-mysql-local-container-and-client-registration.md`.

## NVFlare Stage

NVFlare provisioning lives under:

    nvflare_stage/

This area handles NVFlare installation/provisioning and local workspace generation.

Important generated/provisioning outputs include:

| Path | Role |
| --- | --- |
| `dist/admin_startup_kit.tar` | Admin startup kit generated by NVFlare provisioning. |
| `dist/client_site1_startup_kit.tar` | Generated startup kit for site1. |
| `dist/client_site2_startup_kit.tar` | Generated startup kit for site2. |
| `dist/client_site3_startup_kit.tar` | Generated startup kit for site3. |
| `nvflare_stage/nvflare_workspace/` | Local NVFlare workspace generated/used by the standalone runtime. |

NVFlare provisioning is documented in `06-nvflare-provisioning-and-client-containers.md`.

## Utility Modules

Shared utility modules live under:

    utils/

Known utility files include:

| File | Role |
| --- | --- |
| `utils/environment_utils.py` | Environment file loading, writing, and value handling. |
| `utils/ip_utils.py` | Local IP detection helpers. |
| `utils/mysql_driver_utils.py` | MySQL driver/helper behavior used by standalone scripts. |
| `utils/wheel_utils.py` | Wheel rebuild/copy/deploy helper behavior. |
| `utils/windows_choco_installer.py` | Windows Chocolatey install helper. |

These utilities are used by the main CLI and stage scripts.

## Job Results Directory

The standalone package includes:

    job-results/

This directory is used as local job output/result storage or mount context for the local stack.

Document:

- which containers mount it
- which code writes to it
- whether it is generated or committed
- whether it should be cleared between runs
- how results are viewed from the frontend

## Runtime Assembly

The standalone runtime is assembled from these layers:

1. Root launch script or direct `python3 main.py` command starts the orchestrator.
2. `main.py` loads/seeds environment configuration.
3. Utility modules resolve environment values, IP address, MySQL helpers, and wheel behavior.
4. Codebase stage verifies backend/frontend source directories.
5. MySQL stage runs only when host DB mode requires it.
6. NVFlare stage provisions or verifies local NVFlare workspace/startup kits.
7. Docker stage builds and starts the main Compose services.
8. Client utilities create per-site client container contexts from startup kits.
9. Job results and shared mounted directories connect the local containers to the frontend/backend/NVFlare runtime.

## Client Supervisor Sibling

At the monorepo level, `client-supervisor/` is a sibling of `standalone/`. The supervisor does not own the standalone NVFlare provisioning workspace or local datasource corpus. It consumes datasource configuration from this standalone directory and manages downloaded client runtime data under the user's `~/.duality-client` directory.
