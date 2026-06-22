import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { buildWaypointHtml } from '../utils/mapIconHtml'
import type { useT } from '../i18n'

// ─────────────────────────────────────────────────────────────────────────────
// useWaypointMarkersLayer — the numbered waypoint markers (subway-station style
// ring + stem + ground shadow), carved VERBATIM out of MapView's "Update
// waypoint markers" effect (Phase 4b, task p4b2bi). Owns the ONE layer's two
// refs:
//   - waypointMarkersRef — the live L.marker[] (divIcon `.waypoint-marker`),
//     fully torn down + rebuilt on every signature change.
//   - waypointSigRef     — the lat,lng signature (toFixed(7) joined by `|`) of
//     the last-painted waypoint set, so an identical set does NOT needlessly
//     rebuild the markers (signature-gating: bail early when sig ===
//     waypointSigRef.current).
//
// The mini-menu STATE STAYS in MapView (it's lifted React state + JSX deferred
// to a later task). The per-marker left-click handler does the same DOM /
// Leaflet stopPropagation gymnastics as the original, then invokes the
// `onWaypointMenu(index, isStart, x, y)` callback MapView passes in — which is
// exactly what the original inline handler did via `setWpMenu({ visible: true,
// x, y, index: wp.index, isStart })`. The post-rebuild "dismiss any stale open
// menu" call is likewise routed through MapView's `onWaypointMenuStale`
// callback (the original `setWpMenu((prev) => prev.visible ? ... : prev)`).
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map,
// guarding `if (!mapRef.current) return` — preserving the documented map-init
// ORDER. The effect body is the original VERBATIM; only the map-source (now
// `mapRef.current`) is unchanged from the original (it already read
// `mapRef.current`).
//
// The `tRef` translator ref is passed in (the tooltips read
// `tRef.current('panel.waypoint_start')` / `tRef.current('panel.waypoint_num',
// { n })`). As in the original, the effect dep array is `[waypoints]` — it
// captures `tRef`, `onWaypointMenu`, and `onWaypointMenuStale` from the hook
// scope but re-runs solely on a waypoints change. Preserved exactly.
//
// This overlay is prop-driven and has NO e2e net — it was moved byte-for-byte.
// ─────────────────────────────────────────────────────────────────────────────

interface Waypoint {
  lat: number
  lng: number
  index: number
}

export interface UseWaypointMarkersLayerOptions {
  // The route waypoints to render as numbered markers. index 0 is the implicit
  // start point (green "S"); the rest are orange + numbered. A change to this
  // list (insert / remove / rotate) rebuilds the whole marker set; an identical
  // signature is a no-op (signature-gated).
  waypoints: Waypoint[]
  // Translator ref for the marker tooltips (`tRef.current('panel.waypoint_start')`
  // / `tRef.current('panel.waypoint_num', { n })`). Captured from the hook scope;
  // the effect re-runs only on `[waypoints]` (matching the original).
  tRef: React.MutableRefObject<ReturnType<typeof useT>>
  // Opens the waypoint mini-menu in MapView. Called from the per-marker
  // left-click handler with the same `(index, isStart, x, y)` the original
  // inline handler fed into `setWpMenu`. The mini-menu state + JSX stay in
  // MapView; this is just the open trigger.
  onWaypointMenu: (index: number, isStart: boolean, x: number, y: number) => void
  // Dismiss any open waypoint mini-menu after a rebuild — the waypoint
  // signature may have changed under our feet (insert / remove / rotate) so
  // any open menu now points at a stale index. Mirrors the original
  // post-rebuild `setWpMenu((prev) => prev.visible ? ... : prev)`.
  onWaypointMenuStale: () => void
}

/**
 * Draws / rebuilds the numbered waypoint markers, owning its marker + signature
 * refs and preserving the signature-gating that avoids needless rebuild. The
 * per-marker left-click opens the (still-inline) MapView mini-menu via
 * `onWaypointMenu`.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the waypoints + the translator ref + the menu open / stale-dismiss callbacks
 */
export function useWaypointMarkersLayer(
  mapRef: React.RefObject<L.Map | null>,
  { waypoints, tRef, onWaypointMenu, onWaypointMenuStale }: UseWaypointMarkersLayerOptions,
) {
  const waypointMarkersRef = useRef<L.Marker[]>([])

  // Update waypoint markers
  const waypointSigRef = useRef<string>('');
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const sig = waypoints.map((w) => `${w.lat.toFixed(7)},${w.lng.toFixed(7)}`).join('|');
    if (sig === waypointSigRef.current) return;
    waypointSigRef.current = sig;

    waypointMarkersRef.current.forEach((m) => m.remove());
    waypointMarkersRef.current = [];

    waypoints.forEach((wp) => {
      // index 0 is the implicit start point; S + green, numbered + orange.
      // Design: subway-station style — thick ring + short stem + ground
      // shadow. Chosen by user (from route-marker-designs.html, pick 07).
      const isStart = wp.index === 0;
      const wpIcon = L.divIcon({
        className: 'waypoint-marker',
        // Outer wrapper is pointer-events:auto + cursor:pointer so the
        // ENTIRE 40x46 marker area (ring + stem + ground shadow + the
        // padding around them) catches the left-click — not just the
        // 28px ring. Old layout had pointer-events:none on the wrapper
        // which meant a click on the stem or shadow passed straight
        // through to the map and the waypoint menu never opened.
        html: buildWaypointHtml(wp.index),
        iconSize: [40, 46],
        // Anchor = bottom-center of the ground shadow = exact (lat, lng).
        iconAnchor: [20, 46],
      });

      const marker = L.marker([wp.lat, wp.lng], { icon: wpIcon }).addTo(map);
      marker.bindTooltip(
        isStart ? tRef.current('panel.waypoint_start') : tRef.current('panel.waypoint_num', { n: wp.index }),
        { direction: 'top', offset: [0, -28] },
      );
      // Left-click opens a mini menu (set as start / delete). Stop the
      // event from bubbling to BOTH the map (so the click-to-add-
      // waypoint toggle doesn't see it as a new map click) AND the
      // DOM document (so the document-level outside-click handler
      // doesn't immediately close the menu we just opened — without
      // DOM stopPropagation the menu opens and closes in the same
      // tick and the user sees nothing).
      marker.on('click', (ev) => {
        const oe = ev.originalEvent as MouseEvent | undefined;
        L.DomEvent.stopPropagation(ev);
        if (oe) {
          oe.preventDefault?.();
          oe.stopPropagation?.();
          (oe as any).stopImmediatePropagation?.();
        }
        const x = oe?.clientX ?? 0;
        const y = oe?.clientY ?? 0;
        onWaypointMenu(wp.index, isStart, x, y);
      });
      waypointMarkersRef.current.push(marker);
    });
    // The waypoint signature may have changed under our feet (insert /
    // remove / rotate). Any open menu now points at a stale index, so
    // dismiss it.
    onWaypointMenuStale();
  }, [waypoints]);
}
