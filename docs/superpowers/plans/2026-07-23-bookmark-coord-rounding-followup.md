# Bookmark Coordinate Rounding + Minor Cleanup — Follow-up Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Round stored bookmark coordinates to a sane precision on every save so no bookmark carries a long-precision drifted coordinate, regardless of how it was created (typed, pasted, Bookmark Here, map right-click, mid-navigation). Plus close the review Minors from the clean-broadcast cluster.

**Architecture:** Add a pure `round_coord()` policy (domain ring, stdlib only) and apply it at the three bookmark write choke-points in `services/bookmarks.py` (`create_bookmark`, `update_bookmark`, `_upsert_items`). No frontend change; no model-wide validator (avoids rounding on disk-load, keeping historical data untouched until re-saved). Historical backfill of already-drifted bookmarks is OUT OF SCOPE here (separate, explicitly-gated action against live iCloud data).

**Tech Stack:** Python 3.11, pydantic, pytest. Backend only. Continues on branch `gps-bookmark-jitter-fix`.

## Global Constraints

- Baseline before this plan: backend **1185 passed** (post clean-broadcast cluster). Suite stays green after EVERY commit. Pin the live count before starting: `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1`.
- Clean-arch: `services/` may import `domain/` (allowed). `domain/` imports stdlib + pydantic only. Import-linter 7 kept / 0 broken must stay green; no new cross-ring edge.
- **Precision = 7 decimals** (`COORD_PRECISION = 7`, ≈1.1 cm). Verified against the live store: all clean bookmarks are ≤7 decimals, so this preserves every real coordinate exactly and only strips the 13–16-digit float tail.
- No new dependencies. Personal repo: direct commits on the working branch, auto git identity (never pass `-c user.email`).
- Behavior/API freeze: no WS/HTTP/IPC shape change. Rounding changes only the stored lat/lng VALUE precision on save — the intended fix.

---

## File Structure

| File | Change |
|------|--------|
| `backend/domain/coords.py` | **Create.** `COORD_PRECISION = 7` + pure `round_coord(value: float) -> float`. |
| `backend/services/bookmarks.py` | Modify: import `round_coord`; apply at `create_bookmark` (369-380), `update_bookmark` (405-413), `_upsert_items` (546-562). |
| `backend/tests/test_bookmark_coord_rounding.py` | **Create.** Unit + integration tests. |
| `backend/core/multi_stop.py` | Modify comment only (~206-207): "actual GPS" → pristine intended position. |
| `backend/core/route_loop.py` | Modify comment only (~251-252): same wording fix. |
| `backend/tests/test_move_along_route_pristine_char.py` | Add a one-line comment explaining why device-lng isn't asserted (per-tick varying; both-axes device jitter covered by the joystick test). |
| `backend/tests/test_joystick_cov.py` | Add a one-line comment on `FakeEngine._set_position` noting it must mirror the real engine's `state_*` signature. |

---

### Task 5: Coordinate rounding on bookmark save

**Files:**
- Create: `backend/domain/coords.py`, `backend/tests/test_bookmark_coord_rounding.py`
- Modify: `backend/services/bookmarks.py:369-380` (create), `:405-413` (update), `:546-562` (_upsert_items)

**Interfaces:**
- Produces: `round_coord(value: float) -> float` in `domain/coords.py`; `COORD_PRECISION = 7`.

- [ ] **Step 1: Write the failing tests**

Create `backend/domain/coords.py` is Step 3; first write tests that fail. Create `backend/tests/test_bookmark_coord_rounding.py`. It must exercise BOTH the pure helper AND the manager write paths. Use the existing bookmark-manager test setup as the pattern — find how other tests in `backend/tests/` construct a `BookmarkManager` (grep `BookmarkManager(` in `backend/tests/`) and reuse that fixture/idiom (repositories are injected; do NOT hand-roll a new persistence layer). Skeleton (fill the manager construction to match the existing pattern):

```python
"""Bookmark coordinates are rounded to COORD_PRECISION on every save path,
so no bookmark persists a long-precision (jittered/interpolated/map-click)
coordinate. Clean human/map input (<=7 decimals) is preserved exactly."""
from __future__ import annotations

import pytest

from domain.coords import round_coord, COORD_PRECISION


def test_round_coord_strips_float_tail():
    assert round_coord(25.03462332942381) == 25.0346233
    assert round_coord(121.54608743242391) == 121.5460874


def test_round_coord_preserves_clean_input():
    # <=7-decimal input is unchanged (this is what a human/map provides).
    assert round_coord(25.034623) == 25.034623
    assert round_coord(121.546087) == 121.546087
    assert round_coord(25.0) == 25.0


def test_coord_precision_is_seven():
    assert COORD_PRECISION == 7


# --- integration: manager write paths round on save ---
# Construct a BookmarkManager exactly as the existing tests do (see other
# test_bookmark*.py files: injected BookmarkRepository over a tmp path).

def _make_manager(tmp_path):
    # REPLACE with the repo's established manager-construction idiom.
    ...


def test_create_bookmark_rounds(tmp_path):
    mgr = _make_manager(tmp_path)
    bm = mgr.create_bookmark(name="x", lat=25.03462332942381, lng=121.54608743242391)
    assert bm.lat == 25.0346233
    assert bm.lng == 121.5460874


def test_create_bookmark_preserves_clean(tmp_path):
    mgr = _make_manager(tmp_path)
    bm = mgr.create_bookmark(name="x", lat=25.034623, lng=121.546087)
    assert bm.lat == 25.034623
    assert bm.lng == 121.546087


def test_update_bookmark_rounds_coords(tmp_path):
    mgr = _make_manager(tmp_path)
    bm = mgr.create_bookmark(name="x", lat=25.0, lng=121.0)
    updated = mgr.update_bookmark(bm.id, lat=34.33102440963247, lng=120.00000000000001)
    assert updated.lat == 34.3310244
    assert updated.lng == 120.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_coord_rounding.py -v`
