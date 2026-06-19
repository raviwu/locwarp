import { describe, it, expect, vi } from 'vitest'
import { createWsRouter } from './router'
import type { WsEvent } from '../../contract/wsEvents'

describe('createWsRouter', () => {
  it('dispatches a message to ALL subscribers of its type (fan-out preserved)', () => {
    const router = createWsRouter()
    // Stand-ins for the two real consumers that both read device_disconnected.
    const deviceHandler = vi.fn()       // useDevice-shaped: reads udid / udids
    const simulationHandler = vi.fn()   // useSimulation-shaped: reads remaining_count

    router.subscribe('device_disconnected', deviceHandler)
    router.subscribe('device_disconnected', simulationHandler)

    const evt: WsEvent = {
      type: 'device_disconnected',
      udid: 'UDID-A',
      udids: ['UDID-A'],
      reason: 'forgotten',
      remaining_count: 1,
    }
    router.dispatch(evt)

    expect(deviceHandler).toHaveBeenCalledTimes(1)
    expect(deviceHandler).toHaveBeenCalledWith(evt)
    expect(simulationHandler).toHaveBeenCalledTimes(1)
    expect(simulationHandler).toHaveBeenCalledWith(evt)
  })

  it('only delivers to subscribers of the matching type', () => {
    const router = createWsRouter()
    const onDisc = vi.fn()
    const onPos = vi.fn()
    router.subscribe('device_disconnected', onDisc)
    router.subscribe('position_update', onPos)

    router.dispatch({ type: 'position_update', lat: 1, lng: 2 })

    expect(onPos).toHaveBeenCalledTimes(1)
    expect(onDisc).not.toHaveBeenCalled()
  })

  it('isolates a throwing handler — others still fire (per-handler try/catch)', () => {
    const router = createWsRouter()
    const boom = vi.fn(() => { throw new Error('subscriber blew up') })
    const ok = vi.fn()
    router.subscribe('state_change', boom)
    router.subscribe('state_change', ok)

    expect(() => router.dispatch({ type: 'state_change', state: 'idle' })).not.toThrow()
    expect(boom).toHaveBeenCalledTimes(1)
    expect(ok).toHaveBeenCalledTimes(1)
  })

  it('unsubscribe stops further delivery to that handler only', () => {
    const router = createWsRouter()
    const a = vi.fn()
    const b = vi.fn()
    const unsubA = router.subscribe('device_connected', a)
    router.subscribe('device_connected', b)

    unsubA()
    router.dispatch({ type: 'device_connected', udid: 'X' })

    expect(a).not.toHaveBeenCalled()
    expect(b).toHaveBeenCalledTimes(1)
  })

  it('dropping the last subscriber of a type leaves no empty bucket leak', () => {
    const router = createWsRouter()
    const h = vi.fn()
    const unsub = router.subscribe('tunnel_recovered', h)
    unsub()
    // Dispatching to a now-empty type must be a no-op, not a crash.
    expect(() => router.dispatch({ type: 'tunnel_recovered', udid: 'X' })).not.toThrow()
    expect(h).not.toHaveBeenCalled()
  })

  it('an unknown type with no subscribers is a silent no-op', () => {
    const router = createWsRouter()
    expect(() => router.dispatch({ type: 'never_registered' })).not.toThrow()
  })
})
