"""Container builds the wired graph; create_app yields a FastAPI with the
container on app.state and the same routers mounted."""

import pytest
from fastapi import FastAPI

from bootstrap.container import Container, MonotonicClock


def test_monotonic_clock_is_callable_and_increasing():
    clk = MonotonicClock()
    a = clk()
    b = clk()
    assert isinstance(a, float)
    assert b >= a


def test_container_wires_publisher_and_tunnel_registry_into_device_manager():
    c = Container()
    dm = c.device_manager
    # The DeviceManager must carry the publisher + tunnel registry the
    # container built (identity, not just truthiness).
    assert dm._events is c.event_publisher
    assert dm._tunnels is c.tunnel_registry


def test_container_holds_engines_lock():
    import asyncio
    c = Container()
    assert isinstance(c._engines_lock, asyncio.Lock)


def test_create_app_sets_container_on_state():
    from bootstrap.app import create_app
    app = create_app()
    assert isinstance(app, FastAPI)
    assert hasattr(app.state, "container")
    assert isinstance(app.state.container, Container)


def test_create_app_mounts_device_router():
    from bootstrap.app import create_app
    app = create_app()
    # url_path_for resolves named routes regardless of internal router structure.
    try:
        path = str(app.url_path_for("list_devices"))
        assert path.startswith("/api/device")
    except Exception:
        # Fallback: inspect original_router of included routers.
        all_paths = set()
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.add(r.path)
            elif hasattr(r, "original_router"):
                for sub in r.original_router.routes:
                    if hasattr(sub, "path"):
                        all_paths.add(sub.path)
        assert any(p.startswith("/api/device") for p in all_paths)
