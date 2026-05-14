#!/usr/bin/env bash
# Stop all running LocWarp processes: Electron app, backend (packaged + dev),
# and elevated tunnel helper. Blocks until port 8777 is confirmed free.
# Safe to run even when nothing is running.

set -euo pipefail

PORT=8777

port_free() {
  ! lsof -ti "tcp:${PORT}" 2>/dev/null | grep -q .
}

echo "==> Stopping LocWarp (app + backend + helper)"

# 1. Ask the Electron app to quit gracefully
osascript -e 'tell application "LocWarp" to quit' 2>/dev/null || true

# 2. Ask the running backend to shut down via its API
curl -sf -X POST "http://127.0.0.1:${PORT}/api/system/shutdown" 2>/dev/null || true

# 3. Give graceful exits up to 3 seconds
for _ in 1 2 3 4 5 6; do
  port_free && break
  sleep 0.5
done

# 4. Force-kill any survivors (user-space processes)
pkill -9 -f "LocWarp.app/Contents/MacOS/LocWarp" 2>/dev/null || true
pkill -9 -f "locwarp-backend"                      2>/dev/null || true
pkill -9 -f "uvicorn.*main:app"                    2>/dev/null || true
pkill -9 -f "start\.sh"                            2>/dev/null || true

# 5. Force-kill the elevated helper (runs as root — try sudo -n first, fall back to signal)
sudo -n pkill -9 -f -- "--tunnel-helper" 2>/dev/null || \
  pkill -9 -f -- "--tunnel-helper" 2>/dev/null || true

# 6. Kill by port — catches anything not matched by name
lsof -ti "tcp:${PORT}" 2>/dev/null | xargs kill -9 2>/dev/null || true

# 7. Remove IPC files (may be root-owned; try sudo -n, ignore failure)
sudo -n rm -f /tmp/locwarp-helper.sock /tmp/locwarp-helper.status 2>/dev/null || \
  rm -f /tmp/locwarp-helper.sock /tmp/locwarp-helper.status 2>/dev/null || true

# 8. Wait until port is confirmed free (up to 10 s)
echo -n "   waiting for port ${PORT} to be free..."
for i in $(seq 1 20); do
  if port_free; then
    echo " ok"
    echo "   done."
    exit 0
  fi
  sleep 0.5
done

echo " TIMEOUT"
echo "ERROR: port ${PORT} is still occupied after 10 s." >&2
lsof -nP -i "tcp:${PORT}" 2>/dev/null >&2 || true
exit 1
