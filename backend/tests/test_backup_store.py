from pathlib import Path

from domain import backup
from infra.persistence.backup_store import FileBackupStore


def _store(tmp_path):
    return FileBackupStore(lambda: tmp_path / "backups")


def test_read_latest_none_when_absent(tmp_path):
    assert _store(tmp_path).read_latest() is None


def test_write_and_read_latest_roundtrip(tmp_path):
    s = _store(tmp_path)
    s.write_latest({"_backup_meta": {}, "bookmarks": {"bookmarks": []}, "routes": {"routes": []}})
    assert s.read_latest()["bookmarks"] == {"bookmarks": []}


def test_write_snapshot_and_list_excludes_latest(tmp_path):
    s = _store(tmp_path)
    p = s.write_snapshot({"x": 1}, "20260622-120000")
    assert Path(p).name == f"{backup.SNAPSHOT_PREFIX}20260622-120000{backup.SNAPSHOT_SUFFIX}"
    s.write_latest({"x": 0})  # latest must NOT appear in the snapshot list
    assert s.list_snapshot_names() == [
        f"{backup.SNAPSHOT_PREFIX}20260622-120000{backup.SNAPSHOT_SUFFIX}"
    ]


def test_delete_snapshots_best_effort(tmp_path):
    s = _store(tmp_path)
    s.write_snapshot({"x": 1}, "20260622-120000")
    name = s.list_snapshot_names()[0]
    assert s.delete_snapshots([name, "does-not-exist.json"]) == [name]
    assert s.list_snapshot_names() == []


def test_writes_are_valid_json_on_disk(tmp_path):
    import json

    s = _store(tmp_path)
    s.write_snapshot({"hello": "wörld"}, "20260622-130000")
    f = (tmp_path / "backups" / f"{backup.SNAPSHOT_PREFIX}20260622-130000{backup.SNAPSHOT_SUFFIX}")
    assert json.loads(f.read_text(encoding="utf-8")) == {"hello": "wörld"}
