from __future__ import annotations

import os
from pathlib import Path

APP_HOME = Path.home() / ".duality-client"
INBOX_DIR = APP_HOME / "inbox"
# Managed site workspaces are installed directly beneath APP_HOME, such as
# ~/.duality-client/site1. Keep the legacy name as an alias for existing callers.
WORKSPACES_DIR = APP_HOME
LOGS_DIR = APP_HOME / "logs"
STATE_PATH = APP_HOME / "desktop-state.json"


def ensure_app_dirs() -> None:
    for path in [APP_HOME, INBOX_DIR, LOGS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def resolve_repo_root(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    env_root = os.environ.get("DUALITY_TOOLKIT_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend([Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[3]])

    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "local-results-api" / "app" / "main.py").exists() and (root / "install.ini").exists():
            return root

    # Fall back to cwd. The UI will report a missing Results API application if needed.
    return Path.cwd().resolve()
