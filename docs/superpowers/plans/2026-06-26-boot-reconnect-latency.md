# Boot + Reconnect Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan. Each task is dispatched to an implementer subagent then an adversarial reviewer subagent; use an opus-class model for the danger-zone backend tasks (Task 2 lifespan / Task 3 device-connect). Steps use checkbox (- [ ]) syntax — check each off as it completes. Do the steps in order; do not batch. Every commit must leave the full suite green (see Global Constraints).

**Goal:** Cut the wait on the two most-felt latency paths — "app launch → usable" and "tunnel drop → recovered" — with four small, low-risk changes that preserve all external behavior except the (intended) reconnect cadence.

**Architecture:** Defer two heavy boot-time operations (geo enrichment, device auto-connect) off the lifespan critical path by spawning them as concurrent background tasks (the server starts serving immediately); make WiFi auto-connect fire saved-device candidates immediately instead of after a 3s discover; and tighten the tunnel-restart backoff so the first reconnect attempt is near-instant. No new endpoints/events; no structural refactor.

**Tech Stack:** FastAPI/Python backend, React 18 + TS + Electron frontend, Vitest + pytest, import-linter + dependency-cruiser gates.

## Global Constraints

Every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` (baseline ≈1035 collected) + frontend `vitest` (≈857) + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit.
- **Danger-zone-test-first.** `main.py` lifespan, `device_manager` connect path, and `simulation_engine`/movers have NO direct unit tests. Write characterization tests (REAL collaborators, never stub the unit under test) BEFORE touching them.
- **Behavior preserved, latency only.** The eventual state must be identical: the device still auto-connects, geo fields still get enriched, WiFi auto-connect still connects, reconnect still recovers. The ONE intended external-observable change is the tunnel-restart backoff cadence (which changes the `tunnel_degraded` event's `next_delay_s`/`max_attempts` values — see Task 1). No new HTTP/WS/IPC surface.
- **Lock & inversion rules hold.** `device_manager → EventPublisher` stays awaited in-line / order-preserving; never acquire the WS connection-manager lock under `device_manager._lock`. Bookmark/route writes stay under `_store_lock`.
- **Preserve the WiFi-auto-connect thrash fix.** The `connectedDevices` ref-mirror guard (memory: `wifi_autoconnect_tunnel_thrash`, fixed 2026-06-23) MUST remain intact — a spurious WiFi tunnel must never tear down a healthy USB tunnel.
- **Personal-repo conventions.** Direct commits to a single cluster branch → ff-merge to `main`; git identity auto-set (never `-c user.email=`).

---

### Task 0: Pin baselines + create the cluster branch

**Files:** none (setup only).

**Interfaces:**
- Consumes: the current `main` tip.
- Produces: branch `boot-reconnect-latency`; recorded baseline counts.

- [ ] **Step 1: Create the cluster branch.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git checkout main && git pull --ff-only && git checkout -b boot-reconnect-latency
  ```
  Expected: `Switched to a new branch 'boot-reconnect-latency'`.

- [ ] **Step 2: Pin the backend pytest collection count.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1
  ```
  Expected: a line like `1035 tests collected in ...`. Record the exact number — every later backend commit must keep this count green (additions are fine; no test may break).

- [ ] **Step 3: Pin the frontend vitest count + tsc + depcruise.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run 2>&1 | tail -5 && npx tsc --noEmit && echo "TSC_OK"
  ```
  Expected: vitest summary `Tests  857 passed` (≈), then `TSC_OK` with no type errors. Record the vitest count.

