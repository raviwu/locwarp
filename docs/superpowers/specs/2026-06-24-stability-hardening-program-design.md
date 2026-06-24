# LocWarp Stability Hardening Program — Design Spec

- **Date:** 2026-06-24
- **Status:** Approved (design). Implementation plans pending (SH0 + SH1 first).
- **Owner:** Ravi
- **Source:** Whole-codebase architect + UX cross-comparison audit (2026-06-24, 28-agent workflow, 98 subsystem + 13 cross-compare findings, adversarially verified, deduped to 65 consolidated items).

> Line numbers in this spec are **audit-time anchors** (2026-06-24). Each implementation plan re-confirms exact locations before editing.

---

## 1. Motivation

A full audit surfaced ~111 raw findings, deduped to **65 consolidated items**. The dominant themes:

1. **Silent failures** — core actions (connect / teleport / delete) fail with no toast, spinner, or banner on several entry points, while the same action surfaces feedback on others. Asymmetric feedback erodes day-to-day trust.
2. **Loaded guns** — dead code, never-emitted WS events, untyped wire contract, latent dual-device regressions, and a process-lifetime offline-geo latch that silently blanks data until restart.
3. **Data-integrity footguns** — user imports that silently vanish (empty `updated_at` losing to a tombstone), non-idempotent route import, a CloudSync overlay that can permanently lock the entire UI.
4. **Structural debt** — two un-decomposed god-objects (`api/device.py` WiFi-tunnel state machine, `_move_along_route`), recovery orchestration living in the HTTP ring, and the untyped WS contract that lets every event-name drift through tsc/vitest invisibly.
5. **Accessibility / i18n / cosmetic** — div-based menus with no keyboard path, toasts with no `aria-live`, hardcoded strings, off-token inline styles.

This program does **all 65 items**, sequenced by stability leverage (reliability/correctness first, cosmetic/a11y last), in 5 independently shippable batches **SH0–SH4**.

## 2. Goals and Non-Goals

**Goals**
- Eliminate every silent failure on a core user path; make every async outcome observable.
- Remove dead code, race windows, and data-integrity footguns.
- Make backend↔frontend wire drift visible at compile/test time.
- Incrementally decompose the two god-objects behind test-first seams.
- Bring core surfaces to a baseline of keyboard/a11y/i18n correctness.
- Every batch ships a **user-perceivable, manually verifiable** improvement.

**Non-Goals / Standing Constraints**
- **Not a behavior freeze.** This program intentionally changes behavior (adds confirms, toasts, timeouts, guards, gates). The clean-arch refactor's "no external behavior change" rule does **not** apply here.
- **Full green after every commit.** The complete backend pytest suite (**914 collected** as of 2026-06-24) and the frontend vitest suite stay green after every commit. WS payloads are compared **deep-equal JSON**, serialized `exclude_unset`/`exclude_none`.
- **Danger-zone-test-first (hard rule).** Any change touching `core/simulation_engine.py`, all movers, `core/device_manager.py` recovery, `api/location.py`, `api/device.py` watchdog, or `api/phone_control.py` writes a characterization test (injected `ClockPort` + stepped `asyncio.sleep`, ordered exact-tuple assertions) **before** the edit.
- **No unrelated refactor.** God-object work is incremental, test-first, and only at clean seams — never "rewrite for LOC."
- **Thick carve-outs stay leaky.** Do not abstract `pymobiledevice3` / `usbmuxd` / SIP / tunnel-helper / `osascript` guts into pure cores; wrap behind narrow ports only as a seam.
- **Import-linter / dependency-cruiser gates stay green** (7 backend contracts, FE depcruise).

## 3. Verification Discipline (applies to every batch)

Two layers, both required before a batch is "done":

### 3a. Automated gate (engineering)
Run, in order, and capture output as evidence:
```
cd backend && .venv/bin/python -m pytest -q          # 914+ green
cd backend && .venv/bin/python -m pytest --collect-only -q   # count not regressed
cd frontend && npx tsc --noEmit                       # 0 errors
cd frontend && npx vitest run                          # all green
cd backend && lint-imports                             # 7 kept, 0 broken
cd frontend && npx depcruise src                       # 0 errors
```
New behavior gets a new test in the same commit. Danger-zone touches get the characterization test **first** (red → green).

### 3b. Manual smoke test (user acceptance — required by owner)
Each batch defines a **manual smoke script**: concrete steps Ravi runs in the real app, each with an **observable expected result**, so the improvement is something the user can see and feel. Automated coverage does not replace this layer; it gates it. Where a flow needs a real iPhone (USB/WiFi tunnel, pairing, reconnect), the smoke step says so. Capture evidence (screenshot / screen recording / console log) per the global "Automated Verification First → attach evidence" rule.

Smoke runs happen on `npm run start` (Electron) unless a step says browser (`npx vite --host`).

## 4. Finding Vocabulary

Stable IDs used across this spec and all plans. `A*` = architecture, `U*` = UX, `X*` = cross-cutting, `N*` = needs-measurement/decision.

---

## 5. Batch SH0 — Docs & Repo Hygiene

**Why first:** doc-only, zero runtime risk, and X1 misleads every future agent session through `@`-imported instruction files — it cannot wait.

