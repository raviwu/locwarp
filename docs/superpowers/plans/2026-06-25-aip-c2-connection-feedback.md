# Connection Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan — one implementer subagent per task, one adversarial reviewer per task, and a whole-branch review at the end. Steps use checkbox (- [ ]) syntax.

**Goal:** Make every connection state legible. (1) The "reconnecting…" banner shows the attempt number + a live retry countdown by enriching the existing `tunnel_degraded` WS payload with `{attempt, max_attempts, next_delay_s}`. (2) The `tunnel_lost` banner gains a one-click Reconnect that re-fires `startWifiTunnel` from the per-device `savedips` entry. (3) A new `connect_progress` WS event streams coarse connect phases (`opening_tunnel → rsd_attempt → checking_ddi → opening_dvt → connected`) rendered in the `DeviceStatus` spinner region so a 15s connect is distinguishable from a hang.

**Architecture:** Fits the existing Pragmatic-Hexagonal-lite rings. Backend: a new pure pydantic event model in `domain/events.py`; emit points in `services/wifi_tunnel_service.py` (enriched `tunnel_degraded`) and `core/device_manager.py` (the RSD-retry loop in `connect_wifi_tunnel`, plus the DDI/DVT phases in `_ensure_personalized_ddi_mounted` / `_create_dvt_location_service`); all emits route through the already-injected `EventPublisher` (`self._events`) — awaited in-line, order-preserving, NEVER under `device_manager._lock` while taking the WS connection-manager lock. Frontend: add the `connect_progress` literal to the typed WS vocabulary FIRST (so `tsc` stays green), then a no-op subscriber, then render. View → hooks → ports ← adapters preserved; `DeviceStatus` consumes new props sourced from a hook.

**Tech stack:** FastAPI/Python backend, React 18 + TypeScript + Electron frontend, Vitest + pytest, import-linter + dependency-cruiser CI gates.

## Global Constraints

Copied verbatim from the master spec; every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` + frontend `vitest` + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit. Pin the exact baselines before starting:
  - Backend: `cd backend && .venv/bin/python -m pytest --collect-only -q` (expected ≈949 collected).
  - Frontend: `cd frontend && npx vitest run` (expected ≈773) + `npx tsc --noEmit` (0 errors) + `npm run depcruise` (= `depcruise src --config .dependency-cruiser.cjs`, expect 0/0).
- **Danger-zone-test-first.** `simulation_engine.py`, all movers, `api/location.py`, `device_manager` recovery, `phone_control.py` have NO direct tests. Write characterization tests (injected `ClockPort` + stepped `asyncio.sleep`, ordered exact-tuple assertions, REAL collaborators — never stub the method under test) BEFORE touching them.
- **WS payload discipline.** New/changed WS payloads are compared deep-equal JSON, serialized `exclude_unset`/`exclude_none` so absent keys stay absent. Adding keys to an existing event must be backward-compatible (existing consumers must not break).
- **One documented behavior change.** Speed jitter (Cluster 3) changes the per-tick speed of all existing modes. It is gated behind a settings toggle that defaults ON. This is the ONLY intentional behavior change in the program; characterization tests run with jitter OFF to keep exact-tuple assertions stable.
- **Hexagon boundaries hold.** `domain/` stays pure; `services/` raise domain errors not `HTTPException`; view never imports `adapters/api` / `services/api` directly; the `device_manager → EventPublisher` inversion stays **awaited, in-line, order-preserving** — NEVER acquire the WS connection-manager lock while `device_manager._lock` is held.
- **Survey before adding surface.** Each new endpoint/event below states reuse-vs-new with its justification (done in this spec).
- **Personal-repo conventions.** Direct commits to `main`; git identity auto-set by includeIf (never pass `-c user.email=`); no PR ceremony.

---

### Task 0: Pin baselines (no code change)

**Files:** none (verification only).

**Interfaces:**
- Consumes: nothing.
- Produces: the recorded green baselines used to verify every later task. Backend pytest collected count = `949` (already confirmed). Frontend vitest count ≈ `773`.

- [ ] **Step 1: Record the backend pytest baseline.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1
  ```
  Expected output ends with: `949 tests collected in <…>s`. Record `949` as the collected baseline.

- [ ] **Step 2: Record the frontend green baseline.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run 2>&1 | tail -5
  ```
  Expected: a `Test Files  N passed` / `Tests  ≈773 passed` summary with 0 failures. Then run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -3
  ```
  Expected: `TSC_OK` printed and a depcruise summary with `no dependency violations found` (0 errors, 0 warnings). If the exact depcruise command differs, discover it with `cat package.json | grep -i depcruise`.