- [ ] **Step 4: Pin the lint gates.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m import_linter --config .importlinter 2>/dev/null | tail -3
  ```
  Expected: `Contracts: 7 kept, 0 broken.` (If `.importlinter` lives elsewhere, run `lint-imports` from the repo `Makefile` target — check `grep -n import_linter Makefile`.) Then:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -3
  ```
  Expected: `no dependency violations found` / `0 errors, 0 warnings`. (If the exact invocation differs, use the repo's `npm run depcruise` / Makefile target — `grep -rn depcruise package.json Makefile`.)

---

### Task 1: Faster tunnel-restart backoff + coupled char-test updates (Win 4)

Self-contained, no deferral risk. The backoff constant change and the THREE char-test updates MUST land in the SAME commit — the char-tests assert `next_delay_s` / `max_attempts` derived directly from the backoff tuple, so splitting them would leave a red commit.

**Files:**
- `backend/api/device.py` — the constant `_TUNNEL_RESTART_BACKOFF` (currently line ~740).
- `backend/tests/test_watchdog_tunnel_lost_reason_char.py` (lines 62–69 and 105–111 — the two `tunnel_degraded` deep-equals).
- `backend/tests/test_wifi_tunnel_service_watchdog_char.py` (line 38 `restart_backoff`, and the two `tunnel_degraded` deep-equals at 59–66 and 86–92).
- `backend/tests/test_wifi_tunnel_degraded_attempt_char.py` (lines 60 and 84 `restart_backoff`, and the two `tunnel_degraded` deep-equals at 63–70 and 87–93).

**Interfaces:**
- Consumes: `_TUNNEL_RESTART_BACKOFF: tuple[float, ...]` read at `api/device.py:794` (passed as `restart_backoff` into `WifiTunnelService`). `services/wifi_tunnel_service.run_watchdog` derives `max_attempts = len(backoff)` and `next_delay_s = backoff[0]` for the first `tunnel_degraded` emit (confirmed by the existing char-tests).
- Produces: backoff `(0.5, 2.0, 5.0, 10.0)`; first `tunnel_degraded` now carries `next_delay_s == 0.5`, `max_attempts == 4`.

- [ ] **Step 1: Update the backoff constant AND all three char-test files in one edit pass.**
  In `backend/api/device.py`, replace the constant definition and its comment:
  ```python
  # Restart backoff sequence (seconds). Four attempts: the first retry is
  # near-instant because most WiFi blips (a brief screen-lock pause, transient
  # packet loss) recover immediately — waiting a full 3s before the first retry
  # was a major contributor to the ~27s felt reconnect window. The later steps
  # (2s, 5s, 10s) cover deeper outages without sitting on a dead tunnel for an
  # unbounded time. Total worst-case wait ~17.5s before final teardown.
  _TUNNEL_RESTART_BACKOFF: tuple[float, ...] = (0.5, 2.0, 5.0, 10.0)
  ```
  ⚠️ For the `Edit`, the `old_string` MUST be the EXACT current block verbatim (do not paraphrase — an exact-string Edit fails otherwise). The current text in `device.py` is exactly:
  ```python
  # Restart backoff sequence (seconds). Three attempts cover most WiFi blips
  # (transient packet loss, brief screen-lock pause) without sitting on a dead
  # tunnel for an unbounded time. Total worst-case wait ~21s before final
  # teardown — within the user's tolerance for "auto-recovers" before they'd
  # look at the UI and notice.
  _TUNNEL_RESTART_BACKOFF: tuple[float, ...] = (3.0, 6.0, 12.0)
  ```
  (Note the curly quotes `"auto-recovers"` and the `~21s` line — copy them exactly.)

  In `backend/tests/test_watchdog_tunnel_lost_reason_char.py`, change the first deep-equal (lines 62–69) `max_attempts`/`next_delay_s`:
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": DeviceLostError.REASON_TUNNEL_DEAD,
          "last_error": "helper reports tunnel for X is gone",
          "attempt": 1,
          "max_attempts": 4,
          "next_delay_s": 0.5,
      }
  ```
  and the clean-exit deep-equal (lines 105–111):
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": "task_exited",
          "attempt": 1,
          "max_attempts": 4,
          "next_delay_s": 0.5,
      }
  ```
  (The two `tunnel_lost` assertions in this file stay unchanged — they have no attempt/delay keys.)

  In `backend/tests/test_wifi_tunnel_service_watchdog_char.py`, change `_make_service` (line 38):
  ```python
          restart_backoff=(0.5, 2.0, 5.0, 10.0),
  ```
  the first deep-equal (lines 59–66):
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": DeviceLostError.REASON_TUNNEL_DEAD,
          "last_error": "helper reports tunnel for X is gone",
          "attempt": 1,
          "max_attempts": 4,
          "next_delay_s": 0.5,
      }
  ```
  and the clean-exit deep-equal (lines 86–92):
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": "task_exited",
          "attempt": 1,
          "max_attempts": 4,
          "next_delay_s": 0.5,
      }
  ```
  (Both `tunnel_lost` assertions unchanged.)

  In `backend/tests/test_wifi_tunnel_degraded_attempt_char.py`, change the two `restart_backoff=(3.0, 6.0, 12.0)` literals (lines 60 and 84) to `restart_backoff=(0.5, 2.0, 5.0, 10.0)`, the first deep-equal (lines 63–70):
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": DeviceLostError.REASON_TUNNEL_DEAD,
          "last_error": "helper reports tunnel for X is gone",
          "attempt": 1,
          "max_attempts": 4,
          "next_delay_s": 0.5,
      }
  ```
  and the clean-exit deep-equal (lines 87–93):
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": "task_exited",
          "attempt": 1,
          "max_attempts": 4,
          "next_delay_s": 0.5,
      }
  ```
  LEAVE the third test in this file (`test_tunnel_degraded_empty_backoff_omits_attempt_keys`, lines 96–110) UNCHANGED — it passes `restart_backoff=()` and asserts the no-attempt-keys shape, which is independent of the tuple value.

- [ ] **Step 2: Run the three char-test files — see them pass with the new values.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_watchdog_tunnel_lost_reason_char.py tests/test_wifi_tunnel_service_watchdog_char.py tests/test_wifi_tunnel_degraded_attempt_char.py -q
  ```
  Expected: all tests pass (8 passed). Because the constant and the assertions moved together, this is green in a single edit — there is no intermediate red state.

- [ ] **Step 3: Add a focused assertion that the first emit carries `next_delay_s == 0.5` and `max_attempts == 4`.**
  Append a new test to `backend/tests/test_wifi_tunnel_degraded_attempt_char.py` (it already imports `asyncio`, `AsyncMock`, `MagicMock`, `pytest`, `DeviceLostError`, `WifiTunnelService`, and defines `_CapPublisher` + `_make_service`):
  ```python


  async def test_first_degraded_emit_uses_new_fast_backoff():
      """Regression-lock the Win-4 cadence: with the production backoff
      (0.5, 2.0, 5.0, 10.0) the FIRST tunnel_degraded emit advertises a
      near-instant first retry (0.5s) and 4 total attempts."""
      udid = "UDID-DEG-FAST"

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
      svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=(0.5, 2.0, 5.0, 10.0))
      await svc.run_watchdog(udid, runner)
      by_type = {e: d for e, d in pub.events}
      assert by_type["tunnel_degraded"]["next_delay_s"] == 0.5
      assert by_type["tunnel_degraded"]["max_attempts"] == 4
  ```

- [ ] **Step 4: Run the focused test — see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_degraded_attempt_char.py -q
  ```
  Expected: all pass (4 passed — the 3 originals + the new one).

- [ ] **Step 5: Run the full backend suite + import-linter — confirm green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3 && .venv/bin/python -m import_linter --config .importlinter 2>/dev/null | tail -1
  ```
  Expected: `~1036 passed` (baseline +1 new test), `0 failed`; `Contracts: 7 kept, 0 broken.`

- [ ] **Step 6: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/api/device.py backend/tests/test_watchdog_tunnel_lost_reason_char.py backend/tests/test_wifi_tunnel_service_watchdog_char.py backend/tests/test_wifi_tunnel_degraded_attempt_char.py && git commit -m "perf(tunnel): faster restart backoff (0.5,2,5,10) for near-instant first retry

First retry drops from 3.0s to 0.5s (most WiFi blips recover immediately),
4 attempts for resilience. Updates the three tunnel_degraded characterization
tests in the same commit: next_delay_s 3.0->0.5, max_attempts 3->4. The
tunnel_lost assertions and the empty-backoff omit-keys test are unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
  ```
  Expected: commit succeeds with the personal identity (no `-c user.email`).

