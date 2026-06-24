import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent } from '@testing-library/react'

// ─────────────────────────────────────────────────────────────────────────────
// DANGER-ZONE CHARACTERIZATION (Phase 4b, task p4b1).
//
// Pins the behavior of App.tsx's sim-action handlers (handleStart/Stop/Teleport
// and friends) and handleMapClick BEFORE decomposition. These handlers are the
// fan-out single-vs-dual branch and the deliberate go-around-sim.teleport paths
// that Tasks 9-10 will extract; if an extraction changes which api endpoint is
// called, whether a udid is attached, the toast string, or the waypoint mutation
// shape, these go red.
//
// HOW WE OBSERVE REAL BEHAVIOR:
//   - api functions are spied (vi.fn). The single-device sim methods call the
//     api endpoint WITHOUT a udid (e.g. api.stopSim()); the *All fan-out passes
//     a udid per device (api.stopSim('A')). So the presence/absence of a udid
//     arg is the load-bearing signal for "single-device variant vs *All".
//   - Exact toast strings: the dual path calls showToast(toastForFanout(...));
//     we assert the resolved English string in the DOM toast.
//   - MapView + ControlPanel are stubbed to test-doubles that surface the action
//     props as buttons and expose sim-derived state (waypoints, mode-gated flags)
//     as data-* attributes so we can assert mutations.
//
// HARNESS for 2 connected devices: dispatch device_connected WS frames through
// an injected real createWsRouter(); useDevice re-fetches via listDevices()
// (mocked to return 2 connected devices), populating connectedDevices.length>=2.
// ─────────────────────────────────────────────────────────────────────────────

// ── MapView test-double: surfaces map-side callbacks + sim-derived props ──────
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(props: any, _ref: any) {
    return (
      <div
        data-testid="mapview"
        data-show-bulk-paste={props.showBulkPasteOnMap ? '1' : '0'}
        data-show-waypoint-option={props.showWaypointOption ? '1' : '0'}
        data-waypoints={JSON.stringify(props.waypoints ?? [])}
        data-device-count={(props.devices ?? []).length}
      >
        <button data-testid="map-click" onClick={() => props.onMapClick(25.05, 121.55)} />
        <button data-testid="map-start" onClick={() => props.onStart?.()} />
        <button data-testid="map-stop" onClick={() => props.onStop?.()} />
        <button data-testid="map-teleport" onClick={() => props.onTeleport?.(10, 20)} />
        <button data-testid="map-insert-after-1" onClick={() => props.onInsertAfterWp?.(1)} />
        <button data-testid="map-open-bulk-paste" onClick={() => props.onBulkPasteOpen?.()} />
      </div>
    )
  }),
}))

// ── ControlPanel test-double: surfaces transport + click-to-add toggle ────────
vi.mock('./components/ControlPanel', () => ({
  default: function ControlPanelStub(props: any) {
    return (
      <div data-testid="controlpanel">
        <button data-testid="cp-start" onClick={() => props.onStart()} />
        <button data-testid="cp-stop" onClick={() => props.onStop()} />
        <button data-testid="cp-click-to-add-on" onClick={() => props.onClickToAddWaypointChange(true)} />
        <button data-testid="cp-mode-joystick" onClick={() => props.onModeChange('joystick')} />
        <button data-testid="cp-mode-loop" onClick={() => props.onModeChange('loop')} />
      </div>
    )
  },
}))

// ── api: spy the endpoints the handlers funnel into; inert stubs elsewhere ─────
vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  // Endpoints we assert on — fresh spies so call args are inspectable.
  const spied = new Set([
    'teleport', 'navigate', 'startLoop', 'multiStop', 'randomWalk',
    'joystickStart', 'joystickStop', 'stopSim', 'pauseSim', 'resumeSim',
    'insertWaypoint',
  ])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (spied.has(key)) {
      out[key] = vi.fn(async () => ({ ok: true }))
    } else if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus') {
      out[key] = async () => ({})
    } else if (key === 'getStatus') {
      out[key] = vi.fn(async () => ({}))
    } else if (key === 'listDevices') {
      // Default: no devices. Individual tests override via vi.mocked(...).
      out[key] = vi.fn(async () => [])
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

const DEV = (udid: string) => ({
  udid, name: udid, ios_version: '17.0', connection_type: 'USB', is_connected: true,
})

function renderApp(router: WsRouterImpl) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected: true }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

// Bring connectedDevices up to `udids` by faking listDevices + dispatching a
// device_connected frame (useDevice re-fetches on the frame). Returns when
// the MapView stub reflects the new device count.
async function connectDevices(router: WsRouterImpl, udids: string[]) {
  vi.mocked(api.listDevices).mockResolvedValue(udids.map(DEV) as any)
  await act(async () => {
    for (const u of udids) router.dispatch({ type: 'device_connected', udid: u })
  })
  // Flush the listDevices().then(...) microtask chain.
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}

