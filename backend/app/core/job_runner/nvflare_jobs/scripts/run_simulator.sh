#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOBS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WHEELS_DIR="$JOBS_DIR/wheels"

python3 "$WHEELS_DIR/APIWheelBuilderCI.py" --root "$JOBS_DIR" --out-dir "$WHEELS_DIR"
LOCAL_WHEEL="$(find "$WHEELS_DIR" -maxdepth 1 -type f -name 'duality_nvflare_lib-*.whl' | sort | tail -n 1)"
if [ -z "$LOCAL_WHEEL" ]; then
  echo "ERROR: local duality_nvflare_lib wheel was not produced." >&2
  exit 20
fi

python3 -m pip install --force-reinstall --no-index --no-deps "$LOCAL_WHEEL"
DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1 \
  python3 "$SCRIPT_DIR/run_simulator.py" -w outputs/stat_analytics -n 2 -t 2 \
  "$JOBS_DIR/jobs/nvflare_job_template" --datasource-version 2_1