- [ ] **Step 3: Confirm the import-linter contracts are green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_import_linter.py -q 2>&1 | tail -3
  ```
  Expected: the import-linter test passes (the contracts assert `7 kept, 0 broken`). No commit in this task.

---

### Task 1: Enrich the `tunnel_degraded` WS payload with `{attempt, max_attempts, next_delay_s}` (backend)

**Why this is first:** It is a self-contained, backward-compatible additive change to an existing event with an existing char-test harness — no new event type, so no frontend compile-gate dependency. The frontend can keep ignoring the new keys; this commit is green on its own.

**Files:**
- Create test: `/Users/raviwu/personal/locwarp/backend/tests/test_wifi_tunnel_degraded_attempt_char.py`
- Modify: `/Users/raviwu/personal/locwarp/backend/services/wifi_tunnel_service.py` — the single `tunnel_degraded` emit at lines 160-163 inside `WifiTunnelService.run_watchdog`.

**Interfaces:**
- Consumes: `WifiTunnelService(tunnels, tunnels_lock, tunnel_watchdogs, engines_for, attempt_restart, cleanup_wifi, publish, logger, sim_state_disconnected, restart_backoff)` — existing constructor (`wifi_tunnel_service.py:106-118`). `restart_backoff` is a tuple of float seconds (production default `(3.0, 6.0, 12.0)` — see `test_wifi_tunnel_service_watchdog_char.py:38`). `publish` is an async callable taking a `(event_type: str, data: dict)` tuple.
- Produces: an enriched `tunnel_degraded` payload. NEW shape (deep-equal):
  ```
  ("tunnel_degraded", {"udid": <udid>, "reason": <reason>, [optional "last_error": <str>],
                       "attempt": 1, "max_attempts": len(restart_backoff), "next_delay_s": restart_backoff[0]})
  ```
  When `restart_backoff` is empty, `attempt`/`max_attempts`/`next_delay_s` are omitted (the watchdog has nothing to retry). `attempt` is always `1` here because this event fires once, BEFORE the retry loop begins — it announces the FIRST upcoming retry. `next_delay_s` is the first backoff delay (the seconds until attempt 1 actually fires).

- [ ] **Step 1: Write the failing characterization test.**
  Create `/Users/raviwu/personal/locwarp/backend/tests/test_wifi_tunnel_degraded_attempt_char.py` with the COMPLETE content:
  ```python
  """Characterization: WifiTunnelService.run_watchdog enriches tunnel_degraded
  with {attempt, max_attempts, next_delay_s} so the UI can show "attempt 1/3,
  retrying in 3s". Backward-compatible additive keys; reason/last_error keep
  their existing shape. Real task; no stubbing of the method under test. The
  no-target path (target_ip/port None) skips the restart loop, so we exercise
  only the single degraded emit here.
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


  def _make_service(*, tunnels, publish, restart_backoff):
      return WifiTunnelService(
          tunnels=tunnels,
          tunnels_lock=asyncio.Lock(),
          tunnel_watchdogs={},
          engines_for=lambda udid: None,
          attempt_restart=AsyncMock(return_value=False),
          cleanup_wifi=AsyncMock(return_value=True),
          publish=publish,
          logger=MagicMock(),
          sim_state_disconnected=None,
          restart_backoff=restart_backoff,
      )


  async def test_tunnel_degraded_carries_attempt_max_and_next_delay():
      udid = "UDID-DEG-ATTEMPT"

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
      svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=(3.0, 6.0, 12.0))
      await svc.run_watchdog(udid, runner)
      by_type = {e: d for e, d in pub.events}
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": DeviceLostError.REASON_TUNNEL_DEAD,
          "last_error": "helper reports tunnel for X is gone",
          "attempt": 1,
          "max_attempts": 3,
          "next_delay_s": 3.0,
      }


  async def test_tunnel_degraded_clean_exit_still_carries_attempt_keys():
      udid = "UDID-DEG-CLEAN"

      async def _clean_task():
          return

      runner = MagicMock()
      runner.task = asyncio.create_task(_clean_task())
      runner.target_ip = None
      runner.target_port = None
      pub = _CapPublisher()
      svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=(3.0, 6.0, 12.0))
      await svc.run_watchdog(udid, runner)
      by_type = {e: d for e, d in pub.events}
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": "task_exited",
          "attempt": 1,
          "max_attempts": 3,
          "next_delay_s": 3.0,
      }


  async def test_tunnel_degraded_empty_backoff_omits_attempt_keys():
      udid = "UDID-DEG-EMPTY"

      async def _clean_task():
          return

      runner = MagicMock()
      runner.task = asyncio.create_task(_clean_task())
      runner.target_ip = None
      runner.target_port = None
      pub = _CapPublisher()
      svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=())
      await svc.run_watchdog(udid, runner)
      by_type = {e: d for e, d in pub.events}
      assert by_type["tunnel_degraded"] == {"udid": udid, "reason": "task_exited"}
  ```

- [ ] **Step 2: Run the new test and watch it FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_degraded_attempt_char.py -q 2>&1 | tail -15
  ```
  Expected: the first two tests FAIL with an `AssertionError` showing the emitted dict lacks `attempt`/`max_attempts`/`next_delay_s`. The third (empty-backoff) test PASSES already (current code emits no attempt keys). Confirm the failure is the missing-keys assertion, not an import/collection error.

- [ ] **Step 3: Enrich the emit (minimal implementation).**
  In `/Users/raviwu/personal/locwarp/backend/services/wifi_tunnel_service.py`, replace this block (currently lines 160-163):
  ```python
            try:
                await self._publish(("tunnel_degraded", {"udid": udid, **_reason_payload}))
            except Exception:
                self._logger.exception("Failed to emit tunnel_degraded event")
  ```
  with:
  ```python
            _degraded_payload: dict = {"udid": udid, **_reason_payload}
            if self._restart_backoff:
                # Announce the first upcoming retry so the UI can render
                # "attempt 1/N, retrying in <next_delay_s>s" + a live countdown.
                # This event fires ONCE, before the retry loop; attempt is the
                # first attempt and next_delay_s is the seconds until it runs.
                _degraded_payload["attempt"] = 1
                _degraded_payload["max_attempts"] = len(self._restart_backoff)
                _degraded_payload["next_delay_s"] = self._restart_backoff[0]
            try:
                await self._publish(("tunnel_degraded", _degraded_payload))
            except Exception:
                self._logger.exception("Failed to emit tunnel_degraded event")
  ```

- [ ] **Step 4: Run the new test and watch it PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_wifi_tunnel_degraded_attempt_char.py -q 2>&1 | tail -5
  ```
  Expected: `3 passed`.

- [ ] **Step 5: Run the full backend suite + import-linter.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -5
  ```
  Expected: all pass; collected count is now `952` (949 baseline + 3 new tests). No prior test regressed (the existing `test_wifi_tunnel_service_watchdog_char.py` uses the no-target path with `restart_backoff=(3.0, 6.0, 12.0)` and asserts `tunnel_degraded == {"udid": ..., "reason": ...}` — see Step 6).

- [ ] **Step 6: Fix the now-stale existing watchdog char-tests.**
  ⚠️ `tests/test_wifi_tunnel_service_watchdog_char.py:59-63` and `:83` assert `tunnel_degraded` deep-equals the OLD shape (no attempt keys), and `_make_service` there passes `restart_backoff=(3.0, 6.0, 12.0)`. After Step 3 those two assertions fail. Update them to include the new keys. In `tests/test_wifi_tunnel_service_watchdog_char.py`, change the `test_run_watchdog_threads_device_lost_reason` assertion from:
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": DeviceLostError.REASON_TUNNEL_DEAD,
          "last_error": "helper reports tunnel for X is gone",
      }
  ```
  to:
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": DeviceLostError.REASON_TUNNEL_DEAD,
          "last_error": "helper reports tunnel for X is gone",
          "attempt": 1,
          "max_attempts": 3,
          "next_delay_s": 3.0,
      }
  ```
  and change the `test_run_watchdog_clean_exit_keeps_task_exited_shape` assertion from:
  ```python
      assert by_type["tunnel_degraded"] == {"udid": udid, "reason": "task_exited"}
  ```
  to:
  ```python
      assert by_type["tunnel_degraded"] == {
          "udid": udid,
          "reason": "task_exited",
          "attempt": 1,
          "max_attempts": 3,
          "next_delay_s": 3.0,
      }
  ```
  (The `tunnel_lost` assertions in those files are unchanged — `tunnel_lost` does NOT gain attempt keys.)

  **DEFINITE required edit (same commit as Step 3, before Step 8):** `tests/test_watchdog_tunnel_lost_reason_char.py` drives `api.device._per_tunnel_watchdog` (a DIFFERENT code path) and ALSO asserts `tunnel_degraded` — at line ~62 (the `REASON_TUNNEL_DEAD` case) and line ~102 (the `task_exited` case). The watchdog backoff there is `(3.0, 6.0, 12.0)` so the first emit carries `attempt=1, max_attempts=3, next_delay_s=3.0`. After Step 3, both of those `tunnel_degraded` assertions fail. Add `'attempt': 1, 'max_attempts': 3, 'next_delay_s': 3.0` to BOTH `tunnel_degraded` deep-equals in that file. The two `tunnel_lost` assertions in the same file are unchanged.

- [ ] **Step 7: Re-run the full backend suite and confirm green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -8
  ```
  Expected: `952 passed` (or the baseline-plus-3 count), 0 failures. Confirm that both `test_watchdog_tunnel_lost_reason_char.py` `tunnel_degraded` assertions now include the three new keys — they were updated in Step 6 and MUST be green before this commit lands.

- [ ] **Step 8: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): enrich tunnel_degraded with attempt/max_attempts/next_delay_s

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

---

### Task 2: Add the `connect_progress` literal to the frontend WS vocabulary (frontend, compile-gate first)

**Why this is second:** The master spec mandates the ordering "add the literal to `WS_EVENT_TYPES` BEFORE a typed subscriber, BEFORE the backend emits it." Adding the literal alone (with NO subscriber, NO emit) is green on its own and unblocks every later typed-subscribe. There are THREE hand-maintained lists that must stay in lockstep (verified by tests): `WS_EVENT_TYPES` in `contract/wsEvents.ts`, `CANONICAL_BACKEND_EVENT_TYPES` in `contract/wsEvents.test.ts`, and `CANONICAL_BACKEND_EVENT_TYPES` in `adapters/ws/eventWiring.test.tsx`.

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/contract/wsEvents.ts` — append `'connect_progress'` to `WS_EVENT_TYPES`; add a `ConnectProgressEvent` interface.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/contract/wsEvents.test.ts` — append `'connect_progress'` to `CANONICAL_BACKEND_EVENT_TYPES`.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/adapters/ws/eventWiring.test.tsx` — append `'connect_progress'` to its `CANONICAL_BACKEND_EVENT_TYPES`.

**Interfaces:**
- Consumes: existing `WS_EVENT_TYPES` const array + `WsEventType` union (`contract/wsEvents.ts:14-28`).
- Produces:
  - `'connect_progress'` added to `WS_EVENT_TYPES` (so `WsEventType` includes it and `ws.subscribe('connect_progress', …)` compiles).
  - `ConnectProgressEvent` interface (for downstream rendering in Task 5):
    ```ts
    export interface ConnectProgressEvent {
      type: 'connect_progress'
      udid?: string
      phase: 'opening_tunnel' | 'rsd_attempt' | 'checking_ddi' | 'opening_dvt' | 'connected'
      attempt?: number
      max?: number
    }
    ```
    `udid` is optional because the RSD-loop phases fire before the device identity is known (RSD `peer_info` is only read after `rsd.connect()` succeeds). `attempt`/`max` are present only on `rsd_attempt`.

- [ ] **Step 1: Add the literal + interface to `wsEvents.ts`.**
  In `/Users/raviwu/personal/locwarp/frontend/src/contract/wsEvents.ts`, change the closing of the `WS_EVENT_TYPES` array from:
  ```ts
    'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
  ] as const
  ```
  to:
  ```ts
    'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
    'connect_progress',
  ] as const
  ```
  Then append after the existing `DeviceDisconnectedEvent` interface (end of file):
  ```ts

  // connect_progress — coarse phases of the iOS connect path (WiFi-tunnel RSD
  // loop, then DDI check + DVT open). Streamed so a slow connect is
  // distinguishable from a hang. udid is absent during the RSD loop (device
  // identity is only known after rsd.connect() succeeds). attempt/max are
  // present only on the 'rsd_attempt' phase. All optional keys are omitted by
  // the backend (exclude_unset/exclude_none).
  export interface ConnectProgressEvent {
    type: 'connect_progress'
    udid?: string
    phase: 'opening_tunnel' | 'rsd_attempt' | 'checking_ddi' | 'opening_dvt' | 'connected'
    attempt?: number
    max?: number
  }
  ```

- [ ] **Step 2: Add the literal to `wsEvents.test.ts`.**
  In `/Users/raviwu/personal/locwarp/frontend/src/contract/wsEvents.test.ts`, change:
  ```ts
    'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
  ] as const
  ```
  to:
  ```ts
    'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
    'connect_progress',
  ] as const
  ```

- [ ] **Step 3: Add the literal to `eventWiring.test.tsx` AND allowlist it.**
  In `/Users/raviwu/personal/locwarp/frontend/src/adapters/ws/eventWiring.test.tsx`:

  **3a.** Find the end of its `CANONICAL_BACKEND_EVENT_TYPES` array (after `'goldditto_cycle'`) and add a new entry. First inspect the exact tail with:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "goldditto_cycle\|] as const" src/adapters/ws/eventWiring.test.tsx | head
  ```
  Then add `'connect_progress', // core/device_manager.py connect path (ConnectProgressEvent)` as the last array entry immediately before that file's `] as const`, mirroring the existing one-comment-per-line style in that array.

  **3b.** **BLOCKER — must happen in the same commit as 3a.** The wiring guard asserts that every type NOT in `UI_IGNORED_BY_DESIGN` has a subscriber among the four hooks `collectSubscribedTypes()` mounts (`useDevice` / `useSimulation` / `useExternalChangeSubscriptions` / `useGoldDittoSubscription`). `connect_progress` is consumed by a NEW `useConnectProgress` hook mounted in `App.tsx` — which the guard does NOT mount. Without an allowlist entry, the guard test turns RED after this commit. Add `'connect_progress'` to the `UI_IGNORED_BY_DESIGN` set (after the existing `'restored'` entry):
  ```ts
    'connect_progress', // consumed by useConnectProgress mounted in App.tsx (not by
    // the four hooks the wiring guard mounts). Must STAY allowlisted permanently.
  ```
  This must land in the same commit as the `CANONICAL_BACKEND_EVENT_TYPES` addition — never split across commits.

- [ ] **Step 4: Type-check + run the contract tests.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx vitest run src/contract/wsEvents.test.ts src/adapters/ws/eventWiring.test.tsx 2>&1 | tail -8
  ```
  Expected: `TSC_OK` printed and both test files pass. `wsEvents.test.ts` verifies the three canonical lists match. `eventWiring.test.tsx` verifies that every REQUIRED_TYPES entry (i.e. `CANONICAL_BACKEND_EVENT_TYPES` minus `UI_IGNORED_BY_DESIGN`) has a subscriber — `connect_progress` is now in `UI_IGNORED_BY_DESIGN` so the guard does not require a subscriber for it.

- [ ] **Step 5: Run the full frontend suite + lint.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run 2>&1 | tail -4 && npx tsc --noEmit && echo TSC_OK && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: all vitest pass (count unchanged from baseline; no new test files), `TSC_OK`, depcruise `no dependency violations found`. The `connect_progress` allowlist entry prevents a RED wiring-guard result.

- [ ] **Step 6: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): register connect_progress in the typed WS vocabulary

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

---

### Task 3: Add the `ConnectProgressEvent` domain model (backend pure)

**Why this is third:** A pure pydantic model in `domain/events.py` is the typed payload the emit points (Task 4) will publish. It is import-pure (stdlib + pydantic only), has its own char-test (mirroring `test_domain_events.py`), and is green on its own.

**Files:**
- Create test: `/Users/raviwu/personal/locwarp/backend/tests/test_connect_progress_event.py`
- Modify: `/Users/raviwu/personal/locwarp/backend/domain/events.py` — append a `ConnectProgressEvent` class.

**Interfaces:**
- Consumes: `WsEvent` base (`domain/events.py:18-34`), `from typing import Optional` (already imported), pydantic `BaseModel`/`ConfigDict` (already imported).
- Produces: `ConnectProgressEvent(WsEvent)` with `type = "connect_progress"`, `phase: str` (required), `udid: Optional[str] = None`, `attempt: Optional[int] = None`, `max: Optional[int] = None`. Serialized via `.model_dump(exclude_unset=True, exclude_none=True)` so absent optional keys are omitted — wire shape `{"type": "connect_progress", "phase": ...[, "udid", "attempt", "max"]}`. The publisher (`WsEventPublisher.publish`, `infra/events/ws_event_publisher.py:28-33`) pops `type` and broadcasts `(event_type, payload)`.

- [ ] **Step 1: Write the failing model test.**
  Create `/Users/raviwu/personal/locwarp/backend/tests/test_connect_progress_event.py` with the COMPLETE content:
  ```python
  """Characterization: ConnectProgressEvent serializes with exclude_unset/
  exclude_none so absent optional keys (udid/attempt/max) stay absent — same
  discipline as the DDI events in test_device_manager_events.py."""

  import pytest


  class FakePublisher:
      def __init__(self):
          self.events = []

      async def publish(self, event):
          if hasattr(event, "model_dump"):
              payload = event.model_dump(exclude_unset=True, exclude_none=True)
              etype = payload.pop("type")
              self.events.append((etype, payload))
          else:
              etype, data = event
              self.events.append((etype, {**data}))


  @pytest.mark.asyncio
  async def test_connect_progress_minimal_phase_only():
      from domain.events import ConnectProgressEvent
      pub = FakePublisher()
      await pub.publish(ConnectProgressEvent(phase="opening_tunnel"))
      assert pub.events[-1] == ("connect_progress", {"phase": "opening_tunnel"})


  @pytest.mark.asyncio
  async def test_connect_progress_rsd_attempt_carries_attempt_and_max():
      from domain.events import ConnectProgressEvent
      pub = FakePublisher()
      await pub.publish(ConnectProgressEvent(phase="rsd_attempt", attempt=2, max=10))
      assert pub.events[-1] == (
          "connect_progress",
          {"phase": "rsd_attempt", "attempt": 2, "max": 10},
      )


  @pytest.mark.asyncio
  async def test_connect_progress_with_udid():
      from domain.events import ConnectProgressEvent
      pub = FakePublisher()
      await pub.publish(ConnectProgressEvent(phase="connected", udid="UDID-Z"))
      assert pub.events[-1] == (
          "connect_progress",
          {"phase": "connected", "udid": "UDID-Z"},
      )


  def test_connect_progress_type_default_is_connect_progress():
      from domain.events import ConnectProgressEvent
      ev = ConnectProgressEvent(phase="checking_ddi")
      assert ev.type == "connect_progress"
  ```

- [ ] **Step 2: Run the new test and watch it FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_connect_progress_event.py -q 2>&1 | tail -10
  ```
  Expected: all 4 tests FAIL with `ImportError: cannot import name 'ConnectProgressEvent' from 'domain.events'`.

- [ ] **Step 3: Add the model (minimal implementation).**
  In `/Users/raviwu/personal/locwarp/backend/domain/events.py`, append after the `DdiMountFailedEvent` class (end of file):
  ```python


  class ConnectProgressEvent(WsEvent):
      type: str = "connect_progress"
      phase: str
      udid: Optional[str] = None
      attempt: Optional[int] = None
      max: Optional[int] = None
  ```

- [ ] **Step 4: Run the new test and watch it PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_connect_progress_event.py -q 2>&1 | tail -5
  ```
  Expected: `4 passed`.

- [ ] **Step 5: Run the full backend suite + import-linter.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -5 && .venv/bin/python -m pytest tests/test_import_linter.py -q 2>&1 | tail -2
  ```
  Expected: all pass (collected now `956` = 952 + 4). `test_import_linter.py` still green — `domain/events.py` only added stdlib `Optional` + pydantic (already imported), so the `domain` purity contract holds.

- [ ] **Step 6: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): add ConnectProgressEvent pure domain model

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

---

### Task 4: Emit `connect_progress` across the connect path (backend danger-zone, test-first)

**Why this is fourth:** `core/device_manager.py` connect recovery is danger-zone (no direct tests) — char-tests come FIRST. The connect path spans TWO methods: the RSD-retry loop in `connect_wifi_tunnel` (`device_manager.py:930-953`), then the DDI check (`_ensure_personalized_ddi_mounted`, `:691`) + DVT open (`_create_dvt_location_service`, `:823`) reached after `connect_wifi_tunnel` returns. Emits go in BOTH. All publishes route through `self._events` (the already-injected `EventPublisher`), awaited in-line, order-preserving. The `connect_wifi_tunnel` emits happen OUTSIDE `self._lock` (the lock is taken only at `:1007-1009` to swap the connection); the DDI/DVT emits already follow the same pattern as the existing `DdiMountedEvent` publishes (`:735-736`) which are NOT under `self._lock`.

**Files:**
- Create test: `/Users/raviwu/personal/locwarp/backend/tests/test_connect_progress_emit_char.py`
- Modify: `/Users/raviwu/personal/locwarp/backend/core/device_manager.py`:
  - `connect_wifi_tunnel` (`:902-1022`): emit `opening_tunnel` once before the RSD loop; emit `rsd_attempt` (with `attempt`/`max`) at the top of each loop iteration.
  - `_ensure_personalized_ddi_mounted` (`:691-756`): emit `checking_ddi` (with `udid`) at the start.
  - `_create_dvt_location_service` (`:823-878`): emit `opening_dvt` (with `udid`) before opening the DVT provider, and `connected` (with `udid`) right before returning the `DvtLocationService`.

**Interfaces:**
- Consumes: `self._events` (`DeviceManager.__init__` param `event_publisher`, `:254-260`) — `None`-safe (call sites guard `if self._events is not None`); `ConnectProgressEvent` from `domain.events` (Task 3). The existing import block in `device_manager.py` already imports the DDI events from `domain.events` — extend it to include `ConnectProgressEvent`.
- Produces: ordered `connect_progress` emits. For a successful WiFi connect driven through `connect_wifi_tunnel` then `_create_dvt_location_service`:
  ```
  ("connect_progress", {"phase": "opening_tunnel"})
  ("connect_progress", {"phase": "rsd_attempt", "attempt": 1, "max": 10})
  [... more rsd_attempt if retries ...]
  ("connect_progress", {"phase": "checking_ddi", "udid": <udid>})
  ("connect_progress", {"phase": "opening_dvt", "udid": <udid>})
  ("connect_progress", {"phase": "connected", "udid": <udid>})
  ```
  Emit failures are caught + logged and NEVER abort the connect (mirror the existing `try/except` around DDI publishes).

- [ ] **Step 1: Write the failing characterization test for the RSD-loop emits.**
  This test drives the REAL `connect_wifi_tunnel` with a fake `RemoteServiceDiscoveryService` injected by monkeypatching the symbol in the module, asserting the ordered `opening_tunnel` + `rsd_attempt` emits and that they fire OUTSIDE the lock. Create `/Users/raviwu/personal/locwarp/backend/tests/test_connect_progress_emit_char.py` with the COMPLETE content:
  ```python
  """Characterization: the connect path emits connect_progress phases in exact
  order, awaited in-line through the injected EventPublisher (never stubbed).
  We drive the REAL DeviceManager.connect_wifi_tunnel with a fake RSD (succeeds
  on the first connect) and the REAL _create_dvt_location_service with a fake
  DvtProvider, asserting the ordered (type, payload) tuples.
  """
  from __future__ import annotations

  import asyncio
  from unittest.mock import MagicMock

  import pytest

  import core.device_manager as dm_mod
  from core.device_manager import DeviceManager, _ActiveConnection

  pytestmark = pytest.mark.asyncio


  class _CapPublisher:
      def __init__(self):
          self.events: list[tuple] = []

      async def publish(self, event):
          # Normalize typed events to (type, payload) deep-equal tuples.
          payload = event.model_dump(exclude_unset=True, exclude_none=True)
          etype = payload.pop("type")
          self.events.append((etype, payload))


  class _FakeRSD:
      """Fake RemoteServiceDiscoveryService: connect() succeeds immediately."""

      def __init__(self, _addr):
          self.peer_info = {"Properties": {"UniqueDeviceID": "UDID-CP", "OSVersion": "17.4", "DeviceClass": "iPhone"}}
          self.all_values = {"DeviceName": "Ravi iPhone"}

      async def connect(self):
          return None

      async def close(self):
          return None


  async def test_connect_wifi_tunnel_emits_opening_then_rsd_attempt(monkeypatch):
      pub = _CapPublisher()
      dm = DeviceManager(event_publisher=pub)

      monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _FakeRSD)
      # Suppress device-name cache side effects (file I/O) — they don't affect emits.
      monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
      monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

      info = await dm.connect_wifi_tunnel("fd00::1", 49152)
      assert info.udid == "UDID-CP"

      progress = [(e, d) for e, d in pub.events if e == "connect_progress"]
      # opening_tunnel first, then the single successful rsd_attempt (1/10).
      assert progress[0] == ("connect_progress", {"phase": "opening_tunnel"})
      assert progress[1] == ("connect_progress", {"phase": "rsd_attempt", "attempt": 1, "max": 10})


  async def test_connect_progress_emit_failure_does_not_abort_connect(monkeypatch):
      class _BoomPublisher:
          async def publish(self, event):
              raise RuntimeError("publish boom")

      dm = DeviceManager(event_publisher=_BoomPublisher())
      monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _FakeRSD)
      monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
      monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

      # A publish() that always raises must NOT abort the connect.
      info = await dm.connect_wifi_tunnel("fd00::1", 49152)
      assert info.udid == "UDID-CP"


  async def test_ddi_and_dvt_phases_emit_in_order(monkeypatch):
      pub = _CapPublisher()
      dm = DeviceManager(event_publisher=pub)

      # Fake DvtProvider so _create_dvt_location_service opens "DVT" cleanly.
      class _FakeDvt:
          def __init__(self, _lockdown):
              pass

          async def __aenter__(self):
              return self

      monkeypatch.setattr(dm_mod, "DvtProvider", _FakeDvt)

      # Make the DDI check a no-op that still emits checking_ddi (real method,
      # but MobileImageMounter import path short-circuits to return). We drive
      # the REAL _create_dvt_location_service, which calls the REAL
      # _ensure_personalized_ddi_mounted.
      async def _no_mounter(*a, **k):
          raise ImportError("no mounter in test")
      # Force the early ImportError return in _ensure_personalized_ddi_mounted
      # so it emits checking_ddi then returns without touching real hardware.
      import sys
      import types as _types
      fake_mod = _types.ModuleType("pymobiledevice3.services.mobile_image_mounter")
      monkeypatch.setitem(sys.modules, "pymobiledevice3.services.mobile_image_mounter", fake_mod)

      conn = _ActiveConnection(udid="UDID-CP", lockdown=object(), ios_version="17.4", connection_type="Network")
      loc = await dm._create_dvt_location_service(conn)
      assert loc is not None

      progress = [(e, d) for e, d in pub.events if e == "connect_progress"]
      phases = [d["phase"] for _, d in progress]
      # checking_ddi (from _ensure_personalized_ddi_mounted) → opening_dvt → connected
      assert phases == ["checking_ddi", "opening_dvt", "connected"]
      assert all(d.get("udid") == "UDID-CP" for _, d in progress)
  ```
  ⚠️ Before relying on `test_ddi_and_dvt_phases_emit_in_order`, confirm the exact import-shape used inside `_ensure_personalized_ddi_mounted` (`device_manager.py:709`: `from pymobiledevice3.services.mobile_image_mounter import MobileImageMounterService`). The fake module above has no `MobileImageMounterService` attribute → the `from … import …` raises `ImportError` → the method emits `checking_ddi` then hits the existing early `return` (line 715). If the import does NOT raise in your venv, instead monkeypatch `MobileImageMounterService` on the real module to a class whose `connect()` raises, so the method still emits `checking_ddi` then returns at the broad `except` (line 728). Verify with: `cd /Users/raviwu/personal/locwarp/backend && grep -n "from pymobiledevice3.services.mobile_image_mounter" core/device_manager.py`.

- [ ] **Step 2: Run the new test and watch it FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_connect_progress_emit_char.py -q 2>&1 | tail -20
  ```
  Expected: `test_connect_wifi_tunnel_emits_opening_then_rsd_attempt` and `test_ddi_and_dvt_phases_emit_in_order` FAIL (no `connect_progress` events emitted yet — `progress` is empty, IndexError or assertion mismatch). `test_connect_progress_emit_failure_does_not_abort_connect` should PASS already (no emits = nothing to boom). Confirm the failures are missing-emit assertions, not setup errors. If the fakes are wrong (e.g. `connect_wifi_tunnel` raises before any emit point), fix the fake until the failure is specifically "no connect_progress events," then proceed.

- [ ] **Step 3: Extend the `domain.events` import in `device_manager.py`.**
  Inspect the existing import line:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && grep -n "from domain.events import" core/device_manager.py
  ```
  Add `ConnectProgressEvent` to that import (preserve the existing imported names; if the import is multi-line parenthesized, add the name inside the parens). Example: if the line is `from domain.events import DdiMountedEvent, DdiNotMountedEvent, DdiMountingEvent, DdiMountFailedEvent`, change it to `from domain.events import ConnectProgressEvent, DdiMountedEvent, DdiNotMountedEvent, DdiMountingEvent, DdiMountFailedEvent`.

- [ ] **Step 4: Add a small private emit helper (minimal implementation).**
  In `/Users/raviwu/personal/locwarp/backend/core/device_manager.py`, add this helper method on `DeviceManager` (place it just above `_ensure_personalized_ddi_mounted`, near line 691):
  ```python
      async def _emit_connect_progress(
          self,
          phase: str,
          *,
          udid: str | None = None,
          attempt: int | None = None,
          max: int | None = None,
      ) -> None:
          """Emit a coarse connect-progress phase through the injected
          EventPublisher. Awaited in-line, order-preserving. Never under
          self._lock. Failures are swallowed (logged) so a publish error can
          NEVER abort the connect — mirrors the DDI-event try/except."""
          if self._events is None:
              return
          try:
              await self._events.publish(
                  ConnectProgressEvent(phase=phase, udid=udid, attempt=attempt, max=max)
              )
          except Exception:
              logger.debug("connect_progress emit failed (phase=%s)", phase, exc_info=True)
  ```

- [ ] **Step 5: Emit in the RSD loop.**
  In `connect_wifi_tunnel`, locate the loop (currently `:925-946`):
  ```python
          import asyncio as _asyncio
          rsd = None
          last_exc: Exception | None = None
          # TUN interface routes may take a few seconds to become reachable
          # after the tunnel process reports ready, so retry with backoff.
          for attempt in range(1, 11):
              rsd = RemoteServiceDiscoveryService((rsd_address, rsd_port))
  ```
  Insert an `opening_tunnel` emit before the loop and an `rsd_attempt` emit at the top of each iteration, so it reads:
  ```python
          import asyncio as _asyncio
          rsd = None
          last_exc: Exception | None = None
          await self._emit_connect_progress("opening_tunnel")
          # TUN interface routes may take a few seconds to become reachable
          # after the tunnel process reports ready, so retry with backoff.
          for attempt in range(1, 11):
              await self._emit_connect_progress("rsd_attempt", attempt=attempt, max=10)
              rsd = RemoteServiceDiscoveryService((rsd_address, rsd_port))
  ```
  These run OUTSIDE `self._lock` (the lock is taken only later at `:1007`).

- [ ] **Step 6: Emit `checking_ddi` in `_ensure_personalized_ddi_mounted`.**
  At the very start of the method body (`:708`, before the `try: from pymobiledevice3…` import), insert:
  ```python
          await self._emit_connect_progress("checking_ddi", udid=conn.udid)
  ```
  so it becomes:
  ```python
          await self._emit_connect_progress("checking_ddi", udid=conn.udid)
          try:
              from pymobiledevice3.services.mobile_image_mounter import MobileImageMounterService
          except ImportError as exc:
  ```

- [ ] **Step 7: Emit `opening_dvt` and `connected` in `_create_dvt_location_service`.**
  In `_create_dvt_location_service`, after the DDI pre-mount block and before opening the DVT provider (`:837`, `try: dvt = DvtProvider(...)`), insert `opening_dvt`; and right before the `return DvtLocationService(...)` (`:853`) insert `connected`. The relevant region becomes:
  ```python
          # Try to mount DDI proactively (fast no-op when already mounted).
          try:
              await self._ensure_personalized_ddi_mounted(conn)
          except Exception:
              logger.warning("DDI auto-mount failed; DVT may still fail", exc_info=True)

          await self._emit_connect_progress("opening_dvt", udid=conn.udid)
          try:
              dvt = DvtProvider(conn.lockdown)
              await dvt.__aenter__()
              conn.dvt_provider = dvt
              logger.debug("DVT provider opened for %s", conn.udid)
              udid = conn.udid

              async def _factory(_udid: str = udid) -> DvtProvider:
                  return await self.get_fresh_dvt_provider(_udid)

              await self._emit_connect_progress("connected", udid=conn.udid)
              return DvtLocationService(
                  dvt,
                  lockdown=conn.lockdown,
                  dvt_factory=_factory,
              )
  ```
  Keep the existing comments inside that block; only add the two `await self._emit_connect_progress(...)` lines. The `connected` emit goes inside the `try` (on the success path only) — the legacy fallback in the `except` does NOT emit `connected` because it is a degraded path, but it MAY be left without a `connected` emit (the connect handler in `api/device.py` still completes; this is acceptable — the spinner just won't show "connected" on the rare legacy fallback, and the device list refresh clears it).

- [ ] **Step 8: Run the new char-test and watch it PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_connect_progress_emit_char.py -q 2>&1 | tail -10
  ```
  Expected: `3 passed`. If `test_ddi_and_dvt_phases_emit_in_order` still fails on phase ordering, recheck the fake-module strategy in Step 1's warning and adjust the fake (not the production code) until the ordered phases match.

- [ ] **Step 9: Run the full backend suite + import-linter.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -6 && .venv/bin/python -m pytest tests/test_import_linter.py -q 2>&1 | tail -2
  ```
  Expected: all pass (collected now `959` = 956 + 3). `test_import_linter.py` green — `core/device_manager.py` only added an import from `domain.events` (allowed: core → domain) and uses the already-injected `self._events` port (no new outer-ring import).

- [ ] **Step 10: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): emit connect_progress across the WiFi connect path (RSD loop + DDI/DVT)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

---

### Task 5: Surface connect_progress in `DeviceStatus` via a `useConnectProgress` hook (frontend)

**Why this is fifth:** The backend now emits `connect_progress` and the literal is registered (Task 2). This adds the consumer: a small hook subscribes via `WsRouter`, tracks the latest phase per-session, and `DeviceStatus` renders it in its spinner region. Hook-in-isolation testable; `DeviceStatus` gets a new optional prop so its existing tests stay green.

**Files:**
- Create: `/Users/raviwu/personal/locwarp/frontend/src/hooks/useConnectProgress.ts`
- Create test: `/Users/raviwu/personal/locwarp/frontend/src/hooks/useConnectProgress.test.tsx`
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/components/DeviceStatus.tsx` — add an optional `connectPhase?: string | null` prop and render it in the connect spinner region.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/components/DeviceStatus.test.tsx` — add one test asserting the phase label renders when `connectPhase` is set.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/i18n/strings.ts` — add five phase-label keys.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/App.tsx` — call `useConnectProgress` and pass `connectPhase` into `<DeviceStatus>`.

**Interfaces:**
- Consumes: `WsRouter` port (`ports/WsRouter`, used by `useDevice`/`useSimulation`), `ConnectProgressEvent` (`contract/wsEvents.ts`, Task 2), `WsEvent` (`contract/wsEvents.ts`). The `WsRouter.subscribe(type, handler)` returns an unsubscribe fn (see `useSimulation.ts:440`).
- Produces:
  - `useConnectProgress(ws?: WsRouter): { connectPhase: string | null }` — `connectPhase` is the latest `phase` from a `connect_progress` event, reset to `null` on `'connected'` (terminal — connect is done) after a short clear, or kept until the next connect. Single value, no per-udid map (the spinner region is global to the connecting device).
  - `DeviceStatus` new prop `connectPhase?: string | null` (default `undefined`/`null`).

- [ ] **Step 1: Add the i18n phase-label keys.**
  In `/Users/raviwu/personal/locwarp/frontend/src/i18n/strings.ts`, immediately after the `'wifi.tunnel_reconnecting'` line (line 266), add:
  ```ts
    'wifi.connect_phase.opening_tunnel': { zh: '正在開啟通道…', en: 'Opening tunnel…' },
    'wifi.connect_phase.rsd_attempt': { zh: '正在連線 RSD…', en: 'Connecting to RSD…' },
    'wifi.connect_phase.checking_ddi': { zh: '正在檢查 DDI…', en: 'Checking DDI…' },
    'wifi.connect_phase.opening_dvt': { zh: '正在開啟 DVT…', en: 'Opening DVT…' },
    'wifi.connect_phase.connected': { zh: '已連線', en: 'Connected' },
  ```

- [ ] **Step 2: Write the failing hook test.**
  Create `/Users/raviwu/personal/locwarp/frontend/src/hooks/useConnectProgress.test.tsx` with the COMPLETE content (mirrors `useSimulation.tunnel.test.tsx`: `createWsRouter` + `renderHook` + `act` + `ws.dispatch`):
  ```tsx
  import { describe, it, expect } from 'vitest'
  import { renderHook, act } from '@testing-library/react'
  import { createWsRouter } from '../adapters/ws/router'
  import { useConnectProgress } from './useConnectProgress'

  describe('useConnectProgress', () => {
    it('starts with no phase', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useConnectProgress(ws))
      expect(result.current.connectPhase).toBeNull()
    })

    it('tracks the latest connect_progress phase', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useConnectProgress(ws))
      act(() => { ws.dispatch({ type: 'connect_progress', phase: 'opening_tunnel' }) })
      expect(result.current.connectPhase).toBe('opening_tunnel')
      act(() => { ws.dispatch({ type: 'connect_progress', phase: 'rsd_attempt', attempt: 1, max: 10 }) })
      expect(result.current.connectPhase).toBe('rsd_attempt')
      act(() => { ws.dispatch({ type: 'connect_progress', phase: 'checking_ddi', udid: 'u1' }) })
      expect(result.current.connectPhase).toBe('checking_ddi')
    })

    it('clears the phase after the connected terminal phase', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useConnectProgress(ws))
      act(() => { ws.dispatch({ type: 'connect_progress', phase: 'opening_dvt', udid: 'u1' }) })
      expect(result.current.connectPhase).toBe('opening_dvt')
      act(() => { ws.dispatch({ type: 'connect_progress', phase: 'connected', udid: 'u1' }) })
      expect(result.current.connectPhase).toBeNull()
    })

    it('is a no-op when ws is undefined', () => {
      const { result } = renderHook(() => useConnectProgress(undefined))
      expect(result.current.connectPhase).toBeNull()
    })
  })
  ```

- [ ] **Step 3: Run the hook test and watch it FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useConnectProgress.test.tsx 2>&1 | tail -10
  ```
  Expected: FAIL with a module-not-found / import error (`useConnectProgress.ts` does not exist yet).

- [ ] **Step 4: Create the hook (minimal implementation).**
  Create `/Users/raviwu/personal/locwarp/frontend/src/hooks/useConnectProgress.ts` with the COMPLETE content:
  ```ts
  import { useEffect, useState } from 'react'
  import type { WsRouter } from '../ports/WsRouter'
  import type { WsEvent } from '../contract/wsEvents'

  // Tracks the latest coarse connect phase streamed by the backend
  // (connect_progress WS event). Rendered in the DeviceStatus spinner region
  // so a slow connect is distinguishable from a hang. Single global value —
  // there is one connecting device at a time in the spinner region. The
  // 'connected' phase is terminal and clears the indicator (the device list
  // refresh + connected dot take over from there).
  export function useConnectProgress(ws?: WsRouter): { connectPhase: string | null } {
    const [connectPhase, setConnectPhase] = useState<string | null>(null)
    useEffect(() => {
      if (!ws) return
      const off = ws.subscribe('connect_progress', (e: WsEvent) => {
        const phase = e.phase as string | undefined
        if (!phase) return
        if (phase === 'connected') {
          setConnectPhase(null)
          return
        }
        setConnectPhase(phase)
      })
      return () => { off() }
    }, [ws])
    return { connectPhase }
  }
  ```

- [ ] **Step 5: Run the hook test and watch it PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useConnectProgress.test.tsx 2>&1 | tail -6
  ```
  Expected: `4 passed`.

- [ ] **Step 6: Add the `connectPhase` prop + render it in `DeviceStatus`.**
  In `/Users/raviwu/personal/locwarp/frontend/src/components/DeviceStatus.tsx`, add `connectPhase?: string | null;` to the `DeviceStatusProps` interface (after `onRevealDeveloperMode?` at line 41):
  ```ts
    onRevealDeveloperMode?: (udid: string) => Promise<void>;
    connectPhase?: string | null;
  ```
  Then add it to the destructured props (after `onRevealDeveloperMode,` at line 54):
  ```ts
    onRevealDeveloperMode,
    connectPhase,
  ```
  Then render a phase line. Insert this block immediately after the status-indicator-row closing `</div>` (after line 289, just before the `{/* Reveal Developer Mode button … */}` comment).

  **BLOCKER — tsc type safety:** `DeviceStatus.tsx` uses `const t = useT()` where `t(key: StringKey, ...)` and `StringKey = keyof typeof STRINGS` (a strict literal union). Rendering `t(\`wifi.connect_phase.${connectPhase}\`)` with `connectPhase: string` fails `tsc` because the template-literal type is not assignable to `StringKey`. Use a typed lookup map instead. Import the `StringKey` type at the top of the file (e.g. `import type { StringKey } from '../i18n/strings'` — check the actual export name with `grep -n "export type StringKey\|export type.*StringKey" src/i18n/strings.ts`). Then define the map inside the component body (before the render return), and use a guarded lookup in the JSX:
  ```tsx
  import type { StringKey } from '../i18n/strings'

  // Inside the component, before the return:
  const PHASE_KEYS: Record<string, StringKey> = {
    opening_tunnel: 'wifi.connect_phase.opening_tunnel',
    rsd_attempt:    'wifi.connect_phase.rsd_attempt',
    checking_ddi:   'wifi.connect_phase.checking_ddi',
    opening_dvt:    'wifi.connect_phase.opening_dvt',
    connected:      'wifi.connect_phase.connected',
  }
  ```
  Then in the JSX block render:
  ```tsx
      {connectPhase && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, padding: '4px 8px', marginBottom: 6,
            background: 'rgba(108, 140, 255, 0.08)',
            border: '1px solid rgba(108, 140, 255, 0.3)',
            borderRadius: 4, color: '#6c8cff',
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ animation: 'spin 1s linear infinite' }}>
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83" />
          </svg>
          <span>{PHASE_KEYS[connectPhase] ? t(PHASE_KEYS[connectPhase]) : null}</span>
        </div>
      )}
  ```
  This passes `tsc` because every value in `PHASE_KEYS` is a known `StringKey` literal (the five `wifi.connect_phase.*` keys added in Step 1), and the `PHASE_KEYS[connectPhase]` guard ensures an unknown `connectPhase` string renders nothing rather than crashing. The five `wifi.connect_phase.*` i18n keys are added as a flat map `'key': { zh, en }` in `src/i18n/strings.ts` in Step 1.

- [ ] **Step 7: Add the DeviceStatus render test.**
  In `/Users/raviwu/personal/locwarp/frontend/src/components/DeviceStatus.test.tsx`, add this test inside the `describe('DeviceStatus', …)` block (after the last existing `it(...)`, before the closing `})`):
  ```tsx
    it('renders the connect phase label in the spinner region', () => {
      render(<DeviceStatus {...baseProps} connectPhase="rsd_attempt" />)
      // i18n mock returns the key; the phase line renders the phase-label key.
      expect(screen.getByText('wifi.connect_phase.rsd_attempt')).toBeInTheDocument()
    })

    it('renders nothing extra when connectPhase is null', () => {
      render(<DeviceStatus {...baseProps} connectPhase={null} />)
      expect(screen.queryByText('wifi.connect_phase.rsd_attempt')).not.toBeInTheDocument()
    })
  ```

- [ ] **Step 8: Run the DeviceStatus test and watch it PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/DeviceStatus.test.tsx 2>&1 | tail -8
  ```
  Expected: all DeviceStatus tests pass including the 2 new ones (`rsd_attempt` label present; null → absent). The i18n mock in that file (`useT: () => (key: string) => key`) returns the key, so the template-literal key `wifi.connect_phase.rsd_attempt` renders verbatim.

- [ ] **Step 9: Wire `useConnectProgress` into App.tsx and pass `connectPhase` to `<DeviceStatus>`.**
  In `/Users/raviwu/personal/locwarp/frontend/src/App.tsx`, first confirm the variable names used for the WS router and existing hooks:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "useSimulation(\|useDevice(\|const router\|ws: router\|useConnectProgress\|import .*useSimulation" src/App.tsx | head
  ```
  The router comes from `useServices()` as `ws: router` (i.e. the WsRouter is named `router`, not `ws`). Add the import near the other hook imports (mirror the existing `import { useSimulation } from './hooks/useSimulation'` style):
  ```ts
  import { useConnectProgress } from './hooks/useConnectProgress'
  ```
  Then, immediately after the `const sim = useSimulation(router, …)` / `const device = useDevice(router)` calls, add — using the same `router` variable those calls receive:
  ```ts
    const { connectPhase } = useConnectProgress(router)
  ```
  Then add the prop to the `<DeviceStatus>` element (after `onRevealDeveloperMode={…}` which ends around line 1163 — add it as the last prop before the closing `/>`):
  ```tsx
          connectPhase={connectPhase}
  ```

- [ ] **Step 10: Type-check + run the full frontend suite + lint.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx vitest run 2>&1 | tail -4 && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: `TSC_OK`; all vitest pass (count = baseline + 6 new: 4 hook + 2 DeviceStatus); depcruise `no dependency violations found`. The hook imports only `ports/WsRouter` + `contract/wsEvents` (allowed: hooks → ports/contract), never `adapters/api`.

- [ ] **Step 11: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): render connect_progress phases in DeviceStatus via useConnectProgress

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

**Note — "as needed" items evaluated and closed:** `useWifiAutoConnect.ts` and `useDevice.ts` were audited and need NO change for this task. The one-click Reconnect (Task 7) reuses the already-exported `device.startWifiTunnel` from `useDevice` and a read-only `savedips` localStorage read — no new methods or state are required in either hook.

---

### Task 6: Reconnecting banner shows attempt + live countdown (frontend)

**Why this is sixth:** Task 1 enriched `tunnel_degraded` with `{attempt, max_attempts, next_delay_s}`. This consumes those keys: `useSimulation`'s existing `tunnel_degraded` handler captures them into a new state, and `App.tsx`'s amber banner renders "attempt 1/3, retrying in 6s" with a 1 Hz countdown.

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.ts` — extend the `tunnel_degraded` handler (`:440-446`) to capture attempt/max/next_delay_s; add `reconnectInfo` state + a 1 Hz countdown effect; add to the return object (`:1002`).
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.tunnel.test.tsx` — add tests asserting `reconnectInfo` is populated and the countdown ticks.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/App.tsx` — the amber banner (`:1572-1583`) renders the attempt + countdown when present.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/i18n/strings.ts` — add a parameterized countdown string.

**Interfaces:**
- Consumes: the enriched `tunnel_degraded` payload from Task 1 — `e.attempt`, `e.max_attempts`, `e.next_delay_s` (all optional numbers; absent when `restart_backoff` is empty). Existing `tunnelReconnecting` state (`:208`), `primaryUdidRef` filter (`:442`).
- Produces:
  - new `useSimulation` state `reconnectInfo: { attempt: number; maxAttempts: number; retryInSec: number } | null` — set on `tunnel_degraded` (when the keys are present), cleared on `tunnel_recovered`/`tunnel_lost`/`device_connected` (the same handlers that clear `tunnelReconnecting`). `retryInSec` counts down at 1 Hz to 0.
  - added to the hook's return object so `App.tsx` reads `sim.reconnectInfo`.

- [ ] **Step 1: Add the parameterized i18n string.**
  In `/Users/raviwu/personal/locwarp/frontend/src/i18n/strings.ts`, immediately after the new `'wifi.connect_phase.connected'` line (added in Task 5), add:
  ```ts
    'wifi.tunnel_reconnecting_attempt': {
      zh: 'WiFi Tunnel 連線中斷,重試 {attempt}/{max},{sec} 秒後重連…',
      en: 'Wi-Fi tunnel dropped — attempt {attempt}/{max}, retrying in {sec}s…',
    },
  ```
  ⚠️ Confirm the `t()` interpolation syntax used in this repo first:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "devices_found\|{ n:\|{n}\|interpolat\|replace(" src/i18n/strings.ts src/i18n/*.ts | head
  ```
  Match the placeholder style the existing `t('device.devices_found', { n: … })` calls use (e.g. `{n}`). If the repo uses `{n}`-style braces, the keys above (`{attempt}`/`{max}`/`{sec}`) are correct; if it uses a different token, adjust to match.

- [ ] **Step 2: Write the failing reconnectInfo tests.**
  In `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.tunnel.test.tsx`, add these tests inside the `describe('useSimulation — WiFi tunnel three-state', …)` block (after the existing `it('device_connected after recovery …')`, before the closing `})`):
  ```tsx
    it('tunnel_degraded with attempt keys populates reconnectInfo', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useSimulation(ws, null))
      act(() => {
        ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', reason: 'task_exited', attempt: 1, max_attempts: 3, next_delay_s: 6 })
      })
      expect(result.current.reconnectInfo).toEqual({ attempt: 1, maxAttempts: 3, retryInSec: 6 })
    })

    it('tunnel_degraded without attempt keys leaves reconnectInfo null', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useSimulation(ws, null))
      act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', reason: 'task_exited' }) })
      expect(result.current.tunnelReconnecting).toBe(true)
      expect(result.current.reconnectInfo).toBeNull()
    })

    it('reconnectInfo is cleared on tunnel_recovered', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useSimulation(ws, null))
      act(() => {
        ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', attempt: 2, max_attempts: 3, next_delay_s: 12 })
      })
      expect(result.current.reconnectInfo).not.toBeNull()
      act(() => { ws.dispatch({ type: 'tunnel_recovered', udid: 'dev-a', rsd_address: 'x', rsd_port: 1 }) })
      expect(result.current.reconnectInfo).toBeNull()
    })

    it('reconnectInfo is cleared on tunnel_lost', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useSimulation(ws, null))
      act(() => {
        ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', attempt: 1, max_attempts: 3, next_delay_s: 6 })
      })
      expect(result.current.reconnectInfo).not.toBeNull()
      act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-a', reason: 'task_exited' }) })
      expect(result.current.reconnectInfo).toBeNull()
    })
  ```

- [ ] **Step 3: Run the tests and watch them FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimulation.tunnel.test.tsx 2>&1 | tail -12
  ```
  Expected: the 4 new tests FAIL (`result.current.reconnectInfo` is `undefined` — the property does not exist yet). The existing 8 tests in the file still PASS.

- [ ] **Step 4: Add the `reconnectInfo` state + countdown effect (minimal implementation).**
  In `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.ts`, after the `const [tunnelReconnecting, setTunnelReconnecting] = useState(false)` line (`:208`), add:
  ```ts
    // Attempt counter + retry countdown derived from the enriched tunnel_degraded
    // payload ({attempt, max_attempts, next_delay_s}). Null when the backend
    // sent no attempt keys (empty backoff) — the banner then falls back to the
    // plain "reconnecting…" copy. retryInSec ticks down to 0 at 1 Hz.
    const [reconnectInfo, setReconnectInfo] = useState<
      { attempt: number; maxAttempts: number; retryInSec: number } | null
    >(null)
  ```
  Then add a 1 Hz countdown effect. Place it right after the existing pause-countdown effect (`:279-292`):
  ```ts
    // Tick the reconnect retry countdown down to 0 at 1 Hz.
    useEffect(() => {
      if (reconnectInfo == null) return
      if (reconnectInfo.retryInSec <= 0) return
      const id = setInterval(() => {
        setReconnectInfo((prev) => {
          if (prev == null) return prev
          const next = Math.max(0, prev.retryInSec - 1)
          if (next === prev.retryInSec) return prev
          return { ...prev, retryInSec: next }
        })
      }, 1000)
      return () => clearInterval(id)
    }, [reconnectInfo])
  ```

- [ ] **Step 5: Populate / clear `reconnectInfo` in the tunnel handlers.**
  In `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.ts`, extend the `tunnel_degraded` handler (`:440-446`) from:
  ```ts
      const offTunnelDegraded = ws.subscribe('tunnel_degraded', (e: WsEvent) => {
        const msgUdid = e.udid as string | undefined
        const primary = primaryUdidRef.current
        if (primary && msgUdid && msgUdid !== primary) return
        // Entering the backend retry/backoff window — show "reconnecting…".
        setTunnelReconnecting(true)
      })
  ```
  to:
  ```ts
      const offTunnelDegraded = ws.subscribe('tunnel_degraded', (e: WsEvent) => {
        const msgUdid = e.udid as string | undefined
        const primary = primaryUdidRef.current
        if (primary && msgUdid && msgUdid !== primary) return
        // Entering the backend retry/backoff window — show "reconnecting…".
        setTunnelReconnecting(true)
        // Enriched payload (attempt/max_attempts/next_delay_s) drives the
        // attempt counter + countdown. Absent (empty backoff) → leave null so
        // the banner shows the plain reconnecting copy.
        const attempt = typeof e.attempt === 'number' ? e.attempt : undefined
        const maxAttempts = typeof e.max_attempts === 'number' ? e.max_attempts : undefined
        const nextDelay = typeof e.next_delay_s === 'number' ? e.next_delay_s : undefined
        if (attempt != null && maxAttempts != null && nextDelay != null) {
          setReconnectInfo({ attempt, maxAttempts, retryInSec: Math.round(nextDelay) })
        }
      })
  ```
  Then add `setReconnectInfo(null)` to BOTH the `tunnel_recovered` handler (`:448-459`, alongside `setTunnelReconnecting(false)`) and the `tunnel_lost` handler (`:461-472`, alongside `setTunnelReconnecting(false)`). For `tunnel_recovered`, after `setTunnelReconnecting(false)` add `setReconnectInfo(null)`. For `tunnel_lost`, after `setTunnelReconnecting(false)` add `setReconnectInfo(null)`.
  ⚠️ Also check the `device_connected` backstop that clears `tunnelReconnecting` (the test `device_connected after recovery is a backstop` expects it). Find it:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "setTunnelReconnecting(false)" src/hooks/useSimulation.ts
  ```
  At each `setTunnelReconnecting(false)` that represents a "connection restored / lost" transition (the device_connected backstop and the tunnel_recovered/tunnel_lost handlers), add `setReconnectInfo(null)` immediately after it. Do NOT add it anywhere `setTunnelReconnecting(false)` is part of an unrelated reset that should keep an active countdown.

- [ ] **Step 6: Add `reconnectInfo` to the hook return.**
  In `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.ts`, find the return object (`:1002`) and the existing `tunnelReconnecting,` entry within it (`:1064`). Add `reconnectInfo,` adjacent to `tunnelReconnecting,`:
  ```ts
      tunnelReconnecting,
      reconnectInfo,
  ```

- [ ] **Step 7: Run the tunnel tests and watch them PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimulation.tunnel.test.tsx 2>&1 | tail -8
  ```
  Expected: all tests pass (8 existing + 4 new = 12). Note the countdown-tick interval is real-time; the tests above assert the INITIAL `retryInSec` value and clearing, not a fake-timer tick, so no `vi.useFakeTimers()` is needed.

- [ ] **Step 8: Render the attempt + countdown in the App.tsx banner.**
  In `/Users/raviwu/personal/locwarp/frontend/src/App.tsx`, replace the amber banner body (`:1572-1583`):
  ```tsx
          {sim.tunnelReconnecting && !sim.error && (
            <div
              style={{
                position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
                zIndex: 2000, background: '#f59e0b', color: '#1a1d22', padding: '8px 20px',
                borderRadius: 6, fontSize: 13, fontWeight: 600,
                boxShadow: '0 4px 12px rgba(0,0,0,0.4)', maxWidth: '80%', textAlign: 'center',
              }}
            >
              {t('wifi.tunnel_reconnecting')}
            </div>
          )}
  ```
  with:
  ```tsx
          {sim.tunnelReconnecting && !sim.error && (
            <div
              style={{
                position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
                zIndex: 2000, background: '#f59e0b', color: '#1a1d22', padding: '8px 20px',
                borderRadius: 6, fontSize: 13, fontWeight: 600,
                boxShadow: '0 4px 12px rgba(0,0,0,0.4)', maxWidth: '80%', textAlign: 'center',
              }}
            >
              {sim.reconnectInfo
                ? t('wifi.tunnel_reconnecting_attempt', {
                    attempt: sim.reconnectInfo.attempt,
                    max: sim.reconnectInfo.maxAttempts,
                    sec: sim.reconnectInfo.retryInSec,
                  })
                : t('wifi.tunnel_reconnecting')}
            </div>
          )}
  ```
  ⚠️ Match the `t(key, vars)` call shape to the repo's existing usage (e.g. `t('device.devices_found', { n: devices.length })`). If the i18n helper uses positional or different key names, adjust the `vars` object accordingly (confirmed via the grep in Step 1).

- [ ] **Step 9: Type-check + run the full frontend suite + lint.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx vitest run 2>&1 | tail -4 && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: `TSC_OK`; all vitest pass (count = previous + 4 new tunnel tests); depcruise `no dependency violations found`.

- [ ] **Step 10: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): reconnecting banner shows attempt N/M + live retry countdown

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

---

### Task 7: `tunnel_lost` one-click Reconnect from savedips (frontend)

**Why this is last:** It depends on the terminal `error` banner (driven by `tunnel_lost`) being in place (already shipped) and reuses `startWifiTunnel` + the `savedips` localStorage list (`useDevice.startWifiTunnel:215-229`). Pure frontend; turns a six-step manual recovery into one click. The `tunnel_lost` event carries `udid` (`wifi_tunnel_service.py:255`), so the banner can pick the matching `savedips` entry by udid.

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.ts` — the `tunnel_lost` handler captures the lost udid into a new `lostUdid` state (cleared on recover/connect); add to the return object.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.tunnel.test.tsx` — add a test asserting `lostUdid` is set on `tunnel_lost`.
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/App.tsx` — the red error banner (`:1555-1567`), when `sim.lostUdid` is set, gains a Reconnect button that looks up the savedips entry and calls `device.startWifiTunnel`.
- Create: `/Users/raviwu/personal/locwarp/frontend/src/hooks/savedips.ts` — a tiny pure helper `readSavedipEntry(udid)` shared between this task and reused by the existing logic (read-only; the writer stays in `useDevice`).
- Create test: `/Users/raviwu/personal/locwarp/frontend/src/hooks/savedips.test.ts`
- Modify: `/Users/raviwu/personal/locwarp/frontend/src/i18n/strings.ts` — add a Reconnect button label.

**Interfaces:**
- Consumes: `localStorage['locwarp.tunnel.savedips']` — a JSON array of `{ ip: string; port: number; udid?: string; lastUsed: number }` (written by `useDevice.startWifiTunnel:228`). `device.startWifiTunnel(ip, port?, udidHint?, bonjourId?)` (`useDevice.ts:184`). The `tunnel_lost` payload `udid` (`wsEvents` `WsEvent`).
- Produces:
  - `readSavedipEntry(udid: string | null): { ip: string; port: number; udid?: string } | null` — pure; parses the savedips list and returns the entry matching `udid`, or the most-recent entry when `udid` is null/unmatched, or `null` when the list is empty/corrupt.
  - new `useSimulation` state `lostUdid: string | null` — set on `tunnel_lost` (primary-filtered, same as `error`), cleared on `tunnel_recovered`/`device_connected`. Added to the return object.

- [ ] **Step 1: Add the Reconnect i18n label.**
  In `/Users/raviwu/personal/locwarp/frontend/src/i18n/strings.ts`, after the `'wifi.tunnel_reconnecting_attempt'` block (Task 6), add:
  ```ts
    'wifi.tunnel_reconnect_now': { zh: '重新連線', en: 'Reconnect' },
  ```

- [ ] **Step 2: Write the failing savedips helper test.**
  Create `/Users/raviwu/personal/locwarp/frontend/src/hooks/savedips.test.ts` with the COMPLETE content:
  ```ts
  import { describe, it, expect, beforeEach } from 'vitest'
  import { readSavedipEntry } from './savedips'

  describe('readSavedipEntry', () => {
    beforeEach(() => { localStorage.clear() })

    it('returns null when no savedips are stored', () => {
      expect(readSavedipEntry('u1')).toBeNull()
    })

    it('returns the entry matching the udid', () => {
      localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify([
        { ip: '10.0.0.2', port: 49152, udid: 'u2', lastUsed: 200 },
        { ip: '10.0.0.1', port: 49153, udid: 'u1', lastUsed: 100 },
      ]))
      expect(readSavedipEntry('u1')).toEqual({ ip: '10.0.0.1', port: 49153, udid: 'u1' })
    })

    it('falls back to the first (most recent) entry when udid is null', () => {
      localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify([
        { ip: '10.0.0.2', port: 49152, udid: 'u2', lastUsed: 200 },
        { ip: '10.0.0.1', port: 49153, udid: 'u1', lastUsed: 100 },
      ]))
      expect(readSavedipEntry(null)).toEqual({ ip: '10.0.0.2', port: 49152, udid: 'u2' })
    })

    it('falls back to the first entry when the udid does not match any', () => {
      localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify([
        { ip: '10.0.0.2', port: 49152, udid: 'u2', lastUsed: 200 },
      ]))
      expect(readSavedipEntry('nope')).toEqual({ ip: '10.0.0.2', port: 49152, udid: 'u2' })
    })

    it('returns null on corrupt JSON', () => {
      localStorage.setItem('locwarp.tunnel.savedips', '{not json')
      expect(readSavedipEntry('u1')).toBeNull()
    })
  })
  ```

- [ ] **Step 3: Run the helper test and watch it FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/savedips.test.ts 2>&1 | tail -8
  ```
  Expected: FAIL with module-not-found (`savedips.ts` does not exist).

- [ ] **Step 4: Create the savedips helper (minimal implementation).**
  Create `/Users/raviwu/personal/locwarp/frontend/src/hooks/savedips.ts` with the COMPLETE content:
  ```ts
  // Read-only view of the per-device WiFi-tunnel savedips list. The WRITER lives
  // in useDevice.startWifiTunnel (it appends {ip,port,udid,lastUsed} after every
  // successful tunnel, newest-first). This helper picks the entry to re-fire on
  // a one-click Reconnect: prefer the entry matching the lost udid, else the
  // most-recent (first) entry.
  export interface SavedipEntry {
    ip: string
    port: number
    udid?: string
  }

  export function readSavedipEntry(udid: string | null): SavedipEntry | null {
    let raw: string | null = null
    try { raw = localStorage.getItem('locwarp.tunnel.savedips') } catch { return null }
    if (!raw) return null
    let list: unknown
    try { list = JSON.parse(raw) } catch { return null }
    if (!Array.isArray(list)) return null
    const entries = list.filter(
      (e): e is { ip: string; port?: number; udid?: string } =>
        !!e && typeof e.ip === 'string' && e.ip.trim().length > 0,
    )
    if (entries.length === 0) return null
    const toEntry = (e: { ip: string; port?: number; udid?: string }): SavedipEntry => ({
      ip: String(e.ip).trim(),
      port: Number(e.port) || 49152,
      udid: typeof e.udid === 'string' && e.udid ? e.udid : undefined,
    })
    if (udid) {
      const match = entries.find((e) => e.udid === udid)
      if (match) return toEntry(match)
    }
    return toEntry(entries[0])
  }
  ```

- [ ] **Step 5: Run the helper test and watch it PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/savedips.test.ts 2>&1 | tail -6
  ```
  Expected: `5 passed`.

- [ ] **Step 6: Write the failing `lostUdid` test.**
  In `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.tunnel.test.tsx`, add inside the describe block (after the Task 6 tests, before the closing `})`):
  ```tsx
    it('tunnel_lost captures the lost udid', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useSimulation(ws, null))
      act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-lost', reason: 'task_exited' }) })
      expect(result.current.lostUdid).toBe('dev-lost')
    })

    it('tunnel_recovered clears lostUdid', () => {
      const ws = createWsRouter()
      const { result } = renderHook(() => useSimulation(ws, null))
      act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-lost' }) })
      expect(result.current.lostUdid).toBe('dev-lost')
      act(() => { ws.dispatch({ type: 'tunnel_recovered', udid: 'dev-lost', rsd_address: 'x', rsd_port: 1 }) })
      expect(result.current.lostUdid).toBeNull()
    })
  ```

- [ ] **Step 7: Run and watch them FAIL.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimulation.tunnel.test.tsx 2>&1 | tail -10
  ```
  Expected: the 2 new tests FAIL (`result.current.lostUdid` is `undefined`).

- [ ] **Step 8: Add `lostUdid` state + wire the handlers + return (minimal implementation).**
  In `/Users/raviwu/personal/locwarp/frontend/src/hooks/useSimulation.ts`, after the `reconnectInfo` state added in Task 6, add:
  ```ts
    // The udid whose tunnel was just LOST (terminal). Drives the one-click
    // Reconnect button on the error banner. Cleared when the tunnel recovers or
    // the device reconnects.
    const [lostUdid, setLostUdid] = useState<string | null>(null)
  ```
  In the `tunnel_lost` handler (`:461-472`), after the existing `setError(...)` line, add:
  ```ts
        setLostUdid((msgUdid as string | undefined) ?? null)
  ```
  (Use the handler's local `msgUdid` variable — it is already destructured at the top of the handler.) In the `tunnel_recovered` handler, after `setReconnectInfo(null)` (added in Task 6), add `setLostUdid(null)`. Also add `setLostUdid(null)` to the `device_connected` backstop alongside the existing `setTunnelReconnecting(false)` (the same place Task 6 added `setReconnectInfo(null)`). Then in the return object, add `lostUdid,` adjacent to `reconnectInfo,`:
  ```ts
      reconnectInfo,
      lostUdid,
  ```

- [ ] **Step 9: Run the tunnel tests and watch them PASS.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimulation.tunnel.test.tsx 2>&1 | tail -8
  ```
  Expected: all pass (12 from Task 6 + 2 new = 14).

- [ ] **Step 10: Add the Reconnect button to the error banner in App.tsx.**
  First import the helper near the other App.tsx imports:
  ```ts
  import { readSavedipEntry } from './hooks/savedips'
  ```
  Then replace the red error banner (`:1555-1567`):
  ```tsx
            <div
              style={{
                position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
                zIndex: 2000, background: '#dc2626', color: '#fff', padding: '8px 20px',
                borderRadius: 6, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                cursor: 'pointer', maxWidth: '80%', textAlign: 'center',
              }}
              onClick={sim.clearError}
            >
              {sim.error}
            </div>
  ```
  ⚠️ The exact opening `<div>` style (background `#e53935` etc.) must match what is currently at `:1555-1567` — inspect it first:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "sim.error\|clearError\|dc2626\|onClick={sim" src/App.tsx | head
  ```
  Replace the banner's inner content so it renders a Reconnect button beside the message when `sim.lostUdid` resolves a savedips entry. Keep the dismiss-on-click behavior on the text but NOT on the button (the button has its own handler that stops propagation):
  ```tsx
            <div
              style={{
                position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
                zIndex: 2000, background: '#dc2626', color: '#fff', padding: '8px 20px',
                borderRadius: 6, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                maxWidth: '80%', textAlign: 'center',
                display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'center',
              }}
            >
              <span style={{ cursor: 'pointer' }} onClick={sim.clearError}>{sim.error}</span>
              {(() => {
                const entry = readSavedipEntry(sim.lostUdid)
                if (!entry) return null
                return (
                  <button
                    onClick={async (e) => {
                      e.stopPropagation()
                      try {
                        await device.startWifiTunnel(entry.ip, entry.port, entry.udid)
                        sim.clearError()
                      } catch (err: any) {
                        showToast(err?.message ?? t('wifi.tunnel_reconnect_now'))
                      }
                    }}
                    style={{
                      fontSize: 12, fontWeight: 600, padding: '4px 12px', borderRadius: 4,
                      background: '#fff', color: '#dc2626', border: 'none', cursor: 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t('wifi.tunnel_reconnect_now')}
                  </button>
                )
              })()}
            </div>
  ```
  ⚠️ Confirm `device.startWifiTunnel` and `showToast` and `sim.clearError` are all in scope at this point in `App.tsx` (they are — `device` is the `useDevice()` return wired at `:1150` as `onStartWifiTunnel={device.startWifiTunnel}`, `showToast` is used at `:1147`, `sim.clearError` is the existing banner handler). Verify with:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "const device =\|const sim =\|showToast\b\|sim.clearError" src/App.tsx | head
  ```

- [ ] **Step 11: Type-check + run the full frontend suite + lint.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && echo TSC_OK && npx vitest run 2>&1 | tail -4 && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: `TSC_OK`; all vitest pass (count = previous + 5 savedips + 2 lostUdid = +7); depcruise `no dependency violations found`. `savedips.ts` imports nothing app-internal (only `localStorage`), so no layering violation.

- [ ] **Step 12: Commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add -A && git commit -m "feat(c2): one-click Reconnect on tunnel_lost banner from savedips

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
  ```

---

### Task 8: Whole-cluster verification (no code change)

**Files:** none (verification only).

**Interfaces:**
- Consumes: every prior task's deliverable.
- Produces: the final green evidence for the whole cluster.

- [ ] **Step 1: Full backend suite + import-linter.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -6
  ```
  Expected: all pass; collected count = `959` (949 baseline + 10 new backend tests: 3 degraded-attempt + 4 ConnectProgressEvent + 3 connect_progress-emit). Confirm `7 kept, 0 broken` via:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_import_linter.py -q 2>&1 | tail -2
  ```

- [ ] **Step 2: Full frontend suite + tsc + depcruise.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run 2>&1 | tail -4 && npx tsc --noEmit && echo TSC_OK && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -2
  ```
  Expected: all vitest pass (baseline + 19 new frontend tests: 4 useConnectProgress + 2 DeviceStatus + 4 reconnectInfo + 5 savedips + 2 lostUdid + 0 contract list changes [existing files only edited, not new tests] = the three contract lists were edited in place); `TSC_OK`; depcruise `no dependency violations found`.

- [ ] **Step 3: Confirm the three WS-vocabulary lists are still in lockstep.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/contract/wsEvents.test.ts src/adapters/ws/eventWiring.test.tsx 2>&1 | tail -6
  ```
  Expected: both pass — `connect_progress` is present in all three lists.

- [ ] **Step 4: Final clean-tree check (no uncommitted changes).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git status --porcelain
  ```
  Expected: empty output (all work committed across Tasks 1, 2, 3, 4, 5, 6, 7). No commit in this task.
