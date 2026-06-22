# Clean Architecture Refactor — Design Spec

- **Date:** 2026-06-19
- **Status:** Phase 0 + Phase 1 + Phase 2 (C / spec-literal) merged (2026-06-20). **Phase 3 (movement-math carve-out) IMPLEMENTED on branch `chore/clean-arch-p3` (2026-06-22), pending hardware smoke + merge.** Phases 4–5 deferred.
- **Decision (flavor):** **Pragmatic Hexagonal-lite** — real clean architecture (inward-only rings, inner-owned ports, repository, composition-root DI, CI-enforced layering) **without** per-verb interactor classes, numbered `l1–l4` folders, or a presenter layer (`response_model` already serves that role).
- **Decision (scope):** **MVP first — Phase 0 + Phase 1 + the Phase-1 cycle gate.** Phases 2–5 are documented here but **deferred** (adopt/partial/skip later). The 4 lock/port corrections ride along with the MVP.
- **Reference studied:** `CJHwong/py-clean-architecture-examples` (`example_2_fastapi_todo_app`).
- **Source analysis:** two parallel agent workflows — a 12-agent codebase scan and an 11-agent design + adversarial-risk pass.

> **Constraint reminder:** No external behavior / HTTP / WS / IPC API change. The full backend pytest suite stays green after **every** commit — the design scan's "352" counted test *functions*; this checkout actually collects **≈371 items** (`pytest --collect-only -q`), so pin the exact pre-change baseline and treat every "352" below as shorthand for it. WS payloads compared **deep-equal JSON** (not literal bytes). One explicit, documented exception: the `device_manager.py:1155` NameError fix (a dead retry path becomes live).

---

## 1. Why (chosen over strict L1–L4)

A 3-architect judge panel scored strict L1–L4 lowest (36) and Pragmatic Hexagonal-lite highest (48), on a value function of fit + bounded-risk + behavior-preservation + testability + effort + **solo-dev maintainability**. For a single developer driving real hardware (`pymobiledevice3` / `usbmuxd` / SIP / tunnel-helper), per-verb interactor classes + numbered folders multiply file count 3–4× for substitutability we will never use ("we never swap out the iPhone"). We keep the principled spine (dependency inversion at the boundaries that actually hurt) and drop the ceremony.

---

## 2. Pain points (weighted, highest first)

1. **Coupling / cycle / inverted dependency.** `api/device.py (1623) ⟲ core/device_manager.py (1296)` is **SIX** `core→api` edges, not four (verified `grep 'from api\.' backend/core/device_manager.py`): 4 lazy `from api.websocket import broadcast` (708/720/772/786) **plus** `from api.device import _tunnels` (1135) and `from api.device import _tunnels, _attempt_tunnel_restart` (1200). The latter two reach the live WiFi-tunnel runner registry on the **untested reconnect path** — the load-bearing half. Plus 34 `from main import app_state` service-locator imports.
2. **Silent side-effects.** 4 broadcast back-edges emit untyped dicts; the engine emits ~27 more open-ended type strings via a generic callback (`main.py:351`); `device_disconnected` has **6 deliberately divergent payload shapes** the frontend branches on. `config.py` runs `DATA_DIR.mkdir()` at **import time**; `services/geocoding.py` raises `fastapi.HTTPException` from inside a service (54/110/121).
3. **Fear of breaking the untested engine.** `core/simulation_engine.py (923 LOC, ZERO tests)`; `resume_from_snapshot` dispatches via `getattr(self, kind, None)` and **warns-and-returns** on a miss (silent no-op).
4. **God-files / merge conflicts.** Backend: device.py/device_manager/main.py/simulation_engine. Frontend: `MapView.tsx (2867)`, `App.tsx (2685)`, `BookmarkList.tsx (2109)` — and the frontend has **zero test infra** (verified: no vitest/jsdom/testing-library/msw in `package.json`).

Additional verified issues folded in: `BookmarkManager.store` cross-thread race (Timer `_watcher_tick` vs loop `_save`, no lock); untyped WS over a **multi-subscriber** fan-out; port `8777` hardcoded in 3 frontend files + `config.py`.

---

## 3. Goals

