#!/usr/bin/env bash
# macOS launcher for LocWarp dev mode. The backend runs as the regular
# user; only the tunnel helper runs as root (sudo prompt fires inside
# start.py when needed).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "  LocWarp macOS Launcher"
echo "  iOS 17+ 需要 root 權限建立裝置通道 (sudo prompt will fire for the helper)"
echo

# Prefer the project venv — it carries the FULL backend deps (timezonefinder,
# numpy, tzdata, pymobiledevice3). A bare `python3` (e.g. a pyenv shim) may be
# missing timezonefinder/numpy, which silently kills the offline geo + timezone
# resolver (ModuleNotFoundError -> _load_failed latch -> empty results forever).
# Build the venv once:
#   python3 -m venv backend/.venv
#   backend/.venv/bin/python -m pip install -r backend/requirements.txt
PY="$SCRIPT_DIR/backend/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "  ⚠ backend/.venv not found — falling back to 'python3' (may lack timezonefinder/numpy)."
    echo "    Build it: python3 -m venv backend/.venv && backend/.venv/bin/python -m pip install -r backend/requirements.txt"
    PY="python3"
fi

exec "$PY" "$SCRIPT_DIR/start.py" "$@"
