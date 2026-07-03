# Connection Findings Fixes — Implementation Plan (2026-07-03)

> Supersedes the connect/nav parts of `2026-07-02-usb-reconnect-multistop-terminate-fix.md`.
> Driven by a 12h local-log forensic sweep (07-02 20:18 → 07-03 01:56) + Ravi's field observation.

## Context / why this replaces the 07-02 plan

The 07-02 W1/W3 plan was **never implemented** (HEAD still `012237e`; `_connect_locks` absent).
More importantly, the 12h window shows the tunnel-death symptoms the 07-02 plan targeted are **absent**
(`ConnectionTerminatedError` / `Giving up` / `DeviceLostError` / `No route to host` all = 0). The real
failure profile is different. Confirmed root cause of the one mid-run interruption (00:04:22):

- A **spontaneous physical USB detach** of Renee mid-run. The DVT/DTX channel was provably healthy until
  the drop (`simulateLocationWithLatitude:longitude:` uses `expects_reply=True` → every "DVT location set"
  = a phone ACK; zero gaps, zero "DVT channel dropped" until 00:04:20).
- Ravi observed the phone freeze ~2s **before** the warning banner. That ~2s is a real **silent dark window**:
  when USB dies mid-push, `DvtLocationService.set()` hangs on the unbounded DTX `_wait_for_reply` instead of
  raising, so no warning fires until the usbmux watchdog (3×1s) cancels the task.
- After reconnect the multi-stop can't restart: the captured `segment=66` handoff snapshot is discarded
  because the resume gate is multi-device-only, and the rebuilt engine has `current_position=None`
  → `Cannot start multi-stop: no current position. Teleport first.`

Ravi's decision: single-device reconnect should **auto-resume (seamless)** from the snapshot within a TTL.

## Baseline (pinned)

- `cd backend && .venv/bin/python -m pytest --collect-only -q` → **1098 tests**.
- Full suite **1098 passed** after installing the missing dev tool `import-linter>=2.0` (was in
  `requirements-dev.txt` but not in `.venv`; 7 `test_import_linter.py`-dependent tests were failing
  `FileNotFound` on `lint-imports`). Not a code issue — restores the layering gate.
- **Hard rules (repo CLAUDE.md):** full suite green after EVERY commit; danger-zone (device_manager /
  simulation_engine / multi_stop / api / main watchdog) is **test-first** (characterization); no new
  cross-ring imports (import-linter `7 kept, 0 broken`); one commit per fix; direct commits to `main`.

## Fixes (safest → highest risk)

### F1 — Log-noise downgrades (no behavior change) — findings #5, #6 + docstring
- `core/device_manager.py:804` "Personalized DDI is NOT mounted …" — on iOS 17+ this is a uniform
  false-negative that gates nothing (only read by `api/system.py` status). Downgrade to `INFO`/`debug`,
  drop the "please mount DDI first" hint. Keep `conn.ddi_mounted = False` assignment.
- `main.py` engine-rebuild orchestrator: attempt-1 `Device … is not connected. Call connect() first.` is an
  expected ladder branch — log at `INFO`/`debug` WITHOUT traceback (no `logger.error(exc_info)`), keep
  attempt-2. It can never fire during a running sim (only when `get_engine()` is None).
- `main.py:544` watchdog docstring: fix stale "every 2 s / 2 consecutive polls" → "1 s poll, 3 misses (~3s)".
- **Test:** pure logging → assert-on-caplog level test is optional; no char test required. Verify suite green.

### F2 — rsd.connect timeout + error classification — finding #4 (+ helper -32002 label)
- `core/device_manager.py:_connect_tunnel` (:586-617): wrap `rsd.connect()` in
  `asyncio.wait_for(..., timeout=~15s)` so a stale/superseded tunnel address fails fast instead of the
  ~75s OS TCP default. Replace the bare `except Exception:` that unconditionally raises the
  `請以系統管理員身份執行` RuntimeError: **classify** — `TimeoutError`/`ConnectionError`/`OSError` from the
  RSD connect → a "stale tunnel; reconnecting" error (NOT a privilege message); reserve the admin message for
  a genuine helper-missing/privilege signal (`_helper_client is None`, helper `-32002` with a privilege
  detail). Always `raise … from exc`.
