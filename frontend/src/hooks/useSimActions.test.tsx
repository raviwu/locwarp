import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { SimMode } from './useSimulation'
import { useSimActions, type UseSimActionsArgs } from './useSimActions'

// ─────────────────────────────────────────────────────────────────────────────
// SUPPLEMENTARY unit coverage for the extracted fan-out hook. This does NOT
// replace App.dangerzone.test.tsx (the rendered characterization net) — it pins
// the same single-vs-dual branch directly at the hook boundary, plus the literal
// action strings, so a future refactor of the hook internals is caught here too.
//
// The `sim` object is a bag of vi.fn()s: the SINGLE-device variant calls the
// legacy method (sim.teleport / sim.stop / …) WITHOUT a udid; the *All variant
// calls sim.<x>All(udids, …). Asserting which method ran (and with what args) is
// the load-bearing signal — exactly mirroring how the dangerzone test reads the
// presence/absence of a udid on the spied api endpoints.
// ─────────────────────────────────────────────────────────────────────────────

// Minimal i18n stub that reproduces the real interpolation for the two keys the
// toast path resolves, so the literal action strings ('stop' / 'pause' / …) come
// through verbatim — pinning nuance #5 ("stop started on all devices").
const t = ((k: any, v?: Record<string, string | number>) => {
  if (k === 'group.action_all_success') return `${v?.action} started on all devices`
  if (k === 'group.action_all_failed') return `${v?.action} failed on all devices`
  // mode.* / panel.* keys: echo a stable label so toastForFanout's action arg
  // (which is itself a t('mode.x') result) is deterministic.
  const map: Record<string, string> = {
    'mode.teleport': 'Teleport',
    'mode.navigate': 'Navigate',
    'mode.joystick': 'Joystick',
    'mode.random_walk': 'RandomWalk',
    'mode.loop': 'Loop',
    'mode.multi_stop': 'MultiStop',
    'panel.apply_speed_success': 'ApplySpeed OK',
    'panel.apply_speed_failed': 'ApplySpeed failed',
    'status.restore_in_progress': 'restoring…',
    'status.restore_success_wait': 'restored',
    'status.restore_failed': 'restore failed',
    'toast.no_position_random': 'no position',
    'toast.no_waypoints': 'no waypoints',
    'toast.teleport_failed': 'Teleport failed',
    'toast.navigate_failed': 'Navigate failed',
  }
  return map[k] ?? k
}) as UseSimActionsArgs['t']

const okOutcome = { ok: [{ udid: 'A', value: {} }, { udid: 'B', value: {} }], failed: [] }

function makeSim(overrides: Record<string, any> = {}) {
  const make = () => vi.fn(async () => okOutcome)
  return {
    mode: SimMode.Teleport,
    currentPosition: { lat: 1, lng: 2 },
    waypoints: [],
    // single-device legacy methods (sync-ish; return undefined like the real ones)
    teleport: vi.fn(),
    navigate: vi.fn(),
    stop: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    joystickStart: vi.fn(),
    randomWalk: vi.fn(),
    startLoop: vi.fn(),
    multiStop: vi.fn(),
    applySpeed: vi.fn(async () => ({})),
    restore: vi.fn(async () => ({})),
    setCurrentPosition: vi.fn(),
    // *All fan-out methods
    teleportAll: make(),
    navigateAll: make(),
    stopAll: make(),
    pauseAll: make(),
    resumeAll: make(),
    joystickStartAll: make(),
    joystickStopAll: make(),
    randomWalkAll: make(),
    startLoopAll: make(),
    multiStopAll: make(),
    applySpeedAll: make(),
    restoreAll: vi.fn(async () => okOutcome),
    ...overrides,
  }
}

