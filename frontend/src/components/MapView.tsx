import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { useT } from '../i18n';
import { useServices } from '../contexts/ServicesContext';
import L from 'leaflet';
import { useMapInstance } from '../hooks/useMapInstance';
import { useBaseLayers } from '../hooks/useBaseLayers';
import { useRoutePolylineLayer } from '../hooks/useRoutePolylineLayer';
import { useCurrentPositionLayer } from '../hooks/useCurrentPositionLayer';
import { useDestinationLayer } from '../hooks/useDestinationLayer';
import { useRandomWalkCircleLayer } from '../hooks/useRandomWalkCircleLayer';
import { usePreviewPinLayer } from '../hooks/usePreviewPinLayer';
import { useWaypointMarkersLayer } from '../hooks/useWaypointMarkersLayer';
import { useBookmarkMarkersLayer } from '../hooks/useBookmarkMarkersLayer';
import { useS2Grid } from '../hooks/useS2Grid';
import { S2LevelPicker } from './S2LevelPicker';
import { WaypointMenu } from './WaypointMenu';
import MapContextMenu from './MapContextMenu';
import { CoordInputStrip } from './CoordInputStrip';
import { RecentPlacesPopover } from './RecentPlacesPopover';
import { useLeafletBarButton } from './LeafletBarButton';

interface Position {
  lat: number;
  lng: number;
}

interface Waypoint {
  lat: number;
  lng: number;
  index: number;
}

interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  lat: number;
  lng: number;
  // Set when the menu is opened from a history entry that has a known
  // name (e.g. an address from search). Forwarded to onAddBookmark to
  // pre-fill the dialog. Undefined when opened from a map right-click.
  name?: string;
}

import type { RuntimesMap } from '../hooks/useSimulation';
import { SimMode } from '../hooks/useSimulation';
import type { DeviceInfo } from '../hooks/useDevice';

