#!/usr/bin/env bash
# Install the freshly-built LocWarp.app into /Applications on THIS machine.
#
# Use this after ./build-installer-mac.sh to avoid manually opening the DMG
# and dragging the app + admin .command file every iteration.
#
# Flow:
#   1. Quit any running LocWarp
#   2. Remove /Applications/LocWarp.app
#   3. Copy the freshly-built .app + admin .command to /Applications
#   4. Strip the macOS quarantine xattr so Gatekeeper doesn't nag
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
CMD_SRC="$ROOT/LocWarp-admin.command"

if [[ ! -d "$APP_SRC" ]]; then
  echo "ERROR: $APP_SRC not found." >&2
  echo "Run './build-installer-mac.sh' (or 'install-mac-local.sh --build') first." >&2
  exit 1
fi

echo "==> Quitting any running LocWarp"
osascript -e 'tell application "LocWarp" to quit' 2>/dev/null || true
sleep 1
pkill -f "/Applications/LocWarp.app/Contents/MacOS/LocWarp" 2>/dev/null || true

echo "==> Replacing /Applications/LocWarp.app"
sudo rm -rf /Applications/LocWarp.app
sudo cp -R "$APP_SRC" /Applications/LocWarp.app

echo "==> Copying LocWarp-admin.command"
sudo cp "$CMD_SRC" /Applications/LocWarp-admin.command
sudo chmod +x /Applications/LocWarp-admin.command

echo "==> Stripping quarantine xattr"
sudo xattr -dr com.apple.quarantine /Applications/LocWarp.app
sudo xattr -dr com.apple.quarantine /Applications/LocWarp-admin.command || true

echo
echo "Done. Launch:"
echo "  - Normal:  open -a LocWarp"
echo "  - As root: open /Applications/LocWarp-admin.command"
