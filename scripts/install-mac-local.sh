#!/usr/bin/env bash
# Install the freshly-built LocWarp.app into /Applications on THIS machine.
#
# Use this after ./build-installer-mac.sh to avoid manually opening the DMG
# and dragging the app every iteration.
#
# Flow:
#   1. Quit any running LocWarp
#   2. Remove /Applications/LocWarp.app
#   3. Copy the freshly-built .app to /Applications
#   4. Strip the macOS quarantine xattr so Gatekeeper doesn't nag
#
# Note: LocWarp.app self-elevates on launch (osascript prompts for the
# admin password). No separate launcher script is needed any more.
#
# Usage:
#   ./scripts/install-mac-local.sh         # use existing build artifact
#   ./scripts/install-mac-local.sh --build # rebuild first via build-installer-mac.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "${1:-}" == "--build" ]]; then
  echo "==> Rebuilding via build-installer-mac.sh"
  ./build-installer-mac.sh
fi

APP_SRC="$ROOT/frontend/release/mac-arm64/LocWarp.app"

if [[ ! -d "$APP_SRC" ]]; then
  echo "ERROR: $APP_SRC not found." >&2
  echo "Run './build-installer-mac.sh' (or 'install-mac-local.sh --build') first." >&2
  exit 1
fi

bash "$ROOT/scripts/kill-all.sh"

echo "==> Replacing /Applications/LocWarp.app"
sudo rm -rf /Applications/LocWarp.app
sudo cp -R "$APP_SRC" /Applications/LocWarp.app

echo "==> Stripping quarantine xattr"
sudo /usr/bin/xattr -dr com.apple.quarantine /Applications/LocWarp.app

echo
echo "Done. Launch: open -a LocWarp"
echo "(LocWarp will prompt for the admin password on every launch.)"