interface MapViewProps {
  currentPosition: Position | null;
  destination: Position | null;
  waypoints: Waypoint[];
  routePath: Position[];
  randomWalkRadius: number | null;
  onMapClick: (lat: number, lng: number) => void;
  onTeleport: (lat: number, lng: number, source?: 'menu' | 'coord') => void;
  onNavigate: (lat: number, lng: number, source?: 'menu' | 'coord') => void;
  onAddBookmark: (lat: number, lng: number, suggestedName?: string) => void;
  onAddWaypoint?: (lat: number, lng: number) => void;
  // Left-click on a waypoint marker opens a small action menu. Both
  // handlers are optional — when undefined, the waypoint marker stays
  // tooltip-only (legacy behaviour).
  onSetWpAsStart?: (index: number) => void;
  onRemoveWaypoint?: (index: number) => void;
  // Arms a one-shot "insert after this waypoint" mode. Parent shows
  // the cancel banner and turns insertAfterActive on; the next map
  // click consumes the mode and inserts the new waypoint at index+1.
  onInsertAfterWp?: (index: number) => void;
  // When true the map cursor swaps to crosshair so the user knows the
  // next click will splice a new waypoint into the route.
  insertAfterActive?: boolean;
  // Map right-click → push lat,lng into the GoldDitto panel's A field.
  // Only shown when the device is connected and the parent provides the
  // callback, so non-GoldDitto users don't see it.
  onSetAsGoldDittoA?: (lat: number, lng: number) => void;
  showWaypointOption?: boolean;
  deviceConnected?: boolean;
  onShowToast?: (msg: string) => void;
  // HTML snippet to paint into the current-position divIcon. Lets the parent
  // swap the "blue person" for one of the preset characters or a user-
  // uploaded PNG. Empty / undefined = fall back to the built-in default.
  userAvatarHtml?: string;
  // Group mode: when runtimes + devices are present and 2+ devices connected,
  // render per-device markers/polylines/circles. Single-device rendering is
  // still driven by the legacy currentPosition/destination/routePath props.
  runtimes?: RuntimesMap;
  devices?: DeviceInfo[];
  // Optional bookmark list to render as small clickable markers. When
  // enabled, clicking a marker calls onTeleport at that coordinate.
  bookmarkPins?: Array<{
    id?: string;
    name: string;
    lat: number;
    lng: number;
    country_code?: string;
    // Populated by the backend reverse-geocode reconciliation sweep.
    // Used to render the BookmarkGeoLine on matched history rows; may
    // be absent for freshly-saved bookmarks not yet reconciled.
    city?: string;
    timezone?: string;
  }>;
  showBookmarkPins?: boolean;
  // Imperative escape hatch so non-map components (e.g. the StatusBar's
  // "Locate PC" pan-only flow) can move the map view without going
  // through React state.
  onMapReady?: (api: { panTo: (lat: number, lng: number, zoom?: number) => void }) => void;
  // Preview-only pin: rendered when the user previews a coord (camera-only
  // fly) so they can see exactly where they're looking on the map. Distinct
  // shape + amber color so it doesn't get confused with the red destination
  // marker. Cleared by the parent when a real teleport / clear runs.
  previewPin?: Position | null;
  onPreviewPinClear?: () => void;
  // Triggered by the coord-input overlay's "Preview" button. The parent
  // owns both the map-pan and the preview-pin state so we route through
  // it instead of touching mapRef locally.
  onCoordPreview?: (lat: number, lng: number) => void;
  // Recent destinations (last 20 teleport / navigate / search actions).
  // Rendered in a topright popover so the user can re-fly in one click.
  recentPlaces?: Array<{ lat: number; lng: number; kind: 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate'; name: string; ts: number }>;
  onRecentReFly?: (entry: { lat: number; lng: number; kind: 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate'; name: string }) => void;
  onRecentClear?: () => void;
  // Click handler for the topleft library shortcut. Opens the
  // bookmarks / routes panel without the user having to scroll down
  // to the ControlPanel's library button.
  onOpenLibrary?: () => void;
  // Transport (start / stop / pause) — moved from the sidebar to the
  // bottom-left of the map so they sit just above the coord-input strip.
  simMode?: SimMode;
  isRunning?: boolean;
  isPaused?: boolean;
  onStart?: () => void;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  // Bulk-paste route shortcut on the map (next to the library star),
  // visible only in MultiStop / Loop modes.
  showBulkPasteOnMap?: boolean;
  onBulkPasteOpen?: () => void;
  // Fires after the user moves the map (Leaflet `moveend`) and once on
  // mount with the initial center. Used by the GoldDitto panel's "use
  // map center" B-coordinate button.
  onMapCenterChange?: (lat: number, lng: number) => void;
}

// Transport (Start / Stop / Pause / Resume) — bottom-left of the map,
// directly above the coord-input strip. Mockup S6 (玻璃膠囊) base with
// the active state filled D8 (sliding highlight). Width fits content
// only — we don't want the whole row to span the coord input below.
export function TransportButtons({
  isRunning,
  isPaused,
  simMode,
  deviceConnected,
  onStart,
  onStop,
  onPause,
  onResume,
  t,
}: {
  isRunning: boolean;
  isPaused: boolean;
  simMode: SimMode;
  deviceConnected: boolean;
  onStart?: () => void;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  t: React.MutableRefObject<(k: any, v?: any) => string>;
}) {
  // Don't render if no callbacks were wired (defensive).
  if (!onStart && !onStop && !onPause && !onResume) return null;
  const label = (k: string) => {
    try { return t.current(k as any); } catch { return ''; }
  };
  return (
    <div
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      style={{
        // Static (not absolute): sits inside the bottom-left stack
        // wrapper so its vertical position is dictated by the flex
        // column rather than a hand-tuned bottom value.
        display: 'inline-flex',
        alignSelf: 'flex-start',
        alignItems: 'center',
        gap: 0,
        padding: 4,
        background: 'rgba(20, 23, 34, 0.78)',
        backdropFilter: 'blur(14px) saturate(160%)',
        WebkitBackdropFilter: 'blur(14px) saturate(160%)',
        border: '1px solid rgba(108, 140, 255, 0.22)',
        borderRadius: 10,
        boxShadow: '0 10px 26px rgba(8, 11, 22, 0.5)',
      }}
    >
      {!isRunning && simMode !== SimMode.Teleport && (
        <button
          className="lw-transport-btn lw-transport-start"
          onClick={onStart}
          disabled={!deviceConnected}
          title={label('generic.start')}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21" /></svg>
          {label('generic.start')}
        </button>
      )}
      {isRunning && (
        <button
          className="lw-transport-btn lw-transport-stop"
          onClick={onStop}
          title={label('generic.stop')}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
          {label('generic.stop')}
        </button>
      )}
      {isRunning && !isPaused && (
        <button
          className="lw-transport-btn lw-transport-pause"
          onClick={onPause}
          title={label('generic.pause')}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="4" width="5" height="16" rx="1" /><rect x="14" y="4" width="5" height="16" rx="1" /></svg>
          {label('generic.pause')}
        </button>
      )}
      {isRunning && isPaused && (
        <button
          className="lw-transport-btn lw-transport-resume"
          onClick={onResume}
          title={label('generic.resume')}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21" /></svg>
          {label('generic.resume')}
        </button>
      )}
    </div>
  );
}

// SVG markup for the 4 custom leaflet-bar buttons, lifted VERBATIM out of the
// old inline button builders. Module-scoped so they're parsed once, not on
// every render. Painted into each button via innerHTML by useLeafletBarButton.
const RECENTER_ICON_HTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3" />
        <line x1="12" y1="2" x2="12" y2="5" />
        <line x1="12" y1="19" x2="12" y2="22" />
        <line x1="2" y1="12" x2="5" y2="12" />
        <line x1="19" y1="12" x2="22" y2="12" />
      </svg>`;
const FOLLOW_ICON_HTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round">
        <polygon points="3 11 22 2 13 21 11 13 3 11"/>
      </svg>`;
const LIBRARY_ICON_HTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2l2.5 6.5L22 9l-5.5 5.5L18 22l-6-3.5L6 22l1.5-7.5L2 9l7.5-.5z"/>
      </svg>`;
const S2_ICON_HTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="1" />
        <line x1="9" y1="3" x2="9" y2="21" />
        <line x1="15" y1="3" x2="15" y2="21" />
        <line x1="3" y1="9" x2="21" y2="9" />
        <line x1="3" y1="15" x2="21" y2="15" />
      </svg>`;

const MapViewInner: React.FC<MapViewProps> = ({
  currentPosition,
  destination,
  waypoints,
  routePath,
  randomWalkRadius,
  onMapClick,
  onTeleport,
  onNavigate,
  onAddBookmark,
  onAddWaypoint,
  onSetWpAsStart,
  onRemoveWaypoint,
  onInsertAfterWp,
  insertAfterActive,
  onSetAsGoldDittoA,
  showWaypointOption,
  deviceConnected = true,
  onShowToast,
  userAvatarHtml,
  runtimes,
  devices,
  bookmarkPins,
  showBookmarkPins,
  onMapReady,
  previewPin,
  onPreviewPinClear,
  onCoordPreview,
  recentPlaces,
  onRecentReFly,
  onRecentClear,
  onOpenLibrary,
  simMode,
  isRunning,
  isPaused,
  onStart,
  onStop,
  onPause,
  onResume,
  showBulkPasteOnMap,
  onBulkPasteOpen,
  onMapCenterChange,
}) => {
  // Lookup: bookmark coords → bookmark pin. Used by recent-history rows
  // and the context-menu's Add Bookmark item to detect matches.
  // toFixed(5) gives ~1m precision and avoids float drift in comparisons.
  const bookmarkByCoord = useMemo(() => {
    const m = new Map<string, NonNullable<typeof bookmarkPins>[number]>();
    if (bookmarkPins) {
      for (const bm of bookmarkPins) {
        m.set(`${bm.lat.toFixed(5)}|${bm.lng.toFixed(5)}`, bm);
      }
    }
    return m;
  }, [bookmarkPins]);

  // Dual-mode rendering disabled by design: with pre-sync (both devices
  // teleport to the same start before any group action) and shared random
  // seed, the two phones always sit at the exact same coordinate, so two
  // markers and two polylines just overlap and add visual noise. The view
  // always renders the single-device path (driven by the primary device's
  // currentPosition / routePath / destination passed in as props). The
  // devices / runtimes props are still accepted for API compatibility with
  // App.tsx (prop interface is frozen for this refactor) but unused here.
  void devices; void runtimes;
  const t = useT();
  // The map-init useEffect only runs once, so its click handler captures the
  // first-render `t`. Language switches then don't reach the tooltip hint.
  // Route lookups through a ref that we keep in sync every render.
  const tRef = useRef(t);
  // onMapClick closure gets captured by the once-per-mount click handler;
  // route through a ref so toggling the prop mid-session takes effect.
  const onMapClickRef = useRef(onMapClick);
  useEffect(() => { onMapClickRef.current = onMapClick; }, [onMapClick]);
  tRef.current = t;
  const mapContainerRef = useRef<HTMLDivElement>(null);
  // mapRef is owned by useMapInstance now (the once-per-mount lifecycle hook);
  // it's destructured from the hook call below and consumed by every other
  // effect in this component exactly as before.
  // The "blue person" current-position marker + its two refs (currentMarkerRef,
  // lastAvatarHtmlRef) + the >500m auto-center heuristic + the follow auto-pan
  // are owned by useCurrentPositionLayer now (task p4b2bi); called below after
  // useMapInstance. prevPositionRef stays here — it's shared with useMapInstance
  // (the persisted-initial-position race guard) and passed into both hooks.
  const prevPositionRef = useRef<Position | null>(null);
  // The red destination marker + its two refs (destMarkerRef, destSigRef) are
  // owned by useDestinationLayer now (task p4b2bi); called below after
  // useMapInstance / useBaseLayers / useRoutePolylineLayer / useCurrentPositionLayer.
  // The amber preview pin + its two refs (previewMarkerRef, previewSigRef) are
  // owned by usePreviewPinLayer now (task p4b2bi); called below after the other
  // layer hooks.
  // The numbered waypoint markers + their two refs (waypointMarkersRef,
  // waypointSigRef) are owned by useWaypointMarkersLayer now (task p4b2bi);
  // called below after the other layer hooks. The mini-menu STATE (wpMenu)
  // stays lifted here; its JSX moved to <WaypointMenu> (task p4b2bii), wired
  // via thin closures over the handler-mirror refs below.
  // The small bookmark pins + their marker ref (bookmarkMarkersRef) + the
  // zoomend rebuild listener are owned by useBookmarkMarkersLayer now (task
  // p4b2bi); called below after the other layer hooks.
  // The route polyline (base line + flowing-arrow dash overlay) + its two refs
  // are owned by useRoutePolylineLayer now (task p4b2bi); called below after
  // useMapInstance / useBaseLayers.
  // The 4 custom leaflet-bar buttons (recenter → follow → library → S2-grid)
  // are mounted as real Leaflet controls (not absolutely-positioned React JSX)
  // so Leaflet's own .leaflet-top .leaflet-left layout pins them to the same x
  // as the zoom buttons, with the standard 10px gap. They're now built by the
  // `useLeafletBarButton` primitive (4 call sites below the map-init effects),
  // which owns each button's DOM node + the wire-once `*HandlerRef` mirror +
  // the React→DOM active-sync — so MapView no longer keeps per-button refs.
  // The S2 grid overlay (its s2Enabled/s2Level/s2Suppressed state + localStorage
  // persistence + the grid layer ref + the moveend/zoomend redraw listeners) is
  // owned by useS2Grid now (task p4b2bi); called below after the other layer
  // hooks. The S2 button + the inline level picker read its returned state.
  // followStateRef mirrors followMode so the dragstart handler (wired once
  // at map init) sees the latest value without a stale closure.
  const followStateRef = useRef(false);
  // onShowToast captured by once-mount handlers. Routed through a ref so
  // prop changes mid-session take effect.
  const onShowToastRef = useRef(onShowToast);
  useEffect(() => { onShowToastRef.current = onShowToast; }, [onShowToast]);
  // Waypoint marker click handlers — kept in refs so the per-marker click
  // handler captured inside the waypoints useEffect always calls the
  // freshest prop without re-creating every marker on each prop change.
  const onSetWpAsStartRef = useRef(onSetWpAsStart);
  useEffect(() => { onSetWpAsStartRef.current = onSetWpAsStart; }, [onSetWpAsStart]);
  const onRemoveWaypointRef = useRef(onRemoveWaypoint);
  useEffect(() => { onRemoveWaypointRef.current = onRemoveWaypoint; }, [onRemoveWaypoint]);
  const onInsertAfterWpRef = useRef(onInsertAfterWp);
  useEffect(() => { onInsertAfterWpRef.current = onInsertAfterWp; }, [onInsertAfterWp]);
  // Mini context menu shown on left-click of a waypoint marker.
  // Independent from the right-click `contextMenu` so opening one does
  // not close / reposition the other.
  const [wpMenu, setWpMenu] = useState<{
    visible: boolean; x: number; y: number; index: number; isStart: boolean;
  }>({ visible: false, x: 0, y: 0, index: 0, isStart: false });
  const closeWpMenu = useCallback(() => {
    setWpMenu((prev) => prev.visible ? { ...prev, visible: false } : prev);
  }, []);
  // onMapCenterChange — same ref pattern as onShowToast. The moveend handler
  // is wired once at mount inside the map-init useEffect, so it must read
  // the latest callback through a ref.
  const onMapCenterChangeRef = useRef(onMapCenterChange);
  useEffect(() => { onMapCenterChangeRef.current = onMapCenterChange; }, [onMapCenterChange]);
  // clickMarkerRef removed — left-click no longer drops a pin.
  // radiusCircleRef moved into useRandomWalkCircleLayer (task p4b2bi) — it owns
  // the dashed random-walk radius circle's single ref internally.

  const [followMode, setFollowMode] = useState(false);
  useEffect(() => { followStateRef.current = followMode; }, [followMode]);

  // S2 cell grid state (s2Enabled / s2Level / s2Suppressed) + its localStorage
  // persistence + the grid layer ref + the moveend/zoomend redraw effect are
  // owned by useS2Grid now (task p4b2bi); called below after the other layer
  // hooks. s2PickerOpen — the inline level picker's open/closed visibility — is
  // JSX state, not grid logic, so it stays here; the S2 button's onContextMenu
  // toggles it and the picker JSX reads it.
  const [s2PickerOpen, setS2PickerOpen] = useState(false);

  // The recent-destinations button + draggable popover (its open / clear-
  // confirm / drag-offset state + the capture-phase document drag listeners +
  // the per-row badge / relative-time / bookmark-match rendering) is owned by
  // <RecentPlacesPopover> now (task p4b2bii). Its per-row right-click + ⋮ button
  // open MapView's shared context menu via the onOpenContextMenu callback below
  // (the menu JSX itself stays here). bookmarkByCoord is passed in (MapView also
  // reads it for the context-menu match).

  // Right-click context-menu OPEN-STATE only. The menu JSX (incl. the viewport-
  // clamp layout-effect + the reverse-geocode state/stale-guard) moved into
  // <MapContextMenu> (task p4b2bii); MapView renders it conditionally with a
  // per-open key so each open is a FRESH MOUNT and the stale-guard reduces to a
  // mountedRef inside the component.
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    lat: 0,
    lng: 0,
  });

  const closeContextMenu = useCallback(() => {
    setContextMenu((prev) => ({ ...prev, visible: false }));
  }, []);

  // Copy the right-clicked coord to the clipboard (with the legacy execCommand
  // fallback) + toast. Wrapped here so <MapContextMenu> stays clipboard-free and
  // fires it through the onCopy prop. Same string format, fallback, and toast key
  // as the original inline handler; one intentional difference — the menu now
  // closes optimistically (onClose runs right after onCopy) rather than after the
  // async clipboard write settles. Benign: the write + toast live on these
  // MapView-scoped refs, which outlive the menu unmount.
  const copyContextCoords = useCallback((lat: number, lng: number) => {
    const txt = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    (async () => {
      try {
        await navigator.clipboard.writeText(txt);
      } catch {
        const ta = document.createElement('textarea');
        ta.value = txt;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch { /* ignore */ }
        document.body.removeChild(ta);
      }
      if (onShowToastRef.current) onShowToastRef.current(tRef.current('map.coords_copied'));
    })();
  }, []);

  // Map lifecycle (creation + control-corner offsets + map-level events +
  // persisted initial-position fetch + onMapReady + teardown) lives in
  // useMapInstance now. mapRef is returned and consumed by every effect below
  // exactly as before. The map-level events route to MapView's existing logic
  // through the callbacks here, which read the same *Ref mirrors the once-per-
  // mount handlers always did — so toggling a prop mid-session still takes
  // effect without re-creating the map.
  const { api } = useServices();
  const { mapRef } = useMapInstance(mapContainerRef, {
    // Left-click: dismiss any open context menu / waypoint menu, then forward
    // to onMapClick (the "left-click to add waypoint" toggle). Identical to the
    // original once-per-mount click handler.
    onMapClick: (lat, lng) => {
      closeContextMenu();
      setWpMenu((prev) => prev.visible ? { ...prev, visible: false } : prev);
      try {
        onMapClickRef.current?.(lat, lng);
      } catch { /* ignore handler errors */ }
    },
    // Right-click: open the shared context menu at the click point. The
    // hook already called preventDefault on the original event.
    onContextMenu: (lat, lng, oe) => {
      setContextMenu({
        visible: true,
        x: oe.clientX,
        y: oe.clientY,
        lat,
        lng,
      });
    },
    // moveend (+ once on mount): feed the center up to App via the ref mirror.
    onMapCenterChange: (lat, lng) => {
      if (!onMapCenterChangeRef.current) return;
      try {
        onMapCenterChangeRef.current(lat, lng);
      } catch { /* ignore */ }
    },
    // dragstart: auto-disable follow mode (only when it's currently on, read
    // via followStateRef so this sees the latest state) + toast. Programmatic
    // panTo / setView do not fire dragstart, so the auto-pan loop is safe.
    onDragStart: () => {
      if (!followStateRef.current) return;
      setFollowMode(false);
      try {
        onShowToastRef.current?.(tRef.current('map.follow_disabled_toast'));
      } catch { /* ignore */ }
    },
    onMapReady,
    // Injected api — only getInitialPosition is read, for the persisted
    // initial-position pan on mount. Race-guarded by prevPositionRef so the
    // saved-position pan still loses to a real position_update that arrived.
    api: { getInitialPosition: api.getInitialPosition },
    prevPositionRef,
  });

  // S2 cell grid overlay — owns the s2Enabled/s2Level/s2Suppressed state +
  // localStorage persistence (keys locwarp.s2_enabled / locwarp.s2_level) + the
  // grid layer ref + the moveend/zoomend redraw effect (task p4b2bi). Called
  // after useMapInstance so its redraw effect runs on the already-created map.
  // The S2 leaflet-bar button (below) reads s2Enabled; the inline level picker
  // reads s2Level / s2Suppressed + the setters.
  const { s2Enabled, setS2Enabled, s2Level, setS2Level, s2Suppressed } = useS2Grid(mapRef);

  // ── Leaflet-bar buttons (recenter → follow → library → S2) ──────────────
  // Built by the `useLeafletBarButton` primitive. Defined here (before
  // useBaseLayers) so the documented init ORDER (control corners → button
  // stack → base layers) is preserved: each hook's wire-once effect runs in
  // call order, appending its button to the top-left control corner in turn.
  // The click handlers + the React→DOM active-sync (background / title /
  // aria-pressed / disabled) live inside the hook; MapView just passes the
  // live state.

  const recenter = useCallback(() => {
    const map = mapRef.current;
    if (!map || !currentPosition) return;
    map.setView([currentPosition.lat, currentPosition.lng], Math.max(map.getZoom(), 16), {
      animate: true,
    });
  }, [currentPosition]);
  const toggleFollow = useCallback(() => {
    setFollowMode((prev) => !prev);
  }, []);
  // Toggle handler for the S2 grid. Wired to the leaflet-bar button below; the
  // S2 overlay redraw lives in its own effect further down.
  const toggleS2Grid = useCallback(() => {
    setS2Enabled((prev) => !prev);
  }, []);

  // 1. Recenter — anonymous button (no className), pinned by its title in the
  // e2e net. Blue background when a position exists, disabled+dim when not.
  // NOT a toggle → no aria-pressed (ariaPressed omitted).
  useLeafletBarButton({
    mapRef,
    iconHtml: RECENTER_ICON_HTML,
    title: t('map.recenter'),
    active: !!currentPosition,
    disabled: !currentPosition,
    onClick: recenter,
  });
  // 2. Follow — toggle. Title flips between on/off labels; aria-pressed tracks
  // followMode; blue when on.
  useLeafletBarButton({
    mapRef,
    iconHtml: FOLLOW_ICON_HTML,
    title: t(followMode ? 'map.follow_on' : 'map.follow_off'),
    active: followMode,
    ariaPressed: followMode,
    onClick: toggleFollow,
  });
  // 3. Library — gold star, stable `.locwarp-library-btn` className. Plain
  // action button (no active state); opens the library panel via onOpenLibrary.
  useLeafletBarButton({
    mapRef,
    iconHtml: LIBRARY_ICON_HTML,
    title: t('map.library_open'),
    className: 'locwarp-library-btn',
    color: '#ffd95b',
    onClick: onOpenLibrary ?? (() => {}),
  });
  // 4. S2 grid — toggle, stable `.locwarp-s2-btn` className. aria-pressed tracks
  // s2Enabled; right-click opens the level picker.
  useLeafletBarButton({
    mapRef,
    iconHtml: S2_ICON_HTML,
    title: t('map.s2_toggle'),
    className: 'locwarp-s2-btn',
    active: s2Enabled,
    ariaPressed: s2Enabled,
    onClick: toggleS2Grid,
    onContextMenu: () => setS2PickerOpen((o) => !o),
  });

  // Base layers + the top-right L.control.layers switcher + localStorage
  // persistence, extracted into its own mapRef-dependent hook (task p4b2a).
  // It runs its own once-per-mount effect AFTER useMapInstance has created
  // the map, so the documented init ORDER (control corners → leaflet-bar
  // button stack above → base layers here) is preserved.
  useBaseLayers(mapRef);

  // Route polyline overlay (base line + flowing-arrow dash, `path.route-flow-dash`),
  // extracted into its own mapRef-dependent hook (task p4b2bi). Called after
  // useMapInstance / useBaseLayers so it runs on the already-created map. Owns
  // the layer's two polyline refs internally.
  useRoutePolylineLayer(mapRef, { routePath });

  // Current-position "blue person" marker (move-vs-recreate, avatar rebuild,
  // the >500m auto-center heuristic) + the follow auto-pan, extracted into their
  // own mapRef-dependent hook (task p4b2bi). Called after useMapInstance /
  // useBaseLayers / useRoutePolylineLayer so it runs on the already-created map.
  // Owns the marker's two refs (currentMarkerRef, lastAvatarHtmlRef) internally;
  // prevPositionRef stays owned here (shared with useMapInstance) and is passed
  // in so the saved-position pan still loses to a real position_update.
  useCurrentPositionLayer(mapRef, { currentPosition, userAvatarHtml, followMode, prevPositionRef });

  // Red destination teardrop marker (signature-gated create/move/remove),
  // extracted into its own mapRef-dependent hook (task p4b2bi). Called after
  // useMapInstance / useBaseLayers / useRoutePolylineLayer / useCurrentPositionLayer
  // so it runs on the already-created map. Owns the layer's two refs
  // (destMarkerRef, destSigRef) internally; `t` is passed in for the tooltip.
  useDestinationLayer(mapRef, { destination, t });

  // Dashed blue random-walk radius circle (drawn only when a positive radius is
  // set AND we have a live position), extracted into its own mapRef-dependent
  // hook (task p4b2bi). Called after the other layer hooks so it runs on the
  // already-created map. Owns the layer's single ref (radiusCircleRef) internally.
  useRandomWalkCircleLayer(mapRef, { randomWalkRadius, currentPosition });

  // Amber preview pin (camera-only fly target — signature-gated create/move/
  // remove + click-to-dismiss), extracted into its own mapRef-dependent hook
  // (task p4b2bi). Called after the other layer hooks so it runs on the
  // already-created map. Owns the layer's two refs (previewMarkerRef,
  // previewSigRef) internally; `tRef` is passed in for the tooltip.
  usePreviewPinLayer(mapRef, { previewPin, onPreviewPinClear, tRef });

  // Numbered waypoint markers (signature-gated full rebuild + per-marker
  // left-click), extracted into their own mapRef-dependent hook (task p4b2bi).
  // Called after the other layer hooks so it runs on the already-created map.
  // Owns the layer's two refs (waypointMarkersRef, waypointSigRef) internally;
  // `tRef` is passed in for the tooltips. The per-marker click opens the
  // (still-inline) wpMenu via onWaypointMenu, and a post-rebuild stale-dismiss
  // routes through onWaypointMenuStale — both preserve the original setWpMenu
  // calls exactly.
  useWaypointMarkersLayer(mapRef, {
    waypoints,
    tRef,
    onWaypointMenu: (index, isStart, x, y) => {
      setWpMenu({ visible: true, x, y, index, isStart });
    },
    onWaypointMenuStale: () => {
      setWpMenu((prev) => prev.visible ? { ...prev, visible: false } : prev);
    },
  });

  // Render/clear small bookmark pins on the map when the user toggles
  // 'show all bookmarks on map'. Each pin is clickable and teleports to
  // that bookmark's position. Owns the marker ref (bookmarkMarkersRef) + the
  // zoomend rebuild listener internally (task p4b2bi); the screen-pixel
  // clustering + icon-HTML are the unit-tested pure helpers. The single-pin
  // click and the cluster-popup row click both teleport via onTeleport.
  useBookmarkMarkersLayer(mapRef, {
    bookmarkPins,
    showBookmarkPins,
    onTeleport,
  });

  // The random-walk radius circle effect was moved into useRandomWalkCircleLayer
  // (task p4b2bi) — see the hook call above, after useDestinationLayer.

  // Close context menu on outside click
  useEffect(() => {
    const handler = () => closeContextMenu();
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [closeContextMenu]);

  // Close the waypoint mini-menu on any outside click. Same pattern as
  // closeContextMenu — clicking inside the menu calls stopPropagation
  // there so this fires only for clicks that miss the menu surface.
  useEffect(() => {
    const handler = () => closeWpMenu();
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [closeWpMenu]);

  // The follow auto-pan effect was moved into useCurrentPositionLayer (task
  // p4b2bi) — it drives the same camera-vs-marker layer as the position marker.

  // ── S2 cell grid overlay ────────────────────────────────────────────
  // The toggle handler (toggleS2Grid) + its leaflet-bar button live with the
  // other 3 buttons above (useLeafletBarButton). The overlay redraw + the
  // s2Enabled/s2Level/s2Suppressed state + localStorage persistence + the grid
  // layer ref + the moveend/zoomend redraw listeners are owned by useS2Grid now
  // (task p4b2bi); called above after useMapInstance. The inline level picker
  // (still in MapView) reads s2Level / s2Suppressed + the setters from the hook.

  // lastAvatarHtmlRef moved into useCurrentPositionLayer (task p4b2bi) — it's
  // only read/written by the current-position marker effect now living there.

  // The coord-input overlay (replaces the sidebar's two-field coord input) +
  // its coordInput state + parseCoord + the teleport / navigate / preview
  // submit handlers + the clipboard paste are owned by <CoordInputStrip> now
  // (task p4b2bii). The strip also owns the status-bar-height ResizeObserver
  // and reports the measured height back up via onStatusBarHeight, which feeds
  // statusBarHeight here — the wrapping bottom-left flex column (which also
  // holds the bulk-paste + transport rows) uses it for its `bottom` offset.
  const [statusBarHeight, setStatusBarHeight] = useState<number>(38);
  // Preview-only fly. Mirrors the original submitCoordPreview fallback: the
  // parent owns the pan + preview-pin drop when onCoordPreview is wired (so the
  // pin and camera move together for both this overlay and the bookmark-list
  // "fly camera only" path); otherwise we pan mapRef directly. Wrapped here so
  // CoordInputStrip stays Leaflet-free.
  const handleCoordPreview = useCallback((lat: number, lng: number) => {
    if (onCoordPreview) {
      onCoordPreview(lat, lng);
      return;
    }
    const m = mapRef.current;
    if (!m) return;
    const targetZoom = Math.max(m.getZoom(), 16);
    m.setView([lat, lng], targetZoom, { animate: true });
  }, [onCoordPreview]);

  // When insert-after-waypoint mode is armed, swap the leaflet drag/grab
  // cursor to a crosshair so the user has a visual cue that the next
  // map click drops a new waypoint (and isn't a no-op or a teleport).
  // Scoped via inline <style> so it only affects THIS map instance —
  // a global stylesheet rule would bleed into any other Leaflet map.
  return (
    <div
      className={`map-container${insertAfterActive ? ' wp-insert-mode' : ''}`}
      style={{ position: 'relative', flex: 1 }}
    >
      {insertAfterActive && (
        <style>{`
          .map-container.wp-insert-mode .leaflet-container,
          .map-container.wp-insert-mode .leaflet-grab,
          .map-container.wp-insert-mode .leaflet-interactive {
            cursor: crosshair !important;
          }
        `}</style>
      )}
      <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />

      {/* Bottom-left stack: Bulk-paste (route/multi only) > Transport >
          Coord-input. Single flex column at bottom-left, fixed gap so the
          rows don't drift apart based on container height. Sits exactly
          above the bottom status bar — height tracked dynamically so a
          wrapped (multi-row) status bar doesn't overlap this strip when
          the window is narrow. */}
      <div
        style={{
          position: 'absolute',
          left: 12,
          bottom: statusBarHeight + 22,
          zIndex: 851,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          gap: 8,
        }}
      >
        {showBulkPasteOnMap && onBulkPasteOpen && (
          <button
            onClick={onBulkPasteOpen}
            onMouseDown={(e) => e.stopPropagation()}
            title={tRef.current('panel.route_paste_tooltip')}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 12px', height: 32, fontSize: 12,
              color: '#e8eaff', fontWeight: 600,
              background: 'rgba(20, 23, 34, 0.88)',
              backdropFilter: 'blur(14px) saturate(160%)',
              WebkitBackdropFilter: 'blur(14px) saturate(160%)',
              border: '1px solid rgba(108, 140, 255, 0.32)',
              borderRadius: 10,
              boxShadow: '0 10px 26px rgba(8, 11, 22, 0.5)',
              cursor: 'pointer',
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="2" width="6" height="4" rx="1"/>
              <path d="M9 4H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-3"/>
            </svg>
            {tRef.current('panel.route_paste_button')}
          </button>
        )}
        <TransportButtons
          isRunning={!!isRunning}
          isPaused={!!isPaused}
          simMode={simMode ?? SimMode.Teleport}
          deviceConnected={deviceConnected}
          onStart={onStart}
          onStop={onStop}
          onPause={onPause}
          onResume={onResume}
          t={tRef}
        />
        {/* Coord input strip — last row of the bottom-left flex column so the
            gap above is purely controlled by the parent. Owns its coordInput
            state + parse + submit handlers + the status-bar ResizeObserver,
            which reports the measured height back up so this column's `bottom`
            offset (statusBarHeight + 22) tracks a wrapped (multi-row) status
            bar. The preview fallback is wrapped by handleCoordPreview so the
            strip stays Leaflet-free. */}
        <CoordInputStrip
          deviceConnected={deviceConnected}
          onTeleport={onTeleport}
          onNavigate={onNavigate}
          onPreview={handleCoordPreview}
          onShowToast={onShowToast}
          onStatusBarHeight={setStatusBarHeight}
        />
      </div>

      {/* S2 cell grid level picker — opens via right-click on the S2 toggle
          button OR via the small chip beside the legend below. Snaps to
          discrete levels 8..22, default 17 (Niantic decor cell). */}
      <S2LevelPicker
        open={s2PickerOpen}
        onClose={() => setS2PickerOpen(false)}
        s2Enabled={s2Enabled}
        setS2Enabled={setS2Enabled}
        s2Level={s2Level}
        setS2Level={setS2Level}
        s2Suppressed={s2Suppressed}
        lat={mapRef.current ? mapRef.current.getCenter().lat : 0}
      />

      {/* Recent destinations button + draggable popover (topright, below the
          tile layer switcher). Owns its open / clear-confirm / drag-offset
          state + the capture-phase document drag listeners + the per-row
          badge / relative-time / bookmark-match rendering (task p4b2bii). The
          per-row right-click + the ⋮ button open MapView's shared context menu
          via onOpenContextMenu (the menu JSX stays here); bookmarkByCoord is
          passed in (MapView also reads it for the context-menu match). The
          whole control renders nothing when recentPlaces is undefined. */}
      <RecentPlacesPopover
        recentPlaces={recentPlaces}
        bookmarkByCoord={bookmarkByCoord}
        onRecentReFly={onRecentReFly}
        onRecentClear={onRecentClear}
        onOpenContextMenu={(lat, lng, name, x, y) => {
          setContextMenu({ visible: true, x, y, lat, lng, name });
        }}
      />

      {/* Map right-click context menu — JSX extracted to <MapContextMenu>
          (task p4b2bii); only the open-state (contextMenu) stays lifted here.
          Rendered CONDITIONALLY with a per-open key so each open is a fresh
          mount: that reduces the reverse-geocode stale-guard to a mountedRef
          inside the component (a late address after close/reopen is dropped),
          and gives the viewport-clamp layout-effect a clean per-open run. The
          reverseGeocode gateway is injected via prop (api.reverseGeocode) so
          MapView + the menu stay free of a direct services/api import. */}
      {contextMenu.visible && (
        <MapContextMenu
          key={`${contextMenu.lat}-${contextMenu.lng}-${contextMenu.x}-${contextMenu.y}`}
          lat={contextMenu.lat}
          lng={contextMenu.lng}
          x={contextMenu.x}
          y={contextMenu.y}
          name={contextMenu.name}
          reverseGeocode={api.reverseGeocode}
          bookmarkMatch={bookmarkByCoord.get(
            `${contextMenu.lat.toFixed(5)}|${contextMenu.lng.toFixed(5)}`
          )}
          deviceConnected={deviceConnected}
          showWaypointOption={showWaypointOption}
          onTeleport={onTeleport}
          onNavigate={onNavigate}
          onSetAsGoldDittoA={onSetAsGoldDittoA}
          onCopy={() => copyContextCoords(contextMenu.lat, contextMenu.lng)}
          onAddBookmark={onAddBookmark}
          onAddWaypoint={onAddWaypoint}
          onClose={closeContextMenu}
        />
      )}

      {/* Per-waypoint mini-menu — JSX extracted to <WaypointMenu> (task
          p4b2bii); the wpMenu state stays lifted here. The action props are
          thin closures over the wire-once handler-mirror refs (so freshness is
          preserved), gated on the original optional props so an absent handler
          omits its menu item (mirrors the old `…Ref.current &&` gating). Each
          closure closes the menu before firing, matching the prior order. */}
      <WaypointMenu
        visible={wpMenu.visible}
        x={wpMenu.x}
        y={wpMenu.y}
        index={wpMenu.index}
        isStart={wpMenu.isStart}
        onSetAsStart={onSetWpAsStart ? (idx) => onSetWpAsStartRef.current?.(idx) : undefined}
        onInsertAfter={onInsertAfterWp ? (idx) => onInsertAfterWpRef.current?.(idx) : undefined}
        onRemove={onRemoveWaypoint ? (idx) => onRemoveWaypointRef.current?.(idx) : undefined}
        onClose={closeWpMenu}
      />
    </div>
  );
};

const MapView = React.memo(MapViewInner);
MapView.displayName = 'MapView';

export default MapView;
