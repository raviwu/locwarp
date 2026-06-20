"""Characterization tests for services.cooldown.CooldownTimer.

These freeze the ACTUAL current behavior of the Pokemon GO-style cooldown
pacing timer: the COOLDOWN_TABLE lookup, distance->seconds computation, the
start/dismiss lifecycle, and the get_status snapshot. Clock and asyncio.sleep
are injected for determinism; no real wall-clock waits, no network.
"""

from __future__ import annotations

import asyncio

import pytest

from config import COOLDOWN_TABLE
from services.cooldown import CooldownTimer
from services.interpolator import RouteInterpolator

# Capture the real asyncio.sleep up front. Tests monkeypatch
# services.cooldown.asyncio.sleep, which mutates the shared asyncio module's
# attribute globally -- so any plain `asyncio.sleep(...)` in a test body or
# inside a fake_sleep would otherwise re-enter the fake and deadlock. Use this
# reference for the genuine "yield to the loop" calls.
_real_sleep = asyncio.sleep


# ---------------------------------------------------------------------------
# calculate_cooldown — the threshold table
# ---------------------------------------------------------------------------


def test_table_is_the_expected_frozen_shape():
    # Freeze the actual config table so a silent edit is caught here.
    assert COOLDOWN_TABLE == [
        (1, 0),
        (5, 30),
        (10, 120),
        (25, 300),
        (100, 900),
        (250, 1500),
        (500, 2700),
        (750, 3600),
        (1000, 5400),
        (float("inf"), 7200),
    ]


@pytest.mark.parametrize(
    "distance_km,expected",
    [
        (0.0, 0),       # <= 1 km bucket
        (1.0, 0),       # exactly at the 1 km boundary -> still 0
        (1.0001, 30),   # just over 1 km
        (5.0, 30),      # boundary of 5 km bucket
        (5.5, 120),     # into 10 km bucket
        (10.0, 120),
        (25.0, 300),
        (100.0, 900),
        (250.0, 1500),
        (500.0, 2700),
        (750.0, 3600),
        (1000.0, 5400),
        (1000.0001, 7200),  # past last finite bucket -> inf bucket
        (99999.0, 7200),    # very large -> inf bucket
    ],
)
def test_calculate_cooldown_table_lookup(distance_km, expected):
    timer = CooldownTimer()
    assert timer.calculate_cooldown(distance_km) == expected


def test_calculate_cooldown_negative_distance_hits_first_bucket():
    # Negative distance is <= 1 so it returns the first bucket's 0.
    timer = CooldownTimer()
    assert timer.calculate_cooldown(-50.0) == 0


# ---------------------------------------------------------------------------
# Initial state / get_status snapshot
# ---------------------------------------------------------------------------


def test_initial_state_defaults():
    timer = CooldownTimer()
    assert timer.enabled is False
    assert timer.is_active is False
    assert timer.remaining == 0.0
    assert timer.total == 0.0
    assert timer.distance_km == 0.0


def test_get_status_snapshot_when_idle():
    timer = CooldownTimer()
    status = timer.get_status()
    assert status == {
        "enabled": False,
        "is_active": False,
        "remaining_seconds": 0.0,
        "total_seconds": 0.0,
        "distance_km": 0.0,
    }


def test_get_status_reflects_enabled_flag():
    timer = CooldownTimer()
    timer.enabled = True
    status = timer.get_status()
    assert status["enabled"] is True
    # Still inactive -> remaining stays 0; the active-refresh branch is skipped.
    assert status["is_active"] is False
    assert status["remaining_seconds"] == 0.0


def test_get_status_refreshes_remaining_from_clock_while_active(monkeypatch):
    # Drive the active-branch wall-clock refresh deterministically.
    clock = {"t": 1000.0}
    monkeypatch.setattr(
        "services.cooldown.time.monotonic", lambda: clock["t"]
    )

    timer = CooldownTimer()
    timer.is_active = True
    timer.total = 300.0
    timer.remaining = 300.0
    timer._start_time = 1000.0
    timer.distance_km = 23.456

    # 100 s elapsed -> remaining should be 200.
    clock["t"] = 1100.0
    status = timer.get_status()
    assert status["is_active"] is True
    assert status["remaining_seconds"] == 200.0
    assert status["total_seconds"] == 300.0
    # distance_km is rounded to 2 dp in the snapshot.
    assert status["distance_km"] == 23.46


