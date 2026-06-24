# SH3 — Structural Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carve the two god-objects (`api/device.py` WiFi-tunnel state machine, `_move_along_route`), lift recovery orchestration out of the `api/location.py` controller, unify the duplicated store-import + file-watcher logic, tidy the composition root, and cut the frontend re-render storm — all WITHOUT changing any external behavior.

**Architecture:** 14 behavior-preserving, characterization-test-first refactor tasks across 4 clusters: S1 recovery-orchestration + engine-math carve (A2×2, A4×3), S2 `api/device.py` god-module incremental carve (A1×3), S3 store-upsert unify + controller accessors + Container delegation + watcher dedup + geocode DI (A3, X12, A6, A22, A7), S4 frontend re-render reduction (N1). Each carve pins current behavior with a real-collaborator characterization test FIRST, then proves it unchanged.

**Tech Stack:** Python 3.13 / FastAPI / pytest + pytest-asyncio (backend); React 18 + TypeScript + vitest + RTL (frontend).

## Global Constraints

- **BEHAVIOR FREEZE (this is a REFACTOR batch).** NO external HTTP / WS / IPC change — identical status codes, identical JSON bodies, identical WS payloads (compared **deep-equal**, `exclude_unset`/`exclude_none`), identical Chinese user-facing strings (copied verbatim). The ONLY thing that changes is internal structure.
- **Characterization-test-FIRST (HARD rule).** Every task writes a test that pins the CURRENT behavior BEFORE the carve, using REAL collaborators — NEVER a stub that hard-codes the answer (a prior batch shipped a danger-zone test that stubbed the very method under test and hid a deadlock). Assert ordered exact tuples / exact values. The test PASSES on the un-refactored code, then STILL PASSES byte-for-byte after the carve. (Exception: a brand-new extracted PURE helper gets a unit test that fails-then-passes — the task says which mode applies.)
- **Baselines:** backend `pytest --collect-only -q` => **941 collected**; `lint-imports` => **7 kept, 0 broken**; frontend `tsc --noEmit` => 0 errors, `vitest run` => **707 passed / 91 files**, `depcruise src` => 0 errors. Each task only grows the test count.
- **Full green after every commit**, and the carve introduces **NO new cross-ring edge** (lint-imports + depcruise stay green). Key rule: `services/` may NOT import `fastapi` (whitelist: `cloud_sync_service` only) — so a lifted service raises a DOMAIN error and the controller maps it to `HTTPException` at the boundary. `domain/` imports stdlib+pydantic only.
- **INCREMENTAL.** Carve ONE seam per task; never rewrite a whole god-file in one commit. The `api/device.py` (A1) and `_move_along_route` (A2) carves are split across several tasks.
- **Thick carve-outs stay leaky.** Do NOT abstract `pymobiledevice3` / `usbmuxd` / tunnel-helper / SIP guts into pure cores — wrap behind narrow seams only; keep them injected.
- **Do NOT unify the `main.py` usbmux watchdog (587-672) with the lifted `cleanup_device_lost`** — they emit DIFFERENT observable WS payloads (`device_disconnected reason:"usb_unplugged"` via `broadcast` vs `device_lost`). The watchdog stays as-is this batch.
- **Line numbers in tasks are audit/draft-time anchors** (SH1+SH2 already edited many files) — locate code by CONTENT.
- **Personal repo:** direct commits; identity auto-set by `~/.gitconfig` — never pass `-c user.email=...`.

---


<!-- ===== S1 · Recovery orchestration + engine math carve ===== -->

### Task 1: Extract waypoint seg-index precompute into pure `match_waypoints_to_coords`

**Files:**
- Modify: `backend/domain/movement.py` (append a new module-level pure function after `build_resume_snapshot`)
- Modify: `backend/core/simulation_engine.py` (the `wp_seg_idx` precompute block inside `_move_along_route`, currently the `for wi in range(self._user_waypoint_next, len(user_wps)):` loop at simulation_engine.py:675-693)
- Test: `backend/tests/test_match_waypoints_to_coords.py` (new) + the existing `backend/tests/test_interpolator_golden.py` must stay green

**Interfaces:**
- Consumes: none
- Produces: `domain/movement.py::match_waypoints_to_coords(user_wps: list[Coordinate], planned_coords: list[Coordinate], start_index: int) -> list[int]`

- [ ] **Step 1: Write the unit test (NEW pure helper — FAIL-then-PASS mode).** The helper does not exist yet, so this test FAILS on import until Step 3 extracts it. It pins the exact monotonic forward-scan + early-break semantics currently inline in `_move_along_route`.

```python
"""Pin the pure waypoint->coord-index match extracted from
SimulationEngine._move_along_route (the wp_seg_idx precompute). Monotonic
forward scan with early break when a waypoint can't be matched further
along than the previous one (the multi_stop later-leg cutoff)."""
from models.schemas import Coordinate
from domain.movement import match_waypoints_to_coords


def _c(lat, lng):
    return Coordinate(lat=lat, lng=lng)


def test_each_waypoint_maps_to_nearest_forward_coord():
    # planned coords are a straight east-west line; waypoints sit ON coords 1 and 3.
    planned = [_c(25.0, 121.000), _c(25.0, 121.001), _c(25.0, 121.002),
               _c(25.0, 121.003), _c(25.0, 121.004)]
    user_wps = [_c(25.0, 121.001), _c(25.0, 121.003)]
    assert match_waypoints_to_coords(user_wps, planned, start_index=0) == [1, 3]


def test_start_index_skips_already_consumed_waypoints():
    planned = [_c(25.0, 121.000), _c(25.0, 121.001), _c(25.0, 121.002)]
    user_wps = [_c(25.0, 121.000), _c(25.0, 121.002)]
    # start at index 1 -> only the second waypoint is scanned, from coord 0.
    assert match_waypoints_to_coords(user_wps, planned, start_index=1) == [2]


def test_second_waypoint_scans_strictly_after_the_first():
    # wp0 best-matches coord 2; wp1 then scans from coord 3 onward (last_ci+1),
    # so even though coord 3 is the only remaining candidate it is chosen there.
    planned = [_c(25.0, 121.000), _c(25.0, 121.001), _c(25.0, 121.002),
               _c(25.0, 121.010)]
    user_wps = [_c(25.0, 121.002), _c(25.0, 121.0105)]
    assert match_waypoints_to_coords(user_wps, planned, start_index=0) == [2, 3]


def test_empty_waypoints_returns_empty():
    planned = [_c(25.0, 121.0), _c(25.0, 121.001)]
    assert match_waypoints_to_coords([], planned, start_index=0) == []


def test_break_when_no_coords_remain_to_scan():
    # first wp -> coord 0; second wp scans from coord 1 (range empty) ->
    # best_ci stays -1 -> break, so only [0] is returned.
    planned = [_c(25.0, 121.0)]
    user_wps = [_c(25.0, 121.0), _c(25.0, 121.5)]
    assert match_waypoints_to_coords(user_wps, planned, start_index=0) == [0]
```

- [ ] **Step 2: Run it, verify it FAILS (helper missing).** `cd backend && .venv/bin/python -m pytest tests/test_match_waypoints_to_coords.py -v` — expect `ImportError: cannot import name 'match_waypoints_to_coords'` (collection error) BEFORE the extraction. NEW-pure-helper FAIL-then-PASS mode applies.

- [ ] **Step 3: Refactor (behavior-preserving).** First add the pure function to `domain/movement.py`, lifting the EXACT inline logic verbatim. Current inline code in `_move_along_route` (simulation_engine.py:675-694):

```python
            wp_seg_idx: list[int] = []
            last_ci = -1
            for wi in range(self._user_waypoint_next, len(user_wps)):
                wp = user_wps[wi]
                start_ci = max(last_ci + 1, 0)
                best_ci = -1
                best_d = float("inf")
                for ci in range(start_ci, len(planned_coords)):
                    d = RouteInterpolator.haversine(
                        wp.lat, wp.lng,
                        planned_coords[ci].lat, planned_coords[ci].lng,
                    )
                    if d < best_d:
                        best_d = d
                        best_ci = ci
                if best_ci < 0:
                    break
                wp_seg_idx.append(best_ci)
                last_ci = best_ci
            wp_hit_ptr = 0
```

New function appended to `domain/movement.py` (after `build_resume_snapshot`). It references `RouteInterpolator.haversine`, a module global resolved at CALL time, so placement relative to `class RouteInterpolator` is irrelevant:

```python
def match_waypoints_to_coords(
    user_wps: list[Coordinate],
    planned_coords: list[Coordinate],
    start_index: int,
) -> list[int]:
    """For each user waypoint at index >= start_index, find the nearest
    planned_coord index via a MONOTONIC forward scan (each waypoint's match
    must lie strictly after the previous waypoint's match). Stops as soon as
    a waypoint can't be matched further along than the previous one, meaning
    it belongs to a later leg (multi_stop) or isn't on planned_coords.

    Pure extraction of the wp_seg_idx precompute from
    SimulationEngine._move_along_route. Behavior is byte-identical.
    """
    wp_seg_idx: list[int] = []
    last_ci = -1
    for wi in range(start_index, len(user_wps)):
        wp = user_wps[wi]
        start_ci = max(last_ci + 1, 0)
        best_ci = -1
        best_d = float("inf")
        for ci in range(start_ci, len(planned_coords)):
            d = RouteInterpolator.haversine(
                wp.lat, wp.lng,
                planned_coords[ci].lat, planned_coords[ci].lng,
            )
            if d < best_d:
                best_d = d
                best_ci = ci
        if best_ci < 0:
            break
        wp_seg_idx.append(best_ci)
        last_ci = best_ci
    return wp_seg_idx
```

Then replace the inline block in `core/simulation_engine.py` with the call. KEEP the `wp_hit_ptr = 0` init inline (it is loop-pointer state, not part of the pure compute):

```python
            wp_seg_idx = match_waypoints_to_coords(
                user_wps, planned_coords, self._user_waypoint_next,
            )
            wp_hit_ptr = 0
```

Extend the existing import at the top of `core/simulation_engine.py` (currently `from domain.movement import EtaTracker, build_resume_snapshot, RouteInterpolator`):

```python
from domain.movement import (
    EtaTracker, build_resume_snapshot, RouteInterpolator, match_waypoints_to_coords,
)
```

- [ ] **Step 4: Run the new test + the engine golden + broader suite.** `cd backend && .venv/bin/python -m pytest tests/test_match_waypoints_to_coords.py tests/test_interpolator_golden.py -v` — the new test now PASSES and `test_move_along_route_position_stream_matches_frozen_golden` stays green (the position stream + waypoint_progress emission is unchanged). Then `cd backend && .venv/bin/python -m pytest -q` — expect `941 passed` (no collected-count drop; the new file adds 5 tests, but the baseline assertion is on the PRE-existing suite — after this task the full count rises to 946).

- [ ] **Step 5: Gate.** `cd backend && .venv/bin/lint-imports` — expect `7 kept, 0 broken` (the helper lives in `domain/`, imports stdlib + `models.schemas` only; no new cross-ring edge).

- [ ] **Step 6: Commit.** `git add backend/domain/movement.py backend/core/simulation_engine.py backend/tests/test_match_waypoints_to_coords.py` + message: `refactor(sh3): carve match_waypoints_to_coords pure helper out of _move_along_route`


---

### Task 2: Extract the 3-attempt position push-retry into `SimulationEngine._push_with_retry`

**Files:**
- Modify: `backend/core/simulation_engine.py` (the `pushed = False; for attempt in range(3): ...` block inside `_move_along_route` at simulation_engine.py:739-757, plus a new private method on the class)
- Test: `backend/tests/test_push_with_retry_char.py` (new) + the existing `backend/tests/test_interpolator_golden.py` must stay green

**Interfaces:**
- Consumes: none (independent of Task 1)
- Produces: `core/simulation_engine.py::SimulationEngine._push_with_retry(self, lat: float, lng: float) -> bool`

- [ ] **Step 1: Write the CHARACTERIZATION test** (REAL engine, no answer-hardcoding stub). It pins the EXACT retry ladder: 3 attempts, backoff via the injected `self._sleep` with durations `0.5, 1.0` between the 3 tries (and `1.5` after the 3rd failure), `CancelledError` re-raised, a generic `Exception` breaking out (False, no further retries), and a first-attempt success returning True with `current_position` updated. The engine is built directly (no `device_port`), so the test-only `_DefaultDevicePort` delegates `set_location -> location_service.set`; the `_ScriptedLoc.set` raises on a scripted schedule.

```python
"""Characterize the 3-attempt position push-retry loop currently inline in
SimulationEngine._move_along_route, before it is carved into _push_with_retry.
Drives a REAL SimulationEngine; the device push is a fake LocationService
whose .set raises on a scripted schedule (the engine's _DefaultDevicePort
fallback delegates set_location -> location_service.set).
"""
import asyncio

import pytest

from tests._engine_harness import FakeClock, SteppedSleep

pytestmark = pytest.mark.asyncio


class _ScriptedLoc:
    """location_service double: .set raises the next scripted exception (or
    succeeds when the schedule is exhausted), recording every (lat,lng) it
    accepts. None in the schedule = succeed this call."""
    def __init__(self, schedule):
        self._schedule = list(schedule)
        self.pushes = []

    async def set(self, lat, lng):
        if self._schedule:
            exc = self._schedule.pop(0)
            if exc is not None:
                raise exc
        self.pushes.append((lat, lng))

    async def clear(self):
        pass


def _make_with_loc(loc, clock, sleep):
    from core.simulation_engine import SimulationEngine
    return SimulationEngine(loc, None, clock=clock, sleep=sleep)


async def test_push_succeeds_first_attempt_no_backoff_sleep():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([None])  # first .set succeeds
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is True
    assert loc.pushes == [(25.0, 121.0)]
    assert sleep.durations == []  # no backoff on first-attempt success
    assert (eng.current_position.lat, eng.current_position.lng) == (25.0, 121.0)


async def test_push_retries_with_increasing_backoff_then_succeeds():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    # attempt 1 -> ConnectionError (sleep 0.5), attempt 2 -> OSError (sleep 1.0),
    # attempt 3 -> success.
    loc = _ScriptedLoc([ConnectionError("boom"), OSError("boom2"), None])
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is True
    assert loc.pushes == [(25.0, 121.0)]
    assert sleep.durations == [0.5, 1.0]  # 0.5*(0+1), 0.5*(1+1)


async def test_push_exhausts_three_attempts_returns_false():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([ConnectionError("1"), ConnectionError("2"), ConnectionError("3")])
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is False
    assert loc.pushes == []
    # backoff runs after each failure INCLUDING the last, matching the
    # current inline loop: 0.5, 1.0, 1.5.
    assert sleep.durations == [0.5, 1.0, 1.5]


async def test_generic_exception_breaks_immediately_returns_false():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([ValueError("unexpected")])
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is False
    assert sleep.durations == []  # generic Exception path does NOT backoff-sleep


async def test_cancelled_error_propagates():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([asyncio.CancelledError()])
    eng = _make_with_loc(loc, clock, sleep)
    with pytest.raises(asyncio.CancelledError):
        await eng._push_with_retry(25.0, 121.0)
```

- [ ] **Step 2: Run it, verify it FAILS first (method missing).** `cd backend && .venv/bin/python -m pytest tests/test_push_with_retry_char.py -v` → expect `AttributeError: 'SimulationEngine' object has no attribute '_push_with_retry'`. The behavior it characterizes IS the current inline loop; after Step 3 the same assertions pass. (Mode: new-method extraction — the test pins the EXACT current inline behavior, which only becomes invokable once extracted.)

- [ ] **Step 3: Refactor (behavior-preserving).** Current inline block in `_move_along_route` (simulation_engine.py:739-757):

```python
                pushed = False
                for attempt in range(3):
                    try:
                        await self._set_position(jittered_lat, jittered_lng)
                        pushed = True
                        break
                    except (ConnectionError, OSError) as exc:
                        logger.warning(
                            "position push failed (attempt %d/3): %s", attempt + 1, exc,
                        )
                        await self._sleep(0.5 * (attempt + 1))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Unexpected error pushing position")
                        break
                if not pushed:
                    logger.error("Giving up on this route after repeated push failures")
                    break
```

