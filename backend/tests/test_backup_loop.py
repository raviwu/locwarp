import asyncio
from datetime import datetime, timedelta

import pytest

from main import _bookmark_backup_loop


@pytest.mark.asyncio
async def test_loop_ticks_once_before_each_sleep_until_cancelled():
    calls = []

    class Svc:
        def tick(self, now):
            calls.append(now)

    n = {"i": 0}

    async def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _bookmark_backup_loop(
            Svc(), interval_s=300, sleep=fake_sleep,
            now_provider=lambda: datetime(2026, 6, 22, 12, 0, 0),
        )
    assert len(calls) == 3  # tick precedes each sleep


@pytest.mark.asyncio
async def test_loop_bad_tick_does_not_kill_loop():
    calls = {"n": 0}

    class Svc:
        def tick(self, now):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")  # first tick fails

    n = {"i": 0}

    async def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _bookmark_backup_loop(
            Svc(), interval_s=1, sleep=fake_sleep,
            now_provider=lambda: datetime(2026, 6, 22, 12, 0, 0),
        )
    assert calls["n"] == 2  # survived the failing first tick, ticked again


@pytest.mark.asyncio
async def test_loop_with_real_service_archives_and_prunes(tmp_path):
    from domain import backup
    from infra.persistence.backup_store import FileBackupStore
    from services.backup_service import BackupService

    repo = FileBackupStore(lambda: tmp_path / "backups")
    seq = {"n": 0}

    def provider():
        seq["n"] += 1  # changing data each tick -> every tick archives
        return (
            {"categories": [], "bookmarks": [{"id": str(seq["n"])}]},
            {"categories": [], "routes": []},
        )

    svc = BackupService(repo, provider, retention_hours=72)
    clock = {"t": datetime(2026, 6, 22, 0, 0, 0)}
    iters = {"i": 0}

    async def fake_sleep(_):
        iters["i"] += 1
        clock["t"] += timedelta(hours=24)  # advance 1 day per tick
        if iters["i"] >= 5:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _bookmark_backup_loop(
            svc, interval_s=300, sleep=fake_sleep, now_provider=lambda: clock["t"]
        )

    names = repo.list_snapshot_names()
    day0 = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(datetime(2026,6,22,0,0,0))}{backup.SNAPSHOT_SUFFIX}"
    assert day0 not in names          # day0 is 96h old at the final tick -> pruned
    assert len(names) == 4            # day1..day4 remain within the 72h window
    assert repo.read_latest() is not None
