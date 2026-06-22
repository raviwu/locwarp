import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { SimMode } from './useSimulation'
import { useMapClick, type UseMapClickArgs } from './useMapClick'

// ─────────────────────────────────────────────────────────────────────────────
// SUPPLEMENTARY unit coverage for the extracted map-click hook. This does NOT
// replace App.dangerzone.test.tsx tests 13-15 (the rendered characterization
// net) — it pins the same three branches directly at the hook boundary so a
// future refactor of the hook internals is caught here too. Behavior is FROZEN.
//
//   (a) insert-after branch is UNREACHABLE from App because onInsertAfterWp is
//       never wired — but the hook code itself IS exercised here (we arm it via
//       the returned handleInsertAfterWp) to prove the splice + live-insert
//       fan-out it moved verbatim still works. App keeping it dead is what
//       test 13 pins; this asserts the moved code is correct when reached.
//   (b) click-to-add toggle ON + Loop/MultiStop → a click appends a waypoint.
//   (c) default (no insert armed, toggle OFF) → pure NO-OP.
//
// `api.insertWaypoint` is a vi.fn so we can assert the dead branch's fan-out
// shape. sim.setWaypoints is captured + applied against a held list so we can
// read the resulting waypoints.
// ─────────────────────────────────────────────────────────────────────────────

function makeSim(opts: { mode?: SimMode; running?: boolean; currentPosition?: { lat: number; lng: number } | null; waypoints?: any[] } = {}) {
  let wps: any[] = opts.waypoints ?? []
  return {
    mode: opts.mode ?? SimMode.Loop,
    currentPosition: opts.currentPosition === undefined ? { lat: 1, lng: 2 } : opts.currentPosition,
    status: { running: opts.running ?? false },
    get waypoints() { return wps },
    setWaypoints: vi.fn((updater: any) => {
      wps = typeof updater === 'function' ? updater(wps) : updater
    }),
  }
}

function setup(opts: {
  sim?: any
  udids?: string[]
  clickToAddWaypoint?: boolean
} = {}) {
  const sim = opts.sim ?? makeSim()
  const device = { connectedDevices: (opts.udids ?? ['A']).map((udid) => ({ udid })) }
  const insertWaypoint = vi.fn(
    async (_after: number, _lat: number, _lng: number, _udid?: string) => ({ ok: true }),
  )
  const api = { insertWaypoint } as unknown as ApiGateway
  const args: UseMapClickArgs = {
    sim,
    device,
    api,
    clickToAddWaypoint: opts.clickToAddWaypoint ?? false,
    // Identity-ish normalisers so coords pass through; the real normalizeLng
    // float behavior is pinned by App.dangerzone.test.tsx, not here.
    clampLat: (lat) => lat,
    normalizeLng: (lng) => lng,
  }
  const { result, rerender } = renderHook((p: UseMapClickArgs) => useMapClick(p), { initialProps: args })
  return { result, rerender, sim, device, insertWaypoint, args }
}

beforeEach(() => { vi.clearAllMocks() })

