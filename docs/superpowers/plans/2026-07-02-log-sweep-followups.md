# Log-Sweep Follow-ups (Watchdog Busy-Loop · Restore Signal · Log Retention) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three distinct software issues surfaced by the 2026-07-02 log sweep that are **independent of** the USB-reconnect/multi-stop bug (which has its own plan): ① the usbmux presence-watchdog busy-loop, ② interactive `/restore` + `DELETE /simulation` reporting success when the device clear() actually failed, and ③ log retention that only holds ~27h.

**Architecture:** Three small, independent fixes, each behind a testable seam. ① carves the watchdog's appearance-selection into a **pure function** (`services/device_presence.py`) that dedups against *all* connected devices (any transport) and wires `main.py` to it, plus removes the cooldown-defeating `pop`. ② has the two interactive restore endpoints opt into `restore(raise_on_clear_failure=True)` and surface a real clear() failure as a non-2xx (`restore_failed` / `device_lost`) instead of a false 200, reusing the existing `_handle_device_lost` / frontend `restore_failed` machinery. ③ extracts the file-log handler into a testable factory (`log_config.py`) using `TimedRotatingFileHandler` (daily, 14-day retention).

**Tech Stack:** Python 3.13 (backend), FastAPI, stdlib `logging.handlers`, pytest + pytest-asyncio (`asyncio_mode = strict`), FastAPI `TestClient`.

## Context / evidence

From the log sweep (`~/.locwarp/logs/backend.log*`, ~27h span 2026-07-01 00:35 → 07-02 03:51), adversarially verified:

- **① Watchdog busy-loop (Medium, CONFIRMED distinct):** `main.py:_usbmux_presence_watchdog` logged `new USB device detected → already connected → auto-connect succeeded` for Renee (`00008120…`) **7189×** at ~1.3s cadence — **~34% of all log lines** — with 0 DVT drops during the flood (so *not* a symptom of the tunnel-death cluster). Two compounding bugs: **(A)** the `connected` set is built only from `connection_type=="USB"` entries (`main.py:591-594`), so `new_udids_lc = present_usb - connected` (`main.py:748`) keeps re-flagging an already-connected device whose stored type isn't exactly `"USB"`; `connect()` then no-ops at "already connected" forever. **(B)** the no-op "success" path pops the throttle stamp (`main.py:803 last_reconnect_attempt.pop`), so next tick `last=0.0` and the 5s per-udid cooldown (`main.py:780`) never fires. Also feeds the concurrent-connect pressure behind the USB-reconnect plan's `-32003` collisions, so fixing it is complementary to that plan (which does **not** address this).
- **② Restore false success (Low–Med):** `core/restore.py:restore()` defaults `raise_on_clear_failure=False`; on a clear() exception it logs "Failed to clear device location" (line 46), swallows it, and still emits `"restored"` + logs "Simulation fully restored" (62-65). `api/location.py` `/restore` (315) and `DELETE /simulation` (398) call `restore()` lenient, so a real clear() failure returns 200 `{"status":"restored"}` and the UI shows a success toast — asymmetric with Gold Ditto, which passes `raise_on_clear_failure=True` (`core/goldditto.py:95`). *Caveat (from adversarial verify):* the single observed instance was USB-tunnel-caused, and a dead DVT session may make iOS auto-revert to real GPS, so "restored" was arguably accurate that time; this fix is about **signal honesty** (never show green success on a swallowed failure), which is cheap and reuses existing handling.
- **③ Log retention (Low–Med):** `main.py:83-88` uses `RotatingFileHandler(maxBytes=2MB, backupCount=3)` → 4×2MB ≈ ~27h of a busy session. Too short for post-hoc investigation ("last 7 days" was already gone).

Full analysis: conversation transcript 2026-07-02 + workflow `wf_ad5432cd-ec6`.

## Global Constraints

