"""Port for rotating-backup file storage. stdlib + typing only (domain ring).

The orchestrating BackupService (services ring) depends on this Protocol; the
concrete FileBackupStore (infra ring) implements it and is wired at the
composition root, so services never import infra.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class BackupRepository(Protocol):
    def read_latest(self) -> dict | None:
        """Parsed locwarp-latest-backup.json, or None if absent/unreadable."""
        ...

    def write_latest(self, payload: dict) -> None:
        """Atomically (over)write the 'latest' snapshot."""
        ...

    def write_snapshot(self, payload: dict, stamp: str) -> Path:
        """Atomically write a timestamped snapshot; return its path."""
        ...

    def list_snapshot_names(self) -> list[str]:
        """Filenames of timestamped snapshots (excludes 'latest' + unrelated files)."""
        ...

    def delete_snapshots(self, names: list[str]) -> list[str]:
        """Best-effort delete; return the names actually removed."""
        ...
