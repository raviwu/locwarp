# Clean-Arch Phase 3 — Carve Pure Movement Math into `domain/movement.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the three pieces of pure movement math out of the 955-line `core/simulation_engine.py` into a new pure inner-ring module `backend/domain/movement.py`, guarded by a new enforced domain-purity import-linter contract, with zero external behavior change.

**Architecture:** Pragmatic Hexagonal-lite (see `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md` §4–5). Phase 3 lands three extractions — `EtaTracker` (verbatim move), the snapshot **serializer** (`build_resume_snapshot` pure assembly), and the `RouteInterpolator` **relocation** (services→domain) — each preceded by a characterization net, each one commit. The engine keeps every entrypoint, all stop/pause/cancel signalling, and the full `_move_along_route` orchestration; only referentially-transparent math leaves.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio, import-linter (`lint-imports`), pydantic (models).

## Global Constraints

Every task's requirements implicitly include this section.

- **Behavior / API freeze.** No external HTTP / WS / IPC change. WS payloads stay **deep-equal JSON**. The full backend pytest suite stays green after **EVERY** commit. Pin the exact pre-change baseline first: `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1` (currently **849**; it GROWS as char nets are added — never let an existing test drop or change assertion).
- **`resume_from_snapshot` stays warn-and-return** on unknown/empty/None kind (owner decision 2026-06-22, behavior-freeze governs over the spec's literal "RAISES on miss"). Do **NOT** change it; the existing `tests/test_engine_snapshot_resume_char.py` MUST stay green untouched.
- **Verbatim moves only** for `EtaTracker` and `RouteInterpolator`: copy the class body byte-for-byte, no math edit, no "while I'm here" cleanup (the dead `EtaTracker.start_time` field stays; the `route_service.py` duplicate haversine stays). Bit-exact.
- **Method signatures unchanged.** `capture_resumable_snapshot()`, `resume_from_snapshot()`, and `_move_along_route()` remain instance methods on `SimulationEngine` (api/main/infra and `*_cov.py` tests call/monkeypatch them on the instance).
- **Re-export shims preserve public import paths:** `from core import EtaTracker`, `from core.simulation_engine import EtaTracker`, and `from services.interpolator import RouteInterpolator` MUST all keep working.
- **`domain/movement.py` imports stdlib + pydantic(models) only.** Guarded by the new `no-domain-imports-outer` contract (Task 1). `domain → models.schemas` is allowed (models is pure pydantic); `domain → {core, services, api, infra, fastapi}` is forbidden.
- **One extraction per commit, each guarded by a characterization net written and verified green FIRST** (danger-zone-test-first; `simulation_engine.py` movers have no direct tests).
- **DEFERRED — explicitly out of scope** (document, do not start): the `RouteService` `core→services` edge at `simulation_engine.py:19` (owner deferred 2026-06-22 — needs bootstrap injection, a separate ring fix); consolidating `services/route_service.py`'s duplicate `_haversine_m` (bit-exact drift risk); adding an `EtaTracker` ClockPort seam; adding a `no-core-imports-services` contract (blocked on the deferred `RouteService` edge — note it, don't add it).
- **Git:** work on branch `chore/clean-arch-p3` off `main`. Personal repo, direct-to-branch commits, identity auto-set by includeIf (never pass `-c user.email`). Merge after a light hardware smoke (Task 8).

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `backend/domain/movement.py` | **NEW** pure movement-math module: `EtaTracker`, `build_resume_snapshot`, `RouteInterpolator`. stdlib + pydantic only. | 3, 5, 7 |
| `backend/.importlinter` | Add `no-domain-imports-outer` forbidden contract. | 1 |
| `backend/tests/test_import_contracts_enforced.py` | Add the 6th contract to `REQUIRED_CONTRACTS`; rename the `..._all_five_contracts` test count-agnostic. | 1 |
| `backend/core/simulation_engine.py` | Lose the `EtaTracker` body + the now-dead `from datetime import ...` (→ re-export shim), the snapshot-assembly literal (→ delegate to `build_resume_snapshot`), and the `services.interpolator` import (→ `domain.movement`). Keeps all orchestration + method signatures. | 3, 5, 7 |
| `backend/services/interpolator.py` | Becomes a thin re-export shim of `domain.movement.RouteInterpolator`. | 7 |
| `backend/core/joystick.py`, `backend/core/random_walk.py` | Flip `RouteInterpolator` import to `domain.movement` (kills their `core→services` edge). | 7 |
| `backend/tests/test_eta_tracker_char.py` | **NEW** char net for `EtaTracker`. | 2 |
| `backend/tests/test_snapshot_capture_char.py` | **NEW** char net for `capture_resumable_snapshot` (the build side). | 4 |
| `backend/tests/test_interpolator_golden.py` | **NEW** bit-exact golden vectors + a deterministic `_move_along_route` integration char. | 6 |

