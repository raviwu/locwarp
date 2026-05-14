"""Behaviour of desktop_backup's retention helpers.

Run from this directory with the backend venv's pytest:
    cd scripts && ../backend/.venv/bin/pytest test_desktop_backup.py
"""

import json
import os
import time

from desktop_backup import _payload_changed, _prune_old_snapshots


def test_prune_removes_stale_keeps_recent_and_latest(tmp_path):
    """Snapshots older than the retention window are deleted; recent ones
    and the (non-timestamped) 'latest' file are always kept."""
    now = time.time()
    day = 86400

    stale1 = tmp_path / "locwarp-backup-20260510-120000.json"
    stale2 = tmp_path / "locwarp-backup-20260511-120000.json"
    recent = tmp_path / "locwarp-backup-20260514-120000.json"
    latest = tmp_path / "locwarp-latest-backup.json"
    for f in (stale1, stale2, recent, latest):
        f.write_text("{}")
    os.utime(stale1, (now - 5 * day, now - 5 * day))
    os.utime(stale2, (now - 4 * day, now - 4 * day))
    os.utime(recent, (now - 1 * day, now - 1 * day))
    os.utime(latest, (now - 5 * day, now - 5 * day))  # old, but never a prune target

    removed = _prune_old_snapshots(str(tmp_path), now, 3 * day)

    assert set(removed) == {str(stale1), str(stale2)}
    assert not stale1.exists()
    assert not stale2.exists()
    assert recent.exists()
    assert latest.exists()


def test_payload_changed_true_when_data_differs(tmp_path):
    latest = tmp_path / "locwarp-latest-backup.json"
    latest.write_text(json.dumps({
        "_backup_meta": {"captured_at": "t1"},
        "bookmarks": {"bookmarks": [{"id": "a"}]},
        "routes": {"routes": []},
    }))
    new = {
        "_backup_meta": {"captured_at": "t2"},
        "bookmarks": {"bookmarks": [{"id": "a"}, {"id": "b"}]},
        "routes": {"routes": []},
    }
    assert _payload_changed(new, str(latest)) is True


def test_payload_changed_false_when_only_meta_differs(tmp_path):
    """Same bookmarks + routes, only the timestamp meta differs — must be
    False, or an idle LocWarp would archive 1,440 identical files a day."""
    latest = tmp_path / "locwarp-latest-backup.json"
    data = {"bookmarks": {"bookmarks": [{"id": "a"}]}, "routes": {"routes": []}}
    latest.write_text(json.dumps({"_backup_meta": {"captured_at": "t1"}, **data}))
    new = {"_backup_meta": {"captured_at": "t2-different"}, **data}
    assert _payload_changed(new, str(latest)) is False


def test_payload_changed_true_when_latest_missing(tmp_path):
    new = {"_backup_meta": {}, "bookmarks": {"bookmarks": []}, "routes": {"routes": []}}
    assert _payload_changed(new, str(tmp_path / "does-not-exist.json")) is True
