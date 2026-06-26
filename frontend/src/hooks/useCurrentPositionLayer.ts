import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { buildCurrentPositionHtml } from '../utils/mapIconHtml'

// ─────────────────────────────────────────────────────────────────────────────
// useCurrentPositionLayer — the "blue person" current-position marker, carved
// VERBATIM out of MapView's two position effects (Phase 4b, task p4b2bi). This
// is the layer with the MOST logic. It owns the marker's own refs:
//   - currentMarkerRef   — the live L.marker (divIcon `.current-pos-marker`)
//   - lastAvatarHtmlRef   — the avatar HTML we last painted, so an avatar swap
//     rebuilds the marker even when the position itself did not change
// and contains BOTH effects that drive this one layer:
//   1. "Update current position marker" — move-vs-recreate, avatar rebuild, and
//      the >500m auto-center heuristic (first position OR a teleport jump >500m
//      re-centers the view; small random-walk steps do NOT).
//   2. "Auto-pan in follow mode" — panTo on every position tick while follow is
//      on (separate small effect in the original; moved here as it is part of
//      the same camera-vs-marker layer). Programmatic panTo does NOT fire
//      dragstart, so the follow auto-disable wired at map init stays safe.
//
// `prevPositionRef` is NOT owned here: it is shared with useMapInstance (the
// persisted-initial-position fetch reads it as a race guard so the saved-
// position pan loses to a real position_update that already arrived). MapView
// owns it and passes it into BOTH hooks, exactly as it does for useMapInstance.
//
// Runs as mapRef-dependent effects AFTER useMapInstance has created the map,
// guarding `if (!mapRef.current) return` — preserving the documented map-init
// ORDER. The effect bodies are the original VERBATIM; only the map-source (now
// `mapRef.current`) + the guard shape changed.
//
// Behavior is FROZEN: the e2e net (`.current-pos-marker` present after a
// position arrives) pins this layer. The >500m auto-center + follow auto-pan
// are e2e-thin — preserved byte-for-byte.
// ─────────────────────────────────────────────────────────────────────────────

interface Position {
  lat: number
  lng: number
}

export interface UseCurrentPositionLayerOptions {
  // The live device position. When null (e.g. after 一鍵還原) the marker is
  // removed and prevPositionRef cleared.
  currentPosition: Position | null
  // HTML snippet painted into the current-position divIcon. Swaps the default
  // blue-person SVG for a preset character or a user-uploaded PNG. Empty /
  // undefined = built-in default. Changing it rebuilds the marker in place.
  userAvatarHtml?: string
  // When true, the map auto-pans to every position tick (smooth camera trail).
  followMode: boolean
  // Owned by MapView, shared with useMapInstance. Read for the >500m
  // auto-center heuristic and written on every position update; cleared when
  // currentPosition becomes null.
  prevPositionRef: React.MutableRefObject<Position | null>
}

/**
 * Draws / moves / clears the current-position marker and runs the follow
 * auto-pan, owning the marker's own refs.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the position / avatar / follow state + the shared prevPositionRef
 */