function setup(opts: { udids?: string[]; sim?: any; randomWalkRadius?: number } = {}) {
  const udids = opts.udids ?? ['A']
  const sim = opts.sim ?? makeSim()
  const device = { connectedDevices: udids.map((udid) => ({ udid })) }
  const showToast = vi.fn()
  const pushRecent = vi.fn(async () => undefined)
  const setPreviewPin = vi.fn()
  const api = {} as ApiGateway
  const { result } = renderHook(() =>
    useSimActions({
      sim, device, showToast, t, pushRecent, api,
      randomWalkRadius: opts.randomWalkRadius ?? 500,
      clampLat: (lat) => lat,
      normalizeLng: (lng) => lng,
      setPreviewPin,
    }),
  )
  return { result, sim, device, showToast, pushRecent, setPreviewPin }
}

beforeEach(() => { vi.clearAllMocks() })

describe('useSimActions — teleport', () => {
  it('single device: calls sim.teleport WITHOUT a udid; never the *All variant', async () => {
    const { result, sim, showToast } = setup({ udids: ['A'] })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    expect(sim.teleport).toHaveBeenCalledTimes(1)
    expect(sim.teleport).toHaveBeenCalledWith(10, 20)
    expect(sim.teleportAll).not.toHaveBeenCalled()
    expect(showToast).not.toHaveBeenCalled() // single path: no fan-out toast
  })

  it('dual device: sets currentPosition, fans out teleportAll(udids), toasts the summary', async () => {
    const { result, sim, showToast } = setup({ udids: ['A', 'B'] })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    expect(sim.teleport).not.toHaveBeenCalled()
    expect(sim.setCurrentPosition).toHaveBeenCalledWith({ lat: 10, lng: 20 })
    expect(sim.teleportAll).toHaveBeenCalledWith(['A', 'B'], 10, 20)
    expect(showToast).toHaveBeenCalledWith('Teleport started on all devices')
  })

  it('single device: toasts teleport_failed when sim.teleport throws', async () => {
    const sim = makeSim({ teleport: vi.fn(async () => { throw new Error('DVT error') }) })
    const { result, showToast } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    expect(showToast).toHaveBeenCalledWith('Teleport failed')
  })

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
})

describe('useSimActions — navigate', () => {
  it('single device: sim.navigate, no fan-out toast', async () => {
    const { result, sim, showToast } = setup({ udids: ['A'] })
    await act(async () => { await result.current.handleNavigate(10, 20) })
    expect(sim.navigate).toHaveBeenCalledWith(10, 20)
    expect(sim.navigateAll).not.toHaveBeenCalled()
    expect(showToast).not.toHaveBeenCalled()
  })

  it('dual device: sim.navigateAll + summary toast', async () => {
    const { result, sim, showToast } = setup({ udids: ['A', 'B'] })
    await act(async () => { await result.current.handleNavigate(10, 20) })
    expect(sim.navigateAll).toHaveBeenCalledWith(['A', 'B'], 10, 20)
    expect(showToast).toHaveBeenCalledWith('Navigate started on all devices')
  })

  it('single device: toasts navigate_failed when sim.navigate throws', async () => {
    const sim = makeSim({ navigate: vi.fn(async () => { throw new Error('DVT error') }) })
    const { result, showToast } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleNavigate(10, 20) })
    expect(showToast).toHaveBeenCalledWith('Navigate failed')
  })
})

