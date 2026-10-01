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
# requirements.txt pins need Python >= 3.11 (timezonefinder 8.2.x). A bare
# `python3` on macOS is usually Xcode's 3.9, so pick a versioned interpreter.
if [[ -x "$ROOT/backend/.venv/bin/python" ]] && \
   ! "$ROOT/backend/.venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "ERROR: backend/.venv is $("$ROOT/backend/.venv/bin/python" --version 2>&1); need >= 3.11." >&2
    echo "Remove it (rm -rf backend/.venv) and re-run to bootstrap with a newer Python." >&2
    exit 1
fi
if [[ ! -f "$ROOT/backend/.venv/bin/activate" ]]; then
    PY_BOOT=""
    for cand in python3.13 python3.12 python3.11; do
        if command -v "$cand" >/dev/null 2>&1; then PY_BOOT="$cand"; break; fi
    done
    if [[ -z "$PY_BOOT" ]]; then
        echo "ERROR: no python3.11+ found (try: brew install python@3.13)." >&2
        exit 1
    fi
    echo "==> Bootstrapping backend/.venv with $PY_BOOT (first-time setup)"
    "$PY_BOOT" -m venv "$ROOT/backend/.venv"
    # shellcheck disable=SC1091
    source "$ROOT/backend/.venv/bin/activate"
    python -m pip install --upgrade pip
    pip install -r "$ROOT/backend/requirements.txt" -r "$ROOT/backend/requirements-build.txt"
else
    # shellcheck disable=SC1091
    source "$ROOT/backend/.venv/bin/activate"
fi
# Ensure build deps are present even on a pre-existing venv (e.g. one created
# for running tests, which only installs requirements.txt/-dev.txt). Without
# this the build fails with "No module named PyInstaller".
if ! python3 -c "import PyInstaller" >/dev/null 2>&1; then
    echo "==> PyInstaller missing in venv; installing build deps"
    pip install -r "$ROOT/backend/requirements-build.txt"
fi
python3 -m PyInstaller locwarp-backend.spec --noconfirm \
    --distpath "$ROOT/dist-py" \
    --workpath "$ROOT/build-py/backend"

echo
echo "============================================================"
echo " [1b/3] Frozen-binary self-check (import the fragile native chain)"
echo "============================================================"
# Run the freshly built binary with --self-check: it imports the whole
# PyInstaller-fragile native chain (mobile_image_mounter/pyimg4/apple_compress,
# service_connection/prompt_toolkit, timezonefinder/h3) and exits non-zero on
# the first PackageNotFoundError/ImportError. set -e then fails the whole build,
# turning every historical "dev-good / DMG-broken" metadata gap into a red here.
SELF_CHECK_BIN="$ROOT/dist-py/locwarp-backend/locwarp-backend"
if [[ ! -x "$SELF_CHECK_BIN" ]]; then
    echo "ERROR: built backend binary not found at $SELF_CHECK_BIN" >&2
    exit 1
fi
"$SELF_CHECK_BIN" --self-check

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
# Ad-hoc, NO hardened runtime: this is a locally-distributed (un-notarized)
# build, so the hardened runtime brings no benefit and actively breaks it —
# under hardened runtime Electron's V8 JIT crashes (EXC_BREAKPOINT) without
# allow-jit, and the bundled PyInstaller Python.framework/.so fail library
# validation. package.json sets mac.hardenedRuntime=false; this ad-hoc deep
# sign keeps it that way. The backend's frozen-import issue is fixed in
# main.py (uvicorn.run(app)), not via signing.
codesign --force --deep --sign - "$APP"
echo "Signed: $APP"

echo
echo "Done. DMG in $ROOT/frontend/release/"
ls -lh "$ROOT/frontend/release"/*.dmg
