"""Tests for event date fields on BookmarkCategory."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    import main
    from bootstrap.factories import make_bookmark_manager
    main.app_state.bookmark_manager = make_bookmark_manager()
    return TestClient(main.app)


def test_bookmark_category_schema_has_event_date_fields():
    from models.schemas import BookmarkCategory

    cat = BookmarkCategory(name="evt")
    assert cat.start_date == ""
    assert cat.end_date == ""


def test_bookmark_category_accepts_iso_dates():
    from models.schemas import BookmarkCategory

    cat = BookmarkCategory(
        name="Sanga",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    assert cat.start_date == "2026-02-06"
    assert cat.end_date == "2026-06-07"


def test_bookmark_store_round_trips_legacy_payload():
    """A bookmarks.json without the new keys still parses (defaults to '')."""
    from models.schemas import BookmarkStore

    store = BookmarkStore(**{
        "categories": [{
            "id": "x",
            "name": "old",
            "color": "#000",
            "sort_order": 0,
            "created_at": "2026-01-01T00:00:00Z",
        }],
        "bookmarks": [],
    })
    assert store.categories[0].start_date == ""
    assert store.categories[0].end_date == ""


def test_validate_date_range_accepts_empty():
    from api.bookmarks import _validate_date_range
    _validate_date_range("", "")  # no exception


def test_validate_date_range_accepts_only_start():
    from api.bookmarks import _validate_date_range
    _validate_date_range("2026-06-01", "")  # no exception


def test_validate_date_range_accepts_only_end():
    from api.bookmarks import _validate_date_range
    _validate_date_range("", "2026-06-01")  # no exception


def test_validate_date_range_accepts_valid_range():
    from api.bookmarks import _validate_date_range
    _validate_date_range("2026-02-06", "2026-06-07")  # no exception


def test_validate_date_range_rejects_slash_format():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("2026/06/01", "")
    assert excinfo.value.status_code == 422


def test_validate_date_range_rejects_garbage_string():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("not-a-date", "")
    assert excinfo.value.status_code == 422


def test_validate_date_range_rejects_invalid_calendar_date():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("2026-13-01", "")
    assert excinfo.value.status_code == 422


def test_validate_date_range_rejects_inverted_range():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("2026-06-30", "2026-06-29")
    assert excinfo.value.status_code == 422
    assert "<= end_date" in excinfo.value.detail


def _make_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


def test_create_category_persists_event_dates(tmp_path, monkeypatch):
    bm = _make_manager(tmp_path, monkeypatch)
    cat = bm.create_category(
        name="Sanga",
        color="#ef4444",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    assert cat.start_date == "2026-02-06"
    assert cat.end_date == "2026-06-07"

    # Reload from disk to confirm persistence
    from bootstrap.factories import make_bookmark_manager
    reloaded = make_bookmark_manager()
    found = next(c for c in reloaded.list_categories() if c.id == cat.id)
    assert found.start_date == "2026-02-06"
    assert found.end_date == "2026-06-07"


def test_update_category_with_empty_string_clears_date(tmp_path, monkeypatch):
    bm = _make_manager(tmp_path, monkeypatch)
    cat = bm.create_category(
        name="Sanga",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    updated = bm.update_category(cat.id, start_date="", end_date="")
    assert updated is not None
    assert updated.start_date == ""
    assert updated.end_date == ""


def test_update_category_with_none_preserves_date(tmp_path, monkeypatch):
    bm = _make_manager(tmp_path, monkeypatch)
    cat = bm.create_category(
        name="Sanga",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    updated = bm.update_category(cat.id, name="Renamed")
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.start_date == "2026-02-06"
    assert updated.end_date == "2026-06-07"


def test_post_category_with_dates(client):
    resp = client.post("/api/bookmarks/categories", json={
        "name": "Sanga",
        "color": "#ef4444",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["start_date"] == "2026-02-06"
    assert body["end_date"] == "2026-06-07"


def test_post_category_rejects_bad_date_format(client):
    resp = client.post("/api/bookmarks/categories", json={
        "name": "Bad",
        "start_date": "2026/02/06",
    })
    assert resp.status_code == 422


def test_post_category_rejects_inverted_range(client):
    resp = client.post("/api/bookmarks/categories", json={
        "name": "Bad",
        "start_date": "2026-06-07",
        "end_date": "2026-02-06",
    })
    assert resp.status_code == 422


def test_put_category_updates_dates(client):
    create = client.post("/api/bookmarks/categories", json={
        "name": "Sanga",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    })
    cat = create.json()
    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={
        "name": cat["name"],
        "color": cat["color"],
        "start_date": "",
        "end_date": "",
    })
    assert resp.status_code == 200
    assert resp.json()["start_date"] == ""
    assert resp.json()["end_date"] == ""


def test_put_category_rejects_bad_format(client):
    create = client.post("/api/bookmarks/categories", json={"name": "evt"})
    cat = create.json()
    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={
        "name": cat["name"],
        "color": cat["color"],
        "end_date": "tomorrow",
    })
    assert resp.status_code == 422


def test_get_categories_returns_event_dates(client):
    client.post("/api/bookmarks/categories", json={
        "name": "Sanga",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    })
    listing = client.get("/api/bookmarks").json()
    sanga = next(c for c in listing["categories"] if c["name"] == "Sanga")
    assert sanga["start_date"] == "2026-02-06"
    assert sanga["end_date"] == "2026-06-07"
