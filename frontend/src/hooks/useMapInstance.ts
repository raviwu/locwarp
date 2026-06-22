import { useEffect, useRef } from 'react'
import L from 'leaflet'

// ─────────────────────────────────────────────────────────────────────────────
// useMapInstance — the once-per-mount map lifecycle, lifted VERBATIM out of
// MapView.tsx's monolithic map-init effect (Phase 4b, task p4b2a). This is the
// "core everything else depends on": it creates the single L.map() instance,
// nudges the top-left / top-right control corners below the EtaBar, wires the
// map-level events ONCE (click / contextmenu / moveend / dragstart), performs
// the persisted initial-position fetch (now via an INJECTED api so the hook
// never imports services/api directly — keeps it inside the hexagon-lite gate),
// hands the parent the imperative `onMapReady({ panTo })` contract, and tears
// the map down on unmount.
//
// What it DOES NOT own (relocated by MapView into separate mapRef-dependent
// effects in the same commit, awaiting their own extraction in Tasks 5/6):
//   - the 4 custom leaflet-bar buttons (recenter / follow / library / S2)
//   - the base-layer setup + L.control.layers switcher
// Those run AFTER mapRef is set, preserving the EXACT map-init ORDER:
//   control-corners offset → button stack (recenter → follow → library → S2)
//   → base layers. A reorder reintroduces the "Taipei-flash-then-jump" bug.
//
// Behavior is FROZEN. The map-level events route to the callbacks passed in
// (which MapView wires to its `*Ref` mirrors), so toggling a prop mid-session
// still takes effect without re-creating the map. The initial-position race
// guard (`prevPositionRef`) is owned by MapView and passed in so the initial
// pan still loses to a real `position_update` that already arrived — exactly as
// the original effect did.
// ─────────────────────────────────────────────────────────────────────────────

// Minimal structural type for the one api method this hook needs. Taken as an
// injected arg (not a direct services/api import) so the hook stays decoupled —
// mirroring useMapClick's `api: ApiGateway` pattern.
export interface MapInstanceApi {
  getInitialPosition: () => Promise<{
    position: { lat: number; lng: number } | null
  }>
}

export interface UseMapInstanceOptions {
  // Forwarded from the map `click` event (latlng). MapView routes this to its
  // close-menus + onMapClickRef wiring.
  onMapClick: (lat: number, lng: number, originalEvent: MouseEvent) => void
  // Forwarded from the map `contextmenu` event. MapView opens its shared
  // context menu from here.
  onContextMenu: (lat: number, lng: number, originalEvent: MouseEvent) => void
  // Forwarded from the map `moveend` event AND fired once on mount with the
  // initial center, so the parent's "use map center" state is never stale-null.
  onMapCenterChange: (lat: number, lng: number) => void
  // Forwarded from the map `dragstart` event. MapView uses it to auto-disable
  // follow mode (reads its own followStateRef + shows a toast).
  onDragStart: () => void
  // The external imperative contract: handed `{ panTo }` once the map is ready
  // (used by the StatusBar Locate-PC pan-only flow). Optional — only called
  // when the parent provides it.
  onMapReady?: (api: { panTo: (lat: number, lng: number, zoom?: number) => void }) => void
  // Injected api — only getInitialPosition is needed for the persisted
  // initial-position fetch on mount.
  api: MapInstanceApi
  // Owned by MapView; read once after the initial-position fetch resolves so
  // the saved-position pan loses to a real device position that already
  // arrived (the documented "Taipei flash then jump" race guard).
  prevPositionRef: React.MutableRefObject<{ lat: number; lng: number } | null>
  // Tooltip strings for the controls live in MapView; the map instance itself
  // needs none, so nothing i18n-related is taken here.
}

/**
 * Creates and owns the single Leaflet map instance for a MapView mount.
 *
 * @param containerRef the div the map mounts into
 * @param opts map-level event callbacks + injected api + the race-guard ref
 * @returns `{ mapRef }` — the live map ref consumed by the rest of MapView's
 *          effects (markers / polyline / S2 grid / leaflet-bar buttons).
 */
