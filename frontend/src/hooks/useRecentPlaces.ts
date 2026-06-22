import { useState, useCallback, useEffect } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import type { RecentEntry, RecentKind } from '../services/api'

// Recent-destinations history (last 20 places the user flew to), extracted out
// of App.tsx. Mirrors the useRoutes/useBookmarks `useX(api)` shape — the backend
// `api` is injected (App sources it from useServices()) so the hook never imports
// services/api directly and stays inside the hexagon-lite layering gate. The
// `RecentEntry` / `RecentKind` imports are TYPE-ONLY (erased at build), so no
// runtime services/api edge is introduced.
//
// `connected` is threaded in so the mount fetch is retried whenever the backend
// WebSocket becomes reachable: without it, a slow/racing backend boot could blow
// the only fetch attempt and the list would stay empty for the rest of the
// session (the silent catch in refreshRecent swallows the failure).
export function useRecentPlaces(api: ApiGateway, connected: boolean) {
  const [recentPlaces, setRecentPlaces] = useState<RecentEntry[]>([])

  const refreshRecent = useCallback(async () => {
    try { setRecentPlaces(await api.getRecent()) } catch { /* silent */ }
  }, [api])

  // Re-fetch on initial mount AND whenever the backend WebSocket becomes
  // reachable (see header note on the `connected` dep).
  useEffect(() => { void refreshRecent() }, [refreshRecent, connected])

  const pushRecent = useCallback(async (lat: number, lng: number, kind: RecentKind, name?: string) => {
    try {
      await api.pushRecent({ lat, lng, kind, name: name || null })
      void refreshRecent()
      // When the caller didn't supply a name (right-click teleport /
      // navigate, coord-input fly), reverse-geocode in the background
      // and push again with a resolved short_name. Backend dedupe then
      // bumps the top entry and fills in its name field, so the list
      // stops showing the raw coord twice.
      if (!name) {
        void (async () => {
          try {
            const geo = await api.reverseGeocode(lat, lng)
            const resolved = String(geo?.short_name || geo?.display_name || '').trim()
            if (!resolved) return
            await api.pushRecent({ lat, lng, kind, name: resolved })
            void refreshRecent()
          } catch { /* offline / rate-limited — keep the unnamed entry */ }
        })()
      }
    } catch { /* silent */ }
  }, [api, refreshRecent])

  const clearRecentList = useCallback(async () => {
    try { await api.clearRecent() } catch { /* silent */ }
    setRecentPlaces([])
  }, [api])

  return { recentPlaces, refreshRecent, pushRecent, clearRecentList }
}