def test_get_status_remaining_floors_at_zero(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(
        "services.cooldown.time.monotonic", lambda: clock["t"]
    )
    timer = CooldownTimer()
    timer.is_active = True
    timer.total = 30.0
    timer._start_time = 0.0
    # Way past total -> clamps to 0, never negative.
    clock["t"] = 9999.0
    status = timer.get_status()
    assert status["remaining_seconds"] == 0.0


# ---------------------------------------------------------------------------
# start() — disabled / zero-cooldown short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_noop_when_disabled():
    timer = CooldownTimer()
    assert timer.enabled is False
    # Large hop, but disabled -> nothing happens.
    await timer.start(25.0, 121.0, 35.0, 139.0)
    assert timer.is_active is False
    assert timer.total == 0.0
    assert timer._task is None


@pytest.mark.asyncio
async def test_start_zero_cooldown_for_tiny_hop_does_not_activate():
    timer = CooldownTimer()
    timer.enabled = True
    # Same point -> distance 0 -> cooldown 0 -> early return, but distance_km
    # IS recorded before the zero-cooldown bail-out.
    await timer.start(25.0375, 121.5637, 25.0375, 121.5637)
    assert timer.is_active is False
    assert timer.total == 0.0
    assert timer._task is None
    assert timer.distance_km == pytest.approx(0.0, abs=1e-6)


@pytest.mark.asyncio
async def test_start_activates_and_computes_distance_for_real_hop(monkeypatch):
    # Freeze monotonic so _start_time is deterministic; stub asyncio.sleep so
    # the countdown task parks instead of really sleeping a second.
    monkeypatch.setattr("services.cooldown.time.monotonic", lambda: 500.0)

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        # Park forever so remaining is never decremented by the task; the test
        # cancels via dismiss().
        await asyncio.Event().wait()

    monkeypatch.setattr("services.cooldown.asyncio.sleep", fake_sleep)

    timer = CooldownTimer()
    timer.enabled = True

    # Taipei -> roughly 30+ km hop. Compute the expected distance the same way
    # the module does, then assert the bucket it lands in.
    from_lat, from_lng = 25.0375, 121.5637
    to_lat, to_lng = 25.3, 121.5637
    dist_m = RouteInterpolator.haversine(from_lat, from_lng, to_lat, to_lng)
    expected_km = dist_m / 1000.0
    expected_sec = timer.calculate_cooldown(expected_km)
    assert expected_sec > 0  # sanity: this hop should trigger a cooldown

    await timer.start(from_lat, from_lng, to_lat, to_lng)

    assert timer.is_active is True
    assert timer.distance_km == pytest.approx(expected_km)
    assert timer.total == float(expected_sec)
    assert timer.remaining == float(expected_sec)
    assert timer._start_time == 500.0
    assert timer._task is not None

    # Give the event loop a tick so the countdown task runs to its sleep call.
    await _real_sleep(0)
    assert sleep_calls == [1.0]

    # Clean up the parked task.
    await timer.dismiss()
    assert timer.is_active is False
    assert timer.remaining == 0.0
    assert timer._task is None


# ---------------------------------------------------------------------------
# dismiss()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_when_no_task_resets_state():
    timer = CooldownTimer()
    timer.is_active = True
    timer.remaining = 42.0
    await timer.dismiss()
    assert timer.is_active is False
    assert timer.remaining == 0.0
    assert timer._task is None


@pytest.mark.asyncio
async def test_dismiss_cancels_running_task(monkeypatch):
    monkeypatch.setattr("services.cooldown.time.monotonic", lambda: 0.0)

    async def fake_sleep(secs):
        await asyncio.Event().wait()  # park forever until cancelled

    monkeypatch.setattr("services.cooldown.asyncio.sleep", fake_sleep)

    timer = CooldownTimer()
    timer.enabled = True
    await timer.start(0.0, 0.0, 1.0, 1.0)  # ~157 km -> a real cooldown
    assert timer._task is not None
    task = timer._task

    await timer.dismiss()
    assert task.cancelled() or task.done()
    assert timer._task is None
    assert timer.is_active is False
    assert timer.remaining == 0.0


@pytest.mark.asyncio
async def test_start_cancels_previous_timer(monkeypatch):
    # start() calls dismiss() first; a second start replaces the first task.
    monkeypatch.setattr("services.cooldown.time.monotonic", lambda: 0.0)

    async def fake_sleep(secs):
        await asyncio.Event().wait()

    monkeypatch.setattr("services.cooldown.asyncio.sleep", fake_sleep)

    timer = CooldownTimer()
    timer.enabled = True

    await timer.start(0.0, 0.0, 1.0, 1.0)
    first_task = timer._task
    assert first_task is not None

    await timer.start(0.0, 0.0, 2.0, 2.0)
    second_task = timer._task
    assert second_task is not None
    assert second_task is not first_task
    assert first_task.cancelled() or first_task.done()

    await timer.dismiss()


# ---------------------------------------------------------------------------
# _countdown finishes naturally when remaining already drained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_countdown_finishes_when_clock_already_past_total(monkeypatch):
    # If monotonic jumps past start_time + total on the first tick, remaining
    # drains to 0 and the loop exits, clearing is_active in the finally block.
    clock = {"t": 0.0}
    monkeypatch.setattr(
        "services.cooldown.time.monotonic", lambda: clock["t"]
    )

    async def fake_sleep(secs):
        # Advance the clock far past total during the one sleep, then yield.
        clock["t"] = 100000.0
        await _real_sleep(0)

    monkeypatch.setattr("services.cooldown.asyncio.sleep", fake_sleep)

    timer = CooldownTimer()
    timer.enabled = True
    await timer.start(0.0, 0.0, 1.0, 1.0)
    task = timer._task

    await asyncio.wait_for(task, timeout=1.0)

    assert task.done()
    assert timer.is_active is False
    assert timer.remaining == 0.0
