import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { buildPreviewHtml } from '../utils/mapIconHtml'
import type { useT } from '../i18n'

// ─────────────────────────────────────────────────────────────────────────────
// usePreviewPinLayer — the amber "preview pin" teardrop marker (camera-only fly
// target), carved VERBATIM out of MapView's preview-pin effect (Phase 4b, task
// p4b2bi). Owns the ONE layer's two refs:
//   - previewMarkerRef — the live L.marker (divIcon `.preview-marker`)
//   - previewSigRef    — the lat,lng signature (toFixed(7)) of the last-painted
//     preview, so an identical preview does NOT needlessly recreate the marker
//     (signature-gating: bail early when sig === previewSigRef.current).
//
// The amber teardrop carries an eye icon to convey "you're peeking at this
// coordinate, GPS hasn't actually moved here". Clicking the marker dismisses
// the pin via onPreviewPinClear (wired only when the callback is provided).
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map,
// guarding `if (!mapRef.current) return` — preserving the documented map-init
// ORDER. The effect body is the original VERBATIM; only the map-source (now
// `mapRef.current`) is unchanged from the original (it already read
// `mapRef.current`).
//
// The `tRef` translator ref is passed in (the tooltip reads
// `tRef.current('map.preview_pin')`). As in the original, the effect dep array
// is `[previewPin, onPreviewPinClear]` — it captures `tRef` from the hook scope
// but re-runs solely on a preview / dismiss-callback change. Preserved exactly.
//
// This overlay is prop-driven and has NO e2e net — it was moved byte-for-byte.
// ─────────────────────────────────────────────────────────────────────────────

interface Position {
  lat: number
  lng: number
}

export interface UsePreviewPinLayerOptions {
  // Preview-only pin: rendered when the user previews a coord (camera-only
  // fly) so they can see exactly where they're looking on the map. When null /
  // undefined the marker is removed. A new preview (different lat,lng
  // signature) recreates the marker; an identical one is a no-op
  // (signature-gated).
  previewPin?: Position | null
  // Dismiss callback — when provided, a click on the marker clears the pin.
  // Wired only when defined (matching the original).
  onPreviewPinClear?: () => void
  // Translator ref for the marker tooltip (`tRef.current('map.preview_pin')`).
  // Captured from the hook scope; the effect re-runs only on
  // `[previewPin, onPreviewPinClear]` (matching the original).
  tRef: React.MutableRefObject<ReturnType<typeof useT>>
}

/**
 * Draws / moves / clears the amber preview-pin marker, owning its marker +
 * signature refs and preserving the signature-gating that avoids needless
 * recreate.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the preview pin + the dismiss callback + the translator ref the tooltip reads
 */
export function usePreviewPinLayer(
  mapRef: React.RefObject<L.Map | null>,
  { previewPin, onPreviewPinClear, tRef }: UsePreviewPinLayerOptions,
) {
  const previewMarkerRef = useRef<L.Marker | null>(null)

  // Preview pin (camera-only fly target). Amber teardrop with an eye icon
  // to convey "you're peeking at this coordinate, GPS hasn't actually
  // moved here". Click the marker to dismiss the pin.
  const previewSigRef = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const sig = previewPin ? `${previewPin.lat.toFixed(7)},${previewPin.lng.toFixed(7)}` : null;
    if (sig === previewSigRef.current) return;
    previewSigRef.current = sig;

    if (previewMarkerRef.current) {
      previewMarkerRef.current.remove();
      previewMarkerRef.current = null;
    }

    if (previewPin) {
      const amberIcon = L.divIcon({
        className: 'preview-marker',
        html: buildPreviewHtml(),
        iconSize: [36, 50],
        iconAnchor: [18, 47],
      });

      const marker = L.marker([previewPin.lat, previewPin.lng], {
        icon: amberIcon,
        zIndexOffset: 500,
      }).addTo(map);

      const tip = `${tRef.current('map.preview_pin')} · ${previewPin.lat.toFixed(5)}, ${previewPin.lng.toFixed(5)}`;
      marker.bindTooltip(tip, { direction: 'top', offset: [0, -48] });
      if (onPreviewPinClear) {
        marker.on('click', () => onPreviewPinClear());
      }
      previewMarkerRef.current = marker;
    }
  }, [previewPin, onPreviewPinClear]);
}