Add a new private method on `SimulationEngine` (place it next to `_set_position`):

```python
    async def _push_with_retry(self, lat: float, lng: float) -> bool:
        """Push one coordinate to the device with up to 3 attempts.

        Transient (ConnectionError, OSError) -> warn + backoff-sleep
        0.5*(attempt+1)s and retry. CancelledError propagates. Any other
        Exception logs and gives up immediately. Returns True iff the push
        landed. Carved verbatim from the inline loop in _move_along_route.
        """
        for attempt in range(3):
            try:
                await self._set_position(lat, lng)
                return True
            except (ConnectionError, OSError) as exc:
                logger.warning(
                    "position push failed (attempt %d/3): %s", attempt + 1, exc,
                )
                await self._sleep(0.5 * (attempt + 1))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error pushing position")
                return False
        return False
```

Replace the inline block in `_move_along_route` with:

```python
                if not await self._push_with_retry(jittered_lat, jittered_lng):
                    logger.error("Giving up on this route after repeated push failures")
                    break
```

NOTE: the original loop sleeps AFTER the 3rd failed attempt too (the `await self._sleep(0.5*(attempt+1))` runs inside the `except` even on the last iteration before the loop ends) — the extracted method preserves this (`[0.5, 1.0, 1.5]` on full exhaustion), which is why the char test asserts that exact triple.

- [ ] **Step 4: Run the char test + the engine golden + broader suite.** `cd backend && .venv/bin/python -m pytest tests/test_push_with_retry_char.py tests/test_interpolator_golden.py -v` — char test PASSES; `test_move_along_route_position_stream_matches_frozen_golden` stays green (its loc never raises, so each tick hits attempt-1 success and the injected SteppedSleep is never invoked — the position stream is unchanged). Then `cd backend && .venv/bin/python -m pytest -q` — full suite green (no drop; counts rise by the new file's tests).

- [ ] **Step 5: Gate.** `cd backend && .venv/bin/lint-imports` — expect `7 kept, 0 broken` (intra-`core` change, no new edge).

- [ ] **Step 6: Commit.** `git add backend/core/simulation_engine.py backend/tests/test_push_with_retry_char.py` + message: `refactor(sh3): carve _push_with_retry out of _move_along_route`


---

### Task 3: Lift `_engine` resolve/rebuild into `services/engine_resolver.py::EngineResolver.resolve_engine`

**Files:**
- Create: `backend/services/engine_resolver.py`
- Modify: `backend/domain/errors.py` (add `EngineUnavailableError`)
- Modify: `backend/api/location.py` (`_engine` becomes a thin shim delegating to the service)
- Test: `backend/tests/test_engine_resolver_char.py` (new) + existing `backend/tests/test_location_di_char.py` must stay green

**Interfaces:**
- Consumes: none
- Produces:
  - `domain/errors.py::EngineUnavailableError(code: str, message: str)` (carries `.code`, `.message`; controller maps to `HTTPException(400, {"code": code, "message": message})`)
  - `services/engine_resolver.py::EngineResolver(engine_registry, device_manager)` with `async resolve_engine(self, udid: str | None = None)`

- [ ] **Step 1: Write the CHARACTERIZATION test** (REAL `EngineResolver`, no answer-hardcoding stub — uses a real registry double and asserts exact return identity + exact error code/message strings). Pins the four observable resolve outcomes: direct-hit by udid, primary-when-udid-None, rebuild-attempt-1 success, and the no-device 400 (domain error carrying the verbatim Chinese message). NOTE both no-device error paths in the current `_engine` raise code `"no_device"`; only the message differs.

```python
"""Characterize EngineResolver.resolve_engine — the resolve/rebuild ladder
lifted verbatim from api/location.py::_engine. REAL resolver over a fake
registry/device_manager; asserts exact engine identity + exact domain-error
code/message. The 10x discover loop is NOT exercised with real sleeps; the
no_device test monkeypatches asyncio.sleep + discover_devices so it returns
instantly.
"""
import pytest

from domain.errors import EngineUnavailableError
from services.engine_resolver import EngineResolver

pytestmark = pytest.mark.asyncio


class _FakeDM:
    def __init__(self, connections):
        self._connections = connections


class _FakeRegistry:
    """Minimal stand-in for AppState's resolve surface."""
    def __init__(self, engines, primary, connections):
        self.simulation_engines = engines
        self._primary_udid = primary
        self.device_manager = _FakeDM(connections)
        self._created = []

    @property
    def simulation_engine(self):
        if self._primary_udid and self._primary_udid in self.simulation_engines:
            return self.simulation_engines[self._primary_udid]
        return None

    def get_engine(self, udid):
        if udid is None:
            return self.simulation_engine
        return self.simulation_engines.get(udid)

    async def create_engine_for_device(self, udid, force=False):
        self._created.append(udid)
        # Simulate a successful rebuild: register a sentinel engine.
        self.simulation_engines[udid] = object()
        if self._primary_udid is None:
            self._primary_udid = udid


async def test_direct_hit_returns_engine_for_udid():
    eng = object()
    reg = _FakeRegistry({"U1": eng}, "U1", {"U1": object()})
    resolver = EngineResolver(reg, reg.device_manager)
    assert await resolver.resolve_engine("U1") is eng


async def test_udid_none_returns_primary_engine():
    eng = object()
    reg = _FakeRegistry({"U1": eng}, "U1", {"U1": object()})
    resolver = EngineResolver(reg, reg.device_manager)
    assert await resolver.resolve_engine(None) is eng


async def test_rebuild_attempt1_when_engine_missing_but_connection_present():
    # No engine registered yet, but a connection exists -> attempt-1 rebuild.
    reg = _FakeRegistry({}, None, {"U1": object()})
    resolver = EngineResolver(reg, reg.device_manager)
    out = await resolver.resolve_engine("U1")
    assert reg._created == ["U1"]
    assert out is reg.simulation_engines["U1"]


async def test_no_device_raises_engine_unavailable_with_verbatim_message():
    reg = _FakeRegistry({}, None, {})  # no connections, no engines
    resolver = EngineResolver(reg, reg.device_manager)

    async def _no_discover():
        return []
    reg.device_manager.discover_devices = _no_discover

    import asyncio as _a
    orig_sleep = _a.sleep
    async def _instant(_s):
        return None
    _a.sleep = _instant
    try:
        with pytest.raises(EngineUnavailableError) as ei:
            await resolver.resolve_engine(None)
    finally:
        _a.sleep = orig_sleep
    assert ei.value.code == "no_device"
    assert ei.value.message == "尚未連接任何 iOS 裝置,請先透過 USB 連線"
```

- [ ] **Step 2: Run it, verify it FAILS first (new module).** `cd backend && .venv/bin/python -m pytest tests/test_engine_resolver_char.py -v` → BEFORE Step 3: `ModuleNotFoundError: No module named 'services.engine_resolver'`. AFTER Step 3 the assertions (which mirror the current `_engine` behavior verbatim) PASS. Mode: new-module extraction pinning current `_engine` behavior.

- [ ] **Step 3: Refactor (behavior-preserving).** First add to `backend/domain/errors.py` (stdlib only — keeps `no-domain-imports-outer` green):

```python
class EngineUnavailableError(Exception):
    """Raised by EngineResolver when no usable SimulationEngine can be
    resolved or rebuilt. The api boundary maps this to
    HTTPException(400, {"code": code, "message": message}).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

Create `backend/services/engine_resolver.py`, lifting the `_engine` body verbatim (services may import services + domain; NEVER fastapi). No return-type annotation referencing `SimulationEngine` (avoids a needless services->core import; the resolver just returns the registry's engine object):

```python
"""EngineResolver — resolve/rebuild the active SimulationEngine.

Lifted from api/location.py::_engine so the controller becomes a thin
boundary (it maps EngineUnavailableError -> HTTPException(400)). Behavior is
byte-identical: the same direct-hit -> primary -> discover -> attempt-1
rebuild -> attempt-2 hard-reset ladder, with the same two verbatim 400
messages (both carrying code "no_device").
"""
from __future__ import annotations

import asyncio
import logging

from domain.errors import EngineUnavailableError

_log = logging.getLogger("locwarp")


class EngineResolver:
    def __init__(self, engine_registry, device_manager) -> None:
        self._reg = engine_registry
        self._dm = device_manager

    async def resolve_engine(self, udid: str | None = None):
        app_state = self._reg
        # Direct hit on the requested udid.
        if udid is not None:
            eng = app_state.get_engine(udid)
            if eng is not None:
                return eng
        if udid is None and app_state.simulation_engine is not None:
            return app_state.simulation_engine

        dm = self._dm
        target_udid = udid or next(iter(dm._connections.keys()), None)
        if target_udid is None:
            for attempt in range(10):
                try:
                    discovered = await dm.discover_devices()
                    if discovered:
                        target_udid = discovered[0].udid
                        if attempt > 0:
                            _log.info("discover_devices returned device on attempt %d", attempt + 1)
                        break
                except Exception:
                    _log.exception("discover_devices failed during lazy rebuild (attempt %d)", attempt + 1)
                await asyncio.sleep(1.0)

        if target_udid is None:
            raise EngineUnavailableError(
                "no_device", "尚未連接任何 iOS 裝置,請先透過 USB 連線",
            )

        # Attempt 1: rebuild engine on top of existing connection
        _log.info("simulation_engine missing; attempt 1 (rebuild) for %s", target_udid)
        try:
            await app_state.create_engine_for_device(target_udid)
            rebuilt = app_state.get_engine(target_udid) if udid is not None else app_state.simulation_engine
            if rebuilt is not None:
                _log.info("Engine rebuild succeeded on attempt 1")
                return rebuilt
        except Exception:
            _log.exception("Engine rebuild (attempt 1) failed for %s", target_udid)

        # Attempt 2: hard reset — disconnect + reconnect + rebuild
        _log.info("attempt 2 (hard reset) for %s", target_udid)
        try:
            try:
                await dm.disconnect(target_udid)
            except Exception:
                _log.warning("disconnect during hard reset failed; proceeding", exc_info=True)
            await dm.connect(target_udid)
            await app_state.create_engine_for_device(target_udid)
            rebuilt = app_state.get_engine(target_udid) if udid is not None else app_state.simulation_engine
            if rebuilt is not None:
                _log.info("Engine rebuild succeeded on attempt 2")
                return rebuilt
        except Exception:
            _log.exception("Engine rebuild (attempt 2, hard reset) failed for %s", target_udid)

        raise EngineUnavailableError(
            "no_device",
            "裝置連線已失效,請嘗試重新插拔 USB 或重新啟動 LocWarp(詳見 ~/.locwarp/logs/backend.log)",
        )
```

Now make `api/location.py::_engine` a thin shim that delegates + re-maps the domain error to the EXACT same `HTTPException`s it raised before. Replace the entire current `_engine` body (location.py:31-107) with:

```python
async def _engine(udid: str | None = None, registry=None):
    """Resolve the active SimulationEngine via EngineResolver, mapping the
    domain EngineUnavailableError to the frozen 400 HTTPException."""
    from services.engine_resolver import EngineResolver
    from domain.errors import EngineUnavailableError
    app_state = _engine_registry_or_main(registry)
    resolver = EngineResolver(app_state, app_state.device_manager)
    try:
        return await resolver.resolve_engine(udid)
    except EngineUnavailableError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": e.code, "message": e.message},
        )
```

- [ ] **Step 4: Run the char test + the location char suite + broader suite.** `cd backend && .venv/bin/python -m pytest tests/test_engine_resolver_char.py tests/test_location_di_char.py -v` — both PASS (`test_get_status_stitches_cooldown_remaining` patches `api.location._engine` directly with a fake_resolver, so the shim is irrelevant to it; the no-device 400 detail shape is unchanged). Then `cd backend && .venv/bin/python -m pytest -q` — full suite green.

- [ ] **Step 5: Gate.** `cd backend && .venv/bin/lint-imports` — expect `7 kept, 0 broken`. Verify `services/engine_resolver.py` imports NO fastapi (it raises `EngineUnavailableError`, never `HTTPException`) so `no-services-imports-fastapi` stays green, and `domain/errors.py` stays stdlib-only for `no-domain-imports-outer`.

- [ ] **Step 6: Commit.** `git add backend/services/engine_resolver.py backend/domain/errors.py backend/api/location.py backend/tests/test_engine_resolver_char.py` + message: `refactor(sh3): lift _engine resolve/rebuild into EngineResolver, controller maps domain error to 400`


---

### Task 4: Lift `_try_with_recovery_retry` + `_handle_device_lost` cleanup into `EngineResolver`

**Files:**
- Modify: `backend/services/engine_resolver.py` (add `with_recovery` + `cleanup_device_lost` + the device-lost reason->message table)
- Modify: `backend/api/location.py` (`_try_with_recovery_retry` and `_handle_device_lost` become thin shims; `_device_lost_message` + `_DEVICE_LOST_REASON_MESSAGES` move into the service)
- Test: `backend/tests/test_engine_resolver_recovery_char.py` (new) + existing `backend/tests/test_location_device_lost_publisher.py` must stay green

**Interfaces:**
- Consumes: `services/engine_resolver.py::EngineResolver(engine_registry, device_manager)` (from the prior A4 task)
- Produces:
  - `services/engine_resolver.py::EngineResolver.with_recovery(self, udid: str | None, op)`
  - `services/engine_resolver.py::EngineResolver.cleanup_device_lost(self, exc: Exception, udid: str) -> tuple[str, str]` (returns `(reason, message)`; the controller builds the 503 HTTPException)

- [ ] **Step 1: Write the CHARACTERIZATION test** (REAL `EngineResolver` over a fake registry/dm + a `_CapPublisher`, mirroring `test_location_device_lost_publisher.py`'s real-collaborator style — no answer-hardcoding). Pins: (a) `with_recovery` retries `op` once after a successful `full_reconnect`; (b) `with_recovery` re-raises when `full_reconnect` returns False; (c) `cleanup_device_lost` disconnects ONLY the named udid, publishes the exact `device_disconnected` tuple, and returns the verbatim `(reason, message)`. `DeviceLostError(*args, reason=...)` accepts a positional message + keyword reason (verified).

```python
"""Characterize EngineResolver.with_recovery + cleanup_device_lost, lifted
from api/location.py::_try_with_recovery_retry / _handle_device_lost. REAL
resolver over fakes; asserts exact retry count, exact published tuple, exact
(reason, message). Mirrors test_location_device_lost_publisher.py.
"""
from unittest.mock import AsyncMock

import pytest

from services.engine_resolver import EngineResolver
from services.location_service import DeviceLostError

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.captured = []
    async def publish(self, event):
        etype, data = event
        self.captured.append((etype, {**data}))


class _FakeDM:
    def __init__(self, connections, publisher):
        self._connections = connections
        self._events = publisher
        self.full_reconnect = AsyncMock(return_value=True)
        self._disconnected = []
    async def disconnect(self, u):
        self._disconnected.append(u)
        self._connections.pop(u, None)


class _FakeRegistry:
    def __init__(self, dm, engines):
        self.device_manager = dm
        self.simulation_engines = engines
        self.remove_engine = AsyncMock(return_value=None)


async def test_with_recovery_retries_op_once_after_full_reconnect():
    pub = _CapPublisher()
    dm = _FakeDM({"U1": object()}, pub)
    reg = _FakeRegistry(dm, {})
    resolver = EngineResolver(reg, dm)
    calls = []
    async def op():
        calls.append(1)
        if len(calls) == 1:
            raise DeviceLostError("gone", reason=DeviceLostError.REASON_USB_GONE)
        return "ok"
    out = await resolver.with_recovery("U1", op)
    assert out == "ok"
    assert len(calls) == 2  # original + one retry
    dm.full_reconnect.assert_awaited_once_with("U1")


async def test_with_recovery_reraises_when_full_reconnect_fails():
    pub = _CapPublisher()
    dm = _FakeDM({"U1": object()}, pub)
    dm.full_reconnect = AsyncMock(return_value=False)
    reg = _FakeRegistry(dm, {})
    resolver = EngineResolver(reg, dm)
    async def op():
        raise DeviceLostError("gone")
    with pytest.raises(DeviceLostError):
        await resolver.with_recovery("U1", op)