---

### Task 2: Defer geo enrichment off the boot critical path (Win 1)

Keep the store LOAD pre-yield (bookmarks/routes must exist when the server starts). Defer ONLY `enrich_all()` (the geo-data load + per-bookmark `resolve()`) so the server serves immediately and enrichment completes concurrently. `enrich_all` is a sync method on `BookmarkManager` (`services/bookmarks.py:474`); it mutates the store under `_store_lock` and calls `self._save()` only if anything changed, which fires the watcher's `bookmarks_changed` broadcast so a late-arriving geo fill renders without a reload. Run it off-thread via `asyncio.to_thread` (it is blocking CPU/IO: numpy + timezonefinder + a 2.7MB JSON parse) inside a fire-and-forget task spawned BEFORE `yield`.

**Files:**
- `backend/main.py` — `AppState.load_state()` (lines 173–199, specifically the `self.bookmark_manager.enrich_all()` at line 184), and the `lifespan()` body (the `await app_state.load_state()` at line 914).

**Interfaces:**
- Consumes: `app_state.bookmark_manager` (a `BookmarkManager` after `make_bookmark_manager()`), its sync method `enrich_all() -> int`.
- Produces: `load_state()` no longer calls `enrich_all()` inline; lifespan spawns `asyncio.to_thread(app_state.bookmark_manager.enrich_all)` as a fire-and-forget task (error-logged, strong-ref held) before `yield`. A new module-level helper `_spawn_bg(coro)` on `main.py` mirrors `api/location.py:181`'s pattern.

- [ ] **Step 1: Write a characterization test that pins TODAY's behavior — `enrich_all` is invoked during startup and the store ends up enriched.**
  This test must pass against the CURRENT (pre-change) code so it characterizes existing behavior, then keep passing after the deferral. Create `backend/tests/test_lifespan_enrich_defer_char.py`. Mirror `test_lifespan.py`'s monkeypatch harness (darwin-forced helper stubs + device-discover stub):
  ```python
  """Characterization: lifespan startup runs bookmark geo-enrichment.

  Win 1 moves enrich_all() OFF the awaited critical path (spawned via
  asyncio.to_thread) but the end state is identical — enrich_all must still
  be invoked exactly once during startup, and the server must reach `yield`
  without awaiting it inline. We drive the REAL lifespan with the real
  app_state.bookmark_manager (a real BookmarkManager built by load_state),
  and spy on enrich_all via a call-counter wrapper installed AFTER load_state
  rebuilds the manager.
  """
  from __future__ import annotations

  import asyncio

  import pytest

  from main import lifespan, app_state, helper_client

  pytestmark = pytest.mark.asyncio


  async def test_lifespan_invokes_enrich_all_during_startup(monkeypatch):
      monkeypatch.setattr("sys.platform", "darwin")

      async def fake_connect(timeout=90.0):
          return None

      async def fake_migrate(home, uid, gid):
          return {"chowned": 0, "skipped": 0, "failed": 0}

      async def fake_shutdown():
          return {"ok": True}

      async def fake_close():
          return None

      monkeypatch.setattr(helper_client, "connect", fake_connect)
      monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)
      monkeypatch.setattr(helper_client, "shutdown", fake_shutdown)
      monkeypatch.setattr(helper_client, "close", fake_close)

      async def fake_discover():
          return []

      async def fake_disconnect_all():
          return None

      monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
      monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

      app_state.bookmark_manager = None
      app_state.route_manager = None

      calls = {"n": 0}
      real_to_thread = asyncio.to_thread

      # Spy: count enrich_all invocations regardless of whether it's called
      # inline (pre-change) or via asyncio.to_thread (post-change). We wrap
      # to_thread so a deferred enrich is still observed, and also patch the
      # bound method after load_state builds the manager. Since load_state
      # rebuilds bookmark_manager, install the spy by wrapping the class method.
      from services.bookmarks import BookmarkManager
      real_enrich = BookmarkManager.enrich_all

      def counting_enrich(self):
          calls["n"] += 1
          return real_enrich(self)

      monkeypatch.setattr(BookmarkManager, "enrich_all", counting_enrich)

      async with lifespan(None):
          # Inside the yield window the server is "serving". enrich_all may be
          # inline (pre-change) or spawned (post-change); allow the spawned
          # to_thread task a moment to run.
          for _ in range(50):
              if calls["n"] >= 1:
                  break
              await asyncio.sleep(0.01)
          assert calls["n"] >= 1, "enrich_all must run during startup"
          assert app_state.bookmark_manager is not None
  ```

- [ ] **Step 2: Run the new char-test against the CURRENT code — see it pass (characterizes existing behavior).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_enrich_defer_char.py -q
  ```
  Expected: 1 passed (enrich_all is currently called inline by `load_state`).

- [ ] **Step 3: Write the failing assertion that enrich is DEFERRED (not awaited inline).**
  Append a second test to the SAME file. It asserts the new behavior: `load_state()` itself must NOT call `enrich_all` (so a fresh `load_state` leaves the store un-enriched until the spawned task runs). This will FAIL now (load_state calls it inline) and pass after the change.
  ```python


  async def test_load_state_does_not_enrich_inline(monkeypatch):
      """Win 1 invariant: load_state() builds the manager but does NOT call
      enrich_all inline — enrichment is spawned by the lifespan instead. Calling
      load_state() directly (outside lifespan) therefore leaves enrich_all
      un-invoked."""
      from services.bookmarks import BookmarkManager

      calls = {"n": 0}
      real_enrich = BookmarkManager.enrich_all

      def counting_enrich(self):
          calls["n"] += 1
          return real_enrich(self)

      monkeypatch.setattr(BookmarkManager, "enrich_all", counting_enrich)

      app_state.bookmark_manager = None
      app_state.route_manager = None
      await app_state.load_state()

      assert calls["n"] == 0, "load_state must NOT call enrich_all inline (Win 1: deferred)"
      assert app_state.bookmark_manager is not None, "store load stays pre-yield"
  ```

- [ ] **Step 4: Run the new test — see it FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_enrich_defer_char.py::test_load_state_does_not_enrich_inline -q
  ```
  Expected: 1 failed — `assert 1 == 0` (load_state still calls enrich_all inline).

