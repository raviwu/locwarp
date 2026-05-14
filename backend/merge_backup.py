"""Merge a backup bookmarks/routes JSON into the live LocWarp store.

A safe restore path for when sync trouble leaves the live store missing
data — e.g. a root-owned ``~/.locwarp/settings.json`` that latched the
cloud-sync toggle off, or an old clobber before the tombstone merge
landed. Drop a backup ``.json`` on the Desktop and run ``make
merge-bookmarks``.

Why it is safe:
  - The merge is the same commutative ``merge_stores`` the app uses: a
    union by id where the newer ``updated_at`` wins a collision and the
    LIVE copy wins ties. A backup therefore only fills gaps — it never
    overwrites data the live store already has.
  - The live file is copied aside as ``<name>.bak-<timestamp>`` before
    anything is written.
  - A tombstone in the live store still suppresses a backup item with the
    same id (a genuine deletion is honoured). Pass ``--force-restore`` to
    drop those tombstones so the backup's items come back — use this only
    when you know the data went missing by accident, not a real delete.
    Caveat: on a cloud-synced store another device may still hold the
    tombstone and re-suppress the item on the next sync.

Usage (via the Makefile):
    make merge-bookmarks                        # ~/Desktop/locwarp-bookmark.json
    make merge-bookmarks FILE=~/Desktop/x.json
    make merge-bookmarks DRY_RUN=1              # preview, write nothing
    make merge-bookmarks FORCE=1               # ignore tombstones

Auto-detects whether the backup is a BookmarkStore or RouteStore by which
item key it carries, and merges into the matching live path (the iCloud
sync folder when sync is on, else ``~/.locwarp/``).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import get_bookmarks_path, get_routes_path
from models.schemas import BookmarkStore, RouteStore
from services.json_safe import safe_load_json
from services.store_merge import merge_stores


def detect_store_cls(data: dict):
    """Return BookmarkStore or RouteStore based on which item key is present.

    Raises ValueError if the payload looks like neither."""
    if "bookmarks" in data:
        return BookmarkStore
    if "routes" in data:
        return RouteStore
    raise ValueError(
        "Backup JSON has neither a 'bookmarks' nor a 'routes' key — "
        "not a recognisable LocWarp store file."
    )


def _items(store):
    """The per-store item list — bookmarks or routes."""
    return store.bookmarks if isinstance(store, BookmarkStore) else store.routes


def merge_backup_into_live(
    backup_path: Path,
    live_path: Path,
    *,
    force_restore: bool = False,
    dry_run: bool = False,
) -> dict:
    """Merge the backup at *backup_path* into the live store at *live_path*.

    Returns a summary dict. Raises ValueError if the backup is missing,
    unparseable, or not a recognisable store file.
    """
    raw = safe_load_json(backup_path)
    if not isinstance(raw, dict):
        raise ValueError(f"Backup file is missing or not valid JSON: {backup_path}")
    store_cls = detect_store_cls(raw)
    backup = store_cls(**raw)

    live_raw = safe_load_json(live_path)
    if isinstance(live_raw, dict):
        try:
            live = store_cls(**live_raw)
        except Exception:
            # Corrupt live file — treat as empty so the backup still restores.
            live = store_cls()
    else:
        live = store_cls()

    # Ids the backup carries — used both to report tombstone suppression and
    # to know which tombstones --force-restore should drop.
    backup_ids = {x.id for x in _items(backup)} | {c.id for c in backup.categories}
    suppressed = sorted(t.id for t in live.tombstones if t.id in backup_ids)

    dropped_tombstones: list[str] = []
    if force_restore and suppressed:
        dropped_tombstones = list(suppressed)
        live.tombstones = [t for t in live.tombstones if t.id not in backup_ids]

    before = len(_items(live))
    # live first → live wins ties; the backup only fills gaps.
    merged = merge_stores(live, backup)
    after = len(_items(merged))

    summary = {
        "store_type": "bookmarks" if store_cls is BookmarkStore else "routes",
        "backup_path": str(backup_path),
        "live_path": str(live_path),
        "items_before": before,
        "items_after": after,
        "items_restored": after - before,
        "tombstone_suppressed": [] if force_restore else suppressed,
        "tombstones_dropped": dropped_tombstones,
        "dry_run": dry_run,
        "backup_copy": None,
    }

    if dry_run:
        return summary

    # Copy the live file aside before overwriting — the whole point is safety.
    if live_path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = live_path.parent / f"{live_path.name}.bak-{ts}"
        shutil.copy2(live_path, bak)
        summary["backup_copy"] = str(bak)

    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_text(
        json.dumps(json.loads(merged.model_dump_json()), indent=2),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge a backup store JSON into the live LocWarp store.",
    )
    parser.add_argument("backup", type=Path, help="Path to the backup JSON file")
    parser.add_argument(
        "--force-restore", action="store_true",
        help="Drop live tombstones for ids in the backup so deleted items come back",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing anything",
    )
    args = parser.parse_args(argv)

    backup_path = args.backup.expanduser()
    if not backup_path.exists():
        print(f"error: backup file not found: {backup_path}", file=sys.stderr)
        return 1

    raw = safe_load_json(backup_path)
    if not isinstance(raw, dict):
        print(f"error: backup file is not valid JSON: {backup_path}", file=sys.stderr)
        return 1
    try:
        store_cls = detect_store_cls(raw)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    live_path = get_bookmarks_path() if store_cls is BookmarkStore else get_routes_path()

    summary = merge_backup_into_live(
        backup_path, Path(live_path),
        force_restore=args.force_restore, dry_run=args.dry_run,
    )

    print(f"Store type:    {summary['store_type']}")
    print(f"Backup:        {summary['backup_path']}")
    print(f"Live store:    {summary['live_path']}")
    print(f"Items:         {summary['items_before']} → {summary['items_after']} "
          f"(+{summary['items_restored']} restored)")
    if summary["tombstone_suppressed"]:
        print(f"Suppressed by tombstones (NOT restored): "
              f"{len(summary['tombstone_suppressed'])}")
        print("  → these ids were deleted; re-run with FORCE=1 to bring them back")
    if summary["tombstones_dropped"]:
        print(f"Tombstones dropped (force restore): {len(summary['tombstones_dropped'])}")
    if summary["dry_run"]:
        print("DRY RUN — nothing written.")
    else:
        if summary["backup_copy"]:
            print(f"Live store backed up to: {summary['backup_copy']}")
        print("Merge complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
