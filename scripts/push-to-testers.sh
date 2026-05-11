#!/usr/bin/env bash
# Push a freshly-built LocWarp.app to a list of macOS test laptops over SSH.
#
# Use this to update multiple Mac testers in one shot, without making them
# download the DMG and drag-install. Skips Gatekeeper friction by stripping
# the quarantine xattr on the target.
#
# Note: LocWarp.app self-elevates on launch (osascript prompts for the
# admin password). No separate launcher script needs to be pushed alongside.
#
# Prereqs on each tester laptop:
#   1. Enable SSH: System Settings → General → Sharing → Remote Login
#   2. Authorize your dev Mac's public key:
#        ssh-copy-id <user>@<tester-host>
#   3. The tester user can run `sudo` (needed to write /Applications)
#
# Configure testers via a one-host-per-line file at ./scripts/testers.conf
# (gitignored — each developer keeps their own list). Format: user@host
# Example:
#   alice@alice-mbp.local
#   bob@192.168.1.42
#
# Usage:
#   ./scripts/push-to-testers.sh             # use existing build artifact
#   ./scripts/push-to-testers.sh --build     # rebuild first via build-installer-mac.sh
#   TESTERS="alice@m1.local bob@m2.local" ./scripts/push-to-testers.sh  # inline override

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
  echo "Run './build-installer-mac.sh' (or 'push-to-testers.sh --build') first." >&2
  exit 1
fi

# Resolve tester list: inline TESTERS env wins, else testers.conf, else fail.
TESTERS_LIST="${TESTERS:-}"
if [[ -z "$TESTERS_LIST" && -f "$ROOT/scripts/testers.conf" ]]; then
  TESTERS_LIST="$(grep -vE '^\s*(#|$)' "$ROOT/scripts/testers.conf" | xargs)"
fi
if [[ -z "$TESTERS_LIST" ]]; then
  echo "ERROR: no testers configured." >&2
  echo "Either set TESTERS env var or create scripts/testers.conf." >&2
  exit 1
fi

for HOST in $TESTERS_LIST; do
  echo
  echo "============================================================"
  echo " Updating $HOST"
  echo "============================================================"

  echo "==> Quitting any running LocWarp on $HOST"
  ssh "$HOST" 'osascript -e "tell application \"LocWarp\" to quit" 2>/dev/null || true; sleep 1; sudo pkill -f "/Applications/LocWarp.app/Contents/MacOS/LocWarp" || true'

  echo "==> Replacing /Applications/LocWarp.app on $HOST"
  ssh "$HOST" 'sudo rm -rf /Applications/LocWarp.app'
  # Use rsync to preserve symlinks and executable bits inside the .app bundle.
  rsync -avz --delete \
    --rsync-path='sudo rsync' \
    "$APP_SRC/" "$HOST:/Applications/LocWarp.app/"

  echo "==> Stripping quarantine xattr on $HOST"
  ssh "$HOST" 'sudo /usr/bin/xattr -dr com.apple.quarantine /Applications/LocWarp.app 2>/dev/null || true'

  echo "==> Done with $HOST"
done

echo
echo "All testers updated. They can re-launch LocWarp with: open -a LocWarp"
echo "(LocWarp will prompt for the admin password on every launch.)"
