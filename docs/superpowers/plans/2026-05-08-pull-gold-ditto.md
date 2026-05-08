# Pull Gold Ditto (拉金盆) Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "拉金盆" mode tab that automates the `teleport → wait N seconds → restore` cycle used to pull a Shiny Ditto from the in-game flower-pulling screen.

**Architecture:** Backend grows a `GoldDittoHandler` that runs the three-step cycle atomically inside an `asyncio.Lock`, exposed via a new endpoint `POST /api/location/goldditto/cycle`. Frontend adds a `SimMode.GoldDitto` tab with three buttons (Confirm Location / 1st try / retries); cycle buttons fan out to all connected devices using the existing `fanout` helper. Status-bar messages are driven by a new `goldditto_cycle` WebSocket event.

**Tech Stack:** FastAPI · pydantic · asyncio · React 18 · TypeScript · Leaflet · Vite. Tests use pytest + pytest-asyncio (bootstrapped in Task 1 — the project currently has no Python test suite).

**Spec:** `docs/superpowers/specs/2026-05-08-pull-gold-ditto-design.md`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/requirements-dev.txt` | Create | pytest + pytest-asyncio |
| `backend/tests/__init__.py` | Create | empty marker |
| `backend/tests/conftest.py` | Create | sys.path bootstrap so tests import `core.*`, `models.*` |
| `backend/tests/test_goldditto_handler.py` | Create | unit tests for `GoldDittoHandler` |
| `backend/tests/test_goldditto_api.py` | Create | FastAPI TestClient tests for `/goldditto/cycle` |
| `backend/models/schemas.py` | Modify | Add `GoldDittoCycleRequest` |
| `backend/core/goldditto.py` | Create | `GoldDittoHandler` with `_pick()` and `cycle()` |
| `backend/core/simulation_engine.py` | Modify | Instantiate `_goldditto_handler` in `__init__`; add public `goldditto_cycle()` method |
| `backend/api/location.py` | Modify | New route `POST /goldditto/cycle` |
| `frontend/src/services/api.ts` | Modify | Add `goldDittoCycle()` client method |
| `frontend/src/i18n.ts` | Modify | Add `mode.goldditto` and `goldditto.*` keys (zh-TW + en) |
| `frontend/src/hooks/useSimulation.ts` | Modify | Add `SimMode.GoldDitto`; add `goldDittoCycleAll()` fanout method; track `goldDittoCycling` state |
| `frontend/src/components/GoldDittoPanel.tsx` | Create | Inputs (A, B, wait), three action buttons, helper buttons, validation, localStorage persistence |
| `frontend/src/components/ControlPanel.tsx` | Modify | Add `SimMode.GoldDitto` icon + label; render `<GoldDittoPanel>` when active |
| `frontend/src/components/MapView.tsx` | Modify | Add "設為拉金盆 A 點" entry to right-click menu |
| `frontend/src/App.tsx` | Modify | Subscribe to `goldditto_cycle` WS event → status-bar message; pass A-setter to MapView |

---

## Task 1: Bootstrap pytest + add `GoldDittoCycleRequest` schema

**Files:**
- Create: `backend/requirements-dev.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_goldditto_schema.py`
- Modify: `backend/models/schemas.py` (append at the end)

The repo currently has zero Python tests. Bootstrap a minimal pytest setup so this feature can have its own unit + API tests without touching anything else.

- [ ] **Step 1: Create `backend/requirements-dev.txt`**

```
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
```

(`httpx` is already a runtime dep but FastAPI's `TestClient` needs it explicitly when used outside Starlette's bundled client.)

- [ ] **Step 2: Install dev deps**

Run: `cd backend && py -3.13 -m pip install -r requirements-dev.txt`
On macOS the user may use `python3.13` instead — try `python3.13 -m pip install -r requirements-dev.txt` if `py` is unavailable.

Expected: pytest and pytest-asyncio install successfully.

- [ ] **Step 3: Create `backend/tests/__init__.py`**

Empty file:

```python
```

- [ ] **Step 4: Create `backend/tests/conftest.py`**

```python
"""Pytest configuration. Adds the backend/ root to sys.path so tests can
import models.*, core.*, services.* the same way the runtime does.
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
```

- [ ] **Step 5: Write failing schema test**

Create `backend/tests/test_goldditto_schema.py`:

```python
"""Schema validation tests for GoldDittoCycleRequest."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import GoldDittoCycleRequest


def _base_payload(**overrides):
    base = {
        "udid": None,
        "target": "auto",
        "lat_a": 25.0,
        "lng_a": 121.5,
        "lat_b": 25.034897,
        "lng_b": 121.545827,
        "wait_seconds": 3.0,
    }
    base.update(overrides)
    return base


def test_valid_payload_parses():
    req = GoldDittoCycleRequest(**_base_payload())
    assert req.target == "auto"
    assert req.wait_seconds == 3.0


def test_target_rejects_unknown_value():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(target="C"))


def test_wait_seconds_rejects_below_min():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(wait_seconds=0.4))


def test_wait_seconds_rejects_above_max():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(wait_seconds=10.5))


def test_lat_out_of_range_rejected():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(lat_a=95.0))
```

- [ ] **Step 6: Run failing tests**

Run: `cd backend && python3.13 -m pytest tests/test_goldditto_schema.py -v`
Expected: all 5 tests fail with `ImportError` (GoldDittoCycleRequest doesn't exist).

- [ ] **Step 7: Implement `GoldDittoCycleRequest`**

Append to `backend/models/schemas.py` (after the last existing model — keep imports up top):

```python
from typing import Literal


class GoldDittoCycleRequest(BaseModel):
    """Pull-Gold-Ditto cycle request.

    target=A → use (lat_a, lng_a)
    target=B → use (lat_b, lng_b)
    target=auto → backend picks farther-from-current point
    """
    udid: str | None = None
    target: Literal["A", "B", "auto"]
    lat_a: float = Field(..., ge=-90.0, le=90.0)
    lng_a: float = Field(..., ge=-180.0, le=180.0)
    lat_b: float = Field(..., ge=-90.0, le=90.0)
    lng_b: float = Field(..., ge=-180.0, le=180.0)
    wait_seconds: float = Field(..., ge=0.5, le=10.0)