describe('useSimActions — start (mode gate + joystick branch)', () => {
  it('default Teleport mode is a no-op (the mode gate): no sim call', async () => {
    const sim = makeSim({ mode: SimMode.Teleport })
    const { result } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleStart() })
    expect(sim.joystickStart).not.toHaveBeenCalled()
    expect(sim.startLoop).not.toHaveBeenCalled()
    expect(sim.randomWalk).not.toHaveBeenCalled()
  })

  it('single device, Joystick mode: sim.joystickStart() — the api.joystickStart(moveMode) detail lives in useSimulation', async () => {
    const sim = makeSim({ mode: SimMode.Joystick })
    const { result } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleStart() })
    expect(sim.joystickStart).toHaveBeenCalledTimes(1)
    expect(sim.joystickStartAll).not.toHaveBeenCalled()
  })

  it('dual device, Joystick mode: sim.joystickStartAll(udids) + toast', async () => {
    const sim = makeSim({ mode: SimMode.Joystick })
    const { result, showToast } = setup({ udids: ['A', 'B'], sim })
    await act(async () => { await result.current.handleStart() })
    expect(sim.joystickStartAll).toHaveBeenCalledWith(['A', 'B'])
    expect(showToast).toHaveBeenCalledWith('Joystick started on all devices')
  })

  it('dual device, RandomWalk mode: sim.randomWalkAll(udids, pos, radius) + toast', async () => {
    const sim = makeSim({ mode: SimMode.RandomWalk })
    const { result, showToast } = setup({ udids: ['A', 'B'], sim, randomWalkRadius: 777 })
    await act(async () => { await result.current.handleStart() })
    expect(sim.randomWalkAll).toHaveBeenCalledWith(['A', 'B'], { lat: 1, lng: 2 }, 777)
    expect(showToast).toHaveBeenCalledWith('RandomWalk started on all devices')
  })

  it('Loop mode delegates to startWaypointRoute (needs ≥2 waypoints)', async () => {
    const sim = makeSim({ mode: SimMode.Loop, waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }] })
    const { result } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleStart() })
    expect(sim.startLoop).toHaveBeenCalledTimes(1)
  })

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
})

describe('useSimActions — stop (literal action string + joystick-dual special case)', () => {
  it('single device: sim.stop(), no toast', async () => {
    const { result, sim, showToast } = setup({ udids: ['A'] })
    await act(async () => { await result.current.handleStop() })
    expect(sim.stop).toHaveBeenCalledTimes(1)
    expect(sim.stopAll).not.toHaveBeenCalled()
    expect(showToast).not.toHaveBeenCalled()
  })

  it('dual device: sim.stopAll(udids) + the LITERAL "stop" toast (not a t() key)', async () => {
    const { result, sim, showToast } = setup({ udids: ['A', 'B'] })
    await act(async () => { await result.current.handleStop() })
    expect(sim.stopAll).toHaveBeenCalledWith(['A', 'B'])
    // Nuance #5: literal 'stop' → "stop started on all devices".
    expect(showToast).toHaveBeenCalledWith('stop started on all devices')
  })

  it('dual device + Joystick mode: short-circuits to joystickStopAll, never stopAll', async () => {
    const sim = makeSim({ mode: SimMode.Joystick })
    const { result, showToast } = setup({ udids: ['A', 'B'], sim })
    await act(async () => { await result.current.handleStop() })
    expect(sim.joystickStopAll).toHaveBeenCalledWith(['A', 'B'])
    expect(sim.stopAll).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('Joystick started on all devices')
  })
})

describe('useSimActions — pause / resume (literal action strings)', () => {
  it('single device: sim.pause()/sim.resume(), no toast', async () => {
    const { result, sim, showToast } = setup({ udids: ['A'] })
    await act(async () => { await result.current.handlePause() })
    await act(async () => { await result.current.handleResume() })
    expect(sim.pause).toHaveBeenCalledTimes(1)
    expect(sim.resume).toHaveBeenCalledTimes(1)
    expect(showToast).not.toHaveBeenCalled()
  })

  it('dual device: pauseAll/resumeAll with the LITERAL pause/resume strings', async () => {
    const { result, sim, showToast } = setup({ udids: ['A', 'B'] })
    await act(async () => { await result.current.handlePause() })
    expect(sim.pauseAll).toHaveBeenCalledWith(['A', 'B'])
    expect(showToast).toHaveBeenCalledWith('pause started on all devices')

    showToast.mockClear()
    await act(async () => { await result.current.handleResume() })
    expect(sim.resumeAll).toHaveBeenCalledWith(['A', 'B'])
    expect(showToast).toHaveBeenCalledWith('resume started on all devices')
  })
})

