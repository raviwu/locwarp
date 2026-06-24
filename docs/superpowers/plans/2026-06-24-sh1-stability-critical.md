# SH1 — Stability-Critical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the highest-leverage reliability defects in LocWarp — silent failures, dead code, race windows, data-integrity footguns, and backend↔frontend wire-contract drift — without regressing any existing behavior.

**Architecture:** 22 bite-sized TDD tasks across 6 clusters. In the frontend WS cluster the drift fixes (delete dead subscriptions X8/X7, prune the 404 path X6, add the dropped `device_error` X9) land first under the loose `string` type, then X5 tightens `WsRouter.subscribe` to a `WsEventType` union — so `tsc` stays green after every commit and future drift becomes a compile error. Backend fixes add timeouts, remove a process-lifetime latch, close a lock window, fix import resurrection, and thread richer error reasons into the WS payload. Each danger-zone touch writes a characterization test first (red -> green). One frontend cluster gives the CloudSync busy overlay a timeout + escape hatch.

**Tech Stack:** Python 3.13 / FastAPI / pytest + pytest-asyncio (backend); React 18 + TypeScript + vitest + @testing-library/react (frontend).

## Global Constraints

- **Baseline:** `cd backend && .venv/bin/python -m pytest --collect-only -q` => **914 collected** (confirmed clean tree, 2026-06-24). Each task adds tests; the count only grows. The frontend vitest suite is also green at baseline.
- **Full green after every commit.** Run the task's new test (green), then the relevant suite. `tsc --noEmit`, vitest, pytest, lint-imports, and depcruise are all green at every commit boundary. The batch-final task (Task 23) runs the complete gate.
- **Behavior CHANGE is allowed** — this is stability work, not a refactor freeze. But every change is covered by a test in the same commit.
- **Danger-zone-test-first (HARD rule).** Any change touching `core/simulation_engine.py`, the movers, `core/device_manager.py` recovery, `api/location.py`, the `api/device.py` watchdog, or `api/phone_control.py` writes the characterization test FIRST (red) before the edit. Tasks flagged **[danger-zone]** below already order their steps this way.
- **WS payload changes are compared deep-equal JSON** (serialized `exclude_unset`/`exclude_none` so absent keys stay absent) — never literal-byte compares.
- **C1 ordering:** the WS drift cleanups (Tasks 1-4: X8, X7, X6, X9) land while `subscribe` is still loosely `string`-typed, then **X5 tightens the type LAST (Task 5)** with no out-of-union subscriptions left to flag — keeping `tsc` green at every commit. X5 then permanently turns any future event-name drift into a compile error.
- **Preserve the `WsRouter` multi-subscriber fan-out** (Set/forEach snapshot + per-handler try/catch). It is a broadcast, not route-by-type-to-single-owner.
- **Gates stay green:** backend import-linter (`lint-imports` => 7 kept, 0 broken), frontend `npx tsc --noEmit` (0 errors) and `npx depcruise src` (0 errors).
- **Personal repo:** direct commits to `main`; identity auto-set by `~/.gitconfig` includeIf — never pass `-c user.email=...`.
- Do **not** abstract `pymobiledevice3` / `usbmuxd` / tunnel-helper guts into pure cores — wrap behind the existing client only.

---


<!-- ===== C1 · WS wire contract typing + drift cleanup ===== -->

### Task 1: Delete dead `useSimulation` subscriptions (simulation_state / simulation_complete / simulation_error / random_walk_pause / random_walk_pause_end)

**Files:**
- Modify: `frontend/src/hooks/useSimulation.ts:334-351` (simulation_state), `:370-378` (simulation_complete + the three real completion subs), `:550` (random_walk_pause), `:559` (random_walk_pause_end), `:614-619` (simulation_error), `:621-628` (cleanup return)
- Test: `frontend/src/adapters/ws/eventWiring.test.tsx` (already exists — extend it with a negative-assertion `it`)

**Interfaces:**
- Consumes: none. Runs while `subscribe` is still loosely `string`-typed (X5, Task 5, tightens the type last), so removing these subscriptions cannot introduce a type error. The justification is runtime, not type: the backend never emits these five — the eventWiring guard test proves it.
- Produces: none

The backend never emits these five types — `grep -rn` for each across `backend/api backend/core backend/domain backend/main.py` returns zero `broadcast`/`_events.publish`/`_emit` sites (confirmed: zero occurrences anywhere in backend code). They are absent from `CANONICAL_BACKEND_EVENT_TYPES` in `eventWiring.test.tsx:36-73`, and the file header at `:28-30` explicitly calls them out as never-sent. The completion / pause / status behavior the UI actually needs is already covered by the LIVE subscriptions that survive: `navigation_complete` / `multi_stop_complete` / `loop_complete` (real completion events), `state_change` (drives running/idle/paused status), `pause_countdown` / `pause_countdown_end`.

- [ ] **Step 1: Write the failing test** — no new test file; add a NEGATIVE assertion to the existing `frontend/src/adapters/ws/eventWiring.test.tsx`. Append this `it` inside the existing `describe('WS event-type subscribe wiring', …)` block, before its closing `})` on line 185 (after the POSITIVE CONTROL test that spans `:173-184`):

```ts
  it('does NOT subscribe to event types the backend never emits', () => {
    const subscribed = collectSubscribedTypes()
    // These five were dead listeners — the backend has no emit site for any
    // of them (see CANONICAL_BACKEND_EVENT_TYPES). A subscription here is a
    // silent no-op that misleads future readers.
    const NEVER_EMITTED = [
      'simulation_state', 'simulation_complete', 'simulation_error',
      'random_walk_pause', 'random_walk_pause_end',
    ]
    const stillSubscribed = NEVER_EMITTED.filter((t) => subscribed.has(t))
    expect(
      stillSubscribed,
      `Hooks still subscribe to never-emitted types: ${stillSubscribed.join(', ')}`,
    ).toEqual([])
  })
```
(`collectSubscribedTypes()` is defined at `eventWiring.test.tsx:103` and returns a `Set<string>`, so `subscribed.has(t)` is valid.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/adapters/ws/eventWiring.test.tsx -t "does NOT subscribe to event types"`. Expected failure: `Hooks still subscribe to never-emitted types: simulation_state, simulation_complete, simulation_error, random_walk_pause, random_walk_pause_end` (AssertionError, arrays not equal).

- [ ] **Step 3: Implement** — remove the five subscriptions and their handlers in `frontend/src/hooks/useSimulation.ts`.

  (a) Delete the `simulation_state` block (`:334-351`):
```ts
    const offSimState = ws.subscribe('simulation_state', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setStatus({
        running: !!(e.running),
        paused: !!(e.paused),
        speed: (e.speed as number) ?? 0,
        state: e.state as string | undefined,
        distance_remaining: e.distance_remaining as number | undefined,
        distance_traveled: e.distance_traveled as number | undefined,
      })
      if (e.mode) _setMode(e.mode as any)
      if (e.progress != null) setProgress(e.progress as number)
      if (e.eta != null) setEta(e.eta as number)
      if (e.destination) setDestination(e.destination as any)
      if (e.waypoints) setWaypoints(e.waypoints as any)
    })

```
  (b) Replace the `simulation_complete` subscription + the three real completion subs (`:370-378`). The group-mode `progress:1,state:'idle'` patch (previously only on `simulation_complete`) is preserved by wrapping the three real completion events. Current:
```ts
    const offSimComplete = ws.subscribe('simulation_complete', (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid) updateRuntime(udid, { progress: 1, state: 'idle' })
      handleComplete(e)
    })
    const offNavComplete = ws.subscribe('navigation_complete', handleComplete)
    const offMultiComplete = ws.subscribe('multi_stop_complete', handleComplete)
    const offLoopComplete = ws.subscribe('loop_complete', handleComplete)
```
becomes:
```ts
    const completeWithRuntime = (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid) updateRuntime(udid, { progress: 1, state: 'idle' })
      handleComplete(e)
    }
    const offNavComplete = ws.subscribe('navigation_complete', completeWithRuntime)
    const offMultiComplete = ws.subscribe('multi_stop_complete', completeWithRuntime)
    const offLoopComplete = ws.subscribe('loop_complete', completeWithRuntime)
```
(Behavior note — allowed under the cluster's "behavior CHANGE is allowed" rule: the group-mode `progress:1,state:'idle'` runtime patch now also fires on `navigation_complete`/`multi_stop_complete`/`loop_complete` instead of only the dead `simulation_complete`. This is the intended convergence — those ARE the real completion events the backend emits.)

  (c) `random_walk_pause` (`:550`) — `handlePauseStart` is shared with `pause_countdown` (subscribed at `:549`). Delete only this line:
```ts
    const offRandomWalkPause = ws.subscribe('random_walk_pause', handlePauseStart)
```
  (d) `random_walk_pause_end` (`:559`) — `handlePauseEnd` is shared with `pause_countdown_end` (`:558`). Delete:
```ts
    const offRandomWalkPauseEnd = ws.subscribe('random_walk_pause_end', handlePauseEnd)
```
  (e) `simulation_error` (`:614-619`). Delete:
```ts
    const offSimError = ws.subscribe('simulation_error', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setError((e.message as string) ?? 'Simulation error')
    })

```
  (f) Update the cleanup return (`:621-628`). Current:
```ts
    return () => {
      offPos(); offSimState(); offSimComplete(); offNavComplete(); offMultiComplete(); offLoopComplete()
      offWpProgress(); offLapComplete(); offDdiMounting(); offDdiMounted(); offDdiMountFailed()
      offDdiNotMounted(); offTunnelDegraded(); offTunnelRecovered(); offTunnelLost()
      offDisc(); offReconn(); offConnected()
      offPauseCountdown(); offRandomWalkPause(); offPauseCountdownEnd(); offRandomWalkPauseEnd()
      offRoutePath(); offStateChange(); offSimError()
    }
```
New (drops `offSimState`, `offSimComplete`, `offRandomWalkPause`, `offRandomWalkPauseEnd`, `offSimError`; keeps `offReconn` for now — X7 removes it next):
```ts
    return () => {
      offPos(); offNavComplete(); offMultiComplete(); offLoopComplete()
      offWpProgress(); offLapComplete(); offDdiMounting(); offDdiMounted(); offDdiMountFailed()
      offDdiNotMounted(); offTunnelDegraded(); offTunnelRecovered(); offTunnelLost()
      offDisc(); offReconn(); offConnected()
      offPauseCountdown(); offPauseCountdownEnd()
      offRoutePath(); offStateChange()
    }
```
  (NOTE: `offReconn` is still referenced here — `device_reconnected` removal is X7, do it immediately after.)

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/adapters/ws/eventWiring.test.tsx`. Expected: all green incl. the new negative-assertion test.

- [ ] **Step 5: Run the broader suite** — `cd frontend && npx vitest run` — expected fully green. `cd frontend && npx tsc --noEmit` — expected **0 errors**: `subscribe` is still `string`-typed at this point (X5 is Task 5), so deleting these subscriptions cannot break the type-check. The eventWiring guard (vitest) is the gate here. `device_reconnected` is removed next in Task 2 (X7).

- [ ] **Step 6: Commit** — `git add frontend/src/hooks/useSimulation.ts frontend/src/adapters/ws/eventWiring.test.tsx` then `git commit -m "refactor(ws): delete 5 dead useSimulation subscriptions the backend never emits"`


---

### Task 2: Converge `device_reconnected` onto `device_connected`

**Files:**
- Modify: `frontend/src/hooks/useDevice.ts:87-94` (dead `device_reconnected` sub) + `:95` (cleanup return)
- Modify: `frontend/src/hooks/useSimulation.ts:513-521` (dead `device_reconnected` sub) + cleanup return (rewritten in X8)
- Modify: `backend/main.py:497` (docstring lie)
- Test: `frontend/src/adapters/ws/eventWiring.test.tsx` (extend the X8 negative-assertion list)

**Interfaces:**
- Consumes: none. Runs under the loose `string` type (X5/Task 5 tightens last). The justification is runtime: `device_reconnected` is never emitted by the backend (grep proof below) — the eventWiring guard proves the subscription is dead.
- Produces: none

The usbmux watchdog auto-connect path broadcasts `device_connected` (`backend/main.py:741`) — NOT `device_reconnected`. Grep proof: `grep -rn device_reconnected backend/` returns ONLY the stale docstring at `backend/main.py:497`; there is zero emit site. Both FE `device_reconnected` handlers (`useDevice.ts:87`, `useSimulation.ts:513`) are dead. The `device_connected` handlers in both hooks ALREADY do everything the reconnected handlers intended (re-fetch list + promote a surviving/matching device in `useDevice.ts:75-86`; clear the error banner + tunnel-reconnecting flag in `useSimulation.ts:523-538`) — `useSimulation.ts:529-532` even documents this: "watchdog auto-connect now broadcasts `device_connected` rather than `device_reconnected`". So FOLD: delete the dead subs, keep `device_connected` as the single name, and fix the backend docstring.

- [ ] **Step 1: Write the failing test** — extend the X8 negative-assertion test in `frontend/src/adapters/ws/eventWiring.test.tsx` to also forbid `device_reconnected`. Change the `NEVER_EMITTED` array added in X8 to include it:

