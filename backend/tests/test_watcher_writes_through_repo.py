"""Regression (X14): the bookmark watcher MUST persist through the repo
(self._repo.save), not via a raw services.json_safe.safe_write_json call.

P4a moved all bookmark file-I/O behind BookmarkRepository; _watcher_tick was
the one write that still reached past the repo into infra. Routing it back
through the repo keeps the read-merge-write (and the stale-tombstone GC that
merge_stores does) on every persisted path, and removes the re-leaked
safe_write_json import.
"""
import json

import pytest

from bootstrap.factories import make_bookmark_manager


def _make_manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr(
        "services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    return make_bookmark_manager(), tmp_path / "bookmarks.json"


def test_watcher_tick_persists_through_repo_save(tmp_path, monkeypatch):
    """An external on-disk change that the watcher reconciles must be written
    back via self._repo.save (so the merge/GC stays on the persisted path),
    not via a raw safe_write_json bypassing the repo."""
    mgr, path = _make_manager(tmp_path, monkeypatch)

    # Seed a real on-disk store via the normal write path.
    cat = mgr.create_category(name="C", color="#abc")
    mgr.create_bookmark(name="local", lat=1.0, lng=2.0, category_id=cat.id)

    # Simulate another device writing a NEW bookmark into the same file via
    # iCloud: append directly to the JSON on disk, then bump mtime backstop so
    # the watcher tick treats it as a fresh external write.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["bookmarks"].append(
        {
            "id": "remote-id",
            "name": "remote",
            "lat": 3.0,
            "lng": 4.0,
            "category_id": cat.id,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    mgr._last_loaded_mtime = 0.0  # force current_mtime > last_loaded so the tick proceeds

    # Spy on the repo.save so we can prove the watcher write goes through it.
    real_save = mgr._repo.save
    calls = []

    def _spy_save(store):
        calls.append(store)
        return real_save(store)

    monkeypatch.setattr(mgr._repo, "save", _spy_save)

    # Guard: if any code still reaches the raw infra write, blow up loudly.
    # NOTE: _watcher_tick wraps its body in `try/except Exception` and SWALLOWS
    # exceptions (logs them), so this AssertionError will NOT propagate out of
    # the tick — the real assertion that fails before the fix is `assert calls`
    # below (calls stays empty because the watcher never reached _repo.save).
    def _boom(*a, **k):  # pragma: no cover - only hit on regression
        raise AssertionError("watcher used raw safe_write_json, not self._repo.save")

    monkeypatch.setattr("services.bookmarks.safe_write_json", _boom, raising=False)

    mgr._watcher_tick()

    assert calls, "watcher reconcile did not persist through self._repo.save"
    # The remote bookmark survived the merge and is on disk.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    ids = {b["id"] for b in on_disk["bookmarks"]}
    assert "remote-id" in ids
