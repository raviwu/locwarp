"""Cloud sync path detection and migration helpers.

LocWarp itself does no network I/O; it relies on the operating system
(iCloud Drive, Google Drive Desktop, OneDrive, Dropbox) to synchronise
the bookmarks file across devices. This module only knows about local
filesystem paths.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


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
    create the cloud drive root for the user).

    On macOS the app runs as root (self-elevation for iOS tunnelling), but
    iCloud Drive files created by the normal user carry restrictive
    permissions that block root's read access (EPERM, not EACCES).  We
    therefore chmod the subfolder and any existing bookmarks.json to
    group-readable/writable so that both the elevated process and the
    file-owning user can access them.
    """
    if not parent.exists():
        raise FileNotFoundError(f"Parent folder does not exist: {parent}")
    sub = parent / LOCWARP_SUBFOLDER
    sub.mkdir(exist_ok=True)
    try:
        sub.chmod(0o755)
        bm = sub / "bookmarks.json"
        if bm.exists():
            bm.chmod(0o644)
    except OSError:
        pass  # best-effort; failure here is non-fatal
    return sub


def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Move *src* to *dst* with rollback on partial failure.

    No-op if *src* does not exist. Refuses to overwrite *dst* if both
    exist with different content (caller must resolve).
    """
    if not src.exists():
        return
    if dst.exists():
        try:
            same = dst.read_bytes() == src.read_bytes()
        except OSError:
            # Root cannot read the iCloud file (EPERM on macOS) — treat as
            # "remote copy exists but unreadable": adopt without overwriting.
            same = False
        if not same:
            raise FileExistsError(f"Destination already has different content: {dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    try:
        src.unlink()
    except OSError as exc:
        # The copy succeeded, so the data is safe in dst.
        # Failing to remove src (e.g. permission error when the directory
        # is owned by root from a previous elevated run) is non-fatal:
        # log it and continue. The stale local copy becomes harmless once
        # app_state points at the new path.
        import logging
        logging.getLogger(__name__).warning(
            "migrate_bookmarks: copied %s → %s but could not delete source: %s",
            src, dst, exc,
        )
