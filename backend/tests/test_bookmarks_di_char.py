"""Characterization tests for bookmarks DI sweep (Task 22).

Pins three invariants:
1. GET /api/bookmarks returns {categories, bookmarks} via the injected manager.
2. A None bookmark_manager returns 503 (not 500/AttributeError).
3. The ui-state round-trip reads/writes through the injected engine_registry.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── shared fixture helpers ─────────────────────────────────────────────────────


def _fresh_client(tmp_path, monkeypatch):
    """TestClient with bookmark store redirected to tmp_path."""
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    import main
    from services.bookmarks import BookmarkManager

    main.app_state.bookmark_manager = BookmarkManager()
    return TestClient(main.app)


# ── Test 1: list returns {categories, bookmarks} via injected manager ─────────


def test_list_bookmarks_returns_shape(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    resp = client.get("/api/bookmarks")
    assert resp.status_code == 200
    body = resp.json()
    assert "categories" in body
    assert "bookmarks" in body


# ── Test 2: 503 when bookmark_manager is None ─────────────────────────────────


def test_list_bookmarks_503_when_manager_none(tmp_path, monkeypatch):
    """When container.bookmark_manager is None, endpoint must return 503."""
    import main

    # Redirect store so we don't corrupt real data
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    # Force container to expose None as bookmark_manager
    original_bm = main.app_state.bookmark_manager
    try:
        main.app_state.bookmark_manager = None
        client = TestClient(main.app)
        resp = client.get("/api/bookmarks")
        assert resp.status_code == 503
    finally:
        main.app_state.bookmark_manager = original_bm


# ── Test 3: ui-state round-trip through registry ──────────────────────────────


def test_ui_state_round_trip(tmp_path, monkeypatch):
    """GET + POST /api/bookmarks/ui-state read/write through engine_registry."""
    client = _fresh_client(tmp_path, monkeypatch)

    # Initial state
    resp = client.get("/api/bookmarks/ui-state")
    assert resp.status_code == 200

    # Set expanded + hidden categories
    payload = {
        "expanded_categories": ["cat-1", "cat-2"],
        "hidden_categories": ["cat-3"],
    }
    resp = client.post("/api/bookmarks/ui-state", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["expanded_categories"] == ["cat-1", "cat-2"]
    assert body["hidden_categories"] == ["cat-3"]

    # GET should reflect persisted values
    resp2 = client.get("/api/bookmarks/ui-state")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["expanded_categories"] == ["cat-1", "cat-2"]
    assert body2["hidden_categories"] == ["cat-3"]
