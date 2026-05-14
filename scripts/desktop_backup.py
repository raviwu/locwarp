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
not a plain dotfolder under $HOME. The ``make backup`` target — run from
the user's own shell, which does have Desktop access — additionally copies
the latest snapshot onto the Desktop.

Retention: every run refreshes ``locwarp-latest-backup.json`` (the Desktop
symlink target). A timestamped ``locwarp-backup-<stamp>.json`` is kept only
when the data actually changed since the last run — so an idle LocWarp does
not archive 1,440 identical files a day. Timestamped snapshots older than
the retention window are pruned. The write is skipped on fetch failure or
empty data, so a good backup is never clobbered by a transient empty state.

Run every 60s by ~/Library/LaunchAgents/com.locwarp.desktop-backup.plist,
or once via ``make backup``.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

API = "http://127.0.0.1:8777"
BACKUP_DIR = os.path.expanduser("~/.locwarp/backups")
LATEST = os.path.join(BACKUP_DIR, "locwarp-latest-backup.json")
SNAPSHOT_GLOB = "locwarp-backup-*.json"
RETENTION_S = 3 * 24 * 60 * 60  # keep timestamped snapshots for 3 days
TIMEOUT_S = 5


def _get(path: str):
    with urllib.request.urlopen(API + path, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _content_of(snapshot: dict) -> str:
    """Canonical JSON of just the data (bookmarks + routes), excluding the
    timestamped ``_backup_meta`` — so "changed" means the data changed, not
    merely that a minute passed."""
    return json.dumps(
        {"bookmarks": snapshot.get("bookmarks"), "routes": snapshot.get("routes")},
        sort_keys=True,
        ensure_ascii=False,
    )


def _payload_changed(new_snapshot: dict, latest_path: str) -> bool:
    """True if *new_snapshot*'s data differs from the file at *latest_path*,
    or that file is missing / unreadable."""
    try:
        with open(latest_path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return True
    return _content_of(new_snapshot) != _content_of(old)


def _prune_old_snapshots(backup_dir: str, now: float, max_age_s: float) -> list[str]:
    """Delete timestamped snapshots older than *max_age_s*. Returns the list
    of removed paths. The non-timestamped 'latest' file never matches the
    glob, so it is never a prune target."""
    removed = []
    for p in glob.glob(os.path.join(backup_dir, SNAPSHOT_GLOB)):
        try:
            if now - os.path.getmtime(p) > max_age_s:
                os.remove(p)
                removed.append(p)
        except OSError:
            pass
    return removed


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

    os.makedirs(BACKUP_DIR, exist_ok=True)
    changed = _payload_changed(snapshot, LATEST)
    body = json.dumps(snapshot, ensure_ascii=False, indent=2)

    # 'latest' always reflects the current state (Desktop symlink -> here).
    tmp = LATEST + ".writing"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, LATEST)

    # A timestamped snapshot is kept only on a real data change.
    if changed:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive = os.path.join(BACKUP_DIR, f"locwarp-backup-{stamp}.json")
        with open(archive, "w", encoding="utf-8") as f:
            f.write(body)

    removed = _prune_old_snapshots(BACKUP_DIR, time.time(), RETENTION_S)

    state = "snapshot saved" if changed else "unchanged, latest refreshed"
    msg = f"backed up {bm_count} bookmarks + {rt_count} routes ({state})"
    if removed:
        msg += f"; pruned {len(removed)} >3d"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
