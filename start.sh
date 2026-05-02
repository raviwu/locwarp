#!/usr/bin/env bash
# macOS launcher for LocWarp — requires sudo for iOS 17+ utun tunnel
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "  LocWarp macOS Launcher"
echo "  iOS 17+ 需要 root 權限建立裝置通道"
echo

exec sudo python3 "$SCRIPT_DIR/start.py" "$@"