**Unchanged callers relying on the freeze** (verify, don't touch): `api/device.py:820/837`, `main.py:559/619/633/641`, `infra/device/tunnel_restart.py:117` (call `capture_resumable_snapshot` / `resume_from_snapshot`); `core/navigator.py`, `core/multi_stop.py`, `core/random_walk.py`, `core/route_loop.py` (call `engine._move_along_route`); `services/cooldown.py:10` + `tests/test_*_cov.py` (import `RouteInterpolator` via the shim).

---

## Decisions baked in (owner-approved 2026-06-22)

1. **resume-on-miss:** keep **warn-and-return** (behavior-freeze wins). Spec's "RAISES on miss" is superseded — noted, not implemented.
2. **core→services scope:** **only** the `RouteInterpolator` relocation (Task 7). `RouteService` edge deferred.
3. **Sequencing:** `EtaTracker` → snapshot serializer → interpolation relocation **LAST** (reconciles the spec's two statements: "interpolation then snapshot" vs "float interpolation extracted LAST + bit-exact" — the latter is the more specific instruction and is the wider-blast-radius/bit-exact step, so it lands last with EtaTracker+snapshot nets acting as green backstops).

---

### Task 1: Establish the `no-domain-imports-outer` gate (enforced, first)

Add the domain-purity contract **before** any extraction so `domain/movement.py` is guarded as it is built. `domain/` is already clean (verified: only intra-domain + pydantic imports), so the contract passes immediately.

**Files:**
- Modify: `backend/.importlinter` (append a contract)
- Modify: `backend/tests/test_import_contracts_enforced.py:8-12` (add 6th contract)
- Test: `backend/tests/test_import_contracts_enforced.py` (existing)

**Interfaces:**
- Produces: a 6th enforced contract `no-domain-imports-outer`; later tasks rely on it failing CI if `domain/movement.py` imports an outer ring.

- [ ] **Step 1: Make the enforced-contracts test require the 6th contract + rename it count-agnostic (RED)**

Edit `backend/tests/test_import_contracts_enforced.py`: add the 6th member; rename the now-misnamed `test_importlinter_config_declares_all_five_contracts` to a count-agnostic name; fix the module docstring (line 1 `All five ...` → `All required ...`). The test body is unchanged (it iterates `REQUIRED_CONTRACTS` dynamically).

```python
"""All required import-linter contracts must be ENFORCED and pass (the architecture gate)."""
# ...
REQUIRED_CONTRACTS = {
    "no-core-imports-api", "no-services-imports-fastapi", "no-infra-imports-api",
    "no-api-imports-api", "no-api-imports-main", "no-domain-imports-outer",
}


def test_importlinter_config_declares_all_required_contracts():  # renamed from ..._all_five_contracts
    cfg = (BACKEND / ".importlinter").read_text()
    for name in REQUIRED_CONTRACTS:
        assert f"contract:{name}]" in cfg, f"missing contract: {name}"
    for pkg in ("api", "core", "services", "models", "domain", "infra"):
        assert pkg in cfg, f"root_packages missing {pkg}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py::test_importlinter_config_declares_all_required_contracts -q`
Expected: FAIL — `missing contract: no-domain-imports-outer`.

- [ ] **Step 3: Add the contract to `.importlinter`**

Append to `backend/.importlinter`:

```ini
# Phase 3 (Task 1): ENFORCED from the start of Phase 3. domain/ is the pure
# inner ring (movement.py + events.py + errors.py + ports/) and must import
# stdlib + pydantic ONLY. `models` is intentionally NOT forbidden — it is pure
# pydantic schema and is an allowed inward dep until models relocate into
# domain/ in a later phase. This gate guards the Phase-3 extractions: any
# accidental domain -> core/services/api/infra/fastapi import fails CI.
# domain shares no descendants with the forbidden set, so `forbidden` is correct.
[importlinter:contract:no-domain-imports-outer]
name = Domain must not import outer rings
type = forbidden
source_modules =
    domain
forbidden_modules =
    core
    services
    api
    infra
    fastapi
```

- [ ] **Step 4: Run the architecture gate to verify 6 contracts, 0 broken**

Run: `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q`
Expected: PASS (both tests). The `lint-imports` run prints `Contracts: 6 kept, 0 broken`.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: baseline green (849), 0 failures.

```bash
git add backend/.importlinter backend/tests/test_import_contracts_enforced.py
git commit -m "test(arch): enforce no-domain-imports-outer — Phase-3 domain-purity gate"
```

---

### Task 2: Characterize `EtaTracker` (net before move)

Pin `EtaTracker`'s observable behavior against the **current** location (`core.simulation_engine`) so the Task-3 verbatim move is provably behavior-preserving. The net imports via the stable public path `from core import EtaTracker` and derives the module to monkeypatch from `EtaTracker.__module__`, so it survives the move with **zero churn**.

**Files:**
- Create: `backend/tests/test_eta_tracker_char.py`

**Interfaces:**
- Consumes: `core.EtaTracker` (public re-export), `EtaTracker.__module__` (for the `datetime` monkeypatch target).
- Produces: the green net Task 3 must keep green after the move.

- [ ] **Step 1: Write the characterization test**

Create `backend/tests/test_eta_tracker_char.py`:

```python
"""Characterize EtaTracker before it moves to domain/movement.py (Phase 3, Task 2).

Imports via the stable public path `from core import EtaTracker` and monkeypatches
`datetime` on EtaTracker's OWN module (resolved via EtaTracker.__module__), so this
net passes identically before the move (core.simulation_engine) and after it
(domain.movement) with no edit.
"""
import importlib
from datetime import datetime, timezone

import pytest

from core import EtaTracker


def test_initial_state_is_zeroed():
    t = EtaTracker()
    assert (t.total_distance, t.traveled, t.speed_mps) == (0.0, 0.0, 0.0)
    # total_distance == 0 -> progress short-circuits to 1.0
    assert t.progress == 1.0
    assert t.eta_seconds == 0.0
    assert t.eta_arrival == ""
    assert t.distance_remaining == 0.0


def test_start_clamps_speed_and_resets_traveled():
    t = EtaTracker()
    t.traveled = 50.0
    t.start(total_distance=1000.0, speed_mps=0.0)  # 0 -> clamped to 0.001
    assert t.total_distance == 1000.0
    assert t.traveled == 0.0
    assert t.speed_mps == 0.001


def test_progress_and_distance_remaining_math():
    t = EtaTracker()
    t.start(1000.0, 10.0)
    t.update(250.0)
    assert t.progress == 0.25
    assert t.distance_remaining == 750.0
    assert t.eta_seconds == 75.0  # 750 / 10


def test_progress_clamps_to_one_when_overshot():
    t = EtaTracker()
    t.start(100.0, 10.0)
    t.update(150.0)
    assert t.progress == 1.0
    assert t.distance_remaining == 0.0   # max(100-150, 0)
    assert t.eta_seconds == 0.0


def test_eta_arrival_empty_when_no_time_remaining():
    t = EtaTracker()
    t.start(100.0, 10.0)
    t.update(100.0)            # eta_seconds == 0 -> ''
    assert t.eta_arrival == ""


def test_eta_arrival_is_now_plus_eta_seconds(monkeypatch):
    """eta_arrival = datetime.now(utc) + timedelta(eta_seconds), iso 'seconds'."""
    fixed = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return fixed

    mod = importlib.import_module(EtaTracker.__module__)
    monkeypatch.setattr(mod, "datetime", _FixedDatetime)

    t = EtaTracker()
    t.start(1000.0, 10.0)
    t.update(0.0)             # eta_seconds == 100.0
    assert t.eta_arrival == "2026-06-22T12:01:40+00:00"
```

- [ ] **Step 2: Run it against current code to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_eta_tracker_char.py -q`
Expected: PASS (6 tests) — pins current behavior.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_eta_tracker_char.py
git commit -m "test(engine): characterize EtaTracker before domain extraction"
```

---

### Task 3: Move `EtaTracker` verbatim to `domain/movement.py`

**Files:**
- Create: `backend/domain/movement.py`
- Modify: `backend/core/simulation_engine.py` (remove the `EtaTracker` definition — `# ── ETA Tracker ──` header through `distance_remaining`, before the `# ── Simulation Engine ──` header — + the dead `from datetime import …`; add the re-export import)
- Test: `backend/tests/test_eta_tracker_char.py` (must stay green, untouched)

**Interfaces:**
- Produces: `domain.movement.EtaTracker`; `core.simulation_engine` re-exports it (so `core.EtaTracker` and line-149 `EtaTracker()` keep working).

- [ ] **Step 1: Create `domain/movement.py` with `EtaTracker` moved verbatim**

Create `backend/domain/movement.py`:

```python
"""Pure movement math for the simulation engine (clean-arch Phase 3).

This is the pure inner-ring home for referentially-transparent movement
helpers extracted from core/simulation_engine.py. It imports stdlib + pydantic
(models.schemas) ONLY and is guarded by the `no-domain-imports-outer`
import-linter contract.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


class EtaTracker:
    """Tracks progress and estimates time of arrival for route-based movement."""

    def __init__(self) -> None:
        self.total_distance: float = 0.0
        self.traveled: float = 0.0
        self.speed_mps: float = 0.0
        self.start_time: float = 0.0

    def start(self, total_distance: float, speed_mps: float) -> None:
        """Initialise the tracker at the beginning of a route."""
        self.total_distance = total_distance
        self.traveled = 0.0
        self.speed_mps = max(speed_mps, 0.001)  # avoid division by zero
        self.start_time = time.monotonic()

    def update(self, traveled: float) -> None:
        """Update the distance traveled so far."""
        self.traveled = traveled

    @property
    def progress(self) -> float:
        """Return completion as a fraction 0.0 .. 1.0."""
        if self.total_distance <= 0:
            return 1.0
        return min(self.traveled / self.total_distance, 1.0)

    @property
    def eta_seconds(self) -> float:
        """Estimated seconds remaining."""
        remaining = self.distance_remaining
        if self.speed_mps <= 0:
            return 0.0
        return remaining / self.speed_mps

    @property
    def eta_arrival(self) -> str:
        """ISO-8601 estimated arrival time."""
        secs = self.eta_seconds
        if secs <= 0:
            return ""
        arrival = datetime.now(timezone.utc) + timedelta(seconds=secs)
        return arrival.isoformat(timespec="seconds")

    @property
    def distance_remaining(self) -> float:
        """Meters still to travel."""
        return max(self.total_distance - self.traveled, 0.0)
```

- [ ] **Step 2: Replace the `EtaTracker` body in `simulation_engine.py` with a re-export shim**

In `backend/core/simulation_engine.py`, delete the `EtaTracker` definition — from the `# ── ETA Tracker ──` comment header through the end of the `distance_remaining` property, up to (not including) the `# ── Simulation Engine ──` header — and add the re-export import. Also drop the now-dead `from datetime import datetime, timedelta, timezone` import: after `EtaTracker` leaves, `datetime`/`timedelta`/`timezone` have **zero** remaining references in this file (they were used ONLY inside `EtaTracker.eta_arrival`). Keep `import time` — it stays live as the clock-seam default (`clock: Callable[[], float] = time.monotonic`).

Verify the datetime trio is dead before removing the import:

Run: `cd backend && grep -nE 'datetime|timedelta|timezone' core/simulation_engine.py`
Expected (after deleting the EtaTracker body): only the `from datetime import ...` line itself — no usage lines. If any usage remains, keep the import.

After the edit, the import block / class-region reads:

```python
from core.restore import RestoreHandler
from core.goldditto import GoldDittoHandler

# EtaTracker moved to domain/movement.py (Phase 3); re-exported here so
# `core.EtaTracker`, `from core.simulation_engine import EtaTracker`, and the
# line-149 `self.eta_tracker = EtaTracker()` construction keep working.
from domain.movement import EtaTracker

logger = logging.getLogger(__name__)


# ── Simulation Engine ───────────────────────────────────────────────────

class SimulationEngine:
```

- [ ] **Step 3: Run the EtaTracker char net (still green, unchanged) + the snapshot/resume nets**

Run: `cd backend && .venv/bin/python -m pytest tests/test_eta_tracker_char.py tests/test_engine_clock_seam.py tests/test_engine_snapshot_resume_char.py -q`
Expected: PASS — the net is location-agnostic (`EtaTracker.__module__` now resolves to `domain.movement`), construction via `core` still works.

- [ ] **Step 4: Run the architecture gate (domain still pure) + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q && .venv/bin/python -m pytest -q`
Expected: `6 kept, 0 broken`; full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/domain/movement.py backend/core/simulation_engine.py
git commit -m "refactor(domain): move EtaTracker to domain/movement.py (re-export shim in core)"
```

---

### Task 4: Characterize `capture_resumable_snapshot` (net before extracting the serializer)

Pin the full snapshot **build** behavior — the **9 base keys + the optional `active_speed_profile`** (present iff truthy) for all four kinds, the `seg_for_resume` branch, and the None-when-not-resumable gate — by setting engine fields white-box and calling `capture_resumable_snapshot()`. `resume_from_snapshot` is already covered by `test_engine_snapshot_resume_char.py` and is **not touched**.

**Files:**
- Create: `backend/tests/test_snapshot_capture_char.py`

**Interfaces:**
- Consumes: `SimulationEngine` internal fields (`state`, `_last_sim_kind`, `_last_sim_args`, `current_position`, `segment_index`, `_user_waypoint_next`, `lap_count`, `distance_traveled`, `_speed_was_applied`, `_random_walk_count`, `_active_speed_profile`).
- Produces: the green net Task 5 keeps deep-equal-green after delegating to `build_resume_snapshot`.

- [ ] **Step 1: Write the characterization test**

Create `backend/tests/test_snapshot_capture_char.py`:

```python
"""Characterize capture_resumable_snapshot's dict assembly before the pure
serializer is extracted to domain/movement.py (Phase 3, Task 4).

White-box: sets the engine fields capture reads, then asserts the exact snapshot
dict. Pins: the 9 base keys + optional active_speed_profile, the seg_for_resume
kind branch (multi_stop/start_loop use _user_waypoint_next-1; navigate/random_walk
use segment_index), the active_speed_profile key (present iff truthy), and the
None-when-not-resumable gate.

NOTE: capture_resumable_snapshot short-circuits to None when `_last_sim_args` is
falsy (simulation_engine.py:507), so every armed case passes a NON-EMPTY args dict.
"""
import pytest

from models.schemas import Coordinate, SimulationState
from tests._engine_harness import make_engine


def _arm(eng, *, state, kind, args, seg=0, uwn=0, lap=0, dist=0.0,
         speed_applied=False, rw=0, profile=None, pos=(25.0, 121.0)):
    eng.state = state
    eng._last_sim_kind = kind
    eng._last_sim_args = args
    eng.current_position = Coordinate(lat=pos[0], lng=pos[1]) if pos else None
    eng.segment_index = seg
    eng._user_waypoint_next = uwn
    eng.lap_count = lap
    eng.distance_traveled = dist
    eng._speed_was_applied = speed_applied
    eng._random_walk_count = rw
    eng._active_speed_profile = profile
    return eng


def test_navigate_snapshot_uses_segment_index():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="navigate",
         args={"lat": 1.0, "lng": 2.0}, seg=7, uwn=3, dist=123.5)
    snap = eng.capture_resumable_snapshot()
    assert snap == {
        "kind": "navigate",
        "args": {"lat": 1.0, "lng": 2.0},
        "current_pos": (25.0, 121.0),
        "segment_index": 7,          # navigate -> segment_index, NOT uwn-1
        "lap_count": 0,
        "user_waypoint_next": 3,
        "distance_traveled": 123.5,
        "speed_was_applied": False,
        "random_walk_count": 0,
    }
    assert "active_speed_profile" not in snap   # falsy profile -> key absent


def test_multi_stop_snapshot_uses_user_waypoint_next_minus_one():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.MULTI_STOP, kind="multi_stop",
         args={"stops": []}, seg=99, uwn=4)
    snap = eng.capture_resumable_snapshot()
    assert snap["segment_index"] == 3   # max(0, uwn-1) = 3, NOT seg=99
    assert snap["user_waypoint_next"] == 4


def test_start_loop_snapshot_uses_user_waypoint_next_minus_one_floored():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.LOOPING, kind="start_loop",
         args={"x": 1}, seg=12, uwn=0)   # non-empty args: dodge the falsy short-circuit
    snap = eng.capture_resumable_snapshot()
    assert snap["segment_index"] == 0   # max(0, 0-1) floors to 0


def test_random_walk_snapshot_uses_segment_index_and_count():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.RANDOM_WALK, kind="random_walk",
         args={"radius": 500}, seg=5, uwn=9, rw=2)
    snap = eng.capture_resumable_snapshot()
    assert snap["segment_index"] == 5
    assert snap["random_walk_count"] == 2


def test_active_speed_profile_present_when_truthy():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="navigate",
         args={"x": 1}, profile={"speed_mps": 30.0, "jitter": 0.0})
    snap = eng.capture_resumable_snapshot()
    assert snap["active_speed_profile"] == {"speed_mps": 30.0, "jitter": 0.0}


def test_current_pos_none_when_no_position():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="navigate",
         args={"x": 1}, pos=None)
    snap = eng.capture_resumable_snapshot()
    assert snap["current_pos"] is None


@pytest.mark.parametrize("state", [SimulationState.IDLE, SimulationState.PAUSED,
                                   SimulationState.TELEPORTING])
def test_returns_none_when_not_in_a_resumable_state(state):
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=state, kind="navigate", args={"x": 1})
    assert eng.capture_resumable_snapshot() is None


def test_returns_none_when_no_last_sim_kind():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="", args={})
    assert eng.capture_resumable_snapshot() is None
```

- [ ] **Step 2: Run against current code to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_snapshot_capture_char.py -q`
Expected: PASS. If a `SimulationState` member name differs (e.g. no `TELEPORTING`), read `models/schemas.py` and use the real non-resumable members — keep three of them.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_snapshot_capture_char.py
git commit -m "test(engine): characterize capture_resumable_snapshot dict assembly"
```

---

### Task 5: Extract the pure `build_resume_snapshot` serializer into `domain/movement.py`

Move the pure dict-assembly (the `seg_for_resume` rule + key-absence semantics) out of `capture_resumable_snapshot`; the engine keeps the impure state-gate and the `current_position` read. `resume_from_snapshot` is **unchanged** (warn-and-return stays).

**Files:**
- Modify: `backend/domain/movement.py` (add `build_resume_snapshot`)
- Modify: `backend/core/simulation_engine.py:491-533` (delegate)
- Test: `backend/tests/test_snapshot_capture_char.py` + `tests/test_engine_snapshot_resume_char.py` (stay green)

**Interfaces:**
- Produces: `domain.movement.build_resume_snapshot(*, kind, args, current_pos, segment_index, user_waypoint_next, lap_count, distance_traveled, speed_was_applied, random_walk_count, active_speed_profile) -> dict`.

- [ ] **Step 1: Add `build_resume_snapshot` to `domain/movement.py`**

Append to `backend/domain/movement.py`:

```python
def build_resume_snapshot(
    *,
    kind: str,
    args: dict,
    current_pos: tuple[float, float] | None,
    segment_index: int,
    user_waypoint_next: int,
    lap_count: int,
    distance_traveled: float,
    speed_was_applied: bool,
    random_walk_count: int,
    active_speed_profile: dict | None,
) -> dict:
    """Pure assembly of the resume-snapshot dict.

    Encodes two behaviors that used to live inline in
    ``SimulationEngine.capture_resumable_snapshot``:

    * the ``seg_for_resume`` kind rule — multi_stop / start_loop resume off
      ``user_waypoint_next - 1`` (the stable leg index) because the inner
      ``_move_along_route`` loop clobbers ``segment_index`` with the densified
      coord index; navigate / random_walk keep ``segment_index``;
    * the ``active_speed_profile`` key is present **iff** the profile is truthy
      (preserves the exclude_unset/exclude_none deep-equal contract).

    No engine / running-loop state — primitives in, dict out.
    """
    if kind in ("multi_stop", "start_loop"):
        seg_for_resume = max(0, int(user_waypoint_next) - 1)
    else:
        seg_for_resume = int(segment_index)
    snap = {
        "kind": kind,
        "args": dict(args),
        "current_pos": current_pos,
        "segment_index": seg_for_resume,
        "lap_count": int(lap_count),
        "user_waypoint_next": int(user_waypoint_next),
        "distance_traveled": float(distance_traveled),
        "speed_was_applied": bool(speed_was_applied),
        "random_walk_count": int(random_walk_count),
    }
    if active_speed_profile:
        snap["active_speed_profile"] = dict(active_speed_profile)
    return snap
```

- [ ] **Step 2: Delegate from `capture_resumable_snapshot`**

In `backend/core/simulation_engine.py`, add `build_resume_snapshot` to the existing domain import and replace the body of `capture_resumable_snapshot` (lines 491-533) so the impure gate stays and the assembly delegates:

```python
from domain.movement import EtaTracker, build_resume_snapshot
```

```python
    def capture_resumable_snapshot(self) -> dict | None:
        """Snapshot enough state for another engine to continue this
        sim from the current position. Used by the watchdog when the
        primary device disconnects and a follower needs to be promoted
        to leader without restarting the simulation from scratch.

        Returns None when there's nothing meaningful to resume (idle,
        joystick, paused, etc).
        """
        if self.state not in (
            SimulationState.NAVIGATING,
            SimulationState.LOOPING,
            SimulationState.MULTI_STOP,
            SimulationState.RANDOM_WALK,
        ):
            return None
        if not self._last_sim_kind or not self._last_sim_args:
            return None
        cur = self.current_position
        return build_resume_snapshot(
            kind=self._last_sim_kind,
            args=self._last_sim_args,
            current_pos=(cur.lat, cur.lng) if cur else None,
            segment_index=self.segment_index,
            user_waypoint_next=self._user_waypoint_next,
            lap_count=self.lap_count,
            distance_traveled=self.distance_traveled,
            speed_was_applied=self._speed_was_applied,
            random_walk_count=self._random_walk_count,
            active_speed_profile=self._active_speed_profile,
        )
```

- [ ] **Step 3: Run the capture char net + the untouched resume net + clock seam**

Run: `cd backend && .venv/bin/python -m pytest tests/test_snapshot_capture_char.py tests/test_engine_snapshot_resume_char.py tests/test_multi_stop_cov.py -q`
Expected: PASS — snapshot dict deep-equal identical (the multi_stop `*_cov` test also asserts the shape).

- [ ] **Step 4: Architecture gate + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q && .venv/bin/python -m pytest -q`
Expected: `6 kept, 0 broken`; full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/domain/movement.py backend/core/simulation_engine.py
git commit -m "refactor(domain): extract build_resume_snapshot serializer into domain/movement.py"
```

---

### Task 6: Bit-exact golden vectors + a deterministic `_move_along_route` char (net before relocation)

Before relocating `RouteInterpolator`, pin its pure math bit-exact, and close GAP-2 with a deterministic `_move_along_route` integration char (jitter disabled). **First survey** `tests/test_interpolator_cov.py` — extend/duplicate-avoid; add ONLY the bit-exact golden vectors it lacks.

**Files:**
- Create: `backend/tests/test_interpolator_golden.py`
- Read first: `backend/tests/test_interpolator_cov.py` (avoid duplicate coverage)

**Interfaces:**
- Consumes: `services.interpolator.RouteInterpolator` (current path), `core.simulation_engine.SimulationEngine._move_along_route`.

- [ ] **Step 1: Survey existing interpolator coverage**

Run: `cd backend && .venv/bin/python -m pytest tests/test_interpolator_cov.py -q && sed -n '1,40p' tests/test_interpolator_cov.py`
Note which methods already have exact-value assertions; the golden file below only needs the **bit-exact frozen-vector** assertions if `*_cov` asserts looser properties.

- [ ] **Step 2: Write the golden + integration char test**

Create `backend/tests/test_interpolator_golden.py`. The float literals below are **characterization values captured from the current implementation** (run-once, freeze) — asserted with exact `==`, not `approx`. They are pre-filled from a capture on this repo's `backend/.venv` (Python 3.13); the SAME interpreter runs post-move, so they hold bit-exact across the verbatim relocation. Step 3 re-confirms them.

```python
"""Bit-exact golden vectors for RouteInterpolator + a deterministic
_move_along_route integration char (Phase 3, Task 6). Guards the verbatim
services->domain relocation in Task 7: the math must round-trip identically.

Float literals are CAPTURED from the current implementation (run-once, freeze),
asserted with exact `==`. They are NOT hand-derived.
"""
import asyncio
import random

import pytest

from models.schemas import Coordinate
from services.interpolator import RouteInterpolator as R
from tests._engine_harness import FakeClock, SteppedSleep, make_engine


def test_haversine_golden():
    assert R.haversine(25.0339, 121.5645, 25.0478, 121.5170) == 5028.724286241932


def test_bearing_golden():
    assert R.bearing(25.0, 121.0, 25.0, 121.001) == 89.99978869089777


def test_move_point_golden():
    assert R.move_point(25.0, 121.0, 90.0, 111.0) == (24.99999999594495, 121.00110144367822)


def test_interpolate_golden_two_point_route():
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    pts = R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)
    assert [(p["lat"], p["lng"]) for p in pts] == [
        (25.0, 121.0),
        (25.0, 121.0001984583204),
        (25.0, 121.00039691664081),
        (25.0, 121.00059537496121),
        (25.0, 121.0007938332816),
        (25.0, 121.00099229160202),
        (25.0, 121.001),
    ]
    assert pts[0]["timestamp_offset"] == 0.0 and pts[0]["seg_idx"] == 0
    assert pts[-1]["lat"] == 25.0 and pts[-1]["lng"] == 121.001  # final wp always included


def test_random_point_in_radius_is_seed_deterministic():
    a = R.random_point_in_radius(25.0, 121.0, 500.0, rng=random.Random(42))
    b = R.random_point_in_radius(25.0, 121.0, 500.0, rng=random.Random(42))
    assert a == b   # same seed -> identical point (group-mode invariant)


@pytest.mark.asyncio
async def test_move_along_route_position_stream_matches_frozen_golden(monkeypatch):
    """GAP-2: drive _move_along_route with jitter disabled and assert the EXACT
    ordered position_update lat/lng stream against a FROZEN GOLDEN (NOT a
    push==emit tautology — both sinks get the same per-tick var, so equality
    alone would stay green even if the interpolation extraction broke).

    Inter-tick pacing uses `asyncio.wait_for(self._stop_event.wait(), ...)` (NOT
    the injected sleep), so without help this runs ~5s of real wall-clock. Patch
    wait_for to fire its timeout branch instantly; the position stream is
    timing-independent, so this only removes the wait.
    """
    async def _instant_timeout(aw, timeout):
        aw.close()                       # close the un-awaited stop-event coroutine
        raise asyncio.TimeoutError
    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)

    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    # _move_along_route copies the passed profile into self._active_speed_profile
    # at its start (simulation_engine.py:670) — no field pre-arming needed.
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0}

    await eng._move_along_route(coords, profile)

    latlng = [(d["lat"], d["lng"]) for (t, d) in emitted if t == "position_update"]
    assert latlng == [
        (25.0, 121.0),
        (25.0, 121.0001984583204),
        (25.0, 121.00039691664081),
        (25.0, 121.00059537496121),
        (25.0, 121.0007938332816),
        (25.0, 121.00099229160202),
        (25.0, 121.001),
    ]
    assert loc.pushes == latlng   # secondary invariant: every emit had a matching push, in order
```

- [ ] **Step 3: Confirm the frozen literals against the current implementation**

Run: `cd backend && .venv/bin/python -m pytest tests/test_interpolator_golden.py -q`
Expected: PASS — every golden matches the current `services.interpolator`. If any literal differs on your machine (trailing-ULP platform variance), replace it with YOUR captured value (re-run the one test with a temporary `print(repr(...))`); the same interpreter runs post-move, so your frozen values stay bit-exact across Task 7. Do **NOT** relax any `==` to `approx` — exact equality is the whole point of the bit-exact guard.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_interpolator_golden.py
git commit -m "test(interpolator): bit-exact golden vectors + deterministic _move_along_route char"
```

---

### Task 7: Relocate `RouteInterpolator` to `domain/movement.py` (LAST, kills the `core→services` edge)

Verbatim-move the class; `services/interpolator.py` becomes a re-export shim; flip the **three core** importers to `domain.movement` so the `core→services` interpolator edge dies. Non-core importers (`services/cooldown.py`, `*_cov` tests) keep working via the shim.

**Files:**
- Modify: `backend/domain/movement.py` (add `RouteInterpolator` + its `math`/`random`/`Coordinate` imports)
- Modify: `backend/services/interpolator.py` (→ shim)
- Modify: `backend/core/simulation_engine.py:18`, `backend/core/joystick.py:10`, `backend/core/random_walk.py:12` (flip import)
- Test: `tests/test_interpolator_golden.py`, `tests/test_interpolator_cov.py`, `tests/test_joystick_cov.py`, `tests/test_random_walk_cov.py`, `tests/test_cooldown_cov.py` (all stay green)

**Interfaces:**
- Produces: `domain.movement.RouteInterpolator`; `services.interpolator.RouteInterpolator` (shim alias).

- [ ] **Step 1: Move the `RouteInterpolator` class body verbatim into `domain/movement.py`**

Add to the top of `backend/domain/movement.py` (alongside the existing `time`/`datetime` imports):

```python
import math
import random

from models.schemas import Coordinate
```

Then paste the **entire** `RouteInterpolator` class and the `_R = 6_371_000.0` module constant from `services/interpolator.py` verbatim — everything below its import block (the whole file body, ~lines 11-230) — into `domain/movement.py`. Do not edit any math, comment, or operation order. Verify byte-identity: `diff <(sed -n '11,230p' services/interpolator.py) <(sed -n '/^_R = /,/return RouteInterpolator.move_point/p' domain/movement.py)` should show only expected boundary differences, or simply eyeball that the class body matches.

- [ ] **Step 2: Turn `services/interpolator.py` into a re-export shim**

Replace the whole file `backend/services/interpolator.py` with:

```python
"""Re-export shim — RouteInterpolator moved to domain/movement.py (Phase 3, Task 7).

Kept so non-core importers (services.cooldown, characterization tests, and any
external `from services.interpolator import RouteInterpolator`) keep working. The
three CORE importers were flipped to import from domain.movement directly, which
removes the last interpolator-driven core->services import edge.
"""
from domain.movement import RouteInterpolator

__all__ = ["RouteInterpolator"]
```

- [ ] **Step 3: Flip the three core importers to `domain.movement`**

- `backend/core/simulation_engine.py:18` — change `from services.interpolator import RouteInterpolator` and consolidate with the existing domain import to: `from domain.movement import EtaTracker, build_resume_snapshot, RouteInterpolator` (remove the now-duplicate line 18).
- `backend/core/joystick.py:10` — `from services.interpolator import RouteInterpolator` → `from domain.movement import RouteInterpolator`.
- `backend/core/random_walk.py:12` — `from services.interpolator import RouteInterpolator` → `from domain.movement import RouteInterpolator`.

- [ ] **Step 4: Verify the core→services interpolator edge is gone**

Run: `cd backend && grep -rn 'services.interpolator' core/ ; echo "exit=$?"`
Expected: no matches (`grep` exit 1) — zero `services.interpolator` references under `core/`.

- [ ] **Step 5: Run the interpolator golden + all affected cov tests + clock seam**

Run: `cd backend && .venv/bin/python -m pytest tests/test_interpolator_golden.py tests/test_interpolator_cov.py tests/test_joystick_cov.py tests/test_random_walk_cov.py tests/test_cooldown_cov.py -q`
Expected: PASS — math byte-identical via the verbatim move; shim keeps non-core importers green.

- [ ] **Step 6: Architecture gate (domain still pure — now imports models) + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q && .venv/bin/python -m pytest -q`
Expected: `6 kept, 0 broken` (domain→models is allowed; domain→{core,services,api,infra,fastapi} still absent); full suite green.

- [ ] **Step 7: Commit**

```bash
git add backend/domain/movement.py backend/services/interpolator.py \
        backend/core/simulation_engine.py backend/core/joystick.py backend/core/random_walk.py
git commit -m "refactor(domain): relocate RouteInterpolator to domain/movement.py; kill core->services interpolator edge"
```

---

### Task 8: Close-out — verify, document, smoke, merge

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md` (flip Phase 3 status)
- Modify: `CLAUDE.md` + `AGENTS.md` (note Phase 3 DONE + the deferred `RouteService` edge)

- [ ] **Step 1: Final architecture + full-suite verification**

Run: `cd backend && .venv/bin/python -m pytest -q && .venv/bin/python -m pytest --collect-only -q | tail -1`
Expected: all green; collect count = 849 + (new char tests). Record the new baseline.

- [ ] **Step 2: Confirm the deferred edges are documented, not silently dropped**

Run: `cd backend && grep -n 'from services.route_service' core/simulation_engine.py`
Expected: line 19 still present (RouteService edge intentionally deferred). Confirm no `no-core-imports-services` contract was added (blocked on it).

- [ ] **Step 3: Update the spec + project docs**

In `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md` §5 Phase 3, change status `deferred` → `DONE (2026-06-22)` and note: EtaTracker + build_resume_snapshot + RouteInterpolator relocated to `domain/movement.py`; `no-domain-imports-outer` enforced (6 contracts); resume-on-miss kept warn-and-return (freeze over spec-literal); RouteService `core→services` edge + route_service duplicate haversine deferred. Also correct the spec's literal "snapshot dict↔**dataclass** converter" phrasing (§4.1, §5): no dataclass ever existed — the snapshot is a plain dict, so the serializer is `build_resume_snapshot` (dict-only); the "dataclass" wording is superseded by the freeze, parallel to the resume-RAISES note. Mirror a one-line status note into `CLAUDE.md`'s Clean-Architecture section and `AGENTS.md`.

- [ ] **Step 4: Commit docs**

```bash
git add docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md CLAUDE.md AGENTS.md
git commit -m "docs(clean-arch): flip Phase 3 to DONE; note deferred RouteService edge"
```

- [ ] **Step 5: Light hardware smoke (lower-risk than P1/P2 — no device-manager/tunnel change)**

On real hardware over USB: one `navigate` (watch the path render + position_update stream on the map) and one `multi_stop` run; eyeball that movement is identical to before. The relocation is pure math, so WS payloads are pinned deep-equal by the nets — this smoke confirms no integration surprise. If green, merge `chore/clean-arch-p3` → `main` (ff). If any visible movement regression, `git revert` the Task-7 commit (the shim keeps the old path alive) and investigate.

---

## Rollback & Verification Gates

- Every commit keeps the full suite green individually; `git revert <sha>` of any single commit is safe (verbatim moves + shims mean a revert restores the prior import path).
- The riskiest commit (Task 7 relocation) is guarded by bit-exact golden vectors (Task 6) and the `_move_along_route` char; if hardware smoke regresses, revert Task 7 alone — `services/interpolator.py` returns to the real class and core re-imports it.
- `no-domain-imports-outer` is enforced from Task 1, so no extraction can silently leak an outer-ring import into `domain/`.
- Branch `chore/clean-arch-p3`; merge after the Task-8 smoke.

## Execution Handoff

Two execution options:
1. **Subagent-Driven (recommended)** — fresh implementer per task, char-net-first, task review between tasks, broad final review. Use superpowers:subagent-driven-development.
2. **Inline Execution** — batch with checkpoints. Use superpowers:executing-plans.