- `services/tunnel_helper_client.py`: include the transport in the `-32002` message so a WiFi device no longer
  surfaces as "USB tunnel failed" with an empty detail.
- **Test-first (char):** `tests/test_device_manager_fresh_dvt.py` / a new `_connect_tunnel` char test — inject a
  stubbed `open_tunnel_with_reconcile` + an `rsd` whose `connect()` sleeps > timeout → assert a bounded
  `DeviceConnectionError`/timeout-classified error with `__cause__` set, NOT the admin RuntimeError.

### F3 — W3 per-UDID connect latch — finding #3
- `core/device_manager.py`: add `self._connect_locks: dict[str, asyncio.Lock] = {}`; wrap `connect()` body in
  `connect_lock = self._connect_locks.setdefault(udid, asyncio.Lock())` → `async with connect_lock:` around the
  existing `async with self._lock:` membership check, so overlapping auto-connect triggers coalesce (the loser
  re-checks membership and early-returns "already connected") and never builds a second helper tunnel.
- **Test-first (char):** the coalescing test from the 07-02 plan (Task 1) —
  `test_connect_same_udid_coalesces_no_duplicate_tunnel` in `tests/test_device_manager_connect_race_char.py`:
  two overlapping `connect(udid)` build the tunnel exactly once.

### F4 — bounded DVT push timeout (kills the silent dark window) — finding #7
- `services/location_service.py:set()` (:191-209) and `clear()`: wrap `await sim.set(...)` in
  `asyncio.wait_for(..., timeout=~5s)`. On `asyncio.TimeoutError` treat as a dropped channel — it already falls
  into the reconnect `except` (asyncio.TimeoutError is whitelisted at :198), so a hung push surfaces promptly
  as a reconnect attempt / `DeviceLostError` instead of blocking ~2.7s until the usbmux watchdog cancels it.
- **Test-first (char):** stub `sim.set` to hang; assert `set()` raises/reconnects within the timeout (driven by
  an injected clock / short timeout), not indefinitely.

### F5 — single-device auto-resume (seamless) — finding #2 / W1
- **Stash:** `main.py` watchdog, after the pop/promote — when `leader_lost and handoff_snapshot and not
  new_leader` (single-device), store `app_state._pending_resume[lost_leader_udid] = (handoff_snapshot,
  monotonic_ts)` (capture `lost_leader_udid = app_state._primary_udid` before the loop clears it). Add
  `self._pending_resume: dict[str, tuple[dict, float]] = {}` + a TTL constant (`RESUME_TTL_S = 90`).
- **Consume:** `AppState.create_engine_for_device` (:486-507) — after creating the engine + primary, if
  `_pending_resume[udid]` exists and `now - ts <= RESUME_TTL_S`, pop it and
  `asyncio.create_task(engine.resume_from_snapshot(snapshot))` (reuses the existing, proven resume path that
  teleports to `current_pos` then re-enters the sim handler from the captured segment). Expired entries are
  dropped. This makes the reconnected single device continue the multi-stop from segment N automatically.
- **Endpoint hygiene:** the multi-stop start endpoint / `multi_stop.py:73` guard — when `current_position is
  None`, return a clean `400` ("teleport first") instead of surfacing as `ERROR Multi-stop failed
  unexpectedly` + traceback. (Belt-and-braces for the case where the user manually restarts before/without a
  pending resume.)
- **Test-first (char):** (a) watchdog stash test — single connected device lost mid-multi-stop → snapshot lands
  in `_pending_resume`; (b) reconnect consume test — `create_engine_for_device` with a fresh in-TTL pending
  entry → `resume_from_snapshot` invoked with the snapshot; expired entry → not invoked, dropped.
  Assert no new `core→services`/`core→api` import edges (import-linter stays `7 kept`).

## Sequencing & commits

One commit per fix, suite green after each, in order F1 → F2 → F3 → F4 → F5. F5 last (largest, behavior
change). Re-run `pytest -q` (expect ≥1098 passing, +N new char tests) + `pytest tests/test_import_linter.py`
after each. After F5, drive an end-to-end check of the reconnect-resume path if hardware is available;
otherwise rely on the char tests + note the manual-verification gap.