- **Minimal external surface change, and only where the fix requires it.** ① and ③ are internal. ② intentionally changes the *failure* response of `/restore` and `DELETE /simulation` from a false `200 {"status":"restored"}` to a truthful non-2xx (`503 {"detail":{"code":"restore_failed"|"device_lost"}}`); the **success** path (200 restored) is unchanged. The frontend already maps a thrown/non-2xx restore to `status.restore_failed`.
- **Backend suite green after every commit.** Pin baseline first: `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1` (≈914 + any tests added by the sibling USB-reconnect plan if that landed first).
- **Test-first.** Each fix ships its failing test before the implementation. Pure/factory seams are unit-tested; the watchdog loop and import-time logging block stay thin wrappers over the tested seam.
- **Layering (import-linter `7 kept, 0 broken`):** `services/device_presence.py` and `log_config.py` import **stdlib only**. `main.py` (composition root) may import both. No new cross-ring edges. Verify in Task 4.
- **Test command:** `cd backend && .venv/bin/python -m pytest <args>`; `asyncio_mode = strict`; file logging is disabled under pytest (`main.py:72-74`), so ③ is tested via the extracted factory, not the live root logger.
- **Git identity** auto-set by includeIf — never pass `-c user.email=…`. Personal repo → direct commits to `main`; one commit per task.

---

## File Structure

- **Create** `backend/services/device_presence.py` — pure `compute_usb_reconnect_targets(...)` (①)
- **Create** `backend/log_config.py` — `build_file_log_handler(log_dir, fmt)` + `LOG_RETENTION_DAYS` (③)
- **Modify** `backend/main.py` — watchdog appearance block + remove cooldown pop (①); file-handler construction (③)
- **Modify** `backend/api/location.py` — `/restore` and `DELETE /simulation` strict clear + honest failure (②)
- **Create** `backend/tests/test_device_presence.py` (①)
- **Create** `backend/tests/test_log_config.py` (③)
- **Modify** `backend/tests/test_location_restore_clear_surface_char.py` — new API-level ② test (create this file)

---

## Design Decisions

