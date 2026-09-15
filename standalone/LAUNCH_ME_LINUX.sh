#!/usr/bin/env bash
set -euo pipefail

# Change to the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Allow override via env var
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PY="$PYTHON_BIN"
else
  # Prefer python3, fall back to python
  if command -v python3 >/dev/null 2>&1; then
    PY="python3"
  elif command -v python >/dev/null 2>&1; then
    PY="python"
  else
    echo "[ERROR] Python not found on PATH. Install it or set PYTHON_BIN."
    exit 1
  fi
fi

if command -v docker >/dev/null 2>&1; then
  if ! docker_err="$(docker ps 2>&1 >/dev/null)"; then
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
      echo "[ERROR] Docker preflight failed."
      if [[ -n "${docker_err:-}" ]]; then
        echo "[INFO] ${docker_err}"
      fi
      if [[ "${docker_err,,}" == *"permission denied while trying to connect to the docker daemon socket"* ]]; then
        echo "[INFO] Rerun with elevated privileges on this machine:"
        echo "       sudo ./LAUNCH_ME_LINUX.sh"
      else
        echo "[INFO] Fix Docker first, then rerun the launcher."
      fi
      exit 1
    fi
  fi
fi

exec "$PY" main.py ui "$@"
