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
    """Endpoint contract — does NOT lock specific curated content.

    Asserts: 200, valid full-store shape, non-empty payload,
    every bookmark belongs to a real category, every non-empty
    date string is valid ISO. Curator can add / rename / remove
    entries in catalog.json without touching this test.
    """
    import re
    from datetime import date

    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 200
    body = resp.json()

    # Shape
    assert isinstance(body.get("categories"), list)
    assert isinstance(body.get("bookmarks"), list)
    assert body["categories"], "catalog must have at least one category"
    assert body["bookmarks"], "catalog must have at least one bookmark"

    # Referential integrity — every bookmark.category_id resolves.
    cat_ids = {c["id"] for c in body["categories"]}
    orphans = [b["name"] for b in body["bookmarks"] if b["category_id"] not in cat_ids]
    assert not orphans, f"bookmarks reference unknown category: {orphans}"

    # Date hygiene — empty strings allowed; non-empty must parse as ISO.
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for c in body["categories"]:
        for field in ("start_date", "end_date"):
            v = c.get(field, "")
            if v:
                assert iso_re.match(v), f"{c['name']}.{field}={v!r} is not YYYY-MM-DD"
                date.fromisoformat(v)  # raises if invalid calendar date


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