| ID | Problem | Location | Fix | Effort |
|----|---------|----------|-----|--------|
| X1 | Status block reads "P4a pending merge … P4b + Phase 5 deferred. Do not start without approval" but P0–P5 are all merged (lint-imports 7 kept/0 broken; depcruise gate present; P5 probe test present). Misleads every session. | `CLAUDE.md:11`, `AGENTS.md:11`, design-spec line 4 | Update three status blocks to "P0–P5 all merged 2026-06-23"; remove the "do not start" guard. Most durable: replace with a one-line pointer to the memory note. | S |
| X2 | CLAUDE.md describes Bookmark/RouteManager as `core/` ring; they are `services/`-ring stateful adapters (no `*_manager.py` files). | `CLAUDE.md`, `backend/services/bookmarks.py:94`, `backend/services/route_store.py:88` | Name the real files in the CRDT + backup sections; clarify watcher/`_store_lock` live in `services/`. | S |
| X3 | domain-ring inventory line under-counts: omits `backup.py` and `store_merge.py`. | `CLAUDE.md` | Add both modules to the inventory line. | S |
| X4 | Two clean-arch plan docs (p3, p4a) are permanently untracked (`git status` shows `??`); all other P-series plans are committed. | `docs/superpowers/plans/2026-06-22-clean-arch-p3-*.md`, `*-p4a-*.md` | Commit both for consistency with the series. | S |

**SH0 manual smoke**
1. Open `CLAUDE.md` and `AGENTS.md` → the clean-arch status block reads "P0–P5 all merged"; no "do not start" guard remains. *(Expected: future-session guidance is correct.)*
2. `git status --short` → the two plan files no longer appear as `??`. `git log --oneline -3` shows the commit. *(Expected: clean tree, series consistent.)*
3. Automated gate: pytest/vitest unchanged-green (no code touched). *(Expected: 914 green.)*

**SH0 acceptance:** docs read correctly; tree clean; automated gate green.

---

## 6. Batch SH1 — Stability-Critical

**Theme:** silent failures, races, dead code, data-integrity, contract loaded-guns. Mostly S-effort, low risk, highest reliability leverage. **X5 runs first** as the enabling step for X6–X9.