export function useMapInstance(
  containerRef: React.RefObject<HTMLDivElement>,
  opts: UseMapInstanceOptions,
) {
  const mapRef = useRef<L.Map | null>(null)

  // Mirror every option through refs so the once-per-mount event handlers read
  // the freshest callback / api without re-creating the map. This is the same
  // wire-once + *Ref-mirror pattern MapView already used for onMapClick etc.
  const onMapClickRef = useRef(opts.onMapClick)
  const onContextMenuRef = useRef(opts.onContextMenu)
  const onMapCenterChangeRef = useRef(opts.onMapCenterChange)
  const onDragStartRef = useRef(opts.onDragStart)
  const onMapReadyRef = useRef(opts.onMapReady)
  const apiRef = useRef(opts.api)
  onMapClickRef.current = opts.onMapClick
  onContextMenuRef.current = opts.onContextMenu
  onMapCenterChangeRef.current = opts.onMapCenterChange
  onDragStartRef.current = opts.onDragStart
  onMapReadyRef.current = opts.onMapReady
  apiRef.current = opts.api

  const { prevPositionRef } = opts

  // Initialize map — once per mount. Mirrors the original MapView map-init
  // effect, minus the leaflet-bar buttons + base layers (relocated to their
  // own mapRef-dependent effects in MapView). The control-corner offset stays
  // here so the buttons MapView appends afterwards land in an already-nudged
  // corner — preserving the documented init ORDER.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = L.map(containerRef.current, {
      center: [25.033, 121.5654],
      zoom: 13,
      // Keep Leaflet's default control off so we can position our own
      // zoom control below the EtaBar on the left (default top-left
      // would collide with the overlay).
      zoomControl: false,
      // Snap wheel zoom to integer levels + require a full notch per step,
      // so one wheel tick = one tile-load batch instead of cascading
      // intermediate zooms that all fire tile requests and bomb OSM's
      // rate limiter with black-tile fallout.
      zoomSnap: 1,
      wheelPxPerZoomLevel: 120,
      wheelDebounceTime: 60,
    })
    const zoomCtrl = L.control.zoom({ position: 'topleft' })
    zoomCtrl.addTo(map)
    // Nudge the top-left and top-right control clusters down so they sit
    // below the EtaBar (full-width, absolute-positioned at top:0) instead
    // of being partially covered by it.
    const topLeftEl = (map as any)._controlCorners?.topleft as HTMLElement | undefined
    if (topLeftEl) {
      topLeftEl.style.marginTop = '56px'
    }
    const topRightEl = (map as any)._controlCorners?.topright as HTMLElement | undefined
    if (topRightEl) {
      topRightEl.style.marginTop = '56px'
    }

    // User-initiated drag disables follow mode so they can pan freely. We
    // forward to MapView's onDragStart (which reads its own followStateRef so
    // the handler wired once at mount sees the latest state). dragstart fires
    // only on pointer drag — programmatic panTo / setView do not trigger it, so
    // the auto-pan loop won't accidentally turn itself off.
    map.on('dragstart', () => {
      try {
        onDragStartRef.current()
      } catch { /* ignore */ }
    })

    // Map center change — fed up to App so the GoldDitto panel can offer
    // "use map center" as a one-click B-coord setter. Fire once on mount
    // with the initial center so the parent state is never stale-null.
    try {
      const c0 = map.getCenter()
      onMapCenterChangeRef.current(c0.lat, c0.lng)
    } catch { /* ignore */ }
    map.on('moveend', () => {
      try {
        const c = map.getCenter()
        onMapCenterChangeRef.current(c.lat, c.lng)
      } catch { /* ignore */ }
    })

    // Left-click on the map dismisses any open context menu.
    // If the parent wires `onMapClick` (currently used by the "left-click
    // to add waypoint" toggle in Loop / MultiStop modes), forward the
    // coordinates there too.
    map.on('click', (e: L.LeafletMouseEvent) => {
      try {
        onMapClickRef.current(e.latlng.lat, e.latlng.lng, e.originalEvent)
      } catch { /* ignore handler errors */ }
    })

    map.on('contextmenu', (e: L.LeafletMouseEvent) => {
      e.originalEvent.preventDefault()
      try {
        onContextMenuRef.current(e.latlng.lat, e.latlng.lng, e.originalEvent)
      } catch { /* ignore */ }
    })

    mapRef.current = map

    // Hand the parent an imperative panTo so it can move the view without
    // touching React state (used by the StatusBar's Locate-PC pan-only flow).
    const onMapReady = onMapReadyRef.current
    if (onMapReady) {
      try {
        onMapReady({
          panTo: (lat: number, lng: number, zoom?: number) => {
            const m = mapRef.current
            if (!m) return
            const targetZoom = zoom ?? Math.max(m.getZoom(), 16)
            m.setView([lat, lng], targetZoom, { animate: true })
          },
        })
      } catch { /* non-fatal */ }
    }

    // Fetch the user-saved initial position from the backend (once, on mount).
    // If set, pan the map to it. Brief Taipei flash is acceptable. Uses the
    // INJECTED api so this hook never imports services/api directly.
    apiRef.current.getInitialPosition().then(({ position }) => {
      if (!position || !mapRef.current) return
      if (prevPositionRef.current) return // a real device position already arrived
      mapRef.current.setView([position.lat, position.lng], mapRef.current.getZoom())
    }).catch(() => { /* default center stays */ })

    return () => {
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { mapRef }
}
