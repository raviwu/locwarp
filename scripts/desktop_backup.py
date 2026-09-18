#!/usr/bin/env python3
"""Snapshot LocWarp's live in-memory bookmarks + routes, plus the recent
places store, to a local backup dir.

Insurance against the disk-persistence bug: the backend's atomic write can
fail silently (e.g. a stale root-owned ``bookmarks.json.tmp`` left by an
admin-mode run), so the user's input can live only in the backend's RAM
until a restart or the file-watcher reloads it away. This polls the live
HTTP API — which serves the in-memory state, the only fresh copy — and
writes a durable snapshot. The recent-places file is read directly instead
(see RECENT_PLACES_FILE below): it isn't subject to that admin-mode bug, so
the on-disk copy is already as fresh as the in-memory one.

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
# MUST match backend/config.py's BACKUP_RETENTION_HOURS: the in-process
# rotating backup (main.py's lifespan task) and this standalone tool write
# into and prune the SAME directory (~/.locwarp/backups/) using the SAME
# filename pattern (SNAPSHOT_GLOB above) — if the two windows disagree,
# whichever tool runs prunes snapshots the other one needs. The value is
# duplicated rather than imported because this script runs under plain
# system python3 (see the ``backup`` Makefile target and the launchd agent
# in the module docstring, not necessarily backend/.venv) and is
# deliberately dependency-free / decoupled from the backend package (it
# talks to the app over HTTP, never imports it) — reaching into
# backend/config.py would tie that isolation to backend's future import
# graph. Change both together.
RETENTION_HOURS = 720  # 30 days — keep in lock-step with backend/config.py BACKUP_RETENTION_HOURS
RETENTION_S = RETENTION_HOURS * 60 * 60
TIMEOUT_S = 5

# Read directly rather than via the HTTP API: unlike bookmarks/routes,
# RecentPlacesManager._save() writes synchronously on every push (no admin-mode
# atomic-write bug to work around), so the on-disk file is always fresh. It is
# also not sync-folder-aware (config.RECENT_PLACES_FILE is always
# ~/.locwarp/recent_places.json), so no settings.json lookup is needed either.
RECENT_PLACES_FILE = os.path.expanduser("~/.locwarp/recent_places.json")


def _get(path: str):
    with urllib.request.urlopen(API + path, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_bookmarks_store():
    """Full bookmark store INCLUDING tombstones.

    ``GET /api/bookmarks`` is the UI list endpoint and deliberately carries no
    deletion history; a snapshot without it resurrects deleted bookmarks when
    restored against a peer that still holds them alive (the 2026-09-18
    incident). ``GET /api/bookmarks/store`` exists for exactly this. Falls back
    to the list endpoint when talking to an older backend, so a mixed-version
    machine still gets a (lesser) backup rather than none.

    NOTE: ``HTTPError`` subclasses ``URLError``, so a 404 would otherwise be
    swallowed by main()'s unreachable-backend handler and silently produce no
    backup at all. It must be caught here, ahead of that.
    """
    try:
        return _get("/api/bookmarks/store")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        print(
            "warn: /api/bookmarks/store missing (older backend) — falling back "
            "to /api/bookmarks; this snapshot will carry NO bookmark tombstones",
            file=sys.stderr,
        )
        return _get("/api/bookmarks")


def _read_recent() -> list:
    """Best-effort read of the recent-places file. Never raises — a missing or
    corrupt file just means an empty recent contribution to this backup, same
    as the API-unreachable case does for bookmarks/routes."""
    try:
        with open(RECENT_PLACES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _content_of(snapshot: dict) -> str:
    """Canonical JSON of just the data (bookmarks + routes + recent), excluding
    the timestamped ``_backup_meta`` — so "changed" means the data changed, not
    merely that a minute passed."""
    return json.dumps(
        {
            "bookmarks": snapshot.get("bookmarks"),
            "routes": snapshot.get("routes"),
            "recent": snapshot.get("recent"),
        },
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
        # Both legs must carry tombstones. The routes leg already does:
        # /saved/export serialises the whole RouteStore via model_dump_json().
        bookmarks = _get_bookmarks_store()          # {categories, bookmarks, tombstones}
        routes = _get("/api/route/saved/export")    # {categories, routes, tombstones}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Backend not running / unreachable — keep the last good backup untouched.
        print(f"skip: LocWarp backend unreachable ({exc})", file=sys.stderr)
        return 0

    bm_count = len(bookmarks.get("bookmarks", []))
    rt_count = len(routes.get("routes", []))

    # Never let an empty fetch clobber a good backup. Recent is deliberately
    # NOT part of this guard — same rationale as the in-process BackupService:
    # it is the least valuable store, and empty bookmarks+routes is the signal
    # the data dir isn't ready, not recent being empty on its own.
    if bm_count == 0 and rt_count == 0:
        print("skip: API returned 0 bookmarks and 0 routes", file=sys.stderr)
        return 0

    recent = _read_recent()
    rec_count = len(recent)

    snapshot = {
        "_backup_meta": {
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": API,
            "bookmark_count": bm_count,
            "route_count": rt_count,
            "recent_count": rec_count,
            # Keep IDENTICAL to backend/domain/backup.py's note — both tools
            # write the same file and a reader must get the same instruction.
            "note": "Insurance snapshot of LocWarp live state. 'bookmarks' and "
                    "'routes' are full stores INCLUDING tombstones (deletion "
                    "history). Restore with `make restore-backup` (dry-run "
                    "first): the import endpoints accept these objects but DROP "
                    "tombstones and re-stamp updated_at, which resurrects "
                    "deleted items.",
        },
        "bookmarks": bookmarks,
        "routes": routes,
        "recent": recent,
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
    msg = f"backed up {bm_count} bookmarks + {rt_count} routes + {rec_count} recent ({state})"
    if removed:
        msg += f"; pruned {len(removed)} >{RETENTION_HOURS // 24}d"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