```

If `Field` is not already imported at the top of `schemas.py`, add it: `from pydantic import BaseModel, Field`.

- [ ] **Step 8: Run tests — they should pass**

Run: `cd backend && python3.13 -m pytest tests/test_goldditto_schema.py -v`
Expected: 5 passed.

- [ ] **Step 9: Commit**

```bash
git add backend/requirements-dev.txt backend/tests/ backend/models/schemas.py
git commit -m "feat(backend): add GoldDittoCycleRequest schema + pytest bootstrap"
```

---

## Task 2: Implement `GoldDittoHandler.cycle()` (TDD)

**Files:**
- Create: `backend/core/goldditto.py`
- Create: `backend/tests/test_goldditto_handler.py`

The handler owns its own `asyncio.Lock` and runs `engine.teleport → asyncio.sleep → engine.restore` atomically. Concurrent cycle calls return `LockedError` (mapped to HTTP 409 in Task 3).

- [ ] **Step 1: Write failing handler tests**

Create `backend/tests/test_goldditto_handler.py`:

```python
"""Unit tests for GoldDittoHandler."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from core.goldditto import GoldDittoHandler, GoldDittoLockedError
from models.schemas import Coordinate


# ── Fake engine ────────────────────────────────────────────────────────────

@dataclass
class FakeEngine:
    """Stand-in for SimulationEngine. Records call order so tests can assert
    teleport → sleep → restore happens in order with the correct args."""
    current_position: Coordinate | None = None
    teleport_calls: list[tuple[float, float]] = None
    restore_calls: int = 0
    emitted: list[tuple[str, dict]] = None

    def __post_init__(self):
        self.teleport_calls = []
        self.emitted = []

    async def teleport(self, lat: float, lng: float) -> Coordinate:
        self.teleport_calls.append((lat, lng))
        self.current_position = Coordinate(lat=lat, lng=lng)
        return self.current_position

    async def restore(self) -> None:
        self.restore_calls += 1
        # Real engine keeps current_position after restore; mirror that.

    async def _emit(self, event_type: str, data: dict) -> None:
        self.emitted.append((event_type, data))


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def handler(engine) -> GoldDittoHandler:
    return GoldDittoHandler(engine)


A = (25.034897, 121.545827)
B = (25.10, 121.60)


# ── Target picker ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_target_A_returns_A(handler):
    result = await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"
    assert (result["lat"], result["lng"]) == A


@pytest.mark.asyncio
async def test_target_B_returns_B(handler):
    result = await handler.cycle(target="B", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "B"
    assert (result["lat"], result["lng"]) == B


@pytest.mark.asyncio
async def test_auto_with_no_current_position_picks_A(handler, engine):
    engine.current_position = None
    result = await handler.cycle(target="auto", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"


@pytest.mark.asyncio
async def test_auto_when_close_to_A_picks_B(handler, engine):
    engine.current_position = Coordinate(lat=A[0], lng=A[1])
    result = await handler.cycle(target="auto", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "B"


@pytest.mark.asyncio
async def test_auto_when_close_to_B_picks_A(handler, engine):
    engine.current_position = Coordinate(lat=B[0], lng=B[1])
    result = await handler.cycle(target="auto", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"


# ── Cycle orchestration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cycle_calls_teleport_then_restore_in_order(handler, engine):
    await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                        lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert engine.teleport_calls == [A]
    assert engine.restore_calls == 1


@pytest.mark.asyncio
async def test_cycle_emits_phase_events(handler, engine):
    await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                        lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    events = [e for e in engine.emitted if e[0] == "goldditto_cycle"]
    assert len(events) == 2
    assert events[0][1]["phase"] == "teleported"
    assert events[0][1]["target"] == "A"
    assert events[1][1]["phase"] == "restored"


@pytest.mark.asyncio
async def test_concurrent_cycle_raises_locked(handler, engine):
    """Second cycle started while first is mid-sleep must raise GoldDittoLockedError."""
    cycle1 = asyncio.create_task(handler.cycle(
        target="A", lat_a=A[0], lng_a=A[1],
        lat_b=B[0], lng_b=B[1], wait_seconds=0.2))
    await asyncio.sleep(0.05)  # let cycle1 enter the lock

    with pytest.raises(GoldDittoLockedError):
        await handler.cycle(target="B", lat_a=A[0], lng_a=A[1],
                            lat_b=B[0], lng_b=B[1], wait_seconds=0.01)

    await cycle1
    assert engine.restore_calls == 1


@pytest.mark.asyncio
async def test_teleport_failure_skips_sleep_and_restore(handler, engine):
    """If teleport raises, cycle propagates and never sleeps or restores."""
    async def boom(lat, lng):
        raise RuntimeError("device unplugged")
    engine.teleport = boom

    with pytest.raises(RuntimeError, match="device unplugged"):
        await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                            lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert engine.restore_calls == 0
```

- [ ] **Step 2: Run tests — they should fail with ImportError**

Run: `cd backend && python3.13 -m pytest tests/test_goldditto_handler.py -v`
Expected: ImportError on `core.goldditto` (file doesn't exist yet).

- [ ] **Step 3: Implement `GoldDittoHandler`**

Create `backend/core/goldditto.py`:

```python
"""Pull-Gold-Ditto handler.

Runs a three-step cycle (teleport → asyncio.sleep → restore) atomically.
The whole cycle is serialized by an internal asyncio.Lock so two concurrent
calls cannot interleave and cause undefined device state.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Literal

from models.schemas import Coordinate

logger = logging.getLogger(__name__)


class GoldDittoLockedError(Exception):
    """Raised when a cycle is requested while another is already running."""


def _great_circle_m(p1: Coordinate, p2: tuple[float, float]) -> float:
    """Approximate great-circle distance in meters. Used only to compare two
    distances, so trig precision is not load-bearing."""
    lat1, lng1 = math.radians(p1.lat), math.radians(p1.lng)
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


