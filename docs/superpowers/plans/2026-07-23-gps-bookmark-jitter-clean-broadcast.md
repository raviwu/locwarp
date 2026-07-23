# GPS Bookmark Jitter — Clean-Broadcast Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop saved bookmarks (and the map blue-dot / UI) from inheriting anti-detection GPS jitter, by keeping the engine's live `current_position` and the `position_update` broadcast **pristine** while the jittered value still goes only to the device.

**Architecture:** The jitter that reaches the iPhone (`add_jitter` in `_move_along_route` + joystick) is realism the device *should* keep. The bug is that the same jittered value is written into `current_position` (the single source of truth) and broadcast over WebSocket, so the frontend "Bookmark Here" / library "+" save actions persist a drifted, full-precision coordinate. Fix: decouple "value pushed to device" (jittered) from "value recorded as live position + broadcast" (pristine) at the single `_set_position` choke point, threading an optional pristine `state_lat/state_lng` through `_push_with_retry`. All route movers (navigate/route-loop/multi-stop/random-walk) funnel through `_move_along_route`, so one loop covers them; joystick is the one independent second site.

**Tech Stack:** Python 3.11, asyncio, pytest / pytest-asyncio. Backend only — **no frontend change required** (it simply receives cleaner values).

## Global Constraints

- **Pytest baseline: 1180 tests collected** (`cd backend && .venv/bin/python -m pytest --collect-only -q`). Suite stays green after EVERY commit.
- **Behavior/API freeze applies to SHAPE, not this fix's values.** No WS/HTTP/IPC key added or removed. `position_update` keeps every key; only the `lat`/`lng` **values** change from jittered → pristine — that IS the intended fix. WS payloads elsewhere compared deep-equal JSON must stay unchanged.
- **Danger-zone-test-first:** `simulation_engine.py` + movers are danger-zone. Every production edit here lands **after** a failing test that pins the new behavior (TDD).
- **Backward compatibility is mandatory:** `_set_position(lat, lng)` and `_push_with_retry(lat, lng)` (no state arg) MUST behave exactly as today (`current_position == pushed`). This keeps `test_push_with_retry_char.py` and `test_engine_device_push.py` green.
- Import-linter (7 kept, 0 broken) + dependency-cruiser (0 errors) must stay green — this change adds no cross-ring import, so no contract is touched.
- Personal repo: direct commits to `main`, auto git identity (never pass `-c user.email`). Frequent commits, one per task.

## Design Decision Requiring Sign-off (group mode)

