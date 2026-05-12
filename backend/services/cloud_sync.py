"""Cloud sync path detection and migration helpers.

LocWarp itself does no network I/O; it relies on the operating system
(iCloud Drive, Google Drive Desktop, OneDrive, Dropbox) to synchronise
the bookmarks file across devices. This module only knows about local
filesystem paths.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path


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


def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Move *src* to *dst*. No-op if *src* does not exist.

    Refuses to overwrite *dst* if both files exist with different
    content (caller resolves via the merge code path).
    """
    if not src.exists():
        return
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            try:
                src.unlink()
            except OSError as exc:
                logger.warning(
                    "migrate_bookmarks: %s and %s match but src unlink failed: %s",
                    src, dst, exc,
                )
            return
        raise FileExistsError(f"Destination already has different content: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    src.unlink()