- Break the cycle **structurally** via three inner-owned ports — `DevicePort`, `EventPublisher`, `TunnelRegistry` — wired at a composition root (covers all 6 edges, incl. live WiFi-tunnel state).
- Retire all 34 `from main import app_state` imports in favor of constructor-injection DI exposed through FastAPI `Depends`, with `AppState` **reframed** (not rewritten) as a container on `app.state` — without breaking the lock-free shared-state invariants.
- Make silent side-effects explicit: an **OPEN** typed WS event union with **optional** fields serialized `exclude_unset` (one source of truth, mirrored to TS) preserving the 6 divergent shapes verbatim; domain errors instead of `HTTPException` in services; explicit lifespan dir-init replacing import-time `mkdir`.
- Net the zero-test engine with characterization tests driven by an injected `ClockPort` + stepped `asyncio.sleep` **before** any move; then extract **only** the pure movement math (ETA, interpolation, snapshot serialization) into unit-testable `domain/movement.py` — keeping dispatch entrypoints and stop/pause/cancel ordering **on** the engine.
- Bootstrap Vitest **first and alone** (Phase 0a) before any frontend god-component and before the security folds; route the 7 direct-`api` components through hooks behind an `ApiGateway` / `WsRouter` port that **preserves** the multi-subscriber fan-out; collapse hardcoded `8777` to one constant.
- Land the bug/security folds as independent, individually-revertable commits each with its own regression test, in Phase 0.
- Enforce layering in CI (import-linter as a pytest, eslint `no-restricted-paths`) — shipped **report-only** in Phase 0, flipped to **enforced** at each establishing phase's exit (not a single Phase-5 capstone).

---

## 4. Target architecture (Pragmatic Hexagonal-lite)

### 4.1 Backend rings (dependencies point inward only)

```
backend/
  bootstrap/   composition root — ONLY ring allowed to import every other ring
    app.py       FastAPI app factory + lifespan (lifted from main.py); CORS allowlist (incl LAN origin) + CSP middleware
    container.py AppState reframed as DI container: builds DeviceManager(event_publisher, tunnel_registry),
                 SimulationEngine(device_port, events, clock, sleep), repos, geocoder, MonotonicClock; owns _engines_lock;
                 SYNCHRONOUS providers only (no awaited construction in a request critical section)
    settings.py  from config.py: Settings dataclass; HOST(LAN-reachable)/PORT/CORS/CSP/TIMEZONEDB_API_KEY/paths;
                 ensure_dirs() called from lifespan BEFORE any manager/Observer
  domain/      innermost: pure types + ports. Imports stdlib + pydantic ONLY
    models/      per-aggregate pure pydantic (unchanged)
    events.py    WsEvent: OPEN discriminated union, OPTIONAL fields, exclude_unset/exclude_none (preserves 6 disconnect shapes)
    movement.py  PURE math from simulation_engine: EtaTracker, RouteInterpolator (relocated from services/), snapshot dict serializer (build_resume_snapshot) only — NO dataclass exists
    errors.py    GeocodeError(status,code,detail), DeviceConnectError — domain errors, NOT HTTPException
    ports/       device_port, event_publisher, tunnel_registry, bookmark_repo, route_repo, geocoder, clock
  core/        engine orchestration (depends on domain/ports only) + movers; getattr-dispatch RAISES on miss
  services/    use-cases: device_service/location/bookmark/route/geocoding/cloud_sync/recent/cooldown; raise domain errors
  infra/       hardware/OS-edge adapters implementing ports. NO infra->api edge
    device/      device_manager (impl DevicePort), wifi_tunnel (impl TunnelRegistry, OWNS _tunnels + _tunnels_lock),
                 _tunnel_runner, usbmux_pair_records, tunnel_helper_client, reconnect  (SIP/tunnel carve-out)
    geo/         geo_offline, geo_extras (reads TIMEZONEDB_API_KEY from Settings)
    persistence/ json_store: concrete Bookmark/Route repository over CRDT store; cross-thread store lock
    events/      ws_event_publisher (impl EventPublisher -> WS manager; only emitter)
  api/         thin routers; Depends() not 'from main import app_state'; api/* may NOT import another api/*
  main.py      ~10-line entrypoint: build settings, bootstrap.app.create_app(), uvicorn.run(host from Settings)
```

### 4.2 Frontend hexagon-lite

