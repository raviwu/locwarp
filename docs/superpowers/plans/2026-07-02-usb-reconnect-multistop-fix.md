# USB Reconnect / Multi-Stop Early-Termination Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop multi-point navigation from silently abandoning route legs on the USB device "Renee" by (1) preventing self-inflicted USB-tunnel churn from concurrent connects and (2) making the USB DVT reconnect path actually rebuild the dead tunnel instead of spinning on a stale lockdown for 15s.

**Architecture:** Two independent, internal-only fixes in the `core/` ring. **W3** adds a per-UDID *connect in-flight latch* in `DeviceManager.connect()` so overlapping auto-connect triggers (startup discover + usbmux watchdog + `full_reconnect`) coalesce instead of each opening a second helper tunnel (which collide with helper error `-32003`). **W1** makes `DeviceManager.get_fresh_dvt_provider()` escalate a dead-USB-lockdown to `full_reconnect()` (which rebuilds tunnel + RSD + DvtProvider) rather than retrying the same orphaned lockdown until the 15s deadline. Both are behind the existing `dvt_factory` / recovery seams — no external HTTP/WS/IPC surface changes.

**Tech Stack:** Python 3.13 (backend), FastAPI, `pymobiledevice3`, pytest + pytest-asyncio (`asyncio_mode = strict`), pytest-timeout.

## Root Cause (evidence)

Logs (`~/.locwarp/logs/backend.log*`, 2026-07-02 03:42–03:44) show, for Renee (`00008120-0018598E1120C01E`, **iOS 26.5, USB — `Network=0, USB=7280`**):

1. The iOS 17+ RemoteXPC tunnel that USB rides on dies mid-navigation (`DTX reader exiting: connection terminated` → `ConnectionTerminatedError`).
2. `DvtLocationService.set()` catches the drop → `_reconnect()` → `dvt_factory` → `DeviceManager.get_fresh_dvt_provider()`.
3. For USB, `get_fresh_dvt_provider` (device_manager.py:1249→1262) skips the tunnel-rebuild branch (that branch is gated on `connection_type == "Network"`) and just retries `DvtProvider(conn.lockdown)` on the **already-dead** lockdown for the full **15s** (`min(0.5, remaining)` backoff), then raises `DeviceLostError`.
4. `DeviceLostError` is **not** a `ConnectionError`/`OSError`, so `SimulationEngine._push_with_retry` (simulation_engine.py:606) hits its generic `except Exception` → returns `False` immediately → `_move_along_route` (simulation_engine.py:800) logs **"Giving up on this route after repeated push failures"** and abandons the leg.
5. This repeats every ~16s for 5–6 legs (~90s of dead navigation) until the API-layer `full_reconnect` safety net (which is *not* on the multi-stop push path) eventually does a real teardown+reconnect (`Disconnected device` → `Connecting via USB` → new tunnel → `DVT provider re-acquired`).

