"""Cloud sync file management: migration with rollback on failure."""

import shutil
from pathlib import Path


def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Move *src* to *dst* with rollback on partial failure.

    No-op if *src* does not exist. Refuses to overwrite *dst* if both
    exist with different content (caller must resolve).
    """
    if not src.exists():
        return
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        raise FileExistsError(f"Destination already has different content: {dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    try:
        src.unlink()
    except OSError:
        # Rollback: remove dst so we don't leave duplicate
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        raise
