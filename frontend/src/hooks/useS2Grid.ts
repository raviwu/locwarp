import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { cellsInBounds, approxCellSizeMeters } from '../services/s2grid'
import type { S2CellPolygon } from '../services/s2grid'

// ─────────────────────────────────────────────────────────────────────────────
// useS2Grid — the S2 cell-grid overlay, carved VERBATIM out of MapView's S2
// state + localStorage persistence + paint effect (Phase 4b, task p4b2bi). Owns:
//   - the s2Enabled / s2Level state + their localStorage read/write (keys
//     `locwarp.s2_enabled` / `locwarp.s2_level` — FROZEN), persisting the user's
//     preferred level + on/off across launches.
//   - the s2Suppressed state — set when the chosen level would render cells
//     smaller than ~2 px (too far zoomed out); the level picker reads it to tell
//     the user to zoom in instead of silently showing nothing.
//   - s2LayerRef — the live L.LayerGroup of grid polygons, fully torn down +
//     rebuilt on every effect run AND on every `moveend` / `zoomend`.
//
// The grid is recomputed + painted whenever the layer is toggled, the level
// changes, or the user pans / zooms. cellsInBounds caps the cell count per zoom
// so wide zooms with high levels don't lock the UI. The pure S2 math lives in
// `services/s2grid.ts` (`cellsInBounds` / `approxCellSizeMeters`, unit-tested);
// this hook hands them Leaflet's bounds / zoom / center EXACTLY as the original
// effect did.
//
// CRITICAL listener lifecycle — the redraw listeners (`draw`) are added with
// `map.on('moveend', draw)` + `map.on('zoomend', draw)` and removed in the
// effect cleanup with the matching `map.off(...)`. A leaked `moveend` / `zoomend`
// listener (or an orphaned grid layer) is the main risk of this carve-out, so
// the add + the matching off + the layer teardown are kept together,
// byte-for-byte, inside this single effect — every re-run / unmount removes the
// prior listeners (and removes the prior grid layer) before (re)adding.
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map,
// guarding `if (!map) return` — preserving the documented map-init ORDER. The
// effect body is the original VERBATIM; the dep array stays `[s2Enabled, s2Level]`.
//
// The S2 LeafletBarButton (its active state reads s2Enabled) + the inline level
// picker (reads s2Level / s2Suppressed + the setters) stay in MapView, reading
// this hook's returned state/setters. The picker's open/closed visibility
// (s2PickerOpen) stays in MapView — it is JSX state, not grid logic.
// ─────────────────────────────────────────────────────────────────────────────

export interface UseS2GridResult {
  /** Whether the S2 grid overlay is on. The S2 button's active/aria-pressed reads this. */
  s2Enabled: boolean
  /** Setter for the on/off toggle. Wired to the S2 button + the picker's on/off button. */
  setS2Enabled: React.Dispatch<React.SetStateAction<boolean>>
  /** The chosen S2 cell level (8..22 in the picker; clamped 1..30 from storage, default 17). */
  s2Level: number
  /** Setter for the level. Wired to the picker's range slider + the quick-pick chips. */
  setS2Level: React.Dispatch<React.SetStateAction<number>>
  /** True when the grid was suppressed because the user is too far zoomed out. */
  s2Suppressed: boolean
}

/**
 * Owns the S2 cell-grid state (persisted in localStorage), the grid layer ref,
 * and the moveend/zoomend redraw effect. Returns the state + setters the S2
 * button and the inline level picker need.
 *
 * @param mapRef the live map ref owned by useMapInstance
 */