```ts
    const NEVER_EMITTED = [
      'device_reconnected',
      'simulation_state', 'simulation_complete', 'simulation_error',
      'random_walk_pause', 'random_walk_pause_end',
    ]
```
(If X7 somehow lands before X8, instead add a standalone `it` mirroring X8's negative test but with `NEVER_EMITTED = ['device_reconnected']`.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/adapters/ws/eventWiring.test.tsx -t "does NOT subscribe to event types"`. Expected failure: `Hooks still subscribe to never-emitted types: device_reconnected`.

- [ ] **Step 3: Implement**

  (a) `frontend/src/hooks/useDevice.ts` — delete the `device_reconnected` block (`:87-94`):
```ts
    const offReconn = ws.subscribe('device_reconnected', (e: WsEvent) => {
      listDevices().then((list) => {
        setDevices(list)
        const udid = e.udid as string | undefined
        const match = udid ? list.find((d) => d.udid === udid) : null
        setConnectedDevice(match ?? list.find((d) => d.is_connected) ?? null)
      }).catch(() => {})
    })
```
  and update the cleanup (`:95`). Current:
```ts
    return () => { offDisc(); offConn(); offReconn() }
```
  →
```ts
    return () => { offDisc(); offConn() }
```
  (The `device_connected` handler at `useDevice.ts:75-86` already re-fetches the list and promotes the matching/surviving device, a superset of the reconnected handler.)

  (b) `frontend/src/hooks/useSimulation.ts` — delete the `device_reconnected` block (`:513-521`):
```ts
    const offReconn = ws.subscribe('device_reconnected', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Auto-reconnected by the usbmux watchdog after a re-plug, clear
      // the banner; the success is already visible via DeviceStatus.
      setError(null)
      setTunnelReconnecting(false)
    })

```
  and drop `offReconn()` from the cleanup return. After X8 the return reads `offDisc(); offReconn(); offConnected()` on its fourth line — change that line to `offDisc(); offConnected()`. The `device_connected` handler at `useSimulation.ts:523-538` already calls `setError(null); setTunnelReconnecting(false)`, so behavior is preserved.

  (c) `backend/main.py:497` — fix the docstring lie. Current:
```python
    * **Appearance** — a USB device showing up while we have no active
      connection triggers an auto-connect + engine rebuild, broadcasting
      device_reconnected when it succeeds. Failed attempts are throttled
```
  →
```python
    * **Appearance** — a USB device showing up while we have no active
      connection triggers an auto-connect + engine rebuild, broadcasting
      device_connected when it succeeds. Failed attempts are throttled
```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/adapters/ws/eventWiring.test.tsx`. Expected: green.

- [ ] **Step 5: Run the broader suite** — `cd frontend && npx tsc --noEmit` (expected **0 errors**; `subscribe` is still `string`-typed until X5/Task 5 — these deletions cannot affect the type-check) AND `cd frontend && npx vitest run` — expected fully green. The backend change is docstring-only (no runtime behavior change, so no characterization test required); run the wiring guard anyway: `cd backend && .venv/bin/python -m pytest tests/ -k "watchdog or device_manager or main" -q` — expected green.

- [ ] **Step 6: Commit** — `git add frontend/src/hooks/useDevice.ts frontend/src/hooks/useSimulation.ts backend/main.py frontend/src/adapters/ws/eventWiring.test.tsx` then `git commit -m "refactor(ws): converge device_reconnected onto device_connected (fold dead subs, fix watchdog docstring)"`


---

### Task 3: Delete the dead `wifiConnect` / `connectWifi` / `onWifiConnect` path (404 endpoint)

**Files:**
- Modify: `frontend/src/services/api.ts:131` (delete `wifiConnect`)
- Modify: `frontend/src/hooks/useDevice.ts:2-7` (import), `:167-190` (`connectWifi`), `:328` (return)
- Modify: `frontend/src/components/DeviceStatus.tsx:40` (prop type), `:54` (destructure), `:487` (guard)
- Test: `frontend/src/services/api.test.ts` (new)

**Interfaces:**
- Consumes: none
- Produces: none

The backend endpoint was removed in v0.1.49 — proof: `backend/api/device.py:31` reads `# /wifi/connect (legacy direct-IP WiFi for iOS <17) removed in v0.1.49.` and `grep '/wifi/connect' backend/api/device.py` returns only that comment. The FE still ships `wifiConnect()` (`api.ts:131`) hitting `POST /api/device/wifi/connect` → 404. `useDevice.connectWifi` (`:167-190`) wraps it and is returned (`:328`) but App.tsx never wires it to `DeviceStatus.onWifiConnect` (`grep onWifiConnect frontend/src/App.tsx` → no match; App.tsx:891-913 passes `onStartWifiTunnel` etc., never `onWifiConnect`). The `(onStartWifiTunnel || onWifiConnect)` guard at `DeviceStatus.tsx:487` is satisfied by `onStartWifiTunnel` alone, so dropping `onWifiConnect` is inert. Supported WiFi path is `wifiTunnelStartAndConnect` → `POST /api/device/wifi/tunnel/start-and-connect`.

- [ ] **Step 1: Write the failing test** — pin that the dead export is gone. Use the vitest style from `frontend/src/contract/endpoints.test.ts`.

```ts
// frontend/src/services/api.test.ts
import { describe, it, expect } from 'vitest'
import * as api from './api'

describe('api surface', () => {
  it('does not export wifiConnect (removed /api/device/wifi/connect, 404 since v0.1.49)', () => {
    expect('wifiConnect' in api).toBe(false)
  })

  it('keeps the supported WiFi entrypoint wifiTunnelStartAndConnect', () => {
    expect(typeof api.wifiTunnelStartAndConnect).toBe('function')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/services/api.test.ts`. Expected failure: first assertion `expected true to be false` (`wifiConnect` is still exported).

- [ ] **Step 3: Implement**

  (a) `frontend/src/services/api.ts:131` — delete:
```ts
export const wifiConnect = (ip: string) => request<any>('POST', '/api/device/wifi/connect', { ip })
```
  (b) `frontend/src/hooks/useDevice.ts` — drop `wifiConnect` from the import (`:2-7`). Current:
```ts
import {
  listDevices, connectDevice, disconnectDevice,
  wifiConnect, wifiScan,
  wifiTunnelStartAndConnect, wifiTunnelStatus, wifiTunnelStop,
  type TunnelInfo,
} from '../services/api'
```
  →
```ts
import {
  listDevices, connectDevice, disconnectDevice,
  wifiScan,
  wifiTunnelStartAndConnect, wifiTunnelStatus, wifiTunnelStop,
  type TunnelInfo,
} from '../services/api'
```
  Delete the whole `connectWifi` callback (`:167-190`):
```ts
  const connectWifi = useCallback(
    async (ip: string) => {
      try {
        const res = await wifiConnect(ip)
        const info: DeviceInfo = {
          udid: res.udid,
          name: res.name,
          ios_version: res.ios_version,
          connection_type: 'Network',
          is_connected: true,
        }
        setConnectedDevice(info)
        setDevices((prev) => {
          const filtered = prev.filter((d) => d.udid !== info.udid)
          return [...filtered, info]
        })
        return info
      } catch (err) {
        console.error('WiFi connect failed:', err)
        throw err
      }
    },
    [],
  )

```
  Remove `connectWifi` from the return object (`:328`). Current:
```ts
    connectWifi, scanWifi, wifiScanning, wifiDevices,
```
  →
```ts
    scanWifi, wifiScanning, wifiDevices,
```
  (c) `frontend/src/components/DeviceStatus.tsx` — remove the dead prop. Delete the type line (`:40`):
```ts
  onWifiConnect?: (ip: string) => Promise<any>;
```
  Delete the destructure (`:54`):
```ts
  onWifiConnect,
```
  Simplify the guard (`:487`). Current:
```tsx
      {(onStartWifiTunnel || onWifiConnect) && (
```
  →
```tsx
      {onStartWifiTunnel && (
```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/services/api.test.ts`. Expected: `2 passed`.

- [ ] **Step 5: Run the broader suite** — `cd frontend && npx tsc --noEmit` (no remaining references to `wifiConnect`/`connectWifi`/`onWifiConnect`; grep confirms these three identifiers only appear in api.ts:131, useDevice.ts:4/170, and DeviceStatus.tsx:40/54/487 — all removed here) AND `cd frontend && npx vitest run` — expected fully green.

- [ ] **Step 6: Commit** — `git add frontend/src/services/api.ts frontend/src/services/api.test.ts frontend/src/hooks/useDevice.ts frontend/src/components/DeviceStatus.tsx` then `git commit -m "refactor(ws): remove dead wifiConnect/connectWifi path to deleted /api/device/wifi/connect endpoint"`


---

### Task 4: Subscribe to `device_error` and surface it as the error banner

**Files:**
- Modify: `frontend/src/hooks/useSimulation.ts` (add `device_error` sub after the `device_connected` block at `:523-538`, add `offDeviceError` to the cleanup return)
- Modify: `frontend/src/adapters/ws/eventWiring.test.tsx:84` (remove `device_error` from `UI_IGNORED_BY_DESIGN` so the wiring guard now REQUIRES a subscriber)
- Test: `frontend/src/adapters/ws/eventWiring.test.tsx` (the existing required-subscriber assertion at `:137-149` becomes the failing test once `device_error` is required)

**Interfaces:**
- Consumes: none. `device_error` is a real backend-emitted event, so subscribing is legal under both the loose `string` type in effect now and the `WsEventType` union that X5 (Task 5) adds afterward.
- Produces: none

The backend emits `device_error` with payload `{udid, stage, error}` (`backend/api/device.py:1201` USB-fallback path: `await dm._events.publish(("device_error", {"udid": …, "stage": "usb_fallback", "error": …}))`). No FE hook subscribes today, so it is silently dropped — `eventWiring.test.tsx:84` lists it in `UI_IGNORED_BY_DESIGN` with the comment "logged server-side; no renderer banner for it". The HTTP response that triggered the fallback has already returned to the caller, so the user gets NO signal the engine rebuild failed. Surface it via the existing `error` banner (same mechanism as `tunnel_lost`), primary-device filtered like its siblings.

- [ ] **Step 1: Write the failing test** — flip `device_error` from ignored to required in the wiring guard, which makes the EXISTING `every backend-emitted event type … has a real subscriber` test (`:137-149`) fail until the subscription is added. Remove this line from `UI_IGNORED_BY_DESIGN` (`eventWiring.test.tsx:84`):
```ts
  'device_error', // logged server-side; no renderer banner for it
```
That is the entire test change — the `REQUIRED_TYPES` filter (`:95-97`) now includes `device_error`, and `collectSubscribedTypes()` (which mounts `useSimulation` at `:119`) will not contain it yet.

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/adapters/ws/eventWiring.test.tsx -t "every backend-emitted event type"`. Expected failure: `Backend emits these types but no hook subscribes to them: device_error`.

- [ ] **Step 3: Implement** — add the subscription in `frontend/src/hooks/useSimulation.ts`. Insert immediately AFTER the `offConnected = ws.subscribe('device_connected', …)` block (which ends at `:538` with `})`), matching the surrounding primary-filter + `setError` style:
```ts
    const offDeviceError = ws.subscribe('device_error', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Backend hit an internal failure outside the request/response path
      // (e.g. USB-fallback engine rebuild after a tunnel stop). Surface it on
      // the terminal banner so the user isn't left thinking the device is
      // still healthy. Payload carries {stage, error}.
      const stage = typeof e.stage === 'string' ? e.stage as string : ''
      const detail = typeof e.error === 'string' ? e.error as string : ''
      const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
      const base = isEn ? 'Device error' : '裝置發生錯誤'
      setError(detail ? `${base}: ${detail}` : (stage ? `${base} (${stage})` : base))
    })
```
Add `offDeviceError()` to the cleanup return. After X7 the return's fourth line reads `offDisc(); offConnected()` — change it to `offDisc(); offConnected(); offDeviceError()`.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/adapters/ws/eventWiring.test.tsx`. Expected: green (incl. the `allowlist hygiene` test at `:151-171` — `device_error` is no longer in the ignore set, so no overlap and no stale entry).

- [ ] **Step 5: Run the broader suite** — `cd frontend && npx tsc --noEmit` and `cd frontend && npx vitest run` — expected fully green.

- [ ] **Step 6: Commit** — `git add frontend/src/hooks/useSimulation.ts frontend/src/adapters/ws/eventWiring.test.tsx` then `git commit -m "feat(ws): surface backend device_error as the simulation error banner"`


---

### Task 5: Define a `WsEventType` union and type `WsRouter.subscribe` with it

**Files:**
- Modify: `frontend/src/contract/wsEvents.ts:1-5` (append union after the `WsEvent` type)
- Modify: `frontend/src/ports/WsRouter.ts:1-5`
- Modify: `frontend/src/adapters/ws/router.ts:1-4` (imports) + `:16` (buckets map) + `:18` (subscribe signature)
- Test: `frontend/src/contract/wsEvents.test.ts` (new)

**Interfaces:**
- Consumes: none
- Produces: `export type WsEventType` exported from `frontend/src/contract/wsEvents.ts`; `WsRouter.subscribe(type: WsEventType, handler: (e: WsEvent) => void): () => void`; `WS_EVENT_TYPES: readonly WsEventType[]` (runtime array backing the union, used by the FE⊆backend test). Later tasks (X6–X9) rely on `WsEventType` being assignable from every string literal they pass to `subscribe`.

- [ ] **Step 1: Write the failing test** — this test asserts the runtime array (source of the union) is exactly the backend-emitted vocabulary the renderer can legally subscribe to. It pins the SAME canonical list the existing wiring test (`adapters/ws/eventWiring.test.tsx:36-73`) pins, so the two never drift. Copy the import style from `frontend/src/contract/endpoints.test.ts` (vitest `describe/it/expect`, no React needed here).

```ts
// frontend/src/contract/wsEvents.test.ts
import { describe, it, expect } from 'vitest'
import { WS_EVENT_TYPES } from './wsEvents'
import type { WsEventType } from './wsEvents'

// The single source of truth for what the backend emits also lives in the
// wiring guard (adapters/ws/eventWiring.test.tsx CANONICAL_BACKEND_EVENT_TYPES).
// We re-pin the same literal list here so the typed union can never silently
// diverge from the canonical backend vocabulary. (These three lists are
// hand-maintained — keep them in lockstep; no codegen, by design.)
const CANONICAL_BACKEND_EVENT_TYPES = [
  'device_connected', 'device_disconnected', 'tunnel_recovered',
  'tunnel_degraded', 'tunnel_lost', 'device_error',
  'bookmarks_changed', 'routes_changed',
  'ddi_mounted', 'ddi_not_mounted', 'ddi_mounting', 'ddi_mount_failed',
  'position_update', 'route_path', 'state_change', 'navigation_complete',
  'waypoint_progress', 'pause_countdown', 'pause_countdown_end',
  'lap_complete', 'loop_complete', 'multi_stop_complete', 'stop_reached',
  'user_waypoint_advance', 'connection_lost', 'random_walk_arrived',
  'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
] as const

describe('WsEventType union', () => {
  it('WS_EVENT_TYPES is exactly the canonical backend-emitted vocabulary', () => {
    expect([...WS_EVENT_TYPES].sort()).toEqual(
      [...CANONICAL_BACKEND_EVENT_TYPES].sort(),
    )
  })

  it('every WS_EVENT_TYPES entry is assignable to WsEventType', () => {
    // Compile-time guard expressed at runtime: each entry typed as WsEventType.
    const typed: WsEventType[] = [...WS_EVENT_TYPES]
    expect(typed.length).toBe(WS_EVENT_TYPES.length)
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/contract/wsEvents.test.ts`. Expected failure: `Module './wsEvents' has no exported member 'WS_EVENT_TYPES'` (and `WsEventType`).

- [ ] **Step 3: Implement** — add the runtime array + union to `wsEvents.ts`, keeping `WsEvent` (and the existing `DeviceDisconnectedEvent` interface on lines 7-17) intact. Insert the new block immediately AFTER the existing `WsEvent` type on line 5 (before the blank line 6 and the `DeviceDisconnectedEvent` comment). Current top of file (`frontend/src/contract/wsEvents.ts:1-5`):
```ts
// Typed view of the WS wire frames. The backend sends {"type", "data"} and the
// renderer flattens to a single object keyed by `type` (see adapters/ws/router).
// WsEvent stays intentionally open (Record<string, unknown>) so unknown event
// types still flow through the router untouched.
export type WsEvent = { type: string } & Record<string, unknown>
```
Replace those 5 lines with:
```ts
// Typed view of the WS wire frames. The backend sends {"type", "data"} and the
// renderer flattens to a single object keyed by `type` (see adapters/ws/router).
// WsEvent stays intentionally open (Record<string, unknown>) so unknown event
// types still flow through the router untouched.
export type WsEvent = { type: string } & Record<string, unknown>

// The REAL backend event vocabulary the renderer may subscribe to. Source of
// truth: every broadcast("…") / DeviceManager._events.publish(("…", …)) /
// SimulationEngine._emit("…") literal across backend/api, backend/core,
// backend/domain. Kept in lockstep with the canonical list in
// adapters/ws/eventWiring.test.tsx and contract/wsEvents.test.ts.
// NOTE: this is a typing/lint seam, not codegen — update by hand when the
// backend gains or drops an emitted type.
export const WS_EVENT_TYPES = [
  'device_connected', 'device_disconnected', 'tunnel_recovered',
  'tunnel_degraded', 'tunnel_lost', 'device_error',
  'bookmarks_changed', 'routes_changed',
  'ddi_mounted', 'ddi_not_mounted', 'ddi_mounting', 'ddi_mount_failed',
  'position_update', 'route_path', 'state_change', 'navigation_complete',
  'waypoint_progress', 'pause_countdown', 'pause_countdown_end',
  'lap_complete', 'loop_complete', 'multi_stop_complete', 'stop_reached',
  'user_waypoint_advance', 'connection_lost', 'random_walk_arrived',
  'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
] as const

// String-literal union of the backend vocabulary. subscribe() is typed with
// this so a typo'd key (e.g. 'state_changed') is now a COMPILE error.
export type WsEventType = (typeof WS_EVENT_TYPES)[number]
```

Then tighten the port. Current (`frontend/src/ports/WsRouter.ts:1-5`):
```ts
import type { WsEvent } from '../contract/wsEvents'

export interface WsRouter {
  subscribe(type: string, handler: (e: WsEvent) => void): () => void
}
```
New:
```ts
import type { WsEvent, WsEventType } from '../contract/wsEvents'

export interface WsRouter {
  subscribe(type: WsEventType, handler: (e: WsEvent) => void): () => void
}
```

Then the concrete impl. Current imports (`frontend/src/adapters/ws/router.ts:1-4`):
```ts
import type { WsEvent } from '../../contract/wsEvents'
import type { WsRouter } from '../../ports/WsRouter'

type Handler = (e: WsEvent) => void
```
New:
```ts
import type { WsEvent, WsEventType } from '../../contract/wsEvents'
import type { WsRouter } from '../../ports/WsRouter'

type Handler = (e: WsEvent) => void
```
Then key the single `buckets` map and the inner `subscribe` signature on `WsEventType`. Current (`frontend/src/adapters/ws/router.ts:16` and `:18`):
```ts
  const buckets = new Map<string, Set<Handler>>()

  function subscribe(type: string, handler: Handler): () => void {
```
New:
```ts
  const buckets = new Map<WsEventType, Set<Handler>>()

  function subscribe(type: WsEventType, handler: Handler): () => void {
```
Leave `dispatch(e: WsEvent)` (`:33-45`) UNCHANGED — it must still accept any wire frame (including unknown types like the `'never_registered'` case in `router.test.ts:81`) and silently no-op when no bucket exists. Do NOT change the `[...set]` snapshot / `for...of` fan-out or the per-handler try/catch.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/contract/wsEvents.test.ts`. Expected: `2 passed`.

- [ ] **Step 5: Run the broader suite** — `cd frontend && npx vitest run src/adapters/ws/router.test.ts src/adapters/ws/eventWiring.test.tsx` — expected all green (router.test.ts only subscribes to in-union types: device_disconnected / position_update / state_change / device_connected / tunnel_recovered; eventWiring's recordingRouter still compiles). Type-check is the real gate: `cd frontend && npx tsc --noEmit`.

  NOTE: this task runs LAST in C1 by design. Tasks 1-4 (X8, X7, X6, X9) already removed every out-of-union subscription (`simulation_state` / `simulation_complete` / `simulation_error` / `random_walk_pause` / `random_walk_pause_end` / `device_reconnected`) and the dead `wifiConnect` path while `subscribe` was still `string`-typed. So tightening `subscribe` to `WsEventType` here leaves nothing to flag — **`tsc --noEmit` is GREEN after this commit**. From now on any `subscribe('typo')` with a non-vocabulary string is a compile error. (If `tsc` reports an error here, a dead subscription was missed in Tasks 1-2 — fix that subscription, do not widen the union.)

- [ ] **Step 6: Commit** — `git add frontend/src/contract/wsEvents.ts frontend/src/contract/wsEvents.test.ts frontend/src/ports/WsRouter.ts frontend/src/adapters/ws/router.ts` then `git commit -m "feat(ws): type WsRouter.subscribe with a WsEventType union of the backend vocabulary"`


---


<!-- ===== C2 · Import data-integrity + recent test-isolation ===== -->

### Task 6: Stamp `updated_at=now` on `import_json` items so they survive the `_save()` merge (bookmark + route)

**Files:**
- Modify: `backend/services/bookmarks.py:585-603` (the bookmark loop inside `BookmarkManager.import_json`, which spans 564-603)
- Modify: `backend/services/route_store.py:414-436` (the route loop inside `RouteManager.import_json`, which spans 391-436)
- Test: `backend/tests/test_import_json_resurrect.py` (Create)

**Interfaces:**
- Consumes: `force_seed_items(items: list, now_iso: str) -> list` from `domain.store_merge` (already imported in `bookmarks.py:21`; must be added to `route_store.py` imports). `BookmarkManager.import_json(data: str) -> dict`, `RouteManager.import_json(data: str) -> int`.
- Produces: none (behavior change only — return shapes unchanged: bookmark returns `{"imported": N, "skipped": M}`, route returns `int`).

**Danger-zone:** this touches the store `_save()` path (`merge_stores` runs inside `_save`). Characterization-test-first — write the red test in Step 1 before editing.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_import_json_resurrect.py` with the FULL code below. It mirrors the fixture/style of `tests/test_force_seed.py` (factory + per-module file monkeypatch) and `tests/test_route_tombstones.py` (the `_route()` / `Coordinate` helper). The autouse `_isolate_real_data_paths` in `conftest.py` already redirects paths, but neighboring tests still patch the module-level file name explicitly, so do the same here for parity (patch `BOOKMARKS_FILE` / `ROUTES_FILE` plus the `_CONFIG_DEFAULT_*` sentinel to `object()` so `_*_path_default()` returns the patched path).

```python
"""User import_json must stamp updated_at=now on incoming items so a
locally-deleted id (real-timestamp tombstone) is RESURRECTED by a re-import,
not silently killed by merge_stores inside _save(). Mirrors the catalog path
(import_catalog already does this via force_seed_items); import_json did not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.schemas import Bookmark, Coordinate, SavedRoute


@pytest.fixture
def bm_mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


@pytest.fixture
def rt_mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    from bootstrap.factories import make_route_manager
    return make_route_manager()


def test_bookmark_import_json_resurrects_deleted_id(bm_mgr):
    # Create a real bookmark, capture its id, then delete it -> real-ts tombstone.
    created = bm_mgr.create_bookmark(name="Place", lat=1.0, lng=2.0)
    bm_id = created.id
    bm_mgr.delete_bookmark(bm_id)
    assert any(t.id == bm_id for t in bm_mgr.store.tombstones)
    assert not any(b.id == bm_id for b in bm_mgr.store.bookmarks)

    # Re-import the SAME id with an empty updated_at (the pitfall). Without the
    # fix, merge_stores in _save() lets the tombstone win and the item dies.
    payload = json.dumps({
        "categories": [],
        "bookmarks": [
            {"id": bm_id, "name": "Place (reimported)", "lat": 1.0, "lng": 2.0,
             "category_id": "default", "created_at": "", "last_used_at": "",
             "updated_at": ""},
        ],
    })
    result = bm_mgr.import_json(payload)
    assert result == {"imported": 1, "skipped": 0}

    # Alive on disk — the load-bearing assertion (merge ran inside _save).
    on_disk = json.loads(Path(bm_mgr._bookmarks_path()).read_text())
    assert bm_id in {b["id"] for b in on_disk["bookmarks"]}, (
        "import_json must stamp updated_at so the item beats the tombstone on disk"
    )
    assert any(b.id == bm_id for b in bm_mgr.store.bookmarks)


def test_route_import_json_resurrects_deleted_id(rt_mgr):
    created = rt_mgr.create_route(SavedRoute(
        name="R",
        waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
        profile="walking",
        category_id="default",
    ))
    rt_id = created.id
    rt_mgr.delete_route(rt_id)
    assert any(t.id == rt_id for t in rt_mgr.store.tombstones)
    assert not any(r.id == rt_id for r in rt_mgr.store.routes)

    # Re-import the SAME id with empty updated_at.
    payload = json.dumps({
        "categories": [],
        "routes": [
            {"id": rt_id, "name": "R (reimported)", "profile": "walking",
             "category_id": "default", "created_at": "",
             "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}],
             "updated_at": ""},
        ],
    })
    imported = rt_mgr.import_json(payload)
    assert imported == 1

    on_disk = json.loads(Path(rt_mgr._routes_path()).read_text())
    assert rt_id in {r["id"] for r in on_disk["routes"]}, (
        "route import_json must stamp updated_at so the item beats the tombstone on disk"
    )
    assert any(r.id == rt_id for r in rt_mgr.store.routes)
```

Note: the route test imports the SAME id back. The task that fixes A18 (route idempotency) makes `import_json` skip an existing-LIVE id; here the id is DELETED (tombstoned, not live), so it is re-imported, not skipped — verified the two behaviors do not conflict (a deleted id is absent from `self.store.routes` after `delete_route`, so the A18 live-id skip never fires for it).

- [ ] **Step 2: Run tests, verify they fail** — `cd backend && .venv/bin/python -m pytest tests/test_import_json_resurrect.py -v`. Verified: both tests FAIL at the on-disk assertion (`AssertionError: ... must stamp updated_at so the item beats the tombstone on disk` — actual run showed `assert '<uuid>' in set()`) because the deleted id's real-timestamp tombstone out-votes the empty-`updated_at` re-import inside `_save()`.

- [ ] **Step 3: Implement** — stamp incoming items in both managers.

**Bookmark** (`backend/services/bookmarks.py`). `force_seed_items` is already imported at line 21. Replace the loop (currently lines 585-603):

```python
        existing_bm_ids = {b.id for b in self.store.bookmarks}
        imported = 0
        skipped = 0
        for bm in incoming.bookmarks:
            if bm.id not in existing_bm_ids:
                # Ensure the bookmark's category exists
                if bm.category_id not in existing_cat_ids:
                    bm.category_id = "default"
                enrich_bookmark(bm)  # fill any geo fields the import lacked
                self.store.bookmarks.append(bm)
                existing_bm_ids.add(bm.id)
                imported += 1
            else:
                skipped += 1

        if imported:
            self._save()
```

with (stamp `updated_at=now` on every appended item so it beats any prior real-timestamp tombstone in the `_save()` merge — the same fix `import_catalog` already applies via `force_seed_items`):

```python
        now = _now_iso()
        existing_bm_ids = {b.id for b in self.store.bookmarks}
        imported = 0
        skipped = 0
        for bm in incoming.bookmarks:
            if bm.id not in existing_bm_ids:
                # Ensure the bookmark's category exists
                if bm.category_id not in existing_cat_ids:
                    bm.category_id = "default"
                enrich_bookmark(bm)  # fill any geo fields the import lacked
                # Stamp updated_at=now so a re-imported id whose prior delete
                # left a real-timestamp tombstone is resurrected by the
                # merge_stores _alive() check inside _save() (the
                # empty-updated_at pitfall). Mirrors import_catalog.
                force_seed_items([bm], now)
                self.store.bookmarks.append(bm)
                existing_bm_ids.add(bm.id)
                imported += 1
            else:
                skipped += 1

        if imported:
            self._save()
```

**Route** (`backend/services/route_store.py`). First add the import — line 31 currently reads `from services.store_merge import merge_stores`; add a line after it:

```python
from services.store_merge import merge_stores
from domain.store_merge import force_seed_items
```

Then in `import_json`, replace the route loop (currently lines 414-436):

```python
        existing_route_ids = {r.id for r in self.store.routes}
        imported = 0
        for r in incoming.routes:
            if r.category_id not in existing_cat_ids:
                r.category_id = "default"
            if not r.id or r.id in existing_route_ids:
                r.id = str(uuid.uuid4())
            siblings = [
                s for s in self.store.routes
                if s.category_id == r.category_id and s.name == r.name
            ]
            if siblings:
                r.name = f"{r.name} (匯入)"
            if not r.created_at:
                r.created_at = _now_iso()
            self.store.routes.append(r)
            existing_route_ids.add(r.id)
            imported += 1

        if imported:
            self._save()
        logger.info("Imported %d routes", imported)
        return imported
```

with (add a `now = _now_iso()` at the top of the loop body and the `force_seed_items` stamp just before append — leave the rest unchanged so this task is independent of A18's idempotency rewrite of this same loop; whoever lands second keeps the `force_seed_items` call):

```python
        now = _now_iso()
        existing_route_ids = {r.id for r in self.store.routes}
        imported = 0
        for r in incoming.routes:
            if r.category_id not in existing_cat_ids:
                r.category_id = "default"
            if not r.id or r.id in existing_route_ids:
                r.id = str(uuid.uuid4())
            siblings = [
                s for s in self.store.routes
                if s.category_id == r.category_id and s.name == r.name
            ]
            if siblings:
                r.name = f"{r.name} (匯入)"
            if not r.created_at:
                r.created_at = now
            # Stamp updated_at=now so a re-imported id whose prior delete left a
            # real-timestamp tombstone is resurrected by merge_stores in _save()
            # (the empty-updated_at pitfall). Mirrors bookmark import + catalog.
            force_seed_items([r], now)
            self.store.routes.append(r)
            existing_route_ids.add(r.id)
            imported += 1

        if imported:
            self._save()
        logger.info("Imported %d routes", imported)
        return imported
```

- [ ] **Step 4: Run tests, verify they pass** — `cd backend && .venv/bin/python -m pytest tests/test_import_json_resurrect.py -v`. Expected: 2 passed (verified).

- [ ] **Step 5 (danger-zone): Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_bookmark_import_formats.py tests/test_force_seed.py tests/test_bookmark_tombstones.py tests/test_route_tombstones.py tests/test_route_store.py tests/test_store_merge.py -v` then the full suite `cd backend && .venv/bin/python -m pytest -q`. Expected: all green; this task adds 2 tests and removes none (collection increases by 2). Watch `tests/test_bookmark_import_formats.py::test_full_store_import_reports_skipped_duplicates` — duplicates are still skipped (the stamp only applies to newly-appended items, not the skip branch), so it must stay `{"imported": 0, "skipped": 2}` (verified green).

- [ ] **Step 6: Commit** — `git add backend/services/bookmarks.py backend/services/route_store.py backend/tests/test_import_json_resurrect.py` then:

```
fix(import): stamp updated_at=now on import_json items so re-import resurrects a deleted id

User import_json appended incoming items with their payload updated_at (often
""). A locally-deleted id has a real-timestamp tombstone, so merge_stores in
_save() let the tombstone win and the re-imported item silently died — the same
empty-updated_at pitfall import_catalog already guards against via
force_seed_items. Apply force_seed_items to each newly-appended bookmark AND
route. Duplicates (live id) are still skipped; deleted ids resurrect.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
```


---

### Task 7: Make `RouteManager.import_json` idempotent — skip a live existing id instead of always minting a new uuid

**Files:**
- Modify: `backend/services/route_store.py:414-436` (the route loop inside `RouteManager.import_json`, which spans 391-436)
- Test: `backend/tests/test_route_import_idempotent.py` (Create)

**Interfaces:**
- Consumes: `RouteManager.import_json(data: str) -> int`. `make_route_manager()` from `bootstrap.factories`. `SavedRoute`, `Coordinate` from `models.schemas`.
- Produces: none (behavior change — return type stays `int`).

**Ordering vs A13:** both this task and the A13 task edit the same route loop in `import_json`. If the A13 task lands first it adds a `now = _now_iso()` at the top of the loop body and a `force_seed_items([r], now)` call before `self.store.routes.append(r)` — KEEP both when applying this skip logic (replace `r.created_at = _now_iso()` with `r.created_at = now`). If this task lands first, the A13 task adds the stamp on top. The two changes compose: skip when the incoming id is an existing LIVE route (this task); stamp the items that ARE appended (A13). A deleted/tombstoned id is NOT in `self.store.routes`, so it is not "existing" here and still re-imports — verified by running both new test files together (all pass).

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_route_import_idempotent.py`. Style mirrors `tests/test_route_tombstones.py` (factory fixture + `_route()` / `Coordinate` helper) and the bookmark idempotency assertion in `tests/test_bookmark_import_formats.py::test_full_store_import_reports_skipped_duplicates`.

```python
"""RouteManager.import_json must be idempotent: re-importing the same bundle
(same route ids) must NOT duplicate every route. The bookmark importer skips
existing ids; routes used to always mint a fresh uuid + "(匯入)" suffix, so a
double-import doubled the store.
"""
from __future__ import annotations

import json

import pytest

from models.schemas import Coordinate, SavedRoute


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    from bootstrap.factories import make_route_manager
    return make_route_manager()


def _bundle() -> str:
    return json.dumps({
        "categories": [],
        "routes": [
            {"id": "route-a", "name": "Alpha", "profile": "walking",
             "category_id": "default", "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00",
             "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}]},
        ],
    })


def test_first_import_adds_one_route(mgr):
    imported = mgr.import_json(_bundle())
    assert imported == 1
    assert sum(1 for r in mgr.store.routes if r.id == "route-a") == 1


def test_double_import_does_not_duplicate(mgr):
    assert mgr.import_json(_bundle()) == 1
    # Re-import the SAME bundle: the live id 'route-a' must be skipped, not
    # re-minted with a fresh uuid + "(匯入)" suffix.
    second = mgr.import_json(_bundle())
    assert second == 0, "re-importing the same live id must import nothing"
    assert sum(1 for r in mgr.store.routes if r.name == "Alpha") == 1
    assert not any("(匯入)" in r.name for r in mgr.store.routes)
    assert len([r for r in mgr.store.routes]) == 1
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_route_import_idempotent.py -v`. Verified: `test_double_import_does_not_duplicate` FAILS — `second` is `1` (a new uuid was minted) and the store has two routes, one named `Alpha (匯入)`. `test_first_import_adds_one_route` passes either way.

- [ ] **Step 3: Implement** — in `backend/services/route_store.py`, change `import_json`'s route loop so an incoming id that is ALREADY in `existing_route_ids` (a live route) is SKIPPED, mirroring the bookmark importer. The id-collision-mints-new-uuid branch only fires for empty ids now. Current code (lines 414-436):

```python
        existing_route_ids = {r.id for r in self.store.routes}
        imported = 0
        for r in incoming.routes:
            if r.category_id not in existing_cat_ids:
                r.category_id = "default"
            if not r.id or r.id in existing_route_ids:
                r.id = str(uuid.uuid4())
            siblings = [
                s for s in self.store.routes
                if s.category_id == r.category_id and s.name == r.name
            ]
            if siblings:
                r.name = f"{r.name} (匯入)"
            if not r.created_at:
                r.created_at = _now_iso()
            self.store.routes.append(r)
            existing_route_ids.add(r.id)
            imported += 1

        if imported:
            self._save()
        logger.info("Imported %d routes", imported)
        return imported
```

Replace with (skip a live existing id; keep the empty-id uuid mint + the same-category same-name "(匯入)" suffix for genuinely-new routes):

```python
        existing_route_ids = {r.id for r in self.store.routes}
        imported = 0
        skipped = 0
        for r in incoming.routes:
            # Idempotency: a route whose id already exists in the live store is
            # the same route (e.g. a re-imported export) — skip it instead of
            # minting a fresh uuid, which used to duplicate every route on a
            # second import. Mirrors BookmarkManager.import_json's id-skip.
            if r.id and r.id in existing_route_ids:
                skipped += 1
                continue
            if r.category_id not in existing_cat_ids:
                r.category_id = "default"
            if not r.id:
                r.id = str(uuid.uuid4())
            siblings = [
                s for s in self.store.routes
                if s.category_id == r.category_id and s.name == r.name
            ]
            if siblings:
                r.name = f"{r.name} (匯入)"
            if not r.created_at:
                r.created_at = _now_iso()
            self.store.routes.append(r)
            existing_route_ids.add(r.id)
            imported += 1

        if imported:
            self._save()
        logger.info("Imported %d routes (%d skipped as duplicates)", imported, skipped)
        return imported
```

Note: `_now_iso()` is used here (not a captured `now`) to match the current code; if the A13 task already introduced a `now = _now_iso()` at the top of the loop and a `force_seed_items([r], now)` call, preserve both — replace `r.created_at = _now_iso()` with `r.created_at = now` and keep the `force_seed_items([r], now)` line before the append.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_route_import_idempotent.py -v`. Expected: 2 passed (verified).

- [ ] **Step 5: Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_route_store.py tests/test_route_tombstones.py tests/test_route_di_char.py tests/test_route_watcher.py -v` then `cd backend && .venv/bin/python -m pytest -q`. Expected: all green. (No existing test asserted the old always-mint-uuid behavior — confirmed `grep -rn import_json tests/test_route*.py` returns nothing — so nothing regresses.)

- [ ] **Step 6: Commit** — `git add backend/services/route_store.py backend/tests/test_route_import_idempotent.py` then:

```
fix(route-import): skip an existing live route id so a double-import doesn't duplicate

RouteManager.import_json always minted a fresh uuid + "(匯入)" suffix on an id
collision, so re-importing the same export doubled every route. Mirror
BookmarkManager.import_json: skip when the incoming id is already a live route.
Empty ids still get a uuid; genuinely-new same-name routes still get the suffix.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
```


---

### Task 8: Extend the autouse isolation guard to patch `RECENT_PLACES_FILE` + reset `recent._singleton`

**Files:**
- Modify: `backend/tests/conftest.py:36-60` (the `bm/rt/st`-block onward inside the `_isolate_real_data_paths` autouse fixture)
- Test: `backend/tests/test_recent_isolation.py` (Create)

**Interfaces:**
- Consumes: `config.RECENT_PLACES_FILE` (module-level `Path` = `DATA_DIR / "recent_places.json"`, captured at import time in `services.recent` via `from config import RECENT_PLACES_FILE`). `services.recent.get_manager()` / `services.recent._singleton`.
- Produces: none (test-infra hardening only — extends an existing autouse fixture).

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_recent_isolation.py`. It asserts that after the autouse guard runs, `services.recent.RECENT_PLACES_FILE` points inside the per-test `tmp_path` and the `recent` singleton is fresh — so pushing a recent place writes to tmp, never the real `~/.locwarp/recent_places.json`.

IMPORTANT: anchor the assertions on `tmp_path` (which pytest owns and guarantees unique per test), NOT on `config.DATA_DIR`. A separate test elsewhere in the suite reloads the `config` module, which discards the autouse monkeypatch of `config.DATA_DIR` and snaps it back to the real `~/.locwarp` path. Anchoring on `config.DATA_DIR` makes this test fail intermittently in the full-suite run (the autouse-patched `recent.RECENT_PLACES_FILE` is correct tmp, but `config.DATA_DIR` is the leaked real path, so the `.startswith(config.DATA_DIR)` comparison is False). Comparing directly to `tmp_path / "recent_places.json"` is immune to that leak.

```python
"""The autouse _isolate_real_data_paths guard (conftest.py) must redirect
RECENT_PLACES_FILE to the per-test tmp dir AND reset services.recent._singleton,
so a recent-places write can never touch the user's real ~/.locwarp file and one
test's singleton cannot leak into the next. RECENT_PLACES_FILE is captured at
import time inside services.recent, so patching config alone is not enough — the
guard must also clear the singleton so get_manager() rebuilds against the patch.
"""
from __future__ import annotations

from pathlib import Path


def test_recent_places_file_is_redirected_to_tmp(tmp_path):
    # The autouse guard redirected RECENT_PLACES_FILE into this test's tmp_path.
    import services.recent as recent
    assert Path(recent.RECENT_PLACES_FILE) == tmp_path / "recent_places.json"


def test_recent_singleton_is_reset_and_writes_into_tmp(tmp_path):
    import services.recent as recent
    # Guard must have reset the singleton so a fresh manager binds the patched
    # path; build it and push an entry.
    assert recent._singleton is None, "guard must reset _singleton before each test"
    mgr = recent.get_manager()
    mgr.push(lat=10.0, lng=20.0, kind="teleport", name="X")
    # The entry must land in the patched (tmp) file, proving real data is safe.
    written = Path(recent.RECENT_PLACES_FILE)
    assert written == tmp_path / "recent_places.json"
    assert written.exists()
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_recent_isolation.py -v`. Verified: BOTH tests FAIL before the conftest change — `recent.RECENT_PLACES_FILE` still points at the import-time real `~/.locwarp/recent_places.json` (the guard never patched it), so neither equals `tmp_path / "recent_places.json"` and the singleton reset never happens.

- [ ] **Step 3: Implement** — extend the `_isolate_real_data_paths` fixture in `backend/tests/conftest.py`. Add an `rp` path alongside the existing `bm`/`rt`/`st`, patch `config.RECENT_PLACES_FILE`, and (in the existing `if "services.bookmarks" ...` style block) patch the module-level copy in `services.recent` plus reset its `_singleton`.

Current code (lines 36-60):

```python
    bm = tmp_path / "bookmarks.json"
    rt = tmp_path / "routes.json"
    st = tmp_path / "settings.json"

    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "SETTINGS_FILE", st, raising=False)
    monkeypatch.setattr(config, "_DEFAULT_BOOKMARKS_FILE", bm, raising=False)
    monkeypatch.setattr(config, "ROUTES_FILE", rt, raising=False)
    # BACKUP_DIR is derived from DATA_DIR at import time, so patching DATA_DIR
    # alone leaves it pointing at the real ~/.locwarp/backups. Redirect it too,
    # or a backup test would write real user data (the exact hazard above).
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups", raising=False)

    # Module-level copies captured at import time in the runtime modules.
    if "main" in sys.modules:
        monkeypatch.setattr(sys.modules["main"], "SETTINGS_FILE", st, raising=False)
    if "services.bookmarks" in sys.modules:
        sb = sys.modules["services.bookmarks"]
        monkeypatch.setattr(sb, "BOOKMARKS_FILE", bm, raising=False)
        monkeypatch.setattr(sb, "_CONFIG_DEFAULT_BOOKMARKS_FILE", bm, raising=False)
    if "services.route_store" in sys.modules:
        sr = sys.modules["services.route_store"]
        monkeypatch.setattr(sr, "ROUTES_FILE", rt, raising=False)
        monkeypatch.setattr(sr, "_CONFIG_DEFAULT_ROUTES_FILE", rt, raising=False)
```

Replace with (adds `rp`, patches `config.RECENT_PLACES_FILE`, patches the import-time copy in `services.recent`, and resets `_singleton`):

```python
    bm = tmp_path / "bookmarks.json"
    rt = tmp_path / "routes.json"
    st = tmp_path / "settings.json"
    rp = tmp_path / "recent_places.json"

    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "SETTINGS_FILE", st, raising=False)
    monkeypatch.setattr(config, "_DEFAULT_BOOKMARKS_FILE", bm, raising=False)
    monkeypatch.setattr(config, "ROUTES_FILE", rt, raising=False)
    monkeypatch.setattr(config, "RECENT_PLACES_FILE", rp, raising=False)
    # BACKUP_DIR is derived from DATA_DIR at import time, so patching DATA_DIR
    # alone leaves it pointing at the real ~/.locwarp/backups. Redirect it too,
    # or a backup test would write real user data (the exact hazard above).
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups", raising=False)

    # Module-level copies captured at import time in the runtime modules.
    if "main" in sys.modules:
        monkeypatch.setattr(sys.modules["main"], "SETTINGS_FILE", st, raising=False)
    if "services.bookmarks" in sys.modules:
        sb = sys.modules["services.bookmarks"]
        monkeypatch.setattr(sb, "BOOKMARKS_FILE", bm, raising=False)
        monkeypatch.setattr(sb, "_CONFIG_DEFAULT_BOOKMARKS_FILE", bm, raising=False)
    if "services.route_store" in sys.modules:
        sr = sys.modules["services.route_store"]
        monkeypatch.setattr(sr, "ROUTES_FILE", rt, raising=False)
        monkeypatch.setattr(sr, "_CONFIG_DEFAULT_ROUTES_FILE", rt, raising=False)
    if "services.recent" in sys.modules:
        rc = sys.modules["services.recent"]
        # RECENT_PLACES_FILE is captured at import time (from config import ...).
        monkeypatch.setattr(rc, "RECENT_PLACES_FILE", rp, raising=False)
        # The module caches a process-wide RecentPlacesManager singleton bound
        # to the import-time path; reset it so get_manager() rebuilds against
        # the patched tmp path and one test's list cannot leak into the next.
        monkeypatch.setattr(rc, "_singleton", None, raising=False)
