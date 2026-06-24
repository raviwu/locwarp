import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useT } from './i18n'
import { useDevice } from './hooks/useDevice'
import { useSimulation } from './hooks/useSimulation'
import { useJoystick } from './hooks/useJoystick'
import { useBookmarks } from './hooks/useBookmarks'
import { useRoutes } from './hooks/useRoutes'
import { useRecentPlaces } from './hooks/useRecentPlaces'
import { useWifiAutoConnect } from './hooks/useWifiAutoConnect'
import { useLocationMeta } from './hooks/useLocationMeta'
import { useCatalog } from './hooks/useCatalog'
import { useExternalChangeSubscriptions } from './hooks/useExternalChangeSubscriptions'
import { useGoldDittoSubscription } from './hooks/useGoldDittoSubscription'
import { useSimActions } from './hooks/useSimActions'
import { useMapClick } from './hooks/useMapClick'
import { useServices } from './contexts/ServicesContext'
import { useToast } from './hooks/useToast'
import UserAvatarPicker from './components/UserAvatarPicker'
import { UserAvatar, avatarToHtml, loadAvatar, saveAvatar, loadCustomPng, saveCustomPng } from './userAvatars'
import type { ApiGateway } from './contract/apiGateway'
import { parseCoord } from './utils/coords'
import { toastForFanout } from './utils/toast'

import MapView from './components/MapView'
import ControlPanel from './components/ControlPanel'
import DeviceStatus from './components/DeviceStatus'
import JoystickPad from './components/JoystickPad'
import EtaBar from './components/EtaBar'
import WaypointEditor from './components/WaypointEditor'
import StatusBar from './components/StatusBar'
import AppAddBookmarkDialog from './components/AppAddBookmarkDialog'
import BulkPasteDialog from './components/BulkPasteDialog'
import WaypointFlyDialog from './components/WaypointFlyDialog'
import RouteLoadDialog from './components/RouteLoadDialog'
import RoutePasteDialog from './components/RoutePasteDialog'
import { DeviceChipRow } from './components/DeviceChipRow'
import {
  CloudSyncBusyProvider, useCloudSyncBusy, useCloudSyncAfter,
} from './contexts/CloudSyncBusyContext'
import { CloudSyncBusyOverlay } from './components/CloudSyncBusyOverlay'

import { SimMode, MoveMode } from './hooks/useSimulation'

// One-time iCloud Drive discovery prompt. Fires on app start; skipped when
// cloud sync is already enabled, the prompt was previously dismissed, or
// iCloud Drive is not detected on this machine.
function useCloudSyncDiscovery(api: ApiGateway) {
  const t = useT()
  const { run } = useCloudSyncBusy()
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const s = await api.cloudSyncStatus()
      if (cancelled) return
      if (s.enabled || s.prompt_dismissed || !s.detected_icloud_path) return
      const ok = window.confirm(t('cloud_sync.discovery_prompt'))
      if (ok) {
        await run((signal) => api.cloudSyncEnable(undefined, signal))
      } else {
        await api.cloudSyncDismissPrompt()
      }
    })().catch(() => { /* swallow — non-fatal */ })
    return () => { cancelled = true }
  }, [t, run])
}

const SPEED_MAP: Record<MoveMode, number> = {
  walking: 10.8,
  running: 19.8,
  driving: 60,
}

