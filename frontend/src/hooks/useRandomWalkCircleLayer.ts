import { useEffect, useRef } from 'react'
import L from 'leaflet'

// ─────────────────────────────────────────────────────────────────────────────
// useRandomWalkCircleLayer — the dashed blue "random-walk radius" circle, carved
// VERBATIM out of MapView's "Update random walk radius circle" effect (Phase 4b,
// task p4b2bi). Owns the ONE layer's single ref:
//   - radiusCircleRef — the live L.circle drawn around the current position.
//
// Gating: the circle is drawn ONLY when `randomWalkRadius && randomWalkRadius > 0
// && currentPosition` — i.e. random-walk mode is active (a positive radius set)
// AND we have a live position to center on. On every re-run the old circle is
// removed first, then redrawn if (and only if) the gate passes — so clearing the
// radius (null / 0) or losing the position removes it.
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map,
// guarding `if (!map) return` — preserving the documented map-init ORDER. The
// effect body is the original VERBATIM; only the map-source (now `mapRef.current`)
// is unchanged from the original (it already read `mapRef.current`). The dep
// array stays `[randomWalkRadius, currentPosition]`, matching the original.
//
// This overlay is prop-driven and has NO e2e net — it was moved byte-for-byte.
// ─────────────────────────────────────────────────────────────────────────────

interface Position {
  lat: number
  lng: number
}

export interface UseRandomWalkCircleLayerOptions {
  // The random-walk radius in metres. null / 0 (or any non-positive value)
  // means no circle. A positive value with a live position draws the dashed
  // circle centred on that position.
  randomWalkRadius: number | null
  // The live device position the circle is centred on. When null the circle is
  // removed (the gate fails).
  currentPosition: Position | null
}

/**
 * Draws / updates / clears the dashed random-walk radius circle, owning its
 * single circle ref.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the random-walk radius + the current position the circle centres on
 */
export function useRandomWalkCircleLayer(
  mapRef: React.RefObject<L.Map | null>,
  { randomWalkRadius, currentPosition }: UseRandomWalkCircleLayerOptions,
) {
  const radiusCircleRef = useRef<L.Circle | null>(null);

  // Update random walk radius circle
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Remove old circle
    if (radiusCircleRef.current) {
      radiusCircleRef.current.remove();
      radiusCircleRef.current = null;
    }

    // Draw circle when radius is set and we have a position
    if (randomWalkRadius && randomWalkRadius > 0 && currentPosition) {
      const circle = L.circle(
        [currentPosition.lat, currentPosition.lng],
        {
          radius: randomWalkRadius,
          color: '#4285f4',
          weight: 2,
          opacity: 0.6,
          fillColor: '#4285f4',
          fillOpacity: 0.08,
          dashArray: '6, 6',
        }
      ).addTo(map);
      radiusCircleRef.current = circle;
    }
  }, [randomWalkRadius, currentPosition]);
}
