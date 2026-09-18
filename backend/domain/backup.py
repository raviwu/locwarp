"""Pure backup policy: data fingerprint, snapshot naming, retention, payload.

stdlib only (domain ring). No file I/O, no clock — callers pass ``now`` in, so
every function here is deterministic and trivially unit-testable.
"""
from __future__ import annotations

import json
from datetime import datetime

# File scheme — identical to scripts/desktop_backup.py so the in-process task
# and the manual `make backup` produce interchangeable files in one dir, and
# the existing restore tooling (merge_backup.py) keeps working.
LATEST_NAME = "locwarp-latest-backup.json"
SNAPSHOT_PREFIX = "locwarp-backup-"
SNAPSHOT_SUFFIX = ".json"
_STAMP_FMT = "%Y%m%d-%H%M%S"


def data_fingerprint(bookmarks: dict, routes: dict, recent: list) -> str:
    """Canonical JSON of the DATA only (excludes _backup_meta) — so 'changed'
    means the stores changed, not merely that a tick passed.
    Mirrors desktop_backup._content_of."""
    return json.dumps(
        {"bookmarks": bookmarks, "routes": routes, "recent": recent},
        sort_keys=True, ensure_ascii=False,
    )


def snapshot_stamp(now: datetime) -> str:
    return now.strftime(_STAMP_FMT)


def parse_snapshot_stamp(filename: str) -> datetime | None:
    """Parse the embedded timestamp from a snapshot filename, or None if the
    name is not a timestamped snapshot (e.g. LATEST_NAME, or unrelated files)."""
    if not (filename.startswith(SNAPSHOT_PREFIX) and filename.endswith(SNAPSHOT_SUFFIX)):
        return None
    core = filename[len(SNAPSHOT_PREFIX) : -len(SNAPSHOT_SUFFIX)]
    try:
        return datetime.strptime(core, _STAMP_FMT)
    except ValueError:
        return None


def select_stale_snapshots(
    filenames: list[str], now: datetime, retention_hours: int
) -> list[str]:
    """Snapshot filenames whose embedded stamp is older than the retention
    window. Pruning keys off the filename timestamp (deterministic, immune to
    mtime rewrites), NOT mtime. Non-matching names (incl. LATEST_NAME) are
    never selected, so the 'latest' file and unrelated files are never pruned."""
    stale = []
    for name in filenames:
        ts = parse_snapshot_stamp(name)
        if ts is not None and (now - ts).total_seconds() > retention_hours * 3600:
            stale.append(name)
    return stale


def build_snapshot(
    bookmarks: dict, routes: dict, recent: list, now: datetime, source: str
) -> dict:
    """Assemble the combined snapshot payload. ``bookmarks`` is the
    {categories, bookmarks, tombstones} whole-store shape; ``routes`` is
    {categories, routes, tombstones}. The tombstone lists are what make a
    restore deletion-faithful — the full-fidelity restore path is
    ``make restore-backup`` (merge_backup.py), NOT the import endpoints, which
    drop tombstones. ``recent`` is a flat list
    (RecentPlacesManager.snapshot_export()), not a pydantic store.

    The exported list is whatever was live at snapshot time: GC runs inside
    merge_stores, i.e. on write, so an idle store can export a tombstone older
    than TOMBSTONE_RETENTION_DAYS. Restore applies the authoritative cutoff."""
    return {
        "_backup_meta": {
            "captured_at": now.astimezone().isoformat(timespec="seconds"),
            "source": source,
            "bookmark_count": len(bookmarks.get("bookmarks", [])),
            "route_count": len(routes.get("routes", [])),
            "recent_count": len(recent),
            # Keep IDENTICAL to scripts/desktop_backup.py's note — both tools
            # write the same file and a reader must get the same instruction.
            "note": (
                "Insurance snapshot of LocWarp live state. 'bookmarks' and "
                "'routes' are full stores INCLUDING tombstones (deletion "
                "history). Restore with `make restore-backup` (dry-run first): "
                "the import endpoints accept these objects but DROP tombstones "
                "and re-stamp updated_at, which resurrects deleted items."
            ),
        },
        "bookmarks": bookmarks,
        "routes": routes,
        "recent": recent,
    }
