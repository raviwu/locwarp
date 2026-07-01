import { useEffect, useRef } from 'react'
import type { WsRouter } from '../ports/WsRouter'
import type { StringKey } from '../i18n/strings'

// Replaces App.tsx inline subscriber #2 (goldditto_cycle).
// cbs.t and cbs.showToast have stable references from App.tsx's useCallback/useT.
export function useGoldDittoSubscription(
  ws: WsRouter,
  cbs: {
    t: (key: StringKey, vars?: Record<string, string | number>) => string
    showToast: (msg: string, ms?: number) => void
  },
) {
  const countdownRef = useRef<{ timer: ReturnType<typeof setInterval> | null; endAt: number }>({ timer: null, endAt: 0 })

  useEffect(() => {
    const clearCountdown = () => {
      if (countdownRef.current.timer !== null) {
        clearInterval(countdownRef.current.timer)
      }
      countdownRef.current = { timer: null, endAt: 0 }
    }

    // Format remaining seconds. Short waits show a smooth one-decimal seconds
    // value ("5.0s"); long waits (>= 60s, now possible up to 3600s) show mm:ss
    // so the toast stays readable instead of "1799.8s".
    const fmtRemaining = (secs: number): string => {
      if (secs >= 60) {
        const m = Math.floor(secs / 60)
        const s = Math.floor(secs % 60)
        return `${m}:${String(s).padStart(2, '0')}`
      }
      return `${secs.toFixed(1)}s`
    }

    const offGold = ws.subscribe('goldditto_cycle', (e) => {
      const phase = String(e.phase ?? '')
      if (phase === 'teleported') {
        const target = String(e.target ?? '')
        cbs.showToast(cbs.t('goldditto.toast.teleported', { target }))
        // Read wait_seconds back from the same localStorage key the panel
        // writes to. Avoids plumbing it as a prop through every layer just
        // for this one timer. Falls back to 3.0 (panel default).
        const raw = localStorage.getItem('goldditto.wait_seconds') ?? '3.0'
        const parsed = parseFloat(raw)
        const waitS = Number.isFinite(parsed) && parsed > 0 ? parsed : 3.0
        const endAt = Date.now() + waitS * 1000
        clearCountdown()
        // Adaptive tick: keep the smooth 200ms countdown for short waits, but
        // throttle to 1s for long waits (up to 60min) so we don't fire ~9000
        // toasts over a 30-min pull.
        const tickMs = waitS >= 30 ? 1000 : 200
        const timer = setInterval(() => {
          const remaining = Math.max(0, (countdownRef.current.endAt - Date.now()) / 1000)
          if (remaining <= 0) {
            clearCountdown()
            return
          }
          cbs.showToast(cbs.t('goldditto.toast.waiting', { remaining: fmtRemaining(remaining) }))
        }, tickMs)
        countdownRef.current = { timer, endAt }
      } else if (phase === 'restored') {
        clearCountdown()
        cbs.showToast(cbs.t('goldditto.toast.restored'))
      } else if (phase === 'restore_failed') {
        clearCountdown()
        // 8s persistent red banner — see goldditto.toast.restore_failed key
        // for the warning text. Spec §8 row 5.
        cbs.showToast(cbs.t('goldditto.toast.restore_failed'), 8000)
      }
    })

    return () => {
      offGold()
      clearCountdown()
    }
  }, [ws, cbs])
}
