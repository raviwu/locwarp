import { useEffect } from 'react'
import type { WsRouter } from '../ports/WsRouter'

// Replaces App.tsx inline subscriber #1 (bookmarks_changed / routes_changed).
export function useExternalChangeSubscriptions(
  ws: WsRouter,
  cbs: { onBookmarks: () => void; onRoutes: () => void },
) {
  useEffect(() => {
    const offB = ws.subscribe('bookmarks_changed', () => cbs.onBookmarks())
    const offR = ws.subscribe('routes_changed', () => cbs.onRoutes())
    return () => { offB(); offR() }
  }, [ws, cbs])
}
