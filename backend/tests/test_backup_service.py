from datetime import datetime

from domain import backup
from services.backup_service import BackupService


class FakeRepo:
    def __init__(self):
        self.latest = None
        self.snaps = {}

    def read_latest(self):
        return self.latest

    def write_latest(self, p):
        self.latest = p

    def write_snapshot(self, p, stamp):
        name = f"{backup.SNAPSHOT_PREFIX}{stamp}{backup.SNAPSHOT_SUFFIX}"
        self.snaps[name] = p
        return name

    def list_snapshot_names(self):
        return list(self.snaps)

    def delete_snapshots(self, names):
        for n in names:
            self.snaps.pop(n, None)
        return names


def _svc(repo, bms, rts, retention=72):
    return BackupService(repo, lambda: (bms, rts), retention)


def test_skip_when_empty_writes_nothing():
    r = FakeRepo()
    res = _svc(r, {"bookmarks": []}, {"routes": []}).tick(datetime(2026, 6, 22, 12, 0, 0))
    assert res.skipped == "empty"
    assert r.latest is None and r.snaps == {}


def test_latest_always_refreshed_snapshot_only_on_change():
    r = FakeRepo()
    s = _svc(r, {"categories": [], "bookmarks": [{"id": "a"}]}, {"categories": [], "routes": []})
    res = s.tick(datetime(2026, 6, 22, 12, 0, 0))
    assert res.changed and len(r.snaps) == 1 and r.latest is not None

    # Same data, later tick: latest refreshed but no new snapshot.
    res2 = s.tick(datetime(2026, 6, 22, 12, 5, 0))
    assert not res2.changed and len(r.snaps) == 1

    # Data changed: a new snapshot is archived.
    s2 = _svc(r, {"categories": [], "bookmarks": [{"id": "a"}, {"id": "b"}]}, {"categories": [], "routes": []})
    res3 = s2.tick(datetime(2026, 6, 22, 12, 10, 0))
    assert res3.changed and len(r.snaps) == 2


def test_prune_runs_each_tick():
    r = FakeRepo()
    old = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(datetime(2026, 6, 18, 0, 0, 0))}{backup.SNAPSHOT_SUFFIX}"
    r.snaps[old] = {}
    res = _svc(r, {"categories": [], "bookmarks": [{"id": "a"}]}, {"categories": [], "routes": []}).tick(
        datetime(2026, 6, 22, 12, 0, 0)
    )
    assert res.pruned == 1
    assert all("20260618" not in n for n in r.snaps)


def test_payload_is_restore_compatible_shape():
    r = FakeRepo()
    _svc(r, {"categories": [], "bookmarks": [{"id": "a"}]}, {"categories": [], "routes": []}).tick(
        datetime(2026, 6, 22, 12, 0, 0)
    )
    assert set(r.latest) == {"_backup_meta", "bookmarks", "routes"}
    assert "bookmarks" in r.latest["bookmarks"] and "routes" in r.latest["routes"]


def test_routes_only_change_still_archives():
    r = FakeRepo()
    s = _svc(r, {"categories": [], "bookmarks": []}, {"categories": [], "routes": [{"id": "r1"}]})
    res = s.tick(datetime(2026, 6, 22, 12, 0, 0))
    assert res.changed and res.route_count == 1 and len(r.snaps) == 1