### ① Watchdog busy-loop
- **Chosen:** dedup the appearance set against **all** `_connections` keys (any transport) via a pure helper, and stop popping `last_reconnect_attempt` on a no-op success. Rejected: (a) only fixing the `pop` — leaves Defect A so the loop still fires every 5s; (b) forcing every connection's `connection_type` to `"USB"` — hides the real question of why a USB device is stored as non-USB and would break the disappearance logic that intentionally keeps `connected` USB-only.
- Keep `connected` (USB-only) for the **disappearance** branch unchanged (WiFi disappearance is the WiFi watchdog's job). Only the **appearance** computation becomes transport-agnostic.

### ② Restore signal honesty
- **Chosen:** interactive endpoints pass `raise_on_clear_failure=True` and surface failure. `DeviceLostError` → existing `_handle_device_lost` (503 `device_lost`, with the existing full_reconnect+retry self-heal via `_try_with_recovery_retry`); any other clear exception → new `except Exception` → 503 `restore_failed`. Verified: `EngineResolver.with_recovery` only catches `DeviceLostError`, so a non-device-lost clear error propagates cleanly to the endpoint. Rejected: adding a new `restore_incomplete` WS event/field (more surface + frontend work for no extra correctness).
- Do **not** touch `core/restore.py` (its strict/lenient semantics + tests already exist); only the API callers change.

### ③ Log retention
- **Chosen:** `TimedRotatingFileHandler(when="midnight", backupCount=14)` → 14 daily files. Rejected: bumping `RotatingFileHandler.backupCount` — size-based can't guarantee *days* (a busy window still evicts fast). Trade-off: a single very busy day's file is size-uncapped; acceptable for a personal tool, and ① + the USB-reconnect fix sharply cut daily volume anyway.

---

## Task 0: Pin the baseline

- [ ] **Step 1: Record collected count + green targets**

Run:
```bash
cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1
cd backend && .venv/bin/python -m pytest tests/test_restore_clear_failure.py tests/test_location_restore_action_udid_char.py -q
```
Expected: a count near 914 (write it down); both files PASS.

---

## Task 1: ① Fix the usbmux watchdog busy-loop

**Files:**
- Create: `backend/services/device_presence.py`
- Test: `backend/tests/test_device_presence.py`
- Modify: `backend/main.py` (`_usbmux_presence_watchdog` appearance block ~747-754; remove line 803)

**Interfaces:**
- Produces: `compute_usb_reconnect_targets(connected_udids: Iterable[str], present_usb_serials: Iterable[str], *, max_devices: int = 3) -> list[str]` — USB serials with NO connection on ANY transport, under the cap, original casing preserved.

- [ ] **Step 1: Write the failing pure-helper test**

Create `backend/tests/test_device_presence.py`:
```python
"""Pure appearance-selection logic for the usbmux presence watchdog.

Regression: a device already connected on ANY transport (USB or Network) must
never be treated as a 'new' USB device — otherwise the watchdog busy-loops,
re-'detecting' it every poll (~34% of the log in the 2026-07-02 sweep)."""
from services.device_presence import compute_usb_reconnect_targets


def test_device_already_connected_any_transport_is_not_new():
    # Already-connected UDID present on USB must be excluded; only the truly
    # new device is returned. (Renee reproduced this: connected yet re-flagged.)
    assert compute_usb_reconnect_targets(
        connected_udids=["RENEE"],
        present_usb_serials=["RENEE", "NEWDEV"],
    ) == ["NEWDEV"]


def test_comparison_is_case_insensitive():
    assert compute_usb_reconnect_targets(
        connected_udids=["renee"],
        present_usb_serials=["RENEE"],
    ) == []


def test_respects_device_cap():
    assert compute_usb_reconnect_targets(
        connected_udids=["A", "B", "C"],
        present_usb_serials=["D"],
        max_devices=3,
    ) == []


def test_truly_new_device_is_returned_with_original_casing():
    assert compute_usb_reconnect_targets(
        connected_udids=[],
        present_usb_serials=["New1"],
    ) == ["New1"]
```

- [ ] **Step 2: Run it — RED**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_device_presence.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'services.device_presence'`.

- [ ] **Step 3: Create the pure helper**

Create `backend/services/device_presence.py`:
```python
"""Pure helper for the usbmux presence watchdog's appearance logic."""
from __future__ import annotations

from collections.abc import Iterable


def compute_usb_reconnect_targets(
    connected_udids: Iterable[str],
    present_usb_serials: Iterable[str],
    *,
    max_devices: int = 3,
) -> list[str]:
    """USB serials with NO active connection on ANY transport, under the cap.

    A device already in ``connected_udids`` — regardless of its connection_type
    (USB *or* Network) — is never 'new'. Comparison is case-insensitive because
    usbmux and connect() may store the serial in different casing. Original
    casing from ``present_usb_serials`` is preserved so the caller can hand the
    result straight to ``dm.connect()``.
    """
    all_connected_lc = {u.lower() for u in connected_udids}
    if len(all_connected_lc) >= max_devices:
        return []
    present_map: dict[str, str] = {}
    for s in present_usb_serials:
        present_map[s.lower()] = s
    new_lc = set(present_map) - all_connected_lc
    return [present_map[lc] for lc in sorted(new_lc)]
```

- [ ] **Step 4: Run it — GREEN**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_device_presence.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Wire the watchdog to the helper (Defect A) and drop the cooldown pop (Defect B)**

In `backend/main.py` `_usbmux_presence_watchdog`, replace the appearance block (currently):
```python
            MAX_DEVICES = 3
            new_udids_lc = present_usb - connected
            if not new_udids_lc or len(connected) >= MAX_DEVICES:
                continue
            # Map back to the original-case serials from list_devices so
            # downstream dm.connect() sees the format pymobiledevice3
            # itself expects.
            new_udids = [present_usb_original[lc] for lc in new_udids_lc]
```
with:
```python
            MAX_DEVICES = 3
            # Dedup against ALL connected devices (any transport), not just the
            # USB-typed `connected` set used for disappearance — otherwise a
            # device stored as non-USB (or under different casing) is re-flagged
            # 'new' every poll and connect() no-ops forever (busy-loop).
            from services.device_presence import compute_usb_reconnect_targets
            new_udids = compute_usb_reconnect_targets(
                connected_udids=dm._connections.keys(),
                present_usb_serials=present_usb_original.values(),
                max_devices=MAX_DEVICES,
            )
            if not new_udids:
                continue
```
Then, in the success branch, DELETE the cooldown-defeating pop (currently line 803):
```python
                    logger.info("Auto-connect succeeded for %s", udid)
                    last_reconnect_attempt.pop(udid, None)   # <-- DELETE THIS LINE
                    reconnect_failure_count.pop(udid, None)
```
Result:
```python
                    logger.info("Auto-connect succeeded for %s", udid)
                    reconnect_failure_count.pop(udid, None)
```
> `reconnect_failure_count.pop` stays (reset exponential backoff on success). `last_reconnect_attempt[udid]` keeps the `now` stamp set earlier, so even a transient re-appearance is throttled by the 5s cooldown. The disappearance-side stale-cleanup (`main.py:759-762`) still clears both dicts on unplug, so a re-plug retries immediately.

- [ ] **Step 6: Full suite green**

Run:
```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: baseline + 4 new, all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/services/device_presence.py backend/tests/test_device_presence.py backend/main.py
git commit -m "fix(watchdog): stop usbmux presence busy-loop (transport-agnostic dedup + keep cooldown)

The appearance check subtracted only USB-typed connections, so a device stored
under a non-USB type/casing was re-'detected' as new every poll; connect()
no-op'd at 'already connected' forever. Plus the no-op success path popped
last_reconnect_attempt, defeating the 5s cooldown → ~1.3s hammer (Renee: 7189
spurious cycles, ~34% of the log). Dedup against ALL _connections keys via a
pure helper and stop popping the cooldown stamp on a no-op success.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: ② Restore surfaces clear() failure instead of a false success

**Files:**
- Modify: `backend/api/location.py` (`/restore` 314-331; `DELETE /simulation` 397-403)
- Test: `backend/tests/test_location_restore_clear_surface_char.py` (create)

**Interfaces:**
- Consumes: `RestoreHandler.restore(raise_on_clear_failure: bool = False)`, `_try_with_recovery_retry`, `_handle_device_lost`, `DeviceLostError`.
- Produces: `/restore` and `DELETE /simulation` return `503 {"detail":{"code":"restore_failed","message":...}}` on a non-device-lost clear failure, `503 {"detail":{"code":"device_lost",...}}` on a device-lost clear failure, and unchanged `200` on success.

- [ ] **Step 1: Write the failing API-level test**

Create `backend/tests/test_location_restore_clear_surface_char.py`:
```python
"""Interactive /restore must SURFACE a device clear() failure, not report a
false 200 {"status":"restored"} while the phone may still be simulated.

The fix makes the interactive path opt into restore(raise_on_clear_failure=True)
(matching Gold Ditto) and maps a non-device-lost clear failure to 503
restore_failed."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_restore_surfaces_clear_failure_instead_of_false_success(client):
    from main import app_state
    dm = app_state.device_manager
    resolved = "UDID-RESTORE-CLEARFAIL"

    async def fake_restore(raise_on_clear_failure: bool = False):
        # Lenient (the bug) would swallow and return → false 200 "restored".
        # Strict (the fix) raises a NON-device-lost clear error.
        if raise_on_clear_failure:
            raise RuntimeError("clear failed")

    fake_engine = MagicMock()
    fake_engine.restore = fake_restore  # real coroutine fn honoring the kwarg

    async def fake_engine_resolver(u=None, registry=None):
        app_state._primary_udid = resolved
        return fake_engine

    with (
        patch("api.location._engine", fake_engine_resolver),
        patch.object(dm, "_connections", {resolved: object()}),
        patch.object(dm, "full_reconnect", new=AsyncMock(return_value=False)),
        patch.object(app_state, "_primary_udid", None),
    ):
        resp = client.post("/api/location/restore")

    assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"]["code"] == "restore_failed"
```

- [ ] **Step 2: Run it — RED**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_location_restore_clear_surface_char.py -v
```
Expected: FAIL — current `/restore` calls `eng.restore()` lenient, so `fake_restore` doesn't raise and the endpoint returns `200 {"status":"restored"}` (assert 503 fails).

- [ ] **Step 3: Make `/restore` strict + surface failure**

In `backend/api/location.py`, change `_do_restore` and the try/except in `restore()`:
```python
    async def _do_restore():
        eng = await _engine(action_udid, registry)
        await eng.restore(raise_on_clear_failure=True)

    try:
        await _try_with_recovery_retry(action_udid, _do_restore, registry)
    except DeviceLostError as e:
        raise (await _handle_device_lost(e, action_udid, registry))
    except HTTPException:
        raise
    except Exception as e:
        # A non-device-lost clear() failure (e.g. instrument RuntimeError):
        # do NOT lie "restored". Surface it so the UI shows restore_failed
        # instead of a green success while the phone may still be simulated.
        raise HTTPException(
            status_code=503,
            detail={"code": "restore_failed", "message": str(e)},
        )
    return {"status": "restored"}
```

- [ ] **Step 4: Make `DELETE /simulation` strict + surface failure**

In `backend/api/location.py`, replace `stop_simulation`:
```python
@router.delete("/simulation")
async def stop_simulation(udid: str | None = None, registry=Depends(get_engine_registry)):
    """Legacy endpoint: stop + restore. Kept for backwards compatibility,
    prefer /stop (movement only) or /restore (clear location)."""
    engine = await _engine(udid, registry)
    action_udid = udid or registry.get_primary_udid()
    try:
        await engine.restore(raise_on_clear_failure=True)
    except DeviceLostError as e:
        raise (await _handle_device_lost(e, action_udid, registry))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "restore_failed", "message": str(e)},
        )
    return {"status": "stopped"}
