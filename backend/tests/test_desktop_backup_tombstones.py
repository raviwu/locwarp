"""scripts/desktop_backup.py must fetch the FULL bookmark store.

GET /api/bookmarks is the UI list endpoint and carries no deletion history, so
backing up through it produces a snapshot that resurrects deleted bookmarks on
restore — the 2026-09-18 incident. The script now uses GET /api/bookmarks/store
and falls back only against an older backend.

Loaded by file path via importlib, like tests/test_desktop_backup_recent.py.
"""
from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "desktop_backup.py"


@pytest.fixture
def desktop_backup():
    spec = importlib.util.spec_from_file_location("desktop_backup_tombstones_under_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


def test_bookmarks_leg_requests_the_full_store_endpoint(desktop_backup, monkeypatch):
    calls = []

    def fake_get(path):
        calls.append(path)
        return {"categories": [], "bookmarks": [], "tombstones": [{"id": "x"}]}

    monkeypatch.setattr(desktop_backup, "_get", fake_get)
    result = desktop_backup._get_bookmarks_store()

    assert calls == ["/api/bookmarks/store"]
    assert result["tombstones"] == [{"id": "x"}]


def test_falls_back_to_the_list_endpoint_on_404(desktop_backup, monkeypatch, capsys):
    calls = []

    def fake_get(path):
        calls.append(path)
        if path == "/api/bookmarks/store":
            raise _http_error(404)
        return {"categories": [], "bookmarks": []}

    monkeypatch.setattr(desktop_backup, "_get", fake_get)
    result = desktop_backup._get_bookmarks_store()

    assert calls == ["/api/bookmarks/store", "/api/bookmarks"]
    assert "bookmarks" in result
    assert "NO bookmark tombstones" in capsys.readouterr().err


def test_a_non_404_http_error_is_not_swallowed(desktop_backup, monkeypatch):
    """HTTPError subclasses URLError, so main()'s unreachable-backend handler
    would silently return 0. Only a 404 may fall back; a 500 must propagate."""
    def fake_get(path):
        raise _http_error(500)

    monkeypatch.setattr(desktop_backup, "_get", fake_get)
    with pytest.raises(urllib.error.HTTPError):
        desktop_backup._get_bookmarks_store()


def test_snapshot_note_is_identical_in_both_writers():
    """Two tools write the same locwarp-latest-backup.json and overwrite each
    other's copy (in-process BackupService every 5 min, this script every 60 s
    via launchd). A reader who opens that file must get the same instruction
    whichever one wrote it — and the instruction matters, because the import
    endpoints named by the OLD note silently drop tombstones.

    desktop_backup.py cannot import the backend (dependency-free, plain system
    python3), so the string is duplicated on purpose; this pins the duplicate.
    """
    import ast
    from datetime import datetime, timezone

    from domain.backup import build_snapshot

    expected = build_snapshot({}, {}, [], datetime.now(timezone.utc), "x")["_backup_meta"]["note"]

    tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
    notes = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.startswith("Insurance snapshot")
    ]
    assert notes == [expected], (
        "scripts/desktop_backup.py's _backup_meta note drifted from "
        "backend/domain/backup.py's — they must stay identical"
    )
