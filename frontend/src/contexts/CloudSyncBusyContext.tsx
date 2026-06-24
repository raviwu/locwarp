import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react'

/**
 * Tracks whether a cloud-sync toggle (enable/disable) is in flight.
 *
 * Why: ``POST /api/cloud-sync/enable`` runs ``migrate_pair`` synchronously
 * (union-merge with the iCloud copy + atomic iCloud write). On a cold
 * iCloud cache this can take several seconds, during which the bookmark
 * and route panels would otherwise show pre-merge content. We wrap that
 * window in a busy flag so the UI can block input and surface a clear
 * "Syncing with iCloud…" overlay.
 *
 * The busy window also covers a post-toggle refresh hook: the app shell
 * registers a callback via ``useCloudSyncAfter`` (typically
 * ``Promise.all([bm.refresh(), refreshRouteCategories(), …])``) which
 * runs after the toggle resolves and before the flag clears — so the
 * overlay only disappears once the panels show the merged content.
 */
type AfterFn = () => Promise<void> | void

/**
 * Hard ceiling on a single cloud-sync toggle. A backend stuck mid
 * ``migrate_pair`` (cold iCloud cache, hung atomic write) must not pin
 * the zIndex-9999 busy overlay open forever — at this deadline we abort
 * the in-flight request so ``run``'s ``finally`` clears ``busy``.
 */
export const CLOUD_SYNC_TIMEOUT_MS = 35000

/** After this long, surface a "taking longer…" line + a Cancel button. */
export const CLOUD_SYNC_SLOW_HINT_MS = 10000

type CloudSyncBusyContextValue = {
  busy: boolean
  tookTooLong: boolean
  run<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T>
  cancel(): void
  /** Internal: replace the post-toggle hook. Prefer ``useCloudSyncAfter``. */
  _setAfter(fn: AfterFn | null): void
}

const Ctx = createContext<CloudSyncBusyContextValue>({
  busy: false,
  tookTooLong: false,
  run: async (fn) => fn(new AbortController().signal),
  cancel: () => undefined,
  _setAfter: () => undefined,
})

export function CloudSyncBusyProvider({ children }: { children: React.ReactNode }) {
  const [busy, setBusy] = useState(false)
  const [tookTooLong, setTookTooLong] = useState(false)
  const afterRef = useRef<AfterFn | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  const _setAfter = useCallback((fn: AfterFn | null) => {
    afterRef.current = fn
  }, [])

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
  }, [])

  const run = useCallback(async <T,>(fn: (signal: AbortSignal) => Promise<T>) => {
    setBusy(true)
    setTookTooLong(false)
    const controller = new AbortController()
    controllerRef.current = controller
    const slowTimer = setTimeout(() => setTookTooLong(true), CLOUD_SYNC_SLOW_HINT_MS)
    const timer = setTimeout(() => controller.abort(), CLOUD_SYNC_TIMEOUT_MS)
    try {
      const result = await fn(controller.signal)
      try {
        await afterRef.current?.()
      } catch {
        /* refresh failure must not mask toggle outcome */
      }
      return result
    } finally {
      clearTimeout(slowTimer)
      clearTimeout(timer)
      controllerRef.current = null
      setTookTooLong(false)
      setBusy(false)
    }
  }, [])

  const value = useMemo(
    () => ({ busy, tookTooLong, run, cancel, _setAfter }),
    [busy, tookTooLong, run, cancel, _setAfter],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useCloudSyncBusy() {
  return useContext(Ctx)
}

/**
 * Register a post-toggle refresh hook for the lifetime of the calling
 * component. Use this so the busy overlay stays visible until panel data
 * has actually re-fetched.
 */
export function useCloudSyncAfter(fn: AfterFn) {
  const { _setAfter } = useContext(Ctx)
  // Always register the latest closure; clear on unmount.
  useEffect(() => {
    _setAfter(fn)
    return () => _setAfter(null)
  }, [_setAfter, fn])
}