const App: React.FC = () => {
  const t = useT()
  const { api, ws: router, sendMessage, connected } = useServices()
  useCloudSyncDiscovery(api)
  // Toast lives near the top so `showToast` is a stable reference BEFORE
  // useSimulation runs — its 3rd-arg callback (WiFi tunnel-recovered toast)
  // captures showToast, so it must already be declared here. No forward
  // reference to a later declaration.
  const { toastMsg, showToast, setToastMsg } = useToast()
  const device = useDevice(router)
  // Pass primary-device udid into useSimulation so its legacy single-device
  // setters only react to the primary's WS events in dual-device mode,
  // stopping the map marker from ping-ponging between both devices'
  // independently-jittered positions.
  // 3rd arg: positive "WiFi tunnel restored" toast on recovery.
  const sim = useSimulation(
    router,
    device.primaryDevice?.udid,
    () => showToast(t('wifi.tunnel_recovered')),
  )
  const joystick = useJoystick(sendMessage, sim.mode === SimMode.Joystick)
  const bm = useBookmarks()
  const categoryDatesByName = useMemo(
    () => Object.fromEntries(
      bm.categories.map(c => [c.name, {
        start_date: c.start_date ?? '',
        end_date: c.end_date ?? '',
      }]),
    ),
    [bm.categories],
  )

  // Saved-routes DATA + persistence CRUD live in useRoutes (api injected from
  // useServices). Sim-driving route handlers (load into sim / route-paste
  // teleport) stay in App and consume `routes.savedRoutes`.
  const routes = useRoutes(api)
  const savedRoutes = routes.savedRoutes
  const routeCategories = routes.routeCategories

  // Keep the cloud-sync busy overlay visible until bookmark + route data
  // has been re-fetched after a toggle, so panels never flash pre-merge
  // content. ONE combined closure (bm.refresh + routes.refresh) registered via
  // a single useCloudSyncAfter — do NOT add a second registration (last-writer
  // wins would clobber it).
  useCloudSyncAfter(useCallback(async () => {
    await Promise.all([bm.refresh(), routes.refresh()])
  }, [bm.refresh, routes.refresh]))
  // Bumped every time an external trigger (currently the map topleft
  // library button) wants ControlPanel to open its library panel.
  // ControlPanel reacts on change via useEffect, so we don't have to
  // lift the whole libraryOpen/libraryTab state here.
  const [openLibraryToken, setOpenLibraryToken] = useState(0)
  const [cooldown, setCooldown] = useState(0)
  const [cooldownEnabled, setCooldownEnabled] = useState(false)
  const [randomWalkRadius, setRandomWalkRadius] = useState(500)
  const [clickToAddWaypoint, setClickToAddWaypoint] = useState(false)
  const [showBookmarkPins, setShowBookmarkPinsRaw] = useState<boolean>(() => {
    try { return localStorage.getItem('locwarp.show_bookmark_pins') === '1' } catch { return false }
  })
  const setShowBookmarkPins = (v: boolean) => {
    setShowBookmarkPinsRaw(v)
    try { localStorage.setItem('locwarp.show_bookmark_pins', v ? '1' : '0') } catch { /* ignore */ }
  }
  // Gold Ditto (拉金盆) shared state. externalA receives a "lat, lng" coord
  // pushed in by the map right-click handler so the panel's A-input updates
  // without the user having to copy. We wrap the coord in an object so that
  // every set creates a fresh reference, even when the user picks the same
  // coord twice — the panel's useEffect dep then always re-fires. mapCenter
  // is fed by MapView's `moveend` event (and once on init) so the panel's
  // "use map center" B-button is always enabled with a fresh coord.
  const [goldDittoExternalA, setGoldDittoExternalA] = useState<{ coord: string } | null>(null)
  const [mapCenter, setMapCenter] = useState<{ lat: number; lng: number } | null>(null)
  // Active avatar selection + persistent custom-PNG slot. Stored in two
  // separate localStorage keys so picking a preset doesn't drop the user's
  // uploaded image.
  const [userAvatar, setUserAvatar] = useState<UserAvatar>(() => loadAvatar())
  const [customPng, setCustomPng] = useState<string | null>(() => loadCustomPng())
  const [avatarPickerOpen, setAvatarPickerOpen] = useState(false)
  const handleAvatarSave = useCallback((next: UserAvatar, nextCustom: string | null) => {
    setUserAvatar(next)
    saveAvatar(next)
    setCustomPng(nextCustom)
    saveCustomPng(nextCustom)
  }, [])
  // Reverse-geo / timezone / weather enrichment for the status bar lives in
  // useLocationMeta (api injected from useServices). The >=100m + sim-quiescent
  // gate + lastLookedUpPosRef debounce are preserved exactly inside the hook.
  const { locMeta } = useLocationMeta(api, sim.currentPosition, sim.status?.state)

  // Auto-refresh bookmarks / routes when the backend signals an external
  // change (cloud-sync watchdog picked up a file written by another device).
  const onBookmarksChanged = useCallback(() => { bm.refresh(); showToast(t('cloud_sync.toast_synced')) }, [bm.refresh, showToast, t])
  const onRoutesChanged = useCallback(() => { void routes.refresh(); showToast(t('cloud_sync.toast_routes_synced')) }, [routes.refresh, showToast, t])
  useExternalChangeSubscriptions(router, useMemo(() => ({ onBookmarks: onBookmarksChanged, onRoutes: onRoutesChanged }), [onBookmarksChanged, onRoutesChanged]))

  const [wpGenRadius, setWpGenRadius] = useState(300)
  const [wpGenCount, setWpGenCount] = useState(5)

  const generateWaypoints = useCallback((radius: number, count: number) => {
    if (!sim.currentPosition) {
      alert(t('toast.no_position_random'))
      return
    }
    const { lat, lng } = sim.currentPosition
    const latScale = 111320
    const lngScale = 111320 * Math.cos((lat * Math.PI) / 180)

    type Pt = { lat: number; lng: number; theta?: number }
    const pts: Pt[] = []
    for (let i = 0; i < count; i++) {
      const r = radius * Math.sqrt(Math.random())
      const theta = Math.random() * 2 * Math.PI
      pts.push({
        lat: lat + (r * Math.cos(theta)) / latScale,
        lng: lng + (r * Math.sin(theta)) / lngScale,
        theta,
      })
    }

    // Nearest-neighbor from current position → shorter total path
    const remaining = [...pts]
    const ordered: Pt[] = []
    let cx = lat, cy = lng
    while (remaining.length) {
      let bestIdx = 0, bestD = Infinity
      for (let i = 0; i < remaining.length; i++) {
        const dx = (remaining[i].lat - cx) * latScale
        const dy = (remaining[i].lng - cy) * lngScale
        const d = dx * dx + dy * dy
        if (d < bestD) { bestD = d; bestIdx = i }
      }
      const [next] = remaining.splice(bestIdx, 1)
      ordered.push(next)
      cx = next.lat; cy = next.lng
    }

    // Seed the list with the current position as index 0 so the start button
    // doesn't need to inject it later (and can't double-inject on re-click).
    sim.setWaypoints([
      { lat, lng },
      ...ordered.map(({ lat, lng }) => ({ lat, lng })),
    ])
  }, [sim, t])

  const handleGenerateRandomWaypoints = useCallback(() => {
    generateWaypoints(wpGenRadius, wpGenCount)
  }, [generateWaypoints, wpGenRadius, wpGenCount])

  const handleGenerateAllRandom = useCallback(() => {
    const radius = Math.floor(50 + Math.random() * 950)  // 50–1000 m
    const count = Math.floor(3 + Math.random() * 8)       // 3–10 點
    setWpGenRadius(radius)
    setWpGenCount(count)
    generateWaypoints(radius, count)
  }, [generateWaypoints])

  const handleToggleCooldown = useCallback((enabled: boolean) => {
    setCooldownEnabled(enabled)
    api.setCooldownEnabled(enabled).catch(() => setCooldownEnabled((v) => !v))
  }, [])

  // (Saved routes + categories load on mount inside useRoutes.)


  // (Reverse-geo / timezone / weather enrichment lives in useLocationMeta above.)

  // Auto-scan devices when WebSocket (re)connects (e.g. after backend restart)
  useEffect(() => {
    if (connected) {
      device.scan()
    }
  }, [connected])

  // Once-per-session WiFi auto-connect lives in useWifiAutoConnect (api +
  // device injected from useServices()/useDevice()). The savedips parse,
  // dedupe, cap-at-3 parallel attempts, and the run-once guard are all
  // preserved inside the hook; see its header for the full behavior notes.
  useWifiAutoConnect(connected, api, device)

  // Poll cooldown
  useEffect(() => {
    if (!connected) return
    const id = setInterval(() => {
      api.getCooldownStatus().then((s: any) => {
        setCooldown(s.remaining_seconds ?? 0)
        if (typeof s.enabled === 'boolean') setCooldownEnabled(s.enabled)
      }).catch(() => {})
    }, 2000)
    return () => clearInterval(id)
  }, [connected])

  // Leaflet wraps the world horizontally at very low zoom levels; clicking on
  // a "second copy" of a country yields lng outside [-180, 180]. Backend's
  // pydantic TeleportRequest bounds lng to [-180, 180] so the raw click
  // would 422. Normalize at the handler entry so every downstream call sees
  // a single canonical coordinate.
  const normalizeLng = (lng: number): number => {
    const n = ((lng + 180) % 360 + 360) % 360 - 180
    // ((180 + 180) % 360 + 360) % 360 - 180 == -180, but 180 is also valid.
    // Keep +180 if the input was exactly +180.
    return lng === 180 ? 180 : n
  }
  const clampLat = (lat: number): number => Math.max(-90, Math.min(90, lat))

  // Map left-click handler + the insert-after-waypoint mode it shares (state +
  // ESC listener) live in useMapClick (Phase 4b, task p4b1). clampLat /
  // normalizeLng are passed in so they stay the single source of truth shared
  // with the handlers that remain in App; `api` is injected for the dead
  // insert-after live-insert fan-out. NOTE: onInsertAfterWp is deliberately NOT
  // wired onto <MapView> (insert mode is dead from the UI, pinned by
  // App.dangerzone.test.tsx test 13) — handleInsertAfterWp is returned for
  // parity but stays unwired.
  const {
    insertAfterIndex,
    handleInsertAfterWp,
    cancelInsertMode,
    handleMapClick,
  } = useMapClick({ sim, device, api, clickToAddWaypoint, clampLat, normalizeLng })

  // Recent-destinations history (last 20 places the user flew to) lives in
  // useRecentPlaces (api injected from useServices). The background
  // reverse-geocode-and-re-push behavior + the mount/connected refresh gate are
  // preserved inside the hook.
  const recent = useRecentPlaces(api, connected)
  const recentPlaces = recent.recentPlaces
  const pushRecent = recent.pushRecent
  const clearRecentList = recent.clearRecentList

  // `source` lets the caller tag this flight for the recent-places
  // history: 'menu' (map right-click) is the default, 'coord' when the
  // coord-input overlay button fired us. The UI shows different labels
  // depending on source.
  // Preview pin state. Lives at App level so both the coord-input
  // overlay (inside MapView) and the bookmark-list (inside ControlPanel)
  // can drop / clear the same pin. Cleared automatically by any real
  // teleport so the amber "you're peeking" pin doesn't linger after the
  // GPS catches up to the same coordinate.
  const [previewPin, setPreviewPin] = useState<{ lat: number; lng: number } | null>(null)
  const clearPreviewPin = useCallback(() => setPreviewPin(null), [])

  // Simulation-action fan-out handlers (start / stop / pause / resume / teleport
  // / navigate / applySpeed / restore / startWaypointRoute). Extracted into
  // useSimActions so the single-vs-dual-device branch lives in ONE tested place;
  // child prop names are unchanged (FROZEN). clampLat / normalizeLng / setPreviewPin
  // are passed in so the handlers that stay in App share the same primitives.
  const simActions = useSimActions({
    sim, device, showToast, t, pushRecent, api,
    randomWalkRadius, clampLat, normalizeLng, setPreviewPin,
  })
  const {
    handleRestore, handleTeleport, handleNavigate,
    handleStart, handleStop, handleApplySpeed, handlePause, handleResume,
  } = simActions

  const mapApiRef = useRef<{ panTo: (lat: number, lng: number, zoom?: number) => void } | null>(null)
  const handleMapPanOnly = useCallback((lat: number, lng: number) => {
    const cl = clampLat(lat)
    const nl = normalizeLng(lng)
    mapApiRef.current?.panTo(cl, nl)
    setPreviewPin({ lat: cl, lng: nl })
  }, [])

  const [addBmDialog, setAddBmDialog] = useState<{
    lat: number; lng: number; name: string; category: string;
    countryCode?: string; nameResolving?: boolean;
  } | null>(null)

  const handleAddBookmark = useCallback((lat: number, lng: number, suggestedName?: string) => {
    // When the caller already knows a name (e.g. a recent-history entry
    // from a search), seed the dialog so reverse-geocode only fills the
    // country_code and won't overwrite the typed name — the existing
    // "if (prev.name.length > 0)" branch below already protects it.
    const seedName = (suggestedName || '').trim()
    setAddBmDialog({
      lat,
      lng,
      name: seedName,
      category: bm.categories[0]?.name || t('bm.default'),
      nameResolving: true,
    })
    // Reverse-geocode asynchronously to pre-fill the name + remember country.
    // User can still overwrite the suggestion. If the call fails we just leave
    // the field blank as before.
    ;(async () => {
      try {
        const geo = await api.reverseGeocode(lat, lng)
        if (!geo) {
          setAddBmDialog((prev) => prev ? { ...prev, nameResolving: false } : prev)
          return
        }
        const cc = String(geo.country_code ?? '').toLowerCase()
        // Backend now returns a clean `short_name` picked from POI / road /
        // area tags (ignoring noisy house-number leading segments like "6").
        // Fall back to first display_name segment only if short_name absent.
        const short = String(geo.short_name || '').trim()
          || String(geo.display_name || '').split(',')[0]?.trim()
          || ''
        setAddBmDialog((prev) => {
          if (!prev) return prev
          // Don't overwrite anything the user already typed.
          if (prev.name && prev.name.length > 0) {
            return { ...prev, countryCode: cc, nameResolving: false }
          }
          return { ...prev, name: short, countryCode: cc, nameResolving: false }
        })
      } catch {
        setAddBmDialog((prev) => prev ? { ...prev, nameResolving: false } : prev)
      }
    })()
  }, [bm.categories, t])

  const submitAddBookmark = useCallback(() => {
    if (!addBmDialog || !addBmDialog.name.trim()) return
    const cat = bm.categories.find(c => c.name === addBmDialog.category)
    bm.createBookmark({
      name: addBmDialog.name.trim(),
      lat: addBmDialog.lat,
      lng: addBmDialog.lng,
      category_id: cat?.id || 'default',
      country_code: addBmDialog.countryCode || '',
    } as any)
    setAddBmDialog(null)
  }, [addBmDialog, bm])

  // Bulk-paste bookmark dialog state. Per-line parser scrapes the first
  // valid lat/lng out of each line via parseCoord — extra label text on
  // the same line ("OK", "#3", "一般火", "(...)" brackets, etc.) is
  // dropped, lines without a coord pair count as invalid.
  const [bulkPasteOpen, setBulkPasteOpen] = useState(false)
  const [bulkPasteText, setBulkPasteText] = useState('')
  const [bulkPasteCategory, setBulkPasteCategory] = useState<string>(() => bm.categories[0]?.name || '預設')
  const [bulkPasteBusy, setBulkPasteBusy] = useState(false)
  const parseBulkPaste = useCallback((raw: string): { valid: Array<{ lat: number; lng: number }>; invalidCount: number; totalLines: number } => {
    const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0)
    const valid: Array<{ lat: number; lng: number }> = []
    let invalidCount = 0
    for (const line of lines) {
      const c = parseCoord(line)
      if (!c) { invalidCount++; continue }
      valid.push({ lat: c.lat, lng: c.lng })
    }
    return { valid, invalidCount, totalLines: lines.length }
  }, [])
  const submitBulkPaste = useCallback(async () => {
    const { valid } = parseBulkPaste(bulkPasteText)
    if (valid.length === 0) {
      showToast(t('bm.bulk_paste_empty'))
      return
    }
    setBulkPasteBusy(true)
    const cat = bm.categories.find((c) => c.name === bulkPasteCategory)
    const catId = cat?.id || 'default'
    let added = 0
    for (const entry of valid) {
      try {
        await bm.createBookmark({
          name: `${entry.lat.toFixed(5)}, ${entry.lng.toFixed(5)}`,
          lat: entry.lat,
          lng: entry.lng,
          category_id: catId,
          country_code: '',
        } as any)
        added++
      } catch { /* skip bad rows */ }
    }
    setBulkPasteBusy(false)
    setBulkPasteOpen(false)
    setBulkPasteText('')
    showToast(t('bm.bulk_paste_done').replace('{count}', String(added)))
  }, [bulkPasteText, bulkPasteCategory, bm, parseBulkPaste, t, showToast])

  const handleAddWaypoint = useCallback((lat: number, lng: number) => {
    // Seed the list with the current device position as the implicit start
    // point on the first add. This keeps backend route and UI list aligned
    // so waypoint-progress highlighting indexes correctly, and removes the
    // "start button injects current pos every click" footgun.
    const nlat = clampLat(lat)
    const nlng = normalizeLng(lng)
    sim.setWaypoints((prev: any[]) => {
      if (prev.length === 0 && sim.currentPosition) {
        return [
          { lat: sim.currentPosition.lat, lng: sim.currentPosition.lng },
          { lat: nlat, lng: nlng },
        ]
      }
      return [...prev, { lat: nlat, lng: nlng }]
    })
  }, [sim])

  const handleClearWaypoints = useCallback(() => {
    sim.setWaypoints([])
  }, [sim])

  const handleRemoveWaypoint = useCallback((index: number) => {
    sim.setWaypoints((prev: any[]) => prev.filter((_: any, i: number) => i !== index))
  }, [sim])

  // Move a waypoint up / down inside the Loop / MultiStop list. waypoints[0]
  // is the implicit start (current device position when the first add fired),
  // so it's pinned — we never let the user shuffle index 0, and other rows
  // can't be moved into position 0. Same idempotent pattern as the remove
  // handler: swap two entries inside the immutable list.
  const handleMoveWaypoint = useCallback((index: number, direction: -1 | 1) => {
    sim.setWaypoints((prev: any[]) => {
      const target = index + direction
      if (index <= 0 || target <= 0) return prev
      if (index >= prev.length || target >= prev.length) return prev
      const next = prev.slice()
      const tmp = next[index]
      next[index] = next[target]
      next[target] = tmp
      return next
    })
  }, [sim])

  // Trim the waypoint list so the chosen index becomes the new start.
  // Everything before `index` is dropped — the iPhone won't walk back
  // through them on the next Start press. Concretely: setting #9 as
  // start on a 1..15 route gives 9 → 10 → ... → 15 (and Loop wraps
  // back to 9, not to 1). User asked for trim (not rotate) so a
  // pause-and-resume-from-#9 flow doesn't re-walk #1..#8 at the end.
  const handleSetWpAsStart = useCallback(async (index: number) => {
    const wps = sim.waypoints
    if (index <= 0 || index >= wps.length) return
    const trimmed = wps.slice(index)
    sim.setWaypoints(trimmed)
    const start = trimmed[0]
    sim.setCurrentPosition({ lat: start.lat, lng: start.lng })
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length > 0) {
      try { await sim.teleportAll(udids, start.lat, start.lng) } catch { /* ignore */ }
    }
    void pushRecent(start.lat, start.lng, 'coord_teleport')
  }, [sim, device, pushRecent])

  // Teleport to a waypoint from inside the Loop / MultiStop list. We
  // go around sim.teleport (which flips sim.mode to Teleport and would
  // therefore wipe waypoints the next time the user clicks the Loop /
  // MultiStop mode tab). Talk directly to sim.teleportAll / api.
  // teleport so the current mode and the entire waypoint list stay
  // intact while the iPhone jumps to the chosen point.
  const [wpFlyConfirm, setWpFlyConfirm] = useState<{ lat: number; lng: number; index: number } | null>(null)
  const confirmWpFly = useCallback(async () => {
    if (!wpFlyConfirm) return
    const { lat, lng } = wpFlyConfirm
    sim.setCurrentPosition({ lat, lng })
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length > 0) {
      try { await sim.teleportAll(udids, lat, lng) } catch { /* ignore */ }
    }
    void pushRecent(lat, lng, 'coord_teleport')
    setWpFlyConfirm(null)
  }, [wpFlyConfirm, sim, device, pushRecent])

  // Route bulk-paste: parse a textarea of "lat lng [name]" lines into a
  // waypoint list for Loop / MultiStop. Current device position (if
  // any) is prepended as waypoint[0] so the backend's seg_idx math
  // lines up with the UI, matching handleAddWaypoint's contract.
  // Works identically in single- and dual-device modes because sim.
  // setWaypoints feeds both the global state and any fanout call site.
  const [routePasteOpen, setRoutePasteOpen] = useState(false)
  const [routePasteText, setRoutePasteText] = useState('')
  const parseRoutePaste = useCallback((raw: string): { valid: Array<{ lat: number; lng: number }>; invalidCount: number; totalLines: number } => {
    const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0)
    const valid: Array<{ lat: number; lng: number }> = []
    let invalidCount = 0
    for (const line of lines) {
      const c = parseCoord(line)
      if (!c) { invalidCount++; continue }
      valid.push({ lat: clampLat(c.lat), lng: normalizeLng(c.lng) })
    }
    return { valid, invalidCount, totalLines: lines.length }
  }, [])
  const submitRoutePaste = useCallback(async () => {
    const { valid } = parseRoutePaste(routePasteText)
    if (valid.length === 0) {
      showToast(t('panel.route_paste_empty'))
      return
    }
    // First pasted coord = route start. Teleport iPhone there so
    // waypoints[0] lines up with current GPS, BUT don't go through
    // handleTeleport / sim.teleport — those flip sim.mode back to
    // Teleport, which would then clear waypoints the moment the user
    // clicks Loop / MultiStop in the sidebar. Use the raw API + a
    // direct setCurrentPosition so the mode the user set (Loop /
    // MultiStop) stays intact.
    const first = valid[0]
    sim.setCurrentPosition({ lat: first.lat, lng: first.lng })
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length > 0) {
      try { await sim.teleportAll(udids, first.lat, first.lng) } catch { /* ignore */ }
    }
    sim.setWaypoints(valid)
    setRoutePasteOpen(false)
    setRoutePasteText('')
    showToast(t('panel.route_paste_done').replace('{count}', String(valid.length)))
  }, [routePasteText, parseRoutePaste, sim, device, t, showToast])

  // -- ControlPanel handlers --
  const [routeLoadConfirm, setRouteLoadConfirm] = useState<{ name: string; waypoints: { lat: number; lng: number }[] } | null>(null)
  const handleRouteLoad = useCallback((id: string) => {
    const route = savedRoutes.find((r) => r.id === id)
    if (!route || !Array.isArray(route.waypoints) || route.waypoints.length === 0) return
    const wps = route.waypoints.map((w: any) => ({ lat: w.lat, lng: w.lng }))
    setRouteLoadConfirm({ name: route.name ?? '', waypoints: wps })
  }, [savedRoutes])

  const confirmRouteLoad = useCallback(async (flyToStart: boolean) => {
    if (!routeLoadConfirm) return
    const { waypoints } = routeLoadConfirm
    sim.setWaypoints(waypoints)
    if (flyToStart && waypoints.length > 0) {
      const first = waypoints[0]
      const udids = device.connectedDevices.map((d) => d.udid)
      // Match wpFly flow: set current position + teleport directly (no sim.teleport,
      // so we preserve the mode the user is already in for this route).
      sim.setCurrentPosition({ lat: first.lat, lng: first.lng })
      if (udids.length > 0) {
        try { await sim.teleportAll(udids, first.lat, first.lng) } catch { /* ignore */ }
      }
      void pushRecent(first.lat, first.lng, 'coord_teleport')
    }
    setRouteLoadConfirm(null)
  }, [routeLoadConfirm, sim, device, pushRecent])

  // Thin App wrapper: supplies the sim DATA (waypoints + profile) + the
  // user-facing toasts; the persistence itself lives in routes.save.
  const handleRouteSave = useCallback(async (
    name: string,
    opts?: { categoryId?: string; overwriteId?: string },
  ) => {
    if (sim.waypoints.length === 0) {
      showToast(t('toast.route_need_waypoint'))
      return
    }
    try {
      const { overwritten } = await routes.save({
        name,
        waypoints: sim.waypoints,
        profile: sim.moveMode,
        categoryId: opts?.categoryId,
        overwriteId: opts?.overwriteId,
      })
      showToast(overwritten
        ? t('toast.route_overwritten', { name })
        : t('toast.route_saved', { name }))
    } catch (err: any) {
      showToast(t('toast.route_save_failed', { msg: err.message || '' }))
    }
  }, [sim, routes.save, showToast, t])

  const handleRoutesBulkDelete = useCallback(async (ids: string[]) => {
    try {
      await routes.bulkDelete(ids)
      showToast(t('toast.route_bulk_deleted', { n: ids.length }))
    } catch (err: any) {
      showToast(err.message || t('toast.route_delete_failed'))
    }
  }, [routes.bulkDelete, showToast, t])

  const handleRouteMove = useCallback(async (ids: string[], targetCategoryId: string) => {
    try {
      await routes.move(ids, targetCategoryId)
    } catch (err: any) {
      showToast(err.message || 'move failed')
    }
  }, [routes.move, showToast])

  const handleRouteCategoryAdd = useCallback(async (name: string, color = '#6c8cff') => {
    try {
      await routes.categoryAdd(name, color)
    } catch (err: any) {
      showToast(err.message || 'category add failed')
    }
  }, [routes.categoryAdd, showToast])

  const handleRouteCategoryDelete = useCallback(async (id: string) => {
    try {
      await routes.categoryDelete(id)
    } catch (err: any) {
      showToast(err.message || 'category delete failed')
    }
  }, [routes.categoryDelete, showToast])

  const handleRouteCategoryRename = useCallback(async (id: string, name: string) => {
    try {
      await routes.categoryRename(id, name)
    } catch (err: any) {
      showToast(err.message || 'category rename failed')
    }
  }, [routes.categoryRename, showToast])

  const handleRouteCategoryRecolor = useCallback(async (id: string, color: string) => {
    try {
      await routes.categoryRecolor(id, color)
    } catch (err: any) {
      showToast(err.message || 'category recolor failed')
    }
  }, [routes.categoryRecolor, showToast])

  const handleGpxImport = useCallback(async (file: File) => {
    try {
      const res = await routes.importGpx(file)
      showToast(t('toast.gpx_imported', { n: res.points }))
    } catch (err: any) {
      showToast(t('toast.gpx_import_failed', { msg: err.message || '' }))
    }
  }, [routes.importGpx, showToast, t])

  const handleGpxExport = useCallback((id: string) => {
    routes.exportGpx(id)
  }, [routes.exportGpx])

  const handleRoutesImportAll = useCallback(async (file: File) => {
    try {
      const res = await routes.importAll(file)
      showToast(t('toast.routes_imported', { n: res.imported }))
    } catch (err: any) {
      showToast(t('toast.routes_import_failed', { msg: err.message || '' }))
    }
  }, [routes.importAll, showToast, t])

  // Gold Ditto: map right-click → push lat,lng into the panel's A field.
  // Wrap in an object so every set creates a new reference; the panel's
  // useEffect will fire even if the user picks the same coord twice in a
  // row (otherwise the dep array wouldn't change).
  const handleSetGoldDittoA = useCallback((lat: number, lng: number) => {
    setGoldDittoExternalA({ coord: `${lat.toFixed(6)}, ${lng.toFixed(6)}` })
  }, [])

  // Gold Ditto: "Confirm Location" = simple teleport to A. Reuses the
  // same fanout / single-device split as handleTeleport so multi-device
  // setups still get a fan-out toast.
  const handleGoldDittoConfirm = useCallback(async (lat: number, lng: number) => {
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length >= 2) {
      sim.setCurrentPosition({ lat, lng })
      const outcome = await sim.teleportAll(udids, lat, lng)
      showToast(toastForFanout(t, t('mode.goldditto'), outcome, device.connectedDevices))
    } else {
      sim.teleport(lat, lng)
    }
  }, [sim, device, t, showToast])

  // Gold Ditto cycle. Adapter: GoldDittoPanel.onCycle splits target out
  // of args, but useSimulation.goldDittoCycleAll wants target merged in.
  // Re-merge here at the boundary.
  const handleGoldDittoCycle = useCallback(async (
    target: 'A' | 'B' | 'auto',
    args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
  ) => {
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length === 0) return
    const outcome = await sim.goldDittoCycleAll(udids, { target, ...args })
    if (udids.length >= 2) {
      showToast(toastForFanout(t, t('mode.goldditto'), outcome, device.connectedDevices))
    }
  }, [sim, device, t, showToast])

  // Subscribe to backend goldditto_cycle phase events via typed WsRouter.
  // Extracted into useGoldDittoSubscription for testability; countdown ref
  // and setInterval logic live there.
  useGoldDittoSubscription(router, useMemo(() => ({ t, showToast }), [t, showToast]))

  const handleOpenLog = useCallback(async () => {
    try {
      // Open the folder, not the file — log can be large and copy/paste
      // from a multi-MB Notepad window is painful. Folder lets the user
      // attach the file directly to the Issue.
      await api.openLogFolder()
    } catch (err: any) {
      showToast(t('status.open_log_failed') + (err?.message ? `: ${err.message}` : ''))
    }
  }, [showToast, t])

  const handleBookmarkImport = useCallback(async (file: File) => {
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const res = await api.importBookmarks(data)
      await bm.refresh()
      showToast(t('bm.import_success', { n: res.imported }))
    } catch (err: any) {
      showToast(t('bm.import_failed', { error: err?.message || 'unknown' }))
    }
  }, [bm, showToast, t])

  // Bundled public-event catalog state + force-sync live in useCatalog (api
  // injected from useServices). The mount fetch, catalogNewCount diff vs the
  // current bookmarks, and the re-entrancy guard are preserved inside the hook;
  // App keeps the toast / i18n / post-sync bm.refresh wrapper below (matching the
  // useRoutes convention of keeping user-facing messaging in App).
  const cat = useCatalog(api, bm.bookmarks)
  const catalogStatus = cat.catalogStatus
  const catalogError = cat.catalogError
  const catalogNewCount = cat.catalogNewCount
  const catalogRefreshing = cat.catalogRefreshing

  const handleCatalogRefresh = useCallback(async () => {
    try {
      // refresh() is a no-op (returns null) when there's no catalog loaded or a
      // sync is already in flight — same guard the inline handler had, so no
      // toast fires in those cases.
      const res = await cat.refresh()
      if (!res) return
      await bm.refresh()
      showToast(t('bm.catalog.synced', {
        added: res.added,
        updated: res.updated,
        resurrected: res.resurrected,
      }))
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t('bm.catalog.failed'))
    }
  }, [cat, bm, showToast, t])

  const handleRouteRename = useCallback(async (id: string, name: string) => {
    try {
      await routes.rename(id, name)
    } catch (err: any) {
      showToast(err.message || t('toast.route_rename_failed'))
    }
  }, [routes.rename, showToast, t])

  const handleRouteDelete = useCallback(async (id: string) => {
    try {
      await routes.remove(id)
      showToast(t('toast.route_deleted'))
    } catch (err: any) {
      showToast(err.message || t('toast.route_delete_failed'))
    }
  }, [routes.remove, showToast, t])

  // Build props for components
  const currentPos = sim.currentPosition
    ? { lat: sim.currentPosition.lat, lng: sim.currentPosition.lng }
    : null

  const destPos = sim.destination
    ? { lat: sim.destination.lat, lng: sim.destination.lng }
    : null

  // Mode default km/h, used only for ControlPanel's in-panel preset
  // preview and as a very last fallback in the status bar before any
  // apply / sim start has happened.
  const speed = SPEED_MAP[sim.moveMode] || 10.8
  // Status-bar display: always show what the backend is actually
  // executing (effectiveSpeed, set on sim start / applySpeed /
  // initialized to walking default). Selecting a preset or typing a
  // custom km/h no longer changes the display until the user clicks
  // 套用 (apply-speed) or starts a new sim, which matches the user's
  // mental model of "what's running on the iPhone".
  const fmtSpeedFromInputs = (kmh: number | null, lo: number | null, hi: number | null): number | string => {
    if (lo != null && hi != null) return `${Math.min(lo, hi)}~${Math.max(lo, hi)}`
    if (kmh != null) return kmh
    return SPEED_MAP[sim.moveMode] || 10.8
  }
  const displaySpeed: number | string = sim.effectiveSpeed
    ? fmtSpeedFromInputs(sim.effectiveSpeed.kmh, sim.effectiveSpeed.min, sim.effectiveSpeed.max)
    : SPEED_MAP[sim.moveMode] || 10.8

  // Determine running/paused state from status
  const isRunning = sim.status.running
  const isPaused = sim.status.paused

  // Memoized so MapView's bookmarkByCoord lookup memo isn't invalidated
  // on every parent render. Re-derives only when bm.bookmarks changes.
  const bookmarkPins = useMemo(
    () => bm.bookmarks.map((b: any) => ({
      id: b.id,
      name: b.name,
      lat: b.lat,
      lng: b.lng,
      country_code: b.country_code || '',
      city: b.city || undefined,
      timezone: b.timezone || undefined,
    })),
    [bm.bookmarks]
  )

  return (
    <div className="app-layout">
      <div className="noise-overlay" aria-hidden />
      <div className="sidebar">
        <div className="sidebar-content">
        <DeviceChipRow
          devices={device.connectedDevices}
          runtimes={sim.runtimes}
          onAdd={() => {
            if (device.connectedDevices.length >= 2) {
              setToastMsg(t('device.max_reached'))
              return
            }
            device.scan()
          }}
          onDisconnect={(udid) => { device.disconnect(udid) }}
          onForget={async (udid) => {
            try {
              await api.forgetDevice(udid)
            } catch (e) {
              console.error('forget failed', e)
            }
            // disconnect() is a safe no-op on an already-forgotten udid;
            // reused here for its listDevices() + setConnectedDevice(null)
            // refresh. NOT device.scan() — scan auto-connects when exactly
            // one device remains, which is wrong right after a forget.
            device.disconnect(udid)
          }}
          onRestoreOne={async (udid) => {
            try {
              await api.restoreSim(udid)
              setToastMsg(t('status.restore_success'))
            } catch (e: any) {
              setToastMsg(e?.message ?? 'restore failed')
            }
          }}
        />
        {/* `device` is the currently-connected device (lockdown succeeded), so pair_status is always "ok"; omit it. */}
        <DeviceStatus
          device={device.connectedDevice ? {
            id: device.connectedDevice.udid,
            udid: device.connectedDevice.udid,
            name: device.connectedDevice.name,
            iosVersion: device.connectedDevice.ios_version,
            connectionType: device.connectedDevice.connection_type,
            developerModeEnabled: device.connectedDevice.developer_mode_enabled,
          } : null}
          devices={device.devices.map(d => ({
            id: d.udid,
            udid: d.udid,
            name: d.name,
            iosVersion: d.ios_version,
            connectionType: d.connection_type,
            developerModeEnabled: d.developer_mode_enabled,
            pair_status: d.pair_status,
            pair_error: d.pair_error,
          }))}
          isConnected={device.connectedDevice !== null}
          onScan={() => { device.scan() }}
          onSelect={(id: string) => { device.connect(id) }}
          onStartWifiTunnel={device.startWifiTunnel}
          onStopTunnel={device.stopTunnel}
          tunnelStatus={device.tunnelStatus}
          tunnels={device.tunnels}
          onRevealDeveloperMode={async (udid: string) => {
            try {
              await api.amfiRevealDeveloperMode(udid)
              showToast(t('dev_mode.reveal_success'))
              // Refresh so the button hides once the user actually enables
              // dev mode in Settings and reconnects.
              await device.scan()
            } catch (err: any) {
              showToast(t('dev_mode.reveal_failed') + (err?.message ? `: ${err.message}` : ''))
            }
          }}
        />
        <ControlPanel
          simMode={sim.mode}
          moveMode={sim.moveMode}
          speed={speed}
          isRunning={isRunning}
          isPaused={isPaused}
          currentPosition={currentPos}
          onModeChange={sim.setMode}
          onSpeedChange={(s: number) => {
            if (s <= 10.8) sim.setMoveMode(MoveMode.Walking)
            else if (s <= 19.8) sim.setMoveMode(MoveMode.Running)
            else sim.setMoveMode(MoveMode.Driving)
          }}
          onMoveModeChange={sim.setMoveMode}
          customSpeedKmh={sim.customSpeedKmh}
          onCustomSpeedChange={sim.setCustomSpeedKmh}
          speedMinKmh={sim.speedMinKmh}
          onSpeedMinChange={sim.setSpeedMinKmh}
          speedMaxKmh={sim.speedMaxKmh}
          onSpeedMaxChange={sim.setSpeedMaxKmh}
          onStart={handleStart}
          onStop={handleStop}
          onPause={handlePause}
          onResume={handleResume}
          onRestore={handleRestore}
          onApplySpeed={handleApplySpeed}
          waypointProgress={sim.waypointProgress}
          onTeleport={handleTeleport}
          onNavigate={handleNavigate}
          onAddressSelect={async (lat, lng, name) => {
            const latN = clampLat(lat)
            const lngN = normalizeLng(lng)
            const udids = device.connectedDevices.map((d) => d.udid)
            if (udids.length >= 2) {
              sim.setCurrentPosition({ lat: latN, lng: lngN })
              const outcome = await sim.teleportAll(udids, latN, lngN)
              showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
            } else {
              sim.teleport(latN, lngN)
            }
            void pushRecent(latN, lngN, 'search', name)
          }}
          bookmarks={bm.bookmarks.map((b: any) => ({
            id: b.id,
            name: b.name,
            lat: b.lat,
            lng: b.lng,
            category: bm.categories.find(c => c.id === b.category_id)?.name || t('bm.default'),
            country_code: b.country_code || '',
            timezone: b.timezone || '',
            city: b.city || '',
            region: b.region || '',
            created_at: b.created_at || '',
            last_used_at: b.last_used_at || '',
          }))}
          bookmarkCategories={bm.categories.map(c => c.name)}
          bookmarksRaw={bm.bookmarks.map((b: any) => ({
            id: b.id,
            name: b.name,
            lat: b.lat,
            lng: b.lng,
            category_id: b.category_id,
          }))}
          bookmarkCategoriesFull={bm.categories.map(c => ({ id: c.id, name: c.name }))}
          bookmarkCategoryColors={Object.fromEntries(bm.categories.map(c => [c.name, c.color || '']))}
          onBookmarkClick={(b: any) => handleMapPanOnly(b.lat, b.lng)}
          onSetAsGoldDittoA={handleSetGoldDittoA}
          onAddWaypoint={handleAddWaypoint}
          deviceConnected={device.connectedDevice !== null}
          showWaypointOption={sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop || sim.mode === SimMode.Navigate}
          onShowToast={showToast}
          onBookmarkAdd={(b: any) => {
            const cat = bm.categories.find(c => c.name === b.category)
            // Country / timezone / city / region are resolved offline by
            // the backend on create — no online reverse-geocode needed.
            bm.createBookmark({
              name: b.name,
              lat: b.lat,
              lng: b.lng,
              category_id: cat?.id || 'default',
            } as any)
          }}
          onBookmarkDelete={(id: string) => bm.deleteBookmark(id)}
          onBookmarkEdit={(id: string, data: any) => {
            // BookmarkList emits UI-shape patches ({name}, or {name,lat,lng,category}).
            // Backend PUT /api/bookmarks requires the full Bookmark schema with
            // category_id (not category name), so merge the patch onto the
            // original and translate category name -> id before sending.
            //
            // If orig is missing (bm.bookmarks briefly out of sync with a
            // background refresh), fall back to the patch data — the edit
            // dialog supplies a full bookmark via spread so we still have the
            // fields we need.
            //
            // The backend re-resolves country / timezone / city / region
            // offline whenever the coordinates change, so the frontend no
            // longer reverse-geocodes here.
            const orig = bm.bookmarks.find(b => b.id === id)
            const patch: any = orig ? { ...orig } : { ...data, id }
            if (data.name != null) patch.name = data.name
            if (data.lat != null) patch.lat = data.lat
            if (data.lng != null) patch.lng = data.lng
            if (data.category != null) {
              const cat = bm.categories.find(c => c.name === data.category)
              if (cat) patch.category_id = cat.id
            }
            bm.updateBookmark(id, patch)
          }}
          onCategoryAdd={(name: string) => {
            // Pick a random preset color at creation so different categories
            // start visually distinct; the color is persisted and stays put
            // across rename (was previously hashed from name → jumped on rename).
            const palette = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#3b82f6', '#6366f1', '#a855f7', '#ec4899', '#64748b']
            const color = palette[Math.floor(Math.random() * palette.length)]
            bm.createCategory({ name, color })
          }}
          onCategoryDelete={(name: string) => {
            const cat = bm.categories.find(c => c.name === name)
            if (cat) bm.deleteCategory(cat.id)
          }}
          onCategoryEdit={(oldName: string, patch) => {
            const cat = bm.categories.find(c => c.name === oldName);
            if (!cat) return;
            // Default category is immutable.
            if (cat.id === 'default') return;
            bm.updateCategory(cat.id, {
              name: patch.name,
              color: patch.color,
              start_date: patch.start_date,
              end_date: patch.end_date,
            });
          }}
          categoryDates={categoryDatesByName}
          bookmarkShowOnMap={showBookmarkPins}
          onBookmarkShowOnMapChange={setShowBookmarkPins}
          onBookmarkImport={handleBookmarkImport}
          catalogStatus={catalogStatus}
          catalogNewCount={catalogNewCount}
          catalogError={catalogError}
          catalogRefreshing={catalogRefreshing}
          onCatalogRefresh={handleCatalogRefresh}
          onBookmarkBulkPaste={() => {
            setBulkPasteText('')
            setBulkPasteCategory(bm.categories[0]?.name || '預設')
            setBulkPasteOpen(true)
          }}
          bookmarkExportUrl={api.bookmarksExportUrl()}
          savedRoutes={savedRoutes.map(r => ({
            id: r.id,
            name: r.name,
            waypoints: r.waypoints ?? [],
            profile: r.profile,
            category_id: r.category_id || 'default',
            created_at: r.created_at,
            updated_at: r.updated_at,
          }))}
          routeCategories={routeCategories}
          onRouteGpxImport={handleGpxImport}
          onRouteGpxExport={handleGpxExport}
          onRoutesImportAll={handleRoutesImportAll}
          routesExportAllUrl={api.exportAllRoutesUrl()}
          onRouteRename={handleRouteRename}
          onRouteDelete={handleRouteDelete}
          onRoutesBulkDelete={handleRoutesBulkDelete}
          onRouteMove={handleRouteMove}
          onRouteLoad={handleRouteLoad}
          onRouteSave={handleRouteSave}
          onRouteCategoryAdd={handleRouteCategoryAdd}
          onRouteCategoryDelete={handleRouteCategoryDelete}
          onRouteCategoryRename={handleRouteCategoryRename}
          onRouteCategoryRecolor={handleRouteCategoryRecolor}
          randomWalkRadius={randomWalkRadius}
          pauseRandomWalk={sim.pauseRandomWalk}
          onPauseRandomWalkChange={sim.setPauseRandomWalk}
          onRandomWalkRadiusChange={setRandomWalkRadius}
          currentWaypointsCount={sim.waypoints.length}
          straightLine={sim.straightLine}
          onStraightLineChange={sim.setStraightLine}
          routeEngine={sim.routeEngine}
          onRouteEngineChange={sim.setRouteEngine}
          clickToAddWaypoint={clickToAddWaypoint}
          onClickToAddWaypointChange={setClickToAddWaypoint}
          jumpMode={sim.jumpMode}
          onJumpModeChange={sim.setJumpMode}
          jumpInterval={sim.jumpInterval}
          onJumpIntervalChange={sim.setJumpInterval}
          openLibraryToken={openLibraryToken}
          goldDittoConnectedUdids={device.connectedDevices.map((d) => d.udid)}
          goldDittoCycling={sim.goldDittoCycling}
          goldDittoMapCenter={mapCenter}
          goldDittoExternalA={goldDittoExternalA}
          onGoldDittoConfirm={handleGoldDittoConfirm}
          onGoldDittoCycle={handleGoldDittoCycle}
          goldDittoBookmarks={bm.bookmarks}
          goldDittoCategories={bm.categories}
          onCategoryDeleteCascade={(categoryId: string) =>
            bm.deleteCategory(categoryId, true)
          }
          modeExtraSection={(sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop) ? (
            <WaypointEditor
              mode={sim.mode}
              waypoints={sim.waypoints}
              waypointProgress={sim.waypointProgress}
              statusRunning={sim.status?.running}
              pauseLoop={sim.pauseLoop}
              pauseMultiStop={sim.pauseMultiStop}
              setPauseLoop={sim.setPauseLoop}
              setPauseMultiStop={sim.setPauseMultiStop}
              loopLapCount={sim.loopLapCount}
              setLoopLapCount={sim.setLoopLapCount}
              lapProgress={sim.lapProgress}
              wpGenRadius={wpGenRadius}
              wpGenCount={wpGenCount}
              setWpGenRadius={setWpGenRadius}
              setWpGenCount={setWpGenCount}
              moveMode={sim.moveMode}
              routeEngine={sim.routeEngine}
              onGenerateRandomWaypoints={handleGenerateRandomWaypoints}
              onGenerateAllRandom={handleGenerateAllRandom}
              onMoveWaypoint={handleMoveWaypoint}
              onRemoveWaypoint={handleRemoveWaypoint}
              onClearWaypoints={handleClearWaypoints}
              setWaypoints={sim.setWaypoints}
              onFlyToWaypoint={setWpFlyConfirm}
              onOpenBulkPaste={() => { setRoutePasteText(''); setRoutePasteOpen(true); }}
              showToast={showToast}
              onOptimize={api.routeOptimize}
            />
          ) : null}
        />

        </div>
      </div>
      <div className="map-container">
        <EtaBar
          runtimes={sim.runtimes}
          state={sim.status?.state ?? 'idle'}
          progress={sim.progress}
          remainingDistance={sim.status?.distance_remaining ?? 0}
          traveledDistance={sim.status?.distance_traveled ?? 0}
          eta={sim.eta ?? 0}
        />
        {sim.ddiMounting && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              zIndex: 10000,
              background: 'rgba(20, 22, 32, 0.85)',
              backdropFilter: 'blur(3px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'auto',
            }}
          >
            <div
              style={{
                background: '#23232a',
                border: '1px solid #3a3a42',
                borderRadius: 8,
                padding: '20px 28px',
                maxWidth: 420,
                textAlign: 'center',
                boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
              }}
            >
              <svg
                width="32" height="32" viewBox="0 0 24 24" fill="none"
                stroke="#6c8cff" strokeWidth="2"
                style={{ animation: 'spin 1s linear infinite', margin: '0 auto 10px' }}
              >
                <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="16" />
              </svg>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>
                {t('ddi.mounting_title')}
              </div>
              <div style={{ fontSize: 12, opacity: 0.75, lineHeight: 1.6 }}>
                {t('ddi.mounting_hint')}
              </div>
              {sim.ddiStage && (() => {
                // Stage labels mapped 1:1 with backend emit() calls in
                // _staged_personalized_mount. Fall back to the raw key
                // if we ever add a stage the UI hasn't learnt yet.
                const stageKey = `ddi.stage_${sim.ddiStage.stage}` as any
                const stageLabel = t(stageKey) || sim.ddiStage.stage
                // Typical total 15-45 s. Use a coarse ETA bucket so it
                // doesn't stress the user with a precise countdown that
                // isn't going to be accurate anyway.
                const elapsed = sim.ddiStage.elapsed
                let etaHint = ''
                if (elapsed < 5) etaHint = t('ddi.eta_starting')
                else if (elapsed < 20) etaHint = t('ddi.eta_continuing')
                else if (elapsed < 60) etaHint = t('ddi.eta_slow')
                else etaHint = t('ddi.eta_very_slow')
                // Rough stage index for progress bar fill.
                const order = ['starting','downloading','verifying','signing','uploading','mounting']
                const idx = Math.max(0, order.indexOf(sim.ddiStage.stage))
                const pct = Math.round(((idx + 1) / order.length) * 100)
                return (
                  <div style={{ marginTop: 14 }}>
                    <div style={{
                      height: 6, background: 'rgba(255,255,255,0.08)',
                      borderRadius: 99, overflow: 'hidden', marginBottom: 8,
                    }}>
                      <div style={{
                        width: `${pct}%`, height: '100%',
                        background: 'linear-gradient(90deg, #6c8cff, #4c6bd9)',
                        transition: 'width 300ms ease-out',
                      }} />
                    </div>
                    <div style={{ fontSize: 11, opacity: 0.85, fontWeight: 600 }}>
                      {stageLabel}
                    </div>
                    <div style={{ fontSize: 10, opacity: 0.55, marginTop: 2 }}>
                      {Math.round(elapsed)}s · {etaHint}
                    </div>
                  </div>
                )
              })()}
            </div>
          </div>
        )}
        {sim.pauseRemaining != null && sim.pauseRemaining > 0 && (
          <div
            style={{
              position: 'absolute',
              top: 38,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 901,
              background: 'rgba(255, 152, 0, 0.95)',
              color: '#1a1a1a',
              padding: '6px 14px',
              borderRadius: 18,
              fontSize: 12,
              fontWeight: 600,
              boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="4" width="4" height="16" rx="1" />
              <rect x="14" y="4" width="4" height="16" rx="1" />
            </svg>
            {t('toast.pause_countdown', { n: sim.pauseRemaining })}
          </div>
        )}
        {insertAfterIndex !== null && (
          <div
            style={{
              position: 'absolute',
              top: 38,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 901,
              background: 'rgba(108, 140, 255, 0.95)',
              color: '#fff',
              padding: '6px 14px',
              borderRadius: 18,
              fontSize: 12,
              fontWeight: 600,
              boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span>
              {t('panel.wp_insert_banner', {
                label: insertAfterIndex === 0
                  ? t('panel.waypoint_start')
                  : `#${insertAfterIndex}`,
              })}
            </span>
            <button
              onClick={cancelInsertMode}
              style={{
                background: 'rgba(255,255,255,0.18)', color: '#fff',
                border: '1px solid rgba(255,255,255,0.4)', borderRadius: 4,
                padding: '2px 8px', fontSize: 11, cursor: 'pointer',
              }}
            >{t('panel.wp_insert_cancel')}</button>
          </div>
        )}
        <MapView
          runtimes={sim.runtimes}
          devices={device.connectedDevices}
          currentPosition={currentPos}
          destination={destPos}
          waypoints={sim.waypoints.map((w, i) => ({ ...w, index: i }))}
          routePath={sim.routePath}
          randomWalkRadius={
            sim.mode === SimMode.RandomWalk ? randomWalkRadius :
            (sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop) ? wpGenRadius :
            null
          }
          onMapClick={handleMapClick}
          onTeleport={handleTeleport}
          onNavigate={handleNavigate}
          onAddBookmark={handleAddBookmark}
          onAddWaypoint={handleAddWaypoint}
          onSetAsGoldDittoA={handleSetGoldDittoA}
          showWaypointOption={sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop || sim.mode === SimMode.Navigate}
          deviceConnected={device.connectedDevice !== null}
          onShowToast={showToast}
          userAvatarHtml={avatarToHtml(userAvatar, customPng)}
          bookmarkPins={bookmarkPins}
          showBookmarkPins={showBookmarkPins}
          onMapReady={(api) => { mapApiRef.current = api }}
          previewPin={previewPin}
          onPreviewPinClear={clearPreviewPin}
          onCoordPreview={handleMapPanOnly}
          recentPlaces={recentPlaces}
          onRecentReFly={(entry) => {
            const isNavigate = entry.kind === 'navigate' || entry.kind === 'coord_navigate'
            if (isNavigate) handleNavigate(entry.lat, entry.lng)
            else handleTeleport(entry.lat, entry.lng)
          }}
          onRecentClear={clearRecentList}
          onOpenLibrary={() => setOpenLibraryToken((t) => t + 1)}
          isRunning={isRunning}
          isPaused={isPaused}
          onStart={handleStart}
          onStop={handleStop}
          onPause={handlePause}
          onResume={handleResume}
          showBulkPasteOnMap={sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop}
          onBulkPasteOpen={() => { setRoutePasteText(''); setRoutePasteOpen(true); }}
          onMapCenterChange={(lat, lng) => setMapCenter({ lat, lng })}
        />
        {avatarPickerOpen && (
          <UserAvatarPicker
            avatar={userAvatar}
            customPng={customPng}
            onSave={handleAvatarSave}
            onClose={() => setAvatarPickerOpen(false)}
            onShowToast={showToast}
          />
        )}
        {sim.mode === SimMode.Joystick && (
          <JoystickPad
            direction={joystick.direction}
            intensity={joystick.intensity}
            onMove={joystick.updateFromPad}
            onRelease={() => joystick.updateFromPad(0, 0)}
          />
        )}
        <AppAddBookmarkDialog
          dialog={addBmDialog}
          categories={bm.categories.map((c) => c.name)}
          onNameChange={(name) => setAddBmDialog((prev) => prev ? { ...prev, name } : prev)}
          onCategoryChange={(category) => setAddBmDialog((prev) => prev ? { ...prev, category } : prev)}
          onSubmit={submitAddBookmark}
          onClose={() => setAddBmDialog(null)}
        />
        <BulkPasteDialog
          open={bulkPasteOpen}
          text={bulkPasteText}
          category={bulkPasteCategory}
          categories={bm.categories.map((c) => c.name)}
          busy={bulkPasteBusy}
          parse={parseBulkPaste}
          onTextChange={setBulkPasteText}
          onCategoryChange={setBulkPasteCategory}
          onSubmit={submitBulkPaste}
          onClose={() => { setBulkPasteOpen(false); setBulkPasteText('') }}
        />
        <WaypointFlyDialog
          confirm={wpFlyConfirm}
          onSetAsStart={(idx) => { setWpFlyConfirm(null); void handleSetWpAsStart(idx) }}
          onConfirm={confirmWpFly}
          onClose={() => setWpFlyConfirm(null)}
        />
        <RouteLoadDialog
          confirm={routeLoadConfirm}
          onConfirm={(flyToStart) => void confirmRouteLoad(flyToStart)}
          onClose={() => setRouteLoadConfirm(null)}
        />
        <RoutePasteDialog
          open={routePasteOpen}
          text={routePasteText}
          parse={parseRoutePaste}
          onTextChange={setRoutePasteText}
          onSubmit={submitRoutePaste}
          onClose={() => { setRoutePasteOpen(false); setRoutePasteText('') }}
          onClipboardBlocked={() => showToast(t('panel.route_paste_clipboard_blocked'))}
        />
        {sim.error && (
          <div
            style={{
              position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
              zIndex: 2000, background: '#e53935', color: '#fff', padding: '8px 20px',
              borderRadius: 6, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
              cursor: 'pointer', maxWidth: '80%', textAlign: 'center',
            }}
            onClick={sim.clearError}
          >
            {sim.error}
          </div>
        )}
        {/* Transient amber "reconnecting…" banner for the backend's tunnel
            retry window. Naturally exclusive with the red error banner
            (degraded → reconnecting; recovered → clear; lost → error), but
            gate on !sim.error so a terminal banner always wins. */}
        {sim.tunnelReconnecting && !sim.error && (
          <div
            style={{
              position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
              zIndex: 2000, background: '#f59e0b', color: '#1a1d22', padding: '8px 20px',
              borderRadius: 6, fontSize: 13, fontWeight: 600,
              boxShadow: '0 4px 12px rgba(0,0,0,0.4)', maxWidth: '80%', textAlign: 'center',
            }}
          >
            {t('wifi.tunnel_reconnecting')}
          </div>
        )}
        <StatusBar
          runtimes={sim.runtimes}
          devices={device.connectedDevices}
          isConnected={device.connectedDevice !== null}
          deviceName={device.connectedDevice?.name ?? ''}
          iosVersion={device.connectedDevice?.ios_version ?? ''}
          currentPosition={currentPos}
          speed={displaySpeed}
          mode={sim.mode}
          cooldown={cooldown}
          cooldownEnabled={cooldownEnabled}
          onToggleCooldown={handleToggleCooldown}
          onRestore={handleRestore}
          onOpenLog={handleOpenLog}
          dualDevice={device.connectedDevices.length >= 2}
          countryCode={locMeta.countryCode}
          cityName={locMeta.cityName}
          weatherCode={locMeta.weatherCode}
          tempC={locMeta.tempC}
          timezoneZone={locMeta.timezoneZone}
          gmtOffsetSeconds={locMeta.gmtOffsetSeconds}
          onOpenAvatarPicker={() => setAvatarPickerOpen((v) => !v)}
          onLocatePcFly={handleTeleport}
          onLocatePcPanOnly={handleMapPanOnly}
        />

        {toastMsg && (
          <div
            key={toastMsg}
            className="anim-fade-slide-down"
            style={{
              position: 'fixed',
              top: 72,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 1500,
              background: 'rgba(26, 29, 39, 0.92)',
              backdropFilter: 'blur(10px)',
              WebkitBackdropFilter: 'blur(10px)',
              color: '#fff',
              padding: '10px 18px',
              borderRadius: 10,
              fontSize: 13,
              fontWeight: 500,
              letterSpacing: '-0.005em',
              boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.06) inset',
              border: '1px solid rgba(108, 140, 255, 0.3)',
              maxWidth: '70vw',
              textAlign: 'center',
              whiteSpace: 'pre-line',
              lineHeight: 1.5,
            }}
          >
            {toastMsg}
          </div>
        )}
      </div>
    </div>
  )
}

const AppRoot: React.FC = () => (
  <CloudSyncBusyProvider>
    <App />
    <CloudSyncBusyOverlay />
  </CloudSyncBusyProvider>
)

export default AppRoot
