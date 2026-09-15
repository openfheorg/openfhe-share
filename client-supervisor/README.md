# SHARE Client Supervisor

Local supervisor tooling for provisioning and running a SHARE NVFlare client and its local Results API.

This project lives at:

```text
share/client-supervisor
```

Expected sibling monorepo layout:

```text
share/
├── client-supervisor/
│   ├── client-desktop/
│   ├── local-results-api/
│   ├── test_data/
│   ├── install.ini
│   ├── main.py
│   ├── startup_kit_delivery.py
│   └── tool_ui.py
└── standalone/
    ├── .env.local
    └── nvflare_stage/data/
```

## Startup-kit provisioning

The old `tar_files` staging directory is no longer used. `main.py` and `tool_ui.py` request the selected site directly from the backend content-delivery endpoint:

```text
POST /clients/content/startup-kit
```

Downloaded archives are checksum-validated when the backend supplies a checksum, cached under `~/.duality-client/inbox`, and installed as persistent per-user application data:

```text
~/.duality-client/<site>
```

The workspace and its `job-results` directory therefore survive moving, replacing, or recloning `share/client-supervisor`.

If an existing site workspace is replaced, it is renamed to a timestamped backup first. The installed workspace receives a `job-results` directory and that path is exported as `DUALITY_NVFLARE_JOB_SAVE_LOCATION`.

Override the backend base URL with either:

```text
DUALITY_CONTENT_API_BASE_URL
DUALITY_BACKEND_URL
```

## Datasource files

`client-supervisor/test_data` contains only the per-site FHIR base configuration JSON files.

Actual local datasource JSON or ZIP files are resolved from:

```text
share/standalone/nvflare_stage/data
```

The supervisor also loads `share/standalone/.env.local` and honors the same datasource keys used by the standalone client builder, such as:

```text
DUALITY_CLIENT_SITE1_DATASOURCE_2_1
```

An explicit `.env.local` mapping takes precedence over a filename lookup in `standalone/nvflare_stage/data`.

## Results API

The shared Results API implementation and its headless Docker wrapper live at:

```text
client-supervisor/local-results-api
```

The desktop and terminal supervisors use it differently:

- `client-desktop` imports the shared FastAPI application and runs Uvicorn inside the SHARE Client process on `127.0.0.1:8088`. No Results API container is required for the desktop app.
- `main.py` and `tool_ui.py` retain the Docker workflow through `local-results-api/agent_manage.py` for headless or terminal-only Ubuntu deployments.

Both modes read the same managed site results directory:

```text
~/.duality-client/<site>/job-results
```

## Python library wheel

There is no local wheel-selection or wheel-install workflow in the supervisor. The Duality NVFlare library is installed by a submitted job when needed.

## Run the terminal supervisor

```bash
cd share/client-supervisor
python3 tool_ui.py
```

The first menu option asks for a site and environment, downloads and installs the current startup kit, syncs configured datasource files, starts NVFlare, and builds/deploys the local Results API.

## Run directly

```bash
cd share/client-supervisor
python3 main.py client --site site1 --env aws --os ubuntu
```

Optional startup-kit API override:

```bash
python3 main.py client \
  --site site1 \
  --env aws \
  --os ubuntu \
  --content-api-base https://api.example.org
```

## Run the desktop supervisor

```bash
cd share/client-supervisor
bash client-desktop/scripts/run-share-client.sh --env aws
```
