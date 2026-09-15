# Operations, Troubleshooting, and Security

## Normal Desktop Start

```bash
cd /path/to/share/client-supervisor
bash client-desktop/scripts/run-share-client.sh --env aws
```

Manual:

```bash
PYTHONPATH=client-desktop/src python3 -m share_desktop.main --repo-root . --env aws
```

## Normal Terminal Start

```bash
cd /path/to/share/client-supervisor
python3 tool_ui.py
```

## Confirm Managed Paths

```bash
find "$HOME/.duality-client" -maxdepth 3 -type d -print
```

Expected site paths:

```text
~/.duality-client/site1
~/.duality-client/site1/job-results
```

## Hidden Directory in Files Browser

`.duality-client` is hidden because its name begins with a dot. In the Ubuntu Files app, press:

```text
Ctrl+H
```

Open it directly:

```bash
xdg-open "$HOME/.duality-client"
```

## Docker Daemon Access Error

This applies to the container runtime used by `tool_ui.py`, `main.py`, and the patched startup-kit script. The desktop application hosts the Results API in its own process and does not need Docker.

Symptom:

```text
Docker CLI found but cannot access the Docker daemon
```

Fix once per Linux user:

```bash
sudo usermod -aG docker "$USER"
```

Log out of the WorkSpaces desktop:

```bash
gnome-session-quit --logout --no-prompt
```

Reconnect and verify:

```bash
docker info
```

This permission is user-specific and applies in every directory.

## Startup Kit Download Test

```bash
curl -f -v -X POST \
  "https://api.example.org/clients/content/startup-kit" \
  -H "Content-Type: application/json" \
  -d '{"client_name":"site1"}' \
  -o share-client-site1-startup-kit.tar.gz
```

Inspect without extraction:

```bash
tar -tzf share-client-site1-startup-kit.tar.gz | head -50
```

## Login Test

```bash
curl -i -X POST \
  "https://api.example.org/user/role" \
  -H "Content-Type: application/json" \
  -d '{"username":"client_site1"}'
```

## Results API Health

The health endpoint is the same in both hosting modes:

```bash
curl http://127.0.0.1:8088/health
```

Embedded desktop service output:

```bash
tail -f "$HOME/.duality-client/logs/results-service-output.log"
```

The desktop Results API page shows the same Uvicorn output, and its **Health Check** action reports the probe result. The embedded service has no container and no separate process; it shares the SHARE Client PID.

Container status and logs, for the terminal supervisors and the startup-kit-embedded script:

```bash
docker ps --filter name=duality-client-agent
docker logs -f duality-client-agent
```

If the embedded service reports that port `8088` is already in use, a previous container or process still owns it:

```bash
docker stop duality-client-agent
```

## Full Fresh-State Reset

Stop any managed NVFlare client:

```bash
for stop_script in "$HOME"/.duality-client/site*/startup/stop_fl.sh; do
  [ -f "$stop_script" ] && (cd "$(dirname "$stop_script")" && bash ./stop_fl.sh) || true
done
```

Stop the embedded Results API by quitting SHARE Client. It runs inside that process and stops with it.

Remove the Results API container if the terminal supervisors or a patched startup script created one:

```bash
docker rm -f duality-client-agent 2>/dev/null || true
```

Remove all supervisor state, cached archives, installed startup kits, backups, tokens, and job results:

```bash
rm -rf "$HOME/.duality-client"
```

Remove state files from older terminal builds:

```bash
rm -f "$HOME/.duality_client_state.json" \
      "$HOME/.duality_client_env.sh" \
      "$HOME/.duality_client_env.cmd"
```

Remove persisted older exports from `.bashrc`:

```bash
sed -i -E '/^export (DUALITY_TOOLKIT_ROOT|DUALITY_CLIENT_SITE|DUALITY_CLIENT_ENV|DUALITY_CLIENT_WORKSPACE|DUALITY_NVFLARE_WORKSPACE|DUALITY_NVFLARE_JOB_SAVE_LOCATION|DUALITY_NVFLARE_FHIR_BASE_CONFIG)=/d' "$HOME/.bashrc"
```

Clear the current shell:

```bash
unset DUALITY_TOOLKIT_ROOT \
      DUALITY_CLIENT_SITE \
      DUALITY_CLIENT_ENV \
      DUALITY_CLIENT_WORKSPACE \
      DUALITY_NVFLARE_WORKSPACE \
      DUALITY_NVFLARE_JOB_SAVE_LOCATION \
      DUALITY_NVFLARE_FHIR_BASE_CONFIG
```

## Authorization Warning

The desktop removes arbitrary site selection from normal UI flow, but UI restrictions are not authorization. Until the backend validates an authenticated identity against an allowed site, a caller who can reach the endpoint could construct a request body manually.

Production authorization must bind the authenticated user to the permitted client site on the server and reject any mismatch before packaging credentials.

## SHARE Launch-Link Security

The desktop's SHARE links currently use a reversible compressed JSON payload. A username-only payload prefills login; a username plus `nvflare_job_id` triggers the current direct-results username lookup.

This is not authentication. The payload is not encrypted or signed, `/user/role` currently trusts the username, and the backend direct-results context route does not yet enforce job ownership. Treat the feature as a development convenience inside the current trusted environment.

This version ships no authentication provider and is not supported for production use. Any production deployment must replace username trust with an authenticated, backend-issued, short-lived launch code. Prefer an opaque single-use code that binds the authenticated subject, intended action, optional job ID, expiration, and authorization context. Do not place raw identity or access tokens in the URL.

See `11-share-launch-links-and-direct-results.md` for the complete current protocol.
