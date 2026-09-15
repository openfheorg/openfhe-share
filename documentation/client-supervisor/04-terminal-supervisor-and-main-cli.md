# Terminal Supervisor and Main CLI

## Terminal Supervisor

`tool_ui.py` is the menu-driven terminal supervisor intended for terminal-only or headless Ubuntu use.

Run it from `share/client-supervisor`:

```bash
python3 tool_ui.py
```

It currently prompts for a site rather than logging in. Login parity with the desktop app is planned separately.

## Terminal Menu

The current menu provides operations for:

1. Download/install startup kit, start NVFlare, and build the Results API.
2. Start NVFlare.
3. Stop NVFlare.
4. Build/deploy the Results API.
5. Start/restart the Results API.
6. Stop the Results API.
7. Show the Results API token for a workspace.
8. Install or reinstall liboqs.
9. Refresh or display overview state.
10. Quit.

The exact displayed wording may evolve, but all site workspaces resolve to:

```text
~/.duality-client/<site>
```

## Terminal State

`tool_ui.py` stores its state under:

```text
~/.duality-client/tool-ui-state.json
```

It also generates shell environment helper files:

```text
~/.duality-client/tool-ui-env.sh
~/.duality-client/tool-ui-env.cmd
```

## Direct Client Command

The direct CLI entrypoint is `main.py`.

Example:

```bash
python3 main.py client --site site1 --env aws --os ubuntu
```

When `--site` is omitted in an interactive terminal, the CLI prompts for it:

```bash
python3 main.py client --env aws --os ubuntu
```

In non-interactive use, `--site` is required.

## Client Options

| Option | Purpose |
| --- | --- |
| `--site` | NVFlare client name. Optional only in interactive mode. |
| `--env` | Runtime environment label persisted for the client. |
| `--os` | Platform handling, such as `ubuntu`. |
| `--installdeps` | Install supported Ubuntu Python dependencies. |
| `--venv` | Re-execute inside the selected virtual environment. |
| `--breaksystempackages` | Pass Ubuntu's system-package override to pip where supported. |
| `--install-base` | Parent directory for the site workspace. Defaults to `~/.duality-client`; normal supervisor flows should retain this default. |
| `--content-api-base` | Override the startup-kit service base URL. |
| `--download-timeout` | Download timeout in seconds. Default `300`. |

## Direct Client Flow

`main.py client` performs these steps:

1. Validate or prompt for the site.
2. Load `share/standalone/.env.local`.
3. Load `client-supervisor/install.ini`.
4. Optionally install Ubuntu dependencies.
5. Configure liboqs environment values on Ubuntu.
6. Install or refresh `nvflare==2.7.2`.
7. Resolve the site's FHIR configuration JSON.
8. Sync configured datasource files.
9. Download the current startup kit from the backend.
10. Validate and install it under the selected install base, normally `~/.duality-client/<site>`.
11. Create the site's `job-results` directory.
12. Export and persist site/workspace/job-result environment variables.
13. Copy the local Results API management script into the startup directory for compatibility.
14. Patch the startup script when needed so the local Results API can start with the client.
15. Build/deploy the local Results API.
16. Launch the NVFlare startup script.

## Other Commands

### Update datasource files

```bash
python3 main.py update_data --site site1
```

Options:

- `--overwrite`
- `--no-overwrite`

Without `--site`, all configured site entries are processed.

### Install liboqs

```bash
python3 main.py install_liboqs --os ubuntu
```

Force reinstall:

```bash
python3 main.py install_liboqs --os ubuntu --force_reinstall
```

### Start an existing server workspace

The supervisor no longer provisions server archives. A server command must point to an already existing workspace:

```bash
python3 main.py server --env aws --os ubuntu --workspace /path/to/server-workspace
```

Alternatively set `DUALITY_SERVER_WORKSPACE`.

## No Wheel Workflow

The CLI does not ask users to select or install a Duality wheel. Submitted jobs install the required Duality NVFlare package when needed.