- [ ] **Step 5: Implement — remove the inline enrich from `load_state`; add a `_spawn_bg` helper; spawn the deferred enrich in the lifespan.**
  In `backend/main.py`, in `load_state()`, remove the inline call (lines 181–184). Replace:
  ```python
          self.bookmark_manager = make_bookmark_manager()
          # Reconciliation sweep: backfill country / timezone / city / region
          # on any bookmark (legacy, imported, offline-added) still missing
          # them. Offline + idempotent — a no-op once everything is filled.
          self.bookmark_manager.enrich_all()
          self.route_manager = make_route_manager()
  ```
  with:
  ```python
          self.bookmark_manager = make_bookmark_manager()
          # NOTE: the geo-enrichment reconciliation sweep (enrich_all) is NO
          # LONGER run here. The first resolve() inside enrich_all loads numpy +
          # timezonefinder + a 2.7MB cities5000.json (~530ms) — far too heavy to
          # sit on the awaited boot critical path. It is spawned off-thread by
          # the lifespan (see _spawn_bg(asyncio.to_thread(...enrich_all))) so the
          # server serves immediately and enrichment completes concurrently.
          # Safe: enrich_all mutates the store under _store_lock and is
          # idempotent; its _save() fires the bookmarks_changed broadcast so a
          # late geo fill renders without a reload.
          self.route_manager = make_route_manager()
  ```
  Then add a module-level fire-and-forget helper. Place it just above the `@asynccontextmanager`/`async def lifespan(application: FastAPI):` definition (i.e. immediately before line 837 `@asynccontextmanager`):
  ```python
  # Strong references to fire-and-forget startup tasks. asyncio only keeps weak
  # refs, so without this set Python can GC a task mid-flight (documented
  # footgun). Tasks self-remove on completion; exceptions are logged + swallowed
  # so a deferred-startup failure never takes the server down. Mirrors
  # api/location.py:_spawn / _bg_tasks.
  _startup_bg_tasks: set = set()


  def _spawn_bg(coro):
      task = asyncio.create_task(coro)
      _startup_bg_tasks.add(task)

      def _on_done(t):
          _startup_bg_tasks.discard(t)
          exc = t.exception()
          if exc is not None:
              logger.exception("startup background task crashed: %s", exc, exc_info=exc)

      task.add_done_callback(_on_done)
      return task
  ```
  Then in `lifespan()`, immediately AFTER `await app_state.load_state()` (line 914) and BEFORE the `# ── Startup ──` discover block (line 916), spawn the deferred enrich:
  ```python
      await app_state.load_state()

      # ── Deferred geo enrichment (Win 1) ──
      # Run the reconciliation sweep off the awaited critical path so uvicorn
      # serves immediately. enrich_all is blocking (numpy + timezonefinder +
      # 2.7MB JSON), so push it to a thread; the spawned task error-logs and
      # discards on its own (_spawn_bg). The store itself is already loaded
      # (above) so bookmarks/routes exist the instant the server is up — only
      # the offline geo fields fill in a beat later, broadcast via the watcher's
      # bookmarks_changed event.
      if app_state.bookmark_manager is not None:
          _spawn_bg(asyncio.to_thread(app_state.bookmark_manager.enrich_all))
  ```

- [ ] **Step 6: Run the enrich char-tests — see both pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_enrich_defer_char.py -q
  ```
  Expected: 2 passed — `test_lifespan_invokes_enrich_all_during_startup` (the spawned task runs enrich during the yield window) and `test_load_state_does_not_enrich_inline`.

- [ ] **Step 7: Run the full backend suite + import-linter — confirm green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3 && .venv/bin/python -m import_linter --config .importlinter 2>/dev/null | tail -1
  ```
  Expected: `~1038 passed` (baseline + Task 1's +1 + Task 2's +2), `0 failed`; `Contracts: 7 kept, 0 broken.`

- [ ] **Step 8: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/main.py backend/tests/test_lifespan_enrich_defer_char.py && git commit -m "perf(boot): defer geo enrich_all off the lifespan critical path