Expected: import error / FAIL — `domain.coords` doesn't exist yet, and the manager tests fail because rounding isn't applied.

- [ ] **Step 3: Create the pure policy**

Create `backend/domain/coords.py`:

```python
"""Coordinate precision policy (pure domain rule).

Stored bookmark coordinates are rounded so no bookmark persists a long,
drifted coordinate. 7 decimals ≈ 1.1 cm — finer than any GPS fix and finer
than any coordinate a human types or a map URL provides, so real input is
preserved exactly while the full-float64 tail introduced by GPS jitter,
route interpolation, or map-pixel projection (13–16 decimals) is stripped.
"""
from __future__ import annotations

COORD_PRECISION = 7


def round_coord(value: float) -> float:
    """Round a latitude or longitude to COORD_PRECISION decimal places."""
    return round(value, COORD_PRECISION)
```

- [ ] **Step 4: Apply at the three write choke-points**

In `backend/services/bookmarks.py`, add the import near the other domain imports:

```python
from domain.coords import round_coord
```

`create_bookmark` — round in the `Bookmark(...)` construction (lines 372-373):

```python
            lat=round_coord(lat),
            lng=round_coord(lng),
```

`update_bookmark` — round lat/lng values as they are applied (replace the loop body at 407-409):

```python
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                if key in ("lat", "lng"):
                    value = round_coord(value)  # type: ignore[assignment]
                setattr(bm, key, value)
```

`_upsert_items` — round each incoming item's coords at the top of the loop (before `old = existing.get(bm.id)` at line 547):

```python
        for bm in items:
            bm.lat = round_coord(bm.lat)
            bm.lng = round_coord(bm.lng)
            old = existing.get(bm.id)
```

- [ ] **Step 5: Run tests to verify they pass + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_coord_rounding.py -v`
Expected: PASS.
Then: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -8` → 0 failed.
Then import-linter: `cd backend && .venv/bin/lint-imports 2>&1 | tail -3` → 7 kept, 0 broken.

- [ ] **Step 6: Commit**

```bash
git add backend/domain/coords.py backend/services/bookmarks.py backend/tests/test_bookmark_coord_rounding.py
git commit -m "fix(bookmarks): round stored coordinates to 7 decimals on save (drift/precision)"
```

---

### Task 6: Close the clean-broadcast review Minors (docs/comments only)

**Files:**
- Modify (comment only): `backend/core/multi_stop.py` (~206-207), `backend/core/route_loop.py` (~251-252), `backend/tests/test_move_along_route_pristine_char.py`, `backend/tests/test_joystick_cov.py`

- [ ] **Step 1: Fix the resume-path comment wording**

In `backend/core/multi_stop.py` and `backend/core/route_loop.py`, the resume-origin comments say the leg starts from "the iPhone's actual current GPS". After the clean-broadcast fix, `current_position` is the pristine intended point (jitter goes only to the device), so update the wording. Find the exact comment (grep `actual current GPS` / `actual GPS` in those two files) and change to, e.g.:

```python
                # resume from the recorded current position (the pristine
                # intended point — device jitter is not reflected here).
```

Preserve surrounding lines; comment-only change, no logic edit.

- [ ] **Step 2: Add the clarifying test comments**

In `backend/tests/test_move_along_route_pristine_char.py`, near the device-push assertion, add:

```python
    # Device-side jitter is asserted on lat here; the both-axes device-jitter
    # property is covered exactly by the joystick test (single-tick exact tuple).
```

In `backend/tests/test_joystick_cov.py`, above `FakeEngine._set_position`, add:

```python
    # Mirrors SimulationEngine._set_position's (lat, lng, state_lat, state_lng)
    # signature — keep in sync if the real seam changes.
```

- [ ] **Step 3: Run the affected tests + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_move_along_route_pristine_char.py tests/test_joystick_cov.py tests/test_multi_stop_cov.py tests/test_route_loop_cov.py -q 2>&1 | tail -6`
Expected: 0 failed (comment-only changes; behavior identical).
Then full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -5` → 0 failed.

- [ ] **Step 4: Commit**

```bash
git add backend/core/multi_stop.py backend/core/route_loop.py backend/tests/test_move_along_route_pristine_char.py backend/tests/test_joystick_cov.py
git commit -m "docs(sim): correct resume comments + clarify jitter test coverage (review minors)"
```

---

## Non-goals / separate actions

- **Historical backfill** of the 108 already-drifted bookmarks in the live iCloud store — sub-metre and safe data-wise, but a write to live synced data; requires Ravi's explicit go. Not in this plan.
- **Route waypoint rounding** — routes have the same lat/lng shape; not reported as a problem, out of scope here (candidate follow-up).
- **Second "typed/pasted drifts on reopen" bug** — the store forensics show typed/pasted categories are 100% clean; pending a concrete counterexample from Ravi before investigating further.

## Self-Review

- Spec coverage: rounding on all three write paths → Task 5; review Minors → Task 6.
- Type consistency: `round_coord(value: float) -> float` / `COORD_PRECISION` used identically across `domain/coords.py`, `services/bookmarks.py`, and tests.
- Placeholder note: Task 5 Step 1's `_make_manager` is intentionally left to the implementer to match the repo's established `BookmarkManager` test-construction idiom (injected repository over a tmp path) — the implementer must grep existing `test_bookmark*.py` and reuse it, not invent a persistence layer.
