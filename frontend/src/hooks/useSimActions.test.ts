import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSimActions } from './useSimActions'

// ─────────────────────────────────────────────────────────────────────────────
// Task 8: re-fly must not duplicate a Recent row and must not silently kill a
// running simulation.
//
// `handleTeleport` / `handleNavigate` gain a 4th `opts: { record?: boolean }`
// argument and now resolve a success boolean:
//   - `opts.record === false` skips the `pushRecent` push (used by the
//     Recent popover when re-flying a `route_stop` row, which already has its
//     own history entry — pushing a manual 'teleport'/'navigate' on top of it
//     would be an undedupeable duplicate).
//   - the resolved boolean is `true` iff at least one device actually moved
//     (single-device: the sim.teleport/navigate call didn't throw; dual-device:
//     not a total failure), so `App.tsx`'s `onRecentReFly` can toast "your
//     running simulation was just interrupted" only when the fly-to actually
//     landed.
//
// `useSimActions` takes one plain-object argument (see App.tsx:367-370), so it
// is driven directly via `renderHook` rather than through a rendered `App` —
// far lighter than `App.dangerzone.test.tsx`'s full-App harness, and this hook
// owns the behavior under test. `App.dangerzone.test.tsx` already pins the
// single-vs-dual-device fan-out shape for these handlers; this file only
// covers the NEW opts.record / boolean-return surface, not the fan-out itself.
// The two `onRecentReFly` toast assertions (isRunning-gated,
// never-overwrite-a-failure-toast) live in `App.recentReFly.test.tsx` since
// `onRecentReFly` and `isRunning` are App-local.
// ─────────────────────────────────────────────────────────────────────────────

type FanoutResult = { ok: Array<{ udid: string; value: any }>; failed: Array<{ udid: string; reason: string }> }

function renderSimActions(overrides: {
  udids?: string[]
  teleport?: (...args: any[]) => Promise<any>
  navigate?: (...args: any[]) => Promise<any>
  teleportAllResult?: FanoutResult
  navigateAllResult?: FanoutResult
} = {}) {
  const pushRecent = vi.fn()
  const showToast = vi.fn()
  const t = (k: any) => String(k)
  const udids = overrides.udids ?? ['A']
  const sim: any = {
    currentPosition: null,
    setCurrentPosition: vi.fn(),
    teleport: overrides.teleport ?? vi.fn(async () => ({})),
    teleportAll: vi.fn(async () =>
      overrides.teleportAllResult ?? { ok: udids.map((udid) => ({ udid, value: {} })), failed: [] }),
    navigate: overrides.navigate ?? vi.fn(async () => ({})),
    navigateAll: vi.fn(async () =>
      overrides.navigateAllResult ?? { ok: udids.map((udid) => ({ udid, value: {} })), failed: [] }),
  }
  const device = { connectedDevices: udids.map((udid) => ({ udid })) }
  const api = {} as any
  const clampLat = (lat: number) => lat
  const normalizeLng = (lng: number) => lng
  const setPreviewPin = vi.fn()

  const { result } = renderHook(() => useSimActions({
    sim, device, showToast, t, pushRecent, api,
    randomWalkRadius: 50, clampLat, normalizeLng, setPreviewPin,
  }))

  return { result, pushRecent, showToast, sim, device }
}

describe('useSimActions — re-fly record opt-out + success boolean (Task 8)', () => {
  describe('handleTeleport', () => {
    it('re-flying a route stop does not create a duplicate manual entry', async () => {
      const { result, pushRecent } = renderSimActions()
      await act(async () => {
        await result.current.handleTeleport(25.0, 121.0, 'menu', { record: false })
      })
      expect(pushRecent).not.toHaveBeenCalled()
    })

    it('re-flying a manual row still records it', async () => {
      const { result, pushRecent } = renderSimActions()
      await act(async () => {
        await result.current.handleTeleport(25.0, 121.0)
      })
      expect(pushRecent).toHaveBeenCalledWith(25.0, 121.0, 'teleport')
    })

    it('resolves false when the single-device teleport throws', async () => {
      const { result } = renderSimActions({ teleport: async () => { throw new Error('boom') } })
      let ok: boolean | undefined
      await act(async () => { ok = await result.current.handleTeleport(1, 2) })
      expect(ok).toBe(false)
    })

    it('resolves true on single-device success', async () => {
      const { result } = renderSimActions()
      let ok: boolean | undefined
      await act(async () => { ok = await result.current.handleTeleport(25.0, 121.0) })
      expect(ok).toBe(true)
    })

    it('dual-device: resolves false and skips pushRecent on total failure', async () => {
      const { result, pushRecent } = renderSimActions({
        udids: ['A', 'B'],
        teleportAllResult: { ok: [], failed: [{ udid: 'A', reason: 'x' }, { udid: 'B', reason: 'y' }] },
      })
      let ok: boolean | undefined
      await act(async () => { ok = await result.current.handleTeleport(25.0, 121.0) })
      expect(ok).toBe(false)
      expect(pushRecent).not.toHaveBeenCalled()
    })

    it('dual-device: resolves true on partial success', async () => {
      const { result } = renderSimActions({
        udids: ['A', 'B'],
        teleportAllResult: { ok: [{ udid: 'A', value: {} }], failed: [{ udid: 'B', reason: 'x' }] },
      })
      let ok: boolean | undefined
      await act(async () => { ok = await result.current.handleTeleport(25.0, 121.0) })
      expect(ok).toBe(true)
    })
  })

  describe('handleNavigate', () => {
    it('re-flying a route stop does not create a duplicate manual entry', async () => {
      const { result, pushRecent } = renderSimActions()
      await act(async () => {
        await result.current.handleNavigate(25.0, 121.0, 'menu', { record: false })
      })
      expect(pushRecent).not.toHaveBeenCalled()
    })

    it('re-flying a manual row still records it', async () => {
      const { result, pushRecent } = renderSimActions()
      await act(async () => {
        await result.current.handleNavigate(25.0, 121.0)
      })
      expect(pushRecent).toHaveBeenCalledWith(25.0, 121.0, 'navigate')
    })

    it('resolves false when the single-device navigate throws', async () => {
      const { result } = renderSimActions({ navigate: async () => { throw new Error('boom') } })
      let ok: boolean | undefined
      await act(async () => { ok = await result.current.handleNavigate(1, 2) })
      expect(ok).toBe(false)
    })

    it('resolves true on single-device success', async () => {
      const { result } = renderSimActions()
      let ok: boolean | undefined
      await act(async () => { ok = await result.current.handleNavigate(25.0, 121.0) })
      expect(ok).toBe(true)
    })
  })
})
