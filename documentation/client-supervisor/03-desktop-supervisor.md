# SHARE Client Desktop Supervisor

## Purpose

`client-desktop` is the primary graphical supervisor for client-site operators. It is implemented with PySide6 and targets Ubuntu and macOS. Windows is used for layout preview only; native Windows NVFlare execution is not supported.

## Launch Commands

From `share/client-supervisor`:

```bash
bash client-desktop/scripts/run-share-client.sh --env aws
```

Manual launch:

```bash
PYTHONPATH=client-desktop/src python3 -m share_desktop.main --repo-root . --env aws
```

The site is not supplied on the command line. The login response assigns it. Older `--site` arguments are accepted for shortcut compatibility but ignored.

## Login Flow

The application starts behind a login screen and calls:

```http
POST /user/role
Content-Type: application/json
```

Request:

```json
{
  "username": "client_site1"
}
```

The expected session payload includes:

```json
{
  "role": "CLIENT",
  "username": "client_site1",
  "user_id": 1,
  "client_id": 1,
  "client_name": "site1",
  "projects": []
}
```

The application requires:

- a successful response
- role `CLIENT`
- a valid `client_name`

The current development password field is not sent or validated. Sessions remain in memory and are cleared when the user signs out or closes the application.

## Persistent Header

A compact SHARE Client header remains visible on login and all supervisor pages.

- The left side displays the SHARE Client wordmark and subtitle.
- The logged-out header contains no account text.
- The logged-in header shows `User: <username> (<ROLE>@<site>)`.
- The account dropdown contains **Sign Out**.
- Runtime status is represented by app and tray icons rather than changing the header logo.

## Navigation

The left navigation contains:

- Overview
- Job Results
- NVFlare Output
- Results API
- Settings

## Overview

The Overview page displays status for:

- Startup Kit
- Federated Client
- Results Service

Primary actions include:

- Start All
- Stop Gracefully
- Force Kill NVFlare
- Quit

The page is scrollable so actions remain reachable on small windows.

## Job Results

The Job Results page reads the assigned site's managed job-save directory:

```text
~/.duality-client/<site>/job-results
```

It provides:

- manual refresh
- expandable NVFlare job rows
- modified time and size
- function subfolder summaries
- an **Explore in SHARE** action
- a **View These Results in SHARE** action under each local job row

**Explore in SHARE** sends a pako-compatible launch payload containing the active desktop session username only. SHARE decodes it and prefills the normal login form.

**View These Results in SHARE** sends the same username plus the top-level local job directory name as `nvflare_job_id`. SHARE performs the current development username lookup automatically and opens that job in Results.

Auto-refresh is intentionally disabled to avoid table selection and focus jumping. See `11-share-launch-links-and-direct-results.md` for the complete cross-application contract and the production authentication gap.

## Startup Kit Settings

The Startup Kit panel shows the login-assigned site and the fixed managed workspace:

```text
~/.duality-client/<client_name>
```

The user cannot choose another site or normal installation directory.

The panel supports:

- download and install from the backend
- cached archive installation as an offline fallback
- progress and error reporting
- existing-workspace replacement with timestamped backup

## NVFlare Output

The NVFlare page displays stdout and stderr from the site startup process. It includes actions to start the client and stop it using `startup/stop_fl.sh`.

The host environment includes:

```text
DUALITY_NVFLARE_WORKSPACE=~/.duality-client/<site>
DUALITY_NVFLARE_JOB_SAVE_LOCATION=~/.duality-client/<site>/job-results
```

## Results API Page

The Results API page controls the embedded Results API service and displays its Uvicorn output. The desktop application hosts the FastAPI app itself on a background thread rather than running `local-results-api/agent_manage.py` or a container.

The page provides start, restart, stop, and health-check actions.

Default embedded settings:

```text
host: 127.0.0.1
port: 8088
workspace: <managed workspace>
job save location: <managed workspace>/job-results
```

Because the service runs on the host, it reads the managed workspace directly instead of a read-only container mount. Uvicorn output is mirrored to:

```text
~/.duality-client/logs/results-service-output.log
```

See `06-local-results-api.md` for the embedded lifecycle, health checks, and the separate container runtime used by the terminal supervisors.

## Background Work

Network login, archive download, and archive installation run in worker threads so the Qt event loop remains responsive.

Important worker/service modules:

| Module | Role |
| --- | --- |
| `services/authentication.py` | `/user/role` request and session validation. |
| `workers/login_worker.py` | Background login execution and signals. |
| `services/startup_kit_delivery.py` | Desktop download and verification service. |
| `workers/startup_kit_worker.py` | Background provisioning workflow. |
| `runners/nvflare_runner.py` | NVFlare process lifecycle. |
| `runners/results_api_runner.py` | Embedded Uvicorn Results API lifecycle, health checks, and log capture. |
| `runners/process_runner.py` | Shared subprocess behavior. |

## Desktop State

Desktop state is stored in:

```text
~/.duality-client/desktop-state.json
```

State is keyed by site so one site's workspace is never reused for another login. A saved workspace outside `~/.duality-client/<site>` is not considered the canonical managed workspace.
