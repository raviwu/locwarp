import { useState, useCallback, useEffect, useRef } from 'react'
import type { ApiGateway } from '../contract/apiGateway'

// Saved-routes data + CRUD, extracted out of App.tsx. Mirrors useBookmarks'
// state+CRUD shape but takes the backend `api` injected (App sources it from
// useServices()) so the hook never imports services/api directly — it stays on
// the inward side of the hexagon-lite layering gate.
//
// SCOPE: this owns the saved-route DATA + persistence only. Anything that pushes
// a route into the running simulation (e.g. handleRouteLoad / confirmRouteLoad,
// route-paste teleport) stays in App and consumes `savedRoutes` from here.
//
// Toasts + i18n stay in App: each CRUD handler returns/throws so App keeps full
// control over the user-facing messaging that previously wrapped these calls.
export function useRoutes(api: ApiGateway) {
  const [savedRoutes, setSavedRoutes] = useState<any[]>([])
  const [routeCategories, setRouteCategories] = useState<any[]>([])
  const mountedRef = useRef(true)

  const refreshRouteCategories = useCallback(async () => {
    try {
      const cats = await api.listRouteCategories()
      if (!mountedRef.current) return
      setRouteCategories(Array.isArray(cats) ? cats : [])
    } catch { /* leave empty so RouteList still falls back to default */ }
  }, [api])

  const refreshSavedRoutes = useCallback(async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const rs = await api.getSavedRoutes()
        if (mountedRef.current) setSavedRoutes(rs)
        return
      } catch {
        if (attempt === 0) await new Promise((r) => setTimeout(r, 400))
      }
    }
    // both attempts failed — leave the last good state; a later
    // routes_changed or the reconnect catch-up will refresh again.
  }, [api])

  // Keep the cloud-sync busy overlay visible until route data has been
  // re-fetched after a toggle, so panels never flash pre-merge content.
  // App composes this with bm.refresh into the SINGLE useCloudSyncAfter
  // closure (it must not register its own).
  const refresh = useCallback(async () => {
    await refreshSavedRoutes()
    await refreshRouteCategories()
  }, [refreshSavedRoutes, refreshRouteCategories])

  // Load saved routes + categories on mount.
  useEffect(() => {
    mountedRef.current = true
    api.getSavedRoutes().then((rs) => {
      if (mountedRef.current) setSavedRoutes(rs)
    }).catch(() => {})
    refreshRouteCategories()
    return () => { mountedRef.current = false }
  }, [api, refreshRouteCategories])

  // -- Saved-route CRUD --

  // Save a new route OR overwrite an existing one. waypoints + profile are the
  // sim DATA the caller (App) supplies — the hook never touches the sim itself.
  // On overwrite, the existing route's category_id is preserved unless the
  // caller passes one explicitly. Returns nothing; throws on failure so App can
  // toast.
  const save = useCallback(async (
    args: {
      name: string
      waypoints: any[]
      profile: string
      categoryId?: string
      overwriteId?: string
    },
  ): Promise<{ overwritten: boolean }> => {
    if (args.overwriteId) {
      const prev = savedRoutes.find((r) => r.id === args.overwriteId)
      await api.replaceRoute(args.overwriteId, {
        id: args.overwriteId,
        name: args.name,
        waypoints: args.waypoints,
        profile: args.profile,
        category_id: args.categoryId ?? prev?.category_id ?? 'default',
      })
      const routes = await api.getSavedRoutes()
      setSavedRoutes(routes)
      return { overwritten: true }
    }
    await api.saveRoute({
      name: args.name,
      waypoints: args.waypoints,
      profile: args.profile,
      category_id: args.categoryId ?? 'default',
    })
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
    return { overwritten: false }
  }, [api, savedRoutes])

  const rename = useCallback(async (id: string, name: string) => {
    await api.renameRoute(id, name)
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
  }, [api])

  const remove = useCallback(async (id: string) => {
    await api.deleteRoute(id)
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
  }, [api])

  const bulkDelete = useCallback(async (ids: string[]) => {
    await Promise.all(ids.map((id) => api.deleteRoute(id).catch(() => null)))
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
  }, [api])

  const move = useCallback(async (ids: string[], targetCategoryId: string) => {
    await api.moveRoutes(ids, targetCategoryId)
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
  }, [api])

  // -- Route-category CRUD --

  const categoryAdd = useCallback(async (name: string, color = '#6c8cff') => {
    await api.createRouteCategory(name, color)
    await refreshRouteCategories()
  }, [api, refreshRouteCategories])

  const categoryDelete = useCallback(async (id: string) => {
    await api.deleteRouteCategory(id)
    // Routes that pointed at this category were moved to default by the
    // backend; refresh both lists so the UI reflects the regrouped state.
    await refreshRouteCategories()
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
  }, [api, refreshRouteCategories])

  const categoryRename = useCallback(async (id: string, name: string) => {
    const cat = routeCategories.find((c) => c.id === id)
    await api.updateRouteCategory(id, { name, color: cat?.color || '#6c8cff' })
    await refreshRouteCategories()
  }, [api, routeCategories, refreshRouteCategories])

  const categoryRecolor = useCallback(async (id: string, color: string) => {
    const cat = routeCategories.find((c) => c.id === id)
    await api.updateRouteCategory(id, { name: cat?.name || '', color })
    await refreshRouteCategories()
  }, [api, routeCategories, refreshRouteCategories])

  // -- GPX import / export + bulk JSON import --

  const importGpx = useCallback(async (file: File): Promise<{ points: number }> => {
    const res = await api.importGpx(file)
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
    return { points: res.points }
  }, [api])

  const exportGpx = useCallback((id: string) => {
    const url = api.exportGpxUrl(id)
    window.open(url, '_blank')
  }, [api])

  const importAll = useCallback(async (file: File): Promise<{ imported: number }> => {
    const text = await file.text()
    const data = JSON.parse(text)
    if (!Array.isArray(data?.routes)) {
      throw new Error('invalid file: missing routes array')
    }
    // Pass categories through too if present (post-v0.2.133 export shape).
    // Old exports without this field still import fine.
    const res = await api.importAllRoutes({
      routes: data.routes,
      categories: Array.isArray(data?.categories) ? data.categories : [],
    })
    const routes = await api.getSavedRoutes()
    setSavedRoutes(routes)
    await refreshRouteCategories()
    return { imported: res.imported }
  }, [api, refreshRouteCategories])

  return {
    savedRoutes,
    routeCategories,
    refresh,
    refreshRouteCategories,
    save,
    rename,
    remove,
    bulkDelete,
    move,
    categoryAdd,
    categoryDelete,
    categoryRename,
    categoryRecolor,
    importGpx,
    exportGpx,
    importAll,
  }
}