```
frontend/src/
  contract/   cross-stack truth: http.ts, wsEvents.ts (mirrors backend domain/events.py, OPEN+optional),
              endpoints.ts (ONE origin constant — kills 3x hardcoded 8777; loopback desktop, LAN phone.html)
  domain/     pure TS (utils/* + s2grid moved here) — first Vitest beachhead (Phase 0a)
  ports/      ApiGateway, WsRouter (PRESERVES N-handlers-per-type fan-out + per-handler try/catch)
  adapters/   api/gateway (single typed gateway, only baseUrl site), ws/router (typed dispatch), config (single origin source)
  hooks/      use-case layer; components NEVER import adapters/api directly; add useRoutes/useCloudSync/useGeocode
  contexts/   ServicesContext (DI: provides ApiGateway + WsRouter; tests inject fakes)
  features/   god-components decomposed by feature (map/bookmarks/devices/...); App.tsx + MapView split LAST
  app/        App.tsx (providers + layout shell only; split LAST), main.tsx
  test/       Vitest + jsdom + @testing-library + msw setup (Phase 0a STEP 1, FIRST and ALONE)
  electron/   main.js/preload.js — system-edge carve-out; osascript escaped at the AppleScript-string layer
```

### 4.3 Layer rules (CI-enforced — the "353rd test")

Backend (import-linter contracts as pytest; report-only in P0, flipped to enforced at each phase exit):
- `domain/` imports stdlib + pydantic ONLY — never fastapi, asyncio I/O, httpx, pymobiledevice3, core/services/api/bootstrap.
- `core/` imports `domain/` only; may depend on ports, never on infra impls / services / api / main.
- `services/` imports `core/` + `domain/ports`; raises domain errors, **never** `fastapi.HTTPException`.
- `infra/` + `api/` (outermost) may import inward freely; implement the ports. **`api/*` may not import another `api/*`** (kills future router→router cycles). **`infra/*` may not import `api/*`** (this is why `_tunnels` must become a `TunnelRegistry` port owned by infra, not a carried-along `from api.device import _tunnels`).
- `bootstrap/` is the sole ring allowed to import every other ring. `main.py` imports `bootstrap` only.
- Encoded bans: (a) no fastapi under domain/core/services; (b) no infra/pymobiledevice3 under core/services; (c) only `bootstrap/` + `main.py` read Settings/env; (d) **no `core→api` edge — forbidding the WHOLE api package** (validated by `grep 'from api\.'` under core == 0, not just the broadcast string); (e) no `infra→api` edge.

Frontend (eslint `import/no-restricted-paths`):
- `domain/` + `contract/` pure (no React, no fetch); `contract/` is leaf-most.
- `hooks/` import `domain/` + `contract/` + `ports/` interfaces only; concrete gateway/wsRouter injected via `ServicesContext`.
- `features/` + `app/` (view) may not import `adapters/api` or `services/api` — eslint fails the bypass.
- Only `adapters/config.ts` + `contract/endpoints.ts` know the backend origin. **`WsRouter` MUST preserve** today's `useWebSocket` Set/forEach multi-subscriber broadcast + per-handler try/catch — it is **not** route-by-type-to-single-owner.

### 4.4 The three load-bearing inversions + repository + DI

- **engine → `DevicePort`** (gets infra `device_manager` injected). Severs the engine↔manager edge.
- **device_manager → `EventPublisher`** (gets the api WS publisher injected). Replaces the 4 `broadcast` back-edges. `publish()` is **awaited, in-line, order-preserving** (no background queue) so emission order and interleave with state mutation stay deep-equal-identical. Audit every publish site for `device_manager._lock` held at call time to avoid a **new** lock-ordering inversion.
- **device_manager → `TunnelRegistry`** (gets infra `wifi_tunnel` injected, owning `_tunnels` + `_tunnels_lock`). Replaces `from api.device import _tunnels` / `_attempt_tunnel_restart`. The read path in `get_fresh_dvt_provider` / `full_reconnect` must **snapshot under `_tunnels_lock`** (closes the check-then-use race vs a concurrent restart-swap).
- **Repository:** `BookmarkRepository` / `RouteRepository` Protocols in `domain/ports`; LWW-element-set + tombstone + `merge_stores` move into `infra/persistence/json_store.py` (merge math relocated **verbatim**, pinned by the 43 SAFE tests). Adds `force_seed(items)` that stamps `updated_at = now()` — encoding the documented "empty `updated_at` always loses to a real-timestamp tombstone" pitfall into the **type contract**.
- **DI:** one container on `app.state`, plain constructor injection, `Depends` providers in `api/deps.py`. **All providers stay synchronous** container lookups (no awaited construction in a request critical section). Add `app_state._engines_lock` around `create_engine_for_device`'s `check→await→assign` and the watchdog `pop+promote`. `test_lifespan` asserts **start-order** (dirs first, watchdog last).

