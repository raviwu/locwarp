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
    from bootstrap.factories import make_bookmark_manager
    main.app_state.bookmark_manager = make_bookmark_manager()
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


# ── POST /catalog/sync ──────────────────────────────────────────────


def _seed_catalog(tmp_path):
    """Write a tiny catalog file and return its path."""
    f = tmp_path / "catalog.json"
    f.write_text(json.dumps({
        "categories": [
            {"id": "cat-X", "name": "X", "color": "#000", "sort_order": 1, "created_at": "2026-05-23T00:00:00Z"},
        ],
        "bookmarks": [
            {"id": "bm-X1", "name": "X1", "lat": 1.0, "lng": 2.0, "category_id": "cat-X", "created_at": "2026-05-23T00:00:00Z"},
            {"id": "bm-X2", "name": "X2", "lat": 3.0, "lng": 4.0, "category_id": "cat-X", "created_at": "2026-05-23T00:00:00Z"},
        ],
    }))
    return f


def test_catalog_sync_first_call_adds_all(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: _seed_catalog(tmp_path))
    resp = client.post("/api/bookmarks/catalog/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"added": 3, "updated": 0, "resurrected": 0}


def test_catalog_sync_resurrects_after_delete(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: _seed_catalog(tmp_path))
    # 1) seed
    client.post("/api/bookmarks/catalog/sync")
    # 2) user deletes the category cascade
    resp = client.delete("/api/bookmarks/categories/cat-X?cascade=true")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 2
    # 3) re-sync
    resp = client.post("/api/bookmarks/catalog/sync")
    body = resp.json()
    assert body["resurrected"] == 3
    # The deleted items are back
    listing = client.get("/api/bookmarks").json()
    assert {b["id"] for b in listing["bookmarks"]} >= {"bm-X1", "bm-X2"}


def test_catalog_sync_404_when_file_missing(client, tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: missing)
    resp = client.post("/api/bookmarks/catalog/sync")
    assert resp.status_code == 404
