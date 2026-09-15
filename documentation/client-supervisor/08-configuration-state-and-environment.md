# Configuration, State, and Environment

## Desktop Configuration

Default desktop configuration:

```text
client-desktop/share-client.ini
```

Optional machine-specific override:

```text
~/.duality-client/share-client.ini
```

Important sections:

```ini
[client]
default_env = aws

[authentication]
api_base_url = https://api.example.org
user_role_path = /user/role
login_timeout_seconds = 30

[share]
url = https://dev-app.example.org/?s=0
recent_urls = https://dev-app.example.org/?s=0,http://localhost:3000

[content_delivery]
api_base_url = https://api.example.org
startup_kit_path = /clients/content/startup-kit
download_timeout_seconds = 300

[startup_kit]
extract_base = app_home

[nvflare]
job_results_dir_name = job-results

[results]
port = 8088
health_interval_seconds = 30
```

No site is stored in the default configuration. The desktop session supplies it.

The desktop hosts the Results API as an embedded Uvicorn service, so `[results].port` is the local bind port on `127.0.0.1` and no container name is configured here. The container name and image used by the terminal supervisors are `agent_manage.py` defaults:

```text
image: duality-client-agent:local
container: duality-client-agent
port: 8088
```

`[share].url` is the browser destination used by **Explore in SHARE** and **View These Results in SHARE**. `recent_urls` populates the Settings dropdown. The launch builder preserves unrelated query parameters such as `s=0` and replaces only stale `launch`, `username`, and `nvflare_job_id` fields.

## Desktop State

```text
~/.duality-client/desktop-state.json
```

The desktop records per-site managed workspace and cached archive information. It also retains the selected SHARE URL and Results port. The workspace is still derived and validated against `~/.duality-client/<site>`. Login identity and launch tokens are not persisted in this file.

## Terminal State

```text
~/.duality-client/tool-ui-state.json
~/.duality-client/tool-ui-env.sh
~/.duality-client/tool-ui-env.cmd
```

The terminal supervisor remembers the last site/environment and managed workspace mapping.

## Runtime Environment Variables

| Variable | Meaning |
| --- | --- |
| `DUALITY_CLIENT_SITE` | Active NVFlare site. |
| `DUALITY_CLIENT_ENV` | Environment label such as `aws`. |
| `DUALITY_CLIENT_WORKSPACE` | Host managed workspace. |
| `DUALITY_NVFLARE_WORKSPACE` | Host managed workspace for NVFlare. |
| `DUALITY_NVFLARE_JOB_SAVE_LOCATION` | Host job-result directory. |
| `DUALITY_NVFLARE_FHIR_BASE_CONFIG` | Site configuration JSON used by local setup/sync logic. |
| `DUALITY_CONTENT_API_BASE_URL` | Startup-kit backend base override. |
| `DUALITY_BACKEND_URL` | General backend base fallback. |
| `DUALITY_STARTUP_KIT_PATH` | Startup-kit endpoint path override. |
| `DUALITY_CLIENT_AGENT_TOKEN` | Token used by the local Results API. Set by `agent_manage.py` for the container runtime; the embedded desktop service does not set it. |
| `DUALITY_UI_ORIGINS` | Extra CORS origins for the local Results API. |
| `DUALITY_SERVER_WORKSPACE` | Existing server workspace for the limited server command. |

## State Versus Runtime Data

Deleting only state does not need to delete the installed site or its job history:

```bash
rm -f "$HOME/.duality-client/desktop-state.json"
rm -f "$HOME/.duality-client/tool-ui-state.json"
```

Deleting the entire app home removes all cached archives, installed startup kits, backups, state, tokens, and job results:

```bash
rm -rf "$HOME/.duality-client"
```

Use the full removal only when a completely fresh machine state is intended.