export function useS2Grid(
  mapRef: React.RefObject<L.Map | null>,
): UseS2GridResult {
  // The S2 layer group (the overlay it toggles).
  const s2LayerRef = useRef<L.LayerGroup | null>(null);

  // S2 cell grid state. Persisted in localStorage so the user's preferred
  // level + on/off survives across launches (similar to tile-layer choice).
  const [s2Enabled, setS2Enabled] = useState<boolean>(() => {
    try { return localStorage.getItem('locwarp.s2_enabled') === '1'; }
    catch { return false; }
  });
  const [s2Level, setS2Level] = useState<number>(() => {
    try {
      const raw = localStorage.getItem('locwarp.s2_level');
      const n = raw ? parseInt(raw, 10) : 17;
      if (Number.isFinite(n) && n >= 1 && n <= 30) return n;
    } catch { /* fall through */ }
    return 17;
  });

  useEffect(() => {
    try { localStorage.setItem('locwarp.s2_enabled', s2Enabled ? '1' : '0'); }
    catch { /* ignore */ }
  }, [s2Enabled]);
  useEffect(() => {
    try { localStorage.setItem('locwarp.s2_level', String(s2Level)); }
    catch { /* ignore */ }
  }, [s2Level]);

  // ── S2 cell grid overlay ────────────────────────────────────────────
  // The toggle handler (toggleS2Grid) + its leaflet-bar button live with the
  // other 3 buttons above (useLeafletBarButton). The overlay redraw stays here.

  // Track whether the grid was suppressed because the user is too far zoomed
  // out. The level picker uses this to tell them to zoom in instead of
  // silently showing nothing.
  const [s2Suppressed, setS2Suppressed] = useState(false);

  // Recompute + paint S2 polygons whenever the layer is toggled, the level
  // changes, or the user pans / zooms. Capped per zoom inside cellsInBounds
  // so wide zooms with high levels don't lock the UI.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const draw = () => {
      if (s2LayerRef.current) {
        try { s2LayerRef.current.remove(); } catch { /* ignore */ }
        s2LayerRef.current = null;
      }
      if (!s2Enabled) {
        setS2Suppressed(false);
        return;
      }
      // Suppress when the chosen level would render cells smaller than ~2 px:
      // the BFS safety cap clips at a center cluster and the grid then looks
      // like it 'wanders' with the cursor as you pan. Tell the user to zoom
      // in (or pick a coarser level) instead of silently rendering garbage.
      const zoom = map.getZoom();
      const lat = map.getCenter().lat;
      const cellMeters = approxCellSizeMeters(s2Level, lat);
      // Web Mercator: world circumference at the equator is 40075016m, mapped
      // to 256*2^zoom pixels. cos(lat) factor already baked into approxCellSizeMeters.
      const cellPx = cellMeters * (256 * Math.pow(2, zoom)) / 40075016;
      if (cellPx < 2) {
        setS2Suppressed(true);
        return;
      }
      setS2Suppressed(false);
      const bounds = map.getBounds();
      let cells: S2CellPolygon[];
      try {
        cells = cellsInBounds(bounds, s2Level);
      } catch {
        return;
      }
      if (!cells.length) return;
      const layer = L.layerGroup();
      // Solid colour, transparent fill — keeps the underlying map readable.
      // Slightly thinner stroke at high levels (more cells, would otherwise
      // blanket the screen).
      const weight = s2Level >= 18 ? 0.6 : s2Level >= 16 ? 0.8 : 1.1;
      for (const c of cells) {
        L.polygon(c.corners, {
          color: '#6c8cff',
          weight,
          opacity: 0.85,
          fill: true,
          fillColor: '#6c8cff',
          fillOpacity: 0.04,
          interactive: false,
          // Sit below markers so cell lines never block clicks on bookmark
          // pins / waypoint markers / context menu.
          pane: 'overlayPane',
        }).addTo(layer);
      }
      layer.addTo(map);
      s2LayerRef.current = layer;
    };
    draw();
    map.on('moveend', draw);
    map.on('zoomend', draw);
    return () => {
      map.off('moveend', draw);
      map.off('zoomend', draw);
      if (s2LayerRef.current) {
        try { s2LayerRef.current.remove(); } catch { /* ignore */ }
        s2LayerRef.current = null;
      }
    };
  }, [s2Enabled, s2Level]);

  return { s2Enabled, setS2Enabled, s2Level, setS2Level, s2Suppressed };
}
