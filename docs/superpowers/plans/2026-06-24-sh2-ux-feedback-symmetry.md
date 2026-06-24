# SH2 — UX Feedback Symmetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every core user action that can fail or take effect SILENTLY give visible, perceivable feedback — toast / spinner / window.confirm / banner / disabled-state — reusing infrastructure that already exists, with zero new dependencies.

**Architecture:** 20 bite-sized vitest/RTL TDD tasks across 3 clusters: D1 device-connection feedback (U1-U5), D2 simulation interaction (U6-U12), D3 bookmark/route CRUD feedback (U13-U18, U26). Each fix mirrors an existing correct sibling (the dual-device toast path, the bulk-delete confirm, the AddBookmarkDialog inline error). No backend change.

**Tech Stack:** React 18 + TypeScript + vitest + @testing-library/react.

## Global Constraints

- **Baseline (on `main` after SH1, `e1d56bb`):** `cd frontend && npx vitest run` => **664 passed / 87 files**; `npx tsc --noEmit` => 0 errors. Each task adds tests; the count only grows.
- **Full green after every commit.** After EACH commit, `npx tsc --noEmit` = 0 errors AND `npx vitest run` fully green. Never commit a red tsc or failing vitest.
- **Behavior CHANGE is the point** — adding feedback. Every change is covered by a vitest/RTL test in the same commit.
- **Mirror the correct sibling, don't invent.** The dual-device teleport path already toasts (single-device should match); bulk/category delete already `window.confirm` (single-delete should match); AddBookmarkDialog already shows an inline out-of-range error (Custom/Edit should match).
- **Preserve aria/role semantics**; introduce NO new dependency.
- **i18n:** every new user-facing string gets BOTH `zh` and `en` entries in `frontend/src/i18n/strings.ts`. App tests set `localStorage.locwarp.lang='en'`, so assert against the English string.
- **Line numbers in tasks are audit/draft-time anchors** — SH1 already edited App.tsx / useSimulation.ts / useDevice.ts; locate code by content, not line number.
- **Ordering within D3:** the U14 "category mutation" task creates `App.categoryMutation.test.tsx`; the U26 task extends that same file — U14-category MUST land before U26.
- **Personal repo:** direct commits; identity auto-set by `~/.gitconfig` — never pass `-c user.email=...`.

---


<!-- ===== D1 · UX — device connection feedback ===== -->


<!-- ===== D1 · UX — device connection feedback ===== -->

### Task 1: Toast dropdown device-connect failures (App onSelect)

**Files:**
- Modify: `frontend/src/App.tsx` (the `<DeviceStatus ... onSelect={(id: string) => { device.connect(id) }} />` handler — locate by the string `onSelect={(id: string) => { device.connect(id) }}`)
- Test: `frontend/src/App.deviceConnectFeedback.test.tsx` (new)

**Interfaces:**
- Consumes: none
- Produces: none (reuses existing `showToast` + i18n key `device.connect_failed`)

**Context (real code today):** In `App.tsx` the device dropdown is wired fire-and-forget:
```tsx
onSelect={(id: string) => { device.connect(id) }}
```
`useDevice.connect()` (`frontend/src/hooks/useDevice.ts`) does `console.error('Failed to connect device:', err)` then `throw err`. Because `onSelect` ignores the returned promise, the throw becomes an unhandled rejection — the dropdown closes (`DeviceStatus` sets `setShowDropdown(false)` right after calling `onSelect`) and the user sees nothing. The CORRECT sibling pattern is the chip-row `onRestoreOne` in the same file, which already toasts both ways:
```tsx
onRestoreOne={async (udid) => {
  try {
    await api.restoreSim(udid)
    setToastMsg(t('status.restore_success'))
  } catch (e: any) {
    setToastMsg(e?.message ?? 'restore failed')
  }
}}
```
Note it surfaces `e?.message` when present and only falls back to a literal. We mirror that: surface the rejection's `message`, falling back to the existing i18n key `device.connect_failed` (`{ zh: '連線失敗', en: 'Connection failed' }`, already in `frontend/src/i18n/strings.ts`). No new key needed.

- [ ] **Step 1: Write the failing test** — create `frontend/src/App.deviceConnectFeedback.test.tsx`. Reuse the App.smoke harness verbatim (MapView stub + services/api importOriginal mock + real WsRouter injected via ServicesProvider), then `vi.spyOn` `connectDevice` to reject so the dropdown row click hits the catch. Full file:
```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    return null
  }),
}))

vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'listDevices', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
    } else if (arrayReturning.has(key)) {
      out[key] = async () => []
    } else if (nullReturning.has(key)) {
      out[key] = async () => null
    } else if (urlReturning.has(key)) {
      out[key] = () => ''
    } else {
      out[key] = async () => undefined
    }
  }
  return out
})

import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { createWsRouter, type WsRouterImpl } from './adapters/ws/router'
import * as api from './services/api'

const DEV = (udid: string, connected: boolean) => ({
  udid, name: udid, ios_version: '17.0', connection_type: 'USB', is_connected: connected,
})

function renderApp(router: WsRouterImpl, connected = true) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

beforeEach(() => { try { localStorage.setItem('locwarp.lang', 'en') } catch {} })
afterEach(() => { vi.restoreAllMocks(); try { localStorage.clear() } catch {} })

describe('App device-connect feedback (U1)', () => {
  it('shows a toast when a dropdown device-connect fails', async () => {
    // Two devices so the dropdown renders without auto-connecting (scan auto-
    // connects only when exactly one device is present).
    vi.spyOn(api, 'listDevices').mockResolvedValue([DEV('A', false), DEV('B', false)] as any)
    vi.spyOn(api, 'connectDevice').mockRejectedValue(new Error('connect boom'))

    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Open the device dropdown (summary button shows the count) and pick a row.
    await waitFor(() => expect(screen.getByText('2 devices found')).toBeInTheDocument())
    fireEvent.click(screen.getByText('2 devices found'))
    fireEvent.click(screen.getByText('A'))

    // The connect rejects -> onSelect must surface a toast. Mirroring the
    // onRestoreOne sibling, the handler surfaces the rejection's message
    // ("connect boom") and only falls back to the device.connect_failed key
    // when the error has none. Assert the surfaced message.
    await waitFor(() => expect(screen.getByText('connect boom')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/App.deviceConnectFeedback.test.tsx -t "shows a toast when a dropdown device-connect fails"`. Expected failure: `Unable to find an element with the text: connect boom` (the current fire-and-forget `onSelect` swallows the rejection; no toast renders). The console will also show an unhandled-rejection-style `Failed to connect device:` log.

- [ ] **Step 3: Implement** — in `frontend/src/App.tsx`, replace the fire-and-forget handler. Current:
```tsx
          onSelect={(id: string) => { device.connect(id) }}
```
New (mirror the `onRestoreOne` try/catch + message-first toast pattern; `showToast` and `t` are already in scope from `useToast()` / `useT()` above):
```tsx
          onSelect={async (id: string) => {
            try {
              await device.connect(id)
            } catch (e: any) {
              showToast(e?.message ?? t('device.connect_failed'))
            }
          }}
```
`DeviceStatusProps.onSelect` is typed `(id: string) => void`, which accepts an `async` (Promise-returning) handler, so no prop-type change is needed.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/App.deviceConnectFeedback.test.tsx -t "shows a toast when a dropdown device-connect fails"`. Expected: 1 passed.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green; baseline 664 passed + this new test).

- [ ] **Step 6: Commit** — `git add frontend/src/App.tsx frontend/src/App.deviceConnectFeedback.test.tsx` then `git commit -m "fix(ux): toast when a dropdown device-connect fails (U1)"`.


---

### Task 2: Toast WiFi auto-connect failures + fix the wrong comment (useWifiAutoConnect)

**Files:**
- Modify: `frontend/src/hooks/useWifiAutoConnect.ts` (the hook signature, the silent `catch` block + per-IP `.catch(() => {})`, and the two stale "panel will surface them" comments)
- Modify: `frontend/src/App.tsx` (the `useWifiAutoConnect(connected, api, device)` call site — locate by that exact string)
- Modify: `frontend/src/i18n/strings.ts` (add one key)
- Test: `frontend/src/hooks/useWifiAutoConnect.test.tsx` (extend existing file)

**Interfaces:**
- Consumes: none
- Produces: a new 4th param `onError?: (msg: string) => void` on `useWifiAutoConnect`; a new i18n key `wifi.autoconnect_failed`

**Context (real code today):** `useWifiAutoConnect` (`frontend/src/hooks/useWifiAutoConnect.ts`) is fully silent on the auto pass. Its header comment claims `Failures are silent (the WiFi panel will surface them when the user opens it).` and the inner catch says `// Silent — tunnel section will show its own error when opened.` — but `DeviceStatus.tsx`'s `tunnelError` state is only ever set on the MANUAL connect button / discover / port-scan paths, never the auto pass, so the claim is false. The fan-out today is:
```ts
          await Promise.allSettled(
            limited.map((entry) =>
              device.startWifiTunnel(entry.ip, entry.port, entry.udid).catch(() => {}),
            ),
          )
        } catch {
          // Silent — tunnel section will show its own error when opened.
        }
```
Each per-IP `.catch(() => {})` swallows. Add an injected `onError` callback (App passes a `showToast` wrapper) and a NEW key. The existing positive sibling is the WiFi-tunnel-recovered toast wired through `useSimulation`'s 3rd arg in App (`() => showToast(t('wifi.tunnel_recovered'))`), so an injected callback that emits a toast is the established pattern. NOTE the hook stays inside the hexagon-lite layer: it imports NO i18n; it emits the i18n KEY string and App resolves it via `t`.

- [ ] **Step 1: Write the failing test** — append two tests inside the existing `describe('useWifiAutoConnect', …)` block in `frontend/src/hooks/useWifiAutoConnect.test.tsx` (reuse its `makeApi` / `makeDevice` helpers + the fake-timer `advanceTimersByTimeAsync` style; `vi`, `renderHook`, `act`, `expect` are already imported at the top — do NOT re-import). The hook gains a 4th `onError` arg. Add:
```tsx
  it('calls onError when every auto-connect attempt fails', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const { device, startWifiTunnel } = makeDevice()
    // Force the only attempt to reject.
    startWifiTunnel.mockRejectedValue(new Error('tunnel down'))
    const onError = vi.fn()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(startWifiTunnel).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it('does NOT call onError when at least one attempt succeeds', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const { device } = makeDevice() // default startWifiTunnel resolves
    const onError = vi.fn()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(onError).not.toHaveBeenCalled()
  })
```
Note: the existing `makeDevice()` returns `startWifiTunnel` as a `vi.fn(async () => …)`; `startWifiTunnel.mockRejectedValue(...)` is valid on it. (`beforeEach` already sets `locwarp.tunnel.autoconnect = '1'`, so the pass runs.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/hooks/useWifiAutoConnect.test.tsx -t "calls onError when every auto-connect attempt fails"`. Expected failure: `expected "spy" to be called 1 times, but got 0 times` — the hook currently takes only 3 params (the 4th arg is ignored at runtime; vitest runs via esbuild with no type-check) and swallows all failures, so `onError` is never invoked.

- [ ] **Step 3: Implement** — three edits.

(3a) `frontend/src/i18n/strings.ts`, add right after the existing `wifi.tunnel_recovered` line (~line 260):
```ts
  'wifi.autoconnect_failed': { zh: 'WiFi 自動連線失敗,請開啟 WiFi 區塊手動連線', en: 'Wi-Fi auto-connect failed — open the Wi-Fi section to connect manually' },
```

(3b) `frontend/src/hooks/useWifiAutoConnect.ts`. Fix the header comment — change:
```ts
// via the backend's own watchdog. Failures are silent (the WiFi panel
// will surface them when the user opens it).
```
to:
```ts
// via the backend's own watchdog. On a full failure (every candidate
// rejected) the injected onError callback fires a toast — the WiFi panel
// does NOT surface auto-pass failures on its own (its tunnelError is only
// set by the manual connect / discover paths).
```
Add the param to the signature:
```ts
export function useWifiAutoConnect(
  connected: boolean,
  api: ApiGateway,
  device: WifiAutoConnectDevice,
  onError?: (msg: string) => void,
) {
```
Mirror it into a ref so the deferred closure reads the latest callback without widening the `[connected]` dep (matching the existing `connectedDevicesRef` pattern). Right after `connectedDevicesRef.current = device.connectedDevices` add:
```ts
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
```
Replace the fan-out + its silent catch. Current:
```ts
          await Promise.allSettled(
            limited.map((entry) =>
              device.startWifiTunnel(entry.ip, entry.port, entry.udid).catch(() => {}),
            ),
          )
        } catch {
          // Silent — tunnel section will show its own error when opened.
        }
```
New:
```ts
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
        } catch {
          // Pre-flight (wifiTunnelStatus/discover) threw — same surfacing.
          onErrorRef.current?.('wifi.autoconnect_failed')
        }
```
IMPORTANT: the hook stays inside the hexagon-lite layer (no i18n import); it emits the i18n KEY string and App resolves it via `t`.

(3c) `frontend/src/App.tsx`, the call site. Current:
```tsx
  useWifiAutoConnect(connected, api, device)
```
New:
```tsx
  useWifiAutoConnect(connected, api, device, useCallback((k: string) => showToast(t(k as any)), [showToast, t]))
