import { useEffect, useRef } from 'react'
import L from 'leaflet'

// ─────────────────────────────────────────────────────────────────────────────
// useRoutePolylineLayer — the route-polyline overlay, carved VERBATIM out of
// MapView's "Update route polyline" effect (Phase 4b, task p4b2bi). Owns the ONE
// layer's two polyline refs:
//   - the base solid line (#3a66c5, weight 7)
//   - the animated white flowing-arrow dash overlay on top
//     (`path.route-flow-dash`, dashArray '2 38') — the direction cue.
// Both are removed + recreated whenever `routePath` changes, and the layer is
// drawn only when `routePath.length > 1` (design 6 — flowing arrows).
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map +
// useBaseLayers has set up the tile layers, guarding `if (!mapRef.current)
// return` — preserving the documented map-init ORDER. The effect body is the
// original VERBATIM; only the map-source (now `mapRef.current`) + the guard
// shape changed.
//
// Behavior is FROZEN: the e2e net (`path.route-flow-dash` drawn on route_path,
// cleared on state_change(idle)) pins this layer exactly.
// ─────────────────────────────────────────────────────────────────────────────

interface Position {
  lat: number
  lng: number
}

export interface UseRoutePolylineLayerOptions {
  // The ordered route coordinates. Drawn as a polyline only when length > 1.
  routePath: Position[]
}

/**
 * Draws / clears the route polyline overlay (base line + flowing-arrow dash) on
 * the map, owning its two polyline refs.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the route path the layer reads
 */
export function useRoutePolylineLayer(
  mapRef: React.RefObject<L.Map | null>,
  { routePath }: UseRoutePolylineLayerOptions,
) {
  const polylineRef = useRef<L.Polyline | null>(null)
  // Second polyline layered on top for the flowing-arrow animation (design 6).
  const polylineArrowRef = useRef<L.Polyline | null>(null)

  // Update route polyline
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (polylineRef.current) {
      polylineRef.current.remove()
      polylineRef.current = null
    }
    if (polylineArrowRef.current) {
      polylineArrowRef.current.remove()
      polylineArrowRef.current = null
    }

    if (routePath.length > 1) {
      const latlngs: L.LatLngExpression[] = routePath.map((p) => [p.lat, p.lng])
      // Design 6 (chosen): flowing arrows. Base solid line + animated white
      // dash overlay that flows from start to end so the user can tell the
      // travel direction at a glance.
      const base = L.polyline(latlngs, {
        color: '#3a66c5',
        weight: 7,
        opacity: 0.9,
        lineCap: 'round',
        lineJoin: 'round',
      }).addTo(map)
      polylineRef.current = base

      const arrows = L.polyline(latlngs, {
        color: '#ffffff',
        weight: 3,
        opacity: 0.95,
        dashArray: '2 38',
        lineCap: 'round',
        className: 'route-flow-dash',
      }).addTo(map)
      polylineArrowRef.current = arrows
    }
  }, [routePath])
}