describe('useSimActions — applySpeed / restore', () => {
  it('single device applySpeed: sim.applySpeed() + plain success toast', async () => {
    const { result, sim, showToast } = setup({ udids: ['A'] })
    await act(async () => { await result.current.handleApplySpeed() })
    expect(sim.applySpeed).toHaveBeenCalledTimes(1)
    expect(sim.applySpeedAll).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('ApplySpeed OK')
  })

  it('dual device applySpeed: sim.applySpeedAll(udids) + fan-out toast', async () => {
    const { result, sim, showToast } = setup({ udids: ['A', 'B'] })
    await act(async () => { await result.current.handleApplySpeed() })
    expect(sim.applySpeedAll).toHaveBeenCalledWith(['A', 'B'])
    expect(showToast).toHaveBeenCalledWith('ApplySpeed OK started on all devices')
  })

  it('single device restore: sim.restore(); dual: sim.restoreAll(udids)', async () => {
    const single = setup({ udids: ['A'] })
    await act(async () => { await single.result.current.handleRestore() })
    expect(single.sim.restore).toHaveBeenCalledTimes(1)
    expect(single.sim.restoreAll).not.toHaveBeenCalled()

    const dual = setup({ udids: ['A', 'B'] })
    await act(async () => { await dual.result.current.handleRestore() })
    expect(dual.sim.restoreAll).toHaveBeenCalledWith(['A', 'B'])
    expect(dual.sim.restore).not.toHaveBeenCalled()
  })
})

describe('useSimActions — undo (single-level last-position snapshot)', () => {
  it('single device: handleUndo teleports back to the pre-teleport position', async () => {
    // Device starts at { lat: 1, lng: 2 } (makeSim default currentPosition).
    const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
    const { result } = setup({ udids: ['A'], sim })
    // Teleport to a new spot — snapshot should capture the prior {1,2}.
    await act(async () => { await result.current.handleTeleport(10, 20) })
    expect(sim.teleport).toHaveBeenCalledWith(10, 20)
    sim.teleport.mockClear()
    // Undo flies back to the snapshot.
    await act(async () => { await result.current.handleUndo() })
    expect(sim.teleport).toHaveBeenCalledWith(1, 2)
  })

  it('handleUndo is a silent no-op when nothing has been teleported yet', async () => {
    const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
    const { result } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleUndo() })
    expect(sim.teleport).not.toHaveBeenCalled()
    expect(sim.teleportAll).not.toHaveBeenCalled()
  })

  it('single level: a second consecutive Undo is a no-op (snapshot cleared after use)', async () => {
    const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
    const { result } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    sim.teleport.mockClear()
    await act(async () => { await result.current.handleUndo() })
    expect(sim.teleport).toHaveBeenCalledTimes(1) // first undo flew back
    sim.teleport.mockClear()
    await act(async () => { await result.current.handleUndo() })
    expect(sim.teleport).not.toHaveBeenCalled() // second undo: snapshot consumed
  })

  it('no-op when the pre-teleport position was null (nothing to snapshot)', async () => {
    const sim = makeSim({ currentPosition: null })
    const { result } = setup({ udids: ['A'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    sim.teleport.mockClear()
    await act(async () => { await result.current.handleUndo() })
    expect(sim.teleport).not.toHaveBeenCalled()
  })

  it('dual device: handleUndo fans out teleportAll back to the snapshot', async () => {
    const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
    const { result } = setup({ udids: ['A', 'B'], sim })
    await act(async () => { await result.current.handleTeleport(10, 20) })
    sim.teleportAll.mockClear()
    await act(async () => { await result.current.handleUndo() })
    expect(sim.teleportAll).toHaveBeenCalledWith(['A', 'B'], 1, 2)
  })
})
