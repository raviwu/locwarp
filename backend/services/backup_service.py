"""Rotating-backup orchestration use-case (services ring).

Depends on the BackupRepository port + a snapshot provider + domain policy.
Imports no fastapi and no infra — the concrete repo + provider are injected at
the composition root. ``tick(now)`` takes the time in, so it is deterministic
and unit-testable with no sleeping.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from domain import backup
from domain.ports.backup_repository import BackupRepository


@dataclass
class BackupTickResult:
    bookmark_count: int = 0
    route_count: int = 0
    changed: bool = False
    pruned: int = 0
    skipped: str | None = None


class BackupService:
    def __init__(
        self,
        repo: BackupRepository,
        snapshot_provider: Callable[[], tuple[dict, dict]],
        retention_hours: int,
        source: str = "in-process",
    ):
        self._repo = repo
        self._snapshot_provider = snapshot_provider
        self._retention_hours = retention_hours
        self._source = source

    def tick(self, now: datetime) -> BackupTickResult:
        bookmarks, routes = self._snapshot_provider()
        bm = len(bookmarks.get("bookmarks", []))
        rt = len(routes.get("routes", []))

        # Never let a transient empty state (iCloud eviction, startup) clobber
        # a good backup — write nothing at all.
        if bm == 0 and rt == 0:
            return BackupTickResult(skipped="empty")

        prev = self._repo.read_latest()
        changed = prev is None or backup.data_fingerprint(bookmarks, routes) != backup.data_fingerprint(
            prev.get("bookmarks", {}), prev.get("routes", {})
        )

        payload = backup.build_snapshot(bookmarks, routes, now, self._source)
        self._repo.write_latest(payload)  # 'latest' always reflects current state
        if changed:
            self._repo.write_snapshot(payload, backup.snapshot_stamp(now))

        stale = backup.select_stale_snapshots(
            self._repo.list_snapshot_names(), now, self._retention_hours
        )
        deleted = self._repo.delete_snapshots(stale)
        return BackupTickResult(bm, rt, changed, len(deleted))
