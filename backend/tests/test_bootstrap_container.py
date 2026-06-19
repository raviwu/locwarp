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

    dm = _FakeDM()
    pub = _FakePub()
    reg = _FakeReg()

    c = Container(
        device_manager=dm,
        event_publisher=pub,
        tunnel_registry=reg,
        engines_lock=lock,
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


def test_container_device_service_not_yet_wired():
    """device_service raises NotImplementedError until Task 7."""
    lock = asyncio.Lock()

    class _Stub:
        pass

    c = Container(
        device_manager=_Stub(),
        event_publisher=_Stub(),
        tunnel_registry=_Stub(),
        engines_lock=lock,
    )
    with pytest.raises(NotImplementedError):
        _ = c.device_service