```

Note: `services.recent` is only patched when already imported (`if "services.recent" in sys.modules`), matching how the other module copies are guarded. The `config.RECENT_PLACES_FILE` patch always applies, so a first-time `import services.recent` inside a test captures the already-patched value. On the very first load `_singleton` is `None` anyway; the reset matters once the module is loaded and a prior test built the singleton.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_recent_isolation.py -v`. Expected: 2 passed (verified).

- [ ] **Step 5: Run the broader suite** — `cd backend && .venv/bin/python -m pytest -q`. Expected: all green; this task adds 2 tests and removes none, collection increases by 2 (verified the full suite passes with the `tmp_path`-anchored assertions; an earlier `config.DATA_DIR`-anchored draft failed here in the full run because of the config-reload leak described in Step 1). The change only adds redirects/resets; no production code touched.

- [ ] **Step 6: Commit** — `git add backend/tests/conftest.py backend/tests/test_recent_isolation.py` then:

```
test(isolation): redirect RECENT_PLACES_FILE + reset recent singleton in the data-path guard

The autouse _isolate_real_data_paths guard redirected bookmarks/routes/settings/
backups but not RECENT_PLACES_FILE, and never reset services.recent._singleton.
A recent-places test could write the user's real ~/.locwarp/recent_places.json
or leak a stale singleton across tests — the exact hazard the guard exists to
prevent. Patch the config constant, the import-time module copy, and reset the
singleton.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
```


---


<!-- ===== C3 · Tunnel-helper timeout, geo-offline latch, DM lock, migrate race ===== -->

### Task 9: TunnelHelperClient.call() — wrap readline in asyncio.wait_for and drop the connection on timeout

**Files:**
- Modify: `backend/services/tunnel_helper_client.py:128-145` (the `call` signature + readline block) and `:31` (add the module constant just below `DEFAULT_STATUS_PATH`)
- Test: `backend/tests/test_tunnel_helper_client.py`

**Interfaces:**
- Consumes: none
- Produces: `TunnelHelperClient.call(method, read_timeout=RPC_READ_TIMEOUT_S, **params)` gains keyword arg `read_timeout: float`; on read timeout it raises `TimeoutError` and sets `self._reader = self._writer = None` (so `is_connected` is `False` and the next caller must reconnect). Module-level constant `RPC_READ_TIMEOUT_S = 30.0`. The module already has `logger = logging.getLogger(__name__)` (line 28), so the new `logger.warning` call is valid.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_tunnel_helper_client.py`. The fake server here accepts the request line but never writes a response, simulating a half-open helper socket. Reuse the existing module imports (`asyncio`, `json`, `pytest`, `Path`, `TunnelHelperClient`, `HelperError`) already at the top of the file:

```python
@pytest.mark.asyncio
async def test_call_times_out_and_drops_connection(tmp_path):
    """A half-open helper that never replies must not hang call() forever.
    readline is bounded by read_timeout; on timeout we raise TimeoutError and
    drop the connection so the next caller reconnects instead of deadlocking
    behind the in-flight _lock."""
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    async def on_conn(reader, writer):
        # Read the request but deliberately never write a response.
        await reader.readline()
        await asyncio.sleep(60)  # hang

    server = await asyncio.start_unix_server(on_conn, path=str(sock))
    try:
        status.write_text("READY\n")
        client = TunnelHelperClient(sock_path=sock, status_path=status)
        await client.connect(timeout=2.0)
        assert client.is_connected is True
        with pytest.raises(TimeoutError):
            await client.call("ping", read_timeout=0.2)
        # connection was dropped so a later caller reconnects, not deadlock
        assert client.is_connected is False
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_call_default_read_timeout_constant():
    """RPC_READ_TIMEOUT_S defaults above the helper-side open bound."""
    from services.tunnel_helper_client import RPC_READ_TIMEOUT_S
    assert RPC_READ_TIMEOUT_S >= 30.0
