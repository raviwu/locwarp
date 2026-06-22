import React, { useRef, useEffect, useLayoutEffect, useState, useCallback, useMemo } from 'react';
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
import { cellsInBounds, approxCellSizeMeters } from '../services/s2grid';
import type { S2CellPolygon } from '../services/s2grid';
import { parseCoord } from '../utils/coords';
import { isSubmitEnter } from '../utils/keyboard';
import { clusterByPixelDistance } from '../utils/pinCluster';
import {
  buildWaypointHtml,
  buildBookmarkPinHtml,
  buildBookmarkClusterHtml,
  buildBookmarkClusterPopupHtml,
} from '../utils/mapIconHtml';
import { BookmarkGeoLine } from './BookmarkGeoLine';
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
function TransportButtons({
  isRunning,
  isPaused,
  onStart,
  onStop,
  onPause,
  onResume,
  t,
}: {
  isRunning: boolean;
  isPaused: boolean;
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
      {!isRunning && (
        <button
          className="lw-transport-btn lw-transport-start"
          onClick={onStart}
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

const MapView: React.FC<MapViewProps> = ({
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
  const waypointMarkersRef = useRef<L.Marker[]>([]);
  const bookmarkMarkersRef = useRef<L.Marker[]>([]);
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
  // The S2 layer group (the overlay it toggles) still lives here.
  const s2LayerRef = useRef<L.LayerGroup | null>(null);
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
  const [s2PickerOpen, setS2PickerOpen] = useState(false);

  useEffect(() => {
    try { localStorage.setItem('locwarp.s2_enabled', s2Enabled ? '1' : '0'); }
    catch { /* ignore */ }
  }, [s2Enabled]);
  useEffect(() => {
    try { localStorage.setItem('locwarp.s2_level', String(s2Level)); }
    catch { /* ignore */ }
  }, [s2Level]);

  const [recentOpen, setRecentOpen] = useState(false);
  // Clear-button confirmation state. First click flips the single
  // "清空" button into a pair of explicit "確定清空" / "取消" buttons.
  // User has to pick one — no auto-revert, no stale timers.
  const [clearConfirming, setClearConfirming] = useState(false);
  useEffect(() => {
    if (!recentOpen) setClearConfirming(false);
  }, [recentOpen]);
  // Recent popover drag offset. Clicking + dragging the header shifts
  // the panel; state persists until closed so the user can park it.
  const [recentDragOffset, setRecentDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  // Capture-phase mousemove/mouseup listeners on document so Leaflet's
  // map-container handlers can't eat the events before we update the
  // drag offset. Previous window-level + Pointer-Events attempts both
  // failed because Leaflet attached its own handlers higher up.
  const beginRecentDrag = (e: React.MouseEvent<HTMLDivElement>) => {
    // Ignore mousedown that lands on a child button (e.g. 清空);
    // otherwise our drag handler swallows the click.
    const t = e.target as HTMLElement;
    if (t.closest('button')) return;
    e.preventDefault();
    e.stopPropagation();
    const baseX = recentDragOffset.x;
    const baseY = recentDragOffset.y;
    const startX = e.clientX;
    const startY = e.clientY;
    // Use document with capture:true so Leaflet / the map container
    // cannot swallow mousemove / mouseup before we see them.
    const onMove = (ev: MouseEvent) => {
      ev.preventDefault();
      setRecentDragOffset({
        x: baseX + (ev.clientX - startX),
        y: baseY + (ev.clientY - startY),
      });
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('mouseup', onUp, true);
    };
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('mouseup', onUp, true);
  };

  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    lat: 0,
    lng: 0,
  });
  // DOM ref + clamped position state. Separate states for "click point" and
  // "where the menu is actually painted" — the paint position is set ONCE
  // per open via useLayoutEffect after measuring the real rendered size.
  // Critical: the layout effect's deps do NOT include contextMenuPos itself,
  // otherwise the setState triggers the effect again and we get an infinite
  // reposition loop (that was v0.2.38's bug).
  const contextMenuElRef = useRef<HTMLDivElement | null>(null);
  const [contextMenuPos, setContextMenuPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!contextMenu.visible) {
      if (contextMenuPos !== null) setContextMenuPos(null);
      return;
    }
    const el = contextMenuElRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    // Clamp: prefer opening rightward / downward, but if that overflows,
    // push the menu back in so it never clips the viewport edge.
    const left = Math.max(margin, Math.min(contextMenu.x, vw - width - margin));
    const top  = Math.max(margin, Math.min(contextMenu.y, vh - height - margin));
    setContextMenuPos({ left, top });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextMenu.visible, contextMenu.x, contextMenu.y]);

  // Reverse-geocode state for the context menu header row. Reset whenever
  // the menu closes or the right-click target changes, so a stale address
  // from a previous click never leaks into a new lookup.
  const [reverseGeo, setReverseGeo] = useState<{
    loading: boolean; address: string | null; error: string | null;
    key: string; // lat|lng the result belongs to
  }>({ loading: false, address: null, error: null, key: '' });

  const closeContextMenu = useCallback(() => {
    setContextMenu((prev) => ({ ...prev, visible: false }));
    setReverseGeo({ loading: false, address: null, error: null, key: '' });
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
        setWpMenu({ visible: true, x, y, index: wp.index, isStart });
      });
      waypointMarkersRef.current.push(marker);
    });
    // The waypoint signature may have changed under our feet (insert /
    // remove / rotate). Any open menu now points at a stale index, so
    // dismiss it.
    setWpMenu((prev) => prev.visible ? { ...prev, visible: false } : prev);
  }, [waypoints]);

  // Render/clear small bookmark pins on the map when the user toggles
  // 'show all bookmarks on map'. Each pin is clickable and teleports to
  // that bookmark's position.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    bookmarkMarkersRef.current.forEach((m) => m.remove());
    bookmarkMarkersRef.current = [];
    if (!showBookmarkPins || !bookmarkPins || bookmarkPins.length === 0) return;

    // Cluster bookmarks that fall within ~40 px of each other at the current
    // zoom. One teardrop pin represents the group; clicking a cluster opens a
    // popup list the user can tap to choose which exact bookmark to jump to.
    // This stops a dozen pins stacking into what looks like a single dot when
    // the user zooms out to see all of Taiwan.
    const rebuild = () => {
      bookmarkMarkersRef.current.forEach((m) => m.remove());
      bookmarkMarkersRef.current = [];
      const THRESHOLD_PX = 40;
      const clusters = clusterByPixelDistance(
        bookmarkPins!,
        (item) => map.latLngToLayerPoint([item.lat, item.lng]),
        THRESHOLD_PX,
      );

      clusters.forEach((c) => {
        if (c.members.length === 1) {
          const bm = c.members[0];
          // Design 5 — Neon glass bubble. Frosted capsule with purple glow,
          // flag + name inside, tiny pointing nub underneath pinning the
          // coordinate. Max width 180px, name truncates with ellipsis.
          const icon = L.divIcon({
            className: 'bookmark-pin',
            // Outer div fills the Leaflet divIcon container, flex column
            // bottom-center so the glowing dot at the bottom sits exactly
            // on the (lat, lng) coordinate (matches iconAnchor below).
            html: buildBookmarkPinHtml(bm.name, bm.country_code),
            iconSize: [200, 56],
            // Anchor = bottom-center of the icon = the glowing dot = exact
            // (lat, lng) coordinate. Previously the flex-inline column was
            // sitting at top-left so the whole pin rendered above-left of
            // the real point.
            iconAnchor: [100, 56],
          });
          const marker = L.marker([bm.lat, bm.lng], {
            icon,
            pane: 'markerPane',
            // Sit above the blue person marker (zIndexOffset 1000) so the
            // pin stays clickable when the user is standing on it.
            zIndexOffset: 2000,
          });
          marker.on('click', () => onTeleport(bm.lat, bm.lng));
          marker.addTo(map);
          bookmarkMarkersRef.current.push(marker);
        } else {
          // Design 4 — Polaroid stack cluster. Three overlapping mini cards
          // with rotation, top one shows the count. Click = open list popup.
          const count = c.members.length;
          const icon = L.divIcon({
            className: 'bookmark-cluster-pin',
            html: buildBookmarkClusterHtml(count),
            iconSize: [52, 46],
            iconAnchor: [26, 23],
          });
          const clusterLat = c.members.reduce((s, m) => s + m.lat, 0) / count;
          const clusterLng = c.members.reduce((s, m) => s + m.lng, 0) / count;
          const marker = L.marker([clusterLat, clusterLng], {
            icon,
            pane: 'markerPane',
            // Above blue person so the cluster card is always clickable.
            zIndexOffset: 2000,
          });
          // Click on a cluster opens a popup with a clickable list so the
          // user can pick which specific bookmark to teleport to. Solves the
          // 'zoom out to see whole country, markers overlap into one dot'
          // usability issue.
          const popup = L.popup({
            className: 'bookmark-cluster-popup',
            maxWidth: 240,
            offset: [0, -12],
          }).setContent(buildBookmarkClusterPopupHtml(c.members));
          marker.bindPopup(popup);
          marker.on('popupopen', () => {
            document.querySelectorAll('.bm-cluster-row').forEach((el) => {
              el.addEventListener('click', () => {
                const lat = parseFloat((el as HTMLElement).dataset.lat || '');
                const lng = parseFloat((el as HTMLElement).dataset.lng || '');
                if (Number.isFinite(lat) && Number.isFinite(lng)) {
                  map.closePopup();
                  onTeleport(lat, lng);
                }
              });
            });
          });
          marker.addTo(map);
          bookmarkMarkersRef.current.push(marker);
        }
      });
    };
    rebuild();

    // Rebuild clusters when the zoom level changes — what's 'overlapping'
    // at world-scale is not overlapping at street-scale.
    const onZoom = () => rebuild();
    map.on('zoomend', onZoom);
    return () => { map.off('zoomend', onZoom); };
  }, [bookmarkPins, showBookmarkPins, onTeleport]);

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

  // lastAvatarHtmlRef moved into useCurrentPositionLayer (task p4b2bi) — it's
  // only read/written by the current-position marker effect now living there.

  // Coordinate-input overlay (replaces the sidebar's two-field coord input).
  // parseCoord scrapes the first valid lat/lng out of arbitrary pasted
  // text — bracket decoration, trailing notes ("一般火"), and label
  // prefixes are all discarded so users don't have to hand-clean copies
  // from Google Maps / chat / spreadsheets.
  const [coordInput, setCoordInput] = useState('');
  // Lifts the coord-input strip to clear the bottom status bar. The
  // status bar wraps to extra rows when the window narrows (flexWrap),
  // so its rendered height varies. We observe it directly so the strip
  // sits exactly 12px above whatever height it ends up.
  const [statusBarHeight, setStatusBarHeight] = useState<number>(38);
  useEffect(() => {
    const el = document.querySelector('.status-bar') as HTMLElement | null;
    if (!el) return;
    const update = () => setStatusBarHeight(Math.ceil(el.getBoundingClientRect().height));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener('resize', update);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', update);
    };
  }, []);
  const submitCoordGo = (kind: 'teleport' | 'navigate' = 'teleport') => {
    const parsed = parseCoord(coordInput);
    if (!parsed) {
      if (onShowToast) onShowToast(tRef.current('panel.coord_invalid'));
      return;
    }
    if (kind === 'navigate') onNavigate(parsed.lat, parsed.lng, 'coord');
    else onTeleport(parsed.lat, parsed.lng, 'coord');
    setCoordInput('');
  };
  // Preview-only: pan the map view to the parsed coordinate without
  // touching the iPhone GPS. Lets the user "peek" at a coordinate before
  // deciding to teleport. Keeps the input populated so the next click
  // can promote it to a real teleport / navigate.
  const submitCoordPreview = () => {
    const parsed = parseCoord(coordInput);
    if (!parsed) {
      if (onShowToast) onShowToast(tRef.current('panel.coord_invalid'));
      return;
    }
    if (onCoordPreview) {
      // Parent owns the pan + preview-pin drop. We let it decide so the
      // pin and the camera move together for both this overlay and the
      // bookmark-list "fly camera only" path.
      onCoordPreview(parsed.lat, parsed.lng);
      return;
    }
    const m = mapRef.current;
    if (!m) return;
    const targetZoom = Math.max(m.getZoom(), 16);
    m.setView([parsed.lat, parsed.lng], targetZoom, { animate: true });
  };

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
          onStart={onStart}
          onStop={onStop}
          onPause={onPause}
          onResume={onResume}
          t={tRef}
        />
        {/* Coord input strip — relative positioning inside the flex
            column so the gap above is purely controlled by the parent. */}
        <div
          onContextMenu={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
          className="anim-fade-slide-up"
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'rgba(26, 29, 39, 0.82)',
            backdropFilter: 'blur(14px) saturate(140%)',
            WebkitBackdropFilter: 'blur(14px) saturate(140%)',
            borderRadius: 10,
            padding: '7px 9px',
            boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.06) inset',
            border: '1px solid rgba(108, 140, 255, 0.15)',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6c8cff" strokeWidth="2" style={{ flexShrink: 0 }}>
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          <input
            type="text"
            value={coordInput}
            onChange={(e) => setCoordInput(e.target.value)}
            onKeyDown={(e) => { if (isSubmitEnter(e)) submitCoordGo('teleport'); }}
            placeholder={tRef.current('panel.coord_placeholder')}
            style={{
              width: 210, background: 'transparent', border: 'none',
              color: '#e8e8e8', fontSize: 12, outline: 'none',
              fontFamily: 'monospace',
            }}
          />
          <button
            onClick={async () => {
              try {
                const text = await navigator.clipboard.readText();
                if (text) setCoordInput(text.trim());
              } catch {
                if (onShowToast) onShowToast(tRef.current('panel.paste_denied'));
              }
            }}
            title={tRef.current('panel.paste_tooltip')}
            style={{
              background: 'rgba(255,255,255,0.08)',
              color: '#c7d0e4', border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: 4, padding: '4px 8px', fontSize: 11, fontWeight: 600,
              cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 3,
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2" />
              <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
            </svg>
            {tRef.current('panel.paste')}
          </button>
          <button
            onClick={() => submitCoordGo('teleport')}
            disabled={!coordInput.trim() || !deviceConnected}
            title={t('map.teleport_here')}
            style={{
              background: !coordInput.trim() || !deviceConnected ? 'rgba(108,140,255,0.3)' : '#6c8cff',
              color: '#fff', border: 'none', borderRadius: 4,
              padding: '4px 10px', fontSize: 11, fontWeight: 600,
              cursor: !coordInput.trim() || !deviceConnected ? 'not-allowed' : 'pointer',
            }}
          >{tRef.current('panel.coord_teleport')}</button>
          <button
            onClick={submitCoordPreview}
            disabled={!coordInput.trim()}
            title={tRef.current('panel.coord_preview_tooltip')}
            style={{
              background: 'transparent',
              color: !coordInput.trim() ? 'rgba(199, 208, 228, 0.4)' : '#c7d0e4',
              border: `1px solid ${!coordInput.trim() ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.28)'}`,
              borderRadius: 4,
              padding: '4px 10px', fontSize: 11, fontWeight: 600,
              cursor: !coordInput.trim() ? 'not-allowed' : 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            {tRef.current('panel.coord_preview')}
          </button>
          <button
            onClick={() => submitCoordGo('navigate')}
            disabled={!coordInput.trim() || !deviceConnected}
            title={tRef.current('panel.coord_navigate_tooltip')}
            style={{
              background: 'transparent',
              color: !coordInput.trim() || !deviceConnected ? 'rgba(76, 175, 80, 0.4)' : '#4caf50',
              border: `1px solid ${!coordInput.trim() || !deviceConnected ? 'rgba(76, 175, 80, 0.3)' : 'rgba(76, 175, 80, 0.55)'}`,
              borderRadius: 4,
              padding: '4px 10px', fontSize: 11, fontWeight: 600,
              cursor: !coordInput.trim() || !deviceConnected ? 'not-allowed' : 'pointer',
            }}
          >{tRef.current('panel.coord_navigate')}</button>
        </div>
      </div>

      {/* S2 cell grid level picker — opens via right-click on the S2 toggle
          button OR via the small chip beside the legend below. Snaps to
          discrete levels 8..22, default 17 (Niantic decor cell). */}
      {s2PickerOpen && (
        <div
          onContextMenu={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          className="anim-fade-slide-up"
          style={{
            position: 'absolute',
            left: 56, top: 196, zIndex: 851,
            background: 'rgba(26, 29, 39, 0.94)',
            backdropFilter: 'blur(14px) saturate(160%)',
            WebkitBackdropFilter: 'blur(14px) saturate(160%)',
            border: '1px solid rgba(108, 140, 255, 0.28)',
            borderRadius: 10,
            padding: '10px 12px',
            minWidth: 220,
            boxShadow: '0 12px 32px rgba(12, 18, 40, 0.55)',
            color: '#e8eaf0',
            fontSize: 12,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 600 }}>{tRef.current('map.s2_level_label')}</span>
            <button
              onClick={() => setS2PickerOpen(false)}
              style={{ background: 'transparent', border: 'none', color: '#9499ac', cursor: 'pointer', fontSize: 14, padding: '0 4px' }}
              aria-label="close"
            >×</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <input
              type="range"
              min={8}
              max={22}
              step={1}
              value={s2Level}
              onChange={(e) => setS2Level(parseInt(e.target.value, 10))}
              style={{ flex: 1 }}
            />
            <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#9ac0ff', minWidth: 22, textAlign: 'right' }}>
              L{s2Level}
            </span>
          </div>
          <div style={{ fontSize: 11, color: '#9499ac' }}>
            {(() => {
              const map = mapRef.current;
              const lat = map ? map.getCenter().lat : 0;
              const m = approxCellSizeMeters(s2Level, lat);
              const label = m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
              return tRef.current('map.s2_size_hint', { size: label });
            })()}
          </div>
          {s2Enabled && s2Suppressed && (
            <div style={{
              marginTop: 6, padding: '6px 8px',
              background: 'rgba(255,193,7,0.12)',
              border: '1px solid rgba(255,193,7,0.45)',
              borderRadius: 4,
              fontSize: 11, color: '#ffd54f', lineHeight: 1.4,
            }}>
              {tRef.current('map.s2_zoom_in_hint')}
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            {[13, 14, 15, 16, 17, 18, 19].map((lv) => (
              <button
                key={lv}
                onClick={() => setS2Level(lv)}
                style={{
                  background: s2Level === lv ? 'rgba(108,140,255,0.35)' : 'rgba(255,255,255,0.06)',
                  border: `1px solid ${s2Level === lv ? 'rgba(108,140,255,0.6)' : 'rgba(255,255,255,0.12)'}`,
                  color: s2Level === lv ? '#fff' : '#c7d0e4',
                  fontSize: 11, fontWeight: 600,
                  padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
                }}
              >L{lv}</button>
            ))}
          </div>
          <div style={{ marginTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              onClick={() => setS2Enabled((v) => !v)}
              style={{
                background: s2Enabled ? '#6c8cff' : 'transparent',
                border: `1px solid ${s2Enabled ? '#6c8cff' : 'rgba(255,255,255,0.18)'}`,
                color: s2Enabled ? '#fff' : '#c7d0e4',
                fontSize: 11, fontWeight: 600,
                padding: '4px 10px', borderRadius: 4, cursor: 'pointer',
              }}
            >{s2Enabled ? tRef.current('map.s2_on') : tRef.current('map.s2_off')}</button>
            <span style={{ fontSize: 10, color: '#666c80' }}>{tRef.current('map.s2_picker_hint')}</span>
          </div>
        </div>
      )}

      {/* Recent destinations button + popover (topright, below tile layer
          switcher). Click the clock to toggle a list of the last 20
          places the user flew to; click an entry to re-fly using that
          entry's original action (teleport / navigate / search). */}
      {recentPlaces && (
        <div
          onContextMenu={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            right: 12,
            top: 125,
            zIndex: 851,
          }}
        >
          <button
            onClick={() => setRecentOpen((o) => !o)}
            onMouseEnter={(e) => {
              if (recentOpen) return;
              (e.currentTarget as HTMLButtonElement).style.background =
                'linear-gradient(135deg, rgba(108, 140, 255, 0.35) 0%, rgba(46, 52, 82, 0.95) 100%)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(108, 140, 255, 0.55)';
              (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)';
              (e.currentTarget as HTMLButtonElement).style.boxShadow =
                '0 10px 24px rgba(108, 140, 255, 0.35), 0 2px 6px rgba(12, 18, 40, 0.45)';
            }}
            onMouseLeave={(e) => {
              if (recentOpen) return;
              (e.currentTarget as HTMLButtonElement).style.background =
                'linear-gradient(135deg, rgba(38, 42, 58, 0.92) 0%, rgba(22, 25, 36, 0.92) 100%)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(108, 140, 255, 0.22)';
              (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
              (e.currentTarget as HTMLButtonElement).style.boxShadow = '0 6px 18px rgba(12, 18, 40, 0.45)';
            }}
            title={tRef.current('map.recent_tooltip')}
            style={{
              position: 'relative',
              width: 42, height: 42,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: recentOpen
                ? 'linear-gradient(135deg, #6c8cff 0%, #4c6bd9 100%)'
                : 'linear-gradient(135deg, rgba(38, 42, 58, 0.92) 0%, rgba(22, 25, 36, 0.92) 100%)',
              color: '#fff',
              border: `1px solid ${recentOpen ? 'rgba(108, 140, 255, 0.85)' : 'rgba(108, 140, 255, 0.22)'}`,
              borderRadius: 10,
              cursor: 'pointer',
              boxShadow: recentOpen
                ? '0 10px 28px rgba(108, 140, 255, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.15)'
                : '0 6px 18px rgba(12, 18, 40, 0.45)',
              backdropFilter: 'blur(14px) saturate(160%)',
              WebkitBackdropFilter: 'blur(14px) saturate(160%)',
              transition: 'transform 120ms ease-out, background 120ms ease-out, border-color 120ms ease-out, box-shadow 120ms ease-out',
            }}
          >
            {/* Lucide "History": counterclockwise arrow around a clock
                face. Reads as "past / rewind / history" much more
                clearly than a plain clock icon. */}
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M12 7v5l4 2" />
            </svg>
            {/* Count badge: little pill in the corner showing how many
                entries are recorded, so the user can glance at the map
                and know there's something in history without opening. */}
            {recentPlaces.length > 0 && !recentOpen && (
              <span style={{
                position: 'absolute',
                top: -5, right: -5,
                minWidth: 16, height: 16,
                padding: '0 4px',
                borderRadius: 99,
                background: '#f48fb1',
                color: '#23283a',
                fontSize: 10, fontWeight: 700,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 2px 6px rgba(244, 143, 177, 0.5)',
                border: '1.5px solid rgba(22, 25, 36, 0.92)',
                fontFamily: 'system-ui, sans-serif',
                lineHeight: 1,
              }}>{recentPlaces.length}</span>
            )}
          </button>

          {recentOpen && (
            <div
              // No animation class here: the CSS animation-fill-mode:both
              // on .anim-fade-slide-up pins transform at translateY(0)
              // and wins against any inline transform we apply via drag.
              style={{
                position: 'absolute',
                right: 0,
                top: 48,
                width: 320,
                maxHeight: '62vh',
                display: 'flex', flexDirection: 'column',
                background: 'rgba(26, 29, 39, 0.94)',
                backdropFilter: 'blur(18px) saturate(160%)',
                WebkitBackdropFilter: 'blur(18px) saturate(160%)',
                border: '1px solid rgba(108, 140, 255, 0.22)',
                borderRadius: 12,
                boxShadow: '0 18px 48px rgba(12, 18, 40, 0.65)',
                overflow: 'hidden',
                transform: `translate(${recentDragOffset.x}px, ${recentDragOffset.y}px)`,
              }}
            >
              <div
                onMouseDown={beginRecentDrag}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 12px',
                  borderBottom: '1px solid rgba(255,255,255,0.06)',
                  fontSize: 12, fontWeight: 600, color: '#e8eaf0',
                  cursor: 'move',
                  userSelect: 'none',
                }}
              >
                <span>{tRef.current('map.recent_title')}</span>
                {onRecentClear && recentPlaces.length > 0 && (
                  !clearConfirming ? (
                    <button
                      onClick={() => setClearConfirming(true)}
                      style={{
                        background: 'transparent', border: '1px solid transparent',
                        color: '#9499ac', fontSize: 11, cursor: 'pointer',
                        padding: '2px 8px', borderRadius: 4,
                        transition: 'background 120ms ease, color 120ms ease',
                      }}
                      title={tRef.current('map.recent_clear_tooltip')}
                    >{tRef.current('map.recent_clear')}</button>
                  ) : (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        onClick={() => {
                          onRecentClear();
                          setClearConfirming(false);
                          setRecentOpen(false);
                        }}
                        style={{
                          background: 'rgba(229, 57, 53, 0.18)',
                          border: '1px solid rgba(229, 57, 53, 0.55)',
                          color: '#ff7a6d', fontSize: 11, fontWeight: 700,
                          cursor: 'pointer',
                          padding: '2px 8px', borderRadius: 4,
                        }}
                      >{tRef.current('map.recent_clear_confirm')}</button>
                      <button
                        onClick={() => setClearConfirming(false)}
                        style={{
                          background: 'transparent',
                          border: '1px solid rgba(255, 255, 255, 0.15)',
                          color: '#9499ac', fontSize: 11,
                          cursor: 'pointer',
                          padding: '2px 8px', borderRadius: 4,
                        }}
                      >{tRef.current('generic.cancel')}</button>
                    </div>
                  )
                )}
              </div>
              <div style={{ overflowY: 'auto', flex: 1 }}>
                {recentPlaces.map((entry, idx) => {
                  // Text badge + colour per kind. Coord-input entries
                  // share a single "座標" label regardless of the
                  // teleport / navigate sub-action, since the entry
                  // point is what the user remembers.
                  type BadgeSpec = { label: string; color: string; bg: string };
                  const badgeByKind: Record<string, BadgeSpec> = {
                    teleport:        { label: tRef.current('recent.kind_teleport'),   color: '#6c8cff', bg: 'rgba(108, 140, 255, 0.16)' },
                    navigate:        { label: tRef.current('recent.kind_navigate'),   color: '#4caf50', bg: 'rgba(76, 175, 80, 0.16)' },
                    search:          { label: tRef.current('recent.kind_search'),     color: '#f48fb1', bg: 'rgba(244, 143, 177, 0.16)' },
                    coord_teleport:  { label: tRef.current('recent.kind_coord'),      color: '#ffb74d', bg: 'rgba(255, 183, 77, 0.16)' },
                    coord_navigate:  { label: tRef.current('recent.kind_coord'),      color: '#ffb74d', bg: 'rgba(255, 183, 77, 0.16)' },
                  };
                  const badge = badgeByKind[entry.kind] ?? { label: entry.kind, color: '#9499ac', bg: 'rgba(148, 153, 172, 0.16)' };
                  const now = Math.floor(Date.now() / 1000);
                  const ago = now - (entry.ts || 0);
                  let agoLabel = '';
                  if (ago < 60) agoLabel = tRef.current('time.just_now');
                  else if (ago < 3600) agoLabel = `${Math.floor(ago / 60)} ${tRef.current('time.minutes_ago')}`;
                  else if (ago < 86400) agoLabel = `${Math.floor(ago / 3600)} ${tRef.current('time.hours_ago')}`;
                  else if (ago < 86400 * 7) agoLabel = `${Math.floor(ago / 86400)} ${tRef.current('time.days_ago')}`;
                  else {
                    const d = new Date(entry.ts * 1000);
                    agoLabel = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
                  }
                  const display = entry.name && entry.name.length > 0
                    ? entry.name
                    : `${entry.lat.toFixed(5)}, ${entry.lng.toFixed(5)}`;
                  // Open the shared context menu anchored at the given
                  // viewport coords, carrying the entry's name so the
                  // Add Bookmark item can pre-fill the dialog. Full
                  // object replacement (no spread) so no stale field
                  // from a prior opening leaks in.
                  const openMenuAt = (x: number, y: number) => {
                    setContextMenu({
                      visible: true,
                      x, y,
                      lat: entry.lat,
                      lng: entry.lng,
                      name: entry.name || undefined,
                    });
                  };
                  return (
                    <div
                      key={`${entry.ts}-${idx}`}
                      style={{
                        display: 'flex', alignItems: 'stretch',
                        width: '100%',
                        borderBottom: idx < recentPlaces.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                        transition: 'background 0.12s',
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.04)'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
                      onContextMenu={(e) => {
                        // Suppress the browser's native menu and stop
                        // the event from bubbling to the dropdown's
                        // outside-click handler.
                        e.preventDefault();
                        e.stopPropagation();
                        openMenuAt(e.clientX, e.clientY);
                      }}
                    >
                      <button
                        onClick={() => {
                          if (onRecentReFly) onRecentReFly(entry);
                          setRecentOpen(false);
                        }}
                        style={{
                          flex: 1, minWidth: 0,
                          display: 'flex', alignItems: 'center', gap: 10,
                          padding: '9px 12px',
                          background: 'transparent', border: 'none',
                          color: '#e8eaf0', textAlign: 'left',
                          cursor: 'pointer',
                        }}
                      >
                        <span style={{
                          flexShrink: 0,
                          fontSize: 10, fontWeight: 700,
                          letterSpacing: '0.05em',
                          color: badge.color,
                          background: badge.bg,
                          border: `1px solid ${badge.color}33`,
                          borderRadius: 4,
                          padding: '3px 6px',
                          minWidth: 34,
                          textAlign: 'center',
                        }}>{badge.label}</span>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          {(() => {
                            // If this entry's coords match an existing
                            // bookmark, show the bookmark's name + geo
                            // line so the row reads like a bookmark
                            // entry while keeping the kind badge + time
                            // (those are history-specific).
                            const match = bookmarkByCoord.get(
                              `${entry.lat.toFixed(5)}|${entry.lng.toFixed(5)}`
                            );
                            if (match) {
                              const hasGeo = !!(match.country_code || match.city || match.timezone);
                              return (
                                <>
                                  <div style={{
                                    fontSize: 13, fontWeight: 500,
                                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                  }}>{match.name}</div>
                                  <div style={{
                                    fontSize: 10, marginTop: 2,
                                    display: 'flex', alignItems: 'center', gap: 4,
                                    minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden',
                                  }}>
                                    <BookmarkGeoLine
                                      countryCode={match.country_code}
                                      city={match.city}
                                      timezone={match.timezone}
                                    />
                                    {hasGeo && <span style={{ opacity: 0.55 }}>·</span>}
                                    <span style={{ opacity: 0.55, fontFamily: 'monospace' }}>{agoLabel}</span>
                                  </div>
                                </>
                              );
                            }
                            return (
                              <>
                                <div style={{
                                  fontSize: 13, fontWeight: 500,
                                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                }}>{display}</div>
                                <div style={{
                                  fontSize: 10, opacity: 0.55, fontFamily: 'monospace', marginTop: 2,
                                }}>
                                  {entry.lat.toFixed(5)}, {entry.lng.toFixed(5)} · {agoLabel}
                                </div>
                              </>
                            );
                          })()}
                        </div>
                      </button>
                      <button
                        title={tRef.current('recent.menu_tooltip')}
                        aria-label={tRef.current('recent.menu_tooltip')}
                        onClick={(e) => {
                          e.stopPropagation();
                          openMenuAt(e.clientX, e.clientY);
                        }}
                        style={{
                          flexShrink: 0, alignSelf: 'stretch',
                          padding: '0 10px',
                          background: 'transparent', border: 'none',
                          color: '#9499ac',
                          cursor: 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          transition: 'color 0.12s, background 0.12s',
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.color = '#e8eaf0';
                          (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.06)';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.color = '#9499ac';
                          (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="12" cy="5"  r="1" />
                          <circle cx="12" cy="12" r="1" />
                          <circle cx="12" cy="19" r="1" />
                        </svg>
                      </button>
                    </div>
                  );
                })}
                {recentPlaces.length === 0 && (
                  <div style={{ padding: 16, fontSize: 12, opacity: 0.6, textAlign: 'center' }}>
                    {tRef.current('map.recent_empty')}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {contextMenu.visible && (
        <div
          ref={contextMenuElRef}
          className="context-menu anim-scale-in-tl"
          style={{
            position: 'fixed',
            // First paint renders at the click point but invisible; the
            // layout-effect below measures the actual rendered size and
            // clamps left/top into the viewport, then flips visibility on.
            // Because the layout effect runs synchronously before the
            // browser paints, the user never sees the unclamped position.
            left: contextMenuPos ? contextMenuPos.left : contextMenu.x,
            top: contextMenuPos ? contextMenuPos.top : contextMenu.y,
            visibility: contextMenuPos ? 'visible' : 'hidden',
            zIndex: 1000,
            background: 'rgba(26, 29, 39, 0.95)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            border: '1px solid rgba(108, 140, 255, 0.18)',
            borderRadius: 10,
            padding: '4px 0',
            boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.04) inset',
            minWidth: 180,
            maxWidth: 'calc(100vw - 16px)',
            maxHeight: 'calc(100vh - 16px)',
            overflow: 'auto',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* 1. Coordinates label — always visible at the top of the menu.
                Not clickable; shows the exact lat/lng of the right-click
                target directly instead of making the user click through. */}
          <div
            className="context-menu-item"
            style={{
              padding: '8px 16px 6px',
              color: '#9ac0ff',
              fontSize: 12,
              fontFamily: 'monospace',
              display: 'flex',
              alignItems: 'center',
              cursor: 'pointer',
              gap: 4,
            }}
            title={t('map.whats_here_tooltip')}
            onMouseEnter={highlightItem}
            onMouseLeave={unhighlightItem}
            onClick={async (e) => {
              e.stopPropagation();
              const key = `${contextMenu.lat.toFixed(6)}|${contextMenu.lng.toFixed(6)}`;
              if (reverseGeo.loading && reverseGeo.key === key) return;
              if (reverseGeo.address && reverseGeo.key === key) return;
              setReverseGeo({ loading: true, address: null, error: null, key });
              try {
                const res = await api.reverseGeocode(contextMenu.lat, contextMenu.lng);
                const name = res?.display_name || res?.address || null;
                if (name) {
                  setReverseGeo({ loading: false, address: name, error: null, key });
                } else {
                  setReverseGeo({ loading: false, address: null, error: t('map.whats_here_empty'), key });
                }
              } catch (err: any) {
                setReverseGeo({ loading: false, address: null, error: err?.message || 'error', key });
              }
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 4, opacity: 0.8 }}>
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
            <span style={{ flex: 1 }}>{contextMenu.lat.toFixed(6)}, {contextMenu.lng.toFixed(6)}</span>
            <span style={{ fontSize: 10, opacity: 0.7, fontFamily: 'inherit' }}>
              {reverseGeo.loading && reverseGeo.key === `${contextMenu.lat.toFixed(6)}|${contextMenu.lng.toFixed(6)}`
                ? t('map.whats_here_loading')
                : t('map.whats_here')}
            </span>
          </div>
          {/* Reverse-geocode result or error, shown only after the user taps
              the header row. Wraps + selectable so the user can copy the
              address. Max width is clipped by .context-menu parent. */}
          {reverseGeo.key === `${contextMenu.lat.toFixed(6)}|${contextMenu.lng.toFixed(6)}` &&
           (reverseGeo.address || reverseGeo.error) && (
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                padding: '2px 16px 8px',
                color: reverseGeo.error ? '#ff8a80' : '#d0d0d0',
                fontSize: 11.5,
                lineHeight: 1.5,
                userSelect: 'text',
                cursor: 'text',
                wordBreak: 'break-word',
              }}
            >
              {reverseGeo.address ?? reverseGeo.error}
            </div>
          )}
          <div style={{ height: 1, background: '#444', margin: '2px 0 4px' }} />

          {/* 2 + 3. Teleport / Navigate (device-gated). */}
          {deviceConnected ? (
            <>
              <div
                className="context-menu-item"
                style={contextMenuItemStyle}
                onMouseEnter={highlightItem}
                onMouseLeave={unhighlightItem}
                onClick={() => {
                  onTeleport(contextMenu.lat, contextMenu.lng);
                  closeContextMenu();
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="2" x2="12" y2="6" />
                  <line x1="12" y1="18" x2="12" y2="22" />
                  <line x1="2" y1="12" x2="6" y2="12" />
                  <line x1="18" y1="12" x2="22" y2="12" />
                </svg>
                {t('map.teleport_here')}
              </div>
              <div
                className="context-menu-item"
                style={contextMenuItemStyle}
                onMouseEnter={highlightItem}
                onMouseLeave={unhighlightItem}
                onClick={() => {
                  onNavigate(contextMenu.lat, contextMenu.lng);
                  closeContextMenu();
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <polygon points="3,11 22,2 13,21 11,13" />
                </svg>
                {t('map.navigate_here')}
              </div>
              {onSetAsGoldDittoA && (
                <div
                  className="context-menu-item"
                  style={contextMenuItemStyle}
                  onMouseEnter={highlightItem}
                  onMouseLeave={unhighlightItem}
                  onClick={() => {
                    onSetAsGoldDittoA(contextMenu.lat, contextMenu.lng);
                    closeContextMenu();
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <path d="M12 2 L13.5 9 L21 12 L13.5 15 L12 22 L10.5 15 L3 12 L10.5 9 Z" />
                  </svg>
                  {t('goldditto.set_as_a')}
                </div>
              )}
            </>
          ) : (
            <div
              style={{ ...contextMenuItemStyle, color: '#ff6b6b', cursor: 'not-allowed', opacity: 0.75 }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                <circle cx="12" cy="12" r="10" />
                <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
              </svg>
              {t('map.device_disconnected')}
            </div>
          )}

          {/* 4. Copy coordinates to clipboard. */}
          <div
            className="context-menu-item"
            style={contextMenuItemStyle}
            onMouseEnter={highlightItem}
            onMouseLeave={unhighlightItem}
            onClick={async () => {
              const txt = `${contextMenu.lat.toFixed(6)}, ${contextMenu.lng.toFixed(6)}`;
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
              if (onShowToast) onShowToast(tRef.current('map.coords_copied'));
              closeContextMenu();
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
            {t('map.copy_coords')}
          </div>

          {/* 5. Add to bookmarks — disabled when the coord matches an
              existing bookmark, to prevent duplicates. Visual mirrors
              the device-disconnected disabled item above. */}
          {(() => {
            const ctxMatch = bookmarkByCoord.get(
              `${contextMenu.lat.toFixed(5)}|${contextMenu.lng.toFixed(5)}`
            );
            if (ctxMatch) {
              return (
                <div
                  style={{ ...contextMenuItemStyle, color: '#9499ac', cursor: 'not-allowed', opacity: 0.75 }}
                  title={ctxMatch.name}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
                  </svg>
                  {t('map.already_bookmarked')}
                </div>
              );
            }
            return (
              <div
                className="context-menu-item"
                style={contextMenuItemStyle}
                onMouseEnter={highlightItem}
                onMouseLeave={unhighlightItem}
                onClick={() => {
                  onAddBookmark(contextMenu.lat, contextMenu.lng, contextMenu.name);
                  closeContextMenu();
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
                </svg>
                {t('map.add_bookmark')}
              </div>
            );
          })()}

          {/* 6. Add waypoint (only when in a route mode). */}
          {showWaypointOption && onAddWaypoint && (
            <>
              <div style={{ height: 1, background: '#444', margin: '4px 0' }} />
              <div
                className="context-menu-item"
                style={contextMenuItemStyle}
                onMouseEnter={highlightItem}
                onMouseLeave={unhighlightItem}
                onClick={() => {
                  onAddWaypoint(contextMenu.lat, contextMenu.lng);
                  closeContextMenu();
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <circle cx="12" cy="12" r="3" />
                  <line x1="12" y1="5" x2="12" y2="1" />
                  <line x1="12" y1="23" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="1" y2="12" />
                  <line x1="23" y1="12" x2="19" y2="12" />
                </svg>
                {t('map.add_waypoint')}
              </div>
            </>
          )}

        </div>
      )}

      {wpMenu.visible && (
        <div
          className="context-menu anim-scale-in-tl"
          style={{
            position: 'fixed',
            // Offset slightly so the cursor lands inside the menu rather
            // than on its edge (otherwise the document-level click handler
            // might immediately close it).
            left: Math.max(8, Math.min(wpMenu.x + 6, window.innerWidth - 188)),
            top: Math.max(8, Math.min(wpMenu.y + 6, window.innerHeight - 100)),
            zIndex: 1000,
            background: 'rgba(26, 29, 39, 0.96)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            border: '1px solid rgba(108, 140, 255, 0.18)',
            borderRadius: 10,
            padding: '4px 0',
            boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.04) inset',
            minWidth: 180,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            style={{
              padding: '6px 14px 4px',
              fontSize: 11,
              opacity: 0.55,
              fontFamily: 'monospace',
              borderBottom: '1px solid rgba(255,255,255,0.05)',
              marginBottom: 2,
            }}
          >
            {wpMenu.isStart ? tRef.current('panel.waypoint_start') : `#${wpMenu.index}`}
          </div>
          {!wpMenu.isStart && onSetWpAsStartRef.current && (
            <div
              style={contextMenuItemStyle}
              onMouseEnter={highlightItem}
              onMouseLeave={unhighlightItem}
              onClick={() => {
                const fn = onSetWpAsStartRef.current;
                const idx = wpMenu.index;
                closeWpMenu();
                fn?.(idx);
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#43a047" strokeWidth="2" style={{ marginRight: 8 }}>
                <line x1="4" y1="22" x2="4" y2="3" />
                <path d="M4 4h12l-2 4 2 4H4" fill="#43a04733" />
              </svg>
              {t('map.wp_set_as_start')}
            </div>
          )}
          {onInsertAfterWpRef.current && (
            <div
              style={contextMenuItemStyle}
              onMouseEnter={highlightItem}
              onMouseLeave={unhighlightItem}
              onClick={() => {
                const fn = onInsertAfterWpRef.current;
                const idx = wpMenu.index;
                closeWpMenu();
                fn?.(idx);
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6c8cff" strokeWidth="2" style={{ marginRight: 8 }}>
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              {t('map.wp_insert_after')}
            </div>
          )}
          {onRemoveWaypointRef.current && (
            <div
              style={{ ...contextMenuItemStyle, color: '#ff6b6b' }}
              onMouseEnter={highlightItem}
              onMouseLeave={unhighlightItem}
              onClick={() => {
                const fn = onRemoveWaypointRef.current;
                const idx = wpMenu.index;
                closeWpMenu();
                fn?.(idx);
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
              </svg>
              {t('map.wp_delete')}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const contextMenuItemStyle: React.CSSProperties = {
  padding: '8px 16px',
  cursor: 'pointer',
  color: '#e0e0e0',
  fontSize: 13,
  display: 'flex',
  alignItems: 'center',
  transition: 'background 0.15s',
};

function highlightItem(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}

function unhighlightItem(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}

export default MapView;
