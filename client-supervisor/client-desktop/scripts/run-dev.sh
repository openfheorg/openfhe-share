#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/.." && pwd)"
cd "$APP_DIR"
export PYTHONPATH="$APP_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m share_desktop.main --repo-root "$REPO_ROOT" "$@"
