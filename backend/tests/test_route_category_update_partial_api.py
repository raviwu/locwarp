"""HTTP-level tests for the partial-update ``PUT /api/route/categories/{id}``.

The route-store half of fix F, shipped with change G's Task 0. It was the last
known unconditional re-stamp in either store, and it carried the same two
defects the bookmark side had before ``b35ffeb`` / ``bf4d606``:

  1. The body was parsed as a full ``RouteCategory``, whose ``color`` default
     (``"#6c8cff"``) is concrete — so a client that sent only a name silently
     reset the colour. The frontend papered over that by re-sending its own
     in-memory copy of the other field, which turned every rename into "also
     write my possibly-stale colour" and vice versa.
  2. ``RouteManager.update_category`` re-stamped ``updated_at`` unconditionally,
     so a Save that changed nothing still produced a fresh timestamp and could
     out-vote a newer, still-unsynced edit on the other Mac.

Mirrors ``test_bookmark_update_partial_api.py``; keep the two in step.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "routes.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    import main
    from bootstrap.factories import make_route_manager
    main.app_state.route_manager = make_route_manager()
    return TestClient(main.app)


def _create(client, name="Kyoto loops", color="#ff0000") -> dict:
    resp = client.post("/api/route/categories", json={"name": name, "color": color})
    assert resp.status_code == 200
    return resp.json()


def _fetch(client, cat_id: str) -> dict:
    resp = client.get("/api/route/categories")
    assert resp.status_code == 200
    return next(c for c in resp.json() if c["id"] == cat_id)


def test_put_with_only_a_name_leaves_the_colour_alone(client):
    """The defect that made every rename a colour write."""
    cat = _create(client, name="Kyoto loops", color="#ff0000")

    resp = client.put(f"/api/route/categories/{cat['id']}", json={"name": "Kyoto walks"})
    assert resp.status_code == 200

    after = _fetch(client, cat["id"])
    assert after["name"] == "Kyoto walks"
    assert after["color"] == "#ff0000", "an omitted colour must not fall back to the schema default"


def test_put_with_only_a_colour_leaves_the_name_alone(client):
    cat = _create(client, name="Kyoto loops", color="#ff0000")

    resp = client.put(f"/api/route/categories/{cat['id']}", json={"color": "#00ff00"})
    assert resp.status_code == 200

    after = _fetch(client, cat["id"])
    assert after["name"] == "Kyoto loops", "an omitted name must not be blanked"
    assert after["color"] == "#00ff00"


def test_put_with_an_empty_body_writes_nothing(client, store_path):
    """The category dialog submits an empty patch when nothing was changed."""
    cat = _create(client)
    before_bytes = store_path.read_bytes()
    before_mtime = store_path.stat().st_mtime_ns

    resp = client.put(f"/api/route/categories/{cat['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["updated_at"] == cat["updated_at"]

    assert store_path.read_bytes() == before_bytes
    assert store_path.stat().st_mtime_ns == before_mtime, "a no-op PUT must not reach the store at all"


def test_put_resending_the_stored_values_skips_the_save(client, store_path):
    """Asserted at the FILE, not just on the response.

    A response-only assertion would still pass if the early return re-added
    ``self._save()`` — and a save is exactly what makes a no-op dangerous,
    because it merges against the on-disk copy.
    """
    cat = _create(client, name="Kyoto loops", color="#ff0000")
    before_bytes = store_path.read_bytes()
    before_mtime = store_path.stat().st_mtime_ns

    resp = client.put(
        f"/api/route/categories/{cat['id']}",
        json={"name": "Kyoto loops", "color": "#ff0000"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated_at"] == cat["updated_at"]

    assert store_path.read_bytes() == before_bytes
    assert store_path.stat().st_mtime_ns == before_mtime


def test_put_changing_one_field_still_re_stamps(client, store_path):
    """The guard must not suppress a genuine edit."""
    cat = _create(client, name="Kyoto loops", color="#ff0000")

    resp = client.put(f"/api/route/categories/{cat['id']}", json={"color": "#0000ff"})
    assert resp.status_code == 200
    assert resp.json()["updated_at"] != cat["updated_at"]

    on_disk = json.loads(store_path.read_text())
    stored = next(c for c in on_disk["categories"] if c["id"] == cat["id"])
    assert stored["color"] == "#0000ff"
    assert stored["updated_at"] != cat["updated_at"]


def test_put_explicit_null_is_ignored_not_applied(client):
    """``None`` means "not sent", the same as an omitted key."""
    cat = _create(client, name="Kyoto loops", color="#ff0000")

    resp = client.put(
        f"/api/route/categories/{cat['id']}",
        json={"name": None, "color": "#00ff00"},
    )
    assert resp.status_code == 200

    after = _fetch(client, cat["id"])
    assert after["name"] == "Kyoto loops"
    assert after["color"] == "#00ff00"


def test_put_on_a_missing_category_is_404(client):
    resp = client.put("/api/route/categories/nope", json={"name": "x"})
    assert resp.status_code == 404