beforeEach(() => {
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  vi.clearAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
})

// ════════════════════════════════════════════════════════════════════════════
// Sim fan-out: single device vs dual device
// ════════════════════════════════════════════════════════════════════════════
describe('sim action fan-out (single vs dual device)', () => {
  it('Start in default Teleport mode is a no-op for transport (pins the mode gate)', async () => {
    // handleStart only acts for Joystick / RandomWalk / Loop / MultiStop. In the
    // default Teleport mode none of those branches fire — no api call. This pins
    // the gate so an extraction can't accidentally make Start always-fire.
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => { fireEvent.click(screen.getByTestId('cp-start')) })
    expect(api.joystickStart).not.toHaveBeenCalled()
    expect(api.startLoop).not.toHaveBeenCalled()
    expect(api.randomWalk).not.toHaveBeenCalled()
  })

  it('single device: Start in Joystick mode calls api.joystickStart WITHOUT a udid', async () => {
    // Seed a current position via getStatus so the Joystick no-position guard passes.
    vi.mocked(api.getStatus).mockResolvedValueOnce({ position: { lat: 25.05, lng: 121.55 } } as any)
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    // Flush the async getStatus().then(...) microtask chain so currentPosition is set.
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    await connectDevices(router, ['A'])
    // Put the sim in Joystick mode via the ControlPanel mode-change button.
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-joystick')) })

    await act(async () => { fireEvent.click(screen.getByTestId('cp-start')) })

    expect(api.joystickStart).toHaveBeenCalledTimes(1)
    // Single-device variant: api.joystickStart(moveMode) — NOTE the 1st arg is the
    // MOVE mode ('walking' default), not the SimMode; 2nd arg (udid) absent.
    const call = vi.mocked(api.joystickStart).mock.calls[0]
    expect(call[0]).toBe('walking')
    expect(call[1]).toBeUndefined()
  })

  it('dual device: Start in Joystick mode fans out per-udid AND toasts the fan-out summary', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A', 'B'])
    // Seed a current position via teleport (sim.teleport calls setCurrentPosition internally)
    // so the Joystick no-position guard passes.
    await act(async () => { fireEvent.click(screen.getByTestId('map-teleport')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    // Put the sim in Joystick mode via the ControlPanel mode-change button.
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-joystick')) })

    await act(async () => { fireEvent.click(screen.getByTestId('cp-start')) })
    // preSyncStart has a 150ms settle delay for dual-device pre-teleport;
    // wait enough real time for it to resolve before asserting.
    await act(async () => { await new Promise((r) => setTimeout(r, 200)) })

    // joystickStartAll → one api.joystickStart per connected udid, WITH the udid.
    expect(api.joystickStart).toHaveBeenCalledTimes(2)
    const udids = vi.mocked(api.joystickStart).mock.calls.map((c) => c[1]).sort()
    expect(udids).toEqual(['A', 'B'])
    // toastForFanout (all OK) → t('group.action_all_success', {action: t('mode.joystick')}).
    expect(screen.getByText('Joystick started on all devices')).toBeInTheDocument()
  })

  it('single device: Stop calls api.stopSim WITHOUT a udid', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => { fireEvent.click(screen.getByTestId('cp-stop')) })

    expect(api.stopSim).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.stopSim).mock.calls[0][0]).toBeUndefined()
  })

  it('dual device: Stop fans out api.stopSim per-udid AND toasts the literal "stop" action', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A', 'B'])

    await act(async () => { fireEvent.click(screen.getByTestId('cp-stop')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(api.stopSim).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.stopSim).mock.calls.map((c) => c[0]).sort()).toEqual(['A', 'B'])
    // handleStop dual passes the LITERAL string 'stop' (not a t() key) as action.
    expect(screen.getByText('stop started on all devices')).toBeInTheDocument()
  })

  it('single device: Teleport (map menu) calls api.teleport WITHOUT a udid', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => { fireEvent.click(screen.getByTestId('map-teleport')) })

    expect(api.teleport).toHaveBeenCalledTimes(1)
    const call = vi.mocked(api.teleport).mock.calls[0]
    expect(call[0]).toBe(10) // lat
    expect(call[1]).toBe(20) // lng
    expect(call[2]).toBeUndefined() // udid absent → single-device sim.teleport
  })

  it('dual device: Teleport fans out api.teleport per-udid AND toasts the fan-out summary', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A', 'B'])

    await act(async () => { fireEvent.click(screen.getByTestId('map-teleport')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    // teleportAll → one api.teleport per udid, WITH the udid as 3rd arg.
    expect(api.teleport).toHaveBeenCalledTimes(2)
    const calls = vi.mocked(api.teleport).mock.calls
    for (const c of calls) { expect(c[0]).toBe(10); expect(c[1]).toBe(20) }
    expect(calls.map((c) => c[2]).sort()).toEqual(['A', 'B'])
    expect(screen.getByText('Teleport started on all devices')).toBeInTheDocument()
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Go-around-sim.teleport path: route-paste submit
// ════════════════════════════════════════════════════════════════════════════
describe('go-around-sim.teleport: route-paste submit', () => {
  // submitRoutePaste deliberately bypasses sim.teleport (which flips mode→Teleport
  // and wipes waypoints): single-device sets currentPosition + waypoints only;
  // dual-device uses sim.teleportAll (raw api.teleport per udid). Either way the
  // user's Loop/MultiStop mode must SURVIVE (showBulkPasteOnMap stays true) and
  // the waypoint list becomes exactly the pasted coords.
  async function openAndSubmitRoutePaste(router: WsRouterImpl, text: string) {
    // Put sim in Loop mode so showBulkPasteOnMap would be true (and we can
    // detect a mode-flip-to-Teleport as showBulkPasteOnMap going false).
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-loop')) })
    // Open the route-paste modal via the MapView-surfaced callback.
    await act(async () => { fireEvent.click(screen.getByTestId('map-open-bulk-paste')) })
    const textarea = document.querySelector('textarea') as HTMLTextAreaElement
    expect(textarea).not.toBeNull()
    await act(async () => { fireEvent.change(textarea, { target: { value: text } }) })
    // Submit button label: `${t('panel.route_paste_submit')} (${valid.length})`.
    const submit = screen.getByRole('button', { name: /\(2\)$/ })
    await act(async () => { fireEvent.click(submit) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
  }

  it('single device: sets waypoints to the pasted coords, keeps Loop mode, never calls sim.teleport endpoint with no udid', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await openAndSubmitRoutePaste(router, '25.05 121.55\n25.06 121.56')

    // Mode survived (Loop) → showBulkPasteOnMap still true. If submitRoutePaste
    // had gone through sim.teleport, mode would have flipped to Teleport and this
    // flag would be '0'.
    const mv = screen.getByTestId('mapview')
    expect(mv.getAttribute('data-show-bulk-paste')).toBe('1')

    // Waypoints became exactly the pasted coords. NOTE: parseRoutePaste runs lng
    // through normalizeLng (mod-360), so 121.55 → 121.5499999…; assert close.
    const wps = JSON.parse(mv.getAttribute('data-waypoints') ?? '[]')
    expect(wps).toHaveLength(2)
    expect(wps[0].lat).toBe(25.05)
    expect(wps[0].lng).toBeCloseTo(121.55, 6)
    expect(wps[1].lat).toBe(25.06)
    expect(wps[1].lng).toBeCloseTo(121.56, 6)

    // NOTE: submitRoutePaste gates the start-point teleport on `udids.length > 0`
    // (NOT `>= 2` like handleTeleport). So even with ONE connected device it
    // teleports the start point via sim.teleportAll → raw api.teleport WITH the
    // udid. Crucially it goes through teleportAll (raw api), never the single-
    // device sim.teleport that would flip mode→Teleport + wipe waypoints.
    expect(api.teleport).toHaveBeenCalledTimes(1)
    const tcall = vi.mocked(api.teleport).mock.calls[0]
    expect(tcall[0]).toBe(25.05)
    expect(tcall[1] as number).toBeCloseTo(121.55, 6)
    expect(tcall[2]).toBe('A') // udid present → went through teleportAll, not sim.teleport
  })

  it('dual device: teleports the start point per-udid (raw api.teleport) and still keeps Loop mode + sets waypoints', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A', 'B'])
    // Put sim in Loop mode via the ControlPanel mode-change button.
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-loop')) })

    // Open + submit (mode already loop from above; re-click inside helper is harmless/idempotent).
    await act(async () => { fireEvent.click(screen.getByTestId('map-open-bulk-paste')) })
    const textarea = document.querySelector('textarea') as HTMLTextAreaElement
    await act(async () => { fireEvent.change(textarea, { target: { value: '25.05 121.55\n25.06 121.56' } }) })
    const submit = screen.getByRole('button', { name: /\(2\)$/ })
    await act(async () => { fireEvent.click(submit) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    // Start point teleported to BOTH devices via teleportAll (raw api.teleport
    // WITH a udid) — NOT via the single-device sim.teleport.
    expect(api.teleport).toHaveBeenCalledTimes(2)
    const calls = vi.mocked(api.teleport).mock.calls
    for (const c of calls) { expect(c[0]).toBe(25.05); expect(c[1] as number).toBeCloseTo(121.55, 6) }
    expect(calls.map((c) => c[2]).sort()).toEqual(['A', 'B'])

    // Mode survived Loop; waypoints set to pasted coords.
    const mv = screen.getByTestId('mapview')
    expect(mv.getAttribute('data-show-bulk-paste')).toBe('1')
    expect(JSON.parse(mv.getAttribute('data-waypoints') ?? '[]')).toHaveLength(2)
  })
})

// ════════════════════════════════════════════════════════════════════════════
// handleMapClick three modes
// ════════════════════════════════════════════════════════════════════════════
describe('handleMapClick modes', () => {
  // Seed waypoints into useSimulation via a simulation_state frame, then assert
  // through the MapView stub's data-waypoints.
  function readWaypoints(): any[] {
    return JSON.parse(screen.getByTestId('mapview').getAttribute('data-waypoints') ?? '[]')
  }

  it('(a) insert-after branch is currently UNREACHABLE: App never wires onInsertAfterWp, so a map click cannot arm/splice via the UI', async () => {
    // GAP (reported): handleMapClick's first branch (insertAfterIndex !== null →
    // splice at idx+1 + live-insert api.insertWaypoint fan-out) is real code, but
    // App.tsx defines handleInsertAfterWp and NEVER passes it to <MapView> (no
    // `onInsertAfterWp=` anywhere in the codebase). setInsertAfterIndex is reached
    // only by handleInsertAfterWp (unwired) and cancel/ESC. So insert mode cannot
    // be armed from the UI today, and this branch is dead from the user's view.
    //
    // We pin that REALITY: (1) MapView receives onInsertAfterWp === undefined, and
    // (2) absent arming, a Loop-mode map click (toggle off) is a no-op — the
    // splice branch never runs. A later extraction that WIRES this prop would be a
    // behavior change and should update this characterization deliberately.
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    // Put sim in Loop mode via the ControlPanel mode-change button.
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-loop')) })

    // Triggering the surfaced onInsertAfterWp button is a no-op because App passes
    // undefined for that prop (the stub's optional-chain swallows the call), so no
    // insert banner appears.
    await act(async () => { fireEvent.click(screen.getByTestId('map-insert-after-1')) })
    expect(
      screen.queryByText((content) => content.includes('inserted after')),
    ).not.toBeInTheDocument()

    // A subsequent map click therefore takes the default (toggle-off) no-op path —
    // the splice branch never runs, waypoints unchanged, no live-insert fan-out.
    await act(async () => { fireEvent.click(screen.getByTestId('map-click')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    // No waypoints were seeded; the splice branch never runs, so count stays 0.
    expect(readWaypoints()).toHaveLength(0)
    expect(api.insertWaypoint).not.toHaveBeenCalled()
  })

  it('(b) click-to-add toggle ON + waypoint mode: a map click appends a waypoint', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    // Loop mode, NOT running.
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-loop')) })
    // Turn the click-to-add toggle on (ControlPanel-surfaced callback).
    await act(async () => { fireEvent.click(screen.getByTestId('cp-click-to-add-on')) })

    await act(async () => { fireEvent.click(screen.getByTestId('map-click')) })

    // No pre-seeded waypoints; clicking once adds 1 waypoint (click-to-add toggle ON).
    const wps = readWaypoints()
    expect(wps).toHaveLength(1)
    // normalizeLng float: 121.55 → 121.5499999…
    expect(wps[0].lat).toBe(25.05)
    expect(wps[0].lng).toBeCloseTo(121.55, 6)
    // No teleport/insert side effects in this branch.
    expect(api.teleport).not.toHaveBeenCalled()
    expect(api.insertWaypoint).not.toHaveBeenCalled()
  })

  it('(c) default (no insert mode, toggle OFF): a map click is a no-op', async () => {
    // NOTE: the prompt described the default as "teleport/preview", but the CURRENT
    // handleMapClick default is a NO-OP — left-click does nothing; teleport/preview
    // live on the right-click menu (onTeleport/onCoordPreview), NOT onMapClick.
    // We pin the real no-op behavior. See REPORT for this discrepancy.
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    // Loop mode so showWaypointOption is true.
    await act(async () => { fireEvent.click(screen.getByTestId('cp-mode-loop')) })

    // No insert armed, toggle OFF (default).
    await act(async () => { fireEvent.click(screen.getByTestId('map-click')) })

    // Waypoints unchanged (no pre-seeded waypoints, no click-to-add); no api side effects.
    expect(readWaypoints()).toHaveLength(0)
    expect(api.teleport).not.toHaveBeenCalled()
    expect(api.insertWaypoint).not.toHaveBeenCalled()
  })
})