---

## 5. Phase plan

> **MVP = Phase 0 + Phase 1 + the Phase-1 cycle gate.** Phases 2–5 are **deferred** (documented for continuity). The 4 lock/port corrections (store lock, engine-registry lock, `TunnelRegistry` port, in-line ordering-preserving `EventPublisher`) ride along with the MVP.

Each phase: **執行目標 / 優先順序(first) / 潛在風險 / 驗證方式**. Backend and frontend advance in parallel within a phase.

### Phase 0 — Safety-net bootstrap (0a) then independent fold commits (0b) — **MVP** — ~13 commits

- **執行目標:** stand up BOTH safety nets before any fold; land the 7 bug/security folds as separate, individually-revertable commits each with a regression test; ship import-linter **report-only**.
- **優先順序(first):** **0a-STEP 1 (frontend, alone):** bootstrap `frontend/src/test` (Vitest+jsdom+@testing-library+msw) and pin the 6 pure beachhead utils green — must not be bundled with the thrashy folds. **STEP 2 (backend, alone):** inject a minimal clock/sleep seam into `SimulationEngine` (callable defaulting to `time.monotonic` + sleep defaulting to `asyncio.sleep`, **no logic change**), pinned by an e2e teleport/navigate endpoint test asserting the default path is identical. **STEP 3:** record char nets through the fake clock for the **named** branches — engine position/ETA/pause-resume/goldditto streams as **ordered exact tuples**; `capture→resume_from_snapshot` for ALL FOUR kinds + a 2-device mid-sim disconnect promotion; device_manager connect/discover/forget; the `get_fresh_dvt_provider` WiFi-tunnel-wait branch and DvtProvider-open-retry branch (the 1155 site). **Only after the nets exist do the 0b folds land.**
- **潛在風險:** char tests may pin a current bug as "correct" → assert current **observable** behavior (the 1155 fold has no valid pre-fix baseline — a NameError crash — so its test pins **intended** retry semantics); CORS/CSP/bind folds can keep in-process tests green while breaking the real app (phone.html-over-LAN is easiest to break, hardest for pytest to see); the clock/sleep seam is itself a change to the zero-test engine made before the net exists — e2e-pin the default path first.
- **驗證方式:** 352 green after EACH fold; Vitest green with 6 beachhead utils; clock-seam e2e endpoint test confirms default path identical; all named char nets green and verified **deterministic** (record twice, diff); per-fold regression test green; import-linter printing violations in report-only (exit 0); manual packaged-Electron + real-phone-over-WiFi-under-PIN smoke.

### Phase 1 — Break the 6-edge cycle via THREE ports (backend) / centralized typed WS dispatch (frontend) — **MVP** — ~11 commits

- **執行目標:** invert ALL six `core→api` edges structurally via `DevicePort` + `EventPublisher` + `TunnelRegistry` + a composition root. Frontend: typed WS contract seam + a `WsRouter` that **preserves** the N-subscriber fan-out. Backend inversion and frontend WsRouter are **separate commits**.
- **優先順序(first):** **backend, own commit:** re-enumerate edges (`grep 'from api\.' device_manager.py` → 6). Define `domain/events.py` (OPEN union, optional, exclude_unset) + `domain/ports/event_publisher.py`; inject `EventPublisher` into `DeviceManager`, replacing the 4 broadcast calls — type ONLY those 4 device events; the engine's generic `(type,data)` callback stays an untyped passthrough. Stand up `api/websocket.py`'s `WsEventPublisher` (the only emitter), awaited + in-line + ordering-preserving.
- **潛在風險:** single highest-coupling change; tunnel + sticky_denied + autopair + `_attempt_tunnel_restart` are timing-sensitive (DANGER); `device_disconnected`'s 6 shapes must serialize with `exclude_unset` (pydantic must NOT inject defaults); all 4 `ddi_*` events' ordering + keys must be deep-equal; `EventPublisher` must be in-line/order-preserving; cannot be proven green by pytest alone (real Trust dialogs + tunnels live on the path).
- **驗證方式:** import-linter `no core→api` (whole api package) **enforced** green; `grep 'from api\.' device_manager.py` == 0; 352 green; migrated forget test captures from BOTH emit sinks and still asserts exactly one `device_disconnected` (reason='forgotten', remaining_count==1); WS payloads **deep-equal per emission site** vs P0 recordings (absent keys absent); frontend WsRouter Vitest proves one `device_disconnected` fires BOTH `useSimulation` AND `useDevice`; Playwright WS e2e green; **manual real-hardware smoke: connect + teleport over BOTH USB and WiFi; Trust dialog + tunnel-restart path observed.**

