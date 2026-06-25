# App Improvement Program — Design Spec

> **Status:** Design (awaiting Ravi's review) — 2026-06-25
> **Author:** Claude (Opus 4.8, 1M) + Ravi
> **Predecessor:** the Stability Hardening Program (SH0–SH4, merged 2026-06-24) hardened LocWarp to "won't break." This program targets the *next* leverage: daily-use friction and already-built-but-unwired capability — **not** stability.

**Goal:** Ship four small, independently-verifiable improvement clusters that remove the highest-frequency daily friction and wire up capability the codebase already contains, without regressing the green test baseline.

**Architecture:** Each cluster is a self-contained change set that fits the existing Pragmatic-Hexagonal-lite rings (backend `bootstrap → api+infra → services → core → domain`; frontend `view → hooks → ports ← adapters`). No new subsystems; every change either reuses an existing handler/seam or adds one narrow, additive surface. Clusters are sequenced so each ends with a working, mergeable deliverable.

**Tech stack:** FastAPI/Python backend, React 18 + TypeScript + Electron frontend, Vitest + pytest, import-linter + dependency-cruiser CI gates.

---

## Global Constraints

Copied verbatim into every cluster plan; every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` + frontend `vitest` + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit. Pin the exact baselines before starting:
  - Backend: `cd backend && .venv/bin/python -m pytest --collect-only -q` (expected ≈949 collected).
  - Frontend: `cd frontend && npx vitest run` (expected ≈773) + `npx tsc --noEmit` (0 errors) + `npx depcruise` (0/0).
- **Danger-zone-test-first.** `simulation_engine.py`, all movers, `api/location.py`, `device_manager` recovery, `phone_control.py` have NO direct tests. Write characterization tests (injected `ClockPort` + stepped `asyncio.sleep`, ordered exact-tuple assertions, REAL collaborators — never stub the method under test) BEFORE touching them.
- **WS payload discipline.** New/changed WS payloads are compared deep-equal JSON, serialized `exclude_unset`/`exclude_none` so absent keys stay absent. Adding keys to an existing event must be backward-compatible (existing consumers must not break).
- **One documented behavior change.** Speed jitter (Cluster 3) changes the per-tick speed of all existing modes. It is gated behind a settings toggle that defaults ON. This is the ONLY intentional behavior change in the program; characterization tests run with jitter OFF to keep exact-tuple assertions stable.
- **Hexagon boundaries hold.** `domain/` stays pure; `services/` raise domain errors not `HTTPException`; view never imports `adapters/api` / `services/api` directly; the `device_manager → EventPublisher` inversion stays **awaited, in-line, order-preserving** — NEVER acquire the WS connection-manager lock while `device_manager._lock` is held.
- **Survey before adding surface.** Each new endpoint/event below states reuse-vs-new with its justification (done in this spec).
- **Personal-repo conventions.** Direct commits to `main`; git identity auto-set by includeIf (never pass `-c user.email=`); no PR ceremony.

---

## Execution Structure

- **One master spec** (this file) **+ four cluster implementation plans** under `docs/superpowers/plans/2026-06-25-aip-c{1..4}-*.md`.
- **Subagent-driven development** (per-task implementer + adversarial reviewer + per-cluster whole-branch review), branch + ff-merge per cluster.
- **Order:** C1 (pure frontend, fastest felt) → C2 (frontend + thin backend fields) → C3 (front+back capability) → C4 (build/CI, decoupled from runtime, last). Each cluster is independently mergeable; a later cluster never blocks an earlier merge.

---

## Surface Decisions (reuse vs new) — survey conclusions

Enumerated 2026-06-25 against `backend/api/*.py` + `backend/main.py` + `domain/events.py`.

| Need | Decision | Justification |
|------|----------|---------------|
| Address-search keyboard nav, global shortcuts, Undo | **No backend surface** | Pure frontend; consume existing `useSimActions` handlers, add `isTypingTarget` to `utils/keyboard.ts`, add a universal teleport snapshot. |
| Reconnecting attempt + countdown | **Extend** `tunnel_degraded` payload | Event already published from `services/wifi_tunnel_service.py:161`; `run_watchdog` already has `attempt`/`delay` — additive keys, backward-compatible. |
| `tunnel_lost` one-click Reconnect | **No surface** | `tunnel_lost` already carries `udid` (`wifi_tunnel_service.py:255`); frontend reuses `savedips` + `startWifiTunnel`. |
| Connect progress (RSD/DDI/DVT phases) | **New** WS event `connect_progress` | No existing event covers the in-progress connect path; `domain/events.py` only has `ddi_*`. |
| Nearby POIs | **New** `GET /api/geocode/nearby` | `services/geo_extras.py:176 nearby_pois` has ZERO callers; `api/geocode.py` has no POI route. |
| GPX timing-aware replay | **Extend** `POST /route/gpx/import` | Route exists (`api/route.py:142`); change is parse-time behavior, no new route. |
| Speed jitter | **No surface** | Engine + `config.py` SpeedProfile only. |
| System health / silent latches | **New** `GET /api/system/info` | `api/system.py` has only open-log/open-log-folder/shutdown; `GET /` returns only version + initial_position. |

---

## Cluster 1 — Keyboard Reflexes (frontend only)

**What ships**
1. **Address-search keyboard nav.** `AddressSearch.tsx` results list gains `selectedIndex` state; ArrowUp/ArrowDown move the highlight (wrap or clamp — clamp, simpler); Enter commits the highlighted row through the existing `isSubmitEnter` IME guard; row 0 is highlighted by default so a bare Enter flies to the top result.
2. **App-level keyboard shortcuts** (a single document `keydown` listener, mounted in `App.tsx`, scope = **app window only**, NO Electron `globalShortcut`):
   - `Space` → stop, `R` → restore, `P` → pause/resume toggle, `B` → bookmark-here, `Cmd/Ctrl+K` → focus address search.
   - These map to existing stable handlers, but note where they live: `handleStop`/`handleRestore`/`handlePause`/`handleResume` are defined in `hooks/useSimActions.ts` as `[]`-dep `useCallback`s (stable via refs) and destructured into `App.tsx` (wired as props `onStop`/`onPause`/`onResume`/`onRestore` at `App.tsx:1183-1186`); only `handleAddBookmark` is defined in `App.tsx` itself (`useCallback`, wired at `App.tsx:1470`). The new listener consumes these same callbacks.
   - `utils/keyboard.ts` today centralizes ONLY the IME-safe Enter guard (`isImeComposing` / `isSubmitEnter`); it has **no** INPUT/TEXTAREA/contentEditable ignore guard yet. This cluster **adds** a new `isTypingTarget(e)` helper there (checks `tagName` INPUT/TEXTAREA + `isContentEditable`) and the global listener uses it so shortcuts NEVER fire while typing.
3. **Undo (`Cmd/Ctrl+Z`)** flies back to the previous position. ⚠️ `handleTeleport` lives in `hooks/useSimActions.ts` (not `App.tsx`) and only snapshots `prevPos = sim.currentPosition` inside the `udids.length >= 2` dual-device revert branch — the single-device path does NOT snapshot. So Undo **cannot reuse an existing universal snapshot**; this cluster **adds** a `lastPosition` snapshot captured before EVERY teleport (both single- and multi-device paths) and exposes an Undo affordance on the teleport toast + the keybinding. **Single level** (last position only — YAGNI, no stack).

**Why app-level only:** LocWarp runs on the Mac and controls the iPhone's GPS; the target app the user plays is on the *phone*, where `phone_control.py` / `phone.html` already provides stop/pause over LAN. A system-wide Mac hotkey would only add value for "user is at the Mac but in another app" — narrower than the phone case already covers, and it adds hotkey-collision + enable/disable complexity. Deferred; can be added later without rework.

**Files:** `frontend/src/components/AddressSearch.tsx`, `frontend/src/App.tsx`, `frontend/src/hooks/useSimActions.ts` (add the universal `lastPosition` snapshot in `handleTeleport`), `frontend/src/utils/keyboard.ts` (add `isTypingTarget`), new `frontend/src/hooks/useGlobalShortcuts.ts` (the single listener, testable in isolation).

**Error handling:** shortcuts are no-ops when their precondition is absent (e.g. `R`/restore with no prior position); never throw. Undo with no `lastPosition` is a silent no-op.

**Tests (Vitest, fireEvent only — `@testing-library/user-event` is NOT installed):**
- IME composition active → Enter does NOT submit search.
- Focus inside an INPUT/TEXTAREA → `Space` does NOT stop.
- ArrowDown then Enter commits the second result, not the first.
- `useGlobalShortcuts` dispatches the correct handler per key; preconditions absent → no-op.
- Undo restores the snapshotted coordinate.

---

## Cluster 2 — Connection Feedback (frontend + thin backend fields)

**What ships**
1. **Reconnecting shows attempt + countdown.** Enrich the `tunnel_degraded` payload with `{attempt, max_attempts, next_delay_s}` from `run_watchdog` (which already iterates `enumerate(_restart_backoff, start=1)` and holds the delay — currently discarded). Frontend renders "Reconnecting… attempt 2/3, retrying in 6s" with a live countdown.
2. **`tunnel_lost` one-click Reconnect.** The `tunnel_lost` banner gains a Reconnect button that re-fires `startWifiTunnel` from the per-device `savedips` `{ip, port, udid}` — turning a six-step manual recovery (scroll to DeviceStatus → expand WiFi → re-run discover) into one click. Pure frontend.
3. **Connect progress stream.** New WS event `connect_progress` with a coarse phase enum: `opening_tunnel` → `rsd_attempt` (with `attempt`/`max`) → `checking_ddi` → `opening_dvt` → `connected`. Rendered in the existing `DeviceStatus.tsx` spinner region so a 15s connect is distinguishable from a hang. ⚠️ The connect path spans **two** methods, so emit points straddle both: the ~17s RSD-retry loop (`for attempt in range(1, 11)`, `sleep(min(0.5*attempt, 2.0))` = 17.0s) is in `core/device_manager.py:connect_wifi_tunnel`, but the **DDI check** (`_ensure_personalized_ddi_mounted`) and **DVT open** (`_create_dvt_location_service`) run AFTER `connect_wifi_tunnel` returns, reached via `create_engine_for_device` (`main.py` → `get_location_service` → `_create_dvt_location_service`). The API connect handler (`api/device.py`) calls `connect_wifi_tunnel` THEN `create_engine_for_device` as two steps — `connect_progress` emits go in both.

**Surface:** `connect_progress` MUST be added to the frontend WS typed union **before** the backend emits a typed subscriber. The compile gate is specifically `WS_EVENT_TYPES` / `WsEventType` in `frontend/src/contract/wsEvents.ts` (the raw `WsEvent` type is open, so events still *flow*; only a typed `subscribe()` to an unlisted literal fails `tsc`). Plan task ordering: (a) add the literal to `WS_EVENT_TYPES` + a no-op subscriber, (b) enrich `tunnel_degraded`, (c) emit `connect_progress`, (d) render. Each step keeps `tsc`/vitest green.

**Files:** `backend/services/wifi_tunnel_service.py` (enriched `tunnel_degraded`), `backend/core/device_manager.py` (RSD-loop emits in `connect_wifi_tunnel` + DDI/DVT emits in `_ensure_personalized_ddi_mounted` / `_create_dvt_location_service`), `backend/domain/events.py` (new event model), `backend/contract/wsEvents.ts`-equiv on the frontend (`frontend/src/contract/wsEvents.ts`), `frontend/src/components/DeviceStatus.tsx`, the tunnel-lost banner component, `frontend/src/hooks/useWifiAutoConnect.ts` / `useDevice.ts` as needed.

**Error handling & invariants:** new emits are **awaited in-line, order-preserving**; the connect path MUST NOT acquire the WS connection-manager lock while holding `device_manager._lock` (load-bearing inversion). Emit failures are caught + logged (mirror the existing `try/except` around `tunnel_degraded` at `wifi_tunnel_service.py:163`) and never abort the connect.

**Tests:**
- Backend char-test: the connect path emits `connect_progress` phases in the exact order, awaited in-line (assert ordered tuples; drive the REAL publisher, do not stub it).
- Backend: enriched `tunnel_degraded` payload deep-equals the expected shape incl. the three new keys (and absent-key discipline holds for events that don't carry them).
- Frontend: countdown renders + ticks; Reconnect button calls `startWifiTunnel` with the saved `{ip,port,udid}`; `connect_progress` phases render in the spinner region.

---

## Cluster 3 — Wiring Orphaned Capability (frontend + backend)

**What ships**
1. **Nearby POIs.** New `GET /api/geocode/nearby?lat&lng&radius_m&limit` thin controller that calls the already-complete `services/geo_extras.py:nearby_pois` (Overpass 4-mirror fallback, named filter, haversine sort, `NearbyPoi` schema). Map right-click gains a "Nearby places" submenu listing results; each is teleport-able / bookmark-able.
2. **GPX timing-aware replay.** `gpx_service.py` `parse_gpx` currently flattens to bare lat/lng, discarding `<time>`/`<ele>`; `/route/gpx/import` hardcodes `profile="walking"`. Change: parse `<time>` into the `SavedRoute`, derive per-segment speed from consecutive timestamps, honor it on playback, and stamp real timestamps on export (`generate_gpx` already supports them via `pt.get("timestamp")`/`elevation`). The interpolator that already emits a per-point `timestamp_offset` is `RouteInterpolator.interpolate` in `backend/domain/movement.py:194` (carved to domain in P3 — NOT in `simulation_engine.py`); the engine drives inter-tick sleep off `timestamp_offset` (`simulation_engine.py:799`). Behavior: **timing present → respect original cadence; absent → fall back to profile speed** (no regression for timing-less GPX).
3. **Speed jitter (default ON + settings toggle).** Add a `speed_jitter` field to `config.py` SpeedProfile (alongside the existing `speed_mps`/`jitter`/`update_interval`); the engine applies a ±10–15% Gaussian variation to `speed_mps` each tick (currently constant — `simulation_engine.py:670` sets it once, `:763` pushes the same value every tick), reusing the `_pending_speed_profile` re-plan seam (`simulation_engine.py:120/606/724-726/813-826`). A settings toggle (persisted, default ON) disables it for byte-reproducible runs. ⚠️ The position-jitter helper `RouteInterpolator.add_jitter` (`movement.py:311`) currently uses **module-level `random`** (no rng arg), so it is not deterministically testable. This cluster **adds an injectable `rng: random.Random | None` param** to the jittered path (speed and/or position), mirroring the existing `random_point_in_radius(..., rng=...)` seam at `movement.py:352`.

**Files:** `backend/api/geocode.py` (+route), `backend/services/geo_extras.py` (reuse), map context-menu component + a nearby-results UI under `frontend/src/components/`, `backend/services/gpx_service.py`, `backend/core/simulation_engine.py`, `backend/domain/movement.py` (jitter math if pure), `backend/config.py`, frontend settings + persistence (localStorage, mirroring `show_bookmark_pins`).

**Error handling:** `nearby` route maps `GeocodeError`/timeout to a domain error → controller HTTP mapping (services never raise `HTTPException`); empty result returns `[]` not 500. GPX with malformed/partial `<time>` falls back to profile speed for that segment (never throws). Jitter is clamped so speed never goes ≤0.

**Tests:**
- danger-zone: write characterization tests for `simulation_engine.py` movement output FIRST, run them with **jitter OFF** (toggle off) to keep exact-tuple assertions deterministic.
- A separate focused test injects a **seeded/deterministic RNG** and asserts jitter-on stays within ±15% bounds and never produces ≤0 speed. (Engine needs an injectable RNG seam for this — added as part of the task.)
- GPX: round-trip a `.gpx` with embedded `<time>` → import preserves per-segment timing → export reproduces timestamps (deep-equal within tolerance); a timing-less `.gpx` falls back to profile speed.
- `GET /api/geocode/nearby`: returns `NearbyPoi[]`; upstream failure → `[]` (or mapped error), not 500.

---

## Cluster 4 — Packaging Robustness (build/CI, decoupled from runtime)

**What ships**
1. **`--self-check` flag.** The frozen binary, run with `--self-check`, imports the whole fragile native chain and exits non-zero on the first `PackageNotFoundError` / `ImportError`:
   - `mobile_image_mounter` → `pyimg4` → `apple_compress`
   - `service_connection` → `prompt_toolkit`
   - `geo_offline` → `timezonefinder` → `h3`
   `build-installer-mac.sh` runs the built binary with `--self-check` post-build; a non-zero exit fails the build (red). The `.spec` comments already enumerate these chains — the self-check body is those comments turned into asserts. Rationale: every historical PyInstaller metadata gap (pyimg4 / apple_compress / prompt_toolkit / h3) was found only on real hardware, each silently no-op-ing DDI mount or offline geo. A solo dev has no QA team; this turns "dev-good / DMG-broken" into a build-time red.
2. **Pin the fragile native chain to `==`.** `requirements.txt` currently has 13 `>=` and 0 `==`. ⚠️ Of the native chain, only `pymobiledevice3` (`>=9.9.0`), `timezonefinder` (`>=8.0`), `numpy` (`>=1.24`) are explicit lines today; `pyimg4`, `apple_compress`, `h3`, `prompt_toolkit` are **transitive** (via `pymobiledevice3`) and NOT listed — so pinning them means **adding new direct `==` lines**, not editing existing ones. Pin all of `pymobiledevice3`/`pyimg4`/`apple_compress`/`h3`/`prompt_toolkit`/`timezonefinder`/`numpy` to the known-good versions in the current `.venv` (read them via `pip show`/`pip freeze`); leave pure-Python deps as `>=` floors. Each DMG then builds against a byte-reproducible import graph for the native chain.
3. **`GET /api/system/info`.** Exposes the (otherwise restart-only) health states so they're queryable live. Three signals, with their real current shapes:
   - **helper alive** — derived from `TunnelHelperClient.is_connected` (`_writer`/`_reader` non-None) + an async `ping()`; there is NO stored handshake flag, so `/info` reports the derived aliveness.
   - **per-device `{ddi_mounted, ios}`** — ⚠️ `ddi_mounted` is NOT a persisted latch today: `_ensure_personalized_ddi_mounted` computes it locally and only emits a transient `DdiMountedEvent`/`DdiNotMountedEvent`; `_ActiveConnection` stores `ios_version` but has no `ddi_mounted` field. This cluster **adds a stored `ddi_mounted` flag** on `_ActiveConnection` (set where the event is published) so `/info` can report it without re-probing MobileImageMounter.
   - **`offline_geo_ok`** — ⚠️ there is NO `_load_failed` latch anymore (removed 2026-06-24); the resolver now has `_loaded` (success cache) + `_last_attempt_ts` (30s failure-retry gate) and retries each call. `/info` probes it at request time by calling `_ensure_loaded()`/`resolve()` (never raises; returns blanks on failure) → reports `true`/`false`.

**Files:** `backend/main.py` (`--self-check` arg path), `backend/locwarp-backend.spec` (cross-check the import list), `build-installer-mac.sh` (post-build invocation), `backend/requirements.txt`, `backend/api/system.py` (+route), a small `system_info` assembler in `services/` if it needs to touch multiple managers.

**Error handling:** `--self-check` prints the offending module + exits 1 on the first failure (clear build log). `offline_geo_ok` probe is request-time only (never blocks startup) and catches its own failure → reports `false`, never 500s the whole `/info` response.

**Tests:**
- Unit: the self-check import list matches the `.spec` enumerated chains (assert the list, so drift between `.spec` and self-check is caught).
- `GET /api/system/info` returns the expected shape with each latch field present; `offline_geo_ok` reflects a stubbed resolver success/failure.

---

## Out of Scope (deferred bigger bets, recorded so they're not silently dropped)

From the opportunity map, explicitly NOT in this program: Cmd+K command palette (L), record-and-replay trips (M, shares replay path with C3 GPX — natural follow-up), per-waypoint dwell (M), real A→B commute geocode (M), scheduled route runs (L), active DVT health-ping (L), in-app one-click DDI mount (L, needs separate approval — flaky 20MB upload on iOS 26.4.1, auto-mount was disabled in v0.2.58), iOS Simulator target (L), auto-update download (M), diagnostics-bundle export (M), Gatekeeper unblock helper (S), offline POI index fallback (L), bookmark near-duplicate detection (M), frecency sort (M), search hover-preview pin (M). These remain in the opportunity map for a future program.

---

## Self-review checklist

- [x] Placeholder scan — no TBD/TODO/vague requirements.
- [x] Internal consistency — surface decisions match cluster descriptions; ordering coherent.
- [x] Scope — four clusters, each one mergeable plan; not over-large.
- [x] Ambiguity — fork decisions (app-level shortcuts, jitter default-on+toggle, GPX timing fallback, Undo single-level) stated explicitly.
- [x] **Code claims verified against the real repo** (adversarial 4-agent verification, 2026-06-25): 27 claims checked → 22 CONFIRMED, 5 IMPRECISE, 0 WRONG. All 5 imprecise claims corrected inline: (C1) handlers live in `useSimActions.ts` not `App.tsx`; `handleTeleport` snapshot is dual-device-only so Undo adds a universal one; `keyboard.ts` has no typing-target guard yet. (C2) connect path spans `connect_wifi_tunnel` + `create_engine_for_device`. (C4) no `_load_failed` latch (removed 2026-06-24); `ddi_mounted` is not persisted (add a flag); `pyimg4`/`apple_compress`/`h3`/`prompt_toolkit` are transitive (add direct `==` lines). Plus CONFIRMED-with-nuance folded in (interpolator is `domain/movement.py:194`; `add_jitter` needs an injectable rng).