| ID | Problem | Location | Fix | Effort | Danger-zone? |
|----|---------|----------|-----|--------|--------------|
| X5 | WS wire contract is `{type:string} & Record<string,unknown>`; `subscribe(type:string)`; only 1 typed event. All 7 event-name drifts below are invisible to tsc/vitest. | `frontend/src/contract/wsEvents.ts:5`, `backend/domain/events.py:18` | Define a single `WsEventType` string-literal union listing the real backend vocabulary; `subscribe(type: WsEventType)`. Optional vitest: assert FE union ⊆ checked-in backend emit list. No codegen. | M | no |
| X6 | FE calls removed `/api/device/wifi/connect` (deleted v0.1.49) — guaranteed 404; currently unreachable but a dead loaded gun. | `frontend/src/services/api.ts:131`, `frontend/src/hooks/useDevice.ts:167`, `backend/api/device.py:31` | Delete `wifiConnect`/`connectWifi` + unused `onWifiConnect` prop branch. Supported path is `wifiTunnelStartAndConnect`. | S | no |
| X7 | Reconnect broadcasts `device_connected`, but a docstring + 2 FE subscriptions expect `device_reconnected` (never emitted) — reconnect-specific UX silently lost. | `backend/main.py:741,497`, `frontend/src/hooks/useDevice.ts:87`, `frontend/src/hooks/useSimulation.ts:513` | Converge on one name: fold dead subs into the `device_connected` handler + fix docstring, or add `reconnected:true` to the payload (additive). | S | no |
| X8 | FE subscribes to 4 event classes backend never emits (`simulation_state`/`simulation_complete`/`simulation_error`/`random_walk_pause(_end)`); semantic siblings already correctly subscribed. | `frontend/src/hooks/useSimulation.ts:334,370,614,550,559` | Delete the 5 dead subscriptions. | S | no |
| X9 | Backend emits `device_error` but no FE handler subscribes — error events silently dropped by the router. | `backend/api/device.py:1201` | Add a `device_error` subscription showing a toast/banner (payload carries `stage`+`error`), or delete the broadcast if HTTP response suffices. Keep WS vocabulary honest. | S | no |
| A8 | `TunnelHelperClient.call()` `readline()` has no `asyncio.wait_for`; every typed RPC serializes through one `call()`+`_lock`; a half-open helper socket can hang forever and starve the whole WiFi subsystem. | `backend/services/tunnel_helper_client.py:142` | Wrap readline in `asyncio.wait_for` (~30s, above helper-side 20s open bound); on timeout drop the connection so the next caller reconnects. | S | no |
| A11 | `geo_offline` `_load_failed` latches True forever; first transient failure (numpy not ready, iCloud eviction, cold cache) permanently blanks all flags/timezone/city; only one `logger.exception`. | `backend/services/geo_offline.py:25,90,102` | Remove `_load_failed`; retry each call (success still cached by `_loaded`); optional timestamp gate against retry-storm; throttled WARNING on early-return in `resolve()`. | S | no |
| A13 | User `import_json` appends with the payload's original `updated_at` (often `""`); `_save`→`merge_stores` loses an empty-`updated_at` item to any real-timestamp tombstone. `import_catalog` correctly calls `force_seed_items`; `import_json` doesn't. API returns `imported:N` before merge discards. | `backend/services/bookmarks.py`, `backend/services/route_store.py`, `backend/services/bookmark_import.py` | Treat import as resurrect intent: stamp `updated_at = now` on each item before import (reuse `force_seed_items`). Add 2 characterization tests (delete id → import empty-`updated_at` → assert survives). | S | yes (store save) |
| A18 | `RouteManager.import_json` is non-idempotent: id collision always mints a new uuid + `(匯入)` suffix; re-import duplicates every route. `BookmarkManager` skips existing ids. | `backend/services/route_store.py:419-426` | Mirror bookmark behavior: skip when incoming id exists and content unchanged. Add a double-import-doesn't-duplicate test. | S | no |
| A14 | `_engine()` rebuild for a non-primary udid returns the primary engine: success check uses `app_state.simulation_engine` (primary accessor) while `create_engine_for_device` only sets primary when `_primary_udid is None`. Dual-device → teleport/navigate on B drives A. | `backend/api/location.py:74-95`, `backend/main.py` | After rebuild, re-resolve via `get_engine(target_udid)`; fall back to `simulation_engine` only when the original `udid` arg is None. Add a characterization test. | S | yes |
| A21 | `_handle_device_lost` falls back to disconnecting **all** devices when udid is None; all current callers pass a udid, but the branch is "one new call site away" from a dual-device regression. | `backend/api/location.py:198-200` | Make udid required (drop the None default) so the all-devices branch is unreachable. | S | yes |
| A5 | `ReconnectManager` is constructed but never started; no method is called anywhere; real reconnection lives in `_per_tunnel_watchdog`. It also carries a duplicate `SimulationSnapshot`. A decoy for anyone debugging the reconnect window. | `backend/services/reconnect.py`, `backend/main.py:452` | Delete `reconnect.py` + the `main.py` import/assignment (no test imports it). | S | no |
| A20 | `AppState.simulation_engine` setter's non-None branch stuffs the engine into `simulation_engines['__legacy__']`; zero real assignments tree-wide — unreachable. | `backend/main.py:369-378` | Remove the non-None branch (raise/log) or reduce the setter to a getter. | S | no |
| A9 | `connect_wifi_tunnel`'s `if udid in self._connections` → `await self.disconnect(udid)` check-then-act is outside `_lock`; only the final assignment is inside. (The ~20 other `_connections` accesses are deliberately lock-free and atomic on one event loop — leave them.) | `backend/core/device_manager.py:977-978` | Move just this existence-check + disconnect inside `self._lock`, or add a one-line comment explaining why it's safe. | S | yes |
| A10 | `migrate_pair` runs while the outgoing watcher is still live; `stop_watcher()` is called after. A watcher tick or user edit in the few-ms window can rebuild a just-unlinked file. Convergent merge prevents corruption but yields "import succeeded but nothing changed". | `backend/services/cloud_sync_service.py:83,95-98` | Move `stop_watcher()` before `migrate_pair` (symmetric with enable); managers rebuild afterward anyway. | S | no |
| A16 | `enable()` rollback only snapshots SRC; on failure it unlinks non-preexisting dst files but does not restore merged existing destinations. Docstring claims all-or-nothing; not true. Data is safe (merge idempotent) but the contract lies. | `backend/services/cloud_sync.py:186` | Downgrade docstring to "src restored on failure; dst merges are convergent and safe to retry" (cheapest correct fix). | S | no |
| A19 | `disable()` is a no-op when src is missing (won't clobber) but DATA_DIR may be stale and `_sync_folder=None` cuts the link to the canonical copy; `materialize_if_placeholder` written for this has no non-test caller. | `backend/services/cloud_sync_service.py:122`, `backend/services/cloud_sync.py:44` | Call `materialize_if_placeholder` at the top of `disable()` (and `enable()`) to pull evicted files first; if still missing, raise HTTPException so the user retries. | S | no |
| A17 | `RECENT_PLACES_FILE` is import-time captured; the autouse conftest guard neither patches it nor resets `_singleton`. Latent: the first recent-places test would read/write the developer's real `~/.locwarp/recent_places.json`. | `backend/services/recent.py:14`, `backend/tests/conftest.py` | Extend the conftest guard to monkeypatch `RECENT_PLACES_FILE` → tmp and reset `_singleton=None`. | S | no |
| X14 | `BookmarkManager._watcher_tick` writes via raw `safe_write_json`, bypassing the repo and re-leaking the infra dependency P4a removed; all other bookmark writes go through `self._repo.save()`. Two write paths with different invariants + a dead `safe_load_json` import in both managers. | `backend/services/bookmarks.py:268` | Route watcher writes through the repo (write-only method or idempotent `self._repo.save(self.store)`); delete the unused imports. | S | no |
| A12 | Watchdog recovery hardcodes `reason: 'task_exited'`; the richer `DeviceLostError` classification (`TUNNEL_DEAD`/`LOCKDOWN_DEAD`/`DDI_MISSING`/`USB_GONE`) never reaches the `tunnel_lost` WS payload — operator must read backend logs. | `backend/api/device.py:805,899` | Thread the existing `DeviceLostError.reason` + `last_error` into the WS payload. No new observability infra. | M | yes (watchdog) |
| U25 | CloudSync busy overlay: `fetchWithRetry` has no AbortController/timeout; backend stuck mid-`migrate_pair` → `fn()` never resolves → `busy` stays true → zIndex-9999 overlay locks the entire UI permanently. Worst failure mode for a desktop tool. | `frontend/src/components/CloudSyncBusyOverlay.tsx:14-24`, `frontend/src/contexts/CloudSyncBusyContext.tsx:44-57`, `frontend/src/services/api.ts:6-18` | Add a client-side timeout (AbortController + ~30-45s, or `Promise.race`) to sync calls; on stall, reject so `finally` clears busy + toasts; after ~10s show "taking longer…" + Cancel. | M | no |

**SH1 dependencies:** X5 before X6–X9 (drift fixes become type-checked). A13's tactical stamp here; A3's structural `_upsert_items` consolidation is in SH3. A14/A21 pair (dual-device correctness).

**SH1 manual smoke** (requires a real iPhone for device steps; single device unless noted)
1. **Import resurrection (A13):** export bookmarks → delete one bookmark → re-import the exported file. *(Expected: the deleted bookmark reappears. Before: it silently stayed deleted.)*
2. **Route import idempotency (A18):** import a route file twice. *(Expected: route count unchanged on the second import; no `(匯入)` duplicates.)*
3. **Offline geo resilience (A11):** with the app running and geo data present, confirm a bookmark shows country flag + timezone. *(Expected: geo fields populate; if they ever blank, they recover without a restart.)*
4. **CloudSync escape hatch (U25):** enable cloud sync. To exercise the stall path, point sync at a slow/unreachable folder or throttle the backend. *(Expected: after ~10s the overlay shows "taking longer…" + a Cancel button; clicking Cancel releases the UI. Before: permanent lock.)*
5. **WS contract honesty (X6–X9):** open devtools console; connect, disconnect, and reconnect the iPhone. *(Expected: no 404 for `/api/device/wifi/connect`; no unhandled-rejection spam; a `device_error` (e.g. force a USB-fallback failure) surfaces as a visible toast.)*
6. **Dual-device targeting (A14/A21):** connect two iPhones; teleport device **B**. *(Expected: B moves, A does not.)* Disconnect one device. *(Expected: only that device drops; the other keeps simulating.)*
7. Automated gate green (incl. the new A13/A18/A14 characterization tests).

**SH1 acceptance:** automated gate green with new tests; smoke steps 1–6 observed and evidenced.

---

## 7. Batch SH2 — UX Feedback Symmetry

**Theme:** the audit's dominant theme. Add the already-existing `showToast` / spinner / confirm / banner infrastructure to the core paths that are currently silent. Mostly S-effort, single-device-verifiable, immediately perceivable.

| ID | Problem | Location | Fix | Effort |
|----|---------|----------|-----|--------|
| U13 | Single delete (context menu) executes with no prompt; bulk + category delete use `window.confirm`. Bookmark single-delete is fire-and-forget (no try/catch) → silent unhandled rejection. CRDT tombstone propagates via iCloud forever, no in-app undo. Asymmetry is backwards (deleting one feels "safe" but lost the guard). | `frontend/src/components/BookmarkContextMenu.tsx:371-374`, `frontend/src/components/RouteList.tsx:885-895`, `frontend/src/hooks/useBookmarks.ts:65-71` | Add a lightweight confirm to both single-delete paths (reuse `window.confirm`), or delete + Undo toast (CRDT makes re-add trivial); wrap the bookmark path in try/catch + toast. | S |
| U6 | `sim.mode` defaults to Teleport; `teleport` never sets `running:true` so the Start button renders, but `handleStart` has no Teleport branch → the app's main centered green CTA does nothing on open. Joystick branch lacks the no-position guard RandomWalk has. | `frontend/src/hooks/useSimActions.ts:177-200`, `frontend/src/hooks/useSimulation.ts:123,666-675` | (a) Hide/disable the Transport Start in Teleport mode; (b) add a no-position guard + toast to the Joystick branch. | M |
| U1 | Dropdown device-connect `onSelect` is fire-and-forget; `connect()` failure `console.error`s then throws into an unhandled rejection; dropdown closes, no spinner, no error. Only manual USB connect entry point. `onRestoreOne` is already the correct pattern. | `frontend/src/App.tsx:912`, `frontend/src/hooks/useDevice.ts:133-149` | `try { await device.connect(id) } catch(e){ showToast(...) }`, mirroring `onRestoreOne`. | S |
| U7 | Single-device teleport/navigate failure is fire-and-forget; rethrow is unobserved (not awaited); `sim.error` renders only as a banner. The common single-iPhone user gets weaker feedback than dual-device. | `frontend/src/hooks/useSimActions.ts:125,143`, `frontend/src/hooks/useSimulation.ts:672-674` | await + try/catch + `showToast`, reusing the dual-path toast surface. | S |
| U8 | Map Transport Start isn't gated on `deviceConnected`; the CoordInputStrip 2px below it correctly greys out. `TransportButtons` has no `deviceConnected` prop. | `frontend/src/components/MapView.tsx:147-232`, `frontend/src/components/CoordInputStrip.tsx` | Thread `deviceConnected` into `TransportButtons`; disable Start when `!deviceConnected`. | S |
| U2 | WiFi auto-connect is fully silent; `tunnelError` is only set on the manual path though a comment claims "panel will surface them". Toggle defaults ON. | `frontend/src/hooks/useWifiAutoConnect.ts:147-154`, `frontend/src/components/DeviceStatus.tsx` | Lightweight toast when the auto pass actually runs; a dismissible one-line note in the WiFi section on all-failed; fix the wrong comment. | S |
| U3 | USB disconnect jumps straight to a red terminal banner + chip disappears; the WiFi path has an amber `tunnel_degraded → reconnecting` transition. The watchdog may auto-recover within ~27s, but a recoverable blip looks terminal. | `frontend/src/hooks/useSimulation.ts:485-505`, `frontend/src/hooks/useDevice.ts:310` | USB `device_disconnected` shows amber "reconnecting…" while the watchdog will attempt recovery, then escalates to red; or at least soften the banner copy. | M |
| U4 | Post-Forget recovery only via the collapsed-by-default dropdown; after forget, `disconnect()`→`listDevices()` repopulates the device (with Re-trust) but the always-visible chip row only renders `connectedDevices`, so it vanishes from where the user was. | `frontend/src/components/DeviceChip.tsx:152`, `frontend/src/App.tsx:869-880` | Rewrite forget copy to name the real steps, or auto-expand the dropdown after forget when a trust_required device exists. (Avoid "re-scan" — scan auto-connects in single-device.) | S |
| U5 | Sticky-denied / forgotten state has no persistent visible badge; trust_required only appears inside the collapsed dropdown — why a physically-connected iPhone won't auto-connect is nearly invisible. | `frontend/src/components/DeviceStatus.tsx:420-452` | Show a trust_required chip in the always-visible chip row. | M |
| U9 | Paused route has no paused state in the prominent ETA bar; `EtaBar` doesn't take `isPaused` though `sim.status.paused` exists; progress/ETA still read as advancing. | `frontend/src/components/EtaBar.tsx`, `frontend/src/App.tsx:836,1163-1170` | Pass `isPaused` to `EtaBar`; show a "Paused" chip + dim the progress bar. | S |
| U10 | Custom fixed-speed and speed-range can both render "active"; section comment says "overrides fixed" but the UI never says so. | `frontend/src/components/ControlPanel.tsx:716-823` | Dim/disable the custom field when a range is set, or show "range overrides custom". | S |
| U11 | GoldDitto ② button greys out (opacity 0.5) with no inline reason; empty B input keeps a neutral border so there's no red. | `frontend/src/components/GoldDittoPanel.tsx:170,314` | One-line hint under the disabled ② naming the missing prerequisite (B coord / valid wait); the validation boolean already exists. | S |
| U12 | Dual-device teleport optimistically `setCurrentPosition` before awaiting `teleportAll`; on failure the toast fires but the marker already moved and isn't reverted; the single-device path is correct (sets after success). | `frontend/src/hooks/useSimActions.ts:121-123` | Move `setCurrentPosition` after success, or revert on failure, in the dual branch. | S |
| U14 | JSON import label and category/route mutation lack in-flight feedback (double-trigger risk on slow iCloud writes); `BulkPasteDialog` is the good example (`busy` prop disables + `...`). (Note: imports do toast success/failure.) | `frontend/src/components/BookmarkList.tsx:381-385`, `frontend/src/components/CategoryManagerPanel.tsx:131-136` | Extend the `busy`-prop pattern to the import label; category mutation awaits + failure toast. | M |
| U15 | Custom/Edit bookmark dialog silently no-ops on out-of-range coords; button only disables on finiteness, so lat 200 + submit does nothing. | `frontend/src/components/CustomBookmarkDialog.tsx:65-66`, `frontend/src/components/EditBookmarkDialog.tsx:63-64` | Inline red text on finite-but-out-of-range (reuse `AddBookmarkDialog:90` style). | S |
| U16 | Left-click teleport ignores the device-connected gate the right-click menu enforces; with zero devices it still runs the single-device branch and flashes a 500ms green "success" + pushes a recent entry. | `frontend/src/components/BookmarkList.tsx:255-269`, `frontend/src/components/BookmarkContextMenu.tsx:243-288` | Mirror the context-menu gate on the left-click path; fall back to map-pan or suppress the success flash when no device. | S |
| U17 | Bookmark left-click defaults to teleporting real GPS (`flyGps` default true); browsing the library moves the spoofed location on a single click; opt-out checkbox is below the panel. Documented but a surprising default. | `frontend/src/components/BookmarkList.tsx:221-263` | Persistent inline badge ("Click moves GPS") or a toast on teleport; don't silently change the default. | S |
| U18 | The '+' add-device button is visible at 2 devices but always rejects ("max reached"); row/tunnel imply 3, `onAdd` guard caps at `>=2`. Dead affordance. | `frontend/src/App.tsx:861-866`, `frontend/src/components/DeviceChipRow.tsx:6,21` | Unify the cap: raise `onAdd` guard to `>=MAX_DEVICES` (3) or hide/disable '+' at 2. | S |
| U26 | Stray native `alert(t('toast.no_position_random'))`; the key is clearly meant for the toast surface and bypasses the in-app toast. | `frontend/src/App.tsx:173` | Replace with `showToast(t('toast.no_position_random'))`. | S |

**SH2 manual smoke** (single iPhone sufficient for most; a few need none)
1. **Delete guard (U13):** right-click a bookmark → Delete. *(Expected: a confirm prompt; cancel keeps it.)* Same for a route.
2. **Dead Start fixed (U6):** open the app (Teleport mode). *(Expected: the main green Start is hidden/disabled, not a silent no-op.)* Switch to Joystick with no position set, press Start. *(Expected: a "no position" toast, not silence.)*
3. **Connect feedback (U1):** open the device dropdown and pick a device that fails to connect (e.g. untrusted). *(Expected: a toast explaining the failure; before: nothing.)*
4. **Teleport feedback (U7, U8):** with no device connected, the Map Start button is disabled (U8). With a device, force a teleport failure. *(Expected: a toast.)*
5. **Reconnect transition (U3):** unplug the USB cable mid-sim. *(Expected: amber "reconnecting…" first, red only after the watchdog gives up.)*
6. **Paused clarity (U9):** start a route, press Pause. *(Expected: ETA bar shows "Paused" and a dimmed progress bar.)*
7. **Speed override (U10), GoldDitto hint (U11), out-of-range coord (U15):** exercise each; *(Expected: visible hint/error in each case.)*
8. Spot-check U2, U4, U5, U12, U14, U16, U17, U18, U26 per their one-line expected results.

**SH2 acceptance:** automated gate green; every core action that can fail now shows feedback; smoke 1–7 observed and evidenced.

---

## 8. Batch SH3 — Structural Decomposition (test-first) + Layering

**Theme:** behavior-preserving structural work behind test-first seams. Highest effort, highest care. Every item that touches danger-zone code writes characterization tests first. **N1 is Profiler-gated.**

| ID | Problem | Location | Fix | Effort | Danger-zone? |
|----|---------|----------|-----|--------|--------------|
| A4 | recovery/reconnect orchestration (~210 lines: `_engine`, `_try_with_recovery_retry`, `_handle_device_lost`) lives in the `api/location.py` controller and reaches into `dm._connections`/`dm._events`; the WS path and `main.py` watchdog can't reuse it (watchdog re-implements engine-stop/promote at 590-674). Biggest single source of controller thickness. | `backend/api/location.py`, `backend/main.py:590-674` | Move to `DeviceService` or `services/engine_resolver.py` as `resolve_engine(udid)` / `with_recovery(udid, op)`; controller only maps domain error → HTTPException at the boundary. | L | yes |
| A1 | `api/device.py` is a 1524-line WiFi-tunnel state-machine god-module; `device_service.py` is 39 lines and its docstring defers forget orchestration; real recovery (`_per_tunnel_watchdog` 773-903, `_build_tunnel_udid_candidates`, candidate-loop, re-key, `forget_device`) is HTTP-layer module-level and untestable without FastAPI + module-global `_tunnels`. | `backend/api/device.py`, `backend/services/device_service.py`, `backend/infra/device/tunnel_restart.py` | Incrementally lift pure orchestration into `WifiTunnelService`, starting at the cleanest seam (`_build_tunnel_udid_candidates` → `_per_tunnel_watchdog` → USB-fallback). | L | yes |
| A2 | `_move_along_route` is a ~290-line god-method mixing interpolation, O(W·C) waypoint seg-index precompute, 3-attempt push-retry, hot-swap replanning, emission. Most behavior-critical, no direct tests. | `backend/core/simulation_engine.py:586-878` | Extract two pure/near-pure helpers first: (a) seg-index precompute (675-693) → `domain/movement.py` `match_waypoints_to_coords` (pure, unit-tested); (b) push-retry (740-757) → `_push_with_retry`. | M | yes |
| A3 | `bookmarks.py` 735-line god-service mixes geo enrich, watcher state machine, CRUD, and three near-duplicate seed/import paths (`import_json`/`import_catalog`/`force_seed`) whose divergence is why `import_json` misses the `force_seed_items` stamp (A13). | `backend/services/bookmarks.py` | Extract `_upsert_items(items, *, stamp_now, enrich_force)` shared by all three — structurally fixes the import footgun (`stamp_now` becomes a parameter, not a per-path omission). | M | yes (store) |
| A6 | Controllers read/write registry/AppState privates (`_primary_udid`, `_initial_map_position`, `_bookmark_expanded/hidden_categories`) and call `save_settings()`; settings-persistence policy leaks into the api ring. | `backend/api/location.py`, `backend/api/bookmarks.py` | Add 5-6 thin public methods (`get_primary_udid()`, `get/set_initial_map_position()`, `get/set_bookmark_ui_state()`); keep `simulation_engines` fan-out unchanged. | M | no |
| A22 | Container is built at import-time; managers are guaranteed None there, masked by property + hasattr + 503 (three layers) for a structurally-None value. | `backend/bootstrap/container.py`, `backend/main.py:995`, `backend/api/deps.py` | Build the Container after lifespan `load_state()`, or don't pass managers so the property always delegates. (503 guard is correct; not urgent.) | M | no |
| A7 | `api/geocode.py` builds a module-level `GeocodingService()` bypassing the container; `main.py:1004` also builds one — two instances coexist. | `backend/api/geocode.py:30` | Use `Depends(get_geocoding_service)`; delete the module-level instance. | S | no |
| X12 | Bookmark/Route managers duplicate ~80 lines of file-watcher state machine (`start/stop_watcher`, `_schedule_reconcile`, inner `_Handler`, `Timer(0.5)` debounce) nearly line-for-line; only `_watcher_tick` legitimately diverges (lock differences). Already subtly drifting. | `backend/services/bookmarks.py:190`, `backend/services/route_store.py:135` | Extract a `FileWatchBinding` helper parameterized by `(path_accessor, on_reconcile)`; each manager keeps its own `_watcher_tick` injected as a callback. Keep dedup inside services; no new ring/port. | M | no |
| N1 | Re-render storm (Profiler-gated): hooks return un-memoized object literals; `ControlPanel`/`MapView` aren't `React.memo`; App passes 37/66 props; every `position_update` tick re-renders the whole tree. | `frontend/src/hooks/useSimulation.ts`, `frontend/src/components/ControlPanel.tsx`, `frontend/src/components/MapView.tsx` | First measure with React Profiler over a 60s sim. Then `React.memo` the two children + wrap hook returns in `useMemo` (must land together, else unstable identity defeats memo). Re-measure. | M | no |

**SH3 dependencies:** A3 supersedes A13's tactical stamp (consolidates the footgun). X5 (SH1) already in place. A1/A4 overlap the device/recovery surface — do A4 (extract orchestration) before A1 (carve the god-module) so the seam exists.

**SH3 manual smoke** (behavior-preserving — the smoke is "nothing regressed + feels at least as good"; real iPhone)
1. **Full sim regression:** run an end-to-end route simulation, a teleport, a joystick session, and a random walk. *(Expected: identical behavior to before SH3 — positions, ETA, pause/resume, completion.)*
2. **Recovery regression (A1/A4):** unplug + replug the USB cable mid-sim; toggle WiFi. *(Expected: the watchdog recovers as before; reconnect window unchanged or better.)*
3. **Dual-device regression (A4):** two iPhones, independent teleports. *(Expected: each targets the right device.)*
4. **Render smoothness (N1):** React Profiler commit count/duration over a 60s sim, before vs after. *(Expected: measurably fewer commits per tick; map pan/zoom during sim feels smoother.)* Attach the before/after Profiler numbers.
5. Automated gate green incl. all new characterization tests; import-linter + depcruise still 0 broken.

**SH3 acceptance:** automated gate green with new characterization tests; smoke 1–3 show no regression; N1 has before/after Profiler evidence.

---

## 9. Batch SH4 — a11y / i18n / Cosmetic / Dedup / Coordinate Ownership

**Theme:** baseline accessibility, i18n completeness, design-token consistency, dialog dedup, and the coordinate-ownership decision.

| ID | Problem | Location | Fix | Effort |
|----|---------|----------|-----|--------|
| U22 | Context menus + list rows are div-based with zero `role`/`tabIndex`/`onKeyDown`/`aria-label` (grep-confirmed across 4 files); no keyboard navigation. | `BookmarkContextMenu.tsx`, `RouteList.tsx`, `MapContextMenu.tsx`, `CategoryManagerPanel.tsx` | Pragmatic: context-menu items → `<button role="menuitem">`; container `role="menu"` + arrow/Enter; icon-only buttons mirror `title` to `aria-label`. | L |
| U21 | Device-chip actions (Disconnect/Forget/Re-trust/Restore) are right-click only; the chip is a div with no `role`/`tabIndex` — undiscoverable + keyboard-unreachable. | `frontend/src/components/DeviceChip.tsx:74-77` | Add a visible affordance (left-click or ⋯ button) + `role="button"` + Enter/Space; menu gets `role="menu"/menuitem` + Escape. | M |
| U23 | Modals (WiFi-warning, Repair, Phone-control, Forget) close on backdrop-click but have no focus trap / autofocus / Escape. | `DeviceStatus.tsx:871,924`, `PhoneControl.tsx:139`, `DeviceChip.tsx:129` | A reusable Modal wrapper (focus trap + autofocus + Escape). | M |
| X13 | Every frontend dialog hand-rolls its own portal overlay + inline styles + Escape; rgba/blur/zIndex/boxShadow tokens copy-pasted; Escape re-implemented with behavioral drift (some gate busy, some don't). | ~6 dialogs incl. `CustomBookmarkDialog.tsx:70` | One `DialogShell` (portal + overlay + centered panel + Escape + optional busy-lock). Pairs with U23. | M |
| U19 | All app toasts are plain divs with no `role`/`aria-live`; every async result is silent to assistive tech. `CloudSyncBusyOverlay` already uses `role="alert" aria-live="assertive"`. | `frontend/src/App.tsx:~1478-1506`, `frontend/src/hooks/useToast.ts` | Toast container gets `role="status"` + `aria-live="polite"`. | S |
| U20 | `SettingsModal` + `UserAvatarPicker` lack Esc-close + initial focus; 8+ other dialogs have the pattern — unintentional omission. | `SettingsModal.tsx:99`, `UserAvatarPicker.tsx:163` | Add the same keydown Esc→onClose + initial-focus ref. (Folds into X13 if done first.) | S |
| U24 | Two device-panel strings hardcoded English ("No device", "{n} devices found") while everything else uses `t()`; zh-TW users see English at the most prominent labels. | `DeviceStatus.tsx:225,330` | Add `device.no_device` + `device.devices_found` (with `{n}`, mirroring `device.scan_found`). | S |
| U27 | Inline-styled components hardcode accent literals + off-scale zIndex (CloudSyncBusyOverlay zIndex 9999 above the styles.css scale that explicitly disowns it); a token system exists, unused. | `LangToggle.tsx`, `SettingsModal.tsx`, `CloudSyncBusyOverlay.tsx`, etc. | Inline styles read `var(--accent-blue)`/`var(--z-toast)`; align overlay/toast zIndex to `--z-*`. | M |
| U28 | `UserAvatarPicker` drag mousedown handler removes its document listener only in `onUp`; closing/unmounting mid-drag leaks the listener + setState-after-unmount warning. | `frontend/src/components/UserAvatarPicker.tsx:108-130` | Track onMove/onUp via ref + `useEffect` unmount cleanup. | S |
| X10 + X11 + A15 | **Coordinate ownership.** Backend `CoordinateFormatter` (182 lines DD/DMS/DM) is dead code (only its own ~290-line tests use it; production only instantiates + echoes the format enum in WS settings). FE owns real formatting (`toFixed(6)`) but only decimal; FE has two divergent split helpers (`coords.ts` scrape, `latlng.ts` strict pair). A15: the dead DMS/DM parser adds (not subtracts) minutes/seconds for negative degrees (`-25°2'1.5"` → -24.966 instead of -25.034, ~7.5km off). | `backend/services/coord_format.py`, `backend/main.py:139`, `frontend/src/utils/coords.ts`, `frontend/src/utils/latlng.ts` | **Default decision (reconfirm at SH4 start):** delete the backend dead `CoordinateFormatter` body + dialect tests (keep the `.format` enum passthrough as a UI preference); consolidate the two FE decimal helpers (`trySplitLatLng` delegates to `parseCoord`). DMS/DM paste support is treated as a **separate opt-in feature, not in this program** — which makes A15 disappear by deletion. If Ravi instead wants DMS/DM paste: move parsing to FE (fix A15 there) + delete the backend copy. | S–M |

**SH4 manual smoke**
1. **Keyboard-only pass (U21/U22/U23):** without a mouse, Tab to a bookmark/route row, open its menu, arrow through items, activate with Enter, and close everything with Esc. *(Expected: full keyboard reachability; visible focus ring.)*
2. **Screen reader (U19):** with VoiceOver on, trigger any async action. *(Expected: the toast is announced.)*
3. **i18n (U24):** switch language to zh-TW with no device, then with a device scanning. *(Expected: no stray English in the device panel.)*
4. **Visual consistency (X13/U27):** open several dialogs. *(Expected: consistent overlay/spacing/accent; Esc closes each; no off-scale layering.)*
5. **Coordinate behavior (X10/X11/A15):** per the confirmed decision, paste a decimal coordinate into the bookmark dialog. *(Expected: parses consistently across both dialogs; the dead backend parser and its tests are gone, test count drops accordingly.)*
6. Automated gate green; test count reflects the removed coord-dialect tests.

**SH4 acceptance:** keyboard + screen-reader smoke pass; no stray English; dialogs consistent; coord decision implemented; automated gate green.

---

## 10. Coordinate Ownership Decision (X10/X11/A15/N3)

Recorded default (Section 9): **delete the backend dead parser; FE keeps decimal only; DMS/DM paste is out of scope.** This is reconfirmed with Ravi at the start of SH4 implementation. The alternative (move DMS/DM to FE) is documented there. Until then, A15/X10/X11 carry the default in the SH4 plan.

## 11. Live-Verification Register (cannot be statically verified)

These do not block code changes but are named at each batch's smoke step:
- **N2** — CloudSync overlay deadlock live repro (throttle/kill backend mid-sync) → SH1 smoke 4.
- **N4** — `useExternalChangeSubscriptions` `[ws, cbs]` churn depends on App call-site memoization → trace during SH3 N1.
- **N5** — dual-device teleport marker self-heal: does `position_update` reliably correct a failed marker? → SH1 smoke 6 / SH2 U12.
- **Real-iPhone-only:** the ~27s reconnect-window UX, sticky-denied backend behavior, watchdog auto-recovery timing → SH1 smoke 5–6, SH2 smoke 5, SH3 smoke 2.

## 12. Deliverables & Cadence

- **This spec** — the single source of truth for all 65 items and their batch mapping.
- **5 implementation plans** under `docs/superpowers/plans/2026-06-24-sh{0..4}-*.md`, each with per-step file targets, test-first instructions, and verification commands.
- **Cadence:** write **SH0 + SH1 plans first**, implement and verify them (automated + manual smoke), then write SH2–SH4 plans one at a time, adjusting from real outcomes. Each batch is a separate set of direct commits to `main` (personal-repo convention).

## 13. Out of Scope

- New features (DMS/DM coordinate paste, additional movers, new sync providers).
- Enterprise patterns (microservices, message queues, per-verb interactors, DI frameworks, observability stacks) — inappropriate for a solo personal app.
- LOC-driven rewrites of god-objects beyond the named test-first seams.
- The frontend test-infra is already present (84 vitest files), so no bootstrap step is needed.

## 14. Risk & Rollback

- Every batch is independent and ships as its own commits; revert is per-commit.
- Danger-zone changes are gated by characterization tests written first (red→green), so a regression shows as a failing test before commit.
- Full pytest + vitest + tsc + import-linter + depcruise run before each commit; a broken gate blocks the commit.
- Manual smoke is the final user-acceptance gate per batch; a batch is not "done" until its smoke steps are observed and evidenced.
