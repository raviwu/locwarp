import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { buildDestinationHtml } from '../utils/mapIconHtml'
import type { useT } from '../i18n'

// ─────────────────────────────────────────────────────────────────────────────
// useDestinationLayer — the red "destination" teardrop marker, carved VERBATIM
// out of MapView's "Update destination marker" effect (Phase 4b, task p4b2bi).
// Owns the ONE layer's two refs:
//   - destMarkerRef — the live L.marker (divIcon `.dest-marker`)
//   - destSigRef    — the lat,lng signature (toFixed(7)) of the last-painted
//     destination, so an identical destination does NOT needlessly recreate the
//     marker (signature-gating: bail early when sig === destSigRef.current).
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map,
// guarding `if (!mapRef.current) return` — preserving the documented map-init
// ORDER. The effect body is the original VERBATIM; only the map-source (now
// `mapRef.current`) + the guard shape changed.
//
// The `t` translator is passed in (the tooltip reads `t('map.destination')`).
// As in the original, the effect dep array is `[destination]` only — it captures
// `t` from render but re-runs solely on a destination change. Preserved exactly.
//
// Behavior is FROZEN: the e2e net (`.dest-marker` visible after a
// simulation_state frame carries `data.destination`) pins this layer.
// ─────────────────────────────────────────────────────────────────────────────

interface Position {
  lat: number
  lng: number
}

export interface UseDestinationLayerOptions {
  // The current destination. When null the marker is removed. A new
  // destination (different lat,lng signature) recreates the marker; an
  // identical one is a no-op (signature-gated).
  destination: Position | null
  // The translator for the marker tooltip (`t('map.destination')`). Captured
  // from render; the effect re-runs only on `destination` (matching the
  // original).
  t: ReturnType<typeof useT>
}

/**
 * Draws / moves / clears the red destination marker, owning its marker +
 * signature refs and preserving the signature-gating that avoids needless
 * recreate.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the destination + the translator the tooltip reads
 */
export function useDestinationLayer(
  mapRef: React.RefObject<L.Map | null>,
  { destination, t }: UseDestinationLayerOptions,
) {
  const destMarkerRef = useRef<L.Marker | null>(null)

  // Update destination marker
  const destSigRef = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const sig = destination ? `${destination.lat.toFixed(7)},${destination.lng.toFixed(7)}` : null;
    if (sig === destSigRef.current) return;
    destSigRef.current = sig;

    if (destMarkerRef.current) {
      destMarkerRef.current.remove();
      destMarkerRef.current = null;
    }

    if (destination) {
      const redIcon = L.divIcon({
        className: 'dest-marker',
        html: buildDestinationHtml(),
        iconSize: [36, 50],
        iconAnchor: [18, 47],
      });

      const marker = L.marker([destination.lat, destination.lng], {
        icon: redIcon,
      }).addTo(map);

      marker.bindTooltip(t('map.destination'), { direction: 'top', offset: [0, -48] });
      destMarkerRef.current = marker;
    }
  }, [destination]);
}
