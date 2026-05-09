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
    from services.bookmarks import BookmarkManager
    main.app_state.bookmark_manager = BookmarkManager()
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