The store LOAD stays pre-yield (bookmarks/routes exist when the server
starts), but enrich_all (numpy + timezonefinder + 2.7MB cities5000.json,
~530ms) is spawned off-thread via asyncio.to_thread so uvicorn serves
immediately. enrich_all is idempotent and mutates under _store_lock; its
_save() fires bookmarks_changed so late geo fills render without a reload.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
  ```

---

### Task 3: Defer device auto-connect off pre-yield (Win 2)

Spawn the SAME `discover → connect → create_engine_for_device` logic as a fire-and-forget task (reuse the `_spawn_bg` helper added in Task 2) so the server serves immediately; the connect runs concurrently. Behavior is identical — the device still ends up connected — only the timing moves. A connect failure must NOT crash startup (the done-callback logs + discards).

**Files:**
- `backend/main.py` — the `lifespan()` startup block (lines 916–929: `discover_devices → connect → create_engine_for_device`, currently awaited before `yield` at line 960).

**Interfaces:**
- Consumes: `app_state.device_manager.discover_devices()`, `.connect(udid)`, `app_state.create_engine_for_device(udid)` (all async). The `_spawn_bg` helper from Task 2.
- Produces: a module-level `async def _startup_autoconnect()` coroutine holding the existing discover→connect→engine logic (with its existing try/except logging), spawned via `_spawn_bg(_startup_autoconnect())` instead of awaited inline.

- [ ] **Step 1: Write a characterization test pinning that the device connects during startup — but spawned, not awaited.**
  Create `backend/tests/test_lifespan_autoconnect_defer_char.py`. Mirror `test_lifespan.py`. The key assertion: when `discover_devices` returns a device, `connect` + `create_engine_for_device` are both eventually called during the yield window — AND a fake `connect` that BLOCKS does NOT delay reaching `yield` (proving it's spawned). Use a real-collaborator harness with fakes capturing the calls:
  ```python
  """Characterization: lifespan startup auto-connects the first discovered
  device. Win 2 moves the discover->connect->create_engine block OFF the
  awaited critical path (fire-and-forget _spawn_bg task) — the device still
  ends up connected, only the timing moves. We assert (a) the block is SPAWNED
  not awaited: a connect that blocks does not delay reaching `yield`; (b) the
  device still connects (connect + create_engine_for_device are invoked); and
  (c) a connect failure does not crash startup.
  """
  from __future__ import annotations

  import asyncio

  import pytest

  from main import lifespan, app_state, helper_client

  pytestmark = pytest.mark.asyncio


  def _stub_helper(monkeypatch):
      monkeypatch.setattr("sys.platform", "darwin")

      async def fake_connect(timeout=90.0):
          return None

      async def fake_migrate(home, uid, gid):
          return {"chowned": 0, "skipped": 0, "failed": 0}

      async def fake_shutdown():
          return {"ok": True}

      async def fake_close():
          return None

      monkeypatch.setattr(helper_client, "connect", fake_connect)
      monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)
      monkeypatch.setattr(helper_client, "shutdown", fake_shutdown)
      monkeypatch.setattr(helper_client, "close", fake_close)

      async def fake_disconnect_all():
          return None

      monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)


  class _Dev:
      def __init__(self, udid, name):
          self.udid = udid
          self.name = name


  async def test_autoconnect_is_spawned_not_awaited(monkeypatch):
      _stub_helper(monkeypatch)
      app_state.bookmark_manager = None
      app_state.route_manager = None

      connect_started = asyncio.Event()
      connect_release = asyncio.Event()
      calls = {"connect": 0, "engine": 0}

      async def fake_discover():
          return [_Dev("UDID-AC", "iPhone")]

      async def fake_connect(udid):
          calls["connect"] += 1
          connect_started.set()
          # Block until the test releases — if the lifespan AWAITED this, we'd
          # never reach `yield`.
          await connect_release.wait()

      async def fake_create_engine(udid, force=False):
          calls["engine"] += 1

      monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
      monkeypatch.setattr(app_state.device_manager, "connect", fake_connect)
      monkeypatch.setattr(app_state, "create_engine_for_device", fake_create_engine)

      async with lifespan(None):
          # We reached `yield` even though fake_connect is still blocked ->
          # proves the block was spawned, not awaited.
          assert connect_started.is_set() or calls["connect"] == 0
          # Let the spawned connect proceed and finish.
          connect_release.set()
          for _ in range(50):
              if calls["engine"] >= 1:
                  break
              await asyncio.sleep(0.01)
          assert calls["connect"] == 1, "device must still connect during startup"
          assert calls["engine"] == 1, "engine must still be created for the device"


  async def test_autoconnect_failure_does_not_crash_startup(monkeypatch):
      _stub_helper(monkeypatch)
      app_state.bookmark_manager = None
      app_state.route_manager = None

      async def fake_discover():
          return [_Dev("UDID-FAIL", "iPhone")]

      async def fake_connect(udid):
          raise RuntimeError("trust dialog cancelled")

      async def fake_create_engine(udid, force=False):
          raise AssertionError("create_engine must not run after a failed connect")

      monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
      monkeypatch.setattr(app_state.device_manager, "connect", fake_connect)
      monkeypatch.setattr(app_state, "create_engine_for_device", fake_create_engine)

      # Must NOT raise — the spawned task's done-callback logs + discards.
      async with lifespan(None):
          await asyncio.sleep(0.05)
          assert app_state.bookmark_manager is not None
  ```

- [ ] **Step 2: Run the new char-tests against the CURRENT code — observe the spawn-test FAIL (and the failure-test may also fail/hang).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_autoconnect_defer_char.py -q --timeout=30
  ```
  Expected: `test_autoconnect_is_spawned_not_awaited` FAILS or TIMES OUT — the current lifespan AWAITS `connect`, so `connect_release` is never set before `yield` and the test cannot reach the body. (If `--timeout` is unavailable, the test will hang; install/skip is unnecessary — the next step makes it pass.) This confirms the test discriminates the awaited-vs-spawned behavior.