export function useCurrentPositionLayer(
  mapRef: React.RefObject<L.Map | null>,
  { currentPosition, userAvatarHtml, followMode, prevPositionRef }: UseCurrentPositionLayerOptions,
) {
  const currentMarkerRef = useRef<L.CircleMarker | null>(null)
  // Track the last avatar HTML we painted so the position-update effect below
  // can detect "avatar changed, need to rebuild marker even though the position
  // didn't change". Without this the new avatar only shows up after the next
  // teleport.
  const lastAvatarHtmlRef = useRef<string>('')

  // Update current position marker — move existing marker instead of recreating.
  // When currentPosition becomes null (e.g. after 一鍵還原) remove the marker.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!currentPosition) {
      if (currentMarkerRef.current) {
        try { (currentMarkerRef.current as any).remove(); } catch { /* ignore */ }
        currentMarkerRef.current = null;
      }
      prevPositionRef.current = null;
      return;
    }

    const latlng: L.LatLngExpression = [currentPosition.lat, currentPosition.lng];

    // If the avatar HTML changed since the marker was created, drop the
    // old marker so the recreate branch below paints with the new icon at
    // the current position — without this the user has to teleport again
    // to see their newly-saved avatar.
    const currentAvatar = userAvatarHtml ?? '';
    if (currentMarkerRef.current && lastAvatarHtmlRef.current !== currentAvatar) {
      try { (currentMarkerRef.current as any).remove(); } catch { /* ignore */ }
      currentMarkerRef.current = null;
    }

    if (currentMarkerRef.current) {
      // Just move the existing marker — no flicker. No tooltip update: the
      // marker is non-interactive (see below) and the coordinate readout
      // lives in the bottom status bar.
      (currentMarkerRef.current as any).setLatLng(latlng);
    } else {
      // First time: create the marker. User-supplied avatar HTML (if any)
      // replaces the default blue-person SVG. The pulse rings stay so the
      // marker still reads as a "live" position indicator.
      const personIcon = L.divIcon({
        className: 'current-pos-marker',
        html: buildCurrentPositionHtml(userAvatarHtml),
        iconSize: [44, 44],
        iconAnchor: [22, 22],
      });

      // Non-interactive: no click handlers wired and no coord tooltip. The
      // blue person marker is pure UI — clicks should pass through to the
      // map / markers beneath it (bookmark pins etc.), and the coordinate
      // readout already lives in the bottom status bar.
      const marker = L.marker(latlng, {
        icon: personIcon,
        zIndexOffset: 1000,
        interactive: false,
      }).addTo(map);

      currentMarkerRef.current = marker as any;
      lastAvatarHtmlRef.current = currentAvatar;
    }

    // Only auto-center on first position or teleport (large jump > 500m)
    const prev = prevPositionRef.current;
    if (!prev) {
      map.setView(latlng, map.getZoom());
    } else {
      const dlat = (currentPosition.lat - prev.lat) * 111320;
      const dlng = (currentPosition.lng - prev.lng) * 111320 * Math.cos(currentPosition.lat * Math.PI / 180);
      const distM = Math.sqrt(dlat * dlat + dlng * dlng);
      if (distM > 500) {
        map.setView(latlng, map.getZoom());
      }
    }
    prevPositionRef.current = currentPosition;
  }, [currentPosition, userAvatarHtml]);

  // Auto-pan the map to the current position in follow mode, but ONLY when the
  // marker has drifted out of a central deadzone (the central 50% of the
  // viewport). Recentering on every tick restarted the 0.4s pan animation
  // before it could settle — sim ticks arrive every 0.2-1.0s — so the tile
  // layer never stopped pruning + re-requesting tiles, producing a torn /
  // half-loaded band along the direction of travel (worsened by the OSM
  // endpoint's rate limit). With the deadzone, most ticks leave the map still
  // (tiles settle); the marker only reaches the box edge every few seconds, so
  // each pan runs to completion uninterrupted and animate:true stays smooth.
  // Programmatic panTo does NOT fire dragstart, so the auto-disable wired at
  // map init is safe.
  useEffect(() => {
    if (!followMode || !currentPosition) return;
    const map = mapRef.current;
    if (!map) return;
    const pt = map.latLngToContainerPoint([currentPosition.lat, currentPosition.lng]);
    const size = map.getSize();
    const offX = Math.abs(pt.x - size.x / 2);
    const offY = Math.abs(pt.y - size.y / 2);
    // Inside the central 50% box (within 25% of half-size from center on BOTH
    // axes) → leave the map still so tiles can finish loading.
    if (offX <= size.x * 0.25 && offY <= size.y * 0.25) return;
    map.panTo([currentPosition.lat, currentPosition.lng], {
      animate: true,
      duration: 0.4,
    });
  }, [currentPosition, followMode]);
}
