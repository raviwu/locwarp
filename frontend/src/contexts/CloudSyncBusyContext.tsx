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

type CloudSyncBusyContextValue = {
  busy: boolean
  run<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T>
  /** Internal: replace the post-toggle hook. Prefer ``useCloudSyncAfter``. */
  _setAfter(fn: AfterFn | null): void
}

const Ctx = createContext<CloudSyncBusyContextValue>({
  busy: false,
  run: async (fn) => fn(new AbortController().signal),
  _setAfter: () => undefined,
})

export function CloudSyncBusyProvider({ children }: { children: React.ReactNode }) {
  const [busy, setBusy] = useState(false)
  const afterRef = useRef<AfterFn | null>(null)

  const _setAfter = useCallback((fn: AfterFn | null) => {
    afterRef.current = fn
  }, [])

  const run = useCallback(async <T,>(fn: (signal: AbortSignal) => Promise<T>) => {
    setBusy(true)
    const controller = new AbortController()
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
      clearTimeout(timer)
      setBusy(false)
    }
  }, [])

  const value = useMemo(() => ({ busy, run, _setAfter }), [busy, run, _setAfter])
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
