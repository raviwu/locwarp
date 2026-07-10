"""HTTP contract for /api/recent.

Two invariants the recorder design depends on:

1. `POST /api/recent` accepts only the five MANUAL kinds, so route stops can be
   written by the backend recorder and nothing else.
2. `GET /api/recent` has no `response_model`, so the optional `visit_count`
   field reaches the renderer untouched. If someone ever adds a response_model
   without listing `visit_count`, this test catches the silent strip.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    import main
    # Instantiated without a `with` block on purpose: that skips the lifespan,
    # so no device watchdogs / backup loop start for a pure routing test.
    return TestClient(main.app)


def test_post_rejects_the_route_stop_kind():
    r = _client().post("/api/recent", json={"lat": 1.0, "lng": 2.0, "kind": "route_stop"})
    assert r.status_code == 422


def test_post_accepts_a_manual_kind():
    r = _client().post("/api/recent", json={"lat": 1.0, "lng": 2.0, "kind": "teleport"})
    assert r.status_code == 200
    assert r.json()["kind"] == "teleport"


def test_get_passes_visit_count_through():
    import services.recent as recent
    recent.get_manager().push_route_stop(25.0, 121.0)
    recent.get_manager().push_route_stop(25.0, 121.0)  # same spot, next lap

    rows = _client().get("/api/recent").json()
    route_rows = [r for r in rows if r["kind"] == "route_stop"]
    assert len(route_rows) == 1
    assert route_rows[0]["visit_count"] == 2


def test_get_omits_visit_count_on_manual_rows():
    import services.recent as recent
    recent.get_manager().push(1.0, 2.0, "teleport")
    rows = _client().get("/api/recent").json()
    assert "visit_count" not in rows[0]


def test_delete_clears_both_classes():
    import services.recent as recent
    recent.get_manager().push(1.0, 2.0, "teleport")
    recent.get_manager().push_route_stop(25.0, 121.0)

    c = _client()
    assert c.delete("/api/recent").status_code == 200
    assert c.get("/api/recent").json() == []