async def test_cleanup_device_lost_only_named_udid_and_exact_publish():
    pub = _CapPublisher()
    dm = _FakeDM({"U1": object(), "U2": object()}, pub)
    reg = _FakeRegistry(dm, {})
    resolver = EngineResolver(reg, dm)
    exc = DeviceLostError("device gone", reason=DeviceLostError.REASON_TUNNEL_DEAD)
    reason, message = await resolver.cleanup_device_lost(exc, "U1")
    assert reason == DeviceLostError.REASON_TUNNEL_DEAD
    assert message == "WiFi 連線中斷,請確認手機 WiFi 與電腦同網段、解鎖手機後再試"
    assert dm._disconnected == ["U1"]
    assert "U2" in dm._connections  # survivor untouched
    assert len(pub.captured) == 1
    etype, data = pub.captured[0]
    assert etype == "device_disconnected"
    assert data["udids"] == ["U1"]
    assert data["reason"] == "device_lost"
    assert data["error"] == "device gone"
    assert data["remaining_count"] == 1
```

- [ ] **Step 2: Run it, verify it FAILS first (new methods).** `cd backend && .venv/bin/python -m pytest tests/test_engine_resolver_recovery_char.py -v` → BEFORE Step 3: `AttributeError: 'EngineResolver' object has no attribute 'with_recovery'`. AFTER Step 3 it PASSES (the lifted logic is byte-identical to the current controller closures). Mode: new-method extraction pinning current `_try_with_recovery_retry` / `_handle_device_lost` behavior.

- [ ] **Step 3: Refactor (behavior-preserving).** Add to `services/engine_resolver.py` (move the reason->message table + `_device_lost_message` out of `api/location.py:110-144` verbatim):

```python
from services.location_service import DeviceLostError

_DEVICE_LOST_REASON_MESSAGES: dict[str, str] = {
    DeviceLostError.REASON_TUNNEL_DEAD: "WiFi 連線中斷,請確認手機 WiFi 與電腦同網段、解鎖手機後再試",
    DeviceLostError.REASON_LOCKDOWN_DEAD: "裝置回應停止,請解鎖手機螢幕後再試",
    DeviceLostError.REASON_DDI_MISSING: "Developer Disk Image 未掛載,請重新插拔 USB 或重新啟動裝置",
    DeviceLostError.REASON_USB_GONE: "USB 已拔除,請重新插上後再操作",
    DeviceLostError.REASON_UNKNOWN: "裝置連線中斷(USB 拔除或 Tunnel 死亡),請重新插上 USB 後再操作",
}


def _device_lost_message(exc: Exception) -> tuple[str, str]:
    cause: Exception | None = exc
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, DeviceLostError):
            reason = getattr(cause, "reason", DeviceLostError.REASON_UNKNOWN) or DeviceLostError.REASON_UNKNOWN
            return reason, _DEVICE_LOST_REASON_MESSAGES.get(
                reason, _DEVICE_LOST_REASON_MESSAGES[DeviceLostError.REASON_UNKNOWN],
            )
        cause = cause.__cause__
    return (DeviceLostError.REASON_UNKNOWN, _DEVICE_LOST_REASON_MESSAGES[DeviceLostError.REASON_UNKNOWN])
```

Add two methods on `EngineResolver` (lifted verbatim from the controller closures, minus the HTTPException construction):

```python
    async def with_recovery(self, udid: str | None, op):
        try:
            return await op()
        except DeviceLostError:
            if not udid:
                raise
            _log.warning("DeviceLostError on %s; attempting full_reconnect safety-net retry", udid)
            try:
                recovered = await self._dm.full_reconnect(udid)
            except Exception:
                _log.exception("full_reconnect raised during safety-net retry")
                recovered = False
            if not recovered:
                _log.warning("full_reconnect failed for %s; surfacing original error", udid)
                raise
            _log.info("full_reconnect succeeded for %s; retrying op once", udid)
            return await op()

    async def cleanup_device_lost(self, exc: Exception, udid: str) -> tuple[str, str]:
        app_state = self._reg
        dm = self._dm
        lost_udids = [udid] if udid in dm._connections else []
        if not lost_udids:
            _log.info("device_lost: udid %s no longer in _connections; nothing to clean", udid)
        for u in lost_udids:
            old_eng = app_state.simulation_engines.get(u)
            if old_eng is not None:
                try:
                    old_eng._stop_event.set()
                    old_eng._pause_event.set()
                    active = getattr(old_eng, "_active_task", None)
                    if active is not None and not active.done():
                        active.cancel()
                except Exception:
                    _log.debug("device_lost: failed to stop old engine %s", u, exc_info=True)
            try:
                await dm.disconnect(u)
                _log.info("device_lost cleanup: disconnected %s", u)
            except Exception:
                _log.exception("device_lost cleanup: disconnect failed for %s", u)
            await app_state.remove_engine(u)
        try:
            await dm._events.publish(("device_disconnected", {
                "udids": lost_udids,
                "reason": "device_lost",
                "error": str(exc),
                "remaining_count": len(dm._connections),
            }))
        except Exception:
            _log.exception("Failed to broadcast device_disconnected")
        return _device_lost_message(exc)
```

Now rewrite the `api/location.py` shims. Replace the bodies of `_try_with_recovery_retry` (location.py:147-178) and `_handle_device_lost` (location.py:181-241), keeping their signatures + docstrings so existing patches/tests/callers are byte-identical (`test_handle_device_lost_requires_udid` asserts the `udid` param has NO default; `test_location_module_has_no_websocket_import` still holds since the publish moved to the service):

```python
async def _try_with_recovery_retry(udid: str | None, op, registry=None):
    from services.engine_resolver import EngineResolver
    app_state = _engine_registry_or_main(registry)
    resolver = EngineResolver(app_state, app_state.device_manager)
    return await resolver.with_recovery(udid, op)


async def _handle_device_lost(exc: Exception, udid: str, registry=None) -> "HTTPException":
    from services.engine_resolver import EngineResolver
    app_state = _engine_registry_or_main(registry)
    resolver = EngineResolver(app_state, app_state.device_manager)
    reason, message = await resolver.cleanup_device_lost(exc, udid)
    return HTTPException(
        status_code=503,
        detail={"code": "device_lost", "reason": reason, "message": message},
    )
```

DELETE the now-orphaned `_DEVICE_LOST_REASON_MESSAGES` dict and `_device_lost_message` function from `api/location.py` (location.py:110-144 — they live in the service now). KEEP `from services.location_service import DeviceLostError` in `api/location.py` (the endpoints still `except DeviceLostError`).

- [ ] **Step 4: Run the char test + the device-lost publisher suite + broader suite.** `cd backend && .venv/bin/python -m pytest tests/test_engine_resolver_recovery_char.py tests/test_location_device_lost_publisher.py -v` — all PASS. `test_handle_device_lost_emits_via_injected_publisher` still sees the exact `device_disconnected` tuple (now emitted from the service via the same `dm._events.publish`) and still gets a `HTTPException(503)` back; `test_handle_device_lost_only_touches_named_udid` still passes (cleanup scoped to one udid); `test_handle_device_lost_requires_udid` still passes (signature unchanged, `udid` has no default). Then `cd backend && .venv/bin/python -m pytest -q` — full suite green.

- [ ] **Step 5: Gate.** `cd backend && .venv/bin/lint-imports` — expect `7 kept, 0 broken`. `services/engine_resolver.py` imports `services.location_service` + `domain.errors` only (no fastapi; verified location_service has zero fastapi imports, so no transitive edge); `api/location.py` still has zero `from api.websocket import broadcast` (the publish path is `dm._events.publish` inside the service).

- [ ] **Step 6: Commit.** `git add backend/services/engine_resolver.py backend/api/location.py backend/tests/test_engine_resolver_recovery_char.py` + message: `refactor(sh3): lift with_recovery + cleanup_device_lost into EngineResolver`


---

### Task 5: Route the recovery-using endpoints through EngineResolver + document the watchdog non-reuse

**Files:**
- Modify: `backend/api/location.py` (add a module comment above the `_engine` shim documenting the deliberate watchdog non-reuse; confirm `teleport`, `restore`, `goldditto_cycle` still delegate through the shimmed `_engine` / `_try_with_recovery_retry` / `_handle_device_lost`)
- Test: `backend/tests/test_location_recovery_boundary_char.py` (new) + existing `backend/tests/test_location_di_char.py` must stay green

**Interfaces:**
- Consumes: `EngineResolver.resolve_engine` / `with_recovery` / `cleanup_device_lost` (via the `_engine` / `_try_with_recovery_retry` / `_handle_device_lost` shims from the prior two A4 tasks)
- Produces: none

SEAM-CLOSING step: after the prior tasks the controller closures already delegate to the service. Here we (1) pin that the `teleport` recovery path still produces the EXACT 503 device_lost body via the service-backed shims, and (2) explicitly DOCUMENT (module comment) that the main.py watchdog (verified at main.py:587-672) is NOT migrated to `cleanup_device_lost` in this batch — it has a different observable WS payload (`reason:"usb_unplugged"` via `broadcast(...)` + leader-snapshot promotion via GroupSyncService) and unifying it is out of scope for a behavior-preserving carve.

- [ ] **Step 1: Write the CHARACTERIZATION test** (REAL FastAPI `TestClient`, real app, service-backed shims — mirrors `test_location_di_char.py`). Pins the teleport recovery boundary: a `DeviceLostError` raised by the engine op flows through `with_recovery` (full_reconnect returns False, no recovery) -> `cleanup_device_lost` -> the controller's 503 body. No answer-hardcoding: the engine double genuinely raises; the resolver genuinely cleans up. NOTE `_try_with_recovery_retry` calls `app_state.device_manager.full_reconnect`, so patching `dm.full_reconnect` (where `dm = app_state.device_manager`) is the correct seam.

```python
"""Pin the api/location.py recovery BOUNDARY after the EngineResolver lift:
the controller is the ONLY place HTTPException is built. A DeviceLostError
from the teleport op must surface as the frozen 503 device_lost body.
Real app + TestClient; the engine + dm are doubles that genuinely fail.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.location_service import DeviceLostError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_teleport_device_lost_surfaces_frozen_503(client):
    from main import app_state

    udid = "UDID-TELE-LOST"
    dm = app_state.device_manager

    fake_engine = MagicMock()
    fake_engine.current_position = None
    fake_engine.teleport = AsyncMock(
        side_effect=DeviceLostError("gone", reason=DeviceLostError.REASON_USB_GONE)
    )

    async def fake_resolver(u=None, registry=None):
        return fake_engine

    fake_connections = {udid: object()}

    async def _fake_disconnect(u):
        fake_connections.pop(u, None)

    class _CapPublisher:
        async def publish(self, event):
            pass

    cooldown = app_state.cooldown_timer
    with (
        patch("api.location._engine", fake_resolver),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(dm, "full_reconnect", new=AsyncMock(return_value=False)),
        patch.object(app_state, "remove_engine", new=AsyncMock(return_value=None)),
        patch.object(app_state, "simulation_engines", {}),
        patch.object(cooldown, "enabled", False),
        patch.object(app_state, "_primary_udid", udid),
    ):
        resp = client.post("/api/location/teleport",
                           json={"lat": 25.0, "lng": 121.0, "udid": udid})

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["code"] == "device_lost"
    assert body["detail"]["reason"] == DeviceLostError.REASON_USB_GONE
    assert body["detail"]["message"] == "USB 已拔除,請重新插上後再操作"
```

- [ ] **Step 2: Run it, verify it PASSES against the service-backed shims.** `cd backend && .venv/bin/python -m pytest tests/test_location_recovery_boundary_char.py -v` — PASSES (the teleport endpoint runs `_do_teleport` via `_try_with_recovery_retry`; the op raises `DeviceLostError`, `full_reconnect` returns False so it re-raises, the endpoint `except DeviceLostError` calls `_handle_device_lost` and raises the returned 503). This is the post-lift behavior; it must equal the pre-lift behavior.

- [ ] **Step 3: Refactor (behavior-preserving) — add the scope comment, no logic change.** The endpoints already delegate correctly after the prior tasks; the only edit here is a module-level comment documenting the deliberate non-reuse of the watchdog path, so a future engineer doesn't "helpfully" route main.py's watchdog through `cleanup_device_lost` and silently change the `usb_unplugged` payload. Add just above the `_engine` shim in `api/location.py`:

```python
# NOTE (SH3 / A4): EngineResolver (services/engine_resolver.py) owns the
# resolve+recovery+device-lost-cleanup orchestration. The main.py usbmux
# watchdog (main.py: lost_now handling, ~lines 587-672) deliberately does
# NOT reuse EngineResolver.cleanup_device_lost: it broadcasts
# device_disconnected with reason="usb_unplugged" (not "device_lost") via
# broadcast(...) (not dm._events.publish), captures a leader resume
# snapshot, and promotes a follower via GroupSyncService. Those are a
# DIFFERENT observable WS contract; unifying them is out of scope for a
# behavior-preserving carve. This controller is the ONLY place a resolve/
# recovery domain error is mapped to an HTTPException.
```

- [ ] **Step 4: Run the boundary test + the full location char suite + broader suite.** `cd backend && .venv/bin/python -m pytest tests/test_location_recovery_boundary_char.py tests/test_location_di_char.py tests/test_location_device_lost_publisher.py -v` — all PASS. Then `cd backend && .venv/bin/python -m pytest -q` — full suite green.

- [ ] **Step 5: Gate.** `cd backend && .venv/bin/lint-imports` — expect `7 kept, 0 broken` (comment-only change; no new import).

- [ ] **Step 6: Commit.** `git add backend/api/location.py backend/tests/test_location_recovery_boundary_char.py` + message: `refactor(sh3): pin location recovery boundary + document watchdog non-reuse`


---


<!-- ===== S2 · api/device.py WiFi-tunnel god-module carve ===== -->

### Task 6: Extract pure `build_tunnel_udid_candidates` into a new WifiTunnelService (cleanest seam first)

**Files:**
- Create: `backend/services/wifi_tunnel_service.py`
- Modify: `backend/api/device.py:917-964` (the `_build_tunnel_udid_candidates` body)
- Test: `backend/tests/test_wifi_tunnel_candidates.py`

**Interfaces:**
- Consumes: none
- Produces: `services.wifi_tunnel_service.build_tunnel_udid_candidates(req_udid: str | None, req_ip: str, req_port: int, *, connected_udids: list[str], pair_record_idents: list[str]) -> list[str]` (PURE — no I/O). The api wrapper `api.device._build_tunnel_udid_candidates(req: WifiTunnelStartRequest) -> list[str]` is PRESERVED (name + signature) and now delegates.

- [ ] **Step 1: Write the CHARACTERIZATION test** — NEW-helper mode (pure fn) + wrapper-behavior mode. Unit-test the pure fn directly (priority order: explicit udid → connected udids → pair-record idents, de-duped preserving order; `pending:ip:port` fallback when empty). Then characterize the wrapper with a real `_dm()` patch + stubbed lazy pair-records iterator so we prove the disk/dm resolution is unchanged. Real imports mirror `tests/test_wifi_tunnel_busy_409.py` (which already monkeypatches the wrapper as `lambda req: [...]`).
```python
"""Characterization + unit: build_tunnel_udid_candidates priority/dedup/fallback,
plus the api wrapper resolving connected udids + cached pair records."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import api.device as device_mod
from api.device import WifiTunnelStartRequest
from services.wifi_tunnel_service import build_tunnel_udid_candidates


def test_pure_priority_order_dedup():
    out = build_tunnel_udid_candidates(
        "REQ-UDID", "192.168.0.5", 49152,
        connected_udids=["USB-1", "REQ-UDID"],   # REQ-UDID dup must drop
        pair_record_idents=["CACHE-A", "USB-1"],  # USB-1 dup must drop
    )
    assert out == ["REQ-UDID", "USB-1", "CACHE-A"]


def test_pure_no_req_udid_starts_with_connected():
    out = build_tunnel_udid_candidates(
        None, "10.0.0.9", 50000,
        connected_udids=["USB-1"],
        pair_record_idents=["CACHE-A"],
    )
    assert out == ["USB-1", "CACHE-A"]


def test_pure_empty_falls_back_to_pending_key():
    out = build_tunnel_udid_candidates(
        None, "10.0.0.9", 50000,
        connected_udids=[],
        pair_record_idents=[],
    )
    assert out == ["pending:10.0.0.9:50000"]