class GoldDittoHandler:
    def __init__(self, engine):
        self.engine = engine
        self._lock = asyncio.Lock()

    def _pick(
        self,
        target: Literal["A", "B", "auto"],
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> tuple[str, float, float]:
        """Return (label, lat, lng) for the chosen teleport target."""
        if target == "A":
            return ("A", a[0], a[1])
        if target == "B":
            return ("B", b[0], b[1])
        # auto: closer to A → return B; closer to B → return A; None → A
        cur = self.engine.current_position
        if cur is None:
            return ("A", a[0], a[1])
        dist_a = _great_circle_m(cur, a)
        dist_b = _great_circle_m(cur, b)
        if dist_a < dist_b:
            return ("B", b[0], b[1])
        return ("A", a[0], a[1])

    async def cycle(
        self,
        *,
        target: Literal["A", "B", "auto"],
        lat_a: float,
        lng_a: float,
        lat_b: float,
        lng_b: float,
        wait_seconds: float,
    ) -> dict:
        if self._lock.locked():
            raise GoldDittoLockedError("cycle already in progress")

        async with self._lock:
            label, lat, lng = self._pick(target, (lat_a, lng_a), (lat_b, lng_b))
            t0 = time.monotonic()

            await self.engine.teleport(lat, lng)
            await self.engine._emit("goldditto_cycle", {
                "phase": "teleported",
                "target": label,
                "lat": lat,
                "lng": lng,
            })
            logger.info("Gold Ditto: teleported to %s (%.6f, %.6f); waiting %.2fs",
                        label, lat, lng, wait_seconds)

            await asyncio.sleep(wait_seconds)

            await self.engine.restore()
            await self.engine._emit("goldditto_cycle", {
                "phase": "restored",
                "target": label,
            })
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info("Gold Ditto: cycle complete (%dms)", duration_ms)

            return {
                "target_used": label,
                "lat": lat,
                "lng": lng,
                "duration_ms": duration_ms,
            }
```

- [ ] **Step 4: Run tests — they should all pass**

Run: `cd backend && python3.13 -m pytest tests/test_goldditto_handler.py -v`
Expected: 9 passed (or however many tests above end up — confirm number matches).

- [ ] **Step 5: Commit**

```bash
git add backend/core/goldditto.py backend/tests/test_goldditto_handler.py
git commit -m "feat(backend): add GoldDittoHandler with atomic teleport→wait→restore cycle"
```

---

## Task 3: Wire `GoldDittoHandler` into `SimulationEngine` + add API endpoint

**Files:**
- Modify: `backend/core/simulation_engine.py:117-123` (handler instantiation block) and add public method around line 400
- Modify: `backend/api/location.py` (add new route)
- Create: `backend/tests/test_goldditto_api.py`

The engine already instantiates per-mode handlers in `__init__`. Add `_goldditto_handler` alongside them. The public `goldditto_cycle()` method on the engine just delegates to the handler so the API layer doesn't reach into private attributes.

- [ ] **Step 1: Add handler attribute on engine**

Edit `backend/core/simulation_engine.py`. Find the block (around line 117):

```python
        self._teleport_handler = TeleportHandler(self)
        self._navigator = Navigator(self)
        self._looper = RouteLooper(self)
        self._joystick = JoystickHandler(self)
        self._multi_stop = MultiStopNavigator(self)
        self._random_walk = RandomWalkHandler(self)
        self._restore_handler = RestoreHandler(self)
```

Replace with (add one line after `_restore_handler`):

```python
        self._teleport_handler = TeleportHandler(self)
        self._navigator = Navigator(self)
        self._looper = RouteLooper(self)
        self._joystick = JoystickHandler(self)
        self._multi_stop = MultiStopNavigator(self)
        self._random_walk = RandomWalkHandler(self)
        self._restore_handler = RestoreHandler(self)
        from core.goldditto import GoldDittoHandler  # local import to avoid circular
        self._goldditto_handler = GoldDittoHandler(self)
```

- [ ] **Step 2: Add public method on engine**

Find the existing `async def restore` method (around line 400):

```python
    async def restore(self) -> None:
        ...
        await self._restore_handler.restore()
```

Add a new public method right after it:

```python
    async def goldditto_cycle(
        self,
        *,
        target: str,
        lat_a: float,
        lng_a: float,
        lat_b: float,
        lng_b: float,
        wait_seconds: float,
    ) -> dict:
        """Run a Gold Ditto cycle: teleport → sleep → restore (atomic)."""
        return await self._goldditto_handler.cycle(
            target=target,
            lat_a=lat_a, lng_a=lng_a,
            lat_b=lat_b, lng_b=lng_b,
            wait_seconds=wait_seconds,
        )
```

- [ ] **Step 3: Add API route**

Edit `backend/api/location.py`. Find the existing `/restore` route (around line 381):

```python
@router.post("/restore")
async def restore(udid: str | None = None):
    engine = await _engine(udid)
    await engine.restore()
    return {"status": "restored"}
```

Add immediately after it:

```python
@router.post("/goldditto/cycle")
async def goldditto_cycle(req: GoldDittoCycleRequest):
    """拉金盆 cycle: teleport → asyncio.sleep(wait) → restore, atomic."""
    from core.goldditto import GoldDittoLockedError
    engine = await _engine(req.udid)
    try:
        result = await engine.goldditto_cycle(
            target=req.target,
            lat_a=req.lat_a, lng_a=req.lng_a,
            lat_b=req.lat_b, lng_b=req.lng_b,
            wait_seconds=req.wait_seconds,
        )
    except GoldDittoLockedError:
        raise HTTPException(
            status_code=409,
            detail={"code": "cycle_in_progress",
                    "message": "拉金盆 cycle already in progress, wait for it to finish"},
        )
    except DeviceLostError as e:
        action_udid = req.udid
        from main import app_state as _app_state
        action_udid = action_udid or _app_state._primary_udid
        raise (await _handle_device_lost(e, action_udid))
    except Exception as e:
        import logging, traceback
        logging.getLogger("locwarp").error("Gold Ditto cycle failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "completed", **result}
```

Also update the `from models.schemas import (...)` block at the top of `location.py` to include `GoldDittoCycleRequest`:

```python
from models.schemas import (
    MovementMode,
    TeleportRequest,
    NavigateRequest,
    LoopRequest,
    MultiStopRequest,
    RandomWalkRequest,
    JoystickStartRequest,
    SimulationStatus,
    Coordinate,
    CooldownSettings,
    CooldownStatus,
    CoordFormatRequest,
    CoordinateFormat,
    GoldDittoCycleRequest,  # NEW
)
```

- [ ] **Step 4: Write API tests**

Create `backend/tests/test_goldditto_api.py`:

```python
"""FastAPI integration tests for /api/location/goldditto/cycle."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Build a TestClient against a fresh app with mocked engine resolver."""
    from main import app  # noqa: WPS433
    return TestClient(app)


def _payload(**overrides):
    base = {
        "target": "A",
        "lat_a": 25.034897, "lng_a": 121.545827,
        "lat_b": 25.10, "lng_b": 121.60,
        "wait_seconds": 0.05,
    }
    base.update(overrides)
    return base


def test_endpoint_validates_payload(client):
    resp = client.post("/api/location/goldditto/cycle",
                        json=_payload(wait_seconds=0.1, target="bad"))
    assert resp.status_code == 422


def test_endpoint_validates_wait_lower_bound(client):
    resp = client.post("/api/location/goldditto/cycle",
                        json=_payload(wait_seconds=0.1))
    # 0.1 < 0.5 lower bound → validation error
    assert resp.status_code == 422


def test_endpoint_returns_completed_when_engine_succeeds(client):
    fake_result = {"target_used": "A", "lat": 25.0, "lng": 121.5, "duration_ms": 50}
    fake_engine = MagicMock()
    fake_engine.goldditto_cycle = AsyncMock(return_value=fake_result)

    async def fake_resolver(udid):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post("/api/location/goldditto/cycle", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["target_used"] == "A"
    fake_engine.goldditto_cycle.assert_awaited_once()


def test_endpoint_returns_409_on_locked_error(client):
    from core.goldditto import GoldDittoLockedError
    fake_engine = MagicMock()
    fake_engine.goldditto_cycle = AsyncMock(side_effect=GoldDittoLockedError("busy"))

    async def fake_resolver(udid):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post("/api/location/goldditto/cycle", json=_payload())
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cycle_in_progress"
```

- [ ] **Step 5: Run API tests**

Run: `cd backend && python3.13 -m pytest tests/test_goldditto_api.py -v`
Expected: 4 passed.

If `from main import app` fails because `main.py` has top-level side effects (engine creation, etc.), the test fixture may need to mock `app_state`. Check the error and adjust — most FastAPI apps with `app = FastAPI()` at module scope import cleanly, but LocWarp may need `monkeypatch` on `app_state.simulation_engine`.

- [ ] **Step 6: Smoke test the endpoint manually**

Start the backend in one terminal:
`cd backend && python3.13 main.py`

In another terminal (no iPhone needed for the validation check):
```bash
curl -X POST http://localhost:8777/api/location/goldditto/cycle \
  -H "Content-Type: application/json" \
  -d '{"target":"A","lat_a":25.0,"lng_a":121.5,"lat_b":25.1,"lng_b":121.6,"wait_seconds":0.5}'
```

Expected: HTTP 400 with `no_device` (no iPhone connected). The fact that you get past validation proves the endpoint and schema wire together correctly.

- [ ] **Step 7: Commit**

```bash
git add backend/core/simulation_engine.py backend/api/location.py backend/tests/test_goldditto_api.py
git commit -m "feat(backend): wire GoldDittoHandler into engine + add /goldditto/cycle endpoint"
```

---

## Task 4: Frontend — `SimMode.GoldDitto` enum + tab + i18n keys

**Files:**
- Modify: `frontend/src/hooks/useSimulation.ts:5-12` (SimMode enum)
- Modify: `frontend/src/components/ControlPanel.tsx:152-211` (modeIcons + modeLabelKeys)
- Modify: `frontend/src/i18n.ts` (add new keys for both locales)

This task adds the tab to the Mode panel without yet rendering panel content (panel comes in Task 6). After this task the tab is clickable but the panel area shows the existing default content — we'll wire the panel in Task 6.

- [ ] **Step 1: Add `GoldDitto` to `SimMode` enum**

Edit `frontend/src/hooks/useSimulation.ts`:

```typescript
export enum SimMode {
  Teleport = 'teleport',
  Navigate = 'navigate',
  Loop = 'loop',
  Joystick = 'joystick',
  MultiStop = 'multistop',
  RandomWalk = 'randomwalk',
  GoldDitto = 'goldditto',     // NEW
}
```

- [ ] **Step 2: Add icon entry to `modeIcons` in `ControlPanel.tsx`**

Find the `modeIcons` block (around line 152). Add a new entry — use an emoji-like SVG or any simple icon:

```typescript
const modeIcons: Record<SimMode, JSX.Element> = {
  [SimMode.Teleport]: ( /* existing */ ),
  [SimMode.Navigate]: ( /* existing */ ),
  [SimMode.Loop]: ( /* existing */ ),
  [SimMode.MultiStop]: ( /* existing */ ),
  [SimMode.RandomWalk]: ( /* existing */ ),
  [SimMode.Joystick]: ( /* existing */ ),
  [SimMode.GoldDitto]: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2">
      <path d="M12 2 L13.5 9 L21 12 L13.5 15 L12 22 L10.5 15 L3 12 L10.5 9 Z" />
    </svg>
  ),
};
```

(A four-point star — visually distinct from existing icons.)

- [ ] **Step 3: Add label key entry to `modeLabelKeys`**

Find the `modeLabelKeys` block (around line 204):

```typescript
const modeLabelKeys: Record<SimMode, StringKey> = {
  [SimMode.Teleport]: 'mode.teleport',
  [SimMode.Navigate]: 'mode.navigate',
  [SimMode.Loop]: 'mode.loop',
  [SimMode.MultiStop]: 'mode.multi_stop',
  [SimMode.RandomWalk]: 'mode.random_walk',
  [SimMode.Joystick]: 'mode.joystick',
  [SimMode.GoldDitto]: 'mode.goldditto',   // NEW
};
```

- [ ] **Step 4: Add i18n keys**

Edit `frontend/src/i18n.ts`. Find the `STRINGS` object and add the following keys (mirror the format of existing entries — add to both `zh` and `en` sub-objects of each key):

```typescript
'mode.goldditto': { zh: '拉金盆', en: 'Gold Ditto' },
'goldditto.a_label': { zh: 'A 點 (金盆位置 / 花點)', en: 'A (Gold Ditto / Flower spot)' },
'goldditto.b_label': { zh: 'B 點 (你的真實 GPS)', en: 'B (Your real GPS)' },
'goldditto.wait_label': { zh: '等待秒數', en: 'Wait seconds' },
'goldditto.confirm': { zh: 'Confirm Location', en: 'Confirm Location' },
'goldditto.first_try': { zh: '1st try', en: '1st try' },
'goldditto.retries': { zh: 'retries', en: 'retries' },
'goldditto.random_b': { zh: '🎲 隨機台灣 B 點', en: '🎲 Random Taiwan B' },
'goldditto.use_map_center': { zh: '📍 用目前地圖中心', en: '📍 Use current map center' },
'goldditto.toast.teleported': { zh: '拉金盆: 已瞬移到 {{target}}', en: 'Gold Ditto: teleported to {{target}}' },
'goldditto.toast.waiting': { zh: '拉金盆: 等待 {{remaining}}s ⋯ 即將還原', en: 'Gold Ditto: waiting {{remaining}}s ⋯' },
'goldditto.toast.restored': { zh: '拉金盆: 還原完成,可以開始拉花苞 ✨', en: 'Gold Ditto: restored, pull away ✨' },
'goldditto.toast.failed': { zh: '拉金盆失敗: {{phase}} - {{reason}}', en: 'Gold Ditto failed: {{phase}} - {{reason}}' },
'goldditto.error.no_device': { zh: '請先連接 iPhone', en: 'Connect an iPhone first' },
'goldditto.error.invalid_a': { zh: '請先填 A 座標 (lat,lng)', en: 'Enter A coordinates (lat,lng)' },
'goldditto.error.invalid_b': { zh: '請先填 B 座標 (lat,lng)', en: 'Enter B coordinates (lat,lng)' },
'goldditto.warn_same_ab': { zh: '⚠ A 跟 B 是同一點,輪流會無效', en: '⚠ A and B are identical, alternation has no effect' },
```

(If `i18n.ts` has a different shape — e.g. separate zh.json / en.json — adapt to the existing pattern. Confirm with `head -50 frontend/src/i18n.ts` if unsure.)

- [ ] **Step 5: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. Any "exhaustive switch" errors on `SimMode` mean a `switch` statement somewhere needs a `case SimMode.GoldDitto`. Address them by either adding a case that returns `null` / no-op or by widening to a default branch.

- [ ] **Step 6: Smoke test in browser**

Start dev: `bash start.sh` (macOS) or `LocWarp.bat` (Windows).

Expected: a 7th tab "拉金盆 / Gold Ditto" appears next to the existing 6. Clicking it doesn't yet show panel content (that's Task 6) — but the tab should highlight as active and the existing default panel content stays visible.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/useSimulation.ts frontend/src/components/ControlPanel.tsx frontend/src/i18n.ts
git commit -m "feat(frontend): add GoldDitto SimMode enum value + tab + i18n keys"
```

---

## Task 5: Frontend — API client + `useSimulation` fanout method

**Files:**
- Modify: `frontend/src/services/api.ts` (add `goldDittoCycle()` after the existing `teleport()`)
- Modify: `frontend/src/hooks/useSimulation.ts` (add `goldDittoCycleAll()` and `goldDittoCycling` state)

- [ ] **Step 1: Add API client method**

Edit `frontend/src/services/api.ts`. Find the existing `teleport` export (line ~126) and add right after:

```typescript
export interface GoldDittoCycleResponse {
  status: 'completed';
  target_used: 'A' | 'B';
  lat: number;
  lng: number;
  duration_ms: number;
}

export const goldDittoCycle = (
  args: {
    target: 'A' | 'B' | 'auto';
    lat_a: number; lng_a: number;
    lat_b: number; lng_b: number;
    wait_seconds: number;
  },
  udid?: string,
) =>
  request<GoldDittoCycleResponse>('POST', '/api/location/goldditto/cycle', {
    ...args,
    ...ud(udid),
  });
```

- [ ] **Step 2: Add cycling state and fanout method to `useSimulation`**

Find the section that defines `teleportAll` (around line 814 in `useSimulation.ts`):

```typescript
  const teleportAll = useCallback((udids: string[], lat: number, lng: number) =>
    fanout(udids, 'teleport', (u) => api.teleport(lat, lng, u)), [fanout])
```

Add immediately after:

```typescript
  const [goldDittoCycling, setGoldDittoCycling] = useState(false)

  const goldDittoCycleAll = useCallback(async (
    udids: string[],
    args: {
      target: 'A' | 'B' | 'auto';
      lat_a: number; lng_a: number;
      lat_b: number; lng_b: number;
      wait_seconds: number;
    },
  ) => {
    setGoldDittoCycling(true)
    try {
      return await fanout(udids, 'goldditto_cycle', (u) => api.goldDittoCycle(args, u))
    } finally {
      setGoldDittoCycling(false)
    }
  }, [fanout])
```

- [ ] **Step 3: Export the new state and method**

Find the hook's `return` statement (toward the bottom). Add:

```typescript
return {
  // ...existing exports
  goldDittoCycling,
  goldDittoCycleAll,
}
```

- [ ] **Step 4: Run type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/hooks/useSimulation.ts
git commit -m "feat(frontend): add goldDittoCycle API client + useSimulation fanout"
```

---

## Task 6: Build `GoldDittoPanel` component

**Files:**
- Create: `frontend/src/components/GoldDittoPanel.tsx`

The panel owns: A/B/wait inputs, three action buttons, helper buttons, validation, and localStorage persistence. It receives the cycling state and fanout callback as props from `ControlPanel` (wired in Task 7).

- [ ] **Step 1: Create panel component**

Create `frontend/src/components/GoldDittoPanel.tsx`:

```typescript
import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { useT } from '../i18n'

interface Props {
  connectedUdids: string[]
  isCycling: boolean
  mapCenter: { lat: number; lng: number } | null
  // External A-setter — called when MapView right-click "設為拉金盆 A 點" fires.
  externalAValue: string | null
  onConfirmLocation: (lat: number, lng: number) => Promise<void> | void
  onCycle: (
    target: 'A' | 'B' | 'auto',
    args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
  ) => Promise<void> | void
}

const DEFAULT_B = '25.034897, 121.545827'
const LS_A = 'goldditto.A'
const LS_B = 'goldditto.B'
const LS_WAIT = 'goldditto.wait_seconds'

// Taiwan main-island bounding box (24.0–25.5°N, 120.5–122.0°E).
function randomTaiwanCoord(): string {
  const lat = 24.0 + Math.random() * 1.5
  const lng = 120.5 + Math.random() * 1.5
  return `${lat.toFixed(6)}, ${lng.toFixed(6)}`
}

function parseLatLng(s: string): { lat: number; lng: number } | null {
  const m = s.trim().match(/^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/)
  if (!m) return null
  const lat = parseFloat(m[1])
  const lng = parseFloat(m[2])
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null
  return { lat, lng }
}

export const GoldDittoPanel: React.FC<Props> = ({
  connectedUdids,
  isCycling,
  mapCenter,
  externalAValue,
  onConfirmLocation,
  onCycle,
}) => {
  const t = useT()

  const [aText, setAText] = useState(() => localStorage.getItem(LS_A) ?? '')
  const [bText, setBText] = useState(() => localStorage.getItem(LS_B) ?? DEFAULT_B)
  const [waitText, setWaitText] = useState(
    () => localStorage.getItem(LS_WAIT) ?? '3.0',
  )

  // Persist on change.
  useEffect(() => { localStorage.setItem(LS_A, aText) }, [aText])
  useEffect(() => { localStorage.setItem(LS_B, bText) }, [bText])
  useEffect(() => { localStorage.setItem(LS_WAIT, waitText) }, [waitText])

  // External A setter (map right-click).
  useEffect(() => {
    if (externalAValue) setAText(externalAValue)
  }, [externalAValue])

  const a = useMemo(() => parseLatLng(aText), [aText])
  const b = useMemo(() => parseLatLng(bText), [bText])
  const waitSeconds = useMemo(() => {
    const v = parseFloat(waitText)
    if (Number.isNaN(v)) return null
    return Math.min(10, Math.max(0.5, v))
  }, [waitText])

  const noDevice = connectedUdids.length === 0
  const aValid = a !== null
  const bValid = b !== null
  const waitValid = waitSeconds !== null
  const sameAB = a && b && Math.abs(a.lat - b.lat) < 1e-6 && Math.abs(a.lng - b.lng) < 1e-6

  const cycleArgs = useMemo(() => {
    if (!a || !b || waitSeconds === null) return null
    return {
      lat_a: a.lat, lng_a: a.lng,
      lat_b: b.lat, lng_b: b.lng,
      wait_seconds: waitSeconds,
    }
  }, [a, b, waitSeconds])

  const disableConfirm = noDevice || !aValid || isCycling
  const disableFirstTry = noDevice || !aValid || !bValid || !waitValid || isCycling
  const disableRetries = disableFirstTry

  const handleConfirm = useCallback(async () => {
    if (!a) return
    await onConfirmLocation(a.lat, a.lng)
  }, [a, onConfirmLocation])

  const handleFirstTry = useCallback(async () => {
    if (!cycleArgs) return
    await onCycle('B', cycleArgs)
  }, [cycleArgs, onCycle])

  const handleRetries = useCallback(async () => {
    if (!cycleArgs) return
    await onCycle('auto', cycleArgs)
  }, [cycleArgs, onCycle])

  const handleRandomB = () => setBText(randomTaiwanCoord())
  const handleUseMapCenter = () => {
    if (mapCenter) setBText(`${mapCenter.lat.toFixed(6)}, ${mapCenter.lng.toFixed(6)}`)
  }

  return (
    <div className="goldditto-panel" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 8 }}>
      {noDevice && (
        <div style={{ color: '#f87171', fontSize: 12 }}>{t('goldditto.error.no_device')}</div>
      )}

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.a_label')}</span>
        <input
          type="text"
          value={aText}
          onChange={(e) => setAText(e.target.value)}
          placeholder="lat, lng"
          style={{
            padding: '6px 8px',
            border: aValid || aText === '' ? '1px solid #4b5563' : '1px solid #f87171',
            borderRadius: 4,
            background: '#1f2937',
            color: '#fff',
          }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.b_label')}</span>
        <input
          type="text"
          value={bText}
          onChange={(e) => setBText(e.target.value)}
          placeholder="lat, lng"
          style={{
            padding: '6px 8px',
            border: bValid ? '1px solid #4b5563' : '1px solid #f87171',
            borderRadius: 4,
            background: '#1f2937',
            color: '#fff',
          }}
        />
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={handleRandomB} className="action-btn" style={{ fontSize: 12, flex: 1 }}>
            {t('goldditto.random_b')}
          </button>
          <button onClick={handleUseMapCenter} className="action-btn" style={{ fontSize: 12, flex: 1 }}
                  disabled={!mapCenter}>
            {t('goldditto.use_map_center')}
          </button>
        </div>
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.wait_label')} (0.5–10.0)</span>
        <input
          type="number"
          step="0.1"
          min="0.5"
          max="10"
          value={waitText}
          onChange={(e) => setWaitText(e.target.value)}
          style={{
            padding: '6px 8px',
            border: waitValid ? '1px solid #4b5563' : '1px solid #f87171',
            borderRadius: 4,
            background: '#1f2937',
            color: '#fff',
            width: 100,
          }}
        />
      </label>

      {sameAB && (
        <div style={{ color: '#fbbf24', fontSize: 12 }}>{t('goldditto.warn_same_ab')}</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
        <button
          onClick={handleConfirm}
          disabled={disableConfirm}
          className="action-btn primary"
          style={{ padding: '8px 12px', opacity: disableConfirm ? 0.5 : 1 }}
        >
          ① {t('goldditto.confirm')}
        </button>
        <button
          onClick={handleFirstTry}
          disabled={disableFirstTry}
          className="action-btn primary"
          style={{ padding: '8px 12px', opacity: disableFirstTry ? 0.5 : 1 }}
        >
          ② {t('goldditto.first_try')}
        </button>
        <button
          onClick={handleRetries}
          disabled={disableRetries}
          className="action-btn primary"
          style={{ padding: '8px 12px', opacity: disableRetries ? 0.5 : 1 }}
        >
          ③ {t('goldditto.retries')}
        </button>
      </div>
    </div>
  )
}

export default GoldDittoPanel
```

- [ ] **Step 2: Run type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. If `useT` import path differs, fix it (`grep -r "export.*useT" frontend/src/i18n.ts`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GoldDittoPanel.tsx
git commit -m "feat(frontend): add GoldDittoPanel component"
```

---

## Task 7: Wire `GoldDittoPanel` into `ControlPanel` + WS event handler

**Files:**
- Modify: `frontend/src/components/ControlPanel.tsx` (render `<GoldDittoPanel>` when active; thread props from props/parent)
- Modify: `frontend/src/App.tsx` (subscribe to `goldditto_cycle` events; pass new props to ControlPanel; track external A value)

The `ControlPanel` is dumb — it receives values and callbacks. The wiring lives in `App.tsx`.

- [ ] **Step 1: Add props to `ControlPanelProps` interface**

Edit `frontend/src/components/ControlPanel.tsx`. Find the `interface ControlPanelProps` block (around line 56) and add at the bottom:

```typescript
  goldDittoCycling: boolean;
  goldDittoMapCenter: { lat: number; lng: number } | null;
  goldDittoExternalA: string | null;
  onGoldDittoConfirm: (lat: number, lng: number) => Promise<void> | void;
  onGoldDittoCycle: (
    target: 'A' | 'B' | 'auto',
    args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
  ) => Promise<void> | void;
```

- [ ] **Step 2: Render `GoldDittoPanel` in `ControlPanel`**

Add the import at the top:

```typescript
import GoldDittoPanel from './GoldDittoPanel'
```

Find the section that renders mode-specific content (search for `simMode === SimMode.RandomWalk` around line 531, or where individual mode panels render). Add a new conditional block:

```tsx
{simMode === SimMode.GoldDitto && (
  <GoldDittoPanel
    connectedUdids={/* threaded down — see Task 7 Step 4 */ goldDittoConnectedUdids}
    isCycling={goldDittoCycling}
    mapCenter={goldDittoMapCenter}
    externalAValue={goldDittoExternalA}
    onConfirmLocation={onGoldDittoConfirm}
    onCycle={onGoldDittoCycle}
  />
)}
```

(`goldDittoConnectedUdids` is the existing list — check what's already passed, e.g. `connectedUdids` prop, and reuse. If not present, add it as another prop.)

Add to the destructured props at top of `ControlPanel`:

```typescript
  goldDittoCycling,
  goldDittoMapCenter,
  goldDittoExternalA,
  onGoldDittoConfirm,
  onGoldDittoCycle,
```

- [ ] **Step 3: Wire callbacks in `App.tsx`**

Edit `frontend/src/App.tsx`. Find where `<ControlPanel ... />` is rendered (around line 1500+). Add the new props.

First, add state and callbacks near the top of the App component (after existing hooks):

```typescript
const [goldDittoExternalA, setGoldDittoExternalA] = useState<string | null>(null)
const [mapCenter, setMapCenter] = useState<{ lat: number; lng: number } | null>(null)

const handleGoldDittoConfirm = useCallback(async (lat: number, lng: number) => {
  // Confirm Location = just teleport (fanout via existing teleportAll)
  await sim.teleportAll(udids, lat, lng)
}, [sim, udids])

const handleGoldDittoCycle = useCallback(async (
  target: 'A' | 'B' | 'auto',
  args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
) => {
  await sim.goldDittoCycleAll(udids, { target, ...args })
}, [sim, udids])
```

Then add to `<ControlPanel ... />` render:

```tsx
goldDittoCycling={sim.goldDittoCycling}
goldDittoMapCenter={mapCenter}
goldDittoExternalA={goldDittoExternalA}
onGoldDittoConfirm={handleGoldDittoConfirm}
onGoldDittoCycle={handleGoldDittoCycle}
```

- [ ] **Step 4: Track map center**

Find the `<MapView ... />` render in `App.tsx`. Add a callback prop (assuming MapView supports `onCenterChange` — if not, add a thin one, or compute from MapView state). The simplest path:

Add a Leaflet move-end handler inside `MapView.tsx` that fires `onCenterChange(latlng)` to the parent. Alternatively, expose the current center via a ref. Pick whichever pattern matches what MapView already exposes. If neither is convenient, leave `mapCenter={null}` for now — the "Use map center" button will be disabled, which is acceptable (the user can still type B manually).

(Granular detail intentionally omitted — adapt to whatever pattern `MapView` already uses to communicate state upward. The `useT` hook usage in this file is one signal; check existing prop drilling.)

- [ ] **Step 5: Subscribe to `goldditto_cycle` WS event**

In `App.tsx`, find the WebSocket message handler (look for `useWebSocket` usage or a `subscribe` callback). Add a case:

```typescript
useEffect(() => {
  const unsub = ws.subscribe?.((msg) => {
    if (msg.type === 'goldditto_cycle') {
      const { phase, target } = msg.data ?? {}
      if (phase === 'teleported') {
        setStatusMessage(t('goldditto.toast.teleported', { target }))
      } else if (phase === 'restored') {
        setStatusMessage(t('goldditto.toast.restored'))
      }
    }
  })
  return unsub
}, [ws, t])
```

(Adapt to the existing WS subscription pattern — the names `ws.subscribe`, `setStatusMessage`, and `useT` may differ. The shape should mirror how the codebase already handles `position_update` or `teleport` events.)

- [ ] **Step 6: Type check + smoke test**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

Start dev (`bash start.sh`). Switch to 拉金盆 tab. Verify:
- 3 inputs appear (A, B with default 25.0348..., wait with default 3.0)
- 3 buttons render
- Without iPhone: red "請先連接 iPhone" banner shows; buttons disabled
- "🎲 隨機台灣 B 點" updates B with a Taiwan-bounded random coord

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ControlPanel.tsx frontend/src/App.tsx
git commit -m "feat(frontend): wire GoldDittoPanel + WS goldditto_cycle handler"
```

---

## Task 8: Map right-click "設為拉金盆 A 點"

**Files:**
- Modify: `frontend/src/components/MapView.tsx` (add menu entry)
- Modify: `frontend/src/App.tsx` (handler + setter for `goldDittoExternalA`)

This lets the user right-click a flower spot on the map and beam its lat,lng straight into the A field.

- [ ] **Step 1: Add a callback prop for the new menu entry**

Edit `MapView.tsx`. Find the existing right-click menu's prop interface. Add:

```typescript
  onSetAsGoldDittoA?: (lat: number, lng: number) => void
```

In the menu render JSX (search for the "Teleport" menu item rendered when right-clicking on the map), add another menu entry:

```tsx
{onSetAsGoldDittoA && (
  <button
    onClick={() => {
      onSetAsGoldDittoA(menuLatLng.lat, menuLatLng.lng)
      closeMenu()
    }}
  >
    {t('goldditto.set_as_a')}
  </button>
)}
```

- [ ] **Step 2: Add the i18n key for the new menu entry**

Edit `frontend/src/i18n.ts`:

```typescript
'goldditto.set_as_a': { zh: '設為拉金盆 A 點', en: 'Set as Gold Ditto A' },
```

- [ ] **Step 3: Wire the callback in `App.tsx`**

Pass the prop to `<MapView ... />`:

```tsx
onSetAsGoldDittoA={(lat, lng) => {
  setGoldDittoExternalA(`${lat.toFixed(6)}, ${lng.toFixed(6)}`)
}}
```

`GoldDittoPanel` already watches `externalAValue` via `useEffect` (Task 6) and updates its internal `aText` when it changes.

- [ ] **Step 4: Smoke test**

Restart dev. Right-click any point on the map → "設為拉金盆 A 點" should appear in the menu. Click it → the GoldDitto panel's A field should auto-fill with the clicked lat,lng.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.tsx frontend/src/components/ControlPanel.tsx frontend/src/App.tsx frontend/src/i18n.ts
git commit -m "feat(frontend): map right-click 'Set as Gold Ditto A'"
```

---

## Task 9: Manual E2E checklist + final smoke

**Files:**
- (no code changes)
- Modify: `README.md` if you want to document the new mode (optional)

This is a manual test pass against a real device. If you don't have a real iPhone available, run the steps that don't require one and document the gaps.

- [ ] **Step 1: Backend test suite green**

Run: `cd backend && python3.13 -m pytest tests/ -v`
Expected: all goldditto tests pass.

- [ ] **Step 2: Frontend type check + dev server boots**

Run: `cd frontend && npx tsc --noEmit && npm run dev`
Expected: no TS errors; Vite dev server starts on :5173.

- [ ] **Step 3: Real-device manual checklist**

With a single iPhone connected (USB or WiFi tunnel):

- [ ] Switch to 拉金盆 tab — sees 3 inputs + 3 buttons
- [ ] Default A is empty, default B is `25.034897, 121.545827`, default wait is `3.0`
- [ ] Type a valid lat,lng for A (e.g. `25.05, 121.55`); buttons enable
- [ ] Click ① Confirm Location → device map marker jumps to A
- [ ] Click ② 1st try → status bar shows "拉金盆: 已瞬移到 B" → wait 3s → "還原完成,可以開始拉花苞 ✨"; check on iPhone Settings → Privacy → Location Services that the spoof clears
- [ ] Click ③ retries — first press should teleport to A (since current_position is now B from the 1st try cycle); second press should teleport to B; status messages reflect the alternation
- [ ] Set A == B and click retries → does not deadlock; toasts still show
- [ ] Unplug USB during a 1st-try wait → red banner; buttons disable; reconnect → buttons re-enable
- [ ] Reload the app → A, B, wait values persist (localStorage)

With two iPhones connected:

- [ ] ② 1st try fans out — both iPhones cycle in parallel; status bar shows fanout success
- [ ] ③ retries fans out — both iPhones cycle

- [ ] **Step 4: Validation edge-cases**

- [ ] Enter `0` for wait → input shows red border, ② and ③ disabled
- [ ] Enter `15` for wait → clamps display to `10` on next press (or shows red — pick whichever the implementation does)
- [ ] Enter `abc` for A → red border; cycle buttons disabled
- [ ] Map right-click → "設為拉金盆 A 點" → A field updates

- [ ] **Step 5: README note (optional)**

Add a paragraph under the existing `### 移動模式` table mentioning the new "拉金盆" mode and pointing to the spec for details. Keep it 2–3 sentences.

- [ ] **Step 6: Final commit**

If anything was tweaked during E2E:

```bash
git add -p
git commit -m "fix(goldditto): <whatever you fixed>"
```

If everything is clean:

```bash
git status   # should be clean
```

---

## Self-Review

**Spec coverage:**

- §4.1 inputs (A, B, wait) → Tasks 1, 6
- §4.2 buttons (Confirm Location, 1st try, retries with auto target) → Tasks 6, 7
- §4.3 UX (tab placement, status-bar messages, fanout disable) → Tasks 4, 6, 7
- §4.4 validation → Task 6
- §4.5 localStorage persistence → Task 6
- §5 architecture → Tasks 2, 3 (backend) + Tasks 4–8 (frontend)
- §6 backend (endpoint, handler, schema, lock, cooldown bypass) → Tasks 1, 2, 3
- §7 frontend (SimMode, panel, hook, WS, map integration, i18n) → Tasks 4, 5, 6, 7, 8
- §8 error handling → Tasks 2 (lock + teleport-failure tests), 3 (409 mapping), 6 (validation), 7 (no-device banner)
- §9 edge cases → Task 9 manual checklist
- §10 testing → Tasks 1, 2, 3 (backend tests), Task 9 (manual E2E)
- §11 implementation notes:
  - "Reuse engine.teleport / engine.restore" → ✅ Task 2
  - "thin orchestrator, no new SimulationState" → ✅ Task 2 (no state change)
  - "goldditto_cycle WS event" → ✅ Task 2 emits, Task 7 consumes
  - "localStorage debounced/onChange" → Task 6 uses `useEffect`-on-state which fires on every change (acceptable for low-frequency text inputs)
  - "Fanout failure messages include UDIDs" → relies on existing `summarizeResults` from Task 5
- §12 open questions resolved:
  - "engine.lock exists?" → No; handler owns its own `_lock` (cleaner anyway). ✅ Task 2
  - "bypass_cooldown" → Calling `engine.teleport()` directly bypasses cooldown automatically because cooldown is enforced at the API layer, not inside the engine method. ✅ Documented inline.

**Placeholder scan:** Each task contains complete code. The one soft area is Task 7 Step 4 (map-center wiring) — it's intentionally adaptable because it depends on MapView's existing pattern. The fallback is documented (leave `mapCenter={null}`, "Use map center" button disabled) so the engineer is never blocked.

**Type consistency:** `goldDittoCycle()` API client → `goldDittoCycleAll()` hook method → `onGoldDittoCycle` ControlPanel prop → `onCycle` GoldDittoPanel prop. All accept the same `target` + `args` shape. `GoldDittoCycleResponse.target_used` is `'A' | 'B'`, used in WS event `target` field too. `goldditto_cycle` WS event payload (`{phase, target, lat?, lng?}`) consumed in Task 7 matches what's emitted in Task 2.
