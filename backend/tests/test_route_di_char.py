"""Characterization tests for route.py DI sweep (Task 23).

Pins three invariants:
1. A None route_manager returns 503 (not 500/AttributeError).
2. GET /api/route/saved returns a list via the injected route_manager.
3. GET /api/route/categories returns a list via the injected route_manager.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


# ── shared fixture helpers ─────────────────────────────────────────────────────


def _fresh_client(tmp_path, monkeypatch):
    """TestClient with route store redirected to tmp_path."""
    monkeypatch.setattr(
        "services.route_store.ROUTES_FILE",
        tmp_path / "routes.json",
    )
    import main
    from services.route_store import RouteManager

    main.app_state.route_manager = RouteManager()
    return TestClient(main.app)


# ── Test 1: 503 when route_manager is None ────────────────────────────────────


def test_list_saved_routes_503_when_manager_none(tmp_path, monkeypatch):
    """When container.route_manager is None, endpoint must return 503."""
    import main

    monkeypatch.setattr(
        "services.route_store.ROUTES_FILE",
        tmp_path / "routes.json",
    )
    original_rm = main.app_state.route_manager
    try:
        main.app_state.route_manager = None
        client = TestClient(main.app)
        resp = client.get("/api/route/saved")
        assert resp.status_code == 503
    finally:
        main.app_state.route_manager = original_rm


# ── Test 2: GET /api/route/saved returns list via injected manager ────────────


def test_list_saved_routes_returns_list(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    resp = client.get("/api/route/saved")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Test 3: GET /api/route/categories returns list via injected manager ───────


def test_list_route_categories_returns_list(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    resp = client.get("/api/route/categories")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