```

- [ ] **Step 5: Run the new test + existing restore tests — GREEN**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_location_restore_clear_surface_char.py tests/test_restore_clear_failure.py tests/test_location_restore_action_udid_char.py -v
```
Expected: new test PASS (503 restore_failed); existing device-lost test still PASS (503 device_lost); handler strict/lenient tests untouched and PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/api/location.py backend/tests/test_location_restore_clear_surface_char.py
git commit -m "fix(restore): interactive /restore + DELETE /simulation surface clear() failure

restore() defaulted lenient, so a swallowed device clear() still returned
200 {status:restored} and a green UI toast while the phone could still be
simulated — asymmetric with Gold Ditto's strict path. Opt the interactive
endpoints into raise_on_clear_failure=True: device-lost → existing 503
device_lost (with full_reconnect self-heal), any other clear failure → 503
restore_failed. Success path (200) unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: ③ Extend log retention to ~14 days

**Files:**
- Create: `backend/log_config.py`
- Test: `backend/tests/test_log_config.py`
- Modify: `backend/main.py` (import at line 20; file-handler block 83-91)

**Interfaces:**
- Produces: `LOG_RETENTION_DAYS: int` and `build_file_log_handler(log_dir: Path, fmt: str) -> logging.Handler` (a daily `TimedRotatingFileHandler`).

