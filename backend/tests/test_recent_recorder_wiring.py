"""main.py's engine event_callback is the ONE place a route arrival becomes a
history row. It records before broadcasting (the renderer refetches when it sees
the broadcast), skips the origin waypoint, and only listens to the primary
device's engine — a fan-out run would otherwise count one physical stop once per
phone."""
from __future__ import annotations

import pytest


class _FakeLoc:
    async def set(self, lat, lng):
        pass

    async def clear(self):
        pass


class _FakeDeviceManager:
    async def get_location_service(self, udid):
        return _FakeLoc()


@pytest.fixture
def wired(monkeypatch):
    import main
    import api.websocket as ws

    broadcasts: list[tuple[str, dict]] = []

    async def fake_broadcast(event_type, data):
        broadcasts.append((event_type, dict(data)))

    # create_engine_for_device imports broadcast INSIDE the function body, so
    # patching the module attribute before the call is enough.
    monkeypatch.setattr(ws, "broadcast", fake_broadcast)
    monkeypatch.setattr(main.app_state, "device_manager", _FakeDeviceManager(), raising=False)
    monkeypatch.setattr(main.app_state, "simulation_engines", {}, raising=False)
    monkeypatch.setattr(main.app_state, "_primary_udid", None, raising=False)
    return main, broadcasts


def _stop(lat, lng, origin=False):
    return {"index": 1, "total": 2, "lat": lat, "lng": lng, "origin": origin}


@pytest.mark.asyncio
async def test_primary_records_secondary_and_origin_do_not(wired):
    import services.recent as recent
    main, broadcasts = wired

    await main.app_state.create_engine_for_device("udid-a")  # first device -> primary
    await main.app_state.create_engine_for_device("udid-b")
    eng_a = main.app_state.simulation_engines["udid-a"]
    eng_b = main.app_state.simulation_engines["udid-b"]

    await eng_a.event_callback("stop_reached", _stop(25.0, 121.0))
    await eng_b.event_callback("stop_reached", _stop(30.0, 131.0))          # not primary
    await eng_a.event_callback("stop_reached", _stop(9.0, 9.0, origin=True))  # origin

    rows = [e for e in recent.get_manager().list() if e["kind"] == "route_stop"]
    assert [(e["lat"], e["lng"]) for e in rows] == [(25.0, 121.0)]

    # Every event still reaches the socket, recorded or not.
    assert [t for (t, _d) in broadcasts].count("stop_reached") == 3


@pytest.mark.asyncio
async def test_the_row_exists_before_the_broadcast_goes_out(wired, monkeypatch):
    import services.recent as recent
    import api.websocket as ws
    main, _ = wired

    seen_during_broadcast: list[int] = []

    async def spy_broadcast(event_type, data):
        if event_type == "stop_reached":
            rows = [e for e in recent.get_manager().list() if e["kind"] == "route_stop"]
            seen_during_broadcast.append(len(rows))

    monkeypatch.setattr(ws, "broadcast", spy_broadcast)
    await main.app_state.create_engine_for_device("udid-a")
    eng = main.app_state.simulation_engines["udid-a"]

    await eng.event_callback("stop_reached", _stop(25.0, 121.0))
    # The renderer refetches when it sees the broadcast; the row must already
    # be there when the broadcast is made.
    assert seen_during_broadcast == [1]


@pytest.mark.asyncio
async def test_a_revisit_bumps_visit_count(wired):
    import services.recent as recent
    main, _ = wired

    await main.app_state.create_engine_for_device("udid-a")
    eng = main.app_state.simulation_engines["udid-a"]

    await eng.event_callback("stop_reached", _stop(25.0, 121.0))
    await eng.event_callback("stop_reached", _stop(25.5, 121.5))
    await eng.event_callback("stop_reached", _stop(25.0, 121.0))  # next lap

    rows = [e for e in recent.get_manager().list() if e["kind"] == "route_stop"]
    assert len(rows) == 2
    # Identify by coordinate, not index -- all three pushes land within the
    # same wall-clock second, so their ts values tie and list order comes
    # from a stable sort, not from which row was revisited.
    revisited = next(r for r in rows if (r["lat"], r["lng"]) == (25.0, 121.0))
    other = next(r for r in rows if (r["lat"], r["lng"]) == (25.5, 121.5))
    assert revisited["visit_count"] == 2
    assert other["visit_count"] == 1
