#!/usr/bin/env bash
# LocWarp one-shot Mac build: backend binary + Electron DMG.
# Prereqs (install once):
#   - Python 3.11 (or matching backend requirement) + venv with requirements*.txt
#   - Node 20+ with frontend/node_modules installed
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

bash "$ROOT/scripts/kill-all.sh"

echo
echo "============================================================"
echo " [1/3] Build backend with PyInstaller"
echo "============================================================"
cd "$ROOT/backend"
if [[ ! -f "$ROOT/backend/.venv/bin/activate" ]]; then
    echo "==> Bootstrapping backend/.venv (first-time setup)"
    python3 -m venv "$ROOT/backend/.venv"
    # shellcheck disable=SC1091
    source "$ROOT/backend/.venv/bin/activate"
    python -m pip install --upgrade pip
    pip install -r "$ROOT/backend/requirements.txt" -r "$ROOT/backend/requirements-build.txt"
else
    # shellcheck disable=SC1091
    source "$ROOT/backend/.venv/bin/activate"
fi
python3 -m PyInstaller locwarp-backend.spec --noconfirm \
    --distpath "$ROOT/dist-py" \
    --workpath "$ROOT/build-py/backend"

echo
echo "============================================================"
echo " [2/3] Build frontend with Vite"
echo "============================================================"
cd "$ROOT/frontend"
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "==> Bootstrapping frontend/node_modules (first-time setup)"
    npm install
fi
npm run build

echo
echo "============================================================"
echo " [3/3] Package Electron DMG"
echo "============================================================"
npm run dist:mac

echo
echo "============================================================"
echo " [4/4] Ad-hoc re-sign app bundle"
echo "============================================================"
APP="$ROOT/frontend/release/mac-arm64/LocWarp.app"
codesign --force --deep --sign - "$APP"
echo "Signed: $APP"

echo
echo "Done. DMG in $ROOT/frontend/release/"
ls -lh "$ROOT/frontend/release"/*.dmg
