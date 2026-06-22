import { describe, it, expect } from 'vitest'
import { toastForFanout } from './toast'
import type { FanoutOutcome } from '../hooks/useSimulation'

// A minimal t() stub matching the production behaviour the dangerzone tests
// rely on: the real English strings for the all-success / all-failed keys.
const t = (k: any, v?: Record<string, string | number>): string => {
  if (k === 'group.action_all_success') return `${v?.action} started on all devices`
  if (k === 'group.action_all_failed') return `${v?.action} failed on all devices`
  return k
}

const outcome = <T>(
  ok: { udid: string; value: T }[],
  failed: { udid: string; reason: string }[],
): FanoutOutcome<T> => ({ ok, failed })

describe('toastForFanout', () => {
  it('returns the bare action string when nothing was attempted', () => {
    expect(toastForFanout(t, 'Teleport', outcome([], []), [])).toBe('Teleport')
  })

  it('renders the all-success message when every device succeeded', () => {
    const o = outcome(
      [{ udid: 'a', value: 1 }, { udid: 'b', value: 2 }],
      [],
    )
    expect(toastForFanout(t, 'Teleport', o, [{ udid: 'a' }, { udid: 'b' }]))
      .toBe('Teleport started on all devices')
  })

  it('renders the all-failed message when every device failed', () => {
    const o = outcome<number>(
      [],
      [{ udid: 'a', reason: 'boom' }, { udid: 'b', reason: 'boom' }],
    )
    expect(toastForFanout(t, 'Joystick', o, [{ udid: 'a' }, { udid: 'b' }]))
      .toBe('Joystick failed on all devices')
  })

  it('renders a per-device A/B/C breakdown on a mixed result', () => {
    const o = outcome(
      [{ udid: 'a', value: 1 }],
      [{ udid: 'b', reason: 'stale' }],
    )
    expect(toastForFanout(t, 'stop', o, [{ udid: 'a' }, { udid: 'b' }]))
      .toBe('stop: A OK, B stale')
  })

  it('caps the per-device breakdown at the first three devices', () => {
    const o = outcome(
      [{ udid: 'a', value: 1 }, { udid: 'c', value: 3 }],
      [{ udid: 'b', reason: 'x' }, { udid: 'd', reason: 'y' }],
    )
    expect(
      toastForFanout(t, 'go', o, [
        { udid: 'a' }, { udid: 'b' }, { udid: 'c' }, { udid: 'd' },
      ]),
    ).toBe('go: A OK, B x, C OK')
  })

  it('falls back to "error" when a failed device has no matching reason', () => {
    // device 'b' is neither in ok nor failed → status falls through to 'error'
    const o = outcome(
      [{ udid: 'a', value: 1 }],
      [{ udid: 'z', reason: 'unrelated' }],
    )
    expect(toastForFanout(t, 'go', o, [{ udid: 'a' }, { udid: 'b' }]))
      .toBe('go: A OK, B error')
  })
})
