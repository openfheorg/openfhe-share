# SHARE Client Supervisor Overview

## Purpose

`share/client-supervisor` is the local supervisor layer for a SHARE client site. It provisions the site-specific NVFlare startup kit, keeps the installed client workspace outside the source checkout, runs the NVFlare client, runs the local Results API, monitors both runtimes, and exposes local job-result history.

The project currently provides two operator experiences:

- **SHARE Client Desktop**: the primary PySide6 desktop supervisor for Ubuntu and macOS client sites.
- **Terminal supervisor**: `tool_ui.py`, a menu-driven terminal interface for headless or minimal Ubuntu systems.

The desktop supervisor is login-gated. The terminal supervisor does not use login yet; it prompts for a site and uses the same startup-kit delivery service.

## Major Responsibilities

- Resolve the client site from the desktop login session or a terminal prompt.
- Request the current site startup kit from the backend.
- Validate the downloaded tar and backend checksum.
- Install the site under `~/.duality-client/<site>`.
- Preserve the startup kit and job results independently of the Git checkout.
- Start and stop the NVFlare client.
- Start, stop, and health-check the local Results API. The desktop hosts it as an embedded Uvicorn service; the terminal supervisors build and run it as a Docker container.
- Give the Results API access to the managed site workspace, directly on the host in embedded mode and through a read-only mount in container mode.
- Keep the NVFlare and Results API job-save locations consistent, on the host in embedded mode and between host and container in container mode.
- Show NVFlare logs, Results API logs, runtime state, and local job history.
- Open SHARE for general exploration with the current username prefilled.
- Open a specific NVFlare job directly in SHARE Results by passing the current username and the job-folder UUID in a pako-compatible launch payload.
- Sync datasource files using the standalone runtime's `.env.local` and data directory.

## Current End-to-End Desktop Flow

1. Launch SHARE Client from `share/client-supervisor`.
2. Display the SHARE-branded login screen.
3. Send the username to `POST /user/role`.
4. Require a `CLIENT` session with a valid `client_name` such as `site1`.
5. Bind all site-dependent behavior to the returned `client_name`.
6. If the managed workspace is absent, download the site archive from `POST /clients/content/startup-kit`.
7. Validate and install the archive under `~/.duality-client/<site>`.
8. Create `~/.duality-client/<site>/job-results`.
9. Start the NVFlare client from `<workspace>/startup/start.sh`.
10. Start the local Results API as an embedded Uvicorn service inside the desktop process. The terminal supervisor and `main.py` instead build or start the container from `local-results-api/agent_manage.py`.
11. Monitor both services and display their logs and status.
12. Keep the workspace, downloaded archive, state, and job results when the source checkout moves or is replaced.

## Documentation Map

| Area | Primary files | Document |
| --- | --- | --- |
| Repository and runtime layout | project root, `client-desktop/`, `local-results-api/`, `test_data/` | `02-repository-and-runtime-layout.md` |
| Desktop application | `client-desktop/src/share_desktop/` | `03-desktop-supervisor.md` |
| Terminal and direct CLI flows | `tool_ui.py`, `main.py` | `04-terminal-supervisor-and-main-cli.md` |
| Startup-kit delivery and persistent workspace | `startup_kit_delivery.py` | `05-startup-kit-delivery-and-managed-workspace.md` |
| Local Results API | `local-results-api/` | `06-local-results-api.md` |
| Datasource configuration and staging | `install.ini`, `test_data/`, standalone data paths | `07-datasource-configuration-and-sync.md` |
| Configuration and saved state | INI files, JSON state, environment exports | `08-configuration-state-and-environment.md` |
| Operations, reset, and troubleshooting | all runtime components | `09-operations-troubleshooting-and-security.md` |
| Code map | complete supervisor tree | `10-client-supervisor-code-map.md` |
| SHARE launch links and direct Results | desktop browser actions, pako-compatible payload, frontend bootstrap, backend context lookup, production authentication gap | `11-share-launch-links-and-direct-results.md` |

## Current Security Boundary

The desktop login and SHARE launch links currently use the same development username lookup as the React application. They establish the normal site-selection and direct-results flows but are not yet a complete authentication and authorization system:

- The password field is displayed but is not validated by the current backend lookup.
- The desktop trusts the `client_name` returned by `/user/role`.
- The startup-kit endpoint still accepts `client_name` in the request body.
- The backend must eventually derive or validate the authorized site from authenticated credentials.
- The encoded SHARE launch payload is reversible and must not be treated as a credential.
- Direct Results currently bypasses only the prototype login screen; any production deployment must replace username trust with an authenticated, short-lived launch-code exchange.

Startup kits include site credentials, so the delivery endpoint must remain controlled until server-side authorization is completed. See `11-share-launch-links-and-direct-results.md` for the launch-link security boundary.

## Tested State

The desktop login, site assignment, startup-kit download, managed installation, NVFlare startup, and local Results API workflow have been tested successfully for `client_site1` and `client_site2`.