- [ ] **Step 1: Write the failing factory test**

Create `backend/tests/test_log_config.py`:
```python
"""Backend file logs must retain multiple days (was ~27h with 4x2MB size
rotation — too short for post-hoc investigation)."""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from log_config import LOG_RETENTION_DAYS, build_file_log_handler


def test_retention_is_at_least_a_week():
    assert LOG_RETENTION_DAYS >= 7


def test_file_handler_is_daily_rotating_with_multiday_retention(tmp_path: Path):
    handler = build_file_log_handler(tmp_path, "%(message)s")
    try:
        assert isinstance(handler, TimedRotatingFileHandler)
        assert handler.when.upper() == "MIDNIGHT"
        assert handler.backupCount == LOG_RETENTION_DAYS
        assert handler.level == logging.INFO
    finally:
        handler.close()
```

- [ ] **Step 2: Run it — RED**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_log_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'log_config'`.

- [ ] **Step 3: Create the factory**

Create `backend/log_config.py`:
```python
"""Backend file-log handler construction (extracted for testability)."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_RETENTION_DAYS = 14


def build_file_log_handler(log_dir: Path, fmt: str) -> logging.Handler:
    """Daily-rotating file handler keeping ~LOG_RETENTION_DAYS days of logs.

    Replaces the old size-based rotation (RotatingFileHandler, 2MB x 3) which
    retained only ~1 day of a busy session — too short for post-hoc
    investigation. Time-based rotation guarantees N days regardless of volume;
    a single very busy day's file is size-uncapped, an acceptable trade for a
    personal tool (and daily volume drops once the watchdog/USB-reconnect
    fixes land).
    """
    handler = TimedRotatingFileHandler(
        log_dir / "backend.log",
        when="midnight",
        interval=1,
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(logging.INFO)
    return handler
```

- [ ] **Step 4: Run it — GREEN**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_log_config.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Wire `main.py` to the factory**

In `backend/main.py`, delete the now-unused import at line 20:
```python
from logging.handlers import RotatingFileHandler
```
Then replace the file-handler construction block (currently lines 83-91):
```python
        _file_handler = RotatingFileHandler(
            _log_dir / "backend.log",
            maxBytes=2 * 1024 * 1024,  # 2 MB
            backupCount=3,
            encoding="utf-8",
        )
        _file_handler.setFormatter(logging.Formatter(_log_fmt))
        _file_handler.setLevel(logging.INFO)
        _handlers.append(_file_handler)
```
with:
```python
        from log_config import build_file_log_handler
        _handlers.append(build_file_log_handler(_log_dir, _log_fmt))
```

- [ ] **Step 6: Verify main still imports + boots cleanly**

Run:
```bash
cd backend && .venv/bin/python -c "import main; print('import OK')"
cd backend && .venv/bin/python -m pytest tests/test_log_config.py -q
```
Expected: `import OK` (no NameError from the removed `RotatingFileHandler`), tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/log_config.py backend/tests/test_log_config.py backend/main.py
git commit -m "fix(logging): daily rotation with 14-day retention (was ~27h)

4x2MB size-based rotation retained only ~1 day of a busy session, so a 'last
7 days' investigation had no data. Switch to a TimedRotatingFileHandler
(daily, 14 backups) behind a testable factory.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Full verification

**Files:** none.

- [ ] **Step 1: Full backend suite green, count = baseline + new tests**

Run:
```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: all pass; +10 tests vs Task 0 (4 device_presence + 1 restore-surface + 2 log_config, plus any this plan's edits touched).

- [ ] **Step 2: Import-linter contracts still `7 kept, 0 broken`**

Run:
```bash
cd backend && .venv/bin/lint-imports || make -C .. verify
```
Expected: `7 kept, 0 broken` — the two new modules import stdlib only.

- [ ] **Step 3: Runtime smoke (macOS, Renee on USB)**

Start the backend (`cd backend && .venv/bin/python main.py`) with Renee plugged in; after ~2 min:
```bash
grep -c 'new USB device .* detected' ~/.locwarp/logs/backend.log   # expect ~0 while idle-connected (was ~1/sec)
ls -1 ~/.locwarp/logs/                                              # daily backend.log(.YYYY-MM-DD) files accrue over days
```
Then run `/stop`+`/restore` with the device unplugged mid-restore and confirm the app shows a **failure** toast (not green success) and the API returns 503.

---

## Self-Review

1. **Coverage:** ① → Task 1 (pure helper + wiring + pop removal). ② → Task 2 (both endpoints strict + honest failure). ③ → Task 3 (factory + wiring). Verification → Task 4. ✅
2. **Placeholder scan:** every step has real code; tests assert exact values (`== ["NEWDEV"]`, `code == "restore_failed"`, `backupCount == LOG_RETENTION_DAYS`, `when == "MIDNIGHT"`). ✅
3. **Type/name consistency:** `compute_usb_reconnect_targets` signature identical in test, module, and `main.py` call site (kwargs `connected_udids`/`present_usb_serials`/`max_devices`). `build_file_log_handler(log_dir, fmt)` + `LOG_RETENTION_DAYS` consistent across module/test/`main.py`. `restore(raise_on_clear_failure=True)` matches `core/restore.py`. 503 detail codes `restore_failed`/`device_lost` consistent. ✅
4. **Constraints:** new modules stdlib-only (no ring violation); ② is the only external change and only on the failure path; each task keeps the suite green; file logging tested via the factory since it's disabled under pytest. ✅