- [ ] **Step 3: Implement — extract the discover→connect block into `_startup_autoconnect()` and spawn it.**
  In `backend/main.py`, replace the awaited startup block (lines 916–929):
  ```python
      # ── Startup ──
      logger.info("LocWarp starting — scanning for devices…")
      try:
          devices = await app_state.device_manager.discover_devices()
          if devices:
              target = devices[0]
              logger.info("Found device %s (%s), auto-connecting…", target.name, target.udid)
              await app_state.device_manager.connect(target.udid)
              await app_state.create_engine_for_device(target.udid)
              logger.info("Auto-connected to %s", target.udid)
          else:
              logger.info("No iOS devices found on startup")
      except Exception:
          logger.exception("Auto-connect on startup failed (device may need manual connect)")
  ```
  with a spawned call:
  ```python
      # ── Startup auto-connect (Win 2) ──
      # Discover + connect + create_engine moved OFF the awaited critical path:
      # a slow phone / Trust dialog / RSD tunnel handshake used to inject a
      # variable multi-second stall into cold-start before the window was
      # interactive. Now spawned fire-and-forget so the server serves
      # immediately; the device still ends up connected, only the timing moves.
      # A failure here logs (done-callback) and does NOT crash startup.
      logger.info("LocWarp starting — scanning for devices…")
      _spawn_bg(_startup_autoconnect())
  ```
  Then add the coroutine at module level, immediately AFTER the `_spawn_bg` helper added in Task 2 (i.e. just before `@asynccontextmanager`):
  ```python
  async def _startup_autoconnect() -> None:
      """Discover + auto-connect the first iOS device, off the boot critical
      path. Spawned by the lifespan via _spawn_bg (Win 2). Holds the exact
      logic that used to run awaited before `yield`; only the scheduling moved.
      A failure is logged here AND by the _spawn_bg done-callback — startup
      never crashes on a connect error."""
      try:
          devices = await app_state.device_manager.discover_devices()
          if devices:
              target = devices[0]
              logger.info("Found device %s (%s), auto-connecting…", target.name, target.udid)
              await app_state.device_manager.connect(target.udid)
              await app_state.create_engine_for_device(target.udid)
              logger.info("Auto-connected to %s", target.udid)
          else:
              logger.info("No iOS devices found on startup")
      except Exception:
          logger.exception("Auto-connect on startup failed (device may need manual connect)")
  ```

- [ ] **Step 4: Run the new char-tests — see both pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_autoconnect_defer_char.py -q --timeout=30
  ```
  Expected: 2 passed. `test_autoconnect_is_spawned_not_awaited` now reaches the yield body even while `fake_connect` blocks; `test_autoconnect_failure_does_not_crash_startup` does not raise.

- [ ] **Step 5: Re-run the existing lifespan test + the Task-2 enrich test — confirm no regression.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan.py tests/test_lifespan_enrich_defer_char.py tests/test_lifespan_autoconnect_defer_char.py -q --timeout=30
  ```
  Expected: all pass. Note `test_lifespan.py::test_lifespan_loads_state_after_helper_handshake` already stubs `discover_devices` to return `[]`, so the spawned autoconnect is a harmless no-op there.

- [ ] **Step 6: Run the full backend suite + import-linter — confirm green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3 && .venv/bin/python -m import_linter --config .importlinter 2>/dev/null | tail -1
  ```
  Expected: `~1040 passed` (baseline + Task1 +1 + Task2 +2 + Task3 +2), `0 failed`; `Contracts: 7 kept, 0 broken.`

- [ ] **Step 7: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/main.py backend/tests/test_lifespan_autoconnect_defer_char.py && git commit -m "perf(boot): defer device auto-connect off the lifespan critical path

discover -> connect -> create_engine_for_device moves into a fire-and-forget
_startup_autoconnect() spawned via _spawn_bg, so a slow phone / Trust dialog /
RSD handshake no longer stalls cold-start before the window is interactive.
The device still ends up connected — only the timing moves. A connect failure
logs and is discarded; it never crashes startup.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
  ```

---

### Task 4: WiFi auto-connect fires saved candidates immediately (Win 3)

Today the deferred async body `await`s `wifiTunnelDiscover()` (the full ~3s mDNS browse) BEFORE firing the `savedips` candidates. Fire `savedips` IMMEDIATELY; run `wifiTunnelDiscover()` concurrently (`Promise.allSettled`) and use its result only to ADD un-saved devices. The `connectedDevicesRef` thrash-guard (line 110) MUST still run BEFORE any fire — a device already connected (USB or WiFi) must NOT get a spurious WiFi-tunnel fire.

**Files:**
- `frontend/src/hooks/useWifiAutoConnect.ts` — the deferred async body (lines 103–172): keep the guard at line 110, reorder the discover (line 137) vs the savedips fire (lines 152–154).
- `frontend/src/hooks/useWifiAutoConnect.test.tsx` — add the new ordering + concurrency tests (Vitest, fireEvent/fake-timers only; `@testing-library/user-event` is NOT installed).

**Interfaces:**
- Consumes: `api.wifiTunnelStatus()`, `api.wifiTunnelDiscover()`, `device.startWifiTunnel(ip, port, udid)`, `connectedDevicesRef.current`. Unchanged signatures.
- Produces: `startWifiTunnel` for the `savedips` candidates is invoked WITHOUT awaiting `wifiTunnelDiscover()` first; discover runs concurrently and any discover-only (un-saved) device is fired too. The already-connected guard and the dedupe/cap-at-3 and onError semantics are unchanged.

- [ ] **Step 1: Write the failing test — savedips fires WITHOUT waiting for a slow discover.**
  Add to `useWifiAutoConnect.test.tsx` inside the `describe` block. This test makes `wifiTunnelDiscover` hang (never resolves) and asserts the savedips candidate still fires:
  ```tsx
    it('fires the savedips candidate immediately even when discover never resolves', async () => {
      localStorage.setItem(
        'locwarp.tunnel.savedips',
        JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
      )
      const { api, stub } = makeApi()
      // Discover hangs forever — the savedips fire must NOT wait on it.
      stub.wifiTunnelDiscover.mockImplementation(() => new Promise(() => {}))
      const { device, startWifiTunnel } = makeDevice()

      renderHook(() => useWifiAutoConnect(true, api, device))
      await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

      // savedips candidate fired despite discover being pending.
      expect(startWifiTunnel).toHaveBeenCalledTimes(1)
      expect(startWifiTunnel.mock.calls[0][0]).toBe('10.0.0.1')
      expect(startWifiTunnel.mock.calls[0][2]).toBe('a')
    })
  ```

