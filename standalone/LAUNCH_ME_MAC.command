#!/bin/bash

# Always run from the directory this file lives in
cd "$(dirname "$0")" || exit 1

# Pick a Python
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PY="$PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[ERROR] Python not found on PATH. Install it or set PYTHON_BIN."
  echo
  read -rp "Press Enter to close..." _
  exit 1
fi

# Run the UI (no exec so the script continues afterward)
"$PY" main.py ui "$@"
status=$?

echo
echo "Duality UI exited with status: $status"
read -rp "Press Enter to close this window..." _
exit "$status"
