#!/usr/bin/env bash
# macOS launcher for LocWarp dev mode. The backend runs as the regular
# user; only the tunnel helper runs as root (sudo prompt fires inside
# start.py when needed).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "  LocWarp macOS Launcher"
echo "  iOS 17+ 需要 root 權限建立裝置通道 (sudo prompt will fire for the helper)"
echo

exec python3 "$SCRIPT_DIR/start.py" "$@"
