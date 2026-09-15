#!/usr/bin/env bash
set -u

# SHARE Client bootstrap launcher for Ubuntu desktop.
# Safe to run without sudo. Installs Python GUI deps into the current user's account.
# The client site is assigned by the SHARE login response, not by this script.
# Usage from the client-supervisor root:
#   bash client-desktop/scripts/run-share-client.sh --env aws

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$CLIENT_DESKTOP_DIR/.." && pwd)"
CONFIG_FILE="$CLIENT_DESKTOP_DIR/share-client.ini"

info() { echo "[SHARE Client] $*"; }

show_error() {
  local message="$1"
  if command -v zenity >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
    zenity --error --title="SHARE Client" --text="$message" >/dev/null 2>&1 || true
  else
    echo "ERROR: $message" >&2
  fi
}

get_ini_value() {
  local section="$1"
  local key="$2"
  local fallback="$3"
  if [[ -f "$CONFIG_FILE" ]]; then
    python3 - "$CONFIG_FILE" "$section" "$key" "$fallback" <<'PY'
import configparser
import sys
path, section, key, fallback = sys.argv[1:5]
config = configparser.ConfigParser()
config.read(path)
print(config.get(section, key, fallback=fallback))
PY
  else
    printf '%s\n' "$fallback"
  fi
}

DEFAULT_ENV="$(get_ini_value client default_env aws)"
ENV_NAME="${SHARE_CLIENT_ENV:-$DEFAULT_ENV}"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_NAME="${2:-}"
      shift 2
      ;;
    --site)
      # Compatibility with older shortcuts. Site selection is intentionally ignored.
      info "Ignoring deprecated --site argument; site is assigned after login."
      shift 2
      ;;
    --repo-root)
      # This launcher derives the client-supervisor root from its own location.
      shift 2
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

ensure_deps() {
  python3 - <<'PY' >/dev/null 2>&1
import PySide6  # noqa
import requests  # noqa
import fastapi  # noqa
import uvicorn  # noqa
import pydantic  # noqa
PY
  if [[ $? -eq 0 ]]; then
    return 0
  fi

  info "SHARE Client Python dependencies missing; installing into the current user account..."

  if ! python3 -m pip --version >/dev/null 2>&1; then
    show_error "python3-pip is not available. Install python3-pip once, then rerun SHARE Client."
    return 1
  fi

  local log_file="/tmp/share-client-pip-install.log"
  rm -f "$log_file"

  if command -v zenity >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
    (
      echo "10"
      echo "# Installing SHARE Client and embedded Results API dependencies..."
      python3 -m pip install --user PySide6 requests -r "$REPO_ROOT/local-results-api/requirements.txt" >"$log_file" 2>&1 \
        || python3 -m pip install --user --break-system-packages PySide6 requests -r "$REPO_ROOT/local-results-api/requirements.txt" >>"$log_file" 2>&1
      rc=$?
      echo "100"
      exit $rc
    ) | zenity --progress --title="SHARE Client" --text="Installing Python dependencies..." --percentage=0 --auto-close >/dev/null 2>&1
    rc=${PIPESTATUS[0]}
  else
    python3 -m pip install --user PySide6 requests -r "$REPO_ROOT/local-results-api/requirements.txt" \
      || python3 -m pip install --user --break-system-packages PySide6 requests -r "$REPO_ROOT/local-results-api/requirements.txt"
    rc=$?
  fi

  if [[ $rc -ne 0 ]]; then
    show_error "Failed to install Python dependencies. Check $log_file."
    return $rc
  fi

  python3 - <<'PY' >/dev/null 2>&1
import PySide6  # noqa
import requests  # noqa
import fastapi  # noqa
import uvicorn  # noqa
import pydantic  # noqa
PY
}

ensure_deps || exit 1

export PYTHONPATH="$CLIENT_DESKTOP_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
info "Repo root: $REPO_ROOT"
info "Env: $ENV_NAME"
info "Client site: assigned after login"

exec python3 -m share_desktop.main --repo-root "$REPO_ROOT" --env "$ENV_NAME" "${EXTRA_ARGS[@]}"