```

- [ ] **Step 2: Run test, verify it fails** — the repo has NO global pytest timeout (`pytest.ini` only sets `asyncio_mode = strict`; `pytest-timeout` is not installed), so the unbounded-read test would hang indefinitely against the current code. Verify each new test the bounded way:

  1. Constant test (clean red): `cd backend && .venv/bin/python -m pytest tests/test_tunnel_helper_client.py::test_call_default_read_timeout_constant -v`. Expected: errors with `ImportError: cannot import name 'RPC_READ_TIMEOUT_S' from 'services.tunnel_helper_client'`.
  2. Hang test (red == it hangs, since `readline` is unbounded with no `wait_for` yet). Bound it with a shell `timeout` so the run terminates: `cd backend && timeout 10 .venv/bin/python -m pytest tests/test_tunnel_helper_client.py::test_call_times_out_and_drops_connection -v`. Expected: the `timeout` wrapper KILLS the run (exit code 124) — that hang IS the bug this task removes. (After Step 3 it will instead complete in well under a second.)

- [ ] **Step 3: Implement** — in `backend/services/tunnel_helper_client.py`.

Add the module constant just below `DEFAULT_STATUS_PATH` (current line 31):

```python
DEFAULT_STATUS_PATH = Path("/tmp/locwarp-helper.status")

# Upper bound on how long call() waits for a single RPC response line. On
# timeout we drop the connection and the next caller reconnects, so a
# half-open socket can never hang the backend's helper _lock indefinitely.
RPC_READ_TIMEOUT_S = 30.0
```

Replace the current `call` signature + readline block. Current code (lines 128-144):

```python
    async def call(self, method: str, **params: Any) -> Any:
        if self._writer is None or self._reader is None:
            raise RuntimeError("helper client is not connected")
        async with self._lock:
            self._next_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": params,
            }
            self._writer.write((json.dumps(req) + "\n").encode("utf-8"))
            await self._writer.drain()

            line = await self._reader.readline()
            if not line:
                raise RuntimeError("helper closed the connection")
```

New code (every existing caller passes only keyword params — `udid=`, `ip=`, etc. — so `read_timeout` as the second positional parameter never captures a real RPC param, and it is NOT forwarded into the JSON-RPC `params`):

```python
    async def call(
        self, method: str, read_timeout: float = RPC_READ_TIMEOUT_S, **params: Any
    ) -> Any:
        if self._writer is None or self._reader is None:
            raise RuntimeError("helper client is not connected")
        async with self._lock:
            self._next_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": params,
            }
            self._writer.write((json.dumps(req) + "\n").encode("utf-8"))
            await self._writer.drain()

            try:
                line = await asyncio.wait_for(
                    self._reader.readline(), timeout=read_timeout
                )
            except (asyncio.TimeoutError, TimeoutError):
                # Half-open helper socket: the request was written but no
                # response came back. Drop the connection so the next caller
                # reconnects instead of serialising behind a dead in-flight
                # RPC on this _lock.
                logger.warning(
                    "helper RPC %r timed out after %.1fs; dropping connection",
                    method, read_timeout,
                )
                self._reader = None
                self._writer = None
                raise TimeoutError(
                    f"helper RPC {method!r} timed out after {read_timeout}s"
                )
            if not line:
                raise RuntimeError("helper closed the connection")
```

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_tunnel_helper_client.py -v`. Expected: all tests in the file PASS (the two new ones plus the existing 7), and `test_call_times_out_and_drops_connection` completes in well under a second.

- [ ] **Step 5 (risk — shared client touched): Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/ -k "tunnel or helper" -q`. Expected: green, no regression.

- [ ] **Step 6: Commit** — `git add backend/services/tunnel_helper_client.py backend/tests/test_tunnel_helper_client.py` then `git commit -m "fix(tunnel-helper): bound call() readline with asyncio.wait_for + drop dead connection"`


---

### Task 10: geo_offline — drop the permanent _load_failed latch; retry load each call; throttled WARNING on early-return

**Files:**
- Modify: `backend/services/geo_offline.py:23-25` (module globals), `:53-66` (`_ensure_loaded` head), `:88-91` (except block), `:102-103` (`resolve` early-return)
- Test: `backend/tests/test_geo_offline.py`

**Interfaces:**
- Consumes: none
- Produces: `services.geo_offline` module no longer has a `_load_failed` global. `_ensure_loaded() -> bool` retries the load on every call until it succeeds (success still latched via `_loaded`). `resolve()` emits a throttled `logger.warning` (module globals `_last_warn_ts`, gated by `_WARN_THROTTLE_S = 60.0`) when it early-returns all-empty because tables are unavailable.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_geo_offline.py`. Reuse the file's existing imports (`import services.geo_offline as geo`, `from services.geo_offline import resolve`). The first test proves a transient failure no longer permanently blanks geo; the second pins the throttled warning. (Both `numpy` + `timezonefinder` are installed — the existing `test_resolve_taipei` already passes — so the real second-call load resolves.) Use `monkeypatch` (auto-restores module globals) and `caplog`:

```python
import logging


def test_transient_load_failure_does_not_latch_forever(monkeypatch):
    """A11: a first failed _ensure_loaded must not permanently blank geo.
    Once the underlying cause clears, the very next resolve() succeeds."""
    # Force a cold module state.
    monkeypatch.setattr(geo, "_loaded", False)
    assert not hasattr(geo, "_load_failed")  # latch removed entirely

    calls = {"n": 0}
    real_ensure = geo._ensure_loaded

    # First _ensure_loaded attempt fails (simulated transient), second succeeds.
    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        return real_ensure()

    monkeypatch.setattr(geo, "_ensure_loaded", flaky)

    # First call: transient failure -> all-empty.
    assert geo.resolve(25.0339, 121.5645) == ("", "", "", "")
    # Second call retries and now resolves for real (no permanent latch).
    cc, zone, city, region = geo.resolve(25.0339, 121.5645)
    assert cc == "tw"
    assert zone == "Asia/Taipei"


def test_resolve_warns_throttled_when_tables_unavailable(monkeypatch, caplog):
    """resolve() logs a single throttled WARNING (not one per call) when the
    offline tables are unavailable."""
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_ensure_loaded", lambda: False)
    monkeypatch.setattr(geo, "_last_warn_ts", 0.0)
    monkeypatch.setattr(geo, "_WARN_THROTTLE_S", 60.0)

    with caplog.at_level(logging.WARNING, logger="services.geo_offline"):
        assert geo.resolve(0.0, 0.0) == ("", "", "", "")
        assert geo.resolve(1.0, 1.0) == ("", "", "", "")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # Throttled: the two back-to-back calls produce exactly one WARNING.
    assert len(warnings) == 1
    assert "geo" in warnings[0].getMessage().lower()
```

  ALSO update the existing `test_resolve_returns_empty_when_data_unavailable` (currently at lines 51-57) — it sets `geo._load_failed`, which is being removed. Replace its two `monkeypatch.setattr` lines so it no longer references the removed latch:

```python
def test_resolve_returns_empty_when_data_unavailable(monkeypatch):
    # The one branch every enrich_bookmark caller relies on: when the
    # offline tables can't load, resolve() degrades to all-empty rather
    # than raising. monkeypatch auto-restores module state afterwards.
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_ensure_loaded", lambda: False)
    assert geo.resolve(25.0339, 121.5645) == ("", "", "", "")
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_geo_offline.py::test_transient_load_failure_does_not_latch_forever tests/test_geo_offline.py::test_resolve_warns_throttled_when_tables_unavailable -v`. Expected failure: `test_transient_load_failure...` fails at `assert not hasattr(geo, "_load_failed")` (the latch still exists at line 25); `test_resolve_warns_throttled...` fails at `monkeypatch.setattr(geo, "_last_warn_ts", 0.0)` with `AttributeError: <module 'services.geo_offline'> has no attribute '_last_warn_ts'` (the global doesn't exist yet).

- [ ] **Step 3: Implement** — in `backend/services/geo_offline.py`.

Add `import time` to the stdlib import block (after `import threading`, current line 18) and adjust the module globals. Current lines 23-25:

```python
_lock = threading.Lock()
_loaded = False
_load_failed = False
```

New:

```python
_lock = threading.Lock()
_loaded = False
_last_warn_ts = 0.0           # monotonic ts of the last "tables unavailable" WARNING
_WARN_THROTTLE_S = 60.0       # at most one such WARNING per minute
```

Update `_ensure_loaded` to drop the latch. Current lines 53-66:

```python
def _ensure_loaded() -> bool:
    """Lazily load timezonefinder + the bundled tables. Returns False if
    anything is unavailable — resolve() then degrades to empty results."""
    global _loaded, _load_failed, _tf, _lat, _lng, _name, _cc, _admin1
    global _zone_to_country, _admin1_names
    if _loaded:
        return True
    if _load_failed:
        return False
    with _lock:
        if _loaded:
            return True
        if _load_failed:
            return False
        try:
```

New (no `_load_failed` early-returns; success still cached via `_loaded`, so a transient failure is retried on the next call):

```python
def _ensure_loaded() -> bool:
    """Lazily load timezonefinder + the bundled tables. Returns False if
    anything is unavailable — resolve() then degrades to empty results.

    No permanent failure latch: a transient failure (e.g. an iCloud-evicted
    data file, a not-yet-installed numpy in the venv) is retried on the next
    call. Only success is cached (via _loaded)."""
    global _loaded, _tf, _lat, _lng, _name, _cc, _admin1
    global _zone_to_country, _admin1_names
    if _loaded:
        return True
    with _lock:
        if _loaded:
            return True
        try:
```

Update the except block. Current lines 88-91:

```python
        except Exception:
            logger.exception("geo_offline failed to load; geo fields stay empty")
            _load_failed = True
            return False
```

New:

```python
        except Exception:
            logger.exception(
                "geo_offline failed to load; geo fields stay empty (will retry)"
            )
            return False
```

Add the throttled WARNING at the early-return in `resolve`. Current lines 102-103:

```python
    if not _ensure_loaded():
        return ("", "", "", "")
```

New:

```python
    if not _ensure_loaded():
        global _last_warn_ts
        now = time.monotonic()
        if now - _last_warn_ts >= _WARN_THROTTLE_S:
            _last_warn_ts = now
            logger.warning(
                "geo_offline tables unavailable; bookmark geo fields stay "
                "empty (throttled, retrying each call)"
            )
        return ("", "", "", "")
```

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_geo_offline.py -v`. Expected: all tests PASS, including the two new ones and the updated `test_resolve_returns_empty_when_data_unavailable`.

- [ ] **Step 5 (risk — shared resolver): Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/ -k "geo or bookmark or enrich" -q`. Expected: green.

- [ ] **Step 6: Commit** — `git add backend/services/geo_offline.py backend/tests/test_geo_offline.py` then `git commit -m "fix(geo): drop permanent _load_failed latch; retry load each call + throttled WARNING"`


---

### Task 11: CloudSyncService.disable() — stop outgoing watchers BEFORE migrate_pair

**Files:**
- Modify: `backend/services/cloud_sync_service.py:122-138`
- Test: `backend/tests/test_cloud_sync_service_char.py`

**Interfaces:**
- Consumes: the existing `_SpyAppState` / `_FakeManager` / `_CapBroadcast` / `_patch_managers` doubles in `test_cloud_sync_service_char.py` (`_SpyAppState` seeds `bookmark_manager = _FakeManager("bm-old", ...)` / `route_manager = _FakeManager("rm-old", ...)`, and `_FakeManager.stop_watcher()` already appends `stop:{kind}` to the log → `stop:bm-old` / `stop:rm-old`). `pytestmark = pytest.mark.asyncio` is already set at module top.
- Produces: none

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_cloud_sync_service_char.py`. It pins that `disable()` stops the OLD watchers BEFORE `migrate_pair` runs (so files aren't moved out from under a live watcher), and that the order matches `enable`:

```python
async def test_disable_stops_outgoing_watchers_before_migrate_pair(
    monkeypatch, tmp_path
):
    """A10: the outgoing bookmark + route watchers must be stopped BEFORE
    migrate_pair moves their files back to DATA_DIR — symmetric with enable().
    Otherwise the live file_watcher fires on files being migrated away."""
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    app._sync_folder = str(tmp_path / "LocWarp")
    bc = _CapBroadcast()

    def _spy_migrate(*a, **k):
        log.append("migrate_pair")
        return (0, 0)

    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(css_mod, "migrate_pair", _spy_migrate)
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    await svc.disable()

    # outgoing watchers stopped BEFORE the files are migrated away
    assert log.index("stop:bm-old") < log.index("migrate_pair")
    assert log.index("stop:rm-old") < log.index("migrate_pair")
    # ...and (as before) the rebuilt watchers restart AFTER the rebuild
    assert log.index("new:bm") < log.index("restart:bm")
    assert log.index("new:rm") < log.index("restart:rm")
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_service_char.py::test_disable_stops_outgoing_watchers_before_migrate_pair -v`. Expected failure: `ValueError: 'stop:bm-old' is not in list` raised by `log.index("stop:bm-old")` — `disable()` currently never calls `stop_watcher()` before `migrate_pair`.

- [ ] **Step 3: Implement** — in `backend/services/cloud_sync_service.py`. Current `disable()` head (lines 122-138):

```python
    async def disable(self) -> CloudSyncStatus:
        if self._app._sync_folder is None:
            return self.build_status()

        current = Path(self._app._sync_folder)
        try:
            migrate_pair(current, _config.DATA_DIR)
        except Exception as exc:
            logger.exception("cloud-sync disable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")

        self._app._sync_folder = None
        self._app.save_settings()

        from bootstrap.factories import make_bookmark_manager, make_route_manager
        self._app.bookmark_manager = make_bookmark_manager()
        self._app.route_manager = make_route_manager()
```

New — stop the OUTGOING managers' watches before `migrate_pair` moves their files (symmetric with `enable()`, which already stops at lines 95-98):

```python
    async def disable(self) -> CloudSyncStatus:
        if self._app._sync_folder is None:
            return self.build_status()

        # Stop the OUTGOING managers' watches first — otherwise their live
        # handles on the shared file_watcher Observer fire on files that
        # migrate_pair is moving back to DATA_DIR (symmetric with enable()).
        if self._app.bookmark_manager is not None:
            self._app.bookmark_manager.stop_watcher()
        if self._app.route_manager is not None:
            self._app.route_manager.stop_watcher()

        current = Path(self._app._sync_folder)
        try:
            migrate_pair(current, _config.DATA_DIR)
        except Exception as exc:
            logger.exception("cloud-sync disable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")

        self._app._sync_folder = None
        self._app.save_settings()

        from bootstrap.factories import make_bookmark_manager, make_route_manager
        self._app.bookmark_manager = make_bookmark_manager()
        self._app.route_manager = make_route_manager()
```

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_service_char.py -v`. Expected: all tests PASS, including the new one and the existing `test_disable_orders_and_broadcasts` / `test_disable_noop_when_not_enabled` (the no-op path still returns early at `if self._app._sync_folder is None` BEFORE any `stop_watcher`, so its `assert "new:bm" not in log` still holds).

- [ ] **Step 5 (risk — danger-zone stop/replace/restart ordering): Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/ -k "cloud_sync" -q`. Expected: green.

- [ ] **Step 6: Commit** — `git add backend/services/cloud_sync_service.py backend/tests/test_cloud_sync_service_char.py` then `git commit -m "fix(cloud-sync): stop outgoing watchers before migrate_pair in disable() (symmetric with enable)"`


---

### Task 12: [DANGER-ZONE · device_manager] connect_wifi_tunnel — move the `if udid in self._connections -> disconnect` check-then-act inside self._lock

**Files:**
- Modify: `backend/core/device_manager.py:977-990`
- Test: `backend/tests/test_device_manager_wifi_tunnel_race_char.py` (Create)

**Interfaces:**
- Consumes: none
- Produces: none (behavior-preserving; the only change is that the stale-conn existence check + `disconnect` now runs under `self._lock` alongside the assignment).

DANGER-ZONE: this touches `core/device_manager.py`. Characterization test FIRST (must be GREEN on un-edited code, Step 2). Per CLAUDE.md the ~20 other lock-free `self._connections` accesses are deliberate single-event-loop atomics — DO NOT touch them; this task moves ONLY the check-then-act+assignment block at lines 977-990. Do NOT reimplement RSD/tunnel guts; the test stubs `RemoteServiceDiscoveryService` at the module seam.

Verified against the real code: `DeviceManager.__init__(self, event_publisher=None, tunnel_registry=None)` (so `DeviceManager()` constructs with no args); `connect_wifi_tunnel(self, rsd_address, rsd_port, *, bonjour_id=None)`; `_remember_device_name`, `_remember_wifi_alias`, `_load_device_name_cache`, and `RemoteServiceDiscoveryService` are all bare module-level names in `core.device_manager` (so module-level monkeypatch works). The stub's `all_values = {"DeviceName": "My iPhone"}` makes `device_name` truthy at line 957, so the `if not device_name:` fallback (which would touch `existing.name` on the bare-`object()` stale conn at line 960) is skipped — the test does NOT hit an AttributeError.

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_device_manager_wifi_tunnel_race_char.py`. It drives the real `connect_wifi_tunnel` with a stubbed `RemoteServiceDiscoveryService` (patched on the device_manager module) so we never touch real USB/tunnel guts, pre-seeds a stale connection for the same udid, and asserts the stale `disconnect` + the new-conn assignment both happen and that the final connection is the new one.

```python
"""Characterization: connect_wifi_tunnel replaces a stale same-udid connection
atomically — the existence-check + disconnect + assignment run under _lock."""
from __future__ import annotations

import pytest

import core.device_manager as dm_mod
from core.device_manager import DeviceManager


class _StubRSD:
    """Stands in for RemoteServiceDiscoveryService((addr, port))."""

    def __init__(self, addr_port):
        self.peer_info = {
            "Properties": {
                "UniqueDeviceID": "UDID-WIFI",
                "OSVersion": "17.5",
                "DeviceClass": "iPhone",
            }
        }
        self.all_values = {"DeviceName": "My iPhone"}

    async def connect(self):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_connect_wifi_tunnel_replaces_stale_same_udid_atomically(monkeypatch):
    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _StubRSD)
    # name-cache / alias writers touch disk; stub them out.
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_remember_wifi_alias", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

    mgr = DeviceManager()

    # Pre-seed a STALE connection for the same udid; record that it's torn down.
    disconnected: list[str] = []
    stale = object()
    mgr._connections["UDID-WIFI"] = stale

    async def _fake_disconnect(udid):
        disconnected.append(udid)
        mgr._connections.pop(udid, None)

    monkeypatch.setattr(mgr, "disconnect", _fake_disconnect)

    info = await mgr.connect_wifi_tunnel("127.0.0.1", 12345)

    # the stale same-udid conn was disconnected exactly once...
    assert disconnected == ["UDID-WIFI"]
    # ...and replaced by the fresh connection (not the stale object)
    assert mgr._connections["UDID-WIFI"] is not stale
    assert mgr._connections["UDID-WIFI"].connection_type == "Network"
    assert info.udid == "UDID-WIFI"
    assert info.connection_type == "Network"
    assert info.is_connected is True
```

- [ ] **Step 2: Run test, verify it is GREEN on un-edited code** — `cd backend && .venv/bin/python -m pytest tests/test_device_manager_wifi_tunnel_race_char.py -v`. Expected: this characterization test PASSES against the CURRENT code (it pins existing behavior — the replace already works, just unsafely outside the lock). If it does NOT pass first, fix the stub/monkeypatch until it's green on current code BEFORE making the production edit — a red characterization test here means the harness is wrong, not the code. (This is the danger-zone safety net: it must be green on un-edited code, then stay green through the edit.)

- [ ] **Step 3: Implement** — in `backend/core/device_manager.py`. Current code (lines 977-990):

```python
        if udid in self._connections:
            await self.disconnect(udid)

        conn = _ActiveConnection(
            udid=udid,
            lockdown=rsd,
            ios_version=ios_version_str,
            connection_type="Network",
            name=device_name,
            rsd=rsd,
        )

        async with self._lock:
            self._connections[udid] = conn
```

New — the existence-check + disconnect of the stale same-udid conn now runs under `self._lock` together with the assignment, so a concurrent connect/disconnect on the same loop can't interleave between the check and the swap. (Build `conn` outside the lock — pure object construction, no shared state — to keep the critical section minimal.):

```python
        conn = _ActiveConnection(
            udid=udid,
            lockdown=rsd,
            ios_version=ios_version_str,
            connection_type="Network",
            name=device_name,
            rsd=rsd,
        )

        async with self._lock:
            # Check-then-act for a stale same-udid connection must be atomic
            # with the assignment: doing the existence check + disconnect
            # OUTSIDE the lock let a concurrent connect interleave between the
            # check and the swap and leak/clobber a connection. (The ~20 other
            # lock-free _connections accesses stay as-is — they are deliberate
            # single-event-loop atomics.)
            if udid in self._connections:
                await self.disconnect(udid)
            self._connections[udid] = conn
```

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_device_manager_wifi_tunnel_race_char.py -v`. Expected: still PASS (behavior unchanged; only the locking moved).

- [ ] **Step 5 (DANGER-ZONE — mandatory broader suite): Run device_manager-area + full suite** — `cd backend && .venv/bin/python -m pytest tests/ -k "device_manager or device_service or wifi or tunnel" -q` then the full run `cd backend && .venv/bin/python -m pytest -q`. Expected: full suite green at the 914-collected baseline + the new tests added across this cluster.

- [ ] **Step 6: Commit** — `git add backend/core/device_manager.py backend/tests/test_device_manager_wifi_tunnel_race_char.py` then `git commit -m "fix(device-manager): move stale same-udid disconnect+swap inside _lock in connect_wifi_tunnel"`


---


<!-- ===== C4 · Engine targeting, device-lost guard, dead code, watchdog reason ===== -->

### Task 13: Re-resolve engine by target_udid after rebuild (kill dual-device primary leak)

**Files:**
- Modify: `backend/api/location.py:74-97` (the two rebuild-success checks inside `_engine`)
- Test: `backend/tests/test_location_engine_target_char.py` (create)

**Interfaces:**
- Consumes: `AppState.create_engine_for_device(udid, force=False)`, `AppState.get_engine(udid)`, `AppState.simulation_engine` (primary accessor) — all in `backend/main.py`.
- Produces: none (behavior fix internal to `_engine`).

**Context (real bug):** `_engine(udid, registry)` at `backend/api/location.py:31`. After `await app_state.create_engine_for_device(target_udid)` it checks `if app_state.simulation_engine is not None: return app_state.simulation_engine` at lines 78-80 and again at 93-95. But `simulation_engine` is the PRIMARY accessor (`main.py:361-367`: returns `simulation_engines[_primary_udid]`), and `create_engine_for_device` only sets `_primary_udid` when it was `None` (`main.py:439-440`). So when device A is already primary and the caller targets a non-primary udid B, the rebuild succeeds for B but `simulation_engine` returns A's engine — teleport/navigate on B silently drives A. Fix: after a successful rebuild, re-resolve via `app_state.get_engine(target_udid)`; only fall back to `simulation_engine` when the original `udid` arg was None.

- [ ] **Step 1: Write the failing test** — full file `backend/tests/test_location_engine_target_char.py`:
```python
"""Characterization: api/location._engine must return the engine for the
TARGET udid after a lazy rebuild, not the primary one. Dual-device guard:
rebuilding B while A is primary must NOT hand back A's engine (which would
make teleport/navigate on B silently drive A).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import api.location as location_mod

pytestmark = pytest.mark.asyncio


async def test_engine_returns_target_engine_not_primary_after_rebuild():
    eng_a = MagicMock(name="engine_A")  # primary
    eng_b = MagicMock(name="engine_B")  # the device we actually target

    registry = MagicMock()
    # A is already primary; simulation_engine (primary accessor) returns A.
    registry.simulation_engine = eng_a
    registry._primary_udid = "UDID-A"

    engines = {"UDID-A": eng_a}

    # get_engine(B) is empty before rebuild, populated after.
    def _get_engine(u):
        return engines.get(u)
    registry.get_engine = MagicMock(side_effect=_get_engine)

    async def _create(u, force=False):
        engines[u] = eng_b  # rebuild populates B, leaves A primary
    registry.create_engine_for_device = AsyncMock(side_effect=_create)

    dm = MagicMock()
    dm._connections = {"UDID-A": object(), "UDID-B": object()}
    registry.device_manager = dm

    result = await location_mod._engine("UDID-B", registry)

    assert result is eng_b, "must return B's engine, not the primary (A)"


class _FakeRegistry:
    """Minimal AppState stand-in whose `simulation_engine` property reflects
    the live engines dict + primary udid (so the udid=None fallback path is
    actually exercised, not short-circuited at entry)."""

    def __init__(self, dm):
        self.engines: dict = {}
        self._primary_udid = None
        self.device_manager = dm
        self.create_calls: list = []

    @property
    def simulation_engine(self):
        if self._primary_udid and self._primary_udid in self.engines:
            return self.engines[self._primary_udid]
        return None

    def get_engine(self, udid):
        if udid is None:
            return self.simulation_engine
        return self.engines.get(udid)

    async def create_engine_for_device(self, udid, force=False):
        self.create_calls.append(udid)
        self.engines[udid] = self._next_engine
        if self._primary_udid is None:
            self._primary_udid = udid


async def test_engine_falls_back_to_primary_when_udid_arg_is_none():
    """udid arg is None: no primary yet, slot empty -> lazy rebuild promotes
    the only connected device to primary, and the primary fallback returns it.
    Guards the `else app_state.simulation_engine` branch of the fix."""
    eng_a = MagicMock(name="engine_A")

    dm = MagicMock()
    dm._connections = {"UDID-A": object()}

    reg = _FakeRegistry(dm)
    reg._next_engine = eng_a  # what create_engine_for_device installs

    # simulation_engine starts None (no primary) so _engine does NOT
    # short-circuit on the udid-None fast path; it rebuilds, then the
    # primary fallback is acceptable because no specific target was requested.
    result = await location_mod._engine(None, reg)
    assert result is eng_a
    assert reg.create_calls == ["UDID-A"]
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_location_engine_target_char.py -v`. Expect `test_engine_returns_target_engine_not_primary_after_rebuild` to FAIL with `assert <engine_A> is <engine_B>` (the current code returns `simulation_engine`, i.e. A). `test_engine_falls_back_to_primary_when_udid_arg_is_none` already passes (it guards the unchanged fallback).

- [ ] **Step 3: Implement** — edit `backend/api/location.py`. Current code (attempt-1 block, lines 74-82):
```python
    # Attempt 1: rebuild engine on top of existing connection
    _log.info("simulation_engine missing; attempt 1 (rebuild) for %s", target_udid)
    try:
        await app_state.create_engine_for_device(target_udid)
        if app_state.simulation_engine is not None:
            _log.info("Engine rebuild succeeded on attempt 1")
            return app_state.simulation_engine
    except Exception:
        _log.exception("Engine rebuild (attempt 1) failed for %s", target_udid)
```
Replace the success check with a target-scoped re-resolve:
```python
    # Attempt 1: rebuild engine on top of existing connection
    _log.info("simulation_engine missing; attempt 1 (rebuild) for %s", target_udid)
    try:
        await app_state.create_engine_for_device(target_udid)
        rebuilt = app_state.get_engine(target_udid) if udid is not None else app_state.simulation_engine
        if rebuilt is not None:
            _log.info("Engine rebuild succeeded on attempt 1")
            return rebuilt
    except Exception:
        _log.exception("Engine rebuild (attempt 1) failed for %s", target_udid)
```
Then the attempt-2 block (current lines 91-95):
```python
        await dm.connect(target_udid)
        await app_state.create_engine_for_device(target_udid)
        if app_state.simulation_engine is not None:
            _log.info("Engine rebuild succeeded on attempt 2")
            return app_state.simulation_engine
```
Replace with:
```python
        await dm.connect(target_udid)
        await app_state.create_engine_for_device(target_udid)
        rebuilt = app_state.get_engine(target_udid) if udid is not None else app_state.simulation_engine
        if rebuilt is not None:
            _log.info("Engine rebuild succeeded on attempt 2")
            return rebuilt
```
Note: `target_udid = udid or next(iter(dm._connections.keys()), None)` (line 53). When the original `udid` arg is None we deliberately keep the primary fallback, because the caller didn't ask for a specific device.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_location_engine_target_char.py -v`. Expect 2 passed.

- [ ] **Step 5 (danger-zone): Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_location_di_char.py tests/test_location_device_lost_publisher.py -v` then the full suite `cd backend && .venv/bin/python -m pytest -q`. Expect all green; this task adds 2 tests and removes none (collection increases by 2 over the pre-task count).

- [ ] **Step 6: Commit** — `git add backend/api/location.py backend/tests/test_location_engine_target_char.py` then `git commit -m "fix(location): re-resolve engine by target udid after rebuild (dual-device primary leak)"`.


---

### Task 14: Make _handle_device_lost udid required (drop unreachable all-devices branch)

**Files:**
- Modify: `backend/api/location.py:179-200` (`_handle_device_lost` signature + None branch)
- Test: `backend/tests/test_location_device_lost_publisher.py` (add two tests; existing file)

**Interfaces:**
- Consumes: `dm._events.publish`, `dm.disconnect`, `app_state.remove_engine`, `app_state.simulation_engines` (all already used by the function).
- Produces: `_handle_device_lost(exc, udid, registry=None)` — `udid` is now a required positional (no default). Every existing caller already passes `action_udid` (location.py:326, 335, 492, 515), so no caller change is needed.

**Context (real dead branch):** `_handle_device_lost(exc, udid=None, registry=None)` at `backend/api/location.py:179`. The `udid is None` branch (lines 198-200) does `lost_udids = list(dm._connections.keys())` — i.e. disconnect ALL devices, the exact dual-device bug the docstring warns about. But all four call-sites pass an `action_udid` (e.g. `raise (await _handle_device_lost(e, action_udid, registry))` at line 326), and `action_udid` resolves to `getattr(req, "udid", None) or registry._primary_udid` (teleport line 313) / `udid or registry._primary_udid` (restore line 483) / `req.udid or registry._primary_udid` (goldditto line 514) — only None when there is no primary at all. Drop the default so the all-devices branch is unreachable; keep the `udid not in _connections` no-op path.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_location_device_lost_publisher.py` (imports `AsyncMock, patch` and `import api.location as location_mod` and `pytestmark = pytest.mark.asyncio` are already present at top of that file):
```python
async def test_handle_device_lost_requires_udid():
    """udid is a required positional — the old all-devices fallback is gone."""
    import inspect
    sig = inspect.signature(location_mod._handle_device_lost)
    udid_param = sig.parameters["udid"]
    assert udid_param.default is inspect.Parameter.empty, (
        "_handle_device_lost(exc, udid) must require udid (no None default)"
    )


async def test_handle_device_lost_only_touches_named_udid():
    """Only the failing udid is disconnected — a co-connected device is left alone."""
    from main import app_state

    failing = "UDID-FAILING"
    survivor = "UDID-SURVIVOR"
    dm = app_state.device_manager

    disconnected: list[str] = []
    fake_connections = {failing: object(), survivor: object()}

    async def _fake_disconnect(u):
        disconnected.append(u)
        fake_connections.pop(u, None)

    class _CapPublisher:
        async def publish(self, event):
            pass

    with (
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(app_state, "remove_engine", new=AsyncMock(return_value=None)),
        patch.object(app_state, "simulation_engines", {}),
    ):
        await location_mod._handle_device_lost(Exception("gone"), failing)

    assert disconnected == [failing]
    assert survivor in fake_connections
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_location_device_lost_publisher.py::test_handle_device_lost_requires_udid -v`. Expect FAIL: `udid_param.default` is `None`, not `inspect.Parameter.empty`.

- [ ] **Step 3: Implement** — edit `backend/api/location.py`. Current signature (line 179):
```python
async def _handle_device_lost(exc: Exception, udid: str | None = None, registry=None) -> "HTTPException":
```
becomes:
```python
async def _handle_device_lost(exc: Exception, udid: str, registry=None) -> "HTTPException":
```
Current body (lines 193-200):
```python
    dm = app_state.device_manager
    if udid is not None:
        lost_udids = [udid] if udid in dm._connections else []
        if not lost_udids:
            _log.info("device_lost: udid %s no longer in _connections; nothing to clean", udid)
    else:
        _log.warning("device_lost called without udid; falling back to clearing all devices")
        lost_udids = list(dm._connections.keys())
```
becomes (drop the all-devices fallback; the named-udid no-op path stays):
```python
    dm = app_state.device_manager
    lost_udids = [udid] if udid in dm._connections else []
    if not lost_udids:
        _log.info("device_lost: udid %s no longer in _connections; nothing to clean", udid)
```
Also update the docstring (lines 180-188) — the current text ends with "When udid is None (legacy callers not yet updated), we fall back to disconnecting all as before to preserve behaviour, but log a warning." Replace that closing sentence with: "The caller always passes the udid of the failing action; only that device is cleaned up."

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_location_device_lost_publisher.py -v`. Expect all (existing + 2 new) passed.

- [ ] **Step 5 (danger-zone): Run the broader suite** — `cd backend && .venv/bin/python -m pytest -q`. Expect green; pay attention to any teleport/navigate device-lost tests in `tests/test_location_*.py`.

- [ ] **Step 6: Commit** — `git add backend/api/location.py backend/tests/test_location_device_lost_publisher.py` then `git commit -m "refactor(location): require udid in _handle_device_lost (drop dead all-devices branch)"`.


---

### Task 15: Thread DeviceLostError.reason + last_error into watchdog tunnel_lost / tunnel_degraded payloads

**Files:**
- Modify: `backend/services/location_service.py:47-49` (add `last_error` slot to `DeviceLostError`)
- Modify: `backend/api/device.py:781-790` (capture task exc + classify) and `:805` / `:899` (thread reason/last_error into both payloads); add `DeviceLostError` import
- Test: `backend/tests/test_watchdog_tunnel_lost_reason_char.py` (create)

**Interfaces:**
- Consumes: `DeviceLostError` (`from services.location_service import DeviceLostError`), `dm._events.publish((type, payload))`, `_per_tunnel_watchdog(udid, runner)` in `backend/api/device.py`, module aliases `_tunnels` / `_tunnel_watchdogs` (imported into `api.device` from `infra.device.tunnel_state` at device.py:127-129).
- Produces: `DeviceLostError(..., reason=..., last_error=...)` — `last_error: str | None = None` new kwarg, exposed as `.last_error`. WS payload for `tunnel_degraded` and `tunnel_lost` gains an optional `last_error` key and a classified `reason` (was hardcoded `task_exited`).

**Context (real hardcode):** `_per_tunnel_watchdog` at `backend/api/device.py:773` does `await task` (line 786) inside a `try/except BaseException: pass` (789-790) that DISCARDS the exception. The degraded payload (line 805) and the final lost payload (line 899) both hardcode `{"udid": udid, "reason": "task_exited"}`, so the richer `DeviceLostError.reason` classification (`tunnel_dead` / `lockdown_dead` / `usb_gone`) raised inside `device_manager.get_fresh_dvt_provider` (`core/device_manager.py:1151`/`1165`/`1183`) never reaches the WS client. Capture the exception; when it is a `DeviceLostError`, use its `.reason` and `.last_error`, defaulting to the existing `task_exited` shape otherwise. **WS payloads are compared deep-equal JSON** — the clean-exit path must stay exactly `{udid, reason: 'task_exited'}` (no `last_error` key).

- [ ] **Step 1: Write the failing test** — full file `backend/tests/test_watchdog_tunnel_lost_reason_char.py`:
```python
"""Characterization: _per_tunnel_watchdog must thread a DeviceLostError's
reason + last_error into the tunnel_degraded and tunnel_lost WS payloads
instead of hardcoding reason='task_exited'. Deep-equal JSON comparison.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import api.device as device_mod
from services.location_service import DeviceLostError

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.events: list[tuple] = []

    async def publish(self, event):
        etype, data = event
        # copy the dict so later mutation can't rewrite history
        self.events.append((etype, {**data}))


async def test_watchdog_threads_device_lost_reason_into_payloads():
    udid = "UDID-WD-REASON"

    # Runner whose monitored task raises a classified DeviceLostError.
    async def _dead_task():
        raise DeviceLostError(
            "WiFi tunnel gone",
            reason=DeviceLostError.REASON_TUNNEL_DEAD,
            last_error="helper reports tunnel for X is gone",
        )

    runner = MagicMock()
    runner.task = asyncio.create_task(_dead_task())
    # No captured target -> watchdog skips the restart loop and goes straight
    # to teardown, so we exercise BOTH tunnel_degraded and tunnel_lost.
    runner.target_ip = None
    runner.target_port = None

    pub = _CapPublisher()
    dm = MagicMock()
    dm._events = pub

    eng_reg = MagicMock()
    eng_reg.simulation_engines = {}

    with (
        patch.object(device_mod, "_dm", return_value=dm),
        patch.object(device_mod, "_engines", return_value=eng_reg),
        patch.dict(device_mod._tunnels, {udid: runner}, clear=False),
        patch.object(device_mod, "_cleanup_wifi_connection_for", new=AsyncMock(return_value=True)),
    ):
        await device_mod._per_tunnel_watchdog(udid, runner)

    by_type = {etype: data for etype, data in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }
    assert by_type["tunnel_lost"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }


async def test_watchdog_clean_exit_keeps_task_exited_shape():
    """A clean (non-DeviceLostError) task exit keeps the legacy payload shape:
    reason='task_exited', no last_error key."""
    udid = "UDID-WD-CLEAN"

    async def _clean_task():
        return  # tunnel poll loop returns when helper says gone

    runner = MagicMock()
    runner.task = asyncio.create_task(_clean_task())
    runner.target_ip = None
    runner.target_port = None

    pub = _CapPublisher()
    dm = MagicMock()
    dm._events = pub
    eng_reg = MagicMock()
    eng_reg.simulation_engines = {}

    with (
        patch.object(device_mod, "_dm", return_value=dm),
        patch.object(device_mod, "_engines", return_value=eng_reg),
        patch.dict(device_mod._tunnels, {udid: runner}, clear=False),
        patch.object(device_mod, "_cleanup_wifi_connection_for", new=AsyncMock(return_value=True)),
    ):
        await device_mod._per_tunnel_watchdog(udid, runner)

    by_type = {etype: data for etype, data in pub.events}
    assert by_type["tunnel_degraded"] == {"udid": udid, "reason": "task_exited"}
    assert by_type["tunnel_lost"] == {"udid": udid, "reason": "task_exited"}
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_watchdog_tunnel_lost_reason_char.py -v`. Expect FAIL on `test_watchdog_threads_device_lost_reason_into_payloads`: `DeviceLostError.__init__` rejects `last_error=` (TypeError) and/or the payload equals `{"udid": ..., "reason": "task_exited"}` not the classified shape.

- [ ] **Step 3: Implement** — two source files.

Edit 3a — `backend/services/location_service.py`, add the `last_error` slot. Current (lines 47-49):
```python
    def __init__(self, *args, reason: str = "unknown") -> None:
        super().__init__(*args)
        self.reason = reason
```
becomes:
```python
    def __init__(self, *args, reason: str = "unknown", last_error: str | None = None) -> None:
        super().__init__(*args)
        self.reason = reason
        self.last_error = last_error
```

Edit 3b — `backend/api/device.py`. First add the import: `DeviceLostError` is NOT currently imported (only appears in comments). Add `from services.location_service import DeviceLostError` next to the existing `from services.tunnel_helper_client import TunnelBusyError` at line 106 (confirm with `grep -n "^from services.location_service import DeviceLostError" backend/api/device.py` finds nothing first).

Then the `await task` block. Current (lines 782-790):
```python
        task = runner.task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            return
        except BaseException:
            pass
```
becomes (capture + classify):
```python
        task = runner.task
        if task is None:
            return
        exit_exc: BaseException | None = None
        try:
            await task
        except asyncio.CancelledError:
            return
        except BaseException as _e:
            exit_exc = _e

        # Classify the exit cause for the WS payload. A clean tunnel-poll
        # return keeps the legacy reason='task_exited' (no last_error). A
        # DeviceLostError carries the richer classification + last_error.
        _reason_payload: dict = {"reason": "task_exited"}
        if isinstance(exit_exc, DeviceLostError):
            _reason_payload = {"reason": exit_exc.reason}
            if exit_exc.last_error is not None:
                _reason_payload["last_error"] = exit_exc.last_error
```
Then the degraded publish (current line 805):
```python
            await dm._events.publish(("tunnel_degraded", {"udid": udid, "reason": "task_exited"}))
```
becomes:
```python
            await dm._events.publish(("tunnel_degraded", {"udid": udid, **_reason_payload}))
```
And the lost publish (current line 899):
```python
                await dm._events.publish(("tunnel_lost", {"udid": udid, "reason": "task_exited"}))
```
becomes:
```python
                await dm._events.publish(("tunnel_lost", {"udid": udid, **_reason_payload}))
```

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_watchdog_tunnel_lost_reason_char.py -v`. Expect 2 passed.

- [ ] **Step 5 (danger-zone + WS payload change): Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_device_manager_events.py tests/test_device_manager_fresh_dvt.py -v` then full suite `cd backend && .venv/bin/python -m pytest -q`. Expect green. Also confirm the frontend WS handlers treat the new `last_error` as additive only: `grep -rn "tunnel_lost\|tunnel_degraded" frontend/src` (current handlers in `frontend/src/hooks/useSimulation.ts` read `reason`; `last_error` is optional/additive).

- [ ] **Step 6: Commit** — `git add backend/services/location_service.py backend/api/device.py backend/tests/test_watchdog_tunnel_lost_reason_char.py` then `git commit -m "feat(watchdog): thread DeviceLostError reason + last_error into tunnel_lost/degraded WS payloads"`.


---

### Task 16: Reduce AppState.simulation_engine setter to clear-only (remove unreachable __legacy__ stash)

**Files:**
- Modify: `backend/main.py:369-378` (the `simulation_engine` setter)
- Test: `backend/tests/test_appstate_engine_setter.py` (create)

**Interfaces:**
- Consumes: `AppState.simulation_engines` (dict), `AppState._primary_udid` (`backend/main.py`).
- Produces: none. The `simulation_engine = None` clear-all behavior is preserved; the non-None branch now raises `TypeError` instead of silently stashing under `"__legacy__"`.

**Context (real dead branch):** the setter at `backend/main.py:369-378`. The `value is None` branch (`simulation_engines.clear(); _primary_udid = None`) is still a documented clear-all. The non-None `else` branch stashes the engine under `simulation_engines["__legacy__"]` and sets `_primary_udid = "__legacy__"`. A repo-wide grep for assignments to `.simulation_engine` (not `.simulation_engines`) finds ZERO non-None assignments in production — engines are created via `create_engine_for_device` and removed via `remove_engine` / direct `simulation_engines.pop`. The `__legacy__` synthetic key is dead. Make the misuse loud instead of silent.

- [ ] **Step 1: Write the failing test** — full file `backend/tests/test_appstate_engine_setter.py`:
```python
"""The simulation_engine setter only supports `= None` (clear all). Assigning
a real engine is a programming error (engines are created via
create_engine_for_device) and must raise, not silently stash under __legacy__.
"""
from __future__ import annotations

import pytest


def _fresh_appstate():
    from main import AppState
    return AppState()


def test_setter_none_clears_all_engines():
    st = _fresh_appstate()
    st.simulation_engines["UDID-X"] = object()
    st._primary_udid = "UDID-X"
    st.simulation_engine = None
    assert st.simulation_engines == {}
    assert st._primary_udid is None


def test_setter_non_none_raises_and_does_not_stash_legacy():
    st = _fresh_appstate()
    with pytest.raises(TypeError):
        st.simulation_engine = object()
    assert "__legacy__" not in st.simulation_engines
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_appstate_engine_setter.py -v`. Expect `test_setter_non_none_raises_and_does_not_stash_legacy` to FAIL: no `TypeError` raised and `"__legacy__"` IS in `simulation_engines`.

- [ ] **Step 3: Implement** — edit `backend/main.py`. Current setter (lines 369-378):
```python
    @simulation_engine.setter
    def simulation_engine(self, value):
        """Legacy setter. Only `= None` (clear all) is meaningful."""
        if value is None:
            self.simulation_engines.clear()
            self._primary_udid = None
        else:
            # Best-effort: stash under a synthetic key if udid unknown
            self.simulation_engines["__legacy__"] = value
            self._primary_udid = "__legacy__"
```
becomes:
```python
    @simulation_engine.setter
    def simulation_engine(self, value):
        """Legacy setter. ONLY `= None` (clear all) is supported. Engines are
        created via create_engine_for_device(udid) and removed via
        remove_engine(udid); there is no per-udid-less assignment path."""
        if value is not None:
            raise TypeError(
                "simulation_engine assignment is clear-only; use "
                "create_engine_for_device(udid) to register an engine"
            )
        self.simulation_engines.clear()
        self._primary_udid = None
```

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_appstate_engine_setter.py -v`. Expect 2 passed.

- [ ] **Step 5: Run the broader suite** — `cd backend && .venv/bin/python -m pytest -q`. Expect green (verifies nothing anywhere assigns a real engine through the setter).

- [ ] **Step 6: Commit** — `git add backend/main.py backend/tests/test_appstate_engine_setter.py` then `git commit -m "refactor(appstate): make simulation_engine setter clear-only (drop dead __legacy__ stash)"`.


---

### Task 17: Delete unused ReconnectManager (reconnect.py + main.py import/assignment)

**Files:**
- Delete: `backend/services/reconnect.py`
- Modify: `backend/main.py:35` (import), `backend/main.py:140` (`self.reconnect_manager = None`), `backend/main.py:451-452` (assignment inside `create_engine_for_device`)
- Test: `backend/tests/test_no_reconnect_manager.py` (create — guard against re-introduction)

**Interfaces:**
- Consumes: none.
- Produces: none. `ReconnectManager` and any `SimulationSnapshot` it defines are removed entirely.

**Context (real dead code):** `ReconnectManager` (`backend/services/reconnect.py`) is constructed at `backend/main.py:452` (`self.reconnect_manager = ReconnectManager(self.device_manager)`) inside `create_engine_for_device`, imported at `main.py:35`, and initialized to `None` at `main.py:140`. Its `.start(udid)` exponential-backoff loop is NEVER called anywhere — real reconnection is `_per_tunnel_watchdog` (`api/device.py:773`) + the USB presence watchdog in `main.py`. Verify before deleting: `grep -rn "reconnect_manager" backend` should show ONLY the three main.py lines below (no `.start(` call); `grep -rln "import.*reconnect\b\|services.reconnect" backend/tests` should be empty.

**Order:** do this AFTER the A20 setter task lands, since both touch `backend/main.py`. The regions don't overlap (A20 = setter at :369-378; A5 = :35, :140, :451-452), but A20→A5 ordering keeps A5's quoted line numbers valid.

- [ ] **Step 1: Write the failing test** — full file `backend/tests/test_no_reconnect_manager.py`:
```python
"""Guard: the dead ReconnectManager is gone. Real reconnection lives in
_per_tunnel_watchdog (api/device.py) + the USB presence watchdog (main.py).
"""
from __future__ import annotations

import importlib

import pytest


def test_reconnect_module_is_deleted():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("services.reconnect")


def test_main_has_no_reconnect_manager_attribute():
    import main
    st = main.AppState()
    assert not hasattr(st, "reconnect_manager"), (
        "AppState should no longer carry a reconnect_manager slot"
    )
    assert "ReconnectManager" not in dir(main)
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_no_reconnect_manager.py -v`. Expect both to FAIL: `services.reconnect` still imports successfully, and `main.ReconnectManager` / `st.reconnect_manager` still exist.

- [ ] **Step 3: Implement** — three edits in `backend/main.py` plus the file delete.

3a. Remove the import. Current `backend/main.py:35`:
```python
from services.reconnect import ReconnectManager
```
Delete this line entirely.

3b. Remove the slot init. Current `backend/main.py:140`:
```python
        self.reconnect_manager = None
```
Delete this line entirely.

3c. Remove the construction inside `create_engine_for_device`. Current `backend/main.py:451-452`:
```python
            # Setup reconnect manager
            self.reconnect_manager = ReconnectManager(self.device_manager)
```
Delete both lines.

3d. Delete the module: `git rm backend/services/reconnect.py`.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_no_reconnect_manager.py -v`. Expect 2 passed.

- [ ] **Step 5: Run the broader suite** — `cd backend && .venv/bin/python -m pytest -q` (confirms nothing imported the deleted module). Also `cd backend && .venv/bin/python -c "import main"` to confirm the app module still imports clean.

- [ ] **Step 6: Commit** — `git add backend/main.py backend/tests/test_no_reconnect_manager.py` (the `git rm` already staged the deletion), then `git commit -m "chore(reconnect): delete unused ReconnectManager (real reconnection is the tunnel watchdog)"`.


---


<!-- ===== C5 · Cloud-sync rollback honesty, materialize, watcher repo-leak ===== -->

### Task 18: Route the bookmark watcher write through the repo (kill the re-leaked infra dep) and remove now-unused json_safe imports

**Files:**
- Modify: `backend/services/bookmarks.py:20` (import line) and `backend/services/bookmarks.py:260-273` (`_watcher_tick` write block)
- Modify: `backend/services/route_store.py:30` (import line)
- Test: `backend/tests/test_watcher_writes_through_repo.py` (new)

**Interfaces:**
- Consumes: `JsonStore.save(store) -> store` (read-merge-write, returns the merged store — confirmed at `backend/infra/persistence/json_store.py:63-68`); `BookmarkManager._repo` (a `BookmarkRepository`, set at `bookmarks.py:133`), `BookmarkManager._store_lock` (a plain `threading.Lock()` at `bookmarks.py:132`), `BookmarkManager._record_disk_mtime()`, `BookmarkManager._reconcile_from_disk()`.
- Produces: none (no new public surface; behavior: watcher writes now go through `self._repo.save`).

This is a DANGER-ZONE file (`bookmarks` store path / watcher reconcile). Test first, red before edit.

- [ ] **Step 1: Write the failing test** — assert the watcher write goes through the repo, NOT a raw `safe_write_json`. Drive a real external-write reconcile and spy on `manager._repo.save`. Match the `make_bookmark_manager` + `BOOKMARKS_FILE` monkeypatch fixture style from `backend/tests/test_bookmarks_thread_race.py` / `test_gc_through_save.py`.

```python
"""Regression (X14): the bookmark watcher MUST persist through the repo
(self._repo.save), not via a raw services.json_safe.safe_write_json call.

P4a moved all bookmark file-I/O behind BookmarkRepository; _watcher_tick was
the one write that still reached past the repo into infra. Routing it back
through the repo keeps the read-merge-write (and the stale-tombstone GC that
merge_stores does) on every persisted path, and removes the re-leaked
safe_write_json import.
"""
import json

import pytest

from bootstrap.factories import make_bookmark_manager


def _make_manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr(
        "services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    return make_bookmark_manager(), tmp_path / "bookmarks.json"


def test_watcher_tick_persists_through_repo_save(tmp_path, monkeypatch):
    """An external on-disk change that the watcher reconciles must be written
    back via self._repo.save (so the merge/GC stays on the persisted path),
    not via a raw safe_write_json bypassing the repo."""
    mgr, path = _make_manager(tmp_path, monkeypatch)

    # Seed a real on-disk store via the normal write path.
    cat = mgr.create_category(name="C", color="#abc")
    mgr.create_bookmark(name="local", lat=1.0, lng=2.0, category_id=cat.id)

    # Simulate another device writing a NEW bookmark into the same file via
    # iCloud: append directly to the JSON on disk, then bump mtime backstop so
    # the watcher tick treats it as a fresh external write.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["bookmarks"].append(
        {
            "id": "remote-id",
            "name": "remote",
            "lat": 3.0,
            "lng": 4.0,
            "category_id": cat.id,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    mgr._last_loaded_mtime = 0.0  # force current_mtime > last_loaded so the tick proceeds

    # Spy on the repo.save so we can prove the watcher write goes through it.
    real_save = mgr._repo.save
    calls = []

    def _spy_save(store):
        calls.append(store)
        return real_save(store)

    monkeypatch.setattr(mgr._repo, "save", _spy_save)

    # Guard: if any code still reaches the raw infra write, blow up loudly.
    # NOTE: _watcher_tick wraps its body in `try/except Exception` and SWALLOWS
    # exceptions (logs them), so this AssertionError will NOT propagate out of
    # the tick — the real assertion that fails before the fix is `assert calls`
    # below (calls stays empty because the watcher never reached _repo.save).
    def _boom(*a, **k):  # pragma: no cover - only hit on regression
        raise AssertionError("watcher used raw safe_write_json, not self._repo.save")

    monkeypatch.setattr("services.bookmarks.safe_write_json", _boom, raising=False)

    mgr._watcher_tick()

    assert calls, "watcher reconcile did not persist through self._repo.save"
    # The remote bookmark survived the merge and is on disk.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    ids = {b["id"] for b in on_disk["bookmarks"]}
    assert "remote-id" in ids
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_watcher_writes_through_repo.py -v`. Expected failure (DRY-RUN-VERIFIED): `AssertionError: watcher reconcile did not persist through self._repo.save` / `assert []` — because before the edit `_watcher_tick` line 268 calls `safe_write_json`, never `self._repo.save`, so `calls` stays empty. (The `_boom` AssertionError DOES fire at line 268 but is caught by the tick's own `try/except Exception` and only logged as `ERROR services.bookmarks:bookmarks.py:281 Bookmark watcher tick failed` — it does NOT surface as the test's failure message. Do not expect the `_boom` text in the failure output.) The `raising=False` on the safe_write_json patch lets Step 1's patch survive even after Step 3 removes the import.

- [ ] **Step 3: Implement** — (a) route the watcher write through the repo, (b) drop the dead imports in BOTH managers.

In `backend/services/bookmarks.py`, replace the write branch of `_watcher_tick` (lines 260-273). Current code (verbatim):
```python
            with self._store_lock:
                before_payload = self.store.model_dump_json()
                self._reconcile_from_disk()
                after_payload = self.store.model_dump_json()
                if before_payload != after_payload:
                    # Persist the merged state so disk reflects local edits we
                    # may have reapplied on top of the remote update.
                    payload = json.loads(after_payload)
                    safe_write_json(path, payload)
                    self._record_disk_mtime()
                    fire_callback = True
                else:
                    self._record_disk_mtime()  # still resync mtime
                    fire_callback = False
```
New code (we already hold `_store_lock`, so call the repo directly — NOT `self._save()`, which would re-acquire the non-reentrant `threading.Lock` at `bookmarks.py:132/155` and deadlock):
```python
            with self._store_lock:
                before_payload = self.store.model_dump_json()
                self._reconcile_from_disk()
                after_payload = self.store.model_dump_json()
                if before_payload != after_payload:
                    # Persist the merged state through the repo (read-merge-write +
                    # tombstone GC) so disk reflects local edits we may have
                    # reapplied on top of the remote update. We already hold
                    # _store_lock, so call the repo directly rather than _save()
                    # (which would re-acquire the non-reentrant lock).
                    self.store = self._repo.save(self.store)
                    self._record_disk_mtime()
                    fire_callback = True
                else:
                    self._record_disk_mtime()  # still resync mtime
                    fire_callback = False
```
Note: the `payload = json.loads(after_payload)` line is removed with the block above. The local `path = self._repo.path()` from the top of `_watcher_tick` (line 247) is still used for the `current_mtime` stat — leave it.

Then fix the import line `backend/services/bookmarks.py:20`. Current (verbatim):
```python
from services.json_safe import safe_load_json, safe_write_json
```
After the watcher change, NEITHER `safe_load_json` nor `safe_write_json` is referenced anywhere in `bookmarks.py` (grep-confirmed: `safe_load_json` was already unused; `safe_write_json`'s only use was line 268). Delete the whole import line. KEEP the module-level `import json` (line 5) — it is still used by the import/merge CRUD paths at `bookmarks.py:574` and `bookmarks.py:631`; only the in-block `payload = json.loads(after_payload)` use is removed.

Next, fix `backend/services/route_store.py:30`. Current (verbatim):
```python
from services.json_safe import safe_load_json, safe_write_json
```
`route_store.py` references NEITHER name (grep-confirmed — its watcher merges in-memory and lets the next `_save()` flush; it never calls safe_write_json directly). Its own `import json` (line 15) is separate and still used at line 403 — leave it. Delete only this `from services.json_safe ...` line.

Confirm both deletions are safe before editing:
```bash
cd backend && grep -n 'safe_load_json\|safe_write_json' services/bookmarks.py services/route_store.py
```
Expected after edit: no matches in either file.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_watcher_writes_through_repo.py -v`. Expected (DRY-RUN-VERIFIED): 1 passed (`calls` non-empty; `remote-id` on disk).

- [ ] **Step 5 (danger-zone): Run the broader suite** — the watcher + thread-race + GC nets must stay green (DRY-RUN-VERIFIED green with the edit applied):
```bash
cd backend && .venv/bin/python -m pytest tests/test_bookmarks_thread_race.py tests/test_gc_through_save.py tests/test_watcher_writes_through_repo.py -v
```
Then the full suite: `cd backend && .venv/bin/python -m pytest -q`. Baseline is 914 collected (per `--collect-only -q`); your new test adds one node ID and removes none. The suite must stay green EXCEPT `tests/test_recent_isolation.py::test_recent_singleton_is_reset_and_writes_into_tmp`, which is a PRE-EXISTING full-suite run-order flake (it fails on unmodified `main` too and passes when run in isolation) — it is NOT caused by this change; confirm it still passes alone via `cd backend && .venv/bin/python -m pytest tests/test_recent_isolation.py::test_recent_singleton_is_reset_and_writes_into_tmp -q`. Also run import-linter so the no-`infra` re-leak doesn't trip a contract: `cd backend && .venv/bin/lint-imports` (expected `Contracts: 7 kept, 0 broken` — DRY-RUN-VERIFIED).

- [ ] **Step 6: Commit** — `git add backend/services/bookmarks.py backend/services/route_store.py backend/tests/test_watcher_writes_through_repo.py` then:
```
fix(bookmarks): route watcher write through the repo, drop re-leaked json_safe imports

_watcher_tick wrote via raw safe_write_json, bypassing BookmarkRepository and
re-introducing the infra dependency P4a removed (and skipping the repo's
read-merge-write + tombstone GC on that one path). Persist through
self._repo.save under the lock we already hold. safe_load_json/safe_write_json
are now unused in both bookmarks.py and route_store.py — delete the imports.
```


---

### Task 19: Downgrade migrate_pair's false "all-or-nothing" docstring to the truthful rollback contract

**Files:**
- Modify: `backend/services/cloud_sync.py:167-175` (the `migrate_pair` docstring)
- Test: `backend/tests/test_migrate_pair_rollback_honesty.py` (new)

**Interfaces:**
- Consumes: `migrate_pair(src_dir: Path, dst_dir: Path) -> None` from `backend/services/cloud_sync.py`; `_move_or_merge_file(src, dst, kind)` (the per-file mover the test patches); `merge_bookmark_stores(local_path, remote_path) -> None`, `merge_route_stores(local_path, remote_path) -> None` from `backend/services/sync_merge.py` (they write the union INTO the remote/dst path in place — confirmed at `sync_merge.py:104-121`).
- Produces: none (docstring-only behavior change; signature unchanged).

Why docstring-only: on a merge (both `src`/`dst` exist with different content), `_move_or_merge_file` (`cloud_sync.py:136-164`) calls `merge_bookmark_stores(src, dst)` / `merge_route_stores(src, dst)` which **write the merged union into dst in place** (`sync_merge.py:117`/`:137`). On a later failure, the rollback (lines 191-207) only restores `src` from the snapshot and unlinks dst files that did NOT exist before the call — it does NOT undo an in-place merge into a pre-existing dst. So "All-or-nothing" (line 170) is false. The merge is a CRDT union (commutative + idempotent), so a half-merged dst is convergent and safe to re-run; the correct fix is to state that truthfully rather than add real dst rollback (which would fight the CRDT design). A characterization test pins the actual behavior so the docstring matches reality.

- [ ] **Step 1: Write the failing test** — pin the REAL partial-failure behavior: a pre-existing dst that gets merged is NOT rolled back to its pre-merge bytes when a later step fails; src IS restored. Match `test_cloud_sync.py` import + tmp_path style.

```python
"""Characterization (A16): migrate_pair is NOT all-or-nothing across dst.

On a merge into a pre-existing dst file, a later failure restores src from
snapshot but leaves the (convergent, CRDT-merged) dst as-is. This pins that
behavior so the docstring stays honest. See cloud_sync.migrate_pair.
"""
from pathlib import Path

import pytest

from services import cloud_sync
from services.cloud_sync import migrate_pair


def _store(*names: str) -> str:
    # Minimal valid bookmark-store JSON with the given bookmark ids.
    import json
    return json.dumps(
        {
            "categories": [],
            "bookmarks": [
                {
                    "id": n,
                    "name": n,
                    "lat": 1.0,
                    "lng": 2.0,
                    "updated_at": "2025-01-01T00:00:00+00:00",
                }
                for n in names
            ],
        }
    )


def test_partial_failure_restores_src_but_not_premerge_dst(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    # bookmarks: both sides exist with different content -> triggers a real merge.
    (src_dir / "bookmarks.json").write_text(_store("from-src"), encoding="utf-8")
    (dst_dir / "bookmarks.json").write_text(_store("already-in-dst"), encoding="utf-8")
    dst_bookmarks_before = (dst_dir / "bookmarks.json").read_text(encoding="utf-8")

    # routes: present in src so the SECOND _PAIR_FILES iteration runs and we can
    # make it blow up, proving the bookmarks merge already happened + isn't undone.
    # (_PAIR_FILES order is bookmarks-then-routes, confirmed at cloud_sync.py:130.)
    (src_dir / "routes.json").write_text(_store("r1"), encoding="utf-8")

    # Force the routes step to fail AFTER the bookmarks merge mutated dst.
    real_move = cloud_sync._move_or_merge_file

    def _boom(src, dst, kind):
        if kind == "routes":
            raise RuntimeError("simulated routes-move failure")
        return real_move(src, dst, kind)

    monkeypatch.setattr(cloud_sync, "_move_or_merge_file", _boom)

    with pytest.raises(RuntimeError, match="simulated routes-move failure"):
        migrate_pair(src_dir, dst_dir)

    # src restored from snapshot (the bookmarks src was unlinked by the merge,
    # then put back by rollback).
    assert (src_dir / "bookmarks.json").exists(), "src bookmarks not restored on failure"
    # dst was MERGED in place and is NOT rolled back to its pre-merge bytes:
    # the convergent union now contains BOTH ids.
    import json
    dst_after = json.loads((dst_dir / "bookmarks.json").read_text(encoding="utf-8"))
    ids = {b["id"] for b in dst_after["bookmarks"]}
    assert ids == {"from-src", "already-in-dst"}, (
        "dst should hold the convergent union, proving it is not all-or-nothing"
    )
    assert (dst_dir / "bookmarks.json").read_text(encoding="utf-8") != dst_bookmarks_before
```

- [ ] **Step 2: Run test, verify it is GREEN (non-vacuous), not red** — `cd backend && .venv/bin/python -m pytest tests/test_migrate_pair_rollback_honesty.py -v`. This is a CHARACTERIZATION test: it pins the REAL behavior, not the (wrong) docstring, so it PASSES against the current implementation (DRY-RUN-VERIFIED: 1 passed against today's `main`). Running it first confirms it is GREEN and non-vacuous — that GREEN result is the proof that the docstring's "all-or-nothing" claim is false. If it unexpectedly fails (e.g. the merge serialization differs), inspect the actual `dst_after` ids in the assertion message and adjust the expected set to the real convergent union BEFORE editing the docstring. (The docstring edit itself has no failing-test gate; the test exists to document the true contract the new docstring describes.)

- [ ] **Step 3: Implement** — fix the docstring. Current `backend/services/cloud_sync.py:167-175` (verbatim):
```python
def migrate_pair(src_dir: Path, dst_dir: Path) -> None:
    """Move bookmarks.json + routes.json from *src_dir* to *dst_dir*.

    All-or-nothing: on any failure, restore *src_dir* to its original
    state, remove any files newly created in *dst_dir* by this call, then
    re-raise.

    Union-merges when a file exists on both sides with different content.
    """
```
New:
```python
def migrate_pair(src_dir: Path, dst_dir: Path) -> None:
    """Move bookmarks.json + routes.json from *src_dir* to *dst_dir*.

    Rollback contract (NOT all-or-nothing across *dst*): on any failure we
    restore *src_dir* from a snapshot and unlink only *dst* files that did
    NOT exist before this call. A file that already existed in *dst* and was
    union-merged in place is left as-is — the merge is a CRDT union
    (commutative + idempotent), so a half-merged *dst* is convergent and the
    whole migration is safe to retry. Src is restored on failure; dst merges
    are convergent and safe to re-run.

    Union-merges when a file exists on both sides with different content.
    """
```

- [ ] **Step 4: Run test, verify it still passes** — `cd backend && .venv/bin/python -m pytest tests/test_migrate_pair_rollback_honesty.py -v`. Expected: 1 passed (unchanged by the docstring edit; confirms the test still pins the now-documented behavior).

- [ ] **Step 5: Run the broader suite** — `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync.py tests/test_cloud_sync_service_char.py tests/test_migrate_pair_rollback_honesty.py -q`. Expected: all green.

- [ ] **Step 6: Commit** — `git add backend/services/cloud_sync.py backend/tests/test_migrate_pair_rollback_honesty.py` then:
```
docs(cloud_sync): correct migrate_pair rollback docstring (src restored; dst merges convergent)

The old docstring claimed "all-or-nothing", but a union-merge into a
pre-existing dst file is NOT undone on a later failure — only src is
restored and newly-created dst files are unlinked. State the truthful
contract; add a characterization test pinning the convergent-dst behavior.
```


---

### Task 20: Pull evicted iCloud files (materialize_if_placeholder) at the top of enable()/disable() before migrating

**Files:**
- Modify: `backend/services/cloud_sync_service.py:25-27` (imports), `backend/services/cloud_sync_service.py:82-86` (`enable` body, before `migrate_pair(_config.DATA_DIR, target_folder)`), and `backend/services/cloud_sync_service.py:126-131` (`disable` body, before `migrate_pair(current, _config.DATA_DIR)`)
- Test: `backend/tests/test_cloud_sync_materialize_before_migrate.py` (new)

**Interfaces:**
- Consumes: `materialize_if_placeholder(path: Path) -> None` from `backend/services/cloud_sync.py` (defined at `cloud_sync.py:44`); `migrate_pair`, `setup_sync_folder`, `detect_icloud_path` already imported in the service; `config.DATA_DIR` via the module alias `_config` (`import config as _config` at `cloud_sync_service.py:21`). The pair filenames are `bookmarks.json` + `routes.json` (from `services/cloud_sync._PAIR_FILES`).
- Produces: none (no new public surface; `enable`/`disable` now call `materialize_if_placeholder` on each src `*.json` before migrating).

Why: `materialize_if_placeholder` (written for this) currently has NO non-test caller. When iCloud has evicted `bookmarks.json`/`routes.json` to a `.<name>.icloud` placeholder, `migrate_pair`'s `_move_or_merge_file` sees `not src.exists()` (`cloud_sync.py:142`) and silently no-ops — the user's data is on disk-as-placeholder but the migration skips it. Calling `materialize_if_placeholder` first forces a synchronous `brctl download`. `materialize_if_placeholder` is already a safe no-op when there's no placeholder / non-macOS / brctl missing (see `test_icloud_materialize.py`), so this is additive.

- [ ] **Step 1: Write the failing test** — assert `enable()` and `disable()` materialize each src `*.json` before migrating. Reuse the `_SpyAppState` / `_CapBroadcast` / `_patch_managers` harness in `test_cloud_sync_service_char.py` (they are module-level and importable; `_SpyAppState.__init__(log, tmp_path, *, raise_on_restart=False)`).

```python
"""A19: enable()/disable() must materialize evicted iCloud placeholders for the
source bookmarks/routes files BEFORE migrate_pair, so cold-evicted data isn't
silently skipped by migrate_pair's `not src.exists()` no-op.
"""
from __future__ import annotations

import pytest

import services.cloud_sync_service as css_mod
from services.cloud_sync_service import CloudSyncService
from models.schemas import CloudSyncEnableRequest

# Reuse the spy harness from the characterization test.
from tests.test_cloud_sync_service_char import (
    _SpyAppState,
    _CapBroadcast,
    _patch_managers,
)

pytestmark = pytest.mark.asyncio


async def test_enable_materializes_src_files_before_migrate(monkeypatch, tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path, raise_on_restart=True)
    bc = _CapBroadcast()
    target = tmp_path / "LocWarp"

    materialized: list[str] = []
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(css_mod, "setup_sync_folder", lambda *a, **k: target)
    monkeypatch.setattr(
        css_mod, "materialize_if_placeholder",
        lambda p: materialized.append(p.name),
    )
    # migrate_pair runs AFTER materialize — record ordering via the log.
    def _fake_migrate(src, dst):
        log.append("migrate")
    monkeypatch.setattr(css_mod, "migrate_pair", _fake_migrate)
    # DATA_DIR is the src for enable(); point it somewhere real under tmp.
    src_dir = tmp_path / "data"
    src_dir.mkdir()
    monkeypatch.setattr(css_mod._config, "DATA_DIR", src_dir)
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    await svc.enable(CloudSyncEnableRequest(folder=None))

    # both src files were materialized, and BEFORE migrate ran
    assert set(materialized) == {"bookmarks.json", "routes.json"}
    assert "migrate" in log


async def test_disable_materializes_src_files_before_migrate(monkeypatch, tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    sync_dir = tmp_path / "LocWarp"
    sync_dir.mkdir()
    app._sync_folder = str(sync_dir)
    bc = _CapBroadcast()

    materialized: list[str] = []
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(
        css_mod, "materialize_if_placeholder",
        lambda p: materialized.append(p.name),
    )
    monkeypatch.setattr(css_mod, "migrate_pair", lambda src, dst: log.append("migrate"))
    monkeypatch.setattr(css_mod._config, "DATA_DIR", tmp_path / "data")
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    await svc.disable()

    assert set(materialized) == {"bookmarks.json", "routes.json"}
    assert "migrate" in log
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_materialize_before_migrate.py -v`. Expected failure: `AssertionError: assert set() == {'bookmarks.json', 'routes.json'}` (the service never calls `materialize_if_placeholder`, so `materialized` is empty). It may instead fail at the `monkeypatch.setattr(css_mod, "materialize_if_placeholder", ...)` line with `AttributeError: <module 'services.cloud_sync_service'> has no attribute 'materialize_if_placeholder'` — that is the SAME gap (the name is not yet imported into the service module); fix in Step 3.

- [ ] **Step 3: Implement** — import `materialize_if_placeholder` into the service and call it on each src `*.json` before `migrate_pair`.

Fix the import block. Current `backend/services/cloud_sync_service.py:25-27` (verbatim):
```python
from services.cloud_sync import (
    detect_icloud_path, migrate_pair, setup_sync_folder,
)
```
New:
```python
from services.cloud_sync import (
    detect_icloud_path, materialize_if_placeholder, migrate_pair, setup_sync_folder,
)
```

Add a small private helper inside the `CloudSyncService` class (place it after `build_status`, before `enable` — i.e. between `cloud_sync_service.py:66` and `:68`) so enable + disable share it:
```python
    @staticmethod
    def _materialize_src(src_dir: Path) -> None:
        """Force-download any iCloud-evicted bookmarks/routes placeholder under
        *src_dir* before a migrate, so cold-evicted data is not silently
        skipped by migrate_pair's `not src.exists()` no-op. No-op when the
        files are already local / not under iCloud / brctl is unavailable."""
        for name in ("bookmarks.json", "routes.json"):
            materialize_if_placeholder(src_dir / name)
```

In `enable`, insert the call right before the `migrate_pair` block. Current `backend/services/cloud_sync_service.py:82-86` (verbatim):
```python
        try:
            migrate_pair(_config.DATA_DIR, target_folder)
        except Exception as exc:
            logger.exception("cloud-sync enable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")
```
New:
```python
        # Pull any iCloud-evicted source files local first, else migrate_pair
        # silently skips a placeholder it sees as a missing src.
        self._materialize_src(_config.DATA_DIR)
        try:
            migrate_pair(_config.DATA_DIR, target_folder)
        except Exception as exc:
            logger.exception("cloud-sync enable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")
```

In `disable`, the src is the sync folder. Insert before the `migrate_pair(current, _config.DATA_DIR)` block. Current `backend/services/cloud_sync_service.py:126-131` (verbatim):
```python
        current = Path(self._app._sync_folder)
        try:
            migrate_pair(current, _config.DATA_DIR)
        except Exception as exc:
            logger.exception("cloud-sync disable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")
```
New:
```python
        current = Path(self._app._sync_folder)
        # Pull any iCloud-evicted files in the sync folder local first, else
        # the migrate-back silently drops a cloud-only-evicted store and the
        # canonical link is cut with _sync_folder=None below (A19).
        self._materialize_src(current)
        try:
            migrate_pair(current, _config.DATA_DIR)
        except Exception as exc:
            logger.exception("cloud-sync disable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")
```

Scope note on the A19 "raise if still missing" sub-point: do NOT add an unconditional raise. The current `disable()` does not early-return on a missing src (it always runs `migrate_pair`, which no-ops per file via the `not src.exists()` guard at `cloud_sync.py:142`). A blanket "raise if any src missing" would REGRESS the legitimate fresh-install case (no bookmarks/routes yet → enabling sync would 503). The safe, scoped fix is materialize-first only; the existing per-file `not src.exists()` no-op in `migrate_pair` then correctly handles "genuinely absent" vs "now materialized". A stronger guard that distinguishes "placeholder present but materialize failed" from "no file at all" is out of scope here and should be its own finding.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_materialize_before_migrate.py -v`. Expected: 2 passed.

- [ ] **Step 5: Run the broader suite** — the cloud-sync char test must stay green (the new helper + calls must not perturb the stop/restart/broadcast ordering):
```bash
cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_service_char.py tests/test_icloud_materialize.py tests/test_cloud_sync.py tests/test_cloud_sync_materialize_before_migrate.py -q
```
Then full suite: `cd backend && .venv/bin/python -m pytest -q` — must stay green except the PRE-EXISTING `tests/test_recent_isolation.py::test_recent_singleton_is_reset_and_writes_into_tmp` full-suite run-order flake (unrelated to this change; passes in isolation).

- [ ] **Step 6: Commit** — `git add backend/services/cloud_sync_service.py backend/tests/test_cloud_sync_materialize_before_migrate.py` then:
```
fix(cloud_sync): materialize evicted iCloud files before enable/disable migrate

materialize_if_placeholder had no non-test caller, so an iCloud-evicted
bookmarks/routes file (a .<name>.icloud placeholder) was silently skipped by
migrate_pair's `not src.exists()` no-op — losing data on enable, and cutting
the canonical link on disable. Force a synchronous brctl download of each src
store before migrating; the call is a safe no-op off-iCloud / without brctl.
```


---


<!-- ===== C6 · CloudSync busy overlay timeout + escape hatch (frontend) ===== -->

### Task 21: Client-side timeout for cloud-sync toggle so the busy overlay can never lock forever

**Files:**
- Modify: `frontend/src/services/api.ts:6-18` (thread an optional `AbortSignal` through `fetchWithRetry`, and stop retrying on an abort)
- Modify: `frontend/src/services/api.ts:112-124` (thread the signal through `request`)
- Modify: `frontend/src/services/api.ts:524-528` (accept a `signal` on `cloudSyncEnable` / `cloudSyncDisable`)
- Modify: `frontend/src/contexts/CloudSyncBusyContext.tsx:23-61` (give `run` a per-call `AbortController` + a 35s timeout; pass the signal into `fn`)
- Modify: `frontend/src/components/CloudSyncSection.tsx:29-40` (thread the signal into the cloud-sync call)
- Test: `frontend/src/contexts/CloudSyncBusyContext.test.tsx` (new file)

**Interfaces:**
- Consumes: none
- Produces:
  - `fetchWithRetry(url: string, opts: RequestInit, maxAttempts?: number, signal?: AbortSignal): Promise<Response>`
  - `request<T>(method, path, body?, signal?: AbortSignal): Promise<T>`
  - `cloudSyncEnable(folder?: string, signal?: AbortSignal): Promise<CloudSyncStatus>`
  - `cloudSyncDisable(signal?: AbortSignal): Promise<CloudSyncStatus>`
  - `CloudSyncBusyContextValue.run<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T>` (the `fn` callback now receives an `AbortSignal`; existing zero-arg lambdas still type-check)
  - exported constant `CLOUD_SYNC_TIMEOUT_MS = 35000` from `CloudSyncBusyContext.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/contexts/CloudSyncBusyContext.test.tsx`. NOTE: this repo's fake-timer env STARVES `waitFor` (it polls on real timers — see the comment in `src/hooks/useLocationMeta.test.ts`), so use `await vi.advanceTimersByTimeAsync(...)` inside `act` and assert `busy` directly, never `await waitFor(...)`:

```tsx
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  CloudSyncBusyProvider,
  useCloudSyncBusy,
  CLOUD_SYNC_TIMEOUT_MS,
} from './CloudSyncBusyContext'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <CloudSyncBusyProvider>{children}</CloudSyncBusyProvider>
)

describe('CloudSyncBusyContext run() timeout', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('exposes a 35s timeout constant', () => {
    expect(CLOUD_SYNC_TIMEOUT_MS).toBe(35000)
  })

  it('sets busy true while the toggle is in flight', () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })
    expect(result.current.busy).toBe(false)
    act(() => { void result.current.run(() => new Promise(() => {})) })
    expect(result.current.busy).toBe(true)
  })

  it('aborts the in-flight fn and clears busy + rejects when the toggle stalls past the timeout', async () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })

    let observedSignal: AbortSignal | undefined
    let rejected: unknown
    // fn never resolves on its own; it only settles when its signal aborts.
    const fn = (signal: AbortSignal) =>
      new Promise<never>((_, reject) => {
        observedSignal = signal
        signal.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })

    act(() => {
      result.current.run(fn).catch((e) => { rejected = e })
    })
    expect(result.current.busy).toBe(true)
    expect(observedSignal?.aborted).toBe(false)

    // Cross the timeout deadline; advanceTimersByTimeAsync drains the abort
    // event + the rejection + run()'s finally (setBusy(false)) as microtasks.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOUD_SYNC_TIMEOUT_MS)
    })

    expect(observedSignal?.aborted).toBe(true)
    expect(result.current.busy).toBe(false)
    expect((rejected as Error)?.name).toBe('AbortError')
  })

  it('does NOT abort and clears busy normally when the toggle resolves before the timeout', async () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })

    let observedSignal: AbortSignal | undefined
    const fn = (signal: AbortSignal) => {
      observedSignal = signal
      return Promise.resolve('ok')
    }

    let resolved: unknown
    await act(async () => {
      resolved = await result.current.run(fn)
    })

    expect(resolved).toBe('ok')
    expect(observedSignal?.aborted).toBe(false)
    expect(result.current.busy).toBe(false)
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/contexts/CloudSyncBusyContext.test.tsx`. Expected failure: the `import { CLOUD_SYNC_TIMEOUT_MS } from './CloudSyncBusyContext'` resolves to `undefined` (so `expect(CLOUD_SYNC_TIMEOUT_MS).toBe(35000)` fails), and the stall test never aborts (`observedSignal?.aborted` stays `false`, `busy` stays `true`) because today's `run` neither passes a signal to `fn` nor arms a timeout.

- [ ] **Step 3: Implement** —

  **3a. `frontend/src/services/api.ts:6-18`** — replace the current `fetchWithRetry`:

  ```ts
  // Connection-refused means backend isn't up yet, retry with backoff.
  // Other HTTP errors (4xx/5xx) are real errors and propagate immediately.
  async function fetchWithRetry(url: string, opts: RequestInit, maxAttempts = 15): Promise<Response> {
    let lastErr: unknown
    for (let i = 0; i < maxAttempts; i++) {
      try {
        return await fetch(url, opts)
      } catch (e) {
        lastErr = e
        const delay = Math.min(500 + i * 300, 2000)
        await new Promise((r) => setTimeout(r, delay))
      }
    }
    throw lastErr ?? new Error('fetch failed')
  }
  ```

  with (thread `signal` into `fetch`, and treat an abort as terminal — never retry it, otherwise the loop would re-issue the request and re-block):

  ```ts
  // Connection-refused means backend isn't up yet, retry with backoff.
  // Other HTTP errors (4xx/5xx) are real errors and propagate immediately.
  // An AbortError (caller timeout / Cancel) is terminal — never retry it,
  // or the busy overlay would re-arm against a fresh attempt.
  async function fetchWithRetry(
    url: string,
    opts: RequestInit,
    maxAttempts = 15,
    signal?: AbortSignal,
  ): Promise<Response> {
    let lastErr: unknown
    for (let i = 0; i < maxAttempts; i++) {
      try {
        return await fetch(url, { ...opts, ...(signal ? { signal } : {}) })
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') throw e
        lastErr = e
        const delay = Math.min(500 + i * 300, 2000)
        await new Promise((r) => setTimeout(r, delay))
      }
    }
    throw lastErr ?? new Error('fetch failed')
  }
  ```

  **3b. `frontend/src/services/api.ts:112-124`** — replace the current `request`:

  ```ts
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const opts: RequestInit = {
      method,
      headers: { 'Content-Type': 'application/json' },
    }
    if (body !== undefined) opts.body = JSON.stringify(body)
    const res = await fetchWithRetry(`${API}${path}`, opts)
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new HttpError(formatError(err.detail, res.statusText), res.status)
    }
    return res.json()
  }
  ```

  with (extra optional `signal` arg, passed straight through — every existing call site omits it and is unaffected):

  ```ts
  async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const opts: RequestInit = {
      method,
      headers: { 'Content-Type': 'application/json' },
    }
    if (body !== undefined) opts.body = JSON.stringify(body)
    const res = await fetchWithRetry(`${API}${path}`, opts, 15, signal)
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new HttpError(formatError(err.detail, res.statusText), res.status)
    }
    return res.json()
  }
  ```

  **3c. `frontend/src/services/api.ts:524-528`** — replace the two cloud-sync mutators:

  ```ts
  export const cloudSyncEnable = (folder?: string) =>
    request<CloudSyncStatus>('POST', '/api/cloud-sync/enable', { folder: folder ?? null })

  export const cloudSyncDisable = () =>
    request<CloudSyncStatus>('POST', '/api/cloud-sync/disable')
  ```

  with:

  ```ts
  export const cloudSyncEnable = (folder?: string, signal?: AbortSignal) =>
    request<CloudSyncStatus>('POST', '/api/cloud-sync/enable', { folder: folder ?? null }, signal)

  export const cloudSyncDisable = (signal?: AbortSignal) =>
    request<CloudSyncStatus>('POST', '/api/cloud-sync/disable', undefined, signal)
  ```

  **3d. `frontend/src/contexts/CloudSyncBusyContext.tsx:23-61`** — change the context type, `run`, and add the timeout constant. First, replace the type + default `Ctx` (lines 23-34):

  ```ts
  type CloudSyncBusyContextValue = {
    busy: boolean
    run<T>(fn: () => Promise<T>): Promise<T>
    /** Internal: replace the post-toggle hook. Prefer ``useCloudSyncAfter``. */
    _setAfter(fn: AfterFn | null): void
  }

  const Ctx = createContext<CloudSyncBusyContextValue>({
    busy: false,
    run: async (fn) => fn(),
    _setAfter: () => undefined,
  })
  ```

  with (add the timeout constant above the type; `run`'s `fn` now takes a signal; the no-op default ignores it):

  ```ts
  /**
   * Hard ceiling on a single cloud-sync toggle. A backend stuck mid
   * ``migrate_pair`` (cold iCloud cache, hung atomic write) must not pin
   * the zIndex-9999 busy overlay open forever — at this deadline we abort
   * the in-flight request so ``run``'s ``finally`` clears ``busy``.
   */
  export const CLOUD_SYNC_TIMEOUT_MS = 35000

  type CloudSyncBusyContextValue = {
    busy: boolean
    run<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T>
    /** Internal: replace the post-toggle hook. Prefer ``useCloudSyncAfter``. */
    _setAfter(fn: AfterFn | null): void
  }

  const Ctx = createContext<CloudSyncBusyContextValue>({
    busy: false,
    run: async (fn) => fn(new AbortController().signal),
    _setAfter: () => undefined,
  })
  ```

  Then replace `run` (lines 44-57):

  ```ts
  const run = useCallback(async <T,>(fn: () => Promise<T>) => {
    setBusy(true)
    try {
      const result = await fn()
      try {
        await afterRef.current?.()
      } catch {
        /* refresh failure must not mask toggle outcome */
      }
      return result
    } finally {
      setBusy(false)
    }
  }, [])
  ```

  with (arm an AbortController + timeout; abort on stall; always clear the timer + busy):

  ```ts
  const run = useCallback(async <T,>(fn: (signal: AbortSignal) => Promise<T>) => {
    setBusy(true)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), CLOUD_SYNC_TIMEOUT_MS)
    try {
      const result = await fn(controller.signal)
      try {
        await afterRef.current?.()
      } catch {
        /* refresh failure must not mask toggle outcome */
      }
      return result
    } finally {
      clearTimeout(timer)
      setBusy(false)
    }
  }, [])
  ```

  **3e. `frontend/src/components/CloudSyncSection.tsx:29-40`** — thread the signal into the cloud-sync call so the abort actually cancels the fetch. Replace `onToggle`:

  ```tsx
  const onToggle = async () => {
    if (!status) return
    setError(null)
    try {
      const next = await run(() =>
        status.enabled ? cloudSyncDisable() : cloudSyncEnable(),
      )
      setStatus(next)
    } catch (e) {
      setError(String(e))
    }
  }
  ```

  with:

  ```tsx
  const onToggle = async () => {
    if (!status) return
    setError(null)
    try {
      const next = await run((signal) =>
        status.enabled ? cloudSyncDisable(signal) : cloudSyncEnable(undefined, signal),
      )
      setStatus(next)
    } catch (e) {
      setError(String(e))
    }
  }
  ```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/contexts/CloudSyncBusyContext.test.tsx`. Expected: 4 passed. Also confirm types: `cd frontend && npx tsc --noEmit` (expected: no output / exit 0 — the existing `run(() => api.cloudSyncEnable())` lambda at `App.tsx:58` and `CloudSyncSection`'s threaded-signal lambda both satisfy `(signal: AbortSignal) => Promise<T>`).

- [ ] **Step 5: Run the broader suite** — the change touches the shared `request`/`fetchWithRetry` used by every endpoint, so run the full frontend suite: `cd frontend && npx vitest run`. Expected: all green, including the existing `src/components/CloudSyncSection.test.tsx` (its `runMock` is `vi.fn(async (fn) => fn())` which still passes — `fn` is now called with no signal in the mock, and the real `cloudSyncEnable`/`cloudSyncDisable` are mocked so the missing signal arg is irrelevant) and `src/components/CloudSyncBusyOverlay.test.tsx`.

- [ ] **Step 6: Commit** — `git add frontend/src/services/api.ts frontend/src/contexts/CloudSyncBusyContext.tsx frontend/src/components/CloudSyncSection.tsx frontend/src/contexts/CloudSyncBusyContext.test.tsx` then:

  `git commit -m "fix(cloud-sync): abort a stalled toggle after 35s so the busy overlay can't lock the UI forever"`


---

### Task 22: Escape hatch — "taking longer" message + Cancel button on the cloud-sync busy overlay after 10s

**Files:**
- Modify: `frontend/src/contexts/CloudSyncBusyContext.tsx` (expose `tookTooLong: boolean` + `cancel(): void`; flip `tookTooLong` after 10s; wire `cancel` to abort the live controller)
- Modify: `frontend/src/components/CloudSyncBusyOverlay.tsx:11-76` (when `tookTooLong`, show a "taking longer" line + a Cancel button that calls `cancel()`; preserve `role="alert" aria-live="assertive"`)
- Modify: `frontend/src/i18n/strings.ts:754` (add `cloud_sync.busy_taking_longer` + `cloud_sync.busy_cancel` after the existing `cloud_sync.busy_hint`)
- Test: `frontend/src/components/CloudSyncBusyOverlay.test.tsx` (extend the existing file)

**Interfaces:**
- Consumes (from the previous task): `CLOUD_SYNC_TIMEOUT_MS`, `run<T>(fn: (signal: AbortSignal) => Promise<T>)`, the per-`run` `AbortController`
- Produces:
  - `CloudSyncBusyContextValue` gains `tookTooLong: boolean` and `cancel(): void`
  - exported constant `CLOUD_SYNC_SLOW_HINT_MS = 10000`
  - i18n keys `cloud_sync.busy_taking_longer`, `cloud_sync.busy_cancel`

- [ ] **Step 1: Write the failing test** — append these two `it` blocks inside the existing `describe('CloudSyncBusyOverlay', …)` in `frontend/src/components/CloudSyncBusyOverlay.test.tsx`. The existing file mocks the context as `useCloudSyncBusy: () => ({ busy: busyValue })` (lines 10-13); widen that mock to carry the new fields and a spyable `cancel`. Replace lines 10-13:

  ```tsx
  let busyValue = false
  vi.mock('../contexts/CloudSyncBusyContext', () => ({
    useCloudSyncBusy: () => ({ busy: busyValue }),
  }))
  ```

  with:

  ```tsx
  let busyValue = false
  let tookTooLongValue = false
  const cancelMock = vi.fn()
  vi.mock('../contexts/CloudSyncBusyContext', () => ({
    useCloudSyncBusy: () => ({
      busy: busyValue,
      tookTooLong: tookTooLongValue,
      cancel: cancelMock,
    }),
  }))
  ```

  and replace the existing `beforeEach` (lines 16-18) with one that also resets the new state:

  ```tsx
  beforeEach(() => {
    busyValue = false
    tookTooLongValue = false
    cancelMock.mockClear()
  })
  ```

  Then add `fireEvent` to the `@testing-library/react` import on line 3 (`import { render, screen, fireEvent } from '@testing-library/react'`) and add these tests inside the `describe`:

  ```tsx
  it('does not show the taking-longer hint or Cancel button before the slow threshold', () => {
    busyValue = true
    tookTooLongValue = false
    render(<CloudSyncBusyOverlay />)
    expect(screen.queryByText('cloud_sync.busy_taking_longer')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'cloud_sync.busy_cancel' })).not.toBeInTheDocument()
  })

  it('shows the taking-longer hint + a Cancel button once tookTooLong, and Cancel calls cancel()', () => {
    busyValue = true
    tookTooLongValue = true
    render(<CloudSyncBusyOverlay />)

    // The blocking alert + aria-live semantics are preserved.
    const overlay = screen.getByRole('alert')
    expect(overlay).toHaveAttribute('aria-live', 'assertive')

    expect(screen.getByText('cloud_sync.busy_taking_longer')).toBeInTheDocument()
    const cancelBtn = screen.getByRole('button', { name: 'cloud_sync.busy_cancel' })
    fireEvent.click(cancelBtn)
    expect(cancelMock).toHaveBeenCalledTimes(1)
  })
  ```

  Also add a context-level test in `frontend/src/contexts/CloudSyncBusyContext.test.tsx` (created in the previous task) — append inside its `describe`. As in the timeout task (Task 21), use `await vi.advanceTimersByTimeAsync(...)` (NOT `waitFor`, which the fake-timer env starves):

  ```tsx
  it('flips tookTooLong after the slow-hint threshold and cancel() aborts + clears busy', async () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })

    let observedSignal: AbortSignal | undefined
    let rejected: unknown
    const fn = (signal: AbortSignal) =>
      new Promise<never>((_, reject) => {
        observedSignal = signal
        signal.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })

    act(() => { result.current.run(fn).catch((e) => { rejected = e }) })
    expect(result.current.tookTooLong).toBe(false)

    // Cross the 10s slow-hint threshold (but not the 35s hard timeout).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOUD_SYNC_SLOW_HINT_MS)
    })
    expect(result.current.tookTooLong).toBe(true)
    expect(observedSignal?.aborted).toBe(false)

    // User hits Cancel; advanceTimersByTimeAsync(0) drains the abort event +
    // the rejection + run()'s finally as microtasks.
    await act(async () => {
      result.current.cancel()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(observedSignal?.aborted).toBe(true)
    expect(result.current.busy).toBe(false)
    expect(result.current.tookTooLong).toBe(false)
    expect((rejected as Error)?.name).toBe('AbortError')
  })
  ```

  Add `CLOUD_SYNC_SLOW_HINT_MS` to the import in that file: `import { CloudSyncBusyProvider, useCloudSyncBusy, CLOUD_SYNC_TIMEOUT_MS, CLOUD_SYNC_SLOW_HINT_MS } from './CloudSyncBusyContext'`.

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/CloudSyncBusyOverlay.test.tsx src/contexts/CloudSyncBusyContext.test.tsx`. Expected failure: the overlay renders no `cloud_sync.busy_taking_longer` text and no Cancel button (it ignores `tookTooLong`), and the context has no `tookTooLong`/`cancel`/`CLOUD_SYNC_SLOW_HINT_MS` exports (so `CLOUD_SYNC_SLOW_HINT_MS` is `undefined` and `result.current.cancel` is `undefined`).

- [ ] **Step 3: Implement** —

  **3a. `frontend/src/i18n/strings.ts`** — after line 754 (`'cloud_sync.busy_hint': { … },`), add two keys:

  ```ts
    'cloud_sync.busy_taking_longer': { zh: '同步比預期久，可能是 iCloud 仍在下載。可繼續等待，或取消後再試。', en: 'This is taking longer than expected — iCloud may still be downloading. Keep waiting, or cancel and retry.' },
    'cloud_sync.busy_cancel': { zh: '取消', en: 'Cancel' },
  ```

  **3b. `frontend/src/contexts/CloudSyncBusyContext.tsx`** — add the slow-hint constant, two new state/ref slots, `cancel`, and the slow-hint timer. Add below `CLOUD_SYNC_TIMEOUT_MS`:

  ```ts
  /** After this long, surface a "taking longer…" line + a Cancel button. */
  export const CLOUD_SYNC_SLOW_HINT_MS = 10000
  ```

  Extend the context type + default `Ctx` (add the two fields):

  ```ts
  type CloudSyncBusyContextValue = {
    busy: boolean
    tookTooLong: boolean
    run<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T>
    cancel(): void
    /** Internal: replace the post-toggle hook. Prefer ``useCloudSyncAfter``. */
    _setAfter(fn: AfterFn | null): void
  }

  const Ctx = createContext<CloudSyncBusyContextValue>({
    busy: false,
    tookTooLong: false,
    run: async (fn) => fn(new AbortController().signal),
    cancel: () => undefined,
    _setAfter: () => undefined,
  })
  ```

  In the provider, add state + a ref to the live controller (next to the existing `const [busy, setBusy] = useState(false)` / `const afterRef = useRef<AfterFn | null>(null)`):

  ```ts
  const [tookTooLong, setTookTooLong] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  ```

  Add `cancel` (above `run`):

  ```ts
  const cancel = useCallback(() => {
    controllerRef.current?.abort()
  }, [])
  ```

  Replace the `run` body from the previous task with one that also arms/clears the slow-hint timer, tracks the live controller, and resets `tookTooLong`:

  ```ts
  const run = useCallback(async <T,>(fn: (signal: AbortSignal) => Promise<T>) => {
    setBusy(true)
    setTookTooLong(false)
    const controller = new AbortController()
    controllerRef.current = controller
    const slowTimer = setTimeout(() => setTookTooLong(true), CLOUD_SYNC_SLOW_HINT_MS)
    const timer = setTimeout(() => controller.abort(), CLOUD_SYNC_TIMEOUT_MS)
    try {
      const result = await fn(controller.signal)
      try {
        await afterRef.current?.()
      } catch {
        /* refresh failure must not mask toggle outcome */
      }
      return result
    } finally {
      clearTimeout(slowTimer)
      clearTimeout(timer)
      controllerRef.current = null
      setTookTooLong(false)
      setBusy(false)
    }
  }, [])
  ```

  Update the `value` memo (currently `const value = useMemo(() => ({ busy, run, _setAfter }), [busy, run, _setAfter])`) to expose the new fields:

  ```ts
  const value = useMemo(
    () => ({ busy, tookTooLong, run, cancel, _setAfter }),
    [busy, tookTooLong, run, cancel, _setAfter],
  )
  ```

  **3c. `frontend/src/components/CloudSyncBusyOverlay.tsx`** — consume `tookTooLong` + `cancel` and render the escape hatch. Change line 13:

  ```tsx
    const { busy } = useCloudSyncBusy()
  ```

  to:

  ```tsx
    const { busy, tookTooLong, cancel } = useCloudSyncBusy()
  ```

  Add a button style next to the existing `spinner` style object (after line 60):

  ```tsx
    const cancelBtn: React.CSSProperties = {
      marginTop: 4,
      padding: '6px 16px',
      fontSize: 12,
      fontWeight: 600,
      color: '#e8eaf0',
      background: 'rgba(255,255,255,0.08)',
      border: '1px solid rgba(255,255,255,0.16)',
      borderRadius: 8,
      cursor: 'pointer',
    }
  ```

  Replace the card JSX (lines 69-73) — keep the `role="alert" aria-live="assertive"` backdrop (line 63) UNTOUCHED, add the slow-hint line + Cancel button inside the `card` div after the existing hint:

  ```tsx
        <div style={card}>
          <div style={spinner} aria-hidden />
          <div style={title}>{t('cloud_sync.busy_title')}</div>
          <p style={hint}>{t('cloud_sync.busy_hint')}</p>
          {tookTooLong && (
            <>
              <p style={hint}>{t('cloud_sync.busy_taking_longer')}</p>
              <button type="button" style={cancelBtn} onClick={cancel}>
                {t('cloud_sync.busy_cancel')}
              </button>
            </>
          )}
        </div>
  ```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/CloudSyncBusyOverlay.test.tsx src/contexts/CloudSyncBusyContext.test.tsx`. Expected: all passed (the two original overlay tests + the two new escape-hatch tests + the context timeout/cancel tests). Then `cd frontend && npx tsc --noEmit` (expected exit 0 — the `useCloudSyncBusy` consumers in `App.tsx`/`CloudSyncSection.tsx` don't read the new fields so they stay valid).

- [ ] **Step 5: Run the broader suite** — `cd frontend && npx vitest run`. Expected: all green. Note: `src/components/CloudSyncSection.test.tsx` mocks the context with `{ busy, run }` only — it never reads `tookTooLong`/`cancel`, so it is unaffected.

- [ ] **Step 6: Commit** — `git add frontend/src/contexts/CloudSyncBusyContext.tsx frontend/src/components/CloudSyncBusyOverlay.tsx frontend/src/components/CloudSyncBusyOverlay.test.tsx frontend/src/contexts/CloudSyncBusyContext.test.tsx frontend/src/i18n/strings.ts` then:

  `git commit -m "feat(cloud-sync): add a 10s 'taking longer' hint + Cancel escape hatch to the busy overlay"`


---

<!-- ===== Batch-final gate + manual smoke ===== -->

### Task 23: SH1 acceptance — full automated gate + manual smoke

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-22
- Produces: none

- [ ] **Step 1: Full backend suite + no-regression collection check**

```bash
cd /Users/raviwu/personal/locwarp/backend
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest --collect-only -q | tail -1
```
Expected: all green. Collection has grown from the **914** baseline by the number of tests Tasks 1-22 added; **no pre-existing test was removed or skipped** (the count only increases).

- [ ] **Step 2: Backend layering gate**

```bash
cd /Users/raviwu/personal/locwarp/backend && lint-imports
```
Expected: `Contracts: 7 kept, 0 broken.`

- [ ] **Step 3: Frontend type + test + dependency gates**

```bash
cd /Users/raviwu/personal/locwarp/frontend
npx tsc --noEmit
npx vitest run
npx depcruise src
```
Expected: tsc 0 errors; vitest all green; depcruise 0 errors. (The new `WsEventType` makes any drift-introducing `subscribe('typo')` a tsc error.)

- [ ] **Step 4: Manual smoke — import resurrection (A13)**

In the running app (`cd frontend && npm run start`): export bookmarks -> delete one bookmark -> re-import the exported file.
- Expected: **the deleted bookmark reappears.** (Before SH1 it silently stayed deleted — empty `updated_at` lost to the tombstone.)

- [ ] **Step 5: Manual smoke — route import idempotency (A18)**

Import a route file, then import the **same** file again.
- Expected: route count is unchanged on the second import; **no `(匯入)`-suffixed duplicates.**

- [ ] **Step 6: Manual smoke — offline geo resilience (A11)**

With geo data present, open a bookmark and confirm it shows a country flag + timezone.
- Expected: geo fields populate. If they ever blank from a transient failure, the next lookup recovers them **without an app restart** (the lifetime latch is gone).

- [ ] **Step 7: Manual smoke — CloudSync escape hatch (U25)**

Enable cloud sync pointed at a slow/unreachable folder (or throttle the backend).
- Expected: after ~10s the busy overlay shows a **"taking longer…" message + a Cancel button**; clicking Cancel releases the UI. (Before: permanent zIndex-9999 lock.)

- [ ] **Step 8: Manual smoke — WS contract honesty (X6-X9)** *(requires a real iPhone)*

Open the devtools console. Connect, disconnect, then reconnect the iPhone. Force a USB-fallback failure (e.g. yank the cable during connect) to trigger `device_error`.
- Expected: **no 404** for `/api/device/wifi/connect`; **no unhandled-rejection spam**; the `device_error` surfaces as a visible banner/toast (not silently dropped).

- [ ] **Step 9: Manual smoke — dual-device targeting (A14/A21)** *(requires two iPhones)*

Connect two iPhones. Teleport device **B**.
- Expected: **B moves, A does not.** Disconnect one device -> **only that device drops**; the other keeps simulating.

- [ ] **Step 10: Capture evidence (optional)**

Capture screenshots / console logs from Steps 4-9 as the batch's user-acceptance evidence. No code commit; SH1 is complete when Steps 1-9 pass.

**SH1 acceptance:** automated gate green (Steps 1-3) with all new characterization tests; manual smoke Steps 4-9 observed and evidenced.