```
`useCallback` is already imported in App (`import React, { useState, useCallback, … } from 'react'`). `showToast` and `t` are already in scope above this line. The `as any` cast is required because `t` expects a `StringKey`, not an arbitrary `string`.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/hooks/useWifiAutoConnect.test.tsx`. Expected: all tests in the file pass (the 5 originals + the 2 new). Confirm the original `fires once when connected becomes true and does NOT re-run on a second toggle` test is unaffected (onError defaults `undefined`, so the new `onErrorRef.current?.(…)` calls are no-ops there).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/hooks/useWifiAutoConnect.ts frontend/src/App.tsx frontend/src/i18n/strings.ts frontend/src/hooks/useWifiAutoConnect.test.tsx` then `git commit -m "fix(ux): toast on full WiFi auto-connect failure; fix stale silent comment (U2)"`.


---

### Task 3: Soften USB last-device-disconnect banner copy to acknowledge auto-recovery

**Files:**
- Modify: `frontend/src/hooks/useSimulation.ts` (the `device_disconnected` handler's `remaining === 0` branch — locate by the literal English string `Device disconnected (USB unplugged or tunnel died), please reconnect USB`)
- Modify: `frontend/src/i18n/strings.ts` (add one key)
- Test: `frontend/src/App.smoke.test.tsx` (update the existing `surfaces the disconnect banner` test)

**Interfaces:**
- Consumes: none
- Produces: a new i18n key `device.disconnected_recovering`

**Context (real code today):** In `useSimulation.ts`, the WiFi path has a graceful amber-then-red ladder (`tunnel_degraded` -> reconnecting; `tunnel_recovered` -> clear; `tunnel_lost` -> red). USB has NO amber step: `device_disconnected` with `remaining === 0` jumps straight to the red terminal banner via hard-coded localized literals:
```ts
      if (remaining === 0) {
        const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
        setError(isEn
          ? 'Device disconnected (USB unplugged or tunnel died), please reconnect USB'
          : '裝置連線中斷(USB 拔除或 Tunnel 死亡),請重新插上 USB')
        setStatus((prev) => ({ ...prev, running: false, paused: false }))
      } else {
```
The watchdog may auto-reconnect within ~27s (it broadcasts `device_connected`, whose handler already does `setError(null)`). A full amber state machine for USB is a larger change with no `tunnel_degraded`-equivalent USB event to drive it; the finding's stated minimum is to SOFTEN the copy so the banner reads as "reconnecting / will retry" rather than a dead-end terminal red. This task does the minimum: replace the hard-coded literals with copy that says auto-reconnect is being attempted. Behavior (which state is set, when it clears) is unchanged; only the user-visible string changes, so the App.smoke `surfaces the disconnect banner` test's asserted text must be updated in lockstep.

- [ ] **Step 1: Update the test to assert the new copy** — in `frontend/src/App.smoke.test.tsx`, the existing test `surfaces the disconnect banner when the last device drops (remaining_count 0)` currently asserts the OLD literal at line ~141. Replace its assertion:
```tsx
    expect(
      screen.getByText('Device disconnected (USB unplugged or tunnel died), please reconnect USB'),
    ).toBeInTheDocument()
```
with the softened copy (English is pinned via `localStorage` in the file's `beforeEach`):
```tsx
    // Softened copy: acknowledges the watchdog auto-reconnect window instead
    // of reading as a dead-end terminal failure (U3).
    expect(
      screen.getByText('Device disconnected — trying to reconnect; replug USB if it does not come back'),
    ).toBeInTheDocument()
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/App.smoke.test.tsx -t "surfaces the disconnect banner when the last device drops"`. Expected failure: `Unable to find an element with the text: Device disconnected — trying to reconnect…` because the handler still emits the old `…please reconnect USB` literal.

- [ ] **Step 3: Implement** — two edits.

(3a) `frontend/src/i18n/strings.ts`, add right after the existing `wifi.tunnel_lost_banner_named` line (~line 721, in the "Device status extra" block):
```ts
  'device.disconnected_recovering': { zh: '裝置連線中斷 — 嘗試自動重連中,若未恢復請重新插上 USB', en: 'Device disconnected — trying to reconnect; replug USB if it does not come back' },
```

(3b) `frontend/src/hooks/useSimulation.ts`, replace the `remaining === 0` branch literals. Current:
```ts
      if (remaining === 0) {
        const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
        setError(isEn
          ? 'Device disconnected (USB unplugged or tunnel died), please reconnect USB'
          : '裝置連線中斷(USB 拔除或 Tunnel 死亡),請重新插上 USB')
        setStatus((prev) => ({ ...prev, running: false, paused: false }))
      } else {
```
New (keep the same localStorage-lang trick the file already uses, since this hook has no i18n context):
```ts
      if (remaining === 0) {
        const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
        // Softened from a dead-end terminal message: the watchdog may
        // auto-reconnect within ~27s (it broadcasts device_connected, which
        // clears this banner). Copy now reads as "reconnecting" with replug as
        // the fallback, mirroring the WiFi degraded->reconnecting tone.
        setError(isEn
          ? 'Device disconnected — trying to reconnect; replug USB if it does not come back'
          : '裝置連線中斷 — 嘗試自動重連中,若未恢復請重新插上 USB')
        setStatus((prev) => ({ ...prev, running: false, paused: false }))
      } else {
```
(The literals here are kept in-hook to match the file's existing localStorage-lang pattern; the new `device.disconnected_recovering` key is added to `strings.ts` so the same copy is available to any i18n-context consumer and so future work can switch the hook to a passed-in resolver. The in-hook literals and the strings.ts key MUST stay byte-identical.)

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/App.smoke.test.tsx -t "surfaces the disconnect banner when the last device drops"`. Expected: 1 passed.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green). NOTE: a grep confirms the OLD literal `please reconnect USB` is pinned ONLY by this one App.smoke test (`grep -rn "please reconnect USB" frontend/src` — the only other hit, `services/api.ts` `device_lost`, is a DIFFERENT string "…please reconnect USB and try again" on an unrelated code path and is NOT changed by this task). No other test updates needed.

- [ ] **Step 6: Commit** — `git add frontend/src/hooks/useSimulation.ts frontend/src/i18n/strings.ts frontend/src/App.smoke.test.tsx` then `git commit -m "fix(ux): soften USB last-device-disconnect banner to acknowledge auto-recovery (U3)"`.


---

### Task 4: Show a trust_required chip in the always-visible DeviceChipRow

**Files:**
- Modify: `frontend/src/components/DeviceChipRow.tsx` (accept + render a `trustRequired` device list)
- Modify: `frontend/src/components/DeviceChip.tsx` (render a trust badge + a re-trust menu item when the device is `trust_required`)
- Modify: `frontend/src/App.tsx` (pass the `trustRequired` slice + an `onReTrust` handler into `<DeviceChipRow>`)
- Modify: `frontend/src/i18n/strings.ts` (add one menu-item key; reuse existing `device.pair_chip_trust`)
- Test: `frontend/src/components/DeviceChipRow.test.tsx` (extend) and `frontend/src/components/DeviceChip.test.tsx` (extend)

**Interfaces:**
- Consumes: none
- Produces: new `DeviceChipRow` props `trustRequired?: DeviceInfo[]` + `onReTrust?: (udid: string) => void`; new `DeviceChip` props `variant?: 'connected' | 'trust_required'` + `onReTrust?: () => void`; new i18n key `device.chip_retrust`

**Context (real code today):** The always-visible chip row (`DeviceChipRow`) is fed ONLY `device.connectedDevices` from App (`devices={device.connectedDevices}`). A `trust_required` device is NOT connected (`is_connected === false`), so it never appears in that row — it only shows up inside the collapsed-by-default `DeviceStatus` dropdown, which sorts pair-failed devices to the bottom and renders a `device.pair_chip_trust` badge + a `device.pair_repair_button` ("Re-trust") button. The chip already supports per-state dot colors (`error`/`disconnected` -> `#ff6b6b`) via `stateKind()`. This task adds a visible trust_required chip variant to the row so the user sees the device without expanding anything. The `DeviceInfo.pair_status` field (`'ok' | 'trust_required' | 'error'`) already exists in `frontend/src/hooks/useDevice.ts`.

- [ ] **Step 1: Write the failing tests** — extend both files. They already import `{ describe, it, expect, vi, beforeEach }` from vitest and `{ render, screen, fireEvent, cleanup }` from testing-library at the top, and each mocks i18n as `useT: () => (key) => key` — do NOT re-import or re-mock.

In `frontend/src/components/DeviceChipRow.test.tsx`, the existing `makeDevice(udid, name)` helper takes TWO positional args and returns a connected `DeviceInfo` with no `pair_status`. Add a trust-device helper + a new describe block (note: `baseProps`/`emptyRuntimes`/`DeviceInfo` are already in scope from the top of the file):
```tsx
describe('DeviceChipRow trust_required chips', () => {
  function trustDevice(udid: string, name: string): DeviceInfo {
    return { udid, name, ios_version: '17.0', connection_type: 'usb', is_connected: false, pair_status: 'trust_required' }
  }

  it('renders a trust_required chip alongside connected chips', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'Connected One')]}
        trustRequired={[trustDevice('t1', 'Needs Trust')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    expect(screen.getByTitle('A · Connected One')).toBeInTheDocument()
    // trust chip rendered with its name + the existing trust badge label key
    expect(screen.getByText('· Needs Trust')).toBeInTheDocument()
    expect(screen.getByText('device.pair_chip_trust')).toBeInTheDocument()
  })

  it('fires onReTrust with the udid from the trust chip menu', () => {
    const props = baseProps()
    const onReTrust = vi.fn()
    render(
      <DeviceChipRow
        devices={[]}
        trustRequired={[trustDevice('t1', 'Needs Trust')]}
        runtimes={emptyRuntimes}
        onReTrust={onReTrust}
        {...props}
      />,
    )
    // With no connected devices, the trust chip takes letter A.
    fireEvent.contextMenu(screen.getByTitle('A · Needs Trust'))
    fireEvent.click(screen.getByText('device.chip_retrust'))
    expect(onReTrust).toHaveBeenCalledWith('t1')
  })
})
```

In `frontend/src/components/DeviceChip.test.tsx`, the existing `makeDevice(over: Partial<DeviceInfo>)` helper takes an override object and `noop` is in scope. Add:
```tsx
describe('DeviceChip trust_required variant', () => {
  it('renders the trust badge and a re-trust menu item', () => {
    const onReTrust = vi.fn()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice({ name: 'Needs Trust', is_connected: false, pair_status: 'trust_required' })}
        variant="trust_required"
        onReTrust={onReTrust}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('device.pair_chip_trust')).toBeInTheDocument()
    fireEvent.contextMenu(screen.getByTitle('A · Needs Trust'))
    fireEvent.click(screen.getByText('device.chip_retrust'))
    expect(onReTrust).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run tests, verify they fail** — `cd frontend && npx vitest run src/components/DeviceChipRow.test.tsx src/components/DeviceChip.test.tsx -t "trust"`. Expected failure: `device.chip_retrust` / `device.pair_chip_trust` / `· Needs Trust` not found (the row drops trust devices today and the chip has no trust variant / re-trust item).

- [ ] **Step 3: Implement** — four edits.

(3a) `frontend/src/i18n/strings.ts`, add next to the existing `device.chip_*` keys (e.g. right after `device.chip_enable_dev` at ~line 139):
```ts
  'device.chip_retrust': { zh: '重新信任此裝置', en: 'Re-trust this device' },
```

(3b) `frontend/src/components/DeviceChip.tsx`. Add the two props to the `Props` interface (keep the existing fields and order; just add `variant` and `onReTrust`):
```ts
interface Props {
  letter: DeviceLetter
  device: DeviceInfo
  runtime?: DeviceRuntime
  variant?: 'connected' | 'trust_required'
  onDisconnect: () => void
  onForget: () => void
  onRestoreOne: () => void
  onReTrust?: () => void
  onEnableDev?: () => void
}
```
Destructure `variant = 'connected'` and `onReTrust` in the function signature:
```tsx
export function DeviceChip({ letter, device, runtime, variant = 'connected', onDisconnect, onForget, onRestoreOne, onReTrust, onEnableDev }: Props) {
```
Right after the existing `const accent = DEVICE_COLORS[letter]` line (and before `const shortName = …`) add:
```tsx
  const isTrust = variant === 'trust_required'
  const trustDot = '#ffb627'
```
In the dot `<span>`, change `background: dotColor,` to:
```tsx
            background: isTrust ? trustDot : dotColor,
```
Replace the state-label span (`<span style={{ opacity: 0.6, marginLeft: 2 }}>· {label}</span>`) so a trust chip shows the existing trust badge text instead of a runtime state:
```tsx
        <span style={{ opacity: 0.6, marginLeft: 2 }}>· {isTrust ? t('device.pair_chip_trust') : label}</span>
```
In the context menu (the `menu && createPortal(...)` block), replace the current four `<MenuItem>` lines (`chip_restore`, conditional `chip_enable_dev`, `chip_disconnect`, `chip_forget`) with a trust-aware version. For a trust chip, show only re-trust + forget; for a connected chip, the original restore/enable-dev/disconnect set plus forget:
```tsx
          {isTrust ? (
            <MenuItem onClick={() => { setMenu(null); onReTrust?.() }}>{t('device.chip_retrust')}</MenuItem>
          ) : (
            <>
              <MenuItem onClick={() => { setMenu(null); onRestoreOne() }}>{t('device.chip_restore')}</MenuItem>
              {onEnableDev && <MenuItem onClick={() => { setMenu(null); onEnableDev() }}>{t('device.chip_enable_dev')}</MenuItem>}
              <MenuItem onClick={() => { setMenu(null); onDisconnect() }}>{t('device.chip_disconnect')}</MenuItem>
            </>
          )}
          <MenuItem onClick={() => { setMenu(null); setConfirmForget(true) }}>{t('device.chip_forget')}</MenuItem>
```
(The forget item stays available in both variants; the existing forget-confirm modal is untouched.)

(3c) `frontend/src/components/DeviceChipRow.tsx`. Add the two props to `Props`:
```ts
interface Props {
  devices: DeviceInfo[]           // connected devices in order (max 3)
  trustRequired?: DeviceInfo[]
  runtimes: RuntimesMap
  onAdd: () => void               // opens add-device picker
  onDisconnect: (udid: string) => void
  onForget: (udid: string) => void
  onRestoreOne: (udid: string) => void
  onReTrust?: (udid: string) => void
  onEnableDev?: (udid: string) => void
}
```
Destructure `trustRequired = []` and `onReTrust` in the function signature:
```tsx
export function DeviceChipRow({ devices, trustRequired = [], runtimes, onAdd, onDisconnect, onForget, onRestoreOne, onReTrust, onEnableDev }: Props) {
```
Render the trust chips right after the connected-devices `.map(...)` block, before the `{!atMax && (...)}` add button. Trust chips continue the letter sequence so colors stay distinct (and the index is clamped to the max so the `LETTERS` lookup never returns undefined):
```tsx
      {trustRequired.slice(0, MAX_DEVICES).map((d, i) => {
        const letter = LETTERS[Math.min(devices.length + i, MAX_DEVICES - 1)]
        return (
          <DeviceChip
            key={d.udid}
            letter={letter}
            device={d}
            variant="trust_required"
            onReTrust={() => onReTrust?.(d.udid)}
            onDisconnect={() => onDisconnect(d.udid)}
            onForget={() => onForget(d.udid)}
            onRestoreOne={() => onRestoreOne(d.udid)}
          />
        )
      })}
```

(3d) `frontend/src/App.tsx`, the `<DeviceChipRow>` usage. It currently passes `devices={device.connectedDevices}`. Add the trust slice (derived from `device.devices`, which carries `pair_status`) and the re-trust handler right after the `devices={device.connectedDevices}` line. `api.wifiRepair` IS available on the injected gateway (`ApiGateway = typeof api`, i.e. the whole `services/api` module; `wifiRepair`, `restoreSim`, `forgetDevice` are all exported there and already used elsewhere in App via `api.`). `wifiRepair`'s signature is `(udid?: string | null) => …`, so passing a `udid` string is valid. The success/failure keys `wifi.repair_success` / `wifi.repair_failed` already exist:
```tsx
          trustRequired={device.devices.filter((d) => d.pair_status === 'trust_required' && !d.is_connected)}
          onReTrust={async (udid) => {
            try {
              await api.wifiRepair(udid)
              setToastMsg(t('wifi.repair_success'))
              await device.scan()
            } catch (e: any) {
              setToastMsg(e?.message ?? t('wifi.repair_failed'))
            }
          }}
```

- [ ] **Step 4: Run tests, verify they pass** — `cd frontend && npx vitest run src/components/DeviceChipRow.test.tsx src/components/DeviceChip.test.tsx`. Expected: all green (existing connected-chip tests unaffected because `variant` defaults to `'connected'` and `trustRequired` defaults to `[]`).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/DeviceChipRow.tsx frontend/src/components/DeviceChip.tsx frontend/src/App.tsx frontend/src/i18n/strings.ts frontend/src/components/DeviceChipRow.test.tsx frontend/src/components/DeviceChip.test.tsx` then `git commit -m "feat(ux): surface trust_required devices as a chip in the always-visible row (U5)"`.


---

### Task 5: Auto-expand the device dropdown when a trust_required device exists

**Files:**
- Modify: `frontend/src/components/DeviceStatus.tsx` (auto-open `showDropdown` when any device is `trust_required`)
- Test: `frontend/src/components/DeviceStatus.test.tsx` (extend)

**Interfaces:**
- Consumes: the `device.pair_status` field already threaded into `DeviceStatus.devices` from App (`pair_status: d.pair_status`)
- Produces: none

**Context (real code today):** After a Forget, App's `DeviceChipRow.onForget` calls `device.disconnect(udid)` -> `listDevices()` repopulates the device with `pair_status: 'trust_required'` and `is_connected:false`. The always-visible chip row renders only `connectedDevices`, so the device VANISHES from the always-visible UI; the only place the Re-trust button lives is inside `DeviceStatus`'s dropdown, which is collapsed by default (`const [showDropdown, setShowDropdown] = useState(false)`). The user has no signal to expand it. (U5, a sibling task, adds a visible trust chip; this task complements it by also auto-opening the dropdown that hosts the full Re-trust modal, so the next step is discoverable even if the user looks at the device panel.) The finding explicitly says NOT to surface a "re-scan" affordance, because `device.scan()` auto-connects when exactly one device remains — auto-expanding the existing dropdown sidesteps that. The component's own `Device` interface already has `pair_status?: 'ok' | 'trust_required' | 'error'` (line ~15).

- [ ] **Step 1: Write the failing test** — extend `frontend/src/components/DeviceStatus.test.tsx`. The file already imports `React`, `{ describe, it, expect, vi, beforeEach }` and `{ render, screen, fireEvent, waitFor }`, mocks `../i18n` (`useT: () => (key) => key`) and `../services/api`, and defines `makeDevice` + `baseProps`. The local test `Device` interface only has `{ id, udid, name, iosVersion, connectionType }`, so pass `pair_status` via `as any` (or extend the interface). The existing `opens the device dropdown …` test proves rows are absent until the summary is clicked; a `trust_required` device must make the rows appear WITHOUT a click. Add (inside the existing `describe('DeviceStatus', …)` block):
```tsx
  it('auto-expands the dropdown when a device needs re-trust', () => {
    const trust = makeDevice({ id: 't', udid: 'ut', name: 'Needs Trust', pair_status: 'trust_required' } as any)
    render(<DeviceStatus {...baseProps} devices={[trust]} />)
    // No user click: the dropdown is auto-opened, so the device row + the
    // existing trust badge (device.pair_chip_trust) render immediately.
    expect(screen.getByText('Needs Trust')).toBeInTheDocument()
    expect(screen.getByText('device.pair_chip_trust')).toBeInTheDocument()
  })

  it('does NOT auto-expand when all devices are healthy', () => {
    const ok = makeDevice({ id: 'a', udid: 'ua', name: 'Healthy' })
    render(<DeviceStatus {...baseProps} devices={[ok]} />)
    // Collapsed by default: the row is not rendered until the summary is clicked.
    expect(screen.queryByText('Healthy')).not.toBeInTheDocument()
    expect(screen.getByText('1 devices found')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/DeviceStatus.test.tsx -t "auto-expands the dropdown when a device needs re-trust"`. Expected failure: `Unable to find an element with the text: Needs Trust` — `showDropdown` starts `false` and nothing opens it.

- [ ] **Step 3: Implement** — in `frontend/src/components/DeviceStatus.tsx`, add a one-shot auto-open effect. After the existing `const [showDropdown, setShowDropdown] = useState(false);` and the `devicesRef`/`scanResultTimer` setup, add an effect that opens the dropdown the first time a trust_required device shows up (a ref latch keeps it from fighting a user who manually re-collapses):
```tsx
  // Auto-expand the device dropdown the first time a device reports
  // trust_required, so the Re-trust button (the real next step after a
  // Forget) is reachable without the user hunting through a collapsed
  // panel. One-shot via a ref latch: once we've auto-opened for a given
  // trust event we don't re-open if the user manually collapses it; the
  // latch resets when the trust condition clears so a FUTURE re-trust
  // event re-triggers the auto-expand.
  const autoExpandedForTrustRef = React.useRef(false);
  React.useEffect(() => {
    const hasTrust = devices.some((d) => d.pair_status === 'trust_required');
    if (hasTrust && !autoExpandedForTrustRef.current) {
      autoExpandedForTrustRef.current = true;
      setShowDropdown(true);
    } else if (!hasTrust) {
      autoExpandedForTrustRef.current = false;
    }
  }, [devices]);
```
(`React` is the default import in this file: `import React, { useState } from 'react';` — `React.useRef` / `React.useEffect` match the existing `React.useRef`/`React.useEffect` usage already in the component for `scanResultTimer`.)

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/DeviceStatus.test.tsx`. Expected: all green, including the existing `opens the device dropdown and lists every device on toggle` test (its devices have no `pair_status`, so the latch never fires and the dropdown stays collapsed until the manual click).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/DeviceStatus.tsx frontend/src/components/DeviceStatus.test.tsx` then `git commit -m "feat(ux): auto-expand device dropdown when a device needs re-trust (U4)"`.


---


<!-- ===== D2 · UX — simulation interaction feedback ===== -->

### Task 6: Hide the Map Transport Start in Teleport mode + add a no-position guard to the Joystick start branch

**Context (real code read):** `sim.mode` defaults to `SimMode.Teleport` (`useSimulation.ts`: `const [mode, _setMode] = useState<SimMode>(SimMode.Teleport)`). Teleport never sets `status.running = true`, so `MapView`'s `TransportButtons` renders the green Start button on app open (`if (!isRunning) … lw-transport-start`). But `useSimActions.handleStart()` has NO Teleport branch — its `if (sim.mode === SimMode.Joystick) … else if (RandomWalk) … else if (Loop || MultiStop)` chain means Teleport falls through and does nothing (verified: `handleStart` in `useSimActions.ts`, lines 177–200). So the centered Start is a dead no-op. Separately, the `RandomWalk` branch guards `if (!sim.currentPosition) { showToast(t('toast.no_position_random')); return }`, but the `Joystick` branch does NOT — pressing Start in Joystick with no fix silently calls `sim.joystickStart()` against an unknown position.

Two-part fix: (a) thread `sim.mode` into `MapView` → `TransportButtons` and suppress the Start button when the mode is Teleport (Start is meaningless there — teleport is action-driven via right-click / coord strip); (b) add the same no-position guard + `toast.no_position_random` to the Joystick single AND dual branch of `handleStart`.

**Files:**
- Modify: `frontend/src/hooks/useSimActions.ts` (the `handleStart` callback — locate by `if (sim.mode === SimMode.Joystick)`)
- Modify: `frontend/src/components/MapView.tsx` (the `TransportButtons` component + its `<TransportButtons …>` call site + `MapViewProps`)
- Modify: `frontend/src/App.tsx` (the `<MapView …` call site — locate by the `onMapClick={handleMapClick}` / `isRunning={isRunning}` props, NOT the `<ControlPanel simMode={sim.mode}` one which already exists)
- Test: `frontend/src/hooks/useSimActions.test.tsx` (guard half) and `frontend/src/components/MapView.test.tsx` (Start-hidden half — CREATE; confirmed absent)

**Interfaces:**
- Consumes: `SimMode` (exported as `export enum SimMode` from `frontend/src/hooks/useSimulation.ts` — a VALUE import, not type-only), existing `toast.no_position_random` string key (already present in `strings.ts`)
- Produces: `MapViewProps.simMode?: SimMode`; `TransportButtons` gains a `simMode: SimMode` prop

- [ ] **Step 1: Write the failing tests.**
  Guard half — append to `frontend/src/hooks/useSimActions.test.tsx` inside the existing `describe('useSimActions — start (mode gate + joystick branch)')` block (reuse the file's `makeSim` / `setup` helpers verbatim; `SimMode` is already imported there):
  ```tsx
  it('Joystick mode with no current position: toasts no_position_random and never starts', async () => {
    const sim = makeSim({ mode: SimMode.Joystick, currentPosition: null })
    const { result, showToast } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleStart() })
    expect(sim.joystickStart).not.toHaveBeenCalled()
    expect(sim.joystickStartAll).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('no position')
  })

  it('Joystick dual-device with no position: guard fires before joystickStartAll', async () => {
    const sim = makeSim({ mode: SimMode.Joystick, currentPosition: null })
    const { result, showToast } = setup({ udids: ['A', 'B'], sim })
    await act(async () => { await result.current.handleStart() })
    expect(sim.joystickStartAll).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('no position')
  })
  ```
  (The local `t` stub already maps `'toast.no_position_random' → 'no position'`.)

  Start-hidden half — CREATE `frontend/src/components/MapView.test.tsx`. MapView drags in Leaflet, so test `TransportButtons` directly by exporting it. First add `export` to the function in MapView (Step 3). `TransportButtons` takes `t` as a `React.MutableRefObject<(k)=>string>` (a REF, not a plain function), so the Harness must wrap it in `useRef`:
  ```tsx
  import { describe, it, expect, vi } from 'vitest';
  import { render } from '@testing-library/react';
  import { useRef } from 'react';
  import { TransportButtons } from './MapView';
  import { SimMode } from '../hooks/useSimulation';

  function Harness(props: any) {
    const t = useRef((k: string) => k);
    return <TransportButtons t={t} {...props} />;
  }

  describe('TransportButtons — Teleport-mode Start suppression', () => {
    it('hides the Start button when simMode is Teleport (dead no-op)', () => {
      render(<Harness simMode={SimMode.Teleport} isRunning={false} isPaused={false}
        onStart={vi.fn()} onStop={vi.fn()} onPause={vi.fn()} onResume={vi.fn()} />);
      expect(document.querySelector('.lw-transport-start')).toBeNull();
    });
    it('shows the Start button in a non-Teleport idle mode (e.g. Joystick)', () => {
      render(<Harness simMode={SimMode.Joystick} isRunning={false} isPaused={false}
        onStart={vi.fn()} onStop={vi.fn()} onPause={vi.fn()} onResume={vi.fn()} />);
      expect(document.querySelector('.lw-transport-start')).not.toBeNull();
    });
  });
  ```

- [ ] **Step 2: Run tests, verify they fail.**
  ```
  cd frontend && npx vitest run src/hooks/useSimActions.test.tsx -t "no_position"
  cd frontend && npx vitest run src/components/MapView.test.tsx -t "Start"
  ```
  Expected: guard tests fail because `sim.joystickStart` IS called (no guard) and `showToast` not called with 'no position'; `MapView.test.tsx` fails to import (`TransportButtons` is not exported) / the Teleport case fails because the Start button renders regardless of mode.

- [ ] **Step 3: Implement.**
  (a) In `useSimActions.ts`, the current Joystick branch is:
  ```ts
    if (sim.mode === SimMode.Joystick) {
      if (udids.length >= 2) {
        const outcome = await sim.joystickStartAll(udids)
        showToast(toastForFanout(t, t('mode.joystick'), outcome, device.connectedDevices))
      } else {
        sim.joystickStart()
      }
    } else if (sim.mode === SimMode.RandomWalk) {
  ```
  Add the guard at the top of the Joystick branch (mirroring RandomWalk):
  ```ts
    if (sim.mode === SimMode.Joystick) {
      if (!sim.currentPosition) {
        showToast(t('toast.no_position_random'))
        return
      }
      if (udids.length >= 2) {
        const outcome = await sim.joystickStartAll(udids)
        showToast(toastForFanout(t, t('mode.joystick'), outcome, device.connectedDevices))
      } else {
        sim.joystickStart()
      }
    } else if (sim.mode === SimMode.RandomWalk) {
  ```
  (b) In `MapView.tsx`, export `TransportButtons` and add the `simMode` prop + the Start-suppression gate. Change `function TransportButtons({` to `export function TransportButtons({`, add `simMode,` to the destructured params and `simMode: SimMode;` to its inline prop type. Add the value import `import { SimMode } from '../hooks/useSimulation';` next to the existing `import type { RuntimesMap } from '../hooks/useSimulation';` (line 45). Then gate the Start block:
  ```tsx
      {!isRunning && simMode !== SimMode.Teleport && (
        <button
          className="lw-transport-btn lw-transport-start"
          onClick={onStart}
          title={label('generic.start')}
        >
  ```
  Add `simMode?: SimMode;` to `MapViewProps`, destructure `simMode` in the `MapView` component params, and pass it through at the `<TransportButtons …>` call site (currently `isRunning={!!isRunning}` etc.): add `simMode={simMode ?? SimMode.Teleport}`.
  (c) In `App.tsx`, at the `<MapView …` call site (the one with `onMapClick={handleMapClick}` / `isRunning={isRunning}`) add `simMode={sim.mode}` (e.g. next to `isRunning={isRunning}`).

- [ ] **Step 4: Run tests, verify they pass.**
  ```
  cd frontend && npx vitest run src/hooks/useSimActions.test.tsx -t "no_position"
  cd frontend && npx vitest run src/components/MapView.test.tsx
  ```
  Expected: PASS.

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/hooks/useSimActions.ts frontend/src/components/MapView.tsx frontend/src/components/MapView.test.tsx frontend/src/hooks/useSimActions.test.tsx frontend/src/App.tsx
  git commit -m "feat(sim): hide dead Teleport-mode Start + guard Joystick start with no position"
  ```


---

### Task 7: Toast on single-device teleport/navigate failure (mirror the dual-device toast surface)

**Context (real code read):** In `useSimActions.handleTeleport` / `handleNavigate`, the dual branch awaits + toasts: `const outcome = await sim.teleportAll(udids, lat, lng); showToast(toastForFanout(…))`. The SINGLE branch is fire-and-forget: `sim.teleport(lat, lng)` (line 125) / `sim.navigate(lat, lng)` (line 143) with no `await` and no `try/catch`. Confirmed in `useSimulation.ts`: `teleport` (line 627) and `navigate` (line 653) both do `setError(err.message); throw err` on failure — so a single-device failure raises a banner but the rethrow is unobserved (no toast) and escapes as an unhandled rejection out of the un-awaited call. Add `await` + `try/catch` + a failure `showToast` to the single branch so the single-device path matches the dual-device feedback symmetry.

**Files:**
- Modify: `frontend/src/hooks/useSimActions.ts` (the `handleTeleport` + `handleNavigate` single `else` branches — locate by `sim.teleport(lat, lng)` and `sim.navigate(lat, lng)`)
- Modify: `frontend/src/i18n/strings.ts` (add `panel.teleport_failed` + `panel.navigate_failed` keys)
- Test: `frontend/src/hooks/useSimActions.test.tsx`

**Interfaces:**
- Consumes: existing `showToast` arg, `t` arg
- Produces: new string keys `panel.teleport_failed`, `panel.navigate_failed`

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/hooks/useSimActions.test.tsx` inside `describe('useSimActions — teleport')` (and a parallel one under `describe('useSimActions — navigate')`). The local `t` stub returns `map[k] ?? k`, and `panel.teleport_failed` / `panel.navigate_failed` are NOT in its map — so assert against the raw key. Make the single-device legacy method reject:
  ```tsx
  it('single device teleport failure: awaits, catches, toasts the failure', async () => {
    const sim = makeSim({ teleport: vi.fn(async () => { throw new Error('boom') }) })
    const { result, showToast } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    expect(sim.teleport).toHaveBeenCalledWith(10, 20)
    expect(showToast).toHaveBeenCalledWith('panel.teleport_failed')
  })
  ```
  And under `describe('useSimActions — navigate')`:
  ```tsx
  it('single device navigate failure: awaits, catches, toasts the failure', async () => {
    const sim = makeSim({ navigate: vi.fn(async () => { throw new Error('boom') }) })
    const { result, showToast } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleNavigate(10, 20) })
    expect(showToast).toHaveBeenCalledWith('panel.navigate_failed')
  })
  ```
  The existing single-device success tests stay green — they assert `expect(showToast).not.toHaveBeenCalled()`, and the toast now only fires in the `catch`, so the success path remains silent.

- [ ] **Step 2: Run test, verify it fails.**
  ```
  cd frontend && npx vitest run src/hooks/useSimActions.test.tsx -t "failure"
  ```
  Expected: fails — the single branch doesn't await/catch, so `handleTeleport` rejects out of `act` (or `showToast` is never called with the failure key).

- [ ] **Step 3: Implement.** In `handleTeleport`, change:
  ```ts
    } else {
      sim.teleport(lat, lng)
    }
  ```
  to:
  ```ts
    } else {
      try {
        await sim.teleport(lat, lng)
      } catch {
        showToast(t('panel.teleport_failed'))
      }
    }
  ```
  In `handleNavigate`, change:
  ```ts
    } else {
      sim.navigate(lat, lng)
    }
  ```
  to:
  ```ts
    } else {
      try {
        await sim.navigate(lat, lng)
      } catch {
        showToast(t('panel.navigate_failed'))
      }
    }
  ```
  In `frontend/src/i18n/strings.ts`, add near the other `panel.*` keys (e.g. after `'panel.apply_speed_failed'`, line 195):
  ```ts
  'panel.teleport_failed': { zh: '瞬移失敗', en: 'Teleport failed' },
  'panel.navigate_failed': { zh: '導航失敗', en: 'Navigate failed' },
  ```

- [ ] **Step 4: Run test, verify it passes.**
  ```
  cd frontend && npx vitest run src/hooks/useSimActions.test.tsx -t "failure"
  ```
  Expected: PASS.

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/hooks/useSimActions.ts frontend/src/i18n/strings.ts frontend/src/hooks/useSimActions.test.tsx
  git commit -m "feat(sim): toast single-device teleport/navigate failures (match dual-device path)"
  ```


---

### Task 8: Gate the Map Transport Start on deviceConnected (mirror the CoordInputStrip below it)

**Context (real code read):** `CoordInputStrip` (rendered in MapView's bottom-left stack, just below the transport row) receives `deviceConnected` and disables its teleport/navigate buttons when it is false. But `MapView`'s `TransportButtons` has no `deviceConnected` prop at all — its Start button is always clickable, even with no device, calling `onStart` into a no-op fan-out. `MapView` already RECEIVES `deviceConnected` (line 275, defaulted `true`, used for the context menu + passed to `CoordInputStrip`), so it's already in scope at the `<TransportButtons>` call site — just thread it through and disable Start when `!deviceConnected`.

**Files:**
- Modify: `frontend/src/components/MapView.tsx` (`TransportButtons` component + its inline prop type + the `<TransportButtons …>` call site)
- Test: `frontend/src/components/MapView.test.tsx` (the file created in the U6 task; if doing this task first, create it with the import + `Harness` boilerplate shown in U6 Step 1)

**Interfaces:**
- Consumes: `MapView`'s existing `deviceConnected` prop; `TransportButtons` from MapView (exported in the U6 task)
- Produces: `TransportButtons` gains a `deviceConnected: boolean` prop

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/components/MapView.test.tsx` (reuse the `Harness` helper from U6; pass a non-Teleport mode so Start renders):
  ```tsx
  describe('TransportButtons — deviceConnected gating', () => {
    it('disables Start when no device is connected', () => {
      render(<Harness simMode={SimMode.Joystick} deviceConnected={false}
        isRunning={false} isPaused={false}
        onStart={vi.fn()} onStop={vi.fn()} onPause={vi.fn()} onResume={vi.fn()} />);
      const start = document.querySelector('.lw-transport-start') as HTMLButtonElement;
      expect(start).not.toBeNull();
      expect(start.disabled).toBe(true);
    });
    it('enables Start when a device is connected', () => {
      render(<Harness simMode={SimMode.Joystick} deviceConnected={true}
        isRunning={false} isPaused={false}
        onStart={vi.fn()} onStop={vi.fn()} onPause={vi.fn()} onResume={vi.fn()} />);
      const start = document.querySelector('.lw-transport-start') as HTMLButtonElement;
      expect(start.disabled).toBe(false);
    });
  });
  ```
  (The U6 `Harness` spreads `{...props}`, so `deviceConnected` passes straight through.)

- [ ] **Step 2: Run test, verify it fails.**
  ```
  cd frontend && npx vitest run src/components/MapView.test.tsx -t "deviceConnected gating"
  ```
  Expected: fails — `TransportButtons` has no `deviceConnected` prop, so `start.disabled` is `false` in the no-device case.

- [ ] **Step 3: Implement.** In `MapView.tsx`, add `deviceConnected: boolean;` to the `TransportButtons` inline prop type and `deviceConnected,` to its destructured params. Change the Start button (already gated on `simMode !== SimMode.Teleport` from the U6 task — KEEP that condition):
  ```tsx
      {!isRunning && simMode !== SimMode.Teleport && (
        <button
          className="lw-transport-btn lw-transport-start"
          onClick={onStart}
          disabled={!deviceConnected}
          title={label('generic.start')}
        >
  ```
  At the `<TransportButtons …>` call site in `MapView`'s JSX, add `deviceConnected={deviceConnected}` (the prop is already destructured in `MapView`, defaulted `true`).

- [ ] **Step 4: Run test, verify it passes.**
  ```
  cd frontend && npx vitest run src/components/MapView.test.tsx -t "deviceConnected gating"
  ```
  Expected: PASS.

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/components/MapView.tsx frontend/src/components/MapView.test.tsx
  git commit -m "feat(sim): disable Map Transport Start when no device is connected"
  ```


---

### Task 9: Show a Paused state in the ETA bar (chip + dimmed progress)

**Context (real code read):** `sim.status.paused` exists (`SimulationStatus.paused: boolean`, set on pause/resume) and App already derives `const isPaused = sim.status.paused` (App.tsx line 836). But `EtaBar` (the prominent top-of-map bar, App.tsx line 1163) takes no `isPaused` prop — its props are `state, progress, remainingDistance, traveledDistance, eta, runtimes`. While paused, the progress bar + ETA still read as advancing with no indication the route is on hold. Add an `isPaused?: boolean` prop, wire it from App (`isPaused={isPaused}`, reusing the existing local), and when true: render a small "Paused" chip and dim the progress fill.

**Files:**
- Modify: `frontend/src/components/EtaBar.tsx` (`EtaBarProps` + the destructure + the progress-fill `<div>` + the header row)
- Modify: `frontend/src/App.tsx` (the `<EtaBar …>` call site at ~line 1163 — add `isPaused={isPaused}`)
- Modify: `frontend/src/i18n/strings.ts` (add `eta.paused`)
- Test: `frontend/src/components/EtaBar.test.tsx`

**Interfaces:**
- Consumes: App's existing `isPaused` local (= `sim.status.paused`); existing `eta.*` key style
- Produces: `EtaBarProps.isPaused?: boolean`; new string key `eta.paused`

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/components/EtaBar.test.tsx`. The file already mocks `../i18n` so `t(key) → key`; assert on the raw `eta.paused` key. The progress fill gets a `data-testid` in Step 3.
  ```tsx
  describe('EtaBar — paused state', () => {
    it('renders a Paused chip when isPaused is true', () => {
      render(<EtaBar {...baseProps} isPaused />);
      expect(screen.getByText('eta.paused')).toBeInTheDocument();
    });
    it('does not render the Paused chip when isPaused is false/absent', () => {
      render(<EtaBar {...baseProps} />);
      expect(screen.queryByText('eta.paused')).not.toBeInTheDocument();
    });
    it('dims the progress fill when paused', () => {
      const { rerender } = render(<EtaBar {...baseProps} />);
      const fillActive = screen.getByTestId('eta-progress-fill');
      expect(fillActive.style.opacity).toBe('1');
      rerender(<EtaBar {...baseProps} isPaused />);
      const fillPaused = screen.getByTestId('eta-progress-fill');
      expect(fillPaused.style.opacity).toBe('0.4');
    });
  });
  ```

- [ ] **Step 2: Run test, verify it fails.**
  ```
  cd frontend && npx vitest run src/components/EtaBar.test.tsx -t "paused state"
  ```
  Expected: fails — `EtaBar` ignores `isPaused`; no `eta.paused` text, and the fill has no `data-testid` (so `getByTestId` throws).

- [ ] **Step 3: Implement.** In `EtaBar.tsx`, add `isPaused?: boolean;` to `EtaBarProps`, and add `isPaused` to the destructure (`{ state, progress, remainingDistance, traveledDistance, eta, runtimes, isPaused }`). Tag + dim the progress fill (the inner `<div>` inside the `{/* Progress bar */}` block — currently has only a `style` prop, no `data-testid`):
  ```tsx
        <div
          data-testid="eta-progress-fill"
          style={{
            height: '100%',
            width: `${percent}%`,
            borderRadius: 2,
            background: 'linear-gradient(90deg, #4285f4, #34a853)',
            transition: 'width 0.5s ease-out',
            opacity: isPaused ? 0.4 : 1,
          }}
        />
  ```
  Add the Paused chip right after the `{/* Percentage */}` `<span>` (before the first separator `<div>`):
  ```tsx
      {isPaused && (
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
          color: '#ffb74d', background: 'rgba(255, 183, 77, 0.14)',
          border: '1px solid rgba(255, 183, 77, 0.4)',
          borderRadius: 6, padding: '1px 7px', textTransform: 'uppercase',
        }}>{t('eta.paused')}</span>
      )}
  ```
  In `App.tsx`, at the `<EtaBar …>` call site add `isPaused={isPaused}` (e.g. after `eta={sim.eta ?? 0}`). In `strings.ts`, add near the other `eta.*` keys:
  ```ts
  'eta.paused': { zh: '已暫停', en: 'Paused' },
  ```

- [ ] **Step 4: Run test, verify it passes.**
  ```
  cd frontend && npx vitest run src/components/EtaBar.test.tsx -t "paused state"
  ```
  Expected: PASS. (The existing EtaBar tests stay green — they never pass `isPaused`, so default `undefined` → falsy → no chip, opacity 1.)

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/components/EtaBar.tsx frontend/src/App.tsx frontend/src/i18n/strings.ts frontend/src/components/EtaBar.test.tsx
  git commit -m "feat(eta): surface a paused state (chip + dimmed progress) in the ETA bar"
  ```


---

### Task 10: Indicate that a speed range overrides the custom fixed speed (dim custom field + hint)

**Context (real code read):** In `ControlPanel.tsx` (Speed section, `sections.speed` defaults to `true` so it renders expanded), the custom-speed `<input value={customSpeedKmh ?? ''}>` (line 737, `placeholder="km/h"`, `style={{ flex: 1, maxWidth: 80 }}`) and the random range (`speedMinKmh` / `speedMaxKmh`) render independently. The range comment says "Random range (overrides fixed)" and the `speedMinKmh != null && speedMaxKmh != null` line shows `panel.speed_range_active … (panel.speed_range_hint)` confirming range wins — but the UI shows both the green `panel.custom_speed_active` line AND the range line simultaneously, with no signal the custom value is being ignored. When a range is set (both bounds non-null), dim + disable the custom input and replace its green `panel.custom_speed_active` line with a `panel.range_overrides_custom` hint.

**Files:**
- Modify: `frontend/src/components/ControlPanel.tsx` (the custom-speed input block, lines 737–770)
- Modify: `frontend/src/i18n/strings.ts` (add `panel.range_overrides_custom`)
- Test: `frontend/src/components/ControlPanel.test.tsx`

**Interfaces:**
- Consumes: existing `customSpeedKmh` / `speedMinKmh` / `speedMaxKmh` props (all destructured in the component params, ~lines 286–290)
- Produces: new string key `panel.range_overrides_custom`

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/components/ControlPanel.test.tsx` (reuse `makeProps`; the file mocks `../i18n` so keys pass through; the Speed section is expanded by default). The custom input is uniquely found by `placeholder="km/h"` (the range inputs use the `panel.speed_range_min`/`max` keys as placeholders under the mock — distinct strings):
  ```tsx
  describe('ControlPanel — range overrides custom speed', () => {
    it('disables the custom-speed input and shows the override hint when a full range is set', () => {
      render(<ControlPanel {...(makeProps({ customSpeedKmh: 12, speedMinKmh: 5, speedMaxKmh: 20 }) as any)} />)
      const custom = screen.getByPlaceholderText('km/h') as HTMLInputElement
      expect(custom.disabled).toBe(true)
      expect(screen.getByText('panel.range_overrides_custom')).toBeInTheDocument()
      // the normal 'custom active' green line is suppressed while overridden
      expect(screen.queryByText(/panel\.custom_speed_active/)).toBeNull()
    })
    it('keeps the custom input enabled when no full range is set', () => {
      render(<ControlPanel {...(makeProps({ customSpeedKmh: 12, speedMinKmh: null, speedMaxKmh: null }) as any)} />)
      const custom = screen.getByPlaceholderText('km/h') as HTMLInputElement
      expect(custom.disabled).toBe(false)
      expect(screen.queryByText('panel.range_overrides_custom')).toBeNull()
    })
  })
  ```

- [ ] **Step 2: Run test, verify it fails.**
  ```
  cd frontend && npx vitest run src/components/ControlPanel.test.tsx -t "range overrides custom"
  ```
  Expected: fails — the custom input is never disabled and there's no `panel.range_overrides_custom` text.

- [ ] **Step 3: Implement.**
  (a) Define the derived flag in the component body, just before the `return (`. (The component is an arrow function with destructured props; `speedMinKmh` / `speedMaxKmh` are already in scope.) Add:
  ```tsx
  const rangeOverridesCustom = speedMinKmh != null && speedMaxKmh != null;
  ```
  (b) On the custom `<input>` (line 737), add `disabled={rangeOverridesCustom}` and extend its style. Change:
  ```tsx
              <input
                type="number"
                className="search-input"
                placeholder="km/h"
                value={customSpeedKmh ?? ''}
  ```
  to:
  ```tsx
              <input
                type="number"
                className="search-input"
                placeholder="km/h"
                disabled={rangeOverridesCustom}
                value={customSpeedKmh ?? ''}
  ```
  and change its `style={{ flex: 1, maxWidth: 80 }}` (line 751) to `style={{ flex: 1, maxWidth: 80, opacity: rangeOverridesCustom ? 0.45 : 1 }}`.
  (c) Replace the custom-active line block (lines 766–770):
  ```tsx
            {customSpeedKmh && (
              <div style={{ fontSize: 11, color: '#4caf50', marginTop: 4 }}>
                {t('panel.custom_speed_active')}: {customSpeedKmh} km/h ({(customSpeedKmh / 3.6).toFixed(1)} m/s)
              </div>
            )}
  ```
  with:
  ```tsx
            {customSpeedKmh && rangeOverridesCustom && (
              <div style={{ fontSize: 11, color: '#ffb74d', marginTop: 4 }}>
                {t('panel.range_overrides_custom')}
              </div>
            )}
            {customSpeedKmh && !rangeOverridesCustom && (
              <div style={{ fontSize: 11, color: '#4caf50', marginTop: 4 }}>
                {t('panel.custom_speed_active')}: {customSpeedKmh} km/h ({(customSpeedKmh / 3.6).toFixed(1)} m/s)
              </div>
            )}
  ```
  (d) In `strings.ts`, add near `panel.custom_speed_active` (line 191):
  ```ts
  'panel.range_overrides_custom': { zh: '已設隨機範圍,自訂速度將被忽略', en: 'Range is set — custom speed is ignored' },
  ```

- [ ] **Step 4: Run test, verify it passes.**
  ```
  cd frontend && npx vitest run src/components/ControlPanel.test.tsx -t "range overrides custom"
  ```
  Expected: PASS.

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/components/ControlPanel.tsx frontend/src/i18n/strings.ts frontend/src/components/ControlPanel.test.tsx
  git commit -m "feat(panel): dim custom speed + hint when a speed range overrides it"
  ```


---

### Task 11: Inline reason under the disabled GoldDitto ② button naming the missing prerequisite

**Context (real code read):** In `GoldDittoPanel.tsx`, the ② first-try button greys out (`disabled={disableFirstTry}`, `opacity: disableFirstTry ? 0.5 : 1`, lines 310–317) with no inline reason. The validation booleans already exist (lines 154–170): `noDevice`, `aValid`, `bValid`, `waitValid`, `isCycling`, and `disableFirstTry = noDevice || !aValid || !bValid || !waitValid || isCycling`. An empty B input keeps a neutral border (`bValid || bText === '' ? '1px solid #4b5563' : …`), so the user gets no hint that B is the blocker. Add a one-line hint UNDER the disabled ② button naming the first missing prerequisite (device → A → B → wait). Suppress the hint while `isCycling` (the disable then means "busy", not "missing input").

**Files:**
- Modify: `frontend/src/components/GoldDittoPanel.tsx` (after `const disableFirstTry = …` line 170; and the button column `<div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>` at line 301, after the ② button's `</button>` at line 317)
- Modify: `frontend/src/i18n/strings.ts` (add `goldditto.need_a`, `goldditto.need_b`, `goldditto.need_wait`)
- Test: `frontend/src/components/GoldDittoPanel.test.tsx`

**Interfaces:**
- Consumes: existing `noDevice` / `aValid` / `bValid` / `waitValid` / `isCycling` locals; the existing `goldditto.error.no_device` key (line 168 of strings.ts) for the no-device case
- Produces: new string keys `goldditto.need_a`, `goldditto.need_b`, `goldditto.need_wait`

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/components/GoldDittoPanel.test.tsx` (reuse `baseProps()`; i18n passthrough returns the key; the inputs are found by `getAllByPlaceholderText('lat, lng')`). With a device + valid A but empty B, the blocker is B:
  ```tsx
  it('shows the missing-B hint under a disabled ② when only A is filled', () => {
    render(<GoldDittoPanel {...baseProps()} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '10, 20' } }) // A valid, B empty
    expect(screen.getByText(/goldditto\.first_try/)).toBeDisabled()
    expect(screen.getByText('goldditto.need_b')).toBeInTheDocument()
  })

  it('hides the prerequisite hint once A, B and wait are all valid (② enabled)', () => {
    render(<GoldDittoPanel {...baseProps()} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '10, 20' } })
    fireEvent.change(inputs[1], { target: { value: '30, 40' } })
    expect(screen.getByText(/goldditto\.first_try/)).toBeEnabled()
    expect(screen.queryByText('goldditto.need_b')).toBeNull()
    expect(screen.queryByText('goldditto.need_a')).toBeNull()
  })
  ```

- [ ] **Step 2: Run test, verify it fails.**
  ```
  cd frontend && npx vitest run src/components/GoldDittoPanel.test.tsx -t "missing-B hint"
  ```
  Expected: fails — no `goldditto.need_b` text rendered.

- [ ] **Step 3: Implement.** In `GoldDittoPanel.tsx`, derive the hint key right after `const disableFirstTry = …` (line 170):
  ```ts
  const firstTryHintKey: 'goldditto.error.no_device' | 'goldditto.need_a' | 'goldditto.need_b' | 'goldditto.need_wait' | null =
    isCycling ? null
    : noDevice ? 'goldditto.error.no_device'
    : !aValid ? 'goldditto.need_a'
    : !bValid ? 'goldditto.need_b'
    : !waitValid ? 'goldditto.need_wait'
    : null
  ```
  Then add the hint right after the ② button's closing `</button>` (line 317), still inside the `<div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>`:
  ```tsx
        {firstTryHintKey && (
          <div style={{ fontSize: 11, color: '#fbbf24', marginTop: -2 }}>{t(firstTryHintKey)}</div>
        )}
  ```
  Note the no-device case already shows the top `goldditto.error.no_device` banner (line 218); reusing the key here is intentional (a second inline pointer right at the button). In `strings.ts`, add near the other `goldditto.*` keys:
  ```ts
  'goldditto.need_a': { zh: '請先填入有效的 A 點座標', en: 'Enter a valid A coordinate first' },
  'goldditto.need_b': { zh: '請先填入有效的 B 點座標', en: 'Enter a valid B coordinate first' },
  'goldditto.need_wait': { zh: '請填入有效的等待秒數 (0.5–10.0)', en: 'Enter a valid wait time (0.5–10.0)' },
  ```

- [ ] **Step 4: Run test, verify it passes.**
  ```
  cd frontend && npx vitest run src/components/GoldDittoPanel.test.tsx -t "hint"
  ```
  Expected: PASS. (The existing 'disables ② first-try while a cycle is in progress' test stays green — `isCycling` makes `firstTryHintKey` null, so no hint conflicts.)

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/components/GoldDittoPanel.tsx frontend/src/i18n/strings.ts frontend/src/components/GoldDittoPanel.test.tsx
  git commit -m "feat(goldditto): inline reason under the disabled 2nd-try button naming the missing input"
  ```


---

### Task 12: Don't optimistically move the marker before dual-device teleport succeeds (revert on failure)

**Context (real code read):** In `useSimActions.handleTeleport`, the dual branch (lines 120–123) sets the marker BEFORE the network round-trip:
```ts
    if (udids.length >= 2) {
      sim.setCurrentPosition({ lat, lng })
      const outcome = await sim.teleportAll(udids, lat, lng)
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
    } else {
```
The single-device path (`sim.teleport` in `useSimulation.ts`, line 627) only does `setCurrentPosition({ lat, lng })` AFTER `await api.teleport(...)` succeeds (line 642). So on a dual-device failure the marker has already jumped and is never reverted — the map lies. Fix: snapshot the previous position, set optimistically, and revert if the fan-out fully fails (`outcome.ok.length === 0 && outcome.failed.length > 0`). Keep the optimistic set for the success/partial case (the dual pre-sync model wants both phones at the same coord). NOTE: `App.dangerzone.test.tsx` + the existing `useSimActions.test.tsx` dual-happy-path test pin `sim.setCurrentPosition` is called with `{ lat: 10, lng: 20 }` (the `okOutcome` fixture has `failed: []`, so no revert) — that assertion MUST still hold, so do NOT remove the optimistic set; only ADD a revert on total failure.

**Files:**
- Modify: `frontend/src/hooks/useSimActions.ts` (the `handleTeleport` dual branch, lines 120–123)
- Test: `frontend/src/hooks/useSimActions.test.tsx`

**Interfaces:**
- Consumes: `sim.currentPosition`, `sim.setCurrentPosition`, `sim.teleportAll` (already on the `sim` bag); the `{ ok, failed }` outcome shape
- Produces: none

- [ ] **Step 1: Write the failing test.** Append to `frontend/src/hooks/useSimActions.test.tsx` inside `describe('useSimActions — teleport')`. Drive a fully-failed outcome from `teleportAll` and assert the marker is reverted to the prior position. The `makeSim` default `currentPosition` is `{ lat: 1, lng: 2 }`:
  ```tsx
  it('dual device, total failure: reverts the optimistic marker to the prior position', async () => {
    const failed = { ok: [], failed: [{ udid: 'A', reason: 'x' }, { udid: 'B', reason: 'y' }] }
    const sim = makeSim({
      currentPosition: { lat: 1, lng: 2 },
      teleportAll: vi.fn(async () => failed),
    })
    const { result } = setup({ udids: ['A', 'B'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    // optimistic set first, then revert to the snapshot { lat: 1, lng: 2 }
    expect(sim.setCurrentPosition).toHaveBeenCalledWith({ lat: 10, lng: 20 })
    expect(sim.setCurrentPosition).toHaveBeenLastCalledWith({ lat: 1, lng: 2 })
  })

  it('dual device, partial success: does NOT revert the marker', async () => {
    const partial = { ok: [{ udid: 'A', value: {} }], failed: [{ udid: 'B', reason: 'y' }] }
    const sim = makeSim({
      currentPosition: { lat: 1, lng: 2 },
      teleportAll: vi.fn(async () => partial),
    })
    const { result } = setup({ udids: ['A', 'B'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    expect(sim.setCurrentPosition).toHaveBeenLastCalledWith({ lat: 10, lng: 20 })
  })
  ```
  (The existing 'dual device: sets currentPosition … teleportAll …' happy-path test — which uses the default `okOutcome` with `failed: []` — must still pass, asserting `setCurrentPosition` was called with `{ lat: 10, lng: 20 }`.)

- [ ] **Step 2: Run test, verify it fails.**
  ```
  cd frontend && npx vitest run src/hooks/useSimActions.test.tsx -t "total failure"
  ```
  Expected: fails — the dual branch never reverts, so the last `setCurrentPosition` call is `{ lat: 10, lng: 20 }`, not the `{ lat: 1, lng: 2 }` snapshot.

- [ ] **Step 3: Implement.** In `handleTeleport`, change the dual branch from:
  ```ts
    if (udids.length >= 2) {
      sim.setCurrentPosition({ lat, lng })
      const outcome = await sim.teleportAll(udids, lat, lng)
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
    } else {
  ```
  to:
  ```ts
    if (udids.length >= 2) {
      const prevPos = sim.currentPosition
      sim.setCurrentPosition({ lat, lng })
      const outcome = await sim.teleportAll(udids, lat, lng)
      // Total failure: the marker jumped but no device actually moved —
      // revert so the map doesn't lie. Partial / full success keeps the
      // optimistic position (dual pre-sync wants both phones co-located).
      if (outcome.ok.length === 0 && outcome.failed.length > 0) {
        sim.setCurrentPosition(prevPos ?? null)
      }
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
    } else {
  ```

- [ ] **Step 4: Run test, verify it passes.**
  ```
  cd frontend && npx vitest run src/hooks/useSimActions.test.tsx -t "teleport"
  ```
  Expected: PASS (new revert tests + the pre-existing dual happy-path test).

- [ ] **Step 5: tsc + broader suite.** `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green) — pay attention to `src/App.dangerzone.test.tsx` since it characterizes the dual teleport path.

- [ ] **Step 6: Commit.**
  ```
  git add frontend/src/hooks/useSimActions.ts frontend/src/hooks/useSimActions.test.tsx
  git commit -m "fix(sim): revert the optimistic marker on a fully-failed dual-device teleport"
  ```


---


<!-- ===== D3 · UX — bookmark/route CRUD feedback ===== -->

### Task 13: Bookmark single-delete (context menu) confirm + try/catch + failure toast

**Files:**
- Modify: `frontend/src/components/BookmarkContextMenu.tsx` (the Delete row `onClick`, in the `{/* 8. Delete. */}` block — currently `onClick={() => { if (bm.id) onDelete(bm.id); onClose(); }}`)
- Modify: `frontend/src/components/BookmarkList.tsx` (the `<BookmarkContextMenu ... onDelete={onBookmarkDelete} />` wiring — wrap it in a try/catch + failure toast)
- Test: `frontend/src/components/BookmarkContextMenu.test.tsx`

**Interfaces:**
- Consumes: none
- Produces: i18n keys `bm.delete_one_confirm` + `bm.delete_failed` (both new — `bm.delete_failed` does NOT yet exist, verified); an inline async `onDelete` wrapper in BookmarkList (no exported name)

**Context (real current code):** the bulk path (`useBookmarkSelection.handleBulkDelete`) and category delete (`CategoryDeleteDropdown.confirmSoft/confirmCascade` in `CategoryManagerPanel.tsx`) BOTH gate on `window.confirm`. The single-delete context-menu path does NOT — `BookmarkContextMenu.tsx` fires `onDelete(bm.id)` directly (the `{/* 8. Delete. */}` row, currently `onClick={() => { if (bm.id) onDelete(bm.id); onClose(); }}`), and `BookmarkList` passes `onDelete={onBookmarkDelete}` straight through (around the `<BookmarkContextMenu>` JSX, `onDelete={onBookmarkDelete}`) with no try/catch. App wires `onBookmarkDelete={(id) => bm.deleteBookmark(id)}` (fire-and-forget); `bm.deleteBookmark` is async (`await api.deleteBookmark(id)`) and can reject unhandled. `onShowToast` IS already a prop on `BookmarkList`, and `t` is in scope via `const t = useT()`.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/components/BookmarkContextMenu.test.tsx` (it already imports `vi`, `screen`, `fireEvent`, `afterEach`, and has a module-level `bm` const + a `makeProps` helper + an i18n identity mock):

```tsx
describe('BookmarkContextMenu delete confirmation (U13)', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('does NOT call onDelete when the confirm is dismissed', () => {
    const onDelete = vi.fn();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<BookmarkContextMenu {...makeProps({ onDelete, onClose })} />);
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).not.toHaveBeenCalled();
    // Menu still closes either way (parity with the other action rows).
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onDelete(bm.id) when the confirm is accepted', () => {
    const onDelete = vi.fn();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<BookmarkContextMenu {...makeProps({ onDelete, onClose })} />);
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(bm.id);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

NOTE: the EXISTING test `'fires onDelete(bm.id) and closes when Delete is clicked'` (last test in the file) does NOT stub `window.confirm`. In jsdom `window.confirm` returns `undefined` (falsy) by default, so after this change that test would see `onDelete` not called and FAIL. Update that existing test in the SAME edit to stub confirm true:

```tsx
  it('fires onDelete(bm.id) and closes when Delete is clicked', () => {
    const onDelete = vi.fn();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<BookmarkContextMenu {...makeProps({ onDelete, onClose })} />);
    fireEvent.click(screen.getByText('generic.delete'));
    expect(onDelete).toHaveBeenCalledWith(bm.id);
    expect(onClose).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/BookmarkContextMenu.test.tsx -t "delete confirmation"`. Expected failure: `expected "onDelete" to not have been called` (the dismissed-confirm case) because the current code calls `onDelete` unconditionally.

- [ ] **Step 3: Implement** —

3a. Add the i18n keys in `frontend/src/i18n/strings.ts`. Put `bm.delete_one_confirm` next to the existing `'bm.delete_confirm'` (around line 633) and `bm.delete_failed` next to the existing `'bm.import_failed'` (around line 580):
```ts
  'bm.delete_one_confirm': { zh: '確定要刪除收藏「{name}」嗎?', en: 'Delete bookmark "{name}"?' },
```
```ts
  'bm.delete_failed': { zh: '刪除失敗:{error}', en: 'Delete failed: {error}' },
```
(Verified: `bm.delete_confirm` and `bm.import_failed` exist; `bm.delete_failed` does NOT — so it must be ADDED here.)

3b. In `frontend/src/components/BookmarkContextMenu.tsx`, the Delete row currently is:
```tsx
          onClick={() => {
            if (bm.id) onDelete(bm.id);
            onClose();
          }}
```
Replace with a confirm gate (the menu still closes regardless, matching every other action row):
```tsx
          onClick={() => {
            if (bm.id && window.confirm(t('bm.delete_one_confirm', { name: bm.name }))) {
              onDelete(bm.id);
            }
            onClose();
          }}
```
(`t` is already in scope via `const t = useT();`; its returned function accepts an optional `Record<string, string | number>` 2nd arg — the component already uses interpolation elsewhere, e.g. `reverseGeo` error keys and the move-to submenu.)

3c. In `frontend/src/components/BookmarkList.tsx`, the context menu currently wires `onDelete={onBookmarkDelete}` (in the `{contextMenu && (<BookmarkContextMenu ... />)}` JSX). Replace with a try/catch wrapper that toasts on failure so the previously-unhandled rejection surfaces:
```tsx
          onDelete={async (id) => {
            try {
              await onBookmarkDelete(id);
            } catch (err: any) {
              if (onShowToast) onShowToast(t('bm.delete_failed', { error: err?.message || '' }));
            }
          }}
```
`onBookmarkDelete`'s prop type is `(id: string) => void`; awaiting a `void`-returning value is legal TS (App wires it to the async `bm.deleteBookmark`). If tsc complains, widen the prop on `BookmarkListProps` to `onBookmarkDelete: (id: string) => void | Promise<void>` (a backward-compatible widening; ControlPanel/App still pass a void-returning arrow).

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/BookmarkContextMenu.test.tsx`. Expected: all delete tests PASS (dismissed → no onDelete; accepted → onDelete(bm.id); menu closes in both).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green). Watch for any OTHER existing test that clicks the bookmark context-menu delete without stubbing confirm — grep `getByText('generic.delete')` across `*.test.tsx` and stub confirm in those too. (Note: `BookmarkList.test.tsx` exercises BULK delete via the multi-select toolbar — a different path, already stubbing confirm — not the context-menu single-delete, so it is unaffected.)

- [ ] **Step 6: Commit** — `git add frontend/src/components/BookmarkContextMenu.tsx frontend/src/components/BookmarkList.tsx frontend/src/i18n/strings.ts frontend/src/components/BookmarkContextMenu.test.tsx` then `git commit -m "feat(bookmark): confirm single-delete + toast on failure (SH2 U13)"`


---

### Task 14: Route single-delete (context menu) window.confirm gate

**Files:**
- Modify: `frontend/src/components/RouteList.tsx` (the context-menu Delete row, currently `onClick={() => { onRouteDelete(contextMenu.route.id); setContextMenu(null); }}`)
- Test: `frontend/src/components/RouteList.test.tsx`

**Interfaces:**
- Consumes: existing i18n key `panel.route_delete_confirm` (`'刪除路線「{name}」?'` / `'Delete route "{name}"?'`, strings.ts line 230)
- Produces: none

**Context (real current code):** `RouteList.handleBulkDelete` already gates on `window.confirm(t('route.bulk_delete_confirm')...)`. The single-route context-menu delete (the last item in the `{contextMenu && createPortal(...)}` block) calls `onRouteDelete(contextMenu.route.id)` with NO confirm. There is already an i18n key `panel.route_delete_confirm` with a `{name}` slot — reuse it.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/components/RouteList.test.tsx` (it imports `describe, it, expect, vi` and mocks `../i18n` to an identity translator `useT: () => (key) => key`, and has `makeProps` + `makeRoute` helpers; the default route is named `Morning Loop` with id `r1`). The context menu opens on right-click of a row; the Delete item text is `generic.delete` (identity-translated):

```tsx
describe('RouteList single-delete confirmation (U13)', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('does NOT call onRouteDelete when the confirm is dismissed', () => {
    const onRouteDelete = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<RouteList {...(makeProps({ onRouteDelete }) as any)} />);
    // Open the row's right-click context menu, then click Delete.
    fireEvent.contextMenu(screen.getByText('Morning Loop'));
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onRouteDelete).not.toHaveBeenCalled();
  });

  it('calls onRouteDelete(id) when the confirm is accepted', () => {
    const onRouteDelete = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<RouteList {...(makeProps({ onRouteDelete }) as any)} />);
    fireEvent.contextMenu(screen.getByText('Morning Loop'));
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onRouteDelete).toHaveBeenCalledWith('r1');
  });
});
```

Update the existing top import to add `afterEach`: change `import { describe, it, expect, vi } from 'vitest'` to `import { describe, it, expect, vi, afterEach } from 'vitest'`. (The `../i18n` mock here is a bare identity `useT: () => (key) => key` that ignores the 2nd interpolation arg, so `window.confirm` is called with the raw key string — the assertions only check call-count + onRouteDelete, not the message text, so this is fine.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/RouteList.test.tsx -t "single-delete confirmation"`. Expected failure: `expected "onRouteDelete" to not have been called` (the dismissed case) because the current code deletes unconditionally.

- [ ] **Step 3: Implement** — in `frontend/src/components/RouteList.tsx`, the context-menu Delete row is currently:
```tsx
          <div
            style={ctxItemStyle}
            onMouseEnter={ctxHighlight} onMouseLeave={ctxUnhighlight}
            onClick={() => { onRouteDelete(contextMenu.route.id); setContextMenu(null); }}
          >
```
Replace the `onClick` with a confirm gate reusing the existing key:
```tsx
            onClick={() => {
              const r = contextMenu.route;
              setContextMenu(null);
              if (window.confirm(t('panel.route_delete_confirm', { name: r.name }))) {
                onRouteDelete(r.id);
              }
            }}
```
(Capture `contextMenu.route` into `r` BEFORE `setContextMenu(null)` because clearing the menu nulls `contextMenu`. `t` is in scope via `const t = useT()`.)

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/RouteList.test.tsx`. Expected: both new tests PASS; the existing RouteList tests (which never open the context menu) stay green.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/RouteList.tsx frontend/src/components/RouteList.test.tsx` then `git commit -m "feat(route): confirm single route delete from context menu (SH2 U13)"`


---

### Task 15: Custom + Edit bookmark dialogs: inline out-of-range red error

**Files:**
- Modify: `frontend/src/components/CustomBookmarkDialog.tsx` (after the lat/lng `<input>`, before the buttons row)
- Modify: `frontend/src/components/EditBookmarkDialog.tsx` (same spot)
- Test: `frontend/src/components/CustomBookmarkDialog.test.tsx` (and `frontend/src/components/EditBookmarkDialog.test.tsx`)

**Interfaces:**
- Consumes: none
- Produces: i18n key `bm.latlng_out_of_range`

**Context (real current code):** both dialogs parse `parseFloat(lat)`/`parseFloat(lng)` and `handleSubmit` `return`s SILENTLY when `latNum < -90 || latNum > 90` / `lngNum < -180 || lngNum > 180`. The Add/Save button only disables on `!Number.isFinite(parseFloat(lat))` (and lng), so a FINITE but out-of-range value (e.g. lat `200`) leaves the button ENABLED and clicking it no-ops with zero feedback. The existing `CustomBookmarkDialog.test.tsx` test `'does not submit when lat is out of range'` proves the silent no-op. The pattern to mirror is `AddBookmarkDialog.tsx`'s `{!hasPosition && (<div style={{ fontSize: 11, color: '#f44336', marginTop: 6 }}>{t('bm.no_position')}</div>)}`.

- [ ] **Step 1: Write the failing test** — add to `frontend/src/components/CustomBookmarkDialog.test.tsx` (it has `makeProps`, an identity i18n mock `useT: () => (k) => k`, `render`/`screen`/`fireEvent`):

```tsx
  it('shows an inline out-of-range error for a finite-but-invalid lat', () => {
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '200', lng: '120.65' })}
      />,
    );
    // The error key renders verbatim (identity translator).
    expect(screen.getByText('bm.latlng_out_of_range')).toBeTruthy();
  });

  it('does NOT show the out-of-range error for an in-range pair', () => {
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '24.14', lng: '120.65' })}
      />,
    );
    expect(screen.queryByText('bm.latlng_out_of_range')).toBeNull();
  });

  it('does NOT show the out-of-range error while lat is still partial/empty', () => {
    render(<CustomBookmarkDialog {...makeProps({ name: 'Pin', lat: '24.', lng: '' })} />);
    // parseFloat('24.') === 24 is in range, lng empty (NaN, not finite) => no out-of-range error.
    expect(screen.queryByText('bm.latlng_out_of_range')).toBeNull();
  });
```

Mirror the first two cases into `frontend/src/components/EditBookmarkDialog.test.tsx`. EditBookmarkDialog renders only when `bookmark` is non-null, so its `makeProps` must pass a `bookmark` object — read that test file's existing `makeProps` and reuse it; pass `lat: '200', lng: '120.65'` and assert `screen.getByText('bm.latlng_out_of_range')`, plus an in-range case asserting `queryByText(...)` is null.

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/CustomBookmarkDialog.test.tsx -t "out-of-range"`. Expected failure: `Unable to find an element with the text: bm.latlng_out_of_range`.

- [ ] **Step 3: Implement** —

3a. Add the i18n key in `frontend/src/i18n/strings.ts` next to `'bm.latlng_single_placeholder'` (around line 573):
```ts
  'bm.latlng_out_of_range': { zh: '座標超出範圍 (緯度 -90~90,經度 -180~180)', en: 'Coordinates out of range (lat -90..90, lng -180..180)' },
```

3b. In `frontend/src/components/CustomBookmarkDialog.tsx`, compute the out-of-range flag in the component body (after `const t = useT(); if (!open) return null;`):
```tsx
  const latNum = parseFloat(lat);
  const lngNum = parseFloat(lng);
  const latOutOfRange = Number.isFinite(latNum) && (latNum < -90 || latNum > 90);
  const lngOutOfRange = Number.isFinite(lngNum) && (lngNum < -180 || lngNum > 180);
  const outOfRange = latOutOfRange || lngOutOfRange;
```
and render the inline error after the single 'lat, lng' `<input>` (the one with `placeholder={t('bm.latlng_single_placeholder')}`), before the `<select>`/buttons row — concretely, just before the `<div style={{ display: 'flex', gap: 6 }}>` button row:
```tsx
        {outOfRange && (
          <div style={{ fontSize: 11, color: '#f44336', marginBottom: 8 }}>
            {t('bm.latlng_out_of_range')}
          </div>
        )}
```
(Do NOT change the silent-return guard in `handleSubmit`; just add visible feedback. `latNum`/`lngNum` already exist locally in `handleSubmit` — these new body-level consts shadow nothing because `handleSubmit` re-declares its own; leaving both is fine, or reuse the body-level ones inside `handleSubmit`.)

3c. Apply the IDENTICAL `latNum`/`lngNum`/`outOfRange` computation + inline error block to `frontend/src/components/EditBookmarkDialog.tsx`. Declare the consts after `const t = useT(); if (!bookmark) return null;`, and place the error block after its single 'lat, lng' `<input>` (the one with `style={{ width: '100%', marginBottom: 12 }}`) and before its buttons row (`<div style={{ display: 'flex', gap: 6 }}>`).

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/CustomBookmarkDialog.test.tsx src/components/EditBookmarkDialog.test.tsx`. Expected: all out-of-range tests PASS, existing tests still green.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/CustomBookmarkDialog.tsx frontend/src/components/EditBookmarkDialog.tsx frontend/src/i18n/strings.ts frontend/src/components/CustomBookmarkDialog.test.tsx frontend/src/components/EditBookmarkDialog.test.tsx` then `git commit -m "feat(bookmark): inline out-of-range coord error in custom/edit dialogs (SH2 U15)"`


---

### Task 16: Bookmark left-click teleport: device gate + GPS-moved feedback

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (`handleBookmarkClick`)
- Test: `frontend/src/components/BookmarkList.test.tsx`

**Interfaces:**
- Consumes: existing `BookmarkList` props `deviceConnected: boolean`, `onTeleport`, `onBookmarkClick`, `onShowToast`; existing `flyGps` local state (localStorage `locwarp.bookmark_fly_gps`)
- Produces: i18n keys `bm.click_moves_gps`, `bm.click_no_device`

**Context (real current code):** `handleBookmarkClick` runs `if (flyGps) onTeleport(...) else onBookmarkClick(...)`, then ALWAYS flashes the row green for 500ms. With no device, the right-click menu shows a disabled `map.device_disconnected` row (gated on `deviceConnected`), but the LEFT-click path ignores `deviceConnected` entirely — it still calls `onTeleport` (a no-op fan-out at App level) and flashes a false 'success'. `deviceConnected` is ALREADY a prop on BookmarkList. U16 = gate the teleport branch on `deviceConnected`; U17 = when a teleport actually fires, surface a toast so the user knows a single click moved real GPS (do NOT change the `flyGps` default — it stays `true`).

- [ ] **Step 1: Write the failing test** — add to `frontend/src/components/BookmarkList.test.tsx` (it has `renderWithServices`, `makeProps`, identity i18n mock, and imports `vi`, `screen`, `fireEvent`, `afterEach`). Default `makeProps` sets `deviceConnected: true`; `flyGps` is local state read from localStorage (`null` → `true`). Click a bookmark row by its name (`Place 0`, which is bm-0 at lat 25 / lng 121):

```tsx
describe('BookmarkList left-click teleport gating + feedback (U16/U17)', () => {
  afterEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

  it('with a device connected + flyGps on, left-click teleports AND toasts that GPS moved', async () => {
    const onTeleport = vi.fn();
    const onShowToast = vi.fn();
    renderWithServices(
      <BookmarkList {...makeProps({ deviceConnected: true, onTeleport, onShowToast })} />,
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('Place 0'));
    expect(onTeleport).toHaveBeenCalledWith(25, 121);
    expect(onShowToast).toHaveBeenCalledWith('bm.click_moves_gps');
  });

  it('with NO device connected, left-click does NOT teleport and shows a no-device toast', async () => {
    const onTeleport = vi.fn();
    const onBookmarkClick = vi.fn();
    const onShowToast = vi.fn();
    renderWithServices(
      <BookmarkList
        {...makeProps({ deviceConnected: false, onTeleport, onBookmarkClick, onShowToast })}
      />,
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('Place 0'));
    expect(onTeleport).not.toHaveBeenCalled();
    // Falls back to map-pan (preview) instead of a fake teleport.
    expect(onBookmarkClick).toHaveBeenCalled();
    expect(onShowToast).toHaveBeenCalledWith('bm.click_no_device');
  });
});
```

(`getBookmarkUiState`, `waitFor`, `vi`, `screen`, `fireEvent`, `afterEach` are all already in scope in this file. The `await waitFor(...)` gate mirrors the file's other tests so the ui-state fetch settles before the click.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/BookmarkList.test.tsx -t "left-click teleport gating"`. Expected failure: the no-device case fails with `expected "onTeleport" not to have been called` (current code teleports regardless of `deviceConnected`), and the flyGps-on case fails with `expected "onShowToast" to have been called with bm.click_moves_gps`.

- [ ] **Step 3: Implement** —

3a. Add i18n keys in `frontend/src/i18n/strings.ts` next to `'bm.fly_gps'` (around line 620):
```ts
  'bm.click_moves_gps': { zh: '已將 iPhone 定位移到此收藏', en: 'Moved iPhone GPS to this bookmark' },
  'bm.click_no_device': { zh: '未連接裝置:只移動畫面,未變更 GPS', en: 'No device connected — panned the map only, GPS unchanged' },
```

3b. In `frontend/src/components/BookmarkList.tsx`, `handleBookmarkClick` is currently:
```tsx
  const handleBookmarkClick = (bm: Bookmark) => {
    const now = Date.now();
    if (now - lastClickTs.current < 150) return;
    lastClickTs.current = now;
    if (flyGps) {
      onTeleport(bm.lat, bm.lng);
    } else {
      onBookmarkClick(bm);
    }
    if (bm.id) {
      setFlashedBmId(bm.id);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlashedBmId(null), 500);
    }
  };
```
Replace the body so the teleport branch is gated on `deviceConnected`, falling back to map-pan + a no-device toast, and toasting on a real teleport:
```tsx
  const handleBookmarkClick = (bm: Bookmark) => {
    const now = Date.now();
    if (now - lastClickTs.current < 150) return;
    lastClickTs.current = now;
    if (flyGps && deviceConnected) {
      onTeleport(bm.lat, bm.lng);
      if (onShowToast) onShowToast(t('bm.click_moves_gps'));
    } else if (flyGps && !deviceConnected) {
      // No device: don't fake a teleport. Pan the map for a preview and say so.
      onBookmarkClick(bm);
      if (onShowToast) onShowToast(t('bm.click_no_device'));
    } else {
      onBookmarkClick(bm);
    }
    if (bm.id) {
      setFlashedBmId(bm.id);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlashedBmId(null), 500);
    }
  };
```
(`deviceConnected`, `onTeleport`, `onBookmarkClick`, `onShowToast`, `t` are all already in scope.)

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/BookmarkList.test.tsx`. Expected: both new tests PASS; pre-existing BookmarkList tests still green (existing tests use `deviceConnected: true` default and never assert on the row-click toast, so they are unaffected — but if one starts failing on an unexpected `onShowToast` call, relax that assertion to allow the new `bm.click_moves_gps` toast).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/BookmarkList.tsx frontend/src/i18n/strings.ts frontend/src/components/BookmarkList.test.tsx` then `git commit -m "feat(bookmark): gate left-click teleport on device + toast GPS-moved (SH2 U16/U17)"`


---

### Task 17: Bookmark JSON import label: in-flight busy state (disable + spinner text)

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (the `{onImport && (<label ...>` import button; add a local `importing` state + disabled styling)
- Test: `frontend/src/components/BookmarkList.test.tsx`

**Interfaces:**
- Consumes: existing `onImport?: (file: File) => Promise<void>` prop
- Produces: i18n key `bm.import_busy`

**Context (real current code):** the import `<label>` (with `title={t('bm.import_tooltip')}`) wraps a hidden file `<input>` whose `onChange` does `if (f) await onImport(f); e.target.value = ''`. While the awaited `onImport` runs (slow iCloud write), the label stays fully clickable — a second file pick double-triggers the import. App's `handleBookmarkImport` already toasts success/failure (`bm.import_success` / `bm.import_failed`), so KEEP that — only add in-flight disable + label change. The visible content is just the SVG icon (no text label). NOTE: `makeProps` in `BookmarkList.test.tsx` defaults `onImport: undefined`, so the import label is NOT rendered unless the test passes an `onImport` — the test below does.

- [ ] **Step 1: Write the failing test** — add to `frontend/src/components/BookmarkList.test.tsx`. Use a deferred `onImport` so the busy window is observable. The import control is the `<label>` with `title={t('bm.import_tooltip')}` wrapping a hidden `input[type=file]`:

```tsx
describe('BookmarkList import busy state (U14)', () => {
  it('disables the import control while an import is in flight, re-enables after', async () => {
    let resolveImport!: () => void;
    const onImport = vi.fn(() => new Promise<void>((res) => { resolveImport = res; }));
    renderWithServices(<BookmarkList {...makeProps({ onImport })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    const label = screen.getByTitle('bm.import_tooltip');
    const input = label.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{}'], 'b.json', { type: 'application/json' });

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });
    // In-flight: control is marked busy (aria-disabled) and shows the busy label.
    expect(label).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('bm.import_busy')).toBeTruthy();
    expect(onImport).toHaveBeenCalledTimes(1);

    await act(async () => { resolveImport(); await Promise.resolve(); });
    // Settled: no longer busy.
    expect(label).toHaveAttribute('aria-disabled', 'false');
  });
});
```

(`act`, `screen`, `fireEvent`, `vi`, `waitFor`, `getBookmarkUiState` are all already in scope in this file; `toHaveAttribute` comes from the jest-dom setup the suite already uses.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/BookmarkList.test.tsx -t "import busy state"`. Expected failure: `Unable to find an element with the text: bm.import_busy` (and the `aria-disabled` assertion fails) because no busy state exists yet.

- [ ] **Step 3: Implement** —

3a. Add i18n key in `frontend/src/i18n/strings.ts` next to `'bm.import'` (around line 577):
```ts
  'bm.import_busy': { zh: '匯入中…', en: 'Importing…' },
```

3b. In `frontend/src/components/BookmarkList.tsx`, add a local state near the other `useState` declarations (e.g. by `const [search, setSearch] = useState('')`):
```tsx
  const [importing, setImporting] = useState(false);
```
(`useState` is already imported.)

3c. Replace the import `<label>` block (currently):
```tsx
        {onImport && (
          <label
            className="action-btn"
            style={{ padding: '3px 6px', fontSize: 12, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', marginLeft: (onExportClick || exportUrl || onBulkPaste) ? 0 : 'auto' }}
            title={t('bm.import_tooltip')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <input
              type="file"
              accept="application/json,.json"
              style={{ display: 'none' }}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) await onImport(f);
                e.target.value = '';
              }}
            />
          </label>
        )}
```
with a busy-aware version that disables re-entry, dims the control, shows the busy text, and prevents the file picker from opening while importing:
```tsx
        {onImport && (
          <label
            className="action-btn"
            aria-disabled={importing}
            style={{
              padding: '3px 6px', fontSize: 12,
              cursor: importing ? 'not-allowed' : 'pointer',
              opacity: importing ? 0.5 : 1,
              display: 'inline-flex', alignItems: 'center', gap: 4,
              marginLeft: (onExportClick || exportUrl || onBulkPaste) ? 0 : 'auto',
            }}
            title={t('bm.import_tooltip')}
            onClick={(e) => { if (importing) e.preventDefault(); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            {importing && <span style={{ fontSize: 11 }}>{t('bm.import_busy')}</span>}
            <input
              type="file"
              accept="application/json,.json"
              style={{ display: 'none' }}
              disabled={importing}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setImporting(true);
                try {
                  await onImport(f);
                } finally {
                  setImporting(false);
                  e.target.value = '';
                }
              }}
            />
          </label>
        )}
```
NOTE: `aria-disabled` renders as the literal strings `'true'`/`'false'` (matching the test's `toHaveAttribute('aria-disabled', 'true'|'false')`). The success/failure toast lives in App's `handleBookmarkImport`, untouched here.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/BookmarkList.test.tsx`. Expected: busy-state test PASSES (aria-disabled true mid-flight, `bm.import_busy` shown, false after settle).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/BookmarkList.tsx frontend/src/i18n/strings.ts frontend/src/components/BookmarkList.test.tsx` then `git commit -m "feat(bookmark): in-flight busy state on JSON import label (SH2 U14)"`


---

### Task 18: Category mutation: await + failure toast (App-level onCategoryAdd / onCategoryDelete / onCategoryDeleteCascade)

**Files:**
- Modify: `frontend/src/App.tsx` (the `onCategoryAdd` / `onCategoryDelete` / `onCategoryDeleteCascade` props passed into the `ControlPanel` → `BookmarkList` chain — wrap each in await + try/catch + failure toast)
- Test: `frontend/src/App.p4b1Gaps.test.tsx` (App harness)

**Interfaces:**
- Consumes: `bm.createCategory` / `bm.deleteCategory` from `useBookmarks` (both async, both `await refresh()` and can reject; `deleteCategory` does optimistic update + restore-on-failure + RE-THROW); `showToast`, `t`
- Produces: i18n keys `bm.cat.add_failed`, `bm.cat.delete_failed`

**Context (real current code):** `useBookmarks.createCategory` / `deleteCategory` are async and reject on backend failure (`deleteCategory` re-throws after restoring state). At the App wiring (the props passed into `ControlPanel`), the three handlers are fire-and-forget:
```tsx
          onCategoryAdd={(name: string) => {
            const palette = [...]
            const color = palette[Math.floor(Math.random() * palette.length)]
            bm.createCategory({ name, color })
          }}
          onCategoryDelete={(name: string) => {
            const cat = bm.categories.find(c => c.name === name)
            if (cat) bm.deleteCategory(cat.id)
          }}
          ...
          onCategoryDeleteCascade={(categoryId: string) =>
            bm.deleteCategory(categoryId, true)
          }
```
Note the EXACT shapes: `onCategoryAdd` takes a NAME and a random palette color; `onCategoryDelete` maps NAME → id via `bm.categories.find`; `onCategoryDeleteCascade` takes a category ID directly (NOT a name). A failed category add/delete leaves the panel silently reverted with NO toast. The fix mirrors the import flow (`handleBookmarkImport` wraps in try/catch + `showToast`). BEFORE editing, re-enumerate with `grep -n "onCategoryAdd\|onCategoryDelete\|onCategoryDeleteCascade\|createCategory\|deleteCategory" frontend/src/App.tsx` to confirm these are still the only three sites and that `deleteCategory` is async.

- [ ] **Step 1: Write the failing test** — add a test in the App-harness style of `App.p4b1Gaps.test.tsx` (MapView stubbed; `./services/api` built from the REAL export names via `importOriginal` with catch-all `async () => undefined` spies — so `api.createCategory` is already a `vi.fn`; real `createWsRouter()`; English strings via `localStorage 'locwarp.lang' = 'en'`). Force `api.createCategory` to reject and assert the failure toast text renders. The toast surface renders `{toastMsg}` as plain text, so it is assertable by its EN value `Add category failed: boom`:

```tsx
it('shows a failure toast when a category add rejects (U14)', async () => {
  // The harness mock makes api.createCategory a vi.fn(); force this call to reject.
  vi.mocked(api.createCategory).mockRejectedValueOnce(new Error('boom'));
  const router = createWsRouter();
  await act(async () => { renderApp(router); });
  // Trigger the App-level onCategoryAdd handler. RECOMMENDED (deterministic in
  // jsdom, no brittle navigation): give this test its OWN file that stubs
  // ControlPanel to surface the handler as a button — add at the top of the file:
  //   vi.mock('./components/ControlPanel', () => ({ default: (p: any) => (
  //     <button data-testid="cp-cat-add" onClick={() => p.onCategoryAdd?.('NewCat')} />
  //   ) }))
  // then drive it here:
  fireEvent.click(screen.getByTestId('cp-cat-add'));
  // (FALLBACK if you keep this in App.p4b1Gaps.test.tsx without the stub: open the
  //  category manager via the gear titled EN(bm.manage_categories), fireEvent.change
  //  the input with placeholder EN(bm.add_category) to 'NewCat', then click the button
  //  with text EN(bm.new_category) — read CategoryManagerPanel.tsx for exact labels.)
  await waitFor(() =>
    expect(screen.getByText(/Add category failed/i)).toBeInTheDocument(),
  );
});
```

IMPORTANT: this is the most brittle test in the cluster because reaching the category-add button requires driving the real open-library + category-manager UI. Read `frontend/src/components/CategoryManagerPanel.tsx` for the exact controls (placeholder `bm.add_category`, button `bm.new_category`) and how `BookmarkList`/`ControlPanel` toggle `showCategoryMgr` (the gear button titled `bm.manage_categories`). If the full click chain proves un-drivable in jsdom, the documented fallback is to assert the failure surfaces while STILL exercising a real user action (open category manager → add). Query by rendered EN text, not raw keys (harness mounts with `lang='en'`).

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/App.p4b1Gaps.test.tsx -t "category add rejects"`. Expected failure: no toast text found — the current handler does NOT await or catch the rejection, so an unhandled rejection occurs and no toast renders.

- [ ] **Step 3: Implement** — in `frontend/src/App.tsx`, wrap each of the three category handlers in await + try/catch + `showToast`, PRESERVING the exact existing argument shapes:

3a. Add i18n keys in `frontend/src/i18n/strings.ts` near the other `bm.cat.*` keys (search `'bm.cat.edit_title'`):
```ts
  'bm.cat.add_failed': { zh: '新增分類失敗:{error}', en: 'Add category failed: {error}' },
  'bm.cat.delete_failed': { zh: '刪除分類失敗:{error}', en: 'Delete category failed: {error}' },
```

3b. `onCategoryAdd` (keep the palette/color logic):
```tsx
          onCategoryAdd={async (name: string) => {
            const palette = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#3b82f6', '#6366f1', '#a855f7', '#ec4899', '#64748b']
            const color = palette[Math.floor(Math.random() * palette.length)]
            try {
              await bm.createCategory({ name, color })
            } catch (err: any) {
              showToast(t('bm.cat.add_failed', { error: err?.message || '' }))
            }
          }}
```

3c. `onCategoryDelete` (keep the NAME → id mapping):
```tsx
          onCategoryDelete={async (name: string) => {
            const cat = bm.categories.find(c => c.name === name)
            if (!cat) return
            try {
              await bm.deleteCategory(cat.id)
            } catch (err: any) {
              showToast(t('bm.cat.delete_failed', { error: err?.message || '' }))
            }
          }}
```

3d. `onCategoryDeleteCascade` (takes the category ID directly — do NOT add a name lookup):
```tsx
          onCategoryDeleteCascade={async (categoryId: string) => {
            try {
              await bm.deleteCategory(categoryId, true)
            } catch (err: any) {
              showToast(t('bm.cat.delete_failed', { error: err?.message || '' }))
            }
          }}
```
Do NOT change `useBookmarks` (its `deleteCategory` already does optimistic update + restore-on-failure + re-throw; the App layer just surfaces the re-thrown error as a toast). `showToast` + `t` are already in scope in App.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/App.p4b1Gaps.test.tsx`. Expected: the failure-toast test PASSES; the existing GAP tests still green.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/App.tsx frontend/src/i18n/strings.ts frontend/src/App.p4b1Gaps.test.tsx` then `git commit -m "feat(bookmark): await category mutations + toast on failure (SH2 U14)"`


---

### Task 19: Unify device cap: export MAX_DEVICES and raise the App add-device guard to 3

**Files:**
- Modify: `frontend/src/components/DeviceChipRow.tsx` (export `MAX_DEVICES`)
- Modify: `frontend/src/App.tsx` (the `onAdd` guard `if (device.connectedDevices.length >= 2)`)
- Test: `frontend/src/components/DeviceChipRow.test.tsx`

**Interfaces:**
- Consumes: none
- Produces: exported `MAX_DEVICES` constant from `DeviceChipRow.tsx`

**Context (real current code):** `DeviceChipRow.tsx` defines `const MAX_DEVICES = 3` (module-private) and shows the `+` button whenever `!atMax` i.e. `devices.length < MAX_DEVICES` (so at 2 devices the `+` is VISIBLE and inviting). But App's `onAdd` handler rejects early: `if (device.connectedDevices.length >= 2) { setToastMsg(t('device.max_reached')); return }` — so clicking `+` at 2 devices ALWAYS errors 'Maximum 3 devices connected' instead of opening the picker for the 3rd. The two numbers disagree (UI implies 3, guard caps at 2); the `device.max_reached` copy itself says 'Maximum 3 devices connected'. The other `>= 2` checks in App (`udids.length >= 2` in the gold-ditto / address-select / dual-device paths) are a DIFFERENT, CORRECT 'fan-out at 2+ devices' concern; DO NOT touch those. Only the `onAdd` cap is wrong. Per the SH2 finding, unify to `MAX_DEVICES` (3).

- [ ] **Step 1: Write the failing test** — add to `frontend/src/components/DeviceChipRow.test.tsx` (it has module-level `makeDevice`, `baseProps`, `emptyRuntimes`; already proves `+` hidden at 3 and shown at 1). Change the top import to also pull `MAX_DEVICES`, and add the assertions:

```tsx
import { DeviceChipRow, MAX_DEVICES } from './DeviceChipRow';

describe('DeviceChipRow device cap is unified at MAX_DEVICES (U18)', () => {
  it('exposes MAX_DEVICES === 3', () => {
    expect(MAX_DEVICES).toBe(3);
  });

  it('still shows the + add button at 2 connected devices (room for a 3rd)', () => {
    const props = baseProps();
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'One'), makeDevice('u2', 'Two')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    );
    expect(screen.getByText('+')).toBeInTheDocument();
    expect(screen.getByTitle('device.add_device')).toBeInTheDocument();
  });
});
```

The existing top import is `import { DeviceChipRow } from './DeviceChipRow'` — change it to `import { DeviceChipRow, MAX_DEVICES } from './DeviceChipRow'`. Until the constant is exported, this import resolves `MAX_DEVICES` to `undefined`, so `expect(MAX_DEVICES).toBe(3)` FAILS (the failing state).

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/DeviceChipRow.test.tsx -t "device cap is unified"`. Expected failure: `expected undefined to be 3` (constant is module-private today, so the named import is `undefined`).

- [ ] **Step 3: Implement** —

3a. In `frontend/src/components/DeviceChipRow.tsx`, change:
```tsx
const MAX_DEVICES = 3
```
to:
```tsx
export const MAX_DEVICES = 3
```

3b. In `frontend/src/App.tsx`, import the constant alongside the existing component import (currently `import { DeviceChipRow } from './components/DeviceChipRow'`):
```tsx
import { DeviceChipRow, MAX_DEVICES } from './components/DeviceChipRow'
```

3c. In the `onAdd` guard, change:
```tsx
          onAdd={() => {
            if (device.connectedDevices.length >= 2) {
              setToastMsg(t('device.max_reached'))
              return
            }
            device.scan()
          }}
```
to use the shared cap:
```tsx
          onAdd={() => {
            if (device.connectedDevices.length >= MAX_DEVICES) {
              setToastMsg(t('device.max_reached'))
              return
            }
            device.scan()
          }}
```
Leave every unrelated `udids.length >= 2` fan-out check UNCHANGED.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/DeviceChipRow.test.tsx`. Expected: all DeviceChipRow tests PASS (incl. the existing 'hides the add button entirely at max (3)' which still holds).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/components/DeviceChipRow.tsx frontend/src/App.tsx frontend/src/components/DeviceChipRow.test.tsx` then `git commit -m "fix(device): unify add-device cap at MAX_DEVICES=3 (SH2 U18)"`


---

### Task 20: Replace stray native alert() in waypoint generation with showToast

**Files:**
- Modify: `frontend/src/App.tsx` (`generateWaypoints`, the `alert(t('toast.no_position_random'))`)
- Test: `frontend/src/App.p4b1Gaps.test.tsx` (App harness)

**Interfaces:**
- Consumes: existing `showToast` + key `toast.no_position_random`
- Produces: none

**Context (real current code):** `generateWaypoints` guards `if (!sim.currentPosition) { alert(t('toast.no_position_random')); return }`. The key name is `toast.*` — it was always meant for the toast surface (the sibling path `useSimActions.ts` already does `showToast(t('toast.no_position_random'))`). The native `alert()` is a blocking, off-brand modal. `showToast` is already in scope in App (`const { toastMsg, showToast, setToastMsg } = useToast()`), and the toast slot renders `{toastMsg}` plain text (the `{toastMsg && (...)}` block), so it is assertable. The `generateWaypoints` `useCallback` dep array is currently `[sim, t]` — adding `showToast` is required.

- [ ] **Step 1: Write the failing test** — add to `frontend/src/App.p4b1Gaps.test.tsx` (App harness, English strings). The generate-random-waypoints button lives in `WaypointEditor` (its `t('panel.waypoints_generate')` button fires `onGenerateRandomWaypoints` → `generateWaypoints`). With the default harness there is no `currentPosition`, so the guard fires. Spy on `window.alert` and assert it is NOT called, while the toast text IS shown:

```tsx
it('uses a toast (not a native alert) when generating waypoints with no position (U26)', async () => {
  const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
  const router = createWsRouter();
  await act(async () => { renderApp(router); });

  // Reach the route-mode WaypointEditor (only mounted in SimMode.Loop/MultiStop via
  // modeExtraSection) and click its generate button. RECOMMENDED (deterministic):
  // give this test its OWN file that stubs ControlPanel to expose a mode-switch
  // button AND render modeExtraSection — add at the top of the file:
  //   vi.mock('./components/ControlPanel', () => ({ default: (p: any) => (<>
  //     <button data-testid="cp-mode-loop" onClick={() => p.onModeChange?.('loop')} />
  //     {p.modeExtraSection}
  //   </>) }))
  // then drive it here:
  fireEvent.click(screen.getByTestId('cp-mode-loop'));
  fireEvent.click(screen.getByText('Generate waypoints'));  // EN of panel.waypoints_generate — confirm the exact label in strings.ts
  // (FALLBACK if you keep this in App.p4b1Gaps.test.tsx without the stub: switch to a
  //  loop/multi-stop mode via the real mode control App renders — grep onModeChange /
  //  SimMode.Loop — then click the generate button per WaypointEditor.test.tsx.)

  expect(alertSpy).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(
      screen.getByText('No current position, cannot generate random waypoints'),
    ).toBeInTheDocument(),
  );
  alertSpy.mockRestore();
});
```

Read `frontend/src/components/WaypointEditor.tsx` (the `t('panel.waypoints_generate')` button) and `frontend/src/components/WaypointEditor.test.tsx` to confirm the exact generate-button label; the concrete mode-switch + generate-click is already written in the Step 1 test above (the ControlPanel-stub recipe). The WaypointEditor is gated behind a route mode (`modeExtraSection` renders only in `SimMode.Loop` / `SimMode.MultiStop`), so switch modes first. The English value for `toast.no_position_random` is `'No current position, cannot generate random waypoints'` (strings.ts line 535). If the mode-switch chain proves un-drivable in jsdom, the documented fallback is to assert the no-alert + toast behavior while still exercising a real generate action.

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/App.p4b1Gaps.test.tsx -t "not a native alert"`. Expected failure: `expected "alert" not to have been called` (current code calls `window.alert`), and the toast text is not found.

- [ ] **Step 3: Implement** — in `frontend/src/App.tsx`, `generateWaypoints` currently:
```tsx
  const generateWaypoints = useCallback((radius: number, count: number) => {
    if (!sim.currentPosition) {
      alert(t('toast.no_position_random'))
      return
    }
```
Replace the `alert(...)` with the toast:
```tsx
  const generateWaypoints = useCallback((radius: number, count: number) => {
    if (!sim.currentPosition) {
      showToast(t('toast.no_position_random'))
      return
    }
```
Then update the `useCallback` dependency array (currently `}, [sim, t])`) to include `showToast`:
```tsx
  }, [sim, t, showToast])
```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/App.p4b1Gaps.test.tsx`. Expected: alert NOT called; toast text rendered.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) and `npx vitest run` (green).

- [ ] **Step 6: Commit** — `git add frontend/src/App.tsx frontend/src/App.p4b1Gaps.test.tsx` then `git commit -m "fix(app): toast instead of native alert on no-position waypoint gen (SH2 U26)"`


---

<!-- ===== Acceptance + manual smoke ===== -->

### Task 21: SH2 acceptance — full frontend gate + manual smoke

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-20
- Produces: none

- [ ] **Step 1: Full frontend gate**

```bash
cd /Users/raviwu/personal/locwarp/frontend
npx tsc --noEmit
npx vitest run
npx depcruise src
```
Expected: tsc 0 errors; vitest all green (664 baseline + the SH2 tests added by Tasks 1-20; count only grew); depcruise 0 errors.

- [ ] **Step 2: Manual smoke — delete guards (U13)**

Run `cd frontend && npm run start`. Right-click a bookmark -> Delete; right-click a route -> Delete.
- Expected: a confirm prompt each time; Cancel keeps the item. (Before: single-delete executed instantly; bookmark delete failed silently.)

- [ ] **Step 3: Manual smoke — dead Start + joystick guard (U6)**

Open the app (default Teleport mode).
- Expected: the centered green Transport **Start is hidden/disabled** (not a silent no-op). Switch to Joystick with no position set, press Start -> a **"no position" toast**.

- [ ] **Step 4: Manual smoke — connect + teleport feedback (U1, U7, U8)**

No device connected: the Map Transport **Start is disabled** (U8). Open the device dropdown, pick a device that fails to connect -> a **toast** (U1). With a device, force a teleport failure -> a **toast** (U7).

- [ ] **Step 5: Manual smoke — reconnect transition (U3)** *(real iPhone)*

Unplug the USB cable mid-simulation.
- Expected: an **amber "reconnecting…"** state first, red only after the watchdog gives up.

- [ ] **Step 6: Manual smoke — paused + overrides + inline errors (U9, U10, U11, U15)**

Pause a running route -> ETA bar shows **"Paused"** + dimmed progress (U9). Set a speed range with a custom fixed speed -> **"range overrides custom"** hint/dim (U10). Open GoldDitto with an empty B -> a **one-line inline reason** under the disabled ② (U11). In Custom/Edit bookmark, enter an out-of-range coord and submit -> an **inline red error** (U15).

- [ ] **Step 7: Manual smoke — spot-check the rest**

U2 (WiFi auto-connect failure toasts), U4/U5 (a forgotten/trust-required device stays visibly reachable), U12 (a failed dual-device teleport doesn't leave the marker moved), U14 (import label busy state; a failed category add toasts), U16/U17 (left-click teleport gated on a connected device + signals it moves real GPS), U18 ('+' add-device consistent with the real cap), U26 (no-position waypoint path shows a toast, not a native alert).

**SH2 acceptance:** frontend gate green (Step 1) with the new tests; manual smoke Steps 2-7 observed and evidenced (Steps 2-4, 6-7 single-device; Step 5 needs a real iPhone).