def test_wrapper_resolves_dm_and_pair_records(monkeypatch):
    req = WifiTunnelStartRequest(ip="192.168.0.5", port=49152, udid="REQ-UDID")
    dm = MagicMock()
    dm._connections = {"USB-1": object()}
    # Stub the lazy pair-records iterator to two fake Path-like records.
    class _Rec:
        def __init__(self, name, mtime):
            self.name = name
            self._mtime = mtime
        def stat(self):
            return MagicMock(st_mtime=self._mtime)
    recs = [_Rec("remote_CACHE-A.plist", 100.0), _Rec("CACHE-B.plist", 200.0)]
    monkeypatch.setattr(
        "pymobiledevice3.pair_records.iter_remote_pair_records",
        lambda: recs, raising=False,
    )
    with patch.object(device_mod, "_dm", return_value=dm):
        out = device_mod._build_tunnel_udid_candidates(req)
    # req.udid first, then USB-tracked, then pair-record idents (wrapper sorts
    # mtime DESC: CACHE-B mtime 200 before CACHE-A mtime 100; remote_ stripped).
    assert out == ["REQ-UDID", "USB-1", "CACHE-B", "CACHE-A"]
```
- [ ] **Step 2: Run it** — `cd backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_candidates.py -v`. MODE: all four FAIL first (helper doesn't exist → ImportError at module load; the wrapper test also needs the delegating wrapper). All PASS after Step 3.
- [ ] **Step 3: Refactor (behavior-preserving)** — Create `backend/services/wifi_tunnel_service.py`:
```python
"""WiFi-tunnel use-case orchestration carved out of api/device.py.

Pure candidate computation lives here (no I/O); the api layer resolves the
live collaborators (dm connections, cached pair records) and delegates.
"""
from __future__ import annotations


def build_tunnel_udid_candidates(
    req_udid: str | None,
    req_ip: str,
    req_port: int,
    *,
    connected_udids: list[str],
    pair_record_idents: list[str],
) -> list[str]:
    """Return udids to try for an incoming /wifi/tunnel/start request, in
    priority order: explicit udid > USB-tracked > cached pair-record idents
    (already mtime-sorted by the caller). De-duped, order preserved. Falls
    back to a ``pending:ip:port`` placeholder when nothing else is known.

    Pure: the caller supplies connected_udids (dm._connections.keys()) and
    pair_record_idents (stripped from ~/.pymobiledevice3 stems).
    """
    candidates: list[str] = []

    def _add(c: str | None) -> None:
        if c and c not in candidates:
            candidates.append(c)

    _add(req_udid)
    for u in connected_udids:
        _add(u)
    for ident in pair_record_idents:
        _add(ident)

    if not candidates:
        candidates.append(f"pending:{req_ip}:{req_port}")
    return candidates
