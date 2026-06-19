"""Deterministic time doubles + recording location service for engine
characterization tests (Phase 0a). Shared by all Task-9 sub-tests."""
from __future__ import annotations


class FakeClock:
    """Callable returning a controlled, increasing float (seconds)."""
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += float(dt)


class SteppedSleep:
    """async sleep double: records each duration, advances a FakeClock by it,
    returns immediately (no real wait)."""
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(float(seconds))
        self.clock.advance(seconds)


class RecordingLocation:
    """location_service double. Records every (lat, lng) the engine pushes via
    _set_position -> location_service.set. Also supports .clear() for restore()."""
    def __init__(self) -> None:
        self.pushes: list[tuple[float, float]] = []
        self.clears: int = 0

    async def set(self, lat: float, lng: float) -> None:
        self.pushes.append((lat, lng))

    async def clear(self) -> None:
        self.clears += 1


def make_engine(coords_recorder=None, clock=None, sleep=None):
    """Build a SimulationEngine wired to a recording event_callback.
    Returns (engine, loc, emitted) where emitted is a list of (event_type, data)."""
    from core.simulation_engine import SimulationEngine
    clock = clock or FakeClock()
    loc = RecordingLocation()
    emitted: list[tuple[str, dict]] = []

    async def cb(event_type, data):
        emitted.append((event_type, dict(data)))

    eng = SimulationEngine(
        loc, cb,
        clock=clock,
        sleep=sleep or _noop_sleep,
    )
    return eng, loc, emitted


async def _noop_sleep(_s: float) -> None:
    """Default async sleep double: does nothing (no real wait, no clock advance)."""
    return None
