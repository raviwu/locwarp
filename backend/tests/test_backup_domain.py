from datetime import datetime, timedelta

from domain import backup


def test_fingerprint_stable_orderinsensitive_and_detects_change():
    a = {"categories": [{"id": "c1"}], "bookmarks": [{"id": "x"}]}
    r = {"routes": []}
    rec = [{"lat": 1.0, "lng": 2.0, "kind": "teleport", "name": "", "ts": 1}]
    # Stable across two independent but equal inputs.
    assert backup.data_fingerprint(a, r, rec) == backup.data_fingerprint(
        {"categories": [{"id": "c1"}], "bookmarks": [{"id": "x"}]}, {"routes": []}, rec
    )
    # Key order must not matter (sort_keys) — else identical data churns snapshots.
    assert backup.data_fingerprint(
        {"bookmarks": [{"id": "x"}], "categories": [{"id": "c1"}]}, r, rec
    ) == backup.data_fingerprint(a, r, rec)
    # A real data change is detected.
    assert backup.data_fingerprint(a, r, rec) != backup.data_fingerprint(
        {"categories": [{"id": "c1"}], "bookmarks": [{"id": "y"}]}, r, rec
    )
    # A recent-only change is also detected.
    assert backup.data_fingerprint(a, r, rec) != backup.data_fingerprint(a, r, [])


def test_stamp_roundtrip():
    now = datetime(2026, 6, 22, 14, 30, 5)
    name = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now)}{backup.SNAPSHOT_SUFFIX}"
    assert backup.parse_snapshot_stamp(name) == now


def test_parse_rejects_non_matching():
    assert backup.parse_snapshot_stamp(backup.LATEST_NAME) is None
    assert backup.parse_snapshot_stamp("random.json") is None
    assert backup.parse_snapshot_stamp("locwarp-backup-not-a-date.json") is None


def test_select_stale_drops_old_keeps_recent_ignores_latest():
    now = datetime(2026, 6, 22, 12, 0, 0)
    old = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now - timedelta(hours=80))}{backup.SNAPSHOT_SUFFIX}"
    recent = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now - timedelta(hours=10))}{backup.SNAPSHOT_SUFFIX}"
    names = [old, recent, backup.LATEST_NAME, "noise.json"]
    assert backup.select_stale_snapshots(names, now, 72) == [old]


def test_select_stale_boundary_just_under_and_over():
    now = datetime(2026, 6, 22, 12, 0, 0)
    under = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now - timedelta(hours=71, minutes=59))}{backup.SNAPSHOT_SUFFIX}"
    over = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now - timedelta(hours=72, minutes=1))}{backup.SNAPSHOT_SUFFIX}"
    assert backup.select_stale_snapshots([under, over], now, 72) == [over]


def test_build_snapshot_shape():
    recent = [{"lat": 1.0, "lng": 2.0, "kind": "teleport", "name": "", "ts": 1}]
    snap = backup.build_snapshot(
        {"categories": [], "bookmarks": [{"id": "a"}]},
        {"categories": [], "routes": []},
        recent,
        datetime(2026, 6, 22, 1, 2, 3),
        "in-process",
    )
    assert snap["bookmarks"]["bookmarks"] == [{"id": "a"}]
    assert snap["_backup_meta"]["bookmark_count"] == 1
    assert snap["_backup_meta"]["route_count"] == 0
    assert snap["_backup_meta"]["recent_count"] == 1
    assert snap["_backup_meta"]["source"] == "in-process"
    assert snap["recent"] == recent
    assert set(snap) == {"_backup_meta", "bookmarks", "routes", "recent"}
