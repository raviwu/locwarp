"""api/deps.py providers resolve the right Container attribute; the lazy-manager
providers raise 503 while the manager is still None (pre-load_state)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import deps


def _fake_request(container):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


def test_simple_providers_return_container_attrs():
    c = SimpleNamespace(
        engine_registry=object(), cooldown_timer=object(), coord_formatter=object(),
        helper_client=object(), geocoding_service=object(), route_service=object(),
        gpx_service=object())
    req = _fake_request(c)
    assert deps.get_engine_registry(req) is c.engine_registry
    assert deps.get_cooldown_timer(req) is c.cooldown_timer
    assert deps.get_coord_formatter(req) is c.coord_formatter
    assert deps.get_helper_client(req) is c.helper_client
    assert deps.get_geocoding_service(req) is c.geocoding_service
    assert deps.get_route_service(req) is c.route_service
    assert deps.get_gpx_service(req) is c.gpx_service


def test_bookmark_manager_provider_returns_when_present():
    mgr = object()
    assert deps.get_bookmark_manager(_fake_request(SimpleNamespace(bookmark_manager=mgr))) is mgr


def test_bookmark_manager_provider_raises_503_when_none():
    with pytest.raises(HTTPException) as exc:
        deps.get_bookmark_manager(_fake_request(SimpleNamespace(bookmark_manager=None)))
    assert exc.value.status_code == 503


def test_route_manager_provider_returns_when_present():
    mgr = object()
    assert deps.get_route_manager(_fake_request(SimpleNamespace(route_manager=mgr))) is mgr


def test_route_manager_provider_raises_503_when_none():
    with pytest.raises(HTTPException) as exc:
        deps.get_route_manager(_fake_request(SimpleNamespace(route_manager=None)))
    assert exc.value.status_code == 503
