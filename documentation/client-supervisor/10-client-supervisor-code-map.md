# Client Supervisor Code Map

## Project Root

| Path | Purpose |
| --- | --- |
| `README.md` | Project summary and basic commands. |
| `install.ini` | Site-to-config mapping and server-name reference. |
| `main.py` | Direct setup and launch CLI. |
| `startup_kit_delivery.py` | Shared terminal/CLI archive delivery and install logic. |
| `tool_ui.py` | Menu-driven terminal supervisor. |
| `test_data/` | Site configuration JSON files only. |
| `local-results-api/` | Local job-results FastAPI service, plus its Docker image and container management script. |
| `client-desktop/` | PySide6 desktop supervisor. |

## Desktop Package

| Path | Purpose |
| --- | --- |
| `client-desktop/src/share_desktop/main.py` | Qt application entrypoint and command-line parsing. |
| `app_window.py` | Main window, login gate, header, pages, controls, status, and workflow coordination. |
| `config.py` | Default and user INI loading. |
| `paths.py` | Supervisor root, local Results API, workspace, and asset paths. |
| `state.py` | Persistent desktop state. |
| `theme.py` | Shared Qt stylesheet and visual constants. |
| `icons.py` | App and tray icon selection. |
| `services/authentication.py` | Backend login/session lookup. |
| `services/startup_kit_delivery.py` | Desktop archive download and checksum verification. |
| `services/share_launch.py` | Pako-compatible SHARE launch payload encoding and destination URL construction. |
| `workers/login_worker.py` | Background login execution. |
| `workers/startup_kit_worker.py` | Background startup-kit provisioning. |
| `runners/startup_kit.py` | Archive inspection and installation helpers. |
| `runners/nvflare_runner.py` | NVFlare start, graceful stop, force kill, and log stream. |
| `runners/results_api_runner.py` | Embedded Uvicorn Results API. Imports the FastAPI app, serves it on a background thread, and owns health checks, restart, and shutdown. |
| `runners/container_runner.py` | Older `agent_manage.py` container control and log stream. It is still present but is not used by the current desktop window. |
| `runners/process_runner.py` | Common subprocess handling. |
| `widgets/log_console.py` | Reusable log display. |
| `widgets/service_card.py` | Reusable service status panel. |
| `assets/branding/` | SHARE Client wordmark and login art. |
| `assets/icons/` | Idle, active, error, and platform icon assets. |
| `client-desktop/tests/test_share_launch.py` | Launch payload and URL compatibility tests. |

## Local Results API

| Path | Purpose |
| --- | --- |
| `local-results-api/agent_manage.py` | Docker lifecycle and token management for the terminal supervisors, `main.py`, and the copy embedded in the startup kit. |
| `local-results-api/run_client_agent.py` | Thin command wrapper. |
| `local-results-api/Dockerfile` | Runtime image. |
| `local-results-api/docker-compose.yml` | Reference Compose service. |
| `local-results-api/requirements.txt` | Python dependencies. |
| `local-results-api/app/main.py` | FastAPI routes and health output. |
| `local-results-api/app/NVFlareJobsDataRetriever.py` | Job-result discovery and read logic. |
| `local-results-api/app/SupportedFunction.py` | Supported function enum mapping. |
| `local-results-api/app/models.py` | Request/response models. |
| `local-results-api/app/nvflare_workspace.py` | Workspace path resolution. |
| `local-results-api/app/security.py` | Token extraction and validation. |

## External Dependencies

| External path/service | Purpose |
| --- | --- |
| `share/standalone/.env.local` | Datasource mappings and local runtime values. |
| `share/standalone/nvflare_stage/data` | Actual local datasource files. |
| Backend `/user/role` | Desktop session lookup and assigned site. |
| Backend `/clients/content/startup-kit` | Site-specific startup-kit binary download. |
| SHARE frontend `launch` query parameter | Username-prefill or direct-results bootstrap using zlib/Base64URL payloads decoded with pako. |
| Backend `/nvflare/jobs/results_context` | Resolves compact job, project, datasource-group, and filter context for direct Results entry. |
| NVFlare EC2 workspace | Source of remotely packaged startup kits in non-local backend environments. |
| Docker daemon | Runs the local Results API container for the terminal supervisors and the startup-kit-embedded script. The desktop application does not require it. |