### Phase 2 — Kill service-locator + remove remaining silent side-effects + lock engine registry — **DONE (2026-06-20)** — ~8 commits

- **執行目標:** retire all 34 `from main import app_state`; remove `HTTPException`-from-service and import-time `mkdir`; add the `asyncio.Lock` guarding the engine registry's `check→await→assign`.
- **優先順序(first):** migrate `api/geocode` + `services/geocoding.py` — enumerate EVERY raise with exact `(status_code, detail)` incl. the 2 `raise_for_status` (httpx) paths; `GeocodeError` carries `(status, code, detail)` so the boundary mapper reproduces EACH verbatim; strengthen `test_geocode_api` to assert exact status+body per failure mode BEFORE the move.
- **潛在風險:** hidden ordering deps in app_state; `mkdir`-at-import removal can surface a path nothing creates on a clean machine (pristine-HOME CI pins it); geocoding error-shape must stay identical per branch; engine-registry lock must wrap the FULL check-await-assign; per-component reroute must not change WHEN calls fire or swallow errors differently (msw behavioral test per component).
- **驗證方式:** `grep 'from main import app_state'` == 0 in non-test code; 352 green; geocode tests assert identical status+body per branch (incl httpx); lifespan + pristine-HOME tests; two-concurrent-`create_engine_for_device` regression green; eslint 0 view→adapters/api violations among rerouted components.

### Phase 3 — Carve simulation_engine into pure domain math (fear zone, now netted) — **DONE (2026-06-22, branch chore/clean-arch-p3)** — 7 commits

> **DONE note (2026-06-22):** Implemented as 7 commits on `chore/clean-arch-p3` (3 char nets + 3 extractions + the `no-domain-imports-outer` gate). EtaTracker + `build_resume_snapshot` (a pure dict serializer — **no dataclass ever existed**, so the "dict↔dataclass converter" phrasing below is superseded by the freeze) + RouteInterpolator now live in `backend/domain/movement.py`; RouteInterpolator was *relocated from `services/`* (the interpolation math was never inline in `_move_along_route`), which killed the `core→services` interpolator edge. `engine.py` already depended on `DevicePort` (done in P1). Owner decisions: `resume_from_snapshot` kept **warn-and-return** on unknown kind (behavior-freeze over the literal "RAISES on miss"); the `RouteService` `core→services` edge **deferred** (separate ring fix). Both verbatim moves verified byte-identical; backend 849→871 (new char tests only, no existing test changed); **6 import-linter contracts kept / 0 broken**. Pending: Ravi hardware smoke + merge.

- **執行目標:** extract ONLY the pure movement math (ETA, interpolation, snapshot dict↔dataclass converter) into `domain/movement.py`; make `engine.py` depend on `DevicePort`. Keep navigate/start_loop/multi_stop/random_walk entrypoints + all stop/pause/cancel signalling + ordering ON the engine.
- **優先順序(first):** extract `EtaTracker` first (most self-contained, re-export from old module), THEN `_move_along_route` interpolation, THEN the snapshot converter — **one extraction per commit**, each guarded by P0 recordings; float interpolation extracted LAST, asserted bit-exact. Grep the to-be-extracted functions for device_manager/api imports first — if found, the extraction is not mechanical and must be re-scoped.
- **潛在風險:** highest fear factor, zero original tests (mitigated by P0 nets incl. resume-dispatch all 4 kinds + 2-device promotion); snapshot (de)serialization entangled with running-loop mutable state — extract ONLY the pure converter, round-trip correctness pinned by the e2e P0 recording not a serializer unit round-trip; the watchdog-handoff stop/pause/cancel ordering must NOT be reordered (keep a separate non-fixed-clock concurrency char-test).
- **驗證方式:** P0 char recordings green before AND after each extraction; `resume_from_snapshot` RAISES on missing method; new unit tests on `domain/movement.py`; 352 + new green; non-fixed-clock watchdog-handoff char-test (no `position_update` after DISCONNECTED).

