# Boot + Reconnect Latency — Design Spec

> **Status:** Design (awaiting Ravi's review) — 2026-06-26
> **Author:** Claude (Opus 4.8, 1M) + Ravi
> **Predecessor:** the App Improvement Program (C1–C4, merged 2026-06-25). A subsequent performance audit (multi-agent, 6 lenses, code-grounded) ranked the felt hot-spots; this spec implements the recommended low-risk starter set — the boot + reconnect latency wins.

**Goal:** Cut the wait on the two most-felt latency paths — "app launch → usable" and "tunnel drop → recovered" — with four small, low-risk changes that preserve all external behavior except the (intended) reconnect cadence.

**Architecture:** Defer two heavy boot-time operations (geo enrichment, device auto-connect) off the lifespan critical path by spawning them as concurrent background tasks (the server starts serving immediately); make WiFi auto-connect fire saved-device candidates immediately instead of after a 3s discover; and tighten the tunnel-restart backoff so the first reconnect attempt is near-instant. No new endpoints/events; no structural refactor.

**Tech stack:** FastAPI/Python backend, React 18 + TS + Electron frontend, Vitest + pytest, import-linter + dependency-cruiser gates.

---

## Global Constraints

Copied verbatim into the implementation plan; every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` (baseline ≈1035 collected) + frontend `vitest` (≈857) + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit.
- **Danger-zone-test-first.** `main.py` lifespan, `device_manager` connect path, and `simulation_engine`/movers have NO direct unit tests. Write characterization tests (REAL collaborators, never stub the unit under test) BEFORE touching them.
- **Behavior preserved, latency only.** The eventual state must be identical: the device still auto-connects, geo fields still get enriched, WiFi auto-connect still connects, reconnect still recovers. The ONE intended external-observable change is the tunnel-restart backoff cadence (which changes the `tunnel_degraded` event's `next_delay_s`/`max_attempts` values — see Win 4). No new HTTP/WS/IPC surface.
- **Lock & inversion rules hold.** `device_manager → EventPublisher` stays awaited in-line / order-preserving; never acquire the WS connection-manager lock under `device_manager._lock`. Bookmark/route writes stay under `_store_lock`.
- **Preserve the WiFi-auto-connect thrash fix.** The `connectedDevices` ref-mirror guard (memory: `wifi_autoconnect_tunnel_thrash`, fixed 2026-06-23) MUST remain intact — a spurious WiFi tunnel must never tear down a healthy USB tunnel.
- **Personal-repo conventions.** Direct commits to a single cluster branch → ff-merge to `main`; git identity auto-set (never `-c user.email=`).

---

## Win 1 — Defer geo enrichment off the boot critical path (backend)

**Cost today:** `main.py` lifespan `await`s `load_state()` (≈`main.py:914`) before `yield`; `load_state` calls `enrich_all()` (≈`main.py:184` region / `services/bookmarks.py:474`). The first `resolve()` inside `enrich_all` triggers numpy + timezonefinder + a 2.7MB `cities5000.json` parse (≈530ms, measured-from-code), sitting on the awaited critical path — uvicorn does not serve until it finishes.

**Change:** Keep the **store LOAD** pre-yield (bookmarks/routes must exist when the server starts). Defer ONLY `enrich_all()` (the geo-data load + per-bookmark `resolve()`) into a background task spawned before `yield` (`asyncio.create_task`, fire-and-forget with error logging) so the server serves immediately and enrichment completes concurrently.

**Why safe:** geo fields are idempotent (re-running fills the same values); `enrich_all` mutates the store under `_store_lock` (lock-safe vs a concurrent user edit); the frontend re-fetches on the `bookmarks_changed` event the enrichment emits, so late-arriving geo fields render without a reload.

**Files:** `backend/main.py` (lifespan), `backend/services/bookmarks.py` (confirm `enrich_all` is separable from the store load — the load stays, only the enrich defers).

**Tests:** characterization — assert `enrich_all` is SPAWNED (not awaited) during lifespan startup AND still completes + fills geo fields on a freshly-loaded store (drive the real manager; a fake/stepped clock or an awaitable the test can join). Existing bookmark/geo tests stay green.

---

## Win 2 — Defer device auto-connect off pre-yield (backend)

**Cost today:** `main.py:919-925` runs `discover → connect → create_engine_for_device` awaited BEFORE `yield`. A slow phone / Trust dialog / RSD tunnel handshake injects a variable (sometimes multi-second) stall into cold-start before the window is interactive.

**Change:** Spawn the SAME discover→connect→create_engine logic as a background task (reuse the existing fire-and-forget `_spawn` pattern used in `api/location.py:181` / its done-callback that discards the task + logs exceptions) so the server serves immediately; the connect runs concurrently. Behavior is identical (the device still ends up connected) — only the timing moves. Chosen over relying on watchdog adoption because moving the same logic to a task is lower-risk than switching the connect mechanism.

**Files:** `backend/main.py` (lifespan).

**Tests:** characterization — assert the connect block is SPAWNED not awaited during startup AND the device still connects (the connect coroutine runs + reaches the connected state). Drive with a fake device-manager/registry capturing the call (mirror existing lifespan/`test_location_di_char.py`-style harnesses). A connect failure must NOT crash startup (the task's done-callback logs + discards).

---

## Win 3 — WiFi auto-connect fires saved candidates immediately (frontend)

**Cost today:** `useWifiAutoConnect.ts` (~`:137,:152`) `await wifiTunnelDiscover()` — the full ~3s mDNS browse window — BEFORE firing the saved-IP candidates, even though `savedips` already holds exact `{ip, port, udid}` for known phones.

**Change:** Fire the `savedips` candidates IMMEDIATELY; run `wifiTunnelDiscover()` concurrently (`Promise.allSettled`) and use its result only to ADD devices not already in `savedips`. A single-phone user's auto-connect starts ~3s earlier per launch.

**⚠️ Hard constraint:** preserve the thrash-fix guard. The existing `connectedDevices` ref-mirror (which stopped a stale-closure spurious WiFi tunnel from tearing down a healthy USB tunnel — memory `wifi_autoconnect_tunnel_thrash`) MUST remain: a device already connected (USB or WiFi) must NOT get a spurious WiFi-tunnel fire. The reorder changes WHEN savedips fires, not WHETHER the already-connected guard runs.

**Files:** `frontend/src/hooks/useWifiAutoConnect.ts`.

**Tests (Vitest, fireEvent only):** savedips candidate fires immediately (without waiting for discover to resolve); discover runs concurrently and a discover-only (un-saved) device is added; **the no-thrash guard still holds** — a device already in `connectedDevices` does NOT trigger a WiFi-tunnel fire (regression-lock the historical bug). A pre-flight discover throw does not block the savedips fire and does not spuriously toast (preserve the SH-era `useWifiAutoConnect` outer-catch behavior).

---

## Win 4 — Faster tunnel-restart backoff (backend)

**Cost today:** `_TUNNEL_RESTART_BACKOFF = (3.0, 6.0, 12.0)` (`backend/api/device.py:740`); `services/wifi_tunnel_service.py:run_watchdog` sleeps `delay` BEFORE each restart attempt — so a transient drop waits a full 3s before the first retry, a major contributor to the ~27s reconnect window.

**Change:** `_TUNNEL_RESTART_BACKOFF = (0.5, 2.0, 5.0, 10.0)` — first retry near-instant (most drops are transient and recover immediately), 4 attempts for resilience.

**⚠️ Coupled test update (same commit):** Cluster-2 enriched the `tunnel_degraded` WS payload with `attempt` / `max_attempts` / `next_delay_s` derived from this backoff (`max_attempts = len(backoff)`, `next_delay_s = backoff[0]`). Changing the tuple changes those values (`next_delay_s` 3.0→0.5, `max_attempts` 3→4), so these three characterization tests MUST be updated in the same commit:
- `backend/tests/test_watchdog_tunnel_lost_reason_char.py` (the two `tunnel_degraded` deep-equals)
- `backend/tests/test_wifi_tunnel_service_watchdog_char.py` (the two `tunnel_degraded` deep-equals)
- `backend/tests/test_wifi_tunnel_degraded_attempt_char.py` (the dedicated attempt/max/next_delay assertions)
The `tunnel_lost` assertions in those files stay unchanged.

**Files:** `backend/api/device.py` (the constant) + the three test files above.

**Tests:** the three char-tests updated to the new values; a focused assertion that `next_delay_s == 0.5` and `max_attempts == 4` in the first `tunnel_degraded` emit.

---

## Execution Structure

- **One spec → one implementation plan → one cluster branch** (`boot-reconnect-latency`), subagent-driven (per-task implementer + adversarial reviewer; opus for the danger-zone lifespan/device-manager tasks), per-cluster whole-branch review → ff-merge to `main`.
- **Order (each independently mergeable, suite green between):** Win 4 (backoff + char-test updates — self-contained, no deferral risk) → Win 1 (geo enrich deferral) → Win 2 (device-connect deferral) → Win 3 (frontend WiFi reorder). Win 1+2 both edit the lifespan; sequence them so each leaves the suite green.

---

## Out of Scope (deferred perf items, from the audit — not this cluster)

The bigger / needs-profiling wins: the CRDT store-write fast-path (`json_store.save` re-parse+merge skip when mtime unchanged) + watcher/backup/tombstone follow-ons; the Library-panel memoization (`BookmarkRow`/`CategorySection`/`bookmarksByCategory`); the IPython/prompt_toolkit lazy-import boot trim; the engine `interpolate` streaming-generator; the RSD-retry flattening / `find_port` early-exit / DDI-check fire-and-forget connect-latency wins. These are tracked in the perf audit output for a later pass.

---

## Self-review checklist

- [x] Placeholder scan — no TBD/vague requirements.
- [x] Internal consistency — the 4 wins + ordering coherent; behavior-preserved invariant stated.
- [x] Scope — one mergeable cluster; not over-large.
- [x] Ambiguity — backoff value decided `(0.5, 2.0, 5.0, 10.0)`; deferral mechanism = spawn-as-task (not watchdog-adoption); load-vs-enrich boundary explicit.
- [x] **Code claims verified against the real repo** (2026-06-26): `load_state` (main.py:173) holds the sync `enrich_all()` at :184 (store load precedes it → deferrable via `asyncio.to_thread`); device connect awaited at main.py:919-924, `yield` at :960; `_usbmux_presence_watchdog` already adopts devices via `create_engine_for_device` (:772). `_TUNNEL_RESTART_BACKOFF = (3.0, 6.0, 12.0)` at api/device.py:740 (used :794); all 3 char-test files exist + assert the payload. `useWifiAutoConnect.ts`: thrash-guard `connectedDevicesRef` (:63-64) + early-bail (:110) precede the `await wifiTunnelDiscover()` (:137) → savedips `startWifiTunnel` (:154), so Win 3 reorders within the not-yet-connected path while keeping the guard.
