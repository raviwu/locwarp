"""Infra adapter: rotating-backup file I/O under a caller-provided directory.

Built ONLY at the composition root (bootstrap/factories.make_backup_service).
Reuses services.json_safe for the same atomic temp+replace guarantee the live
store enjoys (the infra -> services.json_safe edge already exists in json_store).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from domain import backup
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)


class FileBackupStore:
    """Implements domain.ports.backup_repository.BackupRepository over a dir.

    The dir is resolved lazily via ``dir_provider()`` so test isolation
    (monkeypatch of config.BACKUP_DIR) takes effect, and so the path is read
    at use-time rather than captured at construction.
    """

    def __init__(self, dir_provider: Callable[[], Path]):
        self._dir_provider = dir_provider

    def _dir(self) -> Path:
        d = Path(self._dir_provider())
        d.mkdir(parents=True, exist_ok=True)
        return d

    def read_latest(self) -> dict | None:
        # safe_load_json returns None for missing/empty/corrupt files.
        return safe_load_json(self._dir() / backup.LATEST_NAME)

    def write_latest(self, payload: dict) -> None:
        safe_write_json(self._dir() / backup.LATEST_NAME, payload)

    def write_snapshot(self, payload: dict, stamp: str) -> Path:
        p = self._dir() / f"{backup.SNAPSHOT_PREFIX}{stamp}{backup.SNAPSHOT_SUFFIX}"
        safe_write_json(p, payload)
        return p

    def list_snapshot_names(self) -> list[str]:
        return sorted(
            f.name
            for f in self._dir().iterdir()
            if backup.parse_snapshot_stamp(f.name) is not None
        )

    def delete_snapshots(self, names: list[str]) -> list[str]:
        deleted = []
        d = self._dir()
        for name in names:
            try:
                (d / name).unlink()
                deleted.append(name)
            except OSError as exc:
                logger.warning("backup prune skipped %s: %s", name, exc)
        return deleted
