"""Characterization: Container.bookmark_manager / route_manager delegate LIVE to
engine_registry, so a Container built BEFORE load_state() (managers None) starts
returning the real managers the instant engine_registry sets them; api.deps's
503 guard covers the None window. Pins behavior before tightening the property."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import deps
from bootstrap.container import Container


def _container(engine_registry):
    return Container(
        device_manager=SimpleNamespace(), event_publisher=SimpleNamespace(),
        tunnel_registry=SimpleNamespace(), engines_lock=asyncio.Lock(),
        engine_registry=engine_registry,
        cooldown_timer=object(), coord_formatter=object(), helper_client=object(),
        geocoding_service=object(), route_service=object(), gpx_service=object(),
        bookmark_manager=None, route_manager=None,
    )


def _req(container):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


def test_delegates_none_before_load_state_then_real_after():
    # engine_registry mimics AppState: managers None pre-load_state.
    reg = SimpleNamespace(bookmark_manager=None, route_manager=None)
    c = _container(reg)
    assert c.bookmark_manager is None
    assert c.route_manager is None
    # 503 guard fires while None (the deps provider, not the property, raises).
    with pytest.raises(HTTPException) as exc:
        deps.get_bookmark_manager(_req(c))
    assert exc.value.status_code == 503
    # load_state() assigns the real managers on engine_registry...
    real_bm, real_rt = object(), object()
    reg.bookmark_manager = real_bm
    reg.route_manager = real_rt
    # ...and the property delegates LIVE, no rebuild needed.
    assert c.bookmark_manager is real_bm
    assert c.route_manager is real_rt
    assert deps.get_bookmark_manager(_req(c)) is real_bm
    assert deps.get_route_manager(_req(c)) is real_rt


def test_real_app_managers_track_app_state_after_load():
    import main
    c = main.app.state.container
    # Whatever app_state currently holds, the container mirrors it identically.
    assert c.bookmark_manager is main.app_state.bookmark_manager
    assert c.route_manager is main.app_state.route_manager
