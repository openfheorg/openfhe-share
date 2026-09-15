# Local Results API

## Purpose

`local-results-api` is a small FastAPI service that exposes job results from the local site's managed NVFlare workspace. The same application is hosted in two different ways depending on which supervisor starts it:

| Hosting mode | Started by | Runtime |
| --- | --- | --- |
| Embedded Uvicorn | SHARE Client desktop | The FastAPI app is imported into the desktop process and served by Uvicorn on a dedicated background thread. |
| Docker container | `tool_ui.py`, `main.py`, and the patched startup-kit script | `agent_manage.py` builds the image and runs the `duality-client-agent` container. |

Both modes serve the same endpoints on `127.0.0.1` port `8088` by default, so only one of them can hold that port at a time.

## Directory

```text
client-supervisor/local-results-api/
```

Important files:

| File | Role |
| --- | --- |
| `agent_manage.py` | Build, deploy, start, restart, stop, status, token, Docker availability, and container command handling. |
| `run_client_agent.py` | Thin command wrapper. |
| `Dockerfile` | Container image definition. |
| `docker-compose.yml` | Reference Compose definition. |
| `requirements.txt` | Python dependencies. |
| `app/main.py` | FastAPI application and endpoints. |
| `app/NVFlareJobsDataRetriever.py` | Local job-result discovery and retrieval. |
| `app/SupportedFunction.py` | Function-name mapping. |
| `app/security.py` | Token lookup and request protection helpers. |

## Embedded Uvicorn Runtime

The desktop supervisor hosts the service itself through `client-desktop/src/share_desktop/runners/results_api_runner.py`. No container, image, or Docker daemon is involved.

`local-results-api` is added to `sys.path` and `app.main` is imported, so the served FastAPI object is the same one the container runs. Uvicorn runs on a daemon thread named `SHARE-Results-API`, which keeps the Qt event loop responsive.

The service binds:

```text
host: 127.0.0.1
port: [results] port from the desktop configuration, default 8088
```

The embedded service has no separate operating-system process. It shares the SHARE Client PID, and closing the application stops it.

Before starting, the runner exports host paths into the desktop process environment:

```text
DUALITY_CLIENT_SITE=<assigned site>
DUALITY_CLIENT_WORKSPACE=~/.duality-client/<site>
DUALITY_NVFLARE_WORKSPACE=~/.duality-client/<site>
DUALITY_NVFLARE_JOB_SAVE_LOCATION=~/.duality-client/<site>/job-results
```

Because the service runs on the host, it reads the managed workspace directly. There is no `/nvflare` mount and no container-side path translation.

### Lifecycle and Recovery

| Behavior | Detail |
| --- | --- |
| Port conflict | `start` fails when `127.0.0.1:<port>` is already bound. The error names the legacy container and suggests `docker stop duality-client-agent`. |
| Startup watch | The runner polls the Uvicorn server until it reports started, then runs health checks. Startup is abandoned after roughly ten seconds. |
| Stop | Sets the Uvicorn exit flag, then forces exit if the thread is still alive after five seconds. |
| Restart | Stops the current server and starts a new one with the same workspace and site. |
| Health check | `GET http://127.0.0.1:<port>/health` with a two-second timeout. The reported detail includes the job-results path and whether it exists. |
| Automatic recovery | Three consecutive failed periodic health checks trigger one controlled restart. An unexpected thread exit triggers up to three restarts with 1s, 2s, and 4s backoff. |
| Application exit | The runner stops the server and joins the thread before the desktop quits. |

### Embedded Logs

Uvicorn's `uvicorn`, `uvicorn.error`, and `uvicorn.access` loggers are captured while the service runs. The captured output is shown on the desktop Results API page and appended to:

```text
~/.duality-client/logs/results-service-output.log
```

## Container Runtime

`tool_ui.py` and `main.py` manage the service as a Docker container through `local-results-api/agent_manage.py`. `main.py` also copies that script into the installed startup kit as `duality_agent_manage.py` and patches `startup/start.sh` so the container starts with the NVFlare client.

Defaults:

```text
image: duality-client-agent:local
container: duality-client-agent
published port: 127.0.0.1:8088 -> 8088
restart policy: unless-stopped
```

The managed host workspace is mounted read-only at:

```text
/nvflare
```

The container receives:

```text
DUALITY_NVFLARE_WORKSPACE=/nvflare
DUALITY_NVFLARE_JOB_SAVE_LOCATION=/nvflare/job-results
DUALITY_CLIENT_AGENT_TOKEN=<token>
```

`DUALITY_UI_ORIGINS` is added only when `--ui_origins` is supplied.

The host-side source is:

```text
~/.duality-client/<site>
```

When a container already exists and a job-save location is requested, it is removed and recreated, because Docker cannot change environment values or mounts on an existing container.

## Management Commands

These commands apply to the container runtime only. The desktop starts, restarts, stops, and health-checks the embedded service from its Results API page instead.

Build and deploy:

```bash
python3 local-results-api/agent_manage.py build_deploy \
  --container duality-client-agent \
  --port 8088 \
  --workspace "$HOME/.duality-client/site1" \
  --job_save_location /nvflare/job-results
```

Start or restart:

```bash
python3 local-results-api/agent_manage.py start \
  --container duality-client-agent \
  --port 8088 \
  --workspace "$HOME/.duality-client/site1" \
  --job_save_location /nvflare/job-results
```

Stop:

```bash
python3 local-results-api/agent_manage.py stop --container duality-client-agent
```

Status:

```bash
python3 local-results-api/agent_manage.py status --container duality-client-agent
```

`--installdocker` allows the manager to attempt supported Docker installation or sudo fallback behavior. Normal production setup should grant the user direct Docker daemon access instead.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Report service health, site, workspace, configured job-save location, existence, and a small directory listing. |
| `POST` | `/jobs/results` | Return workflow data and function configuration for a job/function/workflow. |
| `POST` | `/jobs/results/mapping` | Return workflow result directories and optional profile summary for a job/function. |

### `/jobs/results` request

```json
{
  "nvflare_job_id": "job-id",
  "function": "MEAN",
  "workflow_id": "workflow-id"
}
```

### `/jobs/results/mapping` request

```json
{
  "nvflare_job_id": "job-id",
  "function": "MEAN"
}
```

## Token

`agent_manage.py` reads or creates a Results API token stored in the workspace as `.duality_client_agent_token`, passes it to the container, and prints:

```text
DUALITY_CLIENT_AGENT_TOKEN=<token>
```

The token may be sent as:

```text
Authorization: Bearer <token>
```

or:

```text
X-Duality-Token: <token>
```

The embedded runner does not read or create the workspace token file. It sets only the site, workspace, and job-save-location variables, so `DUALITY_CLIENT_AGENT_TOKEN` is present in embedded mode only when the desktop process already inherited it.

## Docker Permission Requirement

This requirement applies to the container runtime. The embedded desktop service does not use Docker.

Docker daemon permission is user-specific, not directory-specific. On Ubuntu, add each client user to the Docker group once:

```bash
sudo usermod -aG docker "$USER"
```

Then log out and reconnect before relaunching the supervisor. Verify with:

```bash
docker info
```
