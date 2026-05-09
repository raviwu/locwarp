"""FastAPI integration tests for /api/bookmarks endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with the bookmark store redirected to tmp_path."""
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    # Force a fresh BookmarkManager so the patched path takes effect.
    import main
    from services.bookmarks import BookmarkManager
    main.app_state.bookmark_manager = BookmarkManager()
    return TestClient(main.app)


def _create_category(client, name="evt"):
    resp = client.post("/api/bookmarks/categories", json={"name": name})
    assert resp.status_code == 200
    return resp.json()


def _create_bookmark(client, cat_id, name="x", lat=0.0, lng=0.0):
    resp = client.post("/api/bookmarks", json={
        "name": name, "lat": lat, "lng": lng, "category_id": cat_id,
    })
    assert resp.status_code == 200
    return resp.json()


def test_delete_category_cascade_false_default(client):
    cat = _create_category(client)
    bm = _create_bookmark(client, cat["id"])
    resp = client.delete(f"/api/bookmarks/categories/{cat['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 0
    # Bookmark still present, in default
    listing = client.get("/api/bookmarks").json()
    surviving = [b for b in listing["bookmarks"] if b["id"] == bm["id"]]
    assert surviving and surviving[0]["category_id"] == "default"


def test_delete_category_cascade_true_removes_bookmarks(client):
    cat = _create_category(client)
    bm = _create_bookmark(client, cat["id"])
    resp = client.delete(f"/api/bookmarks/categories/{cat['id']}?cascade=true")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 1
    listing = client.get("/api/bookmarks").json()
    assert not any(b["id"] == bm["id"] for b in listing["bookmarks"])


def test_delete_default_category_with_cascade_blocked(client):
    resp = client.delete("/api/bookmarks/categories/default?cascade=true")
    assert resp.status_code == 400