describe('useMapClick — (a) insert-after branch (DEAD from App; wired here to exercise moved code)', () => {
  it('is unreachable until armed: a plain click with insert NOT armed runs no splice/fan-out', () => {
    // Mirrors test 13's reality — without arming, the click takes the default
    // path. Here toggle is OFF so it is a no-op; insertWaypoint never fires.
    const sim = makeSim({ mode: SimMode.Loop, running: true, waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }, { lat: 3, lng: 3 }] })
    const { result, insertWaypoint } = setup({ sim, udids: ['A'] })
    act(() => { result.current.handleMapClick(25.05, 121.55) })
    expect(sim.waypoints).toHaveLength(3)
    expect(insertWaypoint).not.toHaveBeenCalled()
  })

  it('once armed: splices a waypoint after the index, clears the mode (one-shot), and live-inserts per-udid when running', () => {
    const sim = makeSim({ mode: SimMode.Loop, running: true, waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }, { lat: 3, lng: 3 }] })
    const { result, insertWaypoint } = setup({ sim, udids: ['A', 'B'] })

    act(() => { result.current.handleInsertAfterWp(1) })
    expect(result.current.insertAfterIndex).toBe(1)

    act(() => { result.current.handleMapClick(25.05, 121.55) })

    // Spliced after index 1 → new wp at position 2; list grows to 4.
    expect(sim.waypoints).toHaveLength(4)
    expect(sim.waypoints[2]).toEqual({ lat: 25.05, lng: 121.55 })
    // Live-insert fan-out: one api.insertWaypoint per connected udid, WITH udid.
    expect(insertWaypoint).toHaveBeenCalledTimes(2)
    expect(insertWaypoint.mock.calls.map((c) => c[3]).sort()).toEqual(['A', 'B'])
    for (const c of insertWaypoint.mock.calls) {
      expect(c[0]).toBe(1); expect(c[1]).toBe(25.05); expect(c[2]).toBe(121.55)
    }
    // One-shot: mode cleared after the splice.
    expect(result.current.insertAfterIndex).toBeNull()
  })

  it('armed but NOT running: splices locally but fires no live-insert fan-out', () => {
    const sim = makeSim({ mode: SimMode.Loop, running: false, waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }] })
    const { result, insertWaypoint } = setup({ sim, udids: ['A'] })
    act(() => { result.current.handleInsertAfterWp(0) })
    act(() => { result.current.handleMapClick(9, 9) })
    expect(sim.waypoints).toHaveLength(3)
    expect(insertWaypoint).not.toHaveBeenCalled()
  })
})

describe('useMapClick — (b) click-to-add toggle ON + waypoint mode', () => {
  it('appends a waypoint to the existing list', () => {
    const sim = makeSim({ mode: SimMode.Loop, waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }] })
    const { result, insertWaypoint } = setup({ sim, clickToAddWaypoint: true })
    act(() => { result.current.handleMapClick(25.05, 121.55) })
    expect(sim.waypoints).toHaveLength(3)
    expect(sim.waypoints[2]).toEqual({ lat: 25.05, lng: 121.55 })
    expect(insertWaypoint).not.toHaveBeenCalled()
  })

  it('seeds the current position as index 0 on the first add (empty list)', () => {
    const sim = makeSim({ mode: SimMode.MultiStop, currentPosition: { lat: 5, lng: 6 }, waypoints: [] })
    const { result } = setup({ sim, clickToAddWaypoint: true })
    act(() => { result.current.handleMapClick(25.05, 121.55) })
    expect(sim.waypoints).toEqual([{ lat: 5, lng: 6 }, { lat: 25.05, lng: 121.55 }])
  })

  it('is a no-op outside Loop/MultiStop even with the toggle ON', () => {
    const sim = makeSim({ mode: SimMode.Teleport, waypoints: [{ lat: 1, lng: 1 }] })
    const { result } = setup({ sim, clickToAddWaypoint: true })
    act(() => { result.current.handleMapClick(25.05, 121.55) })
    expect(sim.waypoints).toHaveLength(1)
  })
})

describe('useMapClick — (c) default (no insert armed, toggle OFF)', () => {
  it('a map click is a pure no-op: no waypoint mutation, no api side effects', () => {
    const sim = makeSim({ mode: SimMode.Loop, waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }] })
    const { result, insertWaypoint } = setup({ sim, clickToAddWaypoint: false })
    act(() => { result.current.handleMapClick(25.05, 121.55) })
    expect(sim.waypoints).toHaveLength(2)
    expect(sim.setWaypoints).not.toHaveBeenCalled()
    expect(insertWaypoint).not.toHaveBeenCalled()
  })
})

describe('useMapClick — ESC cancels insert mode', () => {
  it('pressing Escape while armed clears insertAfterIndex', () => {
    const { result } = setup({})
    act(() => { result.current.handleInsertAfterWp(2) })
    expect(result.current.insertAfterIndex).toBe(2)
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
    expect(result.current.insertAfterIndex).toBeNull()
  })

  it('cancelInsertMode clears the armed index', () => {
    const { result } = setup({})
    act(() => { result.current.handleInsertAfterWp(0) })
    expect(result.current.insertAfterIndex).toBe(0)
    act(() => { result.current.cancelInsertMode() })
    expect(result.current.insertAfterIndex).toBeNull()
  })
})
