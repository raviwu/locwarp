#!/usr/bin/env python3
"""Snapshot LocWarp's live in-memory bookmarks + routes to a local backup dir.

Insurance against the disk-persistence bug: the backend's atomic write can
fail silently (e.g. a stale root-owned ``bookmarks.json.tmp`` left by an
admin-mode run), so the user's input can live only in the backend's RAM
until a restart or the file-watcher reloads it away. This polls the live
HTTP API — which serves the in-memory state, the only fresh copy — and
writes a durable snapshot.

Writes to ~/.locwarp/backups/ rather than ~/Desktop: macOS TCC blocks a
launchd agent from writing to the Desktop ("Operation not permitted"), but
not a plain dotfolder under $HOME. A one-time Desktop symlink (made by the
user's own shell, which does have Desktop access) gives Desktop visibility.

Run every 60s by ~/Library/LaunchAgents/com.locwarp.desktop-backup.plist.
Overwrites a single "latest" file and keeps one ".prev" generation. The
write is skipped on fetch failure or empty data, so a good backup is never
clobbered by a transient empty state — that overwrite-with-worse-data case
is exactly what this script exists to insure against.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime

API = "http://127.0.0.1:8777"
BACKUP_DIR = os.path.expanduser("~/.locwarp/backups")
OUT = os.path.join(BACKUP_DIR, "locwarp-latest-backup.json")
PREV = os.path.join(BACKUP_DIR, "locwarp-latest-backup.prev.json")
TIMEOUT_S = 5


def _get(path: str):
    with urllib.request.urlopen(API + path, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    try:
        bookmarks = _get("/api/bookmarks")          # {categories, bookmarks}
        routes = _get("/api/route/saved/export")    # {categories, routes}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Backend not running / unreachable — keep the last good backup untouched.
        print(f"skip: LocWarp backend unreachable ({exc})", file=sys.stderr)
        return 0

    bm_count = len(bookmarks.get("bookmarks", []))
    rt_count = len(routes.get("routes", []))

    # Never let an empty fetch clobber a good backup.
    if bm_count == 0 and rt_count == 0:
        print("skip: API returned 0 bookmarks and 0 routes", file=sys.stderr)
        return 0

    snapshot = {
        "_backup_meta": {
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": API,
            "bookmark_count": bm_count,
            "route_count": rt_count,
            "note": "Insurance snapshot of LocWarp in-memory state. The "
                    "'bookmarks' and 'routes' objects are each directly "
                    "re-importable via LocWarp's import endpoints.",
        },
        "bookmarks": bookmarks,
        "routes": routes,
    }

    # Keep one previous generation, then atomically replace the latest.
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if os.path.exists(OUT):
        shutil.copy2(OUT, PREV)
    tmp = OUT + ".writing"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)

    print(f"backed up {bm_count} bookmarks + {rt_count} routes -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
