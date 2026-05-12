"""One-shot ownership repair for LocWarp state directories.

Older versions of LocWarp ran the entire backend as root, so files in
``~/.locwarp/`` and ``~/Library/Mobile Documents/com~apple~CloudDocs/
LocWarp/`` got created with root ownership. After the user/helper
split, the backend runs as the regular user and cannot rewrite those
files; chown of root-owned files requires root. The helper exposes
this function via the ``migrate_user_state`` RPC so the backend can
trigger the repair once at startup.

Best-effort: per-entry failures are counted and logged, never raised.

Security note: this function runs as root in the elevated helper, so
it MUST NOT follow symlinks. A user-writable directory could otherwise
contain a symlink to ``/etc/sudoers`` (or any other root-owned file)
and trick us into rewriting its ownership — a textbook local privilege
escalation vector. We use ``lstat`` and ``os.chown(..., follow_symlinks
=False)`` exclusively, and manually walk directories with ``os.scandir``
so we never descend through a symlinked subdirectory either.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("tunnel_helper.migrate")


def migrate_user_state(*, home: str, uid: int, gid: int) -> dict:
    home_path = Path(home)
    targets = [
        home_path / ".locwarp",
        home_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "LocWarp",
    ]
    chowned = skipped = failed = 0
    for root in targets:
        if not root.exists():
            continue
        # If the target root itself is a symlink, refuse to descend.
        try:
            if root.is_symlink():
                skipped += 1
                continue
        except OSError:
            failed += 1
            continue

        # Collect entries via a manual scandir walk that does NOT
        # cross symlinks. rglob would descend through symlinked
        # subdirectories, which is the very thing we need to avoid.
        entries: list[Path] = [root]
        stack: list[Path] = [root]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for de in it:
                        try:
                            if de.is_symlink():
                                # Don't rewrite or descend through symlinks.
                                skipped += 1
                                continue
                            entries.append(Path(de.path))
                            if de.is_dir(follow_symlinks=False):
                                stack.append(Path(de.path))
                        except OSError as exc:
                            failed += 1
                            logger.warning("could not stat %s: %s", de.path, exc)
            except OSError as exc:
                failed += 1
                logger.warning("could not scan %s: %s", cur, exc)

        for entry in entries:
            try:
                st = entry.lstat()
                if stat.S_ISLNK(st.st_mode):
                    # Defence in depth: scandir loop already filters
                    # symlinks, but the root entry was added without a
                    # lstat check, and a TOCTOU between scandir and
                    # lstat is possible if an attacker swaps the entry
                    # under us. Re-check here.
                    skipped += 1
                    continue
                if st.st_uid == uid:
                    skipped += 1
                    continue
                os.chown(entry, uid, gid, follow_symlinks=False)
                chowned += 1
            except OSError as exc:
                failed += 1
                logger.warning("could not chown %s: %s", entry, exc)
    return {"chowned": chowned, "skipped": skipped, "failed": failed}