- [ ] **Step 2: Write the failing test — a discover-only (un-saved) device is still added concurrently.**
  Add another test:
  ```tsx
    it('adds a discover-only device that is not in savedips (concurrent discover)', async () => {
      localStorage.setItem(
        'locwarp.tunnel.savedips',
        JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
      )
      const { api, stub } = makeApi()
      // Discover surfaces a second, un-saved iPhone.
      stub.wifiTunnelDiscover.mockResolvedValue({ devices: [{ ip: '10.0.0.9', port: 49152 }] })
      const { device, startWifiTunnel } = makeDevice()

      renderHook(() => useWifiAutoConnect(true, api, device))
      await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

      const ipsTried = startWifiTunnel.mock.calls.map((c) => c[0])
      expect(new Set(ipsTried)).toEqual(new Set(['10.0.0.1', '10.0.0.9']))
    })
  ```

- [ ] **Step 3: Write the regression-lock test — the no-thrash guard still suppresses a fire when a device is already connected.**
  Add another test (mirrors the existing "skips when a USB device surfaces AFTER" test but pins it survives the reorder):
  ```tsx
    it('no-thrash guard: an already-connected device suppresses the savedips fire even after the reorder', async () => {
      localStorage.setItem(
        'locwarp.tunnel.savedips',
        JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
      )
      const { api } = makeApi()
      const startWifiTunnel = vi.fn(async () => ({
        udid: 'u', name: 'n', ios_version: '17', connection_type: 'Network', is_connected: true,
      })) as unknown as WifiAutoConnectDevice['startWifiTunnel']
      const deviceEmpty: WifiAutoConnectDevice = { connectedDevices: [], startWifiTunnel }
      const usb = { udid: 'x', name: 'n', ios_version: '17', connection_type: 'USB', is_connected: true }
      const deviceConnected: WifiAutoConnectDevice = { connectedDevices: [usb], startWifiTunnel }

      const { rerender } = renderHook(({ d }) => useWifiAutoConnect(true, api, d), {
        initialProps: { d: deviceEmpty },
      })
      // USB device surfaces on a later render (new object) — guard reads the ref.
      rerender({ d: deviceConnected })
      await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

      // Even with savedips firing "immediately", the already-connected guard
      // (read from connectedDevicesRef) runs FIRST and suppresses any fire.
      expect(startWifiTunnel).not.toHaveBeenCalled()
    })
  ```

- [ ] **Step 4: Run the three new tests — see them behave per current code.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useWifiAutoConnect.test.tsx -t "fires the savedips candidate immediately even when discover never resolves"
  ```
  Expected: FAIL — the current code `await`s the hanging `wifiTunnelDiscover()` before the savedips fire, so `startWifiTunnel` is never called and the assertion `toHaveBeenCalledTimes(1)` fails (the test times out inside `advanceTimersByTimeAsync` or asserts 0 calls). The discover-only test (Step 2) passes today (discover resolves), and the no-thrash test (Step 3) passes today (guard already runs first) — those two are regression-locks. Run the full file to confirm only the ordering test is red:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useWifiAutoConnect.test.tsx 2>&1 | tail -8
  ```
  Expected: 1 failed (the new ordering test), the rest pass.

- [ ] **Step 5: Implement the reorder.**
  In `frontend/src/hooks/useWifiAutoConnect.ts`, replace the candidate-assembly block (lines 124–145, from `const seen = new Set<string>()` through `if (limited.length === 0) return`). Keep the guard at line 110 and the `alreadyTunneled` set (lines 111–115) exactly as-is — they still run first. Replace:
  ```typescript
          const seen = new Set<string>()
          const uniq: Array<{ ip: string; port: number; udid?: string }> = []
          const addCand = (ip: string, port: number, udid?: string) => {
            const key = `${ip}:${port}`
            if (seen.has(key)) return
            if (alreadyTunneled.has(key)) return
            seen.add(key)
            uniq.push({ ip, port, udid })
          }
          for (const entry of savedList) addCand(entry.ip, entry.port, entry.udid)
          // Discover is best-effort and runs in parallel; failures don't
          // block the savedips path.
          try {
            const dres = await api.wifiTunnelDiscover()
            for (const d of (dres?.devices || [])) {
              addCand(String(d.ip), Number(d.port) || 49152)
            }
          } catch { /* discover failed — savedips entries still try */ }
          // Cap at MAX_DEVICES the backend enforces — anything beyond
          // would 409 anyway.
          const limited = uniq.slice(0, 3)
          if (limited.length === 0) return
  ```
  with the reordered version that fires savedips immediately and folds discover concurrently:
  ```typescript
          const seen = new Set<string>()
          const fired = new Set<string>()
          const attempts: Array<Promise<unknown>> = []
          const fire = (ip: string, port: number, udid?: string) => {
            const key = `${ip}:${port}`
            if (seen.has(key)) return
            if (alreadyTunneled.has(key)) return
            // Cap at the MAX_DEVICES the backend enforces — anything beyond
            // would 409 anyway. Count only what we've actually fired.
            if (fired.size >= 3) return
            seen.add(key)
            fired.add(key)
            attempts.push(device.startWifiTunnel(ip, port, udid))
          }
          // (Win 3) Fire the savedips candidates IMMEDIATELY — they already
          // hold exact {ip, port, udid} for known phones, so there's no reason
          // to wait the full ~3s mDNS browse before connecting them. A
          // single-phone user's auto-connect now starts ~3s earlier per launch.
          // The already-connected guard above (connectedDevicesRef) has already
          // run, so this never fires a spurious tunnel over a healthy USB/WiFi
          // connection — the thrash fix (memory: wifi_autoconnect_tunnel_thrash)
          // is preserved.
          for (const entry of savedList) fire(entry.ip, entry.port, entry.udid)
          // Discover runs CONCURRENTLY (best-effort) and only ADDS devices not
          // already in savedips — e.g. a second iPhone connected via the
          // auto-connect path itself that never went through the manual save.
          // Its failure must not block (or surface a toast for) the savedips
          // path, so we allSettle it alongside the saved attempts.
          attempts.push(
            (async () => {
              try {
                const dres = await api.wifiTunnelDiscover()
                for (const d of (dres?.devices || [])) {
                  fire(String(d.ip), Number(d.port) || 49152)
                }
              } catch { /* discover failed — savedips entries still tried */ }
            })(),
          )
          if (attempts.length === 0) return
  ```
  Then replace the `Promise.allSettled` fan-out block (lines 146–162, from the `// Parallel:` comment through the `if (!anyOk) onErrorRef.current?.(...)`) — because we now collect `attempts` (each saved `startWifiTunnel` promise plus the one discover-driver promise) instead of building a `limited` array and mapping it. Replace:
  ```typescript
          // Parallel: every iPhone gets a tunnel attempt at the same
          // time so the user doesn't wait sequentially for unreachable
          // ones to time out (~10s each). Pass entry.udid so the backend
          // tries the right pair record FIRST — without the hint, the
          // second device's request can stall on the wrong candidate's
          // 8s handshake timeout and bail.
          const results = await Promise.allSettled(
            limited.map((entry) =>
              device.startWifiTunnel(entry.ip, entry.port, entry.udid),
            ),
          )
          // The WiFi panel does NOT surface auto-pass failures (its
          // tunnelError is manual-path only), so if EVERY candidate
          // rejected, fire the injected toast so the user isn't left
          // wondering why nothing connected.
          const anyOk = results.some((r) => r.status === 'fulfilled')
          if (!anyOk) onErrorRef.current?.('wifi.autoconnect_failed')
  ```
  with:
  ```typescript
          // Parallel: every iPhone gets its tunnel attempt at the same time
          // (savedips fired up-front, discover-found ones added as discover
          // resolves) so the user doesn't wait sequentially for unreachable
          // ones to time out (~10s each). The udid hint was passed into
          // startWifiTunnel so the backend tries the right pair record FIRST.
          // `attempts` is [...savedStartWifiTunnel promises, discoverDriver];
          // the discover driver resolves to undefined and can't be "rejected"
          // here (it swallows its own error), so it never miscounts as a
          // connect failure.
          const results = await Promise.allSettled(attempts)
          // The WiFi panel does NOT surface auto-pass failures (its tunnelError
          // is manual-path only). Only count the actual connect attempts (the
          // ones that fired a device); if EVERY fired candidate rejected, toast.
          // If nothing fired at all (no saved + no discovered), stay silent.
          const connectResults = results.slice(0, fired.size)
          const anyOk = connectResults.some((r) => r.status === 'fulfilled')
          if (connectResults.length > 0 && !anyOk) {
            onErrorRef.current?.('wifi.autoconnect_failed')
          }
  ```

