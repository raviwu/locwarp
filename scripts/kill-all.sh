#!/usr/bin/env bash
# Stop all running LocWarp processes: Electron app, backend (packaged + dev),
# and elevated tunnel helper. Safe to run even when nothing is running.

echo "==> Stopping LocWarp (app + backend + helper)"

# 1. Ask the Electron app to quit gracefully
osascript -e 'tell application "LocWarp" to quit' 2>/dev/null || true

# 2. Ask the running backend to shut down via its API
curl -sf -X POST http://127.0.0.1:8777/api/system/shutdown 2>/dev/null || true

# 3. Brief pause so graceful exits can complete
sleep 1

# 4. Force-kill any survivors
pkill -f "LocWarp.app/Contents/MacOS/LocWarp" 2>/dev/null || true  # packaged Electron
pkill -f "locwarp-backend" 2>/dev/null || true                       # packaged backend binary
pkill -f -- "--tunnel-helper" 2>/dev/null || true                    # elevated helper (root)
pkill -f "uvicorn.*main:app" 2>/dev/null || true                     # dev backend (uvicorn)
pkill -f "start\.sh" 2>/dev/null || true                             # dev launcher

# 5. Kill anything still holding port 8777
lsof -ti tcp:8777 2>/dev/null | xargs kill -9 2>/dev/null || true

# 6. Remove IPC files left by the helper so the next launch gets a clean slate
rm -f /tmp/locwarp-helper.sock /tmp/locwarp-helper.status

echo "   done."
