"""Container is wired onto the real app using app_state's singletons.

Identity invariants:
  - app.state.container.device_manager IS app_state.device_manager
  - app.state.container._engines_lock IS app_state._engines_lock
  - app.state.container.event_publisher IS app_state.device_manager._events
  - app.state.container.tunnel_registry IS app_state.device_manager._tunnels
"""

import asyncio

import pytest
from fastapi import FastAPI

from bootstrap.container import Container, MonotonicClock


def test_monotonic_clock_is_callable_and_increasing():
    clk = MonotonicClock()
    a = clk()
    b = clk()
    assert isinstance(a, float)
    assert b >= a


def test_container_accepts_injected_singletons():
    """Container stores exactly the instances it is given — no construction."""
    lock = asyncio.Lock()

    class _FakeDM:
        pass

    class _FakePub:
        pass

    class _FakeReg:
        pass

    class _FakeEngineReg:
        pass

    dm = _FakeDM()
    pub = _FakePub()
    reg = _FakeReg()
    eng_reg = _FakeEngineReg()

    c = Container(
        device_manager=dm,
        event_publisher=pub,
        tunnel_registry=reg,
        engines_lock=lock,
        engine_registry=eng_reg,
        cooldown_timer=object(),
        coord_formatter=object(),
        helper_client=object(),
        geocoding_service=object(),
        route_service=object(),
        gpx_service=object(),
        bookmark_manager=None,
        route_manager=None,
    )

    assert c.device_manager is dm
    assert c.event_publisher is pub
    assert c.tunnel_registry is reg
    assert c._engines_lock is lock


def test_real_app_has_container_on_state():
    """main.app carries a Container on its state (set at module load time)."""
    import main

    assert hasattr(main.app.state, "container")
    assert isinstance(main.app.state.container, Container)
    assert isinstance(main.app, FastAPI)


def test_container_device_manager_identity():
    """Container.device_manager is the SAME object as app_state.device_manager."""
    import main

    assert main.app.state.container.device_manager is main.app_state.device_manager


def test_container_engines_lock_identity():
    """Container._engines_lock is the SAME lock as app_state._engines_lock."""
    import main

    assert main.app.state.container._engines_lock is main.app_state._engines_lock


def test_container_event_publisher_identity():
    """Container.event_publisher is the same publisher DeviceManager owns."""
    import main

    assert main.app.state.container.event_publisher is main.app_state.device_manager._events


def test_container_tunnel_registry_identity():
    """Container.tunnel_registry is the same registry DeviceManager owns."""
    import main

    assert main.app.state.container.tunnel_registry is main.app_state.device_manager._tunnels


def test_container_device_service_is_wired():
    """device_service is a DeviceService instance wired to the real app_state (Task 7)."""
    from services.device_service import DeviceService
    import main

    svc = main.app.state.container.device_service
    assert isinstance(svc, DeviceService)
    # Identity invariant: the service's dm is the same singleton DeviceManager.
    assert svc._dm is main.app_state.device_manager


def test_container_stores_engine_registry():
    lock = asyncio.Lock()

    class _Fake:
        pass

    eng_reg = _Fake()
    c = Container(
        device_manager=_Fake(), event_publisher=_Fake(), tunnel_registry=_Fake(),
        engines_lock=lock, engine_registry=eng_reg,
        cooldown_timer=_Fake(), coord_formatter=_Fake(), helper_client=_Fake(),
        geocoding_service=_Fake(), route_service=_Fake(), gpx_service=_Fake(),
        bookmark_manager=None, route_manager=None,
    )
    assert c.engine_registry is eng_reg


def test_container_real_app_engine_registry_identity():
    import main
    assert main.app.state.container.engine_registry is main.app_state


def test_container_real_app_service_singletons_identity():
    import main
    c = main.app.state.container
    assert c.cooldown_timer is main.app_state.cooldown_timer
    assert c.coord_formatter is main.app_state.coord_formatter
    assert c.helper_client is main.helper_client


def test_container_real_app_lazy_managers_track_app_state():
    import main
    c = main.app.state.container
    assert c.bookmark_manager is main.app_state.bookmark_manager
    assert c.route_manager is main.app_state.route_manager


def test_container_real_app_geocode_route_gpx_singletons_present():
    import main
    from services.geocoding import GeocodingService
    from services.route_service import RouteService
    from services.gpx_service import GpxService
    c = main.app.state.container
    assert isinstance(c.geocoding_service, GeocodingService)
    assert isinstance(c.route_service, RouteService)
    assert isinstance(c.gpx_service, GpxService)