- [ ] **Step 6: Run the full hook test file — see all pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useWifiAutoConnect.test.tsx 2>&1 | tail -8
  ```
  Expected: all pass (the original ≈10 tests + 3 new). Pay attention to the existing onError tests: "calls onError when every auto-connect attempt fails" (1 saved entry, startWifiTunnel rejects → `fired.size === 1`, `connectResults` all rejected → onError fires) and "does NOT call onError when the pre-flight wifiTunnelStatus throws" (status throws → outer catch, no fire, no toast). Both must stay green under the new counting.

- [ ] **Step 7: Run tsc + the full frontend suite + depcruise — confirm green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx vitest run 2>&1 | tail -4 && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: `TSC_OK`, vitest `~860 passed` (baseline +3), `0 errors, 0 warnings` from depcruise.

- [ ] **Step 8: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/hooks/useWifiAutoConnect.ts frontend/src/hooks/useWifiAutoConnect.test.tsx && git commit -m "perf(wifi): fire savedips auto-connect immediately, discover concurrently

savedips candidates (exact ip/port/udid for known phones) now fire without
waiting the full ~3s mDNS browse; wifiTunnelDiscover runs concurrently and only
ADDS un-saved devices. The connectedDevicesRef no-thrash guard still runs FIRST,
so a spurious WiFi tunnel never tears down a healthy USB tunnel
(wifi_autoconnect_tunnel_thrash preserved). onError still fires only when every
actually-fired connect attempt rejects.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
  ```

---

### Task 5: Whole-branch review + ff-merge to main

**Files:** none (integration).

**Interfaces:**
- Consumes: the four feature commits on `boot-reconnect-latency`.
- Produces: `main` advanced by ff-merge, all gates green.

- [ ] **Step 1: Run the COMPLETE gate set on the branch tip.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3 && .venv/bin/python -m import_linter --config .importlinter 2>/dev/null | tail -1
  ```
  Expected: `~1040 passed, 0 failed`; `Contracts: 7 kept, 0 broken.` Then:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx vitest run 2>&1 | tail -3 && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: `TSC_OK`, vitest `~860 passed`, depcruise `0 errors, 0 warnings`.

- [ ] **Step 2: Adversarial whole-branch review.**
  Dispatch a reviewer subagent (opus) to diff `main...boot-reconnect-latency` against the spec's four wins + Global Constraints. Specifically verify: (a) the store LOAD is still pre-yield in `load_state` (only `enrich_all` deferred); (b) `_startup_autoconnect` holds the EXACT pre-change logic; (c) the `connectedDevicesRef` guard still runs before any savedips fire; (d) Task 1's backoff change and its three char-test updates are in ONE commit; (e) no new HTTP/WS/IPC surface. Address any finding, re-running the affected gate.

- [ ] **Step 3: ff-merge to main.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git checkout main && git merge --ff-only boot-reconnect-latency && git log --oneline -5
  ```
  Expected: fast-forward; the four feature commits on top of the prior `main` tip.

- [ ] **Step 4: Final post-merge gate sanity.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -2
  ```
  Expected: `~1040 passed, 0 failed`.