### Phase 4 — Repository around the CRDT store + frontend god-component decomposition — **deferred** — ~10 commits

- **執行目標:** encode the empty-`updated_at` tombstone pitfall in the repository contract and move merge into infra (cross-thread store lock already landed in P0). Decompose the 3 frontend god-components; split `App.tsx` / `MapView` LAST.
- **優先順序(first):** backend — define repo Protocols, move `store_merge` + json persistence to `infra/persistence/json_store.py` with an explicit `force_seed(items)` stamping `updated_at = now()` (closes the documented "catalog re-import killed by a pre-existing tombstone" bug); frontend — split `BookmarkList.tsx` FIRST (most extractable, SAFE backend behind it), then `MapView`, then `App.tsx` LAST. Adopt the fallback proactively: if schedule slips, split BookmarkList + MapView and **leave App.tsx**.
- **潛在風險:** CRDT merge regression on import (covered by SAFE CRDT tests + the force_seed regression); frontend zero baseline (Vitest per extracted unit + Playwright smoke); effect/subscription ordering in MapView/App is load-bearing and impure (Playwright covers what unit tests cannot).
- **驗證方式:** 43 SAFE bookmark + CRDT/tombstone/catalog tests green; catalog re-import-over-tombstone regression green; 352 total green; import-linter no-fastapi-under-services/infra enforced; Vitest per extracted unit; Playwright smoke (map+bookmark CRUD+connect+sim+remount+disconnect-during-sim).

### Phase 5 — Prove the architecture gates fail-on-probe + shared-constant cleanup — **deferred** — ~4 commits

- **執行目標:** since each contract was flipped to enforced at its establishing phase's exit, prove every gate actually **fails on an intentional probe** (not just passes trivially) and collapse the last port/origin literals to a single source.
- **優先順序(first):** prove import-linter FAILS on an intentionally-introduced cross-layer import (a `from api.device import x` under core, and a fastapi import under services), then revert the probe.
- **潛在風險:** boundary rules may flag legitimate carve-outs (Electron, usbmux, osascript, TunnelRegistry impl) — add narrow **documented** allow-exceptions, do not weaken globally; collapsing the origin constant must not break Electron preload-injected origin vs Vite-dev fallback nor the phone.html LAN origin.
- **驗證方式:** CI fails on the cross-layer probes (both directions) then reverts; `grep 8777` returns only the single constant; full 352 + Vitest green; packaged-app smoke.

---

## 6. Folded fixes (Phase 0b — independent, individually-revertable commits)