Separately, Renee shows **44** `helper error -32003: tunnel already exists` collisions (vs Ravioli's 3) and repeated same-second bursts of **2–3 concurrent `Connecting to 00008120 via USB`** — because `connect()` checks membership under the lock, *releases the lock*, then does the slow tunnel build, so two overlapping triggers both build a tunnel for the one device. USB is uniquely exposed because the usbmux watchdog fires an auto-connect on every usbmuxd event; the WiFi device never gets those.

**Not a code regression on this path:** the only commit in the "worked 2–3 days ago → broke by 07-02" window is `012237e` (goldditto, 07-01), which does not touch `connect` / `get_fresh_dvt_provider` / `_push_with_retry` / `_move_along_route`. Onset is environmental (Renee's USB RemoteXPC tunnel became less stable — commonly after an iOS point-update); the two code weaknesses above turn a transient tunnel blip into a navigation-killing 90s stall. See conversation transcript 2026-07-02 for full forensics.

## Global Constraints

- **Behavior / API freeze:** no external HTTP / WS / IPC change. All edits are internal to `core/device_manager.py` and its tests. WS payload shapes unchanged.
- **Backend test suite stays green after every commit.** Pin the exact baseline first: `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1` (CLAUDE.md records ≈914). Record the number in Task 0.
- **Danger-zone test-first.** `device_manager` recovery has characterization tests but is thinly covered; write the failing characterization test **before** the implementation for each fix. Assert ordered exact values.
- **Layering (import-linter `7 kept, 0 broken`):** add **no new cross-ring imports**. Reuse only what `core/device_manager.py` already imports (`full_reconnect` is a method on the same class; `DeviceLostError`, `DvtProvider`, `list_devices`, `open_tunnel_with_reconcile` are already imported there). Verify contracts stay green in Task 3.
- **Thick carve-outs stay leaky:** do not abstract `pymobiledevice3` / tunnel-helper guts into new pure cores. W1 reuses the existing `full_reconnect()` path rather than hand-rolling a second tunnel-build.
- **Test command:** `cd backend && .venv/bin/python -m pytest <args>`. `asyncio_mode = strict`; device-hardware tests use the `macos_only` marker (auto-skipped off Darwin); pytest-timeout guards blocking-Event tests.
- **Git identity** is auto-set by `~/.gitconfig` includeIf — never pass `-c user.email=…`. Personal repo ships direct commits to `main`; one commit per task.

---

## Design Decisions

### W3 — how to stop concurrent connects from building duplicate tunnels

| Option | Approach | Trade-off |
|---|---|---|
| **W3-a** Coalescing future map | `self._connecting: dict[str, Future]`; second caller awaits the first's result | Best (second re-does no work) but must hand-manage future resolution + exception fan-out |
| **W3-b (recommended)** Per-UDID connect lock | `self._connect_locks: dict[str, asyncio.Lock]`; wrap the connect body; second caller waits, re-checks membership, returns | Minimal & correct; does **not** hold the global `_lock` during slow I/O; loser waits ~1 build then bails. Slight per-UDID lock retained in a dict (negligible) |
| **W3-c** Hold `self._lock` for the whole build | Move membership-check + claim to span the tunnel build under `_lock` | **Rejected** — `_lock` guards `_connections` and is taken by the watchdog/discovery/teardown; holding it during multi-second tunnel builds serializes/deadlocks the manager (the current code releases it deliberately) |

**Recommendation: W3-b.** The existing end-of-`connect()` atomic-claim (pop-displaced + lock-free teardown, device_manager.py:545–561) stays as the cross-path safety net (still exercised by `test_device_manager_wifi_tunnel_race_char.py`); the latch just prevents the *identical-UDID* duplicate build that produces `-32003`.

### W1 — how to recover a dead USB lockdown inside `get_fresh_dvt_provider`

| Option | Approach | Trade-off |
|---|---|---|
| **W1-a** Rebuild tunnel+RSD inline | Call `open_tunnel_with_reconcile("open_usb_tunnel", udid)` + new RSD inside `get_fresh_dvt_provider`, swap `conn.lockdown` | Fast, no full disconnect, but **duplicates** the tunnel-build/RSD logic that lives in `_connect_tunnel` — violates "thick carve-outs stay leaky / one place" |
| **W1-b (recommended)** Escalate to `full_reconnect()` | On USB DvtProvider-open failure, call `self.full_reconnect(udid)` (existing: disconnect+connect → rebuilds tunnel+RSD+DvtProvider), return the fresh `conn.dvt_provider` | Reuses the proven recovery path; ~0.4s in logs; one extra transient `DvtLocationService` created by `connect()` is harmless. Depends on W3 so the `connect()` it invokes is race-safe |
| **W1-c** Just shorten the USB timeout | Drop `timeout` 15→~3s and lean on the API-layer safety net | **Rejected as sole fix** — the API-layer `full_reconnect` is not on the multi-stop push path, so navigation still abandons legs |

**Recommendation: W1-b**, guarded to escalate at most once per `get_fresh_dvt_provider` call (no recursion: `connect()` opens its DvtProvider directly, never via the factory). Land **W3 first** so the escalated `connect()` cannot itself race.

### W2 — navigation resilience to a genuine device loss *(deferred, not in this plan)*

After W1, a transient tunnel death recovers inside `_reconnect()` and the push lands, so legs are no longer abandoned. A *genuine* unplug still surfaces `DeviceLostError` and abandons the run — which is correct behavior. Making `_move_along_route` pause-and-resume across a true device loss would require importing `DeviceLostError` into the `core` ring (a `core→services` edge that breaks import-linter) or a new domain error + port method. **YAGNI for the reported bug; recorded as a follow-up, not a task.**

Also recorded as follow-up (not this plan): debounce the usbmux watchdog so it stops firing an auto-connect every ~1s for an already-connected device (noise reduction; W3 already neutralizes the harm).

---

## File Structure

- **Modify** `backend/core/device_manager.py`
  - `DeviceManager.__init__` — add `self._connect_locks: dict[str, asyncio.Lock] = {}`
  - `DeviceManager.connect()` (currently 474–563) — wrap the body in the per-UDID latch (W3)
  - `DeviceManager.get_fresh_dvt_provider()` (currently 1214–1292) — USB escalation to `full_reconnect` (W1)
- **Modify** `backend/tests/test_device_manager_connect_race_char.py` — replace the barrier-based identical-UDID race test with the coalescing test (W3)
- **Modify** `backend/tests/test_device_manager_fresh_dvt.py` — add the USB-escalation characterization test (W1)

No new files. No frontend changes.

---

## Task 0: Pin the baseline

- [ ] **Step 1: Record the current collected-test count and green state**

Run:

```bash
cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1
cd backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py tests/test_device_manager_fresh_dvt.py -q
```

Expected: a count near 914 (write it down); both target files PASS.

- [ ] **Step 2: (optional) create a working branch**

```bash
git switch -c fix/usb-reconnect-multistop
```

(Personal repo may also commit straight to `main`; either is fine.)

---

## Task 1: W3 — per-UDID connect in-flight latch

**Files:**
- Modify: `backend/core/device_manager.py` (`__init__`; `connect()` 474–486)
- Test: `backend/tests/test_device_manager_connect_race_char.py`

**Interfaces:**
- Consumes: existing `DeviceManager.connect(udid: str) -> None`, `DeviceManager._connect_tunnel(self, udid, lockdown, ios_version) -> _ActiveConnection`, module-level `list_devices`, `services.usbmux_pair_records.autopair_with_recovery`.
- Produces: no signature change. New private attribute `DeviceManager._connect_locks: dict[str, asyncio.Lock]`. Post-condition: concurrent `connect(udid)` for the same udid build the tunnel **once**.

- [ ] **Step 1: Replace the identical-UDID race test with a coalescing characterization test**

In `backend/tests/test_device_manager_connect_race_char.py`, replace the body of the existing `test_connect_same_udid_concurrent_claims_atomically` (the barrier version deadlocks once the latch lands, because only one coroutine ever enters `_connect_tunnel`) with this test. Keep the file's existing imports/stubs (`dm_mod`, `pair_mod`, `_StubLockdown`, `_Raw`, `_async_value`, `_ActiveConnection`); add them if the rewrite removed any.

```python
@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_connect_same_udid_coalesces_no_duplicate_tunnel(monkeypatch):
    """Two overlapping connect(udid) for the SAME device must build the helper
    tunnel exactly once. Without the per-UDID latch the second call passes the
    membership check while the first is still building and opens a second
    tunnel (real-world: helper error -32003 'tunnel already exists')."""
    monkeypatch.setattr(dm_mod, "list_devices",
                        lambda: _async_value([_Raw("UDID-USB")]))
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)

    async def _fake_autopair(udid, autopair=True):
        return _StubLockdown(), False
    monkeypatch.setattr(pair_mod, "autopair_with_recovery", _fake_autopair)

    mgr = DeviceManager()
    build_count = 0
    build_started = asyncio.Semaphore(0)   # released each time a build begins
    release_first = asyncio.Event()        # holds the first build "in flight"

    async def _fake_connect_tunnel(self, udid, lockdown, ios_version):
        nonlocal build_count
        build_count += 1
        build_started.release()
        await release_first.wait()
        return _ActiveConnection(udid=udid, lockdown=lockdown,
                                 ios_version=ios_version, rsd=lockdown)
    monkeypatch.setattr(DeviceManager, "_connect_tunnel",
                        _fake_connect_tunnel, raising=True)

    t1 = asyncio.create_task(mgr.connect("UDID-USB"))
    await build_started.acquire()          # first build is in flight

    t2 = asyncio.create_task(mgr.connect("UDID-USB"))
    # Give t2 ample opportunity to (wrongly) start a SECOND build.
    try:
        await asyncio.wait_for(build_started.acquire(), timeout=0.5)
        second_build_started = True
    except asyncio.TimeoutError:
        second_build_started = False

    assert second_build_started is False   # RED without latch, GREEN with it

    release_first.set()
    await asyncio.gather(t1, t2)

    assert build_count == 1
    assert list(mgr._connections.keys()) == ["UDID-USB"]
```

- [ ] **Step 2: Run it to confirm RED**

Run:

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py::test_connect_same_udid_coalesces_no_duplicate_tunnel -v
```

Expected: FAIL on `assert second_build_started is False` (the second connect starts a second build), or the older barrier test hangs — either confirms the missing latch.

- [ ] **Step 3: Add the latch dict to `__init__`**

In `DeviceManager.__init__` (add next to the other per-manager state), insert:

```python
        # Per-UDID connect latch: serializes overlapping connect(udid) so
        # concurrent auto-connect triggers (startup discover + usbmux watchdog +
        # full_reconnect) coalesce instead of each opening a second helper tunnel
        # (which collide with helper error -32003 "tunnel already exists").
        self._connect_locks: dict[str, asyncio.Lock] = {}
```

- [ ] **Step 4: Wrap the `connect()` body in the per-UDID latch**

In `core/device_manager.py`, change the head of `connect()` from:

```python
        async with self._lock:
            if udid in self._connections:
                logger.info("Device %s is already connected", udid)
                return
```

to:

```python
        # setdefault has no await between get and set, so it is atomic on the
        # single-threaded loop — two concurrent callers get the SAME Lock.
        connect_lock = self._connect_locks.setdefault(udid, asyncio.Lock())
        async with connect_lock:
            async with self._lock:
                if udid in self._connections:
                    logger.info("Device %s is already connected", udid)
                    return
            return await self._connect_locked(udid)

    async def _connect_locked(self, udid: str) -> None:
        """Body of connect(), run under the per-UDID connect latch."""
```

Everything from the existing "Detect connection type from usbmux device list." comment (device_manager.py:488) through the final `logger.info("Connected to %s ...")` (line 563) becomes the body of the new `_connect_locked` method — move it verbatim (adjust indentation only; it was already one level under `connect`). No logic inside changes.

> Rationale: the loser blocks on `connect_lock`; when it acquires, the winner has installed the connection, so the `udid in self._connections` re-check returns immediately — no second `_connect_tunnel`, no `-32003`. The global `self._lock` is only held for the membership check, never during the slow build.

- [ ] **Step 5: Run the new test + the whole connect-race file GREEN**

Run:

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py tests/test_device_manager_wifi_tunnel_race_char.py -v
```

Expected: PASS (coalescing test green; the cross-path WiFi-tunnel atomic-claim test still green — the end-of-connect teardown safety net is unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/core/device_manager.py backend/tests/test_device_manager_connect_race_char.py
git commit -m "fix(device): per-UDID connect latch — coalesce concurrent connects, kill duplicate USB tunnels (-32003)

Overlapping auto-connect triggers (startup discover + usbmux watchdog +
full_reconnect) each passed connect()'s membership check while the first
was still building, opening a second helper tunnel for the same USB device
(helper -32003 'tunnel already exists', 44x on Renee vs 3x on the WiFi
device). The churned tunnel dropped the live DVT channel mid-navigation.
Serialize connect(udid) behind a per-UDID asyncio.Lock; the loser re-checks
membership and returns without a second build. Global _lock is never held
during the slow tunnel build.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: W1 — `get_fresh_dvt_provider` rebuilds a dead USB tunnel via `full_reconnect`

**Files:**
- Modify: `backend/core/device_manager.py` (`get_fresh_dvt_provider()` 1214–1292)
- Test: `backend/tests/test_device_manager_fresh_dvt.py`

**Interfaces:**
- Consumes: existing `DeviceManager.full_reconnect(self, udid: str) -> bool` (USB branch does disconnect+connect and repopulates `conn.dvt_provider` via `_create_dvt_location_service`), `_ActiveConnection` (fields `udid, lockdown, ios_version, connection_type, dvt_provider`), module-level `DvtProvider`.
- Produces: `get_fresh_dvt_provider(udid, *, timeout=15.0)` unchanged signature; new behavior — on a USB connection whose cached lockdown cannot open a DvtProvider, it escalates to `full_reconnect(udid)` **once** and returns the rebuilt `conn.dvt_provider`.

- [ ] **Step 1: Write the failing USB-escalation characterization test**

Append to `backend/tests/test_device_manager_fresh_dvt.py` (reuse the file's `_FakeDvt`; add the small stubs if not already present):

```python
class _StubLockdownFR:
    def __init__(self):
        self.all_values = {"ProductVersion": "26.5", "DeviceName": "Renee"}


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_get_fresh_dvt_usb_escalates_to_full_reconnect(monkeypatch):
    """On USB, when the cached lockdown is dead (DvtProvider.__aenter__ keeps
    failing), get_fresh_dvt_provider must escalate to full_reconnect (which
    rebuilds tunnel+RSD+DvtProvider) and return the freshly-opened provider —
    instead of spinning on the orphaned lockdown until the deadline and
    raising DeviceLostError."""
    from core.device_manager import DeviceManager, _ActiveConnection

    _FakeDvt.instances = []
    _FakeDvt.fail_remaining = 10_000  # every open on the STALE lockdown fails
    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    dm = DeviceManager()
    conn = _ActiveConnection(
        udid="UDID-USB",
        lockdown=_StubLockdownFR(),
        ios_version="26.5",
        connection_type="USB",
    )
    dm._connections["UDID-USB"] = conn

    healthy = object()  # what connect()/_create_dvt_location_service would install
    reconnect_calls = []

    async def _fake_full_reconnect(udid):
        reconnect_calls.append(udid)
        conn.dvt_provider = healthy
        return True
    monkeypatch.setattr(dm, "full_reconnect", _fake_full_reconnect)

    provider = await dm.get_fresh_dvt_provider("UDID-USB", timeout=1.0)

    assert reconnect_calls == ["UDID-USB"]   # escalated exactly once
    assert provider is healthy               # returned the rebuilt provider
```

- [ ] **Step 2: Run it to confirm RED**

Run:

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_manager_fresh_dvt.py::test_get_fresh_dvt_usb_escalates_to_full_reconnect -v
```

Expected: FAIL — `full_reconnect` is never called for USB today; the call raises `DeviceLostError` after the (1.0s) deadline instead of returning `healthy`.

- [ ] **Step 3: Add the USB escalation to `get_fresh_dvt_provider`**

In `core/device_manager.py`, initialize a one-shot flag just before the `while True:` loop:

```python
        import time
        deadline = time.monotonic() + timeout
        last_exc: Exception | None = None
        usb_reconnect_tried = False   # W1: escalate a dead USB lockdown once
```

Then, inside the `except Exception as exc:` block of the DvtProvider-open `try` (the block that currently sets `last_exc`, checks the deadline, sleeps, and continues), insert the escalation **before** the `remaining = deadline - time.monotonic()` line:

```python
            except Exception as exc:
                last_exc = exc
                # W1: for USB, retrying the SAME cached lockdown is futile once
                # the RemoteXPC tunnel has died — the RSD/lockdown rides that
                # tunnel. Escalate once to full_reconnect (teardown + reconnect
                # rebuilds tunnel + RSD + DvtProvider) and hand back the fresh
                # provider. WiFi keeps its existing tunnel-restart-wait branch
                # above. No recursion: connect() opens its DvtProvider directly.
                if conn.connection_type != "Network" and not usb_reconnect_tried:
                    usb_reconnect_tried = True
                    logger.info(
                        "get_fresh_dvt_provider: USB lockdown dead for %s (%s); "
                        "escalating to full_reconnect", udid, exc,
                    )
                    try:
                        if await self.full_reconnect(udid):
                            async with self._lock:
                                fresh = self._connections.get(udid)
                            if fresh is not None and fresh.dvt_provider is not None:
                                logger.info(
                                    "DVT provider re-acquired via full_reconnect for %s",
                                    udid,
                                )
                                return fresh.dvt_provider
                    except Exception:
                        logger.exception(
                            "get_fresh_dvt_provider: USB full_reconnect failed for %s",
                            udid,
                        )
                    # fall through to the normal deadline/backoff below
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning(
                        "get_fresh_dvt_provider exhausted for %s: %s", udid, exc,
                    )
                    raise DeviceLostError(
                        f"Could not open DvtProvider for {udid}: {exc}",
                        reason=DeviceLostError.REASON_LOCKDOWN_DEAD,
                    ) from exc
                await asyncio.sleep(min(0.5, remaining))
                continue
```

(Only the escalation block is new; the `remaining` / deadline / sleep lines already exist — keep them exactly as-is.)

- [ ] **Step 4: Run the new test + the whole fresh-dvt file GREEN**

Run:

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_manager_fresh_dvt.py -v
```

Expected: PASS — new escalation test green; the existing retry test (USB open fails once then succeeds, `full_reconnect` never needed because the second open succeeds before the flag path fires) and the DeviceLost test (WiFi/no-escalation) still green.

> Note for reviewers: the existing "fail once then succeed" retry test never reaches the escalation branch — its `_FakeDvt.fail_remaining = 1` means the second open succeeds on the same loop iteration's next pass. The escalation only fires when the USB open keeps failing.

- [ ] **Step 5: Commit**

```bash
git add backend/core/device_manager.py backend/tests/test_device_manager_fresh_dvt.py
git commit -m "fix(device): USB get_fresh_dvt_provider escalates dead lockdown to full_reconnect

For USB, a dropped RemoteXPC tunnel orphans conn.lockdown; the old reconnect
loop just retried DvtProvider(conn.lockdown) on that dead lockdown for the
full 15s deadline, then raised DeviceLostError — which the engine's
_push_with_retry treats as non-retryable, so multi-stop abandoned the leg
('Giving up on this route') and re-stalled every ~16s for ~90s. Escalate a
dead USB lockdown once to full_reconnect (rebuilds tunnel+RSD+DvtProvider)
and return the fresh provider. WiFi keeps its tunnel-restart-wait branch.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Full verification + device smoke

**Files:** none (verification only).

- [ ] **Step 1: Full backend suite green, count not regressed**

Run:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: all pass; collected count = Task 0 baseline **+2** new tests (one rewritten in place in Task 1, one added in Task 2 → net +1 vs baseline if the barrier test was replaced 1:1; confirm the delta matches what you changed).

- [ ] **Step 2: Import-linter contracts still `7 kept, 0 broken`**

Run:

```bash
cd backend && .venv/bin/python -m pytest -q -k "import_linter or contracts" || true
make -C .. verify 2>/dev/null || (cd backend && .venv/bin/lint-imports)
```

Expected: `7 kept, 0 broken` (no new cross-ring import was added).

- [ ] **Step 3: Real-device smoke on Renee (macOS, USB) — automated capture first**

With Renee plugged in via USB and the backend running (`cd backend && .venv/bin/python main.py`), run a multi-point navigation of ≥4 waypoints and watch the log:

```bash
grep -nE 'Giving up on this route|get_fresh_dvt_provider exhausted|-32003|full_reconnect (succeeded|via)|DVT provider re-acquired' ~/.locwarp/logs/backend.log | tail -40
```

Expected after the fix:
- **Zero (or isolated single) `-32003`** bursts on a fresh connect (was 2–3 concurrent builds per second).
- On a mid-run tunnel drop: `escalating to full_reconnect` → `DVT provider re-acquired via full_reconnect` within ~1s, and **no** repeated `Giving up on this route` cascade.
- Navigation continues through all legs instead of stopping after `Multi-stop finished after 0 laps`.

- [ ] **Step 4: Commit any doc/status updates (if needed) and finish**

Update the memory/status note if you track one; otherwise no commit. Merge the branch per the personal-repo direct-to-main convention:

```bash
git switch main && git merge --ff-only fix/usb-reconnect-multistop   # if a branch was used
```

---

## Self-Review

1. **Spec coverage:** W3 (duplicate-tunnel / `-32003`) → Task 1. W1 (USB reconnect spins on dead lockdown → give-up cascade) → Task 2. Verification incl. import-linter + device smoke → Task 3. W2 explicitly deferred with rationale. ✅
2. **Placeholder scan:** every code step shows real code; test asserts use exact values (`build_count == 1`, `reconnect_calls == ["UDID-USB"]`, `provider is healthy`). ✅
3. **Type/name consistency:** `_connect_locks` (dict[str, asyncio.Lock]) defined in Task 1 `__init__`, used in Task 1 `connect()`. `_connect_locked` introduced and referenced in the same task. `full_reconnect(udid) -> bool` and `conn.dvt_provider` used in Task 2 match `_ActiveConnection` / `device_manager.py`. `_FakeDvt` (fields `instances`, `fail_remaining`) reused from the existing fresh-dvt test. ✅
4. **Constraint check:** no external surface change; no new cross-ring import (reuses `full_reconnect`, `DvtProvider`, `DeviceLostError` already in `device_manager.py`); test-first for both danger-zone edits; per-task commits keep the suite green. ✅

---

## Task 4 (added post-final-review): Fix re-entrant deadlock in W1 escalation + dead early-return branch

**Found by:** the final whole-branch reviewer (agentId a843f40eb916d5c7f), independently confirmed by the controller reading `location_service.py` and `device_manager.py` directly.

**Root cause (Critical):** `get_fresh_dvt_provider()` is only ever invoked in production via the `dvt_factory` closure bound in `_create_dvt_location_service` (`device_manager.py:926-927`), which is called from inside `DvtLocationService._reconnect()` (`services/location_service.py:116-189`) while `self._reconnect_lock` (non-reentrant `asyncio.Lock`) is held. `conn.location_service` (the connection's cached `DvtLocationService`, set in `get_location_service()` at `device_manager.py:739`) is therefore *always* the exact same instance whose `_reconnect()` is on the call stack when the USB escalation fires.

When the USB escalation calls `full_reconnect(udid)`, the USB branch (`device_manager.py:1364-1375`) does `await self.disconnect(udid)`, which pops the connection and calls `_teardown_connection` (`:661-677`), which — if `conn.location_service is not None` — calls `await conn.location_service.clear()` (`:673-675`). This re-enters the SAME `DvtLocationService.clear()` (`services/location_service.py:211-232`); if `_ensure_instrument()`/`sim.clear()` raises any of `(ConnectionTerminatedError, OSError, EOFError, BrokenPipeError, ConnectionResetError, asyncio.TimeoutError)` — highly plausible right after a dead tunnel, since `self._dvt` was already closed via `__aexit__` at `_reconnect()`'s top (`location_service.py:134`) before the factory call — `clear()`'s except handler calls `await self._reconnect()` again (`:225`), which tries to re-acquire `self._reconnect_lock` — already held by the same task. `asyncio.Lock` is non-reentrant: this blocks forever. **Permanent hang of the navigation coroutine**, worse than the 90s stall this whole plan set out to fix.

All three existing/added tests stub `full_reconnect`, so this real call chain was never exercised — the danger-zone test-first requirement was satisfied for the *escalation* logic but not for its downstream reentrancy interaction.

**Fix:** detach `conn.location_service` (set it to `None`) immediately before calling `full_reconnect` in the escalation branch, so `_teardown_connection`'s guard (`if conn.location_service is not None`) skips the re-entrant `clear()` call. This is safe because `disconnect()` unconditionally pops and discards the whole `_ActiveConnection` object regardless of `full_reconnect`'s outcome — the field would be thrown away either way; nulling it just prevents the redundant/dangerous nested teardown call during the window it's still reachable.

**Root cause (Important, same review):** the escalation's early-return branch (`if fresh is not None and fresh.dvt_provider is not None: return fresh.dvt_provider`, `device_manager.py:1294-1301`) is dead code in production — `full_reconnect`'s USB path is `disconnect()` + `connect()`, and `connect()`/`_connect_locked()` never populates `conn.dvt_provider` (only `_create_dvt_location_service`, called from `get_location_service()`, does — `device_manager.py:916`). So after a real `full_reconnect`, `fresh.dvt_provider` is always `None`, and the *actual* production recovery is the fall-through to the next `while True` iteration, which retries `DvtProvider(conn.lockdown)` on the freshly rebuilt lockdown and returns via the pre-existing success path (`:1320-1333`, logging `"DVT provider re-acquired for %s"` — NOT `"... via full_reconnect"`). The existing `test_get_fresh_dvt_usb_escalates_to_full_reconnect` test (added in Task 2) only exercises this dead branch (its stub sets `conn.dvt_provider = healthy` and returns `True`, asserting `provider is healthy`) — a postcondition the real `full_reconnect` never establishes.

**Fix:** remove the dead early-return branch entirely (YAGNI — this codebase's convention is not to keep defensive code for scenarios that can't happen). The escalation becomes: call `full_reconnect`, log success/failure, and unconditionally fall through to the existing deadline/backoff/continue logic — the next loop iteration's normal retry-and-succeed path already handles the recovery correctly. Update `test_get_fresh_dvt_usb_escalates_to_full_reconnect` to match: assert `full_reconnect` was called once (`reconnect_calls == ["UDID-USB"]`), then let a second loop iteration's `DvtProvider` open succeed (via `_FakeDvt.fail_remaining`) and assert the provider returned is the one from that normal success path, not a `full_reconnect`-injected sentinel.

Also update the plan's Task 3 Step 3 smoke-grep expectation: the real log sequence after a mid-run tunnel drop is `escalating to full_reconnect` → (no `"DVT provider re-acquired via full_reconnect"` — that log line and branch are removed) → `"DVT provider re-acquired for %s"` (the normal-path log, now reached via the fall-through retry). Watch for this corrected sequence during the real-device smoke, not the old expectation.

### Step 1: Write the RED regression test for the deadlock

In `backend/tests/test_device_manager_fresh_dvt.py`, add a test that drives the exact production call chain end-to-end: a real `DvtLocationService` (from `services.location_service`) whose `dvt_factory` is bound to `dm.get_fresh_dvt_provider`, with `conn.location_service` set to that same instance; force the first `DvtProvider` open to fail (triggering escalation); stub `DeviceManager.connect` (not `full_reconnect` — leave `full_reconnect`'s own disconnect/teardown logic real) to simulate a successful reconnect (install a fresh `_ActiveConnection` and let the next `DvtProvider` open succeed); give the service's `_ensure_instrument` a stub whose `.clear()` raises `pymobiledevice3.exceptions.ConnectionTerminatedError` (imported the same way `location_service.py` does) so the pre-fix nested `_teardown_connection` → `conn.location_service.clear()` call hits the reconnect-triggering exception path. Guard the test with `@pytest.mark.timeout(5)` (or similar short bound) so a regression fails fast with a timeout instead of hanging the suite. Call `await service.clear()` directly (simulating the engine detecting a dropped channel) and assert it completes (does not raise `asyncio.TimeoutError` from the test timeout marker) and that the factory was invoked exactly once.

Confirm this test hangs/times out against the current (pre-fix) code.

### Step 2: Apply the fix

In `get_fresh_dvt_provider`'s escalation block (`device_manager.py:1286-1307` before this task), before calling `full_reconnect`:

```python
                if conn.connection_type != "Network" and not usb_reconnect_tried:
                    usb_reconnect_tried = True
                    logger.info(
                        "get_fresh_dvt_provider: USB lockdown dead for %s (%s); "
                        "escalating to full_reconnect", udid, exc,
                    )
                    # Detach location_service before escalating: full_reconnect's
                    # USB path tears down THIS EXACT connection via disconnect(),
                    # which would otherwise call conn.location_service.clear() —
                    # re-entering the very DvtLocationService._reconnect() call
                    # that (via the bound dvt_factory) got us here, deadlocking
                    # on its non-reentrant _reconnect_lock. Safe to null: disconnect()
                    # unconditionally discards this _ActiveConnection regardless of
                    # full_reconnect's outcome, so the field is thrown away either way.
                    conn.location_service = None
                    try:
                        if not await self.full_reconnect(udid):
                            logger.warning(
                                "get_fresh_dvt_provider: USB full_reconnect failed for %s",
                                udid,
                            )
                    except Exception:
                        logger.exception(
                            "get_fresh_dvt_provider: USB full_reconnect failed for %s",
                            udid,
                        )
                    # fall through to the normal deadline/backoff below; the next
                    # loop iteration re-fetches conn (now the rebuilt connection)
                    # and retries DvtProvider(conn.lockdown), succeeding via the
                    # pre-existing normal-path return below.
```

(Removes the `if await self.full_reconnect(udid): ... return fresh.dvt_provider` early-return entirely — replaced with the simpler call-and-log-only form above.)

### Step 3: Confirm GREEN

Re-run the new deadlock regression test (must now complete, not time out) and the whole `test_device_manager_fresh_dvt.py` file.

### Step 4: Fix the Important finding — dead branch test

Update `test_get_fresh_dvt_usb_escalates_to_full_reconnect` (added in Task 2): the mocked `full_reconnect` should leave `conn.dvt_provider` as `None` (matching reality) and instead swap `conn.lockdown` to a healthy stub and let `_FakeDvt.fail_remaining` allow the SECOND `DvtProvider` open (the fall-through retry, on the rebuilt lockdown) to succeed. Assert `reconnect_calls == ["UDID-USB"]` (escalated once) and that the returned provider is the one from the normal-path success (e.g. `provider is _FakeDvt.instances[-1]`), not a `full_reconnect`-injected sentinel object.

### Step 5: Full local verification + commit

Run the whole `test_device_manager_fresh_dvt.py` file, plus `test_device_manager_connect_race_char.py` as a sanity check (shares `DeviceManager`). Then run the full backend suite and `lint-imports` once more (expect 1100 passed given +1 net new test from this task; `7 kept, 0 broken`). Commit as a new commit (not amending), message summarizing: fixes a re-entrant deadlock in the USB DVT-recovery escalation (W1) where `full_reconnect`'s teardown could re-enter the calling `DvtLocationService`'s non-reentrant reconnect lock, plus removes the escalation's dead early-return branch (never reachable in production — `connect()` doesn't populate `dvt_provider`) and updates its test to match the real fall-through recovery path.
