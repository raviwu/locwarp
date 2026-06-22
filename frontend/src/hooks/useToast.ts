import { useState, useCallback, useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'

export interface ToastState {
  /** The currently-displayed toast message, or null when nothing is shown. */
  toastMsg: string | null
  /**
   * Show a toast for `ms` milliseconds (default 3000). A newer call cancels
   * the prior auto-clear timer so the newest toast always gets its full
   * duration — otherwise an earlier toast's clear timer (e.g. a 2s teleport
   * toast) would fire mid-way through a later toast (e.g. a 6s timezone toast)
   * and blank it out after only a fraction of its intended time.
   */
  showToast: (msg: string, ms?: number) => void
  /**
   * Raw setter for the few call-sites that deliberately set a sticky toast
   * with NO auto-clear timer (it stays until the next showToast / setToastMsg).
   * Preserved verbatim from the original App so behaviour is unchanged.
   */
  setToastMsg: Dispatch<SetStateAction<string | null>>
}

/**
 * App-wide toast: a single message slot driven by a single shared auto-clear
 * timer. Extracted from App so the toast surface is unit-testable and so
 * `showToast` can be a stable reference available BEFORE useSimulation runs
 * (it captures showToast for the WiFi-tunnel-recovered toast).
 */
export function useToast(): ToastState {
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = useCallback((msg: string, ms = 3000) => {
    // Cancel any previous auto-clear timer so the newest toast always
    // gets its full duration. Otherwise an earlier toast (e.g. teleport,
    // 2s) would fire its clear timer mid-way through a later toast
    // (e.g. timezone, 6s) and blank it out after only a fraction.
    if (toastTimerRef.current !== null) {
      clearTimeout(toastTimerRef.current)
      toastTimerRef.current = null
    }
    setToastMsg(msg)
    toastTimerRef.current = setTimeout(() => {
      setToastMsg(null)
      toastTimerRef.current = null
    }, ms)
  }, [])

  return { toastMsg, showToast, setToastMsg }
}
