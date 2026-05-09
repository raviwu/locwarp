"""Tests for GET /api/bookmarks/catalog."""
from __future__ import annotations

import json
from pathlib import Path

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


def test_get_catalog_returns_bundled_payload(client):
    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert "categories" in body
    assert "bookmarks" in body
    # Sanity: the seed file currently has six curated categories.
    # (Update this list when the curator adds a new entry.)
    cat_names = [c["name"] for c in body["categories"]]
    assert "Sapporo Pikmin Bloom Tour" in cat_names
    assert "京都散步" in cat_names
    assert "每月拿禮物" in cat_names
    assert "每月照片鈕扣" in cat_names
    assert "Sanga Stadium by KYOCERA" in cat_names
    assert "宮島 SA 活動" in cat_names
    # Dates round-trip on time-bound entries.
    sanga = next(c for c in body["categories"] if c["name"] == "Sanga Stadium by KYOCERA")
    assert sanga["start_date"] == "2026-02-06"
    assert sanga["end_date"] == "2026-06-07"
    miyajima = next(c for c in body["categories"] if c["name"] == "宮島 SA 活動")
    assert miyajima["start_date"] == "2026-03-01"
    assert miyajima["end_date"] == "2026-05-10"
    # Evergreen entries leave both dates empty.
    kyoto = next(c for c in body["categories"] if c["name"] == "京都散步")
    assert kyoto["start_date"] == ""
    assert kyoto["end_date"] == ""
    monthly_gifts = next(c for c in body["categories"] if c["name"] == "每月拿禮物")
    assert monthly_gifts["start_date"] == ""
    assert monthly_gifts["end_date"] == ""


def test_get_catalog_404_when_file_missing(client, tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: missing)
    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 404


def test_get_catalog_500_when_malformed(client, tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: bad)
    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 500