```
Then replace the api/device.py body (currently L917-964). Keep the original docstring + the I/O resolution (dm + lazy pair-record iter + mtime-DESC sort + `remote_` strip + `.split('.',1)[0]`) in the wrapper:
```python
def _build_tunnel_udid_candidates(req: WifiTunnelStartRequest) -> list[str]:
    """Return udids to try for an incoming /wifi/tunnel/start request, in
    priority order (see services.wifi_tunnel_service.build_tunnel_udid_candidates).
    This wrapper resolves the live collaborators (dm connections + cached
    pair records) and delegates the pure policy. Bug history: v0.2.92 only
    used the first candidate, which broke multi-iPhone users."""
    from services.wifi_tunnel_service import build_tunnel_udid_candidates

    connected_udids: list[str] = []
    try:
        dm = _dm()
        connected_udids = list(dm._connections.keys())
    except (RuntimeError, AttributeError):
        pass

    pair_record_idents: list[str] = []
    try:
        from pymobiledevice3.pair_records import iter_remote_pair_records
        records = sorted(
            iter_remote_pair_records(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for rec in records:
            stem = rec.name
            if stem.startswith("remote_"):
                stem = stem.split("remote_", 1)[1]
            ident = stem.split(".", 1)[0]
            pair_record_idents.append(ident)
    except Exception:
        _tunnel_logger.debug("Could not enumerate cached pair records", exc_info=True)

    return build_tunnel_udid_candidates(
        req.udid, req.ip, req.port,
        connected_udids=connected_udids,
        pair_record_idents=pair_record_idents,
    )
```
NOTE: the old code used ONE shared `_add`/`candidates` list across all three sources; `build_tunnel_udid_candidates` does the same, so cross-source dedup is preserved identically. The `(RuntimeError, AttributeError)` guard around the dm lookup matches the original L944.
- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_candidates.py tests/test_wifi_tunnel_busy_409.py -v` (the busy_409 test monkeypatches the wrapper as `lambda req: [...]` — must still pass), then `cd backend && .venv/bin/python -m pytest -q` (941 + new, all green).
- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken` (new services module imports stdlib only; no new cross-ring edge).
- [ ] **Step 6: Commit** — `git add backend/services/wifi_tunnel_service.py backend/api/device.py backend/tests/test_wifi_tunnel_candidates.py` then `git commit -m "refactor(sh3): carve pure build_tunnel_udid_candidates into WifiTunnelService"`


---

### Task 7: Carve the USB-fallback path out of `wifi_tunnel_stop` into WifiTunnelService

**Files:**
- Modify: `backend/api/device.py:1169-1220` (the USB-fallback try-block inside `wifi_tunnel_stop`)
- Modify: `backend/services/wifi_tunnel_service.py` (add `run_usb_fallback`)
- Test: `backend/tests/test_wifi_tunnel_stop_usb_fallback_char.py`

**Interfaces:**
- Consumes: `services.wifi_tunnel_service` module from the candidates task (same file).
- Produces: `services.wifi_tunnel_service.run_usb_fallback(was_network_udids: list[str], *, device_manager, engine_registry, discover_devices, publish, logger) -> None`. (`discover_devices`/`publish`/`logger` injected; sticky set + connect/disconnect read off `device_manager`, create/remove-engine off `engine_registry` — they are already narrow. Service imports zero api/main.)

- [ ] **Step 1: Write the CHARACTERIZATION test** — Drive the REAL fallback logic (no stub of the fn under test) through a `TestClient` POST to `/api/device/wifi/tunnel/stop`, asserting the exact ordered actions. Mirror the harness in `tests/test_device_forget_endpoint.py` (TestClient + `app.state.container.engine_registry` + `.device_manager` + `.simulation_engines` + MagicMock conns + monkeypatched dm.disconnect/discover_devices). The endpoint runs the REAL `_cleanup_wifi_connection_for` (which calls `eng_reg.remove_engine` + `dm.disconnect`), so patch `remove_engine`/`disconnect` before the request.
```python
"""Characterization: /wifi/tunnel/stop USB-fallback re-attaches a udid that is
now visible as USB, skips sticky-denied udids, and (rollback path) emits the
exact device_error payload. Deep-equal events.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_state():
    from main import app
    app_state = app.state.container.engine_registry
    dm = app_state.device_manager
    yield
    dm._connections.clear()
    dm.sticky_user_denied.clear()
    app_state.simulation_engines.clear()
    import api.device as device_mod
    device_mod._tunnels.clear()


def test_usb_fallback_reattaches_visible_usb_device(monkeypatch):
    from main import app
    app_state = app.state.container.engine_registry
    dm = app_state.device_manager
    udid = "UDID-FALLBACK"

    # A Network conn exists so cleanup tears it down, then USB-fallback runs.
    conn = MagicMock()
    conn.connection_type = "Network"
    dm._connections[udid] = conn

    async def fake_disconnect(u):
        dm._connections.pop(u, None)
    monkeypatch.setattr(dm, "disconnect", fake_disconnect)
    monkeypatch.setattr(app_state, "remove_engine", AsyncMock())

    async def fake_discover():
        return [SimpleNamespace(udid=udid, connection_type="USB")]
    monkeypatch.setattr(dm, "discover_devices", fake_discover)

    connected = []
    async def fake_connect(u):
        connected.append(u)
    monkeypatch.setattr(dm, "connect", fake_connect)

    created = []
    async def fake_create(u, force=False):
        created.append((u, force))
    monkeypatch.setattr(app_state, "create_engine_for_device", fake_create)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/tunnel/stop", json={"udid": udid})
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert connected == [udid]
    assert created == [(udid, True)]  # force=True, exact


def test_usb_fallback_skips_sticky_denied(monkeypatch):
    from main import app
    app_state = app.state.container.engine_registry
    dm = app_state.device_manager
    udid = "UDID-DENIED"
    conn = MagicMock(); conn.connection_type = "Network"
    dm._connections[udid] = conn
    dm.sticky_user_denied.add(udid)

    async def fake_disconnect(u):
        dm._connections.pop(u, None)
    monkeypatch.setattr(dm, "disconnect", fake_disconnect)
    monkeypatch.setattr(app_state, "remove_engine", AsyncMock())

    async def fake_discover():
        return [SimpleNamespace(udid=udid, connection_type="USB")]
    monkeypatch.setattr(dm, "discover_devices", fake_discover)

    connected = []
    async def fake_connect(u):
        connected.append(u)
    monkeypatch.setattr(dm, "connect", fake_connect)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/tunnel/stop", json={"udid": udid})
    assert resp.status_code == 200
    assert connected == []  # sticky-denied udid is never reconnected
```
- [ ] **Step 2: Run it, verify it PASSES on current code** — `cd backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_stop_usb_fallback_char.py -v`. These PIN current behavior of the un-refactored endpoint → PASS now.
- [ ] **Step 3: Refactor (behavior-preserving)** — Add to `backend/services/wifi_tunnel_service.py`:
```python
async def run_usb_fallback(
    was_network_udids,
    *,
    device_manager,
    engine_registry,
    discover_devices,
    publish,
    logger,
) -> None:
    """After a WiFi tunnel stop, re-attach via USB any udid that (a) was just
    in WiFi, (b) is NOT sticky-denied, and (c) shows up as USB right now.
    On engine-creation failure, roll the connection back and emit device_error.
    Collaborators injected so this never imports api/main."""
    try:
        devices = await discover_devices()
        for udid in was_network_udids:
            if udid in device_manager.sticky_user_denied:
                logger.info("USB fallback: skipping %s (sticky_user_denied)", udid)
                continue
            usb_dev = next(
                (d for d in devices if d.udid == udid and d.connection_type == "USB"),
                None,
            )
            if usb_dev is None:
                logger.info(
                    "USB fallback: skipping %s (not visible as USB after tunnel stop)",
                    udid,
                )
                continue
            try:
                await device_manager.connect(usb_dev.udid)
            except Exception:
                logger.exception("USB fallback: connect failed for %s", usb_dev.udid)
                continue
            try:
                await engine_registry.create_engine_for_device(usb_dev.udid, force=True)
                logger.info("Switched back to USB connection: %s", usb_dev.udid)
            except Exception:
                logger.exception(
                    "USB fallback: engine creation failed for %s; rolling back",
                    usb_dev.udid,
                )
                try:
                    await device_manager.disconnect(usb_dev.udid)
                except Exception:
                    pass
                await engine_registry.remove_engine(usb_dev.udid)
                try:
                    await publish(("device_error", {
                        "udid": usb_dev.udid,
                        "stage": "usb_fallback",
                        "error": "USB fallback engine creation failed",
                    }))
                except Exception:
                    pass
    except Exception:
        logger.exception("USB fallback after tunnel stop failed")
```
Then in `api/device.py` replace the whole try-block at L1169-1220 (`# USB fallback: ...` comment through the final `except Exception: _tunnel_logger.exception("USB fallback after tunnel stop failed")`) with:
```python
    # USB fallback: only re-attach udids that were just in WiFi AND show
    # up as USB right now (covers users plugging in a cable mid-stop).
    from services.wifi_tunnel_service import run_usb_fallback
    eng_reg = _engines()
    await run_usb_fallback(
        was_network_udids,
        device_manager=dm,
        engine_registry=eng_reg,
        discover_devices=dm.discover_devices,
        publish=dm._events.publish,
        logger=_tunnel_logger,
    )
```
(The `dm = _dm()` at L1134 and `was_network_udids` at L1163 already exist above the moved block — keep them. The `eng_reg = _engines()` that was at L1172 inside the carved block moves into this wrapper snippet. The `_cleanup_wifi_connection_for` + `_tear_down_tunnel` loop at L1165-1167 inside the `async with _tunnels_lock:` is UNTOUCHED.)
- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_stop_usb_fallback_char.py -v` (still PASS, behavior unchanged), then `cd backend && .venv/bin/python -m pytest -q` (941 + 2 new, all green).
- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken`.
- [ ] **Step 6: Commit** — `git add backend/services/wifi_tunnel_service.py backend/api/device.py backend/tests/test_wifi_tunnel_stop_usb_fallback_char.py` then `git commit -m "refactor(sh3): carve USB-fallback path out of wifi_tunnel_stop into WifiTunnelService"`


---

### Task 8: Lift `_per_tunnel_watchdog` decision logic behind WifiTunnelService (riskiest — do LAST)

**Files:**
- Modify: `backend/api/device.py:774-915` (the `_per_tunnel_watchdog` body)
- Modify: `backend/services/wifi_tunnel_service.py` (add `WifiTunnelService` class with `run_watchdog`)
- Test: `backend/tests/test_wifi_tunnel_service_watchdog_char.py` (NEW; the EXISTING `tests/test_watchdog_tunnel_lost_reason_char.py` must still pass byte-for-byte against the wrapper)

**Interfaces:**
- Consumes: `services.wifi_tunnel_service` (candidates + usb-fallback tasks).
- Produces: `services.wifi_tunnel_service.WifiTunnelService` with `async def run_watchdog(self, udid, runner) -> None`, ctor `WifiTunnelService(*, tunnels, tunnels_lock, tunnel_watchdogs, engines_for, attempt_restart, cleanup_wifi, publish, logger, sim_state_disconnected, restart_backoff)`. The api `_per_tunnel_watchdog(udid, runner)` is PRESERVED as the public entry point (the `_watchdog_factory` in `_attempt_tunnel_restart` L764-765 and `infra/device/tunnel_restart.attempt_tunnel_restart` both create tasks on it) and now builds a `WifiTunnelService` per call and delegates.

- [ ] **Step 1: Write the CHARACTERIZATION test** — Drive `WifiTunnelService.run_watchdog` directly with a REAL DeviceLostError-raising task + a captured publisher (no stub of run_watchdog). Assert the exact ordered tunnel_degraded → tunnel_lost payloads, including the SH1 A12 reason/last_error threading. Mirror `tests/test_watchdog_tunnel_lost_reason_char.py`'s `_CapPublisher` (unpacks `etype, data = event`) + MagicMock runner pattern. `target_ip=None` ⇒ restart loop skipped ⇒ `attempt_restart` (AsyncMock) never called.
```python
"""Characterization: WifiTunnelService.run_watchdog threads a DeviceLostError's
reason+last_error into tunnel_degraded/tunnel_lost (deep-equal), and a clean exit
keeps reason='task_exited' with NO last_error key. Real task, no stubbing of the
method under test; teardown skips the restart loop (no target ip/port).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.location_service import DeviceLostError
from services.wifi_tunnel_service import WifiTunnelService

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.events: list[tuple] = []
    async def publish(self, event):
        etype, data = event
        self.events.append((etype, {**data}))


def _make_service(*, tunnels, publish):
    return WifiTunnelService(
        tunnels=tunnels,
        tunnels_lock=asyncio.Lock(),
        tunnel_watchdogs={},
        engines_for=lambda udid: None,            # no sim engine
        attempt_restart=AsyncMock(return_value=False),
        cleanup_wifi=AsyncMock(return_value=True),
        publish=publish,
        logger=MagicMock(),
        sim_state_disconnected=None,
        restart_backoff=(3.0, 6.0, 12.0),
    )


async def test_run_watchdog_threads_device_lost_reason():
    udid = "UDID-WD-REASON"
    async def _dead_task():
        raise DeviceLostError(
            "WiFi tunnel gone",
            reason=DeviceLostError.REASON_TUNNEL_DEAD,
            last_error="helper reports tunnel for X is gone",
        )
    runner = MagicMock()
    runner.task = asyncio.create_task(_dead_task())
    runner.target_ip = None
    runner.target_port = None
    pub = _CapPublisher()
    tunnels = {udid: runner}
    svc = _make_service(tunnels=tunnels, publish=pub.publish)
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }
    assert by_type["tunnel_lost"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }


async def test_run_watchdog_clean_exit_keeps_task_exited_shape():
    udid = "UDID-WD-CLEAN"
    async def _clean_task():
        return
    runner = MagicMock()
    runner.task = asyncio.create_task(_clean_task())
    runner.target_ip = None
    runner.target_port = None
    pub = _CapPublisher()
    svc = _make_service(tunnels={udid: runner}, publish=pub.publish)
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {"udid": udid, "reason": "task_exited"}
    assert by_type["tunnel_lost"] == {"udid": udid, "reason": "task_exited"}
```
- [ ] **Step 2: Run it** — MODE: NEW-helper. `cd backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_service_watchdog_char.py -v` FAILS first (ImportError: cannot import WifiTunnelService). PASSES after Step 3. SEPARATELY: the existing `tests/test_watchdog_tunnel_lost_reason_char.py` (which drives the api `_per_tunnel_watchdog` wrapper) must STILL pass byte-for-byte.
- [ ] **Step 3: Refactor (behavior-preserving)** — Add the class to `backend/services/wifi_tunnel_service.py`. Move the watchdog body VERBATIM (api/device.py L774-915), substituting injected collaborators for the module globals: `_dm()`→ (publisher already injected as `self._publish`; the `dm` local is no longer needed since its only use was `dm._events.publish`), `_tunnels`→`self._tunnels`, `_tunnels_lock`→`self._tunnels_lock`, `_tunnel_watchdogs`→`self._tunnel_watchdogs`, `_engines().simulation_engines.get(udid)`→`self._engines_for(udid)`, `_attempt_tunnel_restart(udid, ip, port, snapshot, runner)`→`self._attempt_restart(udid, ip, port, snapshot, runner)`, `_cleanup_wifi_connection_for(udid, caller=...)`→`self._cleanup_wifi(udid, caller=...)`, `dm._events.publish((event_type, payload))`→`self._publish((event_type, payload))`, the `from models.schemas import SimulationState as _SS; old_eng.state = _SS.DISCONNECTED` park step → `if self._sim_state_disconnected is not None: old_eng.state = self._sim_state_disconnected` (and only emit the disconnected state_change inside that guard), and `_TUNNEL_RESTART_BACKOFF`→`self._restart_backoff`. CRITICAL: preserve the `_reason_payload` build EXACTLY (clean ⇒ `{"reason":"task_exited"}`; DeviceLostError ⇒ adds reason + last_error only when `last_error is not None`, api/device.py L797-801), preserve the `_tunnels.get(udid) is not runner` stale checks (L805, L879), the `async with self._tunnels_lock:` teardown (L901), the `wd is not asyncio.current_task()` guard (L906), and the outer `except asyncio.CancelledError: raise` (L913-914) plus the inner `except asyncio.CancelledError: return` on `await task` (L789-790) and on `await asyncio.sleep(delay)` (L874-875).
```python
from services.location_service import DeviceLostError


class WifiTunnelService:
    def __init__(self, *, tunnels, tunnels_lock, tunnel_watchdogs, engines_for,
                 attempt_restart, cleanup_wifi, publish, logger,
                 sim_state_disconnected, restart_backoff):
        self._tunnels = tunnels
        self._tunnels_lock = tunnels_lock
        self._tunnel_watchdogs = tunnel_watchdogs
        self._engines_for = engines_for
        self._attempt_restart = attempt_restart
        self._cleanup_wifi = cleanup_wifi
        self._publish = publish
        self._logger = logger
        self._sim_state_disconnected = sim_state_disconnected
        self._restart_backoff = restart_backoff

    async def run_watchdog(self, udid, runner):
        # ...VERBATIM body of api/device.py L782-914 (everything after the
        # `dm = _dm()` line), with the substitutions above. self._logger
        # replaces _tunnel_logger.
```
Then rewrite api/device.py `_per_tunnel_watchdog` to a thin delegating wrapper (keep the docstring verbatim):
```python
async def _per_tunnel_watchdog(udid: str, runner: TunnelRunner) -> None:
    """Watch a single device's tunnel ... (docstring preserved verbatim from L775-780)."""
    from models.schemas import SimulationState as _SS
    from services.wifi_tunnel_service import WifiTunnelService
    dm = _dm()
    svc = WifiTunnelService(
        tunnels=_tunnels,
        tunnels_lock=_tunnels_lock,
        tunnel_watchdogs=_tunnel_watchdogs,
        engines_for=lambda u: _engines().simulation_engines.get(u),
        attempt_restart=_attempt_tunnel_restart,
        cleanup_wifi=_cleanup_wifi_connection_for,
        publish=dm._events.publish,
        logger=_tunnel_logger,
        sim_state_disconnected=_SS.DISCONNECTED,
        restart_backoff=_TUNNEL_RESTART_BACKOFF,
    )
    await svc.run_watchdog(udid, runner)
```
NOTE: the existing `test_watchdog_tunnel_lost_reason_char.py` patches `device_mod._dm`/`_engines`/`_tunnels` (dict-patch) + `device_mod._cleanup_wifi_connection_for` — the wrapper resolves all of those at call time (`dm = _dm()`; `engines_for` lambda calls `_engines()` lazily; `_tunnels` passed by reference so the dict-patch mutates the same object; `cleanup_wifi=_cleanup_wifi_connection_for` reads the module attr at wrapper-call time), so the patches still take effect. Keep `_attempt_tunnel_restart`, `_cleanup_wifi_connection_for`, `_TUNNEL_RESTART_BACKOFF`, `_tunnels`, `_tunnels_lock`, `_tunnel_watchdogs` defined in api/device.py (consumed by the wrapper + other endpoints).
- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_service_watchdog_char.py tests/test_watchdog_tunnel_lost_reason_char.py tests/test_wifi_tunnel_facade.py tests/test_no_reconnect_manager.py -v` (new + existing watchdog chars all PASS), then `cd backend && .venv/bin/python -m pytest -q` (full suite green).
- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken`. (services importing `services.location_service` + stdlib only; no fastapi, no api, no infra edge.)
- [ ] **Step 6: Commit** — `git add backend/services/wifi_tunnel_service.py backend/api/device.py backend/tests/test_wifi_tunnel_service_watchdog_char.py` then `git commit -m "refactor(sh3): lift per-tunnel watchdog decision logic behind WifiTunnelService"`


---


<!-- ===== S3 · Store upsert unify + controller methods + Container lifespan + watcher dedup + geocode DI ===== -->

### Task 9: Extract BookmarkManager._upsert_items shared by import_json / import_catalog / force_seed

**Files:**
- Modify: `backend/services/bookmarks.py` (the three import/seed methods + a new private `_upsert_items`; locate by content — `def import_json`, `def import_catalog`, `def force_seed`)
- Test: `backend/tests/test_upsert_items_unify.py` (new)

**Interfaces:**
- Consumes: `domain.store_merge.force_seed_items(items: list, now_iso: str) -> list`, `services.bookmarks.enrich_bookmark(bm, *, force: bool=False) -> bool`
- Produces: `BookmarkManager._upsert_items(self, items: list, *, stamp_now: bool, enrich_force: bool) -> tuple[int, int]` returning `(added, updated)`. The three callers (`import_json`, `import_catalog`, `force_seed`) all route through it.

- [ ] **Step 1: Write the CHARACTERIZATION test** — pins the CURRENT outputs of all three paths against REAL collaborators (a real BookmarkManager backed by a tmp JsonStore via `make_bookmark_manager`, real `merge_stores`, real disk). No stubbing of the method under test. The fixture mirrors `test_force_seed.py` EXACTLY (it monkeypatches ONLY `services.bookmarks.BOOKMARKS_FILE` — that single reassignment already makes `_bookmarks_path_default`'s `BOOKMARKS_FILE is not _CONFIG_DEFAULT_BOOKMARKS_FILE` guard True, so no second patch is needed).

```python
"""Characterization: import_json / import_catalog / force_seed all upsert via
one primitive. Pins CURRENT add/update counts + on-disk survival BEFORE the
refactor, so the carve is byte-for-byte behavior-preserving."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.schemas import Bookmark


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


def test_import_json_add_then_skip(manager):
    payload = json.dumps({
        "categories": [{"id": "cat-x", "name": "E", "color": "#ef4444",
                        "sort_order": 1, "created_at": ""}],
        "bookmarks": [{"id": "b1", "name": "p1", "lat": 1.0, "lng": 2.0,
                       "category_id": "cat-x", "created_at": "",
                       "last_used_at": "", "updated_at": ""}],
    })
    assert manager.import_json(payload) == {"imported": 1, "skipped": 0}
    assert manager.import_json(payload) == {"imported": 0, "skipped": 1}
    # import_json stamps updated_at=now so the bookmark survives the merge.
    on_disk = json.loads(Path(manager._bookmarks_path()).read_text())
    bm = next(b for b in on_disk["bookmarks"] if b["id"] == "b1")
    assert bm["updated_at"] != ""
    # cat-x exists (added by this import), so the bookmark keeps its category.
    assert bm["category_id"] == "cat-x"


def test_import_catalog_add_update_resurrect(manager):
    # Seed one catalog category + one catalog bookmark.
    cat_payload = json.dumps({
        "categories": [{"id": "seed-cat", "name": "Seed", "color": "#111111",
                        "sort_order": 0, "created_at": ""}],
        "bookmarks": [{"id": "seed-1", "name": "Orig", "lat": 1.0, "lng": 2.0,
                       "category_id": "seed-cat", "created_at": "",
                       "last_used_at": ""}],
    })
    first = manager.import_catalog(cat_payload)
    # 1 category + 1 bookmark are both new -> added counts BOTH (added_cats+added_bms).
    assert first == {"added": 2, "updated": 0, "resurrected": 0}
    # Re-sync with a name+coord correction -> the existing ids are UPSERTED.
    cat_payload2 = json.dumps({
        "categories": [{"id": "seed-cat", "name": "Seed", "color": "#111111",
                        "sort_order": 0, "created_at": ""}],
        "bookmarks": [{"id": "seed-1", "name": "Corrected", "lat": 9.0, "lng": 8.0,
                       "category_id": "seed-cat", "created_at": "",
                       "last_used_at": ""}],
    })
    second = manager.import_catalog(cat_payload2)
    assert second == {"added": 0, "updated": 2, "resurrected": 0}
    bm = next(b for b in manager.store.bookmarks if b.id == "seed-1")
    assert bm.name == "Corrected" and bm.lat == 9.0 and bm.lng == 8.0


def test_import_catalog_resurrects_deleted_id(manager):
    created = manager.create_bookmark(name="X", lat=1.0, lng=2.0)
    manager.delete_bookmark(created.id)
    payload = json.dumps({
        "categories": [],
        "bookmarks": [{"id": created.id, "name": "Back", "lat": 1.0, "lng": 2.0,
                       "category_id": "default", "created_at": "",
                       "last_used_at": ""}],
    })
    result = manager.import_catalog(payload)
    assert result["resurrected"] == 1
    on_disk = json.loads(Path(manager._bookmarks_path()).read_text())
    assert created.id in {b["id"] for b in on_disk["bookmarks"]}


def test_force_seed_add_then_update(manager):
    item = Bookmark(id="f1", name="Seeded", lat=1.0, lng=2.0,
                    category_id="default", updated_at="")
    assert manager.force_seed([item]) == {"added": 1, "updated": 0}
    item2 = Bookmark(id="f1", name="Seeded v2", lat=3.0, lng=4.0,
                     category_id="default", updated_at="")
    assert manager.force_seed([item2]) == {"added": 0, "updated": 1}
    bm = next(b for b in manager.store.bookmarks if b.id == "f1")
    assert bm.name == "Seeded v2" and bm.lat == 3.0
```

- [ ] **Step 2: Run it, verify it PASSES on current code** — `cd backend && .venv/bin/python -m pytest tests/test_upsert_items_unify.py -v` → all PASS on the un-refactored god-service (it pins existing behavior). Mode: characterization (the methods already exist).

- [ ] **Step 3: Refactor (behavior-preserving)** — add ONE shared private primitive and route all three callers through it. The current `force_seed` body is:

```python
        now = _now_iso()
        force_seed_items(items, now)

        existing = {b.id: b for b in self.store.bookmarks}
        added = updated = 0
        for bm in items:
            if bm.id in existing:
                old = existing[bm.id]
                old.name = bm.name
                old.lat = bm.lat
                old.lng = bm.lng
                old.address = bm.address
                old.category_id = bm.category_id
                old.country_code = bm.country_code
                old.updated_at = bm.updated_at
                enrich_bookmark(old, force=True)
                updated += 1
            else:
                enrich_bookmark(bm)
                self.store.bookmarks.append(bm)
                existing[bm.id] = bm
                added += 1

        self._save()
        return {"added": added, "updated": updated}
```

Introduce the shared primitive (note: it must NOT call `_save()` — callers own the save + logging + return shape, and `import_catalog` upserts categories too which stay in their own loop). Because `force_seed_items` ALWAYS overwrites `updated_at = now`, after stamping `bm.updated_at == now`, so `old.updated_at = bm.updated_at` is byte-equivalent to the catalog path's current `old.updated_at = now`:

```python
    def _upsert_items(self, items: list, *, stamp_now: bool, enrich_force: bool) -> tuple[int, int]:
        """Upsert bookmark *items* into self.store.bookmarks; the single seed/
        import primitive shared by import_json / import_catalog / force_seed.

        ``stamp_now`` stamps each incoming item's ``updated_at = now()`` via
        force_seed_items so it beats any pre-existing real-timestamp tombstone
        in merge_stores inside _save() (the empty-updated_at pitfall). This is
        a PARAMETER, not a per-path omission — every caller declares whether it
        wants the stamp instead of duplicating the logic.

        For an UPDATE (id already present) the existing record's mutable fields
        are overwritten and re-enriched with ``force=enrich_force``. For an ADD
        the new item is enriched with ``force=False`` (fill blanks only).

        Caller-owned: validating category_id, appending categories, calling
        _save(), logging, and the return-shape mapping. Returns (added, updated).
        """
        if stamp_now:
            force_seed_items(items, _now_iso())
        existing = {b.id: b for b in self.store.bookmarks}
        added = updated = 0
        for bm in items:
            old = existing.get(bm.id)
            if old is not None:
                old.name = bm.name
                old.lat = bm.lat
                old.lng = bm.lng
                old.address = bm.address
                old.category_id = bm.category_id
                old.country_code = bm.country_code
                old.updated_at = bm.updated_at
                enrich_bookmark(old, force=enrich_force)
                updated += 1
            else:
                enrich_bookmark(bm)
                self.store.bookmarks.append(bm)
                existing[bm.id] = bm
                added += 1
        return added, updated
```

Then rewrite `force_seed` to delegate (preserving its `{added, updated}` shape and its own `_save()`):

```python
    def force_seed(self, items: list) -> dict:
        """ ... (keep the existing docstring verbatim) ... """
        added, updated = self._upsert_items(items, stamp_now=True, enrich_force=True)
        self._save()
        return {"added": added, "updated": updated}
```

Rewrite the bookmark-upsert loop inside `import_catalog` to delegate (keep the category loop, `resurrected` count, `valid_cat_ids` reparent-to-default, `_save()`, logging, and `{added, updated, resurrected}` return UNCHANGED). The catalog path already calls `force_seed_items(incoming.bookmarks, now)` up front (line ~648), so replace the manual bookmark for-loop (`existing_bms = ...; added_bms = updated_bms = 0; for bm in incoming.bookmarks: ...`) with:

```python
        valid_cat_ids = {c.id for c in self.store.categories}
        for bm in incoming.bookmarks:
            if bm.category_id not in valid_cat_ids:
                bm.category_id = "default"
        # incoming.bookmarks already stamped via force_seed_items above, so
        # stamp_now=False here avoids double-stamping; catalog upserts re-resolve
        # geo on coord changes (enrich_force=True).
        added_bms, updated_bms = self._upsert_items(
            incoming.bookmarks, stamp_now=False, enrich_force=True
        )
```

Keep `added_cats + added_bms`, `updated_cats + updated_bms`, the resurrected count, the log line, and the return dict exactly as-is.

Rewrite the new-bookmark branch of `import_json` to delegate. import_json keeps its skip-existing semantics (it must NOT upsert existing ids — it counts them as `skipped`), so it filters to genuinely-new items FIRST, reparents unknown categories to default, then upserts only those new items with `stamp_now=True, enrich_force=False` (import_json never re-resolves geo with force). Replace the current per-bookmark for-loop body (`now = _now_iso(); existing_bm_ids = ...; imported = 0; skipped = 0; for bm in incoming.bookmarks: ...`) with:

```python
        existing_bm_ids = {b.id for b in self.store.bookmarks}
        new_items = [bm for bm in incoming.bookmarks if bm.id not in existing_bm_ids]
        skipped = len(incoming.bookmarks) - len(new_items)
        for bm in new_items:
            if bm.category_id not in existing_cat_ids:
                bm.category_id = "default"
        imported, _ = self._upsert_items(new_items, stamp_now=True, enrich_force=False)
```

Keep `if imported: self._save()`, the logging line, and the `{"imported": imported, "skipped": skipped}` return shape unchanged. (The category-append loop above the bookmark loop — which builds `existing_cat_ids` — stays as-is.) Carve ONE seam (the bookmark upsert) — categories stay in their existing per-method loops.

- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_upsert_items_unify.py tests/test_force_seed.py tests/test_import_json_resurrect.py tests/test_bookmark_import_formats.py -v` (all PASS, byte-for-byte), then `cd backend && .venv/bin/python -m pytest -q` (baseline 941 + this task's new test file = re-pin the collected count before asserting; all green).

- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken` (no new cross-ring edge; `_upsert_items` lives in services and imports only domain `force_seed_items` + the module-local `enrich_bookmark` helper).

- [ ] **Step 6: Commit** — `git add backend/services/bookmarks.py backend/tests/test_upsert_items_unify.py` then `git commit -m "refactor(bookmarks): unify import_json/import_catalog/force_seed via _upsert_items (stamp_now param)"`


---

### Task 10: Extract FileWatchBinding helper; rebind BookmarkManager + RouteManager watcher state machine onto it

**Files:**
- Create: `backend/services/file_watch_binding.py`
- Modify: `backend/services/route_store.py` (the watcher block — `start_watcher`/`stop_watcher`/`_schedule_reconcile`, the inner `_Handler`, the `self._watch`/`self._watcher_debounce_timer` fields; locate by content), `backend/services/bookmarks.py` (same watcher block)
- Test: `backend/tests/test_file_watch_binding.py` (new)

**Interfaces:**
- Consumes: `services.file_watcher.schedule(handler, path) -> ObservedWatch` (imported in both managers as `schedule as _watcher_schedule`), `services.file_watcher.unschedule(watch)`
- Produces: `services.file_watch_binding.FileWatchBinding(path_accessor: Callable[[], Path], on_reconcile: Callable[[], None], *, debounce_s: float = 0.5)` with methods `.start() -> None`, `.stop() -> None`. `path_accessor` is called fresh on every fs event (so a rebind/path change is honoured). `on_reconcile` is the manager's own `_watcher_tick` injected as a callback — the binding owns ONLY the watchdog plumbing + the `threading.Timer(0.5)` debounce, never the merge/mtime logic.

- [ ] **Step 1: Write the CHARACTERIZATION test** — pins the CURRENT external-modification → callback behavior of BOTH managers against REAL watchdog + real disk + real debounce (no stubbed handler). Mirror `test_route_watcher.py` exactly, including its autouse `file_watcher.shutdown()` teardown and the `os.utime(..., time.time()+1.0)` future-mtime trick. The autouse fixture monkeypatches the same paths `test_route_watcher.py` does (`config.DATA_DIR`, `config.SETTINGS_FILE`, `config.ROUTES_FILE`, `config._DEFAULT_BOOKMARKS_FILE`, `services.bookmarks.BOOKMARKS_FILE`, `services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE`).

```python
"""Characterization for the extracted FileWatchBinding: external file mods on
BOTH the bookmark and route files still fire each manager's on_change after a
0.5s debounce; self-writes do NOT fire. Pins CURRENT behavior with real watchdog
+ real disk before/after the carve."""
import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    yield
    from services.file_watcher import shutdown as _shutdown
    _shutdown()


def _wait_for(predicate, timeout=3.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _write_routes(p: Path, route_id: str) -> None:
    p.write_text(json.dumps({
        "categories": [{"id": "default", "name": "預設", "color": "#6c8cff",
                        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00"}],
        "routes": [{"id": route_id, "name": route_id, "category_id": "default",
                    "profile": "walking", "waypoints": [{"lat": 1.0, "lng": 1.0}],
                    "created_at": "2026-05-12T00:00:00+00:00"}],
    }))


def _write_bookmarks(p: Path, bm_id: str) -> None:
    p.write_text(json.dumps({
        "categories": [{"id": "default", "name": "預設", "color": "#6c8cff",
                        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00"}],
        "bookmarks": [{"id": bm_id, "name": bm_id, "lat": 1.0, "lng": 2.0,
                       "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
                       "last_used_at": "", "updated_at": "2026-05-12T00:00:00+00:00"}],
    }))


def test_route_external_mod_fires_callback(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "initial")
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        _write_routes(routes_file, "external")
        nm = time.time() + 1.0
        os.utime(routes_file, (nm, nm))
        assert _wait_for(lambda: bool(fired)), "route callback never fired"
        assert rm.list_routes()[0].id == "external"
    finally:
        rm.stop_watcher()


def test_bookmark_external_mod_fires_callback(tmp_path):
    bm_file = tmp_path / "bookmarks.json"
    _write_bookmarks(bm_file, "b-initial")
    from bootstrap.factories import make_bookmark_manager
    bm = make_bookmark_manager()
    fired: list[None] = []
    bm.start_watcher(lambda: fired.append(None))
    try:
        _write_bookmarks(bm_file, "b-external")
        nm = time.time() + 1.0
        os.utime(bm_file, (nm, nm))
        assert _wait_for(lambda: any(b.id == "b-external" for b in bm.list_bookmarks())), \
            "bookmark external change never reconciled"
    finally:
        bm.stop_watcher()


def test_self_write_does_not_fire(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "r0")
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        rm.create_category(name="from-self")
        time.sleep(1.0)
        assert not fired, "self-write must not fire external-change callback"
    finally:
        rm.stop_watcher()


def test_stop_watcher_idempotent(tmp_path):
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    rm.stop_watcher()
    rm.start_watcher(lambda: None)
    rm.stop_watcher()
    rm.stop_watcher()
```

(`list_bookmarks` exists on BookmarkManager; if a given build does not expose it, assert via `bm.store.bookmarks` instead — verify the accessor name when writing the test.)

- [ ] **Step 2: Run it, verify it PASSES on current code** — `cd backend && .venv/bin/python -m pytest tests/test_file_watch_binding.py tests/test_route_watcher.py -v` → all PASS on the un-refactored managers (characterization mode; the watcher already works).

- [ ] **Step 3: Refactor (behavior-preserving)** — create the helper, then carve ONE manager at a time (route first — it has no `_store_lock`, so it is the simpler seam). Create `backend/services/file_watch_binding.py`:

```python
"""Shared file-watcher binding: the start/stop/debounce state machine that
BookmarkManager and RouteManager duplicated.

Owns ONLY the watchdog plumbing (schedule/unschedule on the shared Observer)
and the threading.Timer(0.5) debounce. It does NOT own merge/mtime/reconcile
logic — that stays on each manager, injected here as the ``on_reconcile``
callback (the manager's own _watcher_tick). path_accessor is called fresh on
every fs event so a path rebind (cloud-sync folder change) is honoured.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers.api import ObservedWatch

from services.file_watcher import schedule as _schedule, unschedule as _unschedule

logger = logging.getLogger(__name__)


class FileWatchBinding:
    def __init__(
        self,
        path_accessor: Callable[[], Path],
        on_reconcile: Callable[[], None],
        *,
        debounce_s: float = 0.5,
    ) -> None:
        self._path_accessor = path_accessor
        self._on_reconcile = on_reconcile
        self._debounce_s = debounce_s
        self._watch: ObservedWatch | None = None
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        self.stop()
        path = self._path_accessor()
        parent = path.parent
        if not parent.exists():
            logger.warning("Watch folder does not exist; watcher not started: %s", parent)
            return
        binding = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path) != binding._path_accessor():
                    return
                binding._schedule()

            on_created = on_modified

            def on_moved(self, event):
                if event.is_directory:
                    return
                target = binding._path_accessor()
                if Path(event.src_path) != target and Path(getattr(event, "dest_path", "")) != target:
                    return
                binding._schedule()

        self._watch = _schedule(_Handler(), parent)
        logger.info("Watcher scheduled on %s", parent)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._watch is not None:
            _unschedule(self._watch)
            self._watch = None

    def _schedule(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce_s, self._on_reconcile)
        self._timer.daemon = True
        self._timer.start()
```

In `RouteManager.__init__`, replace the three fields `self._watch`, `self._watcher_debounce_timer`, `self._on_external_change` with `self._watch_binding: FileWatchBinding | None = None` PLUS keep `self._on_external_change: Callable[[], None] | None = None` (still set in start_watcher, still fired inside `_watcher_tick`). Add `from services.file_watch_binding import FileWatchBinding` at module top. Replace `start_watcher` / `stop_watcher` / `_schedule_reconcile` with:

```python
    def start_watcher(self, on_change: Callable[[], None]) -> None:
        """ ... keep existing docstring ... """
        self.stop_watcher()
        self._on_external_change = on_change
        self._watch_binding = FileWatchBinding(self._routes_path, self._watcher_tick)
        self._watch_binding.start()

    def stop_watcher(self) -> None:
        if self._watch_binding is not None:
            self._watch_binding.stop()
            self._watch_binding = None
```

Delete the now-dead inner `_Handler` and `_schedule_reconcile`. `_watcher_tick` is UNCHANGED (it still does the mtime guard + `merge_stores` + `_last_loaded_mtime` update + `self._on_external_change()` callback). Then repeat the identical carve for `BookmarkManager` — its `_watcher_tick` (which holds `_store_lock` and calls `self._repo.save`) stays byte-for-byte unchanged; only `start_watcher`/`stop_watcher`/`_schedule_reconcile`/`_Handler` and the `self._watch`/`self._watcher_debounce_timer` fields are removed in favour of the binding. Keep `_bookmarks_path` / `_routes_path` accessors (the binding's `path_accessor`).

- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_file_watch_binding.py tests/test_route_watcher.py tests/test_bookmarks_thread_race.py -v` (watcher + the real-thread race stress test all PASS), then `cd backend && .venv/bin/python -m pytest -q` (all green; the FUTURE-MAINTAINER NOTE at bookmarks.py ~line 124 warns the Timer thread-affinity is load-bearing — this carve keeps `_watcher_tick` on the Timer daemon thread, so the invariant holds).

- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken` (the new `services.file_watch_binding` imports only `services.file_watcher` + stdlib + watchdog — stays inside the services ring; no new cross-ring edge, no new contract).

- [ ] **Step 6: Commit** — `git add backend/services/file_watch_binding.py backend/services/route_store.py backend/services/bookmarks.py backend/tests/test_file_watch_binding.py` then `git commit -m "refactor(watcher): extract FileWatchBinding shared by Bookmark/Route managers (dedup ~80 lines)"`


---

### Task 11: Add public AppState accessors for settings privates; route location.py + bookmarks.py controllers through them

**Files:**
- Modify: `backend/main.py` (AppState — add public methods near `save_settings`/`get_initial_position`; locate by content. NOTE: an existing `get_initial_position()` already exists and returns the `_last_position`/DEFAULT_LOCATION map-default — a DIFFERENT concept; do NOT touch it. The new accessor is named `get_initial_map_position()` to avoid the collision)
- Modify: `backend/api/location.py` (the `/settings/initial-position` GET+PUT handlers reading/writing `registry._initial_map_position` + `registry.save_settings()`, and the `action_udid = ... or registry._primary_udid` reads in `teleport`/`restore`/`goldditto_cycle`; locate by content)
- Modify: `backend/api/bookmarks.py` (the `/ui-state` GET+POST handlers touching `registry._bookmark_expanded_categories`/`_bookmark_hidden_categories` + `save_settings`)
- Test: `backend/tests/test_appstate_public_accessors.py` (new)

**Interfaces:**
- Consumes: none
- Produces: on `AppState`: `get_primary_udid() -> str | None`; `get_initial_map_position() -> dict | None`; `set_initial_map_position(pos: dict | None) -> None` (persists via save_settings); `get_bookmark_ui_state() -> dict` returning `{"expanded_categories": list[str] | None, "hidden_categories": list[str] | None}`; `set_bookmark_ui_state(*, expanded: list[str] | None = None, hidden: list[str] | None = None) -> None` (per-field, persists). Controllers call these instead of touching privates.

- [ ] **Step 1: Write the CHARACTERIZATION test** — pins CURRENT HTTP behavior of the four affected endpoints (GET/PUT initial-position, GET/POST bookmarks ui-state) end-to-end through a real TestClient + real AppState, asserting exact JSON. Build the TestClient over `main.app` like `test_geocode_api.py`. The deep-equal JSON assertions are the behavior freeze. The fixture resets the persisted UI fields on the LIVE `main.app_state` (do NOT rebind the module-level `app_state` — `test_lifespan.py`/`test_appstate_sync_migration.py` bind it at import time).

```python
"""Characterization: initial-position + bookmark ui-state endpoints return the
exact JSON before/after AppState gains public accessors. Behavior freeze."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")
    import main
    # Reset the persisted UI fields on the live app_state (do NOT rebind the
    # module-level app_state — other test files bind it at import time).
    main.app_state._initial_map_position = None
    main.app_state._bookmark_expanded_categories = None
    main.app_state._bookmark_hidden_categories = None
    return TestClient(main.app)


def test_initial_position_roundtrip(client):
    assert client.get("/api/location/settings/initial-position").json() == {"position": None}
    r = client.put("/api/location/settings/initial-position", json={"lat": 25.0, "lng": 121.5})
    assert r.status_code == 200
    assert r.json() == {"position": {"lat": 25.0, "lng": 121.5}}
    assert client.get("/api/location/settings/initial-position").json() == {
        "position": {"lat": 25.0, "lng": 121.5}
    }
    # Clear with null lat/lng.
    r = client.put("/api/location/settings/initial-position", json={"lat": None, "lng": None})
    assert r.json() == {"position": None}


def test_initial_position_rejects_out_of_range(client):
    r = client.put("/api/location/settings/initial-position", json={"lat": 200.0, "lng": 0.0})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_coord"


def test_bookmark_ui_state_per_field_update(client):
    assert client.get("/api/bookmarks/ui-state").json() == {
        "expanded_categories": None, "hidden_categories": None
    }
    # POST only expanded -> hidden stays None.
    r = client.post("/api/bookmarks/ui-state", json={"expanded_categories": ["a", "b"]})
    assert r.json() == {"status": "ok", "expanded_categories": ["a", "b"], "hidden_categories": None}
    # POST only hidden -> expanded unchanged (per-field, no clobber).
    r = client.post("/api/bookmarks/ui-state", json={"hidden_categories": ["c"]})
    assert r.json() == {"status": "ok", "expanded_categories": ["a", "b"], "hidden_categories": ["c"]}
    assert client.get("/api/bookmarks/ui-state").json() == {
        "expanded_categories": ["a", "b"], "hidden_categories": ["c"]
    }
```

- [ ] **Step 2: Run it, verify it PASSES on current code** — `cd backend && .venv/bin/python -m pytest tests/test_appstate_public_accessors.py -v` → PASS on the un-refactored controllers (pins the current private-touching behavior).

- [ ] **Step 3: Refactor (behavior-preserving)** — add the public methods on `AppState` (next to `save_settings`), each a thin wrapper around the existing privates so on-disk + in-memory behavior is identical:

```python
    def get_primary_udid(self) -> str | None:
        return self._primary_udid

    def get_initial_map_position(self) -> dict | None:
        return self._initial_map_position

    def set_initial_map_position(self, pos: dict | None) -> None:
        self._initial_map_position = pos
        self.save_settings()

    def get_bookmark_ui_state(self) -> dict:
        return {
            "expanded_categories": self._bookmark_expanded_categories,
            "hidden_categories": self._bookmark_hidden_categories,
        }

    def set_bookmark_ui_state(self, *, expanded: list[str] | None = None,
                              hidden: list[str] | None = None) -> None:
        # Per-field: only touch a field whose value is not None, mirroring the
        # frontend's independent expand/hide persistence.
        if expanded is not None:
            self._bookmark_expanded_categories = list(expanded)
        if hidden is not None:
            self._bookmark_hidden_categories = list(hidden)
        self.save_settings()
```

In `api/location.py` rewrite the two initial-position handlers. The current GET reads `registry._initial_map_position` and the PUT validates + assigns `registry._initial_map_position` then calls `registry.save_settings()`. The validation + `None` semantics stay in the controller (it raises HTTP 400); only the read/assign/persist moves behind the accessors:

```python
@router.get("/settings/initial-position", tags=["settings"])
async def get_initial_position(registry=Depends(get_engine_registry)):
    return {"position": registry.get_initial_map_position()}


@router.put("/settings/initial-position", tags=["settings"])
async def set_initial_position(req: _InitialPosRequest, registry=Depends(get_engine_registry)):
    """ ... keep the existing docstring ... """
    if req.lat is None or req.lng is None:
        registry.set_initial_map_position(None)
    else:
        if not (-90 <= req.lat <= 90) or not (-180 <= req.lng <= 180):
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_coord", "message": "lat must be in [-90, 90], lng in [-180, 180]"},
            )
        registry.set_initial_map_position({"lat": float(req.lat), "lng": float(req.lng)})
    return {"position": registry.get_initial_map_position()}
```

Note: the FastAPI handler name `get_initial_position` (the route) collides in NAME with AppState's existing `get_initial_position()` method, but they live in different modules — leave the route function name as-is; only the AppState side uses the new `get_initial_map_position`. For the `registry._primary_udid` reads in location.py (`action_udid = getattr(req, "udid", None) or registry._primary_udid` in `teleport`; `action_udid = udid or registry._primary_udid` in `restore`; `action_udid = req.udid or registry._primary_udid` in `goldditto_cycle`), replace each `registry._primary_udid` with `registry.get_primary_udid()`. Leave the simulation-engine fan-out (`registry.simulation_engines`, the watchdog's `_primary_udid` leader-promotion in main.py, `dm._connections`) UNCHANGED — A6 only covers the settings privates + the controller-side `_primary_udid` reads, not the registry/watchdog internals. In `api/bookmarks.py` rewrite the two `/ui-state` handlers:

```python
@router.get("/ui-state")
async def get_bookmark_ui_state(registry=Depends(get_engine_registry)):
    return registry.get_bookmark_ui_state()


@router.post("/ui-state")
async def set_bookmark_ui_state(req: BookmarkUiState, registry=Depends(get_engine_registry)):
    registry.set_bookmark_ui_state(
        expanded=req.expanded_categories, hidden=req.hidden_categories
    )
    return {"status": "ok", **registry.get_bookmark_ui_state()}
```

The current POST returns `{"status": "ok", "expanded_categories": ..., "hidden_categories": ...}`; `get_bookmark_ui_state()` returns exactly `{"expanded_categories", "hidden_categories"}`, so `{"status": "ok", **...}` is byte-identical (verified key-by-key). Confirm against the characterization test.

- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_appstate_public_accessors.py -v` (still PASS, behavior unchanged), then `cd backend && .venv/bin/python -m pytest -q` (baseline 941 + this task's new test file; all green).

- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken` (no import change — only method calls; controllers already import `get_engine_registry` from `api.deps`).

- [ ] **Step 6: Commit** — `git add backend/main.py backend/api/location.py backend/api/bookmarks.py backend/tests/test_appstate_public_accessors.py` then `git commit -m "refactor(api): route initial-position + bookmark ui-state controllers through public AppState accessors"`


---

### Task 12: Pin Container lazy-manager delegation; characterize 503-before-load_state and post-load_state liveness

**Files:**
- Modify: `backend/bootstrap/container.py` (the `bookmark_manager`/`route_manager` properties — tighten the docstring/intent; locate by content)
- Test: `backend/tests/test_container_lazy_manager_delegation.py` (new)

**Interfaces:**
- Consumes: `bootstrap.container.Container(...)`, `api.deps.get_bookmark_manager(request) -> manager | raises HTTPException(503)`
- Produces: none (behavior-preserving tightening of the property)

- [ ] **Step 1: Write the CHARACTERIZATION test** — the Container is built at IMPORT time (main.py module load) while `app_state.bookmark_manager` is still None (set later in `load_state()`); the `@property` delegates LIVE to `engine_registry`, and the 503 guard in `api/deps.py` covers the None window. Pin all three facts with REAL collaborators (a real Container wrapping a SimpleNamespace registry, the real `api.deps` providers — no stubbing of the property under test). The Container constructor builds a `DeviceService` internally, which only stores the passed refs (no attribute access at construction), so SimpleNamespace stand-ins are safe.

```python
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
```

- [ ] **Step 2: Run it, verify it PASSES on current code** — `cd backend && .venv/bin/python -m pytest tests/test_container_lazy_manager_delegation.py tests/test_bootstrap_container.py tests/test_deps_providers.py -v` → PASS on the current property (it already delegates via the `hasattr` guard; the test characterizes that the existing build-at-import + live-delegation + 503-guard works correctly, satisfying A22).

- [ ] **Step 3: Refactor (behavior-preserving)** — A22's resolution is the minimal doc/intent tightening that pins the build-before-load_state + live-delegation contract WITHOUT changing branch outcomes. The current `bookmark_manager` property is:

```python
    @property
    def bookmark_manager(self):
        """Live read from engine_registry so post-load_state() manager is returned."""
        if self.engine_registry is not None and hasattr(self.engine_registry, "bookmark_manager"):
            return self.engine_registry.bookmark_manager
        return self._bookmark_manager
```

The `_bookmark_manager`/`_route_manager` fallback is ONLY exercised by `test_container_accepts_injected_singletons` (passes `_FakeEngineReg` — a bare class with NO `bookmark_manager` attribute → the `hasattr` is False → returns the None fallback). With a real AppState the attribute always exists, so the fallback is dead in production. Keep the branch logic IDENTICAL (so that `_FakeEngineReg` test stays green) and only tighten the docstring to pin the contract:

```python
    @property
    def bookmark_manager(self):
        """Live read from engine_registry so the manager built inside
        load_state() (AFTER this Container is constructed at import time) is
        returned without rebuilding the Container. The _bookmark_manager
        fallback is ONLY for unit tests that inject a bare fake registry with
        no bookmark_manager attribute; in production engine_registry is the
        AppState and always carries it (None until load_state, real after).
        The 503 guard in api.deps.get_bookmark_manager covers the None window."""
        reg = self.engine_registry
        if reg is not None and hasattr(reg, "bookmark_manager"):
            return reg.bookmark_manager
        return self._bookmark_manager
```

Apply the identical doc-tightening to `route_manager`. This is a documentation-and-intent carve (branch logic unchanged so all existing container tests stay green); it formally resolves A22 by pinning the build-after-load_state contract in code + test rather than altering wiring. Do NOT move the Container build later in main.py — `test_appstate_sync_migration.py` documents that `test_lifespan.py` binds `app_state`/`helper_client` at module import time, and rebinding/reordering risks running the real 90s helper handshake.

- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_container_lazy_manager_delegation.py tests/test_bootstrap_container.py tests/test_deps_providers.py -v` (all PASS), then `cd backend && .venv/bin/python -m pytest -q` (baseline 941 + this task's new test file; all green).

- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → `7 kept, 0 broken` (no import change in container.py).

- [ ] **Step 6: Commit** — `git add backend/bootstrap/container.py backend/tests/test_container_lazy_manager_delegation.py` then `git commit -m "refactor(bootstrap): pin Container lazy-manager live-delegation contract (build-before-load_state)"`


---

### Task 13: api/geocode.py: inject GeocodingService via Depends(get_geocoding_service); delete module-level instance

**Files:**
- Modify: `backend/api/geocode.py` (delete the module-level `geocoding_service = GeocodingService()` at line ~30; switch `from fastapi import APIRouter, HTTPException` to add `Depends`; add `from api.deps import get_geocoding_service`; drop the now-unused `from services.geocoding import GeocodingService`; add `Depends(get_geocoding_service)` to `search_address` + `reverse_geocode`; locate by content)
- Modify: `backend/tests/test_geocode_api.py` (the THREE tests that `monkeypatch.setattr(geo_api.geocoding_service, "reverse", ...)` — lines ~24, ~54, ~109 — must monkeypatch the container's service instead; locate by content)
- Modify: `backend/.importlinter` (add `api.geocode -> api.deps` to the `ignore_imports` of `[importlinter:contract:no-api-imports-api]`)
- Test: `backend/tests/test_geocode_api.py` (existing — updated, +1 new test)

**Interfaces:**
- Consumes: `api.deps.get_geocoding_service(request) -> GeocodingService` (resolves `request.app.state.container.geocoding_service`)
- Produces: none

- [ ] **Step 1: Write the CHARACTERIZATION test** — the existing `test_geocode_api.py` suite IS the characterization (it pins the reverse-fallback-to-offline, timezone, and happy-path HTTP behavior). It must STILL pass after switching to DI (the monkeypatch target changes from the module-level instance to the container's instance, but the asserted HTTP responses are byte-identical). Add ONE new regression test asserting the module-level attribute is gone and the endpoint resolves the container's service. The `client` fixture is `import main; return TestClient(main.app)`:

```python
def test_geocode_uses_container_service_not_module_level(monkeypatch, client):
    """After DI: api.geocode has no module-level geocoding_service; the endpoint
    resolves the container's instance. Monkeypatching the container's reverse
    drives the offline fallback path identically to the old module-level seam."""
    import api.geocode as geo_api
    import services.geo_offline as geo_offline
    import main

    assert not hasattr(geo_api, "geocoding_service"), (
        "module-level GeocodingService must be deleted; service comes from the container"
    )

    async def boom(_lat, _lng):
        raise RuntimeError("simulated Nominatim outage")

    monkeypatch.setattr(main.app.state.container.geocoding_service, "reverse", boom)
    monkeypatch.setattr(
        geo_offline, "resolve", lambda _lat, _lng: ("jp", "Asia/Tokyo", "Tokyo", "Tokyo")
    )
    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    assert res.json()["country_code"] == "jp"
```

- [ ] **Step 2: Run it, verify it PASSES on current code** — the NEW test FAILS on current code (mode: new-assertion — `hasattr(geo_api, "geocoding_service")` is True today, and the container service is not yet wired into the endpoints). The EXISTING 5 tests PASS. Run `cd backend && .venv/bin/python -m pytest tests/test_geocode_api.py -v` → existing 5 PASS, new 1 FAILS until Step 3.

- [ ] **Step 3: Refactor (behavior-preserving)** — in `api/geocode.py`: change the fastapi import to `from fastapi import APIRouter, Depends, HTTPException`, add `from api.deps import get_geocoding_service`, delete the line `geocoding_service = GeocodingService()` (line ~30) AND the now-unused `from services.geocoding import GeocodingService` import (line ~17). Update the two endpoints that use it:

```python
@router.get("/search", response_model=list[GeocodingResult])
async def search_address(
    q: str,
    limit: int = 5,
    provider: str = "nominatim",
    google_key: str | None = None,
    geocoding_service=Depends(get_geocoding_service),
):
    """ ... keep docstring ... """
    try:
        return await geocoding_service.search(q, limit, provider, google_key)
    except GeocodeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/reverse", response_model=GeocodingResult | None)
async def reverse_geocode(lat: float, lng: float, geocoding_service=Depends(get_geocoding_service)):
    """ ... keep docstring ... """
    try:
        result = await geocoding_service.reverse(lat, lng)
        if result is not None:
            return result
    except Exception:
        logger.exception("Nominatim reverse failed; falling back to offline")
    # ... rest of the offline-fallback body (geo_offline.resolve + GeocodingResult) UNCHANGED
```

The `timezone_lookup`, `real_location`, `route_optimize` endpoints do not use `geocoding_service`, so they are untouched. Then update the THREE existing tests in `test_geocode_api.py` that do `monkeypatch.setattr(geo_api.geocoding_service, "reverse", boom)` / `..., "reverse", ok)` — change the target to the container's instance: `monkeypatch.setattr(main.app.state.container.geocoding_service, "reverse", boom)` (add `import main` inside each of those three test bodies). The `api.deps.get_geocoding_service` returns `request.app.state.container.geocoding_service`, so monkeypatching that single instance reaches the endpoint. The asserted HTTP responses are unchanged.

- [ ] **Step 4: Run the characterization test + the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_geocode_api.py -v` (all 6 now PASS — existing behavior frozen, new regression green; the file grows from 5 to 6 tests, so the suite total is baseline 941 + 1 = 942), then `cd backend && .venv/bin/python -m pytest -q` (all green; re-pin the collected count).

- [ ] **Step 5: Gate** — `cd backend && .venv/bin/lint-imports` → MUST be `7 kept, 0 broken`. The `no-api-imports-api` independence contract's `ignore_imports` block currently lists `api.bookmarks/device/cloud_sync/location/phone_control/route -> api.deps` but NOT `api.geocode -> api.deps`. Adding `from api.deps import get_geocoding_service` creates a new `api.geocode -> api.deps` edge that the contract will flag as BROKEN. Add the line `    api.geocode -> api.deps` to the `ignore_imports` of `[importlinter:contract:no-api-imports-api]` in `backend/.importlinter` in the SAME commit (the contract already has `unmatched_ignore_imports_alerting = none`, so ordering of the ignore list is unconstrained), then re-run lint-imports to confirm `7 kept, 0 broken`.

- [ ] **Step 6: Commit** — `git add backend/api/geocode.py backend/tests/test_geocode_api.py backend/.importlinter` then `git commit -m "refactor(geocode): inject GeocodingService via Depends; drop module-level instance + whitelist api.geocode->api.deps"`


---


<!-- ===== S4 · Frontend re-render reduction (Profiler-gated) ===== -->

### Task 14: Memo ControlPanel + MapView and stabilize their App-side prop sources (one coherent commit)

**Files:**
- Create: `frontend/src/App.renderCount.test.tsx`
- Modify: `frontend/src/components/ControlPanel.tsx` (component `const ControlPanel: React.FC<ControlPanelProps> = ({ ... }) => { ... }` at L276; `export default ControlPanel;` at L1064; React namespace already imported at L1: `import React, { useState, useEffect } from 'react';`)
- Modify: `frontend/src/components/MapView.tsx` (component `const MapView: React.FC<MapViewProps> = ({ ... }) => { ... }` at L265; `export default MapView;` at L911. NOTE: `export function TransportButtons(...)` at L149 is a SEPARATE named export — do NOT wrap it. React namespace already imported at L1: `import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';`)
- Modify: `frontend/src/App.tsx` (derived-prop block: `currentPos` L807-809, `destPos` L811-813; the `<ControlPanel .../>` JSX L945-1187; the `<MapView .../>` JSX L1350-1396. App already imports `useMemo` at L1 and already memoizes `bookmarkPins` L840-851 + `categoryDatesByName` L95-103)
- Test: `frontend/src/App.renderCount.test.tsx`

**Interfaces:**
- Consumes: `createWsRouter`, `type WsRouterImpl` from `./adapters/ws/router` (real router exposing `.dispatch(e: WsEvent)`); `ServicesProvider` from `./contexts/ServicesContext` (`value={{ api, ws, sendMessage, connected }}`); `I18nProvider` from `./i18n`; `* as api` from `./services/api`; `App` default export from `./App` (NOTE: the default export is `AppRoot`, which wraps the inner `App` in `CloudSyncBusyProvider`; `import App from './App'` binds to it exactly as `App.smoke.test.tsx` L66 does). Copy the `renderApp` harness + the `vi.mock('./services/api', ...)` importOriginal block + the `localStorage.setItem('locwarp.lang','en')` beforeEach VERBATIM from `App.smoke.test.tsx` (L33-93).
- Produces: `ControlPanel` and `MapView` default exports become `React.memo`-wrapped (prop interfaces `ControlPanelProps` / `MapViewProps` FROZEN — no prop renames, no shape change). No new public symbols. Set `.displayName` on each memo.

**Why this is ONE task and must NOT be split:** a `React.memo`'d child still re-renders whenever ANY prop it receives is a fresh reference each parent render. App currently hands ControlPanel/MapView freshly-allocated object literals (`currentPos`/`destPos` rebuilt every render at L807-813, `sim.waypoints.map((w,i)=>({...w,index:i}))` at L1355, inline arrow handlers like `onAddressSelect` L974, `onBookmarkClick` L1010, the giant `onBookmarkEdit` L1028, `onCategoryAdd` L1053, etc.) and freshly-mapped arrays (`bookmarks={bm.bookmarks.map(...)}` L987, `bookmarksRaw`/`bookmarkCategoriesFull`/`bookmarkCategoryColors`/`bookmarkCategories` at L1000-1009). Wrapping the children in `React.memo` WITHOUT first stabilizing those parent-side prop sources is a no-op (the memo's shallow-compare always sees new refs). Conversely, memoizing the prop sources without `React.memo` on the child does nothing either. They are two halves of one fix and must land in the same commit.

- [ ] **Step 1: Write the CHARACTERIZATION test** — render-count probe that PINS the CURRENT (high) commit count per `position_update` tick.

  **CRITICAL harness detail (do NOT copy the plain-stub pattern from `App.dangerzone.test.tsx`/`App.smoke.test.tsx` here):** because the test `vi.mock`s `./components/ControlPanel` and `./components/MapView`, the REAL `React.memo` wrappers added in Step 3 are replaced by the mock and are NEVER exercised by this test. A PLAIN (non-memo) stub re-renders on EVERY App re-render regardless of prop stability, so the counts would equal the App-re-render count BEFORE AND AFTER the refactor — the test could never show a drop and would not characterize the seam. To make the probe measure the EXACT invariant the refactor establishes (prop-reference stability), the stub children themselves MUST be wrapped in `React.memo`. A memo'd stub is structurally identical to the real memo'd component for shallow-compare purposes, so the counter then measures whether App hands stable prop refs — which is precisely what Step 3 fixes. Create `frontend/src/App.renderCount.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act } from '@testing-library/react'

// Commit counters mutated from inside the stubbed children's render bodies.
const counts = { control: 0, map: 0 }

// MapView pulls Leaflet/MapLibre (no WebGL in jsdom). Stub to a render-nothing
// component that bumps a commit counter. CRITICAL: wrap the stub in React.memo
// so its shallow prop-compare is what we measure — that mirrors the real
// component's memo wrapper (which vi.mock would otherwise shadow) and turns
// the counter into a prop-reference-stability probe, the exact seam under test.
// forwardRef so App's onMapReady/ref wiring still type-checks.
vi.mock('./components/MapView', () => {
  const MapViewStub = React.memo(React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    counts.map++
    return null
  }))
  ;(MapViewStub as any).displayName = 'MapViewStub'
  return { default: MapViewStub }
})

// ControlPanel is heavy. Stub to a memo'd counter for the same reason.
vi.mock('./components/ControlPanel', () => {
  const ControlPanelStub = React.memo(function ControlPanelStub(_props: any) {
    counts.control++
    return null
  })
  ;(ControlPanelStub as any).displayName = 'ControlPanelStub'
  return { default: ControlPanelStub }
})

// Same inert services/api mock the smoke test uses, copied verbatim.
vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'listDevices', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
    } else if (arrayReturning.has(key)) { out[key] = async () => [] }
    else if (nullReturning.has(key)) { out[key] = async () => null }
    else if (urlReturning.has(key)) { out[key] = () => '' }
    else { out[key] = async () => undefined }
  }
  return out
})

import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { createWsRouter, type WsRouterImpl } from './adapters/ws/router'
import * as api from './services/api'

function renderApp(router: WsRouterImpl, connected = true) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

beforeEach(() => {
  counts.control = 0
  counts.map = 0
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})
afterEach(() => { try { localStorage.clear() } catch { /* ignore */ } })

describe('App re-render count per position_update tick (characterization)', () => {
  it('pins the commit count for ControlPanel + MapView across N position_update frames', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Reset AFTER mount so we count only the steady-state ticks, not the
    // initial mount + the mount-effect flushes (status fetch, scan, etc.).
    counts.control = 0
    counts.map = 0

    const FRAMES = 5
    for (let i = 0; i < FRAMES; i++) {
      await act(async () => {
        // Single-device frame (NO udid) so it flows through the legacy
        // setters: useSimulation's position_update handler calls
        // setCurrentPosition + setProgress + setStatus (useSimulation.ts
        // L309-330) — the path that re-renders App on every tick.
        router.dispatch({
          type: 'position_update',
          lat: 25.03 + i * 1e-4,
          lng: 121.56 + i * 1e-4,
          progress: i / FRAMES,
          distance_remaining: 100 - i,
          distance_traveled: i,
        })
      })
    }

    // PIN the status quo. With the memo'd stubs above, the counters measure
    // PROP-REFERENCE STABILITY: on the un-refactored code App hands fresh
    // object/array/handler refs every render, so BOTH children commit every
    // frame. Run once, read the ACTUAL counts from the assertion diff, then
    // hard-code them. Replace the two literals below with the observed
    // BEFORE values from Step 2's first run.
    expect(counts.control).toBe(/* OBSERVED_CONTROL_COMMITS_BEFORE */ 5)
    expect(counts.map).toBe(/* OBSERVED_MAP_COMMITS_BEFORE */ 5)
  })
})
```

This is a true characterization probe: it drives REAL `position_update` frames through the REAL `createWsRouter` into the REAL `useSimulation` subscription, and the re-render TRIGGER (App's hook state + prop allocation) is the real code under test. The memo'd stub children are the measurement instrument — they record how often App's prop graph forces a child commit, which is exactly the invariant the refactor changes.

- [ ] **Step 2: Run it, verify it PASSES on current code** — `cd frontend && npx vitest run src/App.renderCount.test.tsx`. The FIRST run will likely fail on the placeholder literals; read the actual `counts.control` / `counts.map` from the assertion diff, substitute those observed BEFORE numbers into the two `expect(...).toBe(...)` lines, and re-run until GREEN. The test now PINS the current (HIGH) per-tick commit count. Record both numbers in the test's comment as the "before" baseline.

- [ ] **Step 3: Refactor (behavior-preserving) — memo + useMemo/useCallback together, in one edit.**

  (3a) `MapView.tsx`. Rename the inner arrow to `MapViewInner` and wrap. React namespace is already imported (L1), so `React.memo` is available with no import change:
  ```tsx
  const MapViewInner: React.FC<MapViewProps> = ({
    currentPosition,
    destination,
    waypoints,
    routePath,
    // ... (body UNCHANGED) ...
  }) => {
    // ...
  };

  const MapView = React.memo(MapViewInner);
  MapView.displayName = 'MapView';

  export default MapView;
  ```
  Leave `export function TransportButtons(...)` (L149) exactly as-is — MapView.test.tsx imports only that named export, so it is unaffected.

  (3b) `ControlPanel.tsx`. Same pattern. React namespace is already imported (L1):
  ```tsx
  const ControlPanelInner: React.FC<ControlPanelProps> = ({
    simMode,
    // ... (body UNCHANGED) ...
  }) => {
    // ...
  };

  const ControlPanel = React.memo(ControlPanelInner);
  ControlPanel.displayName = 'ControlPanel';

  export default ControlPanel;
  ```

  (3c) `App.tsx` — stabilize the prop sources the two memo'd children read. App already imports `useMemo` (L1) and already memoizes `bookmarkPins` (L840-851) + `categoryDatesByName` (L95-103) — follow that exact pattern. Replace the plain derived block at L807-813:
  ```tsx
  const currentPos = sim.currentPosition
    ? { lat: sim.currentPosition.lat, lng: sim.currentPosition.lng }
    : null

  const destPos = sim.destination
    ? { lat: sim.destination.lat, lng: sim.destination.lng }
    : null
  ```
  with:
  ```tsx
  const currentPos = useMemo(
    () => sim.currentPosition
      ? { lat: sim.currentPosition.lat, lng: sim.currentPosition.lng }
      : null,
    [sim.currentPosition],
  )

  const destPos = useMemo(
    () => sim.destination
      ? { lat: sim.destination.lat, lng: sim.destination.lng }
      : null,
    [sim.destination],
  )
  ```
  Hoist the inline arrays passed to ControlPanel into `useMemo`s mirroring the existing `bookmarkPins` memo: the `bookmarks={bm.bookmarks.map(...)}` (L987-999) keyed on `[bm.bookmarks, bm.categories, t]`; `bookmarkCategories={bm.categories.map(c => c.name)}` (L1000) keyed on `[bm.categories]`; `bookmarksRaw` (L1001-1007) keyed on `[bm.bookmarks]`; `bookmarkCategoriesFull` (L1008) keyed on `[bm.categories]`; `bookmarkCategoryColors` (L1009) keyed on `[bm.categories]`; also `savedRoutes={savedRoutes.map(...)}` (L1101-1109) keyed on `[savedRoutes]`, `goldDittoConnectedUdids` (L1141) keyed on `[device.connectedDevices]`, and `bookmarkExportUrl`/`routesExportAllUrl` (the `api.*Url()` calls L1100/L1114) hoisted to a `useMemo` keyed on `[api]`. Memoize the MapView `waypoints` prop (L1355) into `const waypointsForMap = useMemo(() => sim.waypoints.map((w, i) => ({ ...w, index: i })), [sim.waypoints])` and pass `waypoints={waypointsForMap}`. Wrap the remaining INLINE arrow handlers passed to ControlPanel/MapView (`onSpeedChange` L953, `onAddressSelect` L974, `onBookmarkClick` L1010, `onBookmarkAdd` L1016, `onBookmarkDelete` L1027, `onBookmarkEdit` L1028, `onCategoryAdd` L1053, `onCategoryDelete` L1065, `onCategoryEdit` L1074, `onCategoryDeleteCascade` L1149, `onBookmarkBulkPaste` L1095, `onRecentReFly` L1380, `onOpenLibrary` L1386, `onMapCenterChange` L1395, `onMapReady` L1375, `onBulkPasteOpen` L1394) into `useCallback`s with correct dep arrays — most deps (`bm`, `device`, `sim`, `t`, `showToast`, `pushRecent`, the clamp/normalize helpers, the already-`useCallback`'d `handleMapPanOnly`/`handleTeleport`/`handleNavigate`) are already stable. Do NOT change any handler BEHAVIOR — only wrap. Leave `isRunning` (L835), `isPaused` (L836), `speed` (L818), `displaySpeed` (L830) as plain primitives — primitives compare by value and do not defeat memo. This carves the ONE seam: stabilize the children's prop graph so a `position_update` tick (which mutates only `currentPosition`/`progress`/`status`, NOT the bookmark arrays / waypoints / handlers) short-circuits each child's `React.memo` shallow-compare.

- [ ] **Step 4: Run the characterization test + the broader suite.** Re-run the render-count test and read the NEW counts: `cd frontend && npx vitest run src/App.renderCount.test.tsx`. Because the stub children are memo'd, the counts now reflect the stabilized prop graph and should DROP: ControlPanel should fall to 0 commits across the 5 frames (none of its props change on a position tick), and MapView should commit only when `currentPosition` actually changes (so it tracks the position frames rather than every App render). UPDATE the two `expect(...).toBe(...)` literals to the new, LOWER observed values and record before→after in the comment (the test now pins the IMPROVED steady state and catches a regression that re-introduces unstable props). Then run the full frontend suite: `cd frontend && npx vitest run`. The 707 existing tests must stay GREEN (behavior identical — `App.smoke.test.tsx`, `App.dangerzone.test.tsx`, `ControlPanel.test.tsx`, `MapView.test.tsx`, `useSimActions.test.tsx`, `eventWiring.test.tsx` included); with the new file the runner should report 708. The memo wrappers must not change any rendered output, banner wiring, or event flow.

- [ ] **Step 5: Gate.** `cd frontend && npx tsc --noEmit && npx depcruise src` (the `depcruise` script in package.json runs `depcruise src --config .dependency-cruiser.cjs`) — both GREEN, no new cross-ring edge. memo/useMemo/useCallback are intra-`components`/`App` view-layer changes; confirm no new `import` of `adapters/` or `services/` was added so the hexagon-lite frontend layering stays untouched.

- [ ] **Step 6: Commit.** `git add frontend/src/App.tsx frontend/src/components/ControlPanel.tsx frontend/src/components/MapView.tsx frontend/src/App.renderCount.test.tsx` then:
```
perf(frontend): memo ControlPanel+MapView and stabilize their App prop sources

React.memo the two heavy children and wrap the App-side prop sources they
read (currentPos/destPos/waypoints/bookmark arrays + inline handlers) in
useMemo/useCallback so a position_update tick no longer forces a re-render
of the whole tree. memo without stable props (or vice versa) is a no-op, so
both halves land together. Behavior frozen; pinned by App.renderCount.test.tsx,
which measures prop-reference stability via memo'd stub children and records
the before->after commit-count drop. Deeper before/after is a manual React
Profiler 60s-sim smoke (RTL commit-counting is a proxy).
```

**Manual Profiler note (out of band, NOT a test step):** RTL commit-counting via memo'd stubs is a proxy for the real win. After merge, do a one-off manual React Profiler smoke — run a 60s simulation (Navigate or Loop) with the Profiler recording, and confirm the per-`position_update` commit fan-out shrank to App + the position-dependent layers only (ControlPanel and the static MapView shell should no longer commit on every GPS tick). This is the genuine before/after; the vitest test only guards against regression of the prop-stability invariant.


---

<!-- ===== Acceptance + manual smoke ===== -->

### Task 15: SH3 acceptance — full gate + behavior-unchanged smoke + Profiler

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-14
- Produces: none

- [ ] **Step 1: Full backend gate**

```bash
cd /Users/raviwu/personal/locwarp/backend
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest --collect-only -q | tail -1
.venv/bin/lint-imports
```
Expected: all green; collection grew from 941 by the characterization tests added; `lint-imports` = `7 kept, 0 broken` (no new cross-ring edge from any carve).

- [ ] **Step 2: Full frontend gate**

```bash
cd /Users/raviwu/personal/locwarp/frontend
npx tsc --noEmit
npx vitest run
npx depcruise src
```
Expected: tsc 0 errors; vitest all green (707 baseline + the N1 render-count test); depcruise 0 errors (no NEW warnings vs main).

- [ ] **Step 3: Manual smoke — behavior UNCHANGED** *(real iPhone for device paths)*

Because this is a refactor batch, the smoke is "everything works exactly as before". Run `cd frontend && npm run start`:
- A full route simulation end-to-end (positions, ETA, pause/resume, completion) — identical to before SH3.
- A teleport, a joystick session, a random walk — identical behavior.
- Dual-device: connect two iPhones, teleport B → B moves not A; disconnect one → only that one drops (recovery orchestration carve A4 preserved).
- Unplug + replug the USB cable mid-sim, and toggle WiFi → the watchdog recovers exactly as before (api/device.py carve A1 preserved); the `tunnel_lost`/`device_error` banners + reasons are unchanged.
- Import a bookmark + a route file (A3 store carve) → same import/resurrect/idempotency behavior as SH1.

- [ ] **Step 4: Manual smoke — N1 render reduction (React Profiler)**

With the React DevTools Profiler, record a 60s route simulation before vs after SH3 (or compare the N1 render-count test's asserted commit counts).
- Expected: **measurably fewer commits per `position_update` tick**; map pan/zoom during a sim feels at least as smooth (ideally smoother). Attach the before/after Profiler commit numbers as evidence. Behavior (positions, ETA) is identical.

**SH3 acceptance:** automated gate green (Steps 1-2) with all new characterization tests; behavior-unchanged smoke (Step 3) observed; N1 Profiler before/after evidence (Step 4). Any behavior difference at all is a FAILURE for this refactor batch.
