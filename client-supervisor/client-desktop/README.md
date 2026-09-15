# SHARE Client Desktop

Desktop supervisor for the SHARE client experience. The app manages an authenticated site's NVFlare startup kit, embedded local Results API, health/status recovery, and local job-result history.

## Login and assigned-site flow

SHARE Client now opens behind a login screen and uses the same lookup as the React application:

```http
POST /user/role
Content-Type: application/json
```

```json
{
  "username": "client_site4"
}
```

The backend response supplies `role`, `username`, `user_id`, `client_id`, `client_name`, and `projects`. The desktop app requires a `CLIENT` account with a valid `client_name`, such as `site4`.

The site is no longer configurable or selectable in the desktop UI. After login, `client_name` becomes the sole source for:

- Startup-kit download and archive validation
- Workspace installation and lookup
- NVFlare process environment
- Embedded Results API workspace and job-results path
- Local `job-results` path

The current development endpoint does not validate the password field, matching the React login page. The desktop login card uses the same labels, development note, and supplied login illustration. Login sessions remain in memory only and are cleared when the app closes or the user signs out.

## Persistent header

A compact SHARE header remains visible on the login screen and every supervisor page. It now mirrors the React application more closely:

- The supplied SHARE wordmark is displayed at the left.
- The logged-out header contains no account-status text.
- The header uses the dedicated SHARE Client wordmark while retaining the Secure Healthcare Data Collaboration Platform subtitle.
- After login, the account summary reads `User: <username> (<ROLE>@<site>)`.
- The adjacent dropdown contains the **Sign Out** action.

Runtime status remains represented by the application and tray icons rather than changing the header wordmark.

## Startup-kit delivery flow

The Startup Kit panel in **Settings** can:

1. Display the site assigned by login.
2. Use the fixed managed workspace `~/.duality-client/<client_name>`.
3. Request the assigned site's tar from the backend.
4. Stream the download into `~/.duality-client/inbox`.
5. Verify the backend SHA-256 header when present.
6. Validate that the archive contains exactly one matching site root and `startup/start.sh`.
7. Extract through a temporary staging directory.
8. Move the completed site folder into `~/.duality-client/<client_name>`.
9. Create `~/.duality-client/<client_name>/job-results`.
10. Persist workspace information separately for each assigned site in `~/.duality-client/desktop-state.json`.

The existing-archive installation controls remain available as an offline fallback using archives cached in `~/.duality-client/inbox`, and the archive must match the site assigned by login.

## Runtime assumptions

- Ubuntu or macOS with Python 3.10+
- Python packages for PySide6, requests, FastAPI, Uvicorn, and Pydantic
- Existing `share/client-supervisor` layout containing:
  - `install.ini`
  - `local-results-api/app/main.py`
- Docker is **not required** by the desktop Results API. Docker remains available to `main.py` and `tool_ui.py` for terminal/headless deployments.
- Windows is supported for UI/layout preview, but native Windows NVFlare execution is not supported.

## Embedded Results API

The desktop app imports the shared FastAPI application from `local-results-api/app/main.py` and runs Uvicorn on a dedicated background thread:

```text
http://127.0.0.1:8088
```

The Qt UI remains responsive and displays Uvicorn/application output directly. The service reads results from:

```text
~/.duality-client/<client_name>/job-results
```

The Results API page provides **Start Results Service**, **Restart Results Service**, **Stop Results Service**, and **Health Check** controls. Repeated periodic health failures trigger a controlled restart, and unexpected Uvicorn exits are retried up to three times. Closing the window to the tray keeps the API running; choosing **Quit** stops the embedded server. Signing out also stops it so a new account cannot inherit the previous site's Results API workspace.

A legacy Docker container on port 8088 must be stopped before starting embedded mode:

```bash
docker stop duality-client-agent 2>/dev/null || true
```

## Configuration

Default settings live in:

```text
client-desktop/share-client.ini
```

Important values:

```ini
[client]
default_env = aws

[authentication]
api_base_url = https://api.example.org
user_role_path = /user/role
login_timeout_seconds = 30

[content_delivery]
api_base_url = https://api.example.org
startup_kit_path = /clients/content/startup-kit
download_timeout_seconds = 300
```

The assigned client site is deliberately absent from configuration.

Optional machine overrides are loaded from:

```text
~/.duality-client/share-client.ini
```

## Run from source

From the `share/client-supervisor` root:

```bash
bash client-desktop/scripts/run-share-client.sh --env aws
```

Manual command:

```bash
PYTHONPATH=client-desktop/src python3 -m share_desktop.main --repo-root . --env aws
```

Older shortcuts that still pass `--site` will continue to launch, but the argument is ignored. The login response assigns the site.

## Clean login/provisioning test

1. Stop NVFlare and stop any legacy Results API container using port 8088.
2. Remove or rename the existing managed workspace, such as `~/.duality-client/site4`.
3. Remove the assigned site's cached archive from `~/.duality-client/inbox`.
4. Launch SHARE Client.
5. Log in with a CLIENT username mapped to the desired site.
6. Confirm the header and Settings page show the returned `client_name`.
7. Confirm Settings shows `~/.duality-client/<client_name>` as the managed workspace.
8. Click **Download and Install Startup Kit**.
9. Confirm `~/.duality-client/<client_name>` and its `job-results` directory are created.
10. Click **Start All** and confirm both NVFlare and the embedded Results API become healthy.

## Current security boundary

The login lookup establishes the desktop site's normal application flow, but it is not yet a complete authorization system. The backend startup-kit endpoint must eventually derive or validate the allowed site from authenticated credentials rather than trusting `client_name` supplied in a request body.

## SHARE launch links

The authenticated username is passed to the web application through its pako-compatible `launch` query payload.

- **Explore in SHARE** sends `{ "v": 1, "username": "..." }`.
- **View These Results in SHARE** additionally sends `{ "nvflare_job_id": "<job-folder-uuid>" }`.

The payload is compact UTF-8 JSON, zlib-wrapped DEFLATE (compatible with `pako.inflate`), then unpadded URL-safe Base64. The username and job ID are not exposed as separate plain-text query parameters.

