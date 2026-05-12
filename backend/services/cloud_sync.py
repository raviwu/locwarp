"""Cloud sync path detection and migration helpers.

LocWarp itself does no network I/O; it relies on the operating system
(iCloud Drive, Google Drive Desktop, OneDrive, Dropbox) to synchronise
the bookmarks file across devices. This module only knows about local
filesystem paths.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

from services.sync_merge import merge_bookmark_stores, merge_route_stores


logger = logging.getLogger(__name__)


_MACOS_ICLOUD_REL = Path("Library/Mobile Documents/com~apple~CloudDocs")
_WIN_ICLOUD_REL = Path("iCloudDrive")

LOCWARP_SUBFOLDER = "LocWarp"


def detect_icloud_path() -> Path | None:
    """Return the user's iCloud Drive root if it exists; else None.

    On macOS this is ``~/Library/Mobile Documents/com~apple~CloudDocs``;
    on Windows it is ``%USERPROFILE%\\iCloudDrive`` (requires iCloud for
    Windows to be installed and signed in). Other platforms return None.
    """
    home = Path.home()
    if sys.platform == "darwin":
        candidate = home / _MACOS_ICLOUD_REL
    elif sys.platform == "win32":
        candidate = home / _WIN_ICLOUD_REL
    else:
        return None
    return candidate if candidate.exists() else None


def setup_sync_folder(parent: Path) -> Path:
    """Create (or reuse) the LocWarp subfolder under *parent*.

    Raises FileNotFoundError if *parent* itself does not exist (we never
    create the cloud-drive root for the user).
    """
    if not parent.exists():
        raise FileNotFoundError(f"Parent folder does not exist: {parent}")
    sub = parent / LOCWARP_SUBFOLDER
    sub.mkdir(exist_ok=True)
    return sub


_PAIR_FILES: tuple[tuple[str, str], ...] = (
    ("bookmarks.json", "bookmarks"),
    ("routes.json", "routes"),
)


def _move_or_merge_file(src: Path, dst: Path, kind: str) -> None:
    """Move *src* to *dst*, union-merging when both exist with different content.

    *kind* is "bookmarks" or "routes" — picks the right merger.
    No-op when *src* does not exist.
    """
    if not src.exists():
        return
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            try:
                src.unlink()
            except OSError as exc:
                logger.warning(
                    "migrate %s: %s and %s match but src unlink failed: %s",
                    kind, src, dst, exc,
                )
            return
        if kind == "bookmarks":
            merge_bookmark_stores(src, dst)
        elif kind == "routes":
            merge_route_stores(src, dst)
        else:
            raise ValueError(f"unknown kind: {kind}")
        src.unlink(missing_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    src.unlink()


def migrate_pair(src_dir: Path, dst_dir: Path) -> None:
    """Move bookmarks.json + routes.json from *src_dir* to *dst_dir*.

    All-or-nothing: on any failure, restore *src_dir* to its original
    state, remove any files newly created in *dst_dir* by this call, then
    re-raise.

    Union-merges when a file exists on both sides with different content.
    """
    if not dst_dir.exists():
        raise FileNotFoundError(f"Destination folder does not exist: {dst_dir}")

    # Snapshot src files so we can restore on failure.
    snapshot_dir = Path(tempfile.mkdtemp(prefix="locwarp-migrate-"))
    dst_existed_before: dict[str, bool] = {}
    try:
        for name, _kind in _PAIR_FILES:
            src_file = src_dir / name
            if src_file.exists():
                shutil.copy2(src_file, snapshot_dir / name)
            dst_existed_before[name] = (dst_dir / name).exists()

        for name, kind in _PAIR_FILES:
            _move_or_merge_file(src_dir / name, dst_dir / name, kind)
    except Exception:
        # Restore src from snapshot.
        for name, _kind in _PAIR_FILES:
            snap = snapshot_dir / name
            target = src_dir / name
            if snap.exists() and not target.exists():
                shutil.copy2(snap, target)
        # Remove dst files we created in this call.
        for name, _kind in _PAIR_FILES:
            if not dst_existed_before.get(name, False):
                p = dst_dir / name
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        logger.exception("rollback: could not unlink %s", p)
        raise
    finally:
        shutil.rmtree(snapshot_dir, ignore_errors=True)


def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Backwards-compat wrapper: move just the bookmarks file.

    Retained so existing tests and the legacy API path continue to work
    while we migrate to the unified ``migrate_pair`` flow.
    """
    _move_or_merge_file(src, dst, "bookmarks")