1. **`device_manager.py:1155` LIVE NameError** — `remaining = deadline - loop.time()` references `loop`, never bound in `get_fresh_dvt_provider` (deadline at 1115 uses `time.monotonic()`). The except-handler raises NameError on the first DvtProvider-open failure, masking the original error and killing the retry-with-backoff (1156–1164) — **the USB DvtProvider-retry path is dead-on-first-failure today.** Fix: `loop.time()` → `time.monotonic()`. **Behavior delta** (dead path → live retry). Regression test injects a DvtProvider raising on attempt 1, succeeding on attempt 2: asserts no NameError, retry re-loops, and on permanent failure `DeviceLostError(REASON_LOCKDOWN_DEAD)` at the right elapsed time via a fake clock. Land AFTER the surrounding char nets. Real-hardware USB-unplug-during-DVT smoke. Commit message states the USB-fallback retry was previously dead.
2. **`geo_extras.py:31` hardcoded `TIMEZONEDB_KEY`** — read from Settings env (`TIMEZONEDB_API_KEY`); literal removed; test asserts graceful no-key path. **Leaked key rotated out-of-band.**
3. **`main.py:952-953` CORS `'*'` + `allow_credentials=True`** — explicit allowlist from Settings incl. the LAN origin phone.html uses; packaged-app + real-phone smoke (in-process pytest doesn't exercise Origin headers).
4. **`config.py:185` `0.0.0.0` bind** — **REVISED:** phone.html is served to a physical phone over the LAN, so loopback would **break** phone-control. Keep LAN-reachable bind; close exposure with the existing 6-digit PIN/token gate + CORS allowlist. (A stricter default, if wanted, is an explicit opt-in env, never a silent loopback default.)
5. **No CSP** — add CSP response-header middleware AND externalize the `index.html` inline boot-splash script (or per-load nonce); looser dev CSP (Vite HMR) vs strict packaged CSP. Playwright/Electron smoke confirms splash hides + React paints under the policy (header-presence unit test alone would pass while the renderer is broken).
6. **`electron/main.js:332` osascript string-interp** — injection surface is the **AppleScript string literal** (`do shell script` takes one string, not argv). Escape for AppleScript context, or pass args via temp file/env to a fixed wrapper; preserve SIP-exempt `with administrator privileges`. Test asserts a path with a literal double-quote cannot break out. Land LAST; real packaged-app elevation smoke.
7. **`BookmarkManager.store` cross-thread race** — `_watcher_tick` (Timer daemon thread) and `_save` (event-loop coroutines) mutate `store` with no lock; the read-disk→merge→write sequence isn't atomic against a Timer interleave. Add a `threading.Lock` around every `store` read-modify-write in BOTH, or marshal `_watcher_tick` onto the loop via `loop.call_soon_threadsafe`. Concurrency regression test fires `_watcher_tick` from a real second thread during a `_save` and asserts no item lost. Forbid any future infra async wrapper from changing the watcher's thread-affinity without re-proving atomicity.

---

## 7. Hard corrections from the adversarial review (worth keeping in mind)

1. The cycle is **6 edges, not 4** — a `grep broadcast == 0` greens a still-cyclic graph; the `TunnelRegistry` port must invert `_tunnels` too.
2. `device_manager.py:1155` is a **LIVE NameError**, not a clock-origin mismatch — the fix is a documented behavior delta; its test pins intended (not pre-fix) semantics.
3. The `0.0.0.0` bind **must stay LAN-reachable** — phone.html runs on a real phone over WiFi; gate with PIN + CORS, not loopback.
4. The WS layer is a **multi-subscriber fan-out** — `device_*` is dual-handled in `useSimulation` AND `useDevice` plus two inline App.tsx subscribers; route-to-single-owner would silently drop a handler.
5. Honest MVP = **P0 + P1 + the P1 cycle gate**; P2–P4 are the full payload and can be deferred — the cycle inversion and security folds pay for themselves regardless.

---

## 8. Rollback & verification gates

- Every phase ships small commits keeping 352 tests green individually; `git revert <sha>` of any single commit is safe.
- The 7 folds are independent, individually-revertable.
- Phase 0a (Vitest + clock seam) lands first and alone — safety nets exist before any fold and are never co-reverted with one.
- Extract-and-re-export (Phases 1, 3): the old module re-exports from the new `domain/` location, so callers keep working; a bad move is reverted while the shim keeps the old path alive.
- Phase 1 splits into a backend-inversion commit and a separate frontend-WsRouter commit (cross-stack WS regressions are bisectable). The riskiest commit (backend cycle inversion) is gated behind **real-hardware USB+WiFi + tunnel-restart smoke** before it is done; if the live path regresses, revert the port-injection commit and the lazy imports return (cyclic but working).
- import-linter ships report-only in P0; each contract flips to enforced at its establishing phase's exit (no single Phase-5 capstone), so a gate never blocks an in-flight intermediate state.
- Personal repo: direct commits to main; `--force-with-lease` permitted for amending a not-yet-pushed commit; git identity auto-set by `~/.gitconfig` includeIf (never pass `-c user.email`).

---

## 9. Next step

After spec review approval: invoke the writing-plans skill to turn **Phase 0 + Phase 1** (the MVP) into a detailed, ordered implementation plan with per-commit tasks and TDD checkpoints. Phases 2–5 remain documented here for when/if they're picked up.