`services/group_sync_service.py:115-118` mirrors `primary_eng.current_position` onto follower devices. After this fix `current_position` is pristine, so **group followers sit on the pristine path while the leader device keeps jitter** (they'd be a few metres apart instead of pinned to the same jittered point).

- **Option A (recommended, default in this plan — zero extra code):** Accept it. Followers track the leader's *intended* path; the small leader/follower offset is arguably more realistic than all devices at one identical jittered point. No change to `group_sync_service.py`.
- **Option C (preserve exact current group behavior):** Add a `self._last_device_push: Coordinate | None` field set inside `_set_position` to the *pushed* (jittered) coord, and have `_follow_primary_positions` read that instead of `current_position`. ~4 lines. Implement only if Ravi wants byte-identical group-mode device behavior.

This plan implements **Option A**. Task 4 contains the Option-C variant, gated on Ravi's choice.

---

## File Structure

| File | Change |
|------|--------|
| `backend/core/simulation_engine.py` | Modify `_set_position` (590-593) + `_push_with_retry` (595-617): optional `state_lat/state_lng`. Modify `_move_along_route` (806-822): push jittered, record+broadcast pristine. |
| `backend/core/joystick.py` | Modify tick (100-116): keep `move_point` output pristine, push jittered, record+broadcast pristine. |
| `backend/tests/test_set_position_state_seam.py` | **Create.** Unit tests for the backward-compatible state seam. |
| `backend/tests/test_move_along_route_pristine_char.py` | **Create.** Char test: device gets jittered, `current_position` + `position_update` pristine. |
| `backend/tests/test_joystick_cov.py` | Modify: add a test asserting device jittered vs broadcast pristine (existing file, existing harness at 40-61). |
| `backend/services/group_sync_service.py` | **Option C only** — otherwise untouched. |

Movers `navigator.py` / `multi_stop.py` / `route_loop.py` / `random_walk.py` need **no change** — they delegate to `_move_along_route`, and their per-stop/per-lap emits already use pristine waypoint coords (`multi_stop.py:359`, `route_loop.py:383/424`). `teleport.py:35-41` is already pristine.

---

### Task 1: Backward-compatible state seam in `_set_position` / `_push_with_retry`

**Files:**
- Modify: `backend/core/simulation_engine.py:590-593` (`_set_position`), `:595-617` (`_push_with_retry`)
- Test: `backend/tests/test_set_position_state_seam.py` (create)

**Interfaces:**
- Produces: `async _set_position(lat, lng, state_lat: float | None = None, state_lng: float | None = None) -> None` — pushes `(lat, lng)` to the device; records `current_position` as `(state_lat or lat, state_lng or lng)`. `async _push_with_retry(lat, lng, state_lat=None, state_lng=None) -> bool` — same extra args, forwarded to `_set_position`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_set_position_state_seam.py`:

```python
"""The device-push value and the recorded live position can differ.

Backward compatible: with no state_* args, current_position == pushed (today's
behavior). With state_* args, the device gets (lat,lng) but current_position
records (state_lat, state_lng) — the seam the jitter fix relies on."""
from __future__ import annotations

import pytest

from tests._engine_harness import make_engine

pytestmark = pytest.mark.asyncio


async def test_set_position_default_records_pushed_value():
    eng, loc, _ = make_engine()
    await eng._set_position(10.0, 20.0)
    assert loc.pushes[-1] == (10.0, 20.0)
    assert (eng.current_position.lat, eng.current_position.lng) == (10.0, 20.0)


async def test_set_position_records_state_while_pushing_device_value():
    eng, loc, _ = make_engine()
    await eng._set_position(10.001, 20.001, state_lat=10.0, state_lng=20.0)
    # Device got the (jittered) push value...
    assert loc.pushes[-1] == (10.001, 20.001)
    # ...but the recorded live position is the pristine state value.
    assert (eng.current_position.lat, eng.current_position.lng) == (10.0, 20.0)


async def test_push_with_retry_forwards_state():
    eng, loc, _ = make_engine()
    ok = await eng._push_with_retry(10.001, 20.001, state_lat=10.0, state_lng=20.0)
    assert ok is True
    assert loc.pushes[-1] == (10.001, 20.001)
    assert (eng.current_position.lat, eng.current_position.lng) == (10.0, 20.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_set_position_state_seam.py -v`
Expected: `test_set_position_records_state_while_pushing_device_value` and `test_push_with_retry_forwards_state` FAIL (TypeError: unexpected keyword argument `state_lat`). The default test passes.

- [ ] **Step 3: Write minimal implementation**

In `backend/core/simulation_engine.py`, replace `_set_position` (590-593):

```python
    async def _set_position(
        self,
        lat: float,
        lng: float,
        state_lat: float | None = None,
        state_lng: float | None = None,
    ) -> None:
        """Push a coordinate to the device and update internal state.

        The value pushed to the device is (lat, lng). The value recorded as the
        live ``current_position`` is (state_lat, state_lng), defaulting to the
        pushed coord. The route/joystick loops push the JITTERED coord but pass
        the PRISTINE point as state_* so the recorded/broadcast position — and
        therefore any 'Bookmark Here' save — stays drift-free."""
        await self._device.set_location(self._udid, lat, lng)
        self.current_position = Coordinate(
            lat=state_lat if state_lat is not None else lat,
            lng=state_lng if state_lng is not None else lng,
        )
```

Replace the `_push_with_retry` signature + the `_set_position` call inside it (595-605):

```python
    async def _push_with_retry(
        self,
        lat: float,
        lng: float,
        state_lat: float | None = None,
        state_lng: float | None = None,
    ) -> bool:
        """Push one coordinate to the device with up to 3 attempts.

        Transient (ConnectionError, OSError) -> warn + backoff-sleep
        0.5*(attempt+1)s and retry. CancelledError propagates. Any other
        Exception logs and gives up immediately. Returns True iff the push
        landed. state_lat/state_lng forward to _set_position (pristine record
        while the jittered coord goes to the device)."""
        for attempt in range(3):
            try:
                await self._set_position(lat, lng, state_lat, state_lng)
                return True
```

(Leave lines 607-617 — the except/backoff/return — unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_set_position_state_seam.py tests/test_push_with_retry_char.py tests/test_engine_device_push.py -v`
Expected: all PASS (new seam works; the two existing char tests that call the no-state form still pass).

- [ ] **Step 5: Commit**

```bash
git add backend/core/simulation_engine.py backend/tests/test_set_position_state_seam.py
git commit -m "refactor(engine): decouple device-push value from recorded current_position"
```

---

### Task 2: `_move_along_route` records + broadcasts pristine, pushes jittered

**Files:**
- Modify: `backend/core/simulation_engine.py:806-822`
- Test: `backend/tests/test_move_along_route_pristine_char.py` (create)

**Interfaces:**
- Consumes: the `state_lat/state_lng` seam from Task 1.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_move_along_route_pristine_char.py`:

```python
"""Characterization: GPS jitter reaches the DEVICE but never the recorded
live position or the position_update broadcast.

Root cause of the 'saved bookmark drifts a few metres with a long-precision
tail' bug: the jittered coord used to be written into current_position and
broadcast, so 'Bookmark Here' persisted it. This pins the fix: device gets
jittered, current_position + position_update stay pristine (the exact route
point). add_jitter is stubbed to a fixed offset for determinism, mirroring the
identity-stub pattern in test_joystick_cov.py."""
from __future__ import annotations

import asyncio

import pytest

from models.schemas import Coordinate
from core.simulation_engine import SimulationEngine
from core.movement import RouteInterpolator
from tests._engine_harness import FakeClock, SteppedSleep, RecordingLocation

pytestmark = pytest.mark.asyncio


def _make_engine():
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    loc = RecordingLocation()
    emitted: list[tuple[str, dict]] = []

    async def cb(event_type, data):
        emitted.append((event_type, dict(data)))

    eng = SimulationEngine(loc, cb, clock=clock, sleep=sleep)
    return eng, loc, emitted


async def test_route_jitter_hits_device_not_broadcast(monkeypatch):
    # Deterministic non-identity jitter: +0.001 on each axis.
    monkeypatch.setattr(
        RouteInterpolator, "add_jitter",
        staticmethod(lambda lat, lng, j, rng=None: (lat + 0.001, lng + 0.001)),
    )

    async def _instant_timeout(aw, timeout):
        aw.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)

    eng, loc, emitted = _make_engine()
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    profile = {"speed_mps": 20.0, "jitter": 5.0, "update_interval": 1.0, "speed_jitter": 0.0}
    await eng._move_along_route(coords, profile)

    pos_events = [d for (t, d) in emitted if t == "position_update"]
    assert pos_events, "expected at least one position_update"

    # The route runs along lat==25.0; every pushed device coord carries the
    # +0.001 jitter offset (pushed lat == 25.001), while the broadcast lat
    # stays pristine (25.0).
    assert loc.pushes, "expected at least one device push"
    assert all(plat == pytest.approx(25.001) for (plat, _plng) in loc.pushes)

    # Broadcast + recorded live position are the pristine route points (no offset).
    for d in pos_events:
        assert d["lat"] == pytest.approx(25.0)
    assert eng.current_position.lat == pytest.approx(25.0)
    assert eng.current_position.lng == pytest.approx(121.001)  # pristine final point
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_move_along_route_pristine_char.py -v`
Expected: FAIL — today the broadcast `lat` is `25.001` (jittered) and `current_position.lat` is `25.001`, so the pristine assertions fail.

- [ ] **Step 3: Write minimal implementation**

In `backend/core/simulation_engine.py`, change the jitter block (806-822). Push jittered with pristine state; broadcast pristine:

```python
                # Add GPS jitter for the DEVICE only — the recorded live
                # position and the broadcast stay pristine so 'Bookmark Here'
                # and the blue dot never inherit the drift.
                jittered_lat, jittered_lng = RouteInterpolator.add_jitter(lat, lng, jitter)

                if not await self._push_with_retry(
                    jittered_lat, jittered_lng, state_lat=lat, state_lng=lng
                ):
                    logger.error("Giving up on this route after repeated push failures")
                    break

                # Update tracking
                self.distance_traveled += step_dist
                self.distance_remaining = max(total_distance - accumulated_distance, 0.0)
                self.eta_tracker.update(accumulated_distance)
                self.segment_index = min(idx, self.total_segments)

                combined_remaining = self.distance_remaining + self._route_offset_remaining
                combined_eta = combined_remaining / max(eff_speed, 0.001)
                await self._emit("position_update", {
                    "lat": lat,
                    "lng": lng,
                    "bearing": bearing,
                    "speed_mps": eff_speed,
                    "progress": self.eta_tracker.progress,
                    "distance_remaining": combined_remaining,
                    "distance_traveled": self.distance_traveled,
                    "eta_seconds": combined_eta,
                })
```

(Only three edits: `_push_with_retry(...)` gains `state_lat=lat, state_lng=lng`; the emit `"lat"`/`"lng"` change from `jittered_lat`/`jittered_lng` to `lat`/`lng`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_move_along_route_pristine_char.py tests/test_engine_speed_jitter_char.py tests/test_engine_loop_timing_char.py tests/test_engine_stream_char.py -v`
Expected: all PASS (new pristine behavior; existing char tests use `jitter=0.0` so are unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/core/simulation_engine.py backend/tests/test_move_along_route_pristine_char.py
git commit -m "fix(engine): keep current_position + broadcast pristine, jitter only the device (bookmark drift)"
```

---

### Task 3: Joystick records + broadcasts pristine, pushes jittered

**Files:**
- Modify: `backend/core/joystick.py:100-116`
- Test: `backend/tests/test_joystick_cov.py` (add one test; reuse the file's existing harness at 40-61)

**Interfaces:**
- Consumes: the `state_lat/state_lng` seam from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_joystick_cov.py` (uses the file's existing `make_engine`-style harness / `RouteInterpolator` import already present near the top; if `RouteInterpolator` is not imported in this file, add `from core.movement import RouteInterpolator`):

```python
async def test_joystick_tick_jitter_hits_device_not_broadcast(monkeypatch):
    """One joystick tick: device gets the jittered coord, but current_position
    and the position_update broadcast stay on the pristine move_point output."""
    from models.schemas import Coordinate

    eng, loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)

    # Fixed non-identity jitter so device != pristine deterministically.
    monkeypatch.setattr(
        RouteInterpolator, "add_jitter",
        staticmethod(lambda lat, lng, j, rng=None: (lat + 0.002, lng + 0.002)),
    )
    # Freeze move_point to a known pristine target.
    monkeypatch.setattr(
        RouteInterpolator, "move_point",
        staticmethod(lambda lat, lng, direction, distance: (25.01, 121.01)),
    )

    # Drive exactly one active tick then deactivate (follow the existing
    # single-tick pattern in test_loop_tick_moves_position_and_emits).
    await _run_one_joystick_tick(eng, direction=0.0, intensity=1.0)  # helper already in file

    # Device push carries the jitter offset...
    assert loc.pushes[-1] == pytest.approx((25.012, 121.012))
    # ...but broadcast + recorded position are the pristine move_point output.
    pos = [d for (t, d) in emitted if t == "position_update"][-1]
    assert (pos["lat"], pos["lng"]) == pytest.approx((25.01, 121.01))
    assert (eng.current_position.lat, eng.current_position.lng) == pytest.approx((25.01, 121.01))
```

> **Note for implementer:** `test_joystick_cov.py` already exercises a single joystick tick (see `test_loop_tick_moves_position_and_emits`, ~line 206, which stubs `add_jitter` to identity and drives one tick with a self-deactivating input). Reuse that exact driving mechanism instead of the placeholder `_run_one_joystick_tick` above — copy its setup (input object with `intensity`/`direction`, the one-shot loop, the `pytest.approx` on the pushed coord). Do not invent a new harness.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_joystick_cov.py -k jitter_hits_device -v`
Expected: FAIL — today `current_position` and the broadcast are `(25.012, 121.012)` (jittered), so the pristine assertions fail.

- [ ] **Step 3: Write minimal implementation**

In `backend/core/joystick.py`, change the tick body (100-116) so `move_point` output stays pristine, jitter goes to a separate pair, and the pristine value is recorded + broadcast:

```python
                    # move_point output is the PRISTINE intended position.
                    new_lat, new_lng = RouteInterpolator.move_point(
                        engine.current_position.lat,
                        engine.current_position.lng,
                        inp.direction,
                        distance,
                    )

                    # Jitter the DEVICE push only; record + broadcast pristine.
                    jittered_lat, jittered_lng = RouteInterpolator.add_jitter(
                        new_lat, new_lng, jitter * 0.3,
                    )
                    await engine._set_position(
                        jittered_lat, jittered_lng,
                        state_lat=new_lat, state_lng=new_lng,
                    )

                    # Accumulate distance
                    engine.distance_traveled += distance

                    await engine._emit("position_update", {
                        "lat": new_lat,
                        "lng": new_lng,
                        "speed_mps": speed_mps,
                        "bearing": inp.direction,
                    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_joystick_cov.py -v`
Expected: all PASS (new test green; existing joystick tests stub `add_jitter` to identity, so device == pristine there and every prior assertion still holds).

- [ ] **Step 5: Commit**

```bash
git add backend/core/joystick.py backend/tests/test_joystick_cov.py
git commit -m "fix(joystick): keep current_position + broadcast pristine, jitter only the device"
```

---

### Task 4: Group-mode decision, full regression, and verification

**Files:**
- (Option C only) Modify: `backend/services/group_sync_service.py:94-119` and `backend/core/simulation_engine.py` `_set_position`
- No new test file unless Option C is chosen.

- [ ] **Step 1: Confirm the group-mode decision with Ravi**

Default is **Option A** (no code change; followers track the pristine path). If Ravi chose Option A, skip to Step 3. Only do Step 2 for **Option C**.

- [ ] **Step 2 (Option C ONLY): Preserve exact group-follower behavior**

Add a recorded push field in `_set_position` (after the `current_position` assignment in Task 1's version):

```python
        self._last_device_push = Coordinate(lat=lat, lng=lng)
```

Initialise it in `__init__` next to `self.current_position` (simulation_engine.py:88):

```python
        self._last_device_push: Coordinate | None = None
```

Then in `group_sync_service.py`, change the read (line 115) to prefer the pushed value, falling back to current_position:

```python
            pos = primary_eng._last_device_push or primary_eng.current_position
```

Add a focused test `backend/tests/test_group_follow_uses_device_push.py` asserting `_last_device_push` holds the jittered value after `_set_position(j_lat, j_lng, state_lat=p_lat, state_lng=p_lng)`. (Write the failing test first, run it, implement, run it green — same TDD loop as Tasks 1-3.)

- [ ] **Step 3: Full backend regression**

Run: `cd backend && .venv/bin/python -m pytest -q > /tmp/gps_fix_suite.txt 2>&1; tail -5 /tmp/gps_fix_suite.txt`
Expected: `0 failed`. Collected count = 1180 + (2 new files' tests) + joystick's new test (Option A) — no regressions in the 1180 baseline.

- [ ] **Step 4: Import-linter + dependency-cruiser gates**

Run: `cd backend && .venv/bin/python -m pytest -q -k "import_linter or contracts" 2>/dev/null || true` then the repo's contract command (per CLAUDE.md: 7 kept, 0 broken). Frontend: `cd frontend && npx depcruise` gate stays 0 errors (frontend untouched, so this is a formality).
Expected: 7 contracts kept, 0 broken; depcruise 0 errors.

- [ ] **Step 5: Manual on-device verification (evidence required)**

Automated tests cover the mechanism; a manual pass confirms the end-to-end save. With a connected device:
1. Type `25.034623,121.546087`, start a **navigate/walk** simulation to a nearby point (a moving sim, NOT teleport).
2. While moving, press **Bookmark Here** (and separately the library-panel **+** name-only add).
3. Inspect `~/.locwarp/bookmarks.json` (or the Library panel): the saved `lat`/`lng` must equal the pristine route point at save time — **no long jittered tail, no few-metre drift**.
4. Confirm the device (iPhone) still shows realistic per-tick jitter on its own map (jitter preserved on-device).
Capture the saved JSON snippet as evidence.

- [ ] **Step 6: Commit (Option C only) / done**

```bash
# Option C only:
git add backend/core/simulation_engine.py backend/services/group_sync_service.py backend/tests/test_group_follow_uses_device_push.py
git commit -m "fix(group): followers mirror the leader's device-pushed position, preserving group-mode jitter"
```

---

## Non-goals / follow-ups (not in this plan)

- **Historical bookmarks stay drifted.** Bookmarks saved before this fix keep their jittered coords; they won't self-heal. User can edit/re-save. A bulk cleanup is risky under the CRDT merge (empty `updated_at` pitfall) and is deliberately out of scope.
- **Map right-click "Add bookmark here"** persists full-precision Leaflet click coordinates (`MapContextMenu.tsx:361` → unrounded dialog). That produces long digits too but is "where you clicked", not drift from a typed value — a separate, lower-priority precision concern. Not addressed here.
- **`AppAddBookmarkDialog` has no editable coordinate field** (read-only `toFixed(5)`). Adding one would let users correct a saved coord, but is a UX change beyond this fix.
- **Threading `self._rng` into `add_jitter` at `_move_along_route:806`** (position jitter currently uses module `random`, not the seeded engine rng — inconsistent with speed jitter at :789). A reasonable consistency cleanup, but out of the minimal scope; the new tests use a monkeypatched `add_jitter` instead.

## Self-Review

- **Spec coverage:** primary bug (route movers) → Task 2; second jitter site (joystick) → Task 3; the enabling seam → Task 1; group-mode consequence → Task 4 decision; regression + on-device evidence → Task 4. Per-stop/lap emits + teleport verified already pristine (no task needed).
- **Placeholder scan:** the only intentional pointer is the joystick single-tick driver in Task 3 Step 1, which explicitly directs the implementer to reuse the existing `test_loop_tick_moves_position_and_emits` mechanism in the same file (real, named reference) rather than a stub.
- **Type consistency:** `_set_position(lat, lng, state_lat=None, state_lng=None)` and `_push_with_retry(lat, lng, state_lat=None, state_lng=None)` used identically in Tasks 1-3; `state_lat/state_lng` naming consistent throughout; `Coordinate(lat=, lng=)` matches `models/schemas.py`.
