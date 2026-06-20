"""AppState.create_engine_for_device guards check->await->assign with _engines_lock
so two concurrent calls for the same udid create exactly one engine."""

import asyncio
import pytest


@pytest.mark.asyncio
async def test_concurrent_create_engine_creates_one(monkeypatch):
    from main import app_state

    # Fresh state.
    app_state.simulation_engines.clear()
    app_state._primary_udid = None

    created = []

    class FakeLocService:
        async def set(self, lat, lng):
            pass

    async def slow_get_location_service(udid):
        await asyncio.sleep(0)  # yield, widening the race window
        return FakeLocService()

    monkeypatch.setattr(
        app_state.device_manager, "get_location_service", slow_get_location_service
    )

    udid = "RACE-UDID"
    await asyncio.gather(
        app_state.create_engine_for_device(udid),
        app_state.create_engine_for_device(udid),
    )
    assert list(app_state.simulation_engines.keys()).count(udid) == 1

    # cleanup
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


@pytest.mark.asyncio
async def test_remove_engine_pops_and_promotes_primary():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state.simulation_engines["B"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("A")
    assert "A" not in app_state.simulation_engines
    assert app_state._primary_udid == "B"
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


@pytest.mark.asyncio
async def test_remove_engine_non_primary_keeps_primary():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state.simulation_engines["B"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("B")
    assert "B" not in app_state.simulation_engines
    assert app_state._primary_udid == "A"
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


@pytest.mark.asyncio
async def test_remove_engine_last_engine_sets_primary_none():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("A")
    assert app_state.simulation_engines == {}
    assert app_state._primary_udid is None


@pytest.mark.asyncio
async def test_remove_engine_unknown_udid_is_noop():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("ZZZ")
    assert "A" in app_state.simulation_engines
    assert app_state._primary_udid == "A"
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
