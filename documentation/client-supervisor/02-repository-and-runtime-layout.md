# Repository and Runtime Layout

## Monorepo Location

The project lives under the SHARE monorepo:

```text
share/
├── backend/
├── frontend/
├── standalone/
└── client-supervisor/
```

The supervisor source checkout is replaceable application code. Installed client runtime data is stored separately under the user's home directory.

## Source Layout

```text
client-supervisor/
├── client-desktop/
├── local-results-api/
├── test_data/
├── install.ini
├── main.py
├── startup_kit_delivery.py
├── tool_ui.py
├── README.md
└── .gitignore
```

| Path | Role |
| --- | --- |
| `client-desktop/` | PySide6 desktop supervisor, login UI, service controls, job-result browser, logs, state handling, and branding assets. |
| `local-results-api/` | FastAPI service that reads local NVFlare job results, hosted in-process by the desktop supervisor or as a Docker container by the terminal supervisors. |
| `test_data/` | Configuration JSON files that define datasource destinations. It does not contain the actual datasource corpus. |
| `install.ini` | Maps sites to their configuration JSON files and retains the configured server name. |
| `main.py` | Direct CLI for client provisioning, datasource sync, NVFlare setup, Results API build/start, and limited server startup. |
| `startup_kit_delivery.py` | Shared startup-kit download, validation, checksum, safe extraction, backup, and managed-install logic. |
| `tool_ui.py` | Menu-driven terminal supervisor. |

## Expected Sibling Layout

The supervisor uses data and environment configuration from the standalone project:

```text
share/
├── client-supervisor/
└── standalone/
    ├── .env.local
    └── nvflare_stage/
        └── data/
```

The actual datasource JSON or ZIP files are resolved from:

```text
share/standalone/nvflare_stage/data
```

The supervisor loads datasource mappings from:

```text
share/standalone/.env.local
```

## Persistent Runtime Layout

Per-user runtime data is stored under:

```text
~/.duality-client/
```

Typical layout:

```text
~/.duality-client/
├── desktop-state.json
├── tool-ui-state.json
├── tool-ui-env.sh
├── tool-ui-env.cmd
├── share-client.ini
├── inbox/
│   ├── share-client-site1-startup-kit.tar.gz
│   └── share-client-site2-startup-kit.tar.gz
├── logs/
│   └── results-service-output.log
├── site1/
│   ├── startup/
│   ├── local/
│   ├── transfer/
│   └── job-results/
└── site2/
    ├── startup/
    ├── local/
    ├── transfer/
    └── job-results/
```

The source checkout can move from one directory to another without moving the installed startup kit or local job history.

## Path Responsibilities

| Data | Canonical path |
| --- | --- |
| Cached downloaded archive | `~/.duality-client/inbox/share-client-<site>-startup-kit.tar.gz` |
| Installed site workspace | `~/.duality-client/<site>` |
| Host job results | `~/.duality-client/<site>/job-results` |
| Results API workspace, container runtime only | `/nvflare` |
| Results API job results, container runtime only | `/nvflare/job-results` |
| Results API workspace, embedded runtime | `~/.duality-client/<site>` |
| Results API job results, embedded runtime | `~/.duality-client/<site>/job-results` |
| Embedded Results API output log | `~/.duality-client/logs/results-service-output.log` |
| Desktop state | `~/.duality-client/desktop-state.json` |
| Terminal state | `~/.duality-client/tool-ui-state.json` |
| Optional desktop override config | `~/.duality-client/share-client.ini` |

## Removed Legacy Inputs

The supervisor no longer contains or depends on:

- a repository `tar_files/` directory
- a repository `wheels/` directory
- a user-selected Duality wheel install flow
- the retired name previously used for the local Results API directory
- source-checkout-local installed site workspaces

The Duality NVFlare library is installed by submitted jobs when needed. The local results service is now named `local-results-api`.
