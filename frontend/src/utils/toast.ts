import type { FanoutOutcome } from '../hooks/useSimulation'

// Summarise a group fan-out result into a single toast string.
// Call from action handlers: showToast(toastForFanout(t, 'teleport', outcome, connectedDevices))
export function toastForFanout<T>(
  t: (k: any, v?: Record<string, string | number>) => string,
  action: string,
  outcome: FanoutOutcome<T>,
  devices: { udid: string }[],
): string {
  const total = outcome.ok.length + outcome.failed.length
  if (total === 0) return action
  if (outcome.failed.length === 0) return t('group.action_all_success', { action })
  if (outcome.ok.length === 0) return t('group.action_all_failed', { action })
  const statusFor = (udid: string) =>
    outcome.ok.some((o) => o.udid === udid) ? 'OK'
      : outcome.failed.find((f) => f.udid === udid)?.reason ?? 'error'
  const letters = ['A', 'B', 'C']
  const parts = devices.slice(0, 3).map((d, i) => `${letters[i]} ${statusFor(d.udid)}`)
  return `${action}: ${parts.join(', ')}`
}
