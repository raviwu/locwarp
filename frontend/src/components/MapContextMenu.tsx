import React, { useRef, useState, useLayoutEffect } from 'react';
import { useT } from '../i18n';
import {
  contextMenuItemStyle,
  highlightItem,
  unhighlightItem,
} from '../utils/contextMenuStyle';

// Subset of a bookmark pin the context menu needs for the "already bookmarked"
// disabled item. Mirrors MapView's bookmarkByCoord match value.
interface CtxBookmarkMatch {
  name: string;
}

interface MapContextMenuProps {
  // The right-click target's lat/lng + the viewport coords the menu anchors to.
  lat: number;
  lng: number;
  x: number;
  y: number;
  // Set when the menu was opened from a history entry with a known name (an
  // address from search). Forwarded to onAddBookmark to pre-fill the dialog.
  // Undefined when opened from a plain map right-click.
  name?: string;

  // Injected reverse-geocode gateway (MapView's api.reverseGeocode). Kept as a
  // prop so this component stays free of ServicesContext coupling + unit-testable.
  reverseGeocode: (lat: number, lng: number) => Promise<any>;

  // Already-bookmarked detection. When a match exists for this coord, the Add
  // Bookmark item renders disabled (prevents duplicates). MapView passes the
  // result of bookmarkByCoord.get(`${lat.toFixed(5)}|${lng.toFixed(5)}`).
  bookmarkMatch?: CtxBookmarkMatch;

  // --- Gating flags, mirroring the inline menu's conditionals ---------------
  deviceConnected: boolean;
  showWaypointOption?: boolean;

  // --- The 7 actions, identical callbacks/args to the original inline menu --
  onTeleport: (lat: number, lng: number) => void;
  onNavigate: (lat: number, lng: number) => void;
  onSetAsGoldDittoA?: (lat: number, lng: number) => void;
  onCopy: () => void;
  onAddBookmark: (lat: number, lng: number, suggestedName?: string) => void;
  onAddWaypoint?: (lat: number, lng: number) => void;

  // Close the menu (clears the parent's contextMenu open-state).
  onClose: () => void;
}

/**
 * Map right-click context menu — extracted VERBATIM from MapView's inline JSX
 * (Phase 4b, task p4b2bii). Same classNames / markup / inline styles / i18n
 * keys / per-action callbacks + args as the original.
 *
 * Two load-bearing mechanisms are preserved EXACTLY:
 *  1. The viewport-clamp layout-effect. Its dep list DELIBERATELY EXCLUDES the
 *     painted position (contextMenuPos) — including it would re-trigger the
 *     effect on every setState and reproduce the v0.2.38 reposition loop.
 *  2. The reverse-geocode stale-guard. The parent mounts this per-open (keyed
 *     on the open coords) so "is this the same open?" reduces to "is this menu
 *     instance still mounted?". `mountedRef` flips false on unmount; a late
 *     reverseGeocode resolve is then dropped instead of leaking a stale address.
 */
const MapContextMenu: React.FC<MapContextMenuProps> = ({
  lat,
  lng,
  x,
  y,
  name,
  reverseGeocode,
  bookmarkMatch,
  deviceConnected,
  showWaypointOption,
  onTeleport,
  onNavigate,
  onSetAsGoldDittoA,
  onCopy,
  onAddBookmark,
  onAddWaypoint,
  onClose,
}) => {
  const t = useT();

  // DOM ref + clamped position state. Separate states for "click point" and
  // "where the menu is actually painted" — the paint position is set ONCE
  // per open via useLayoutEffect after measuring the real rendered size.
  // Critical: the layout effect's deps do NOT include contextMenuPos itself,
  // otherwise the setState triggers the effect again and we get an infinite
  // reposition loop (that was v0.2.38's bug).
  const contextMenuElRef = useRef<HTMLDivElement | null>(null);
  const [contextMenuPos, setContextMenuPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const el = contextMenuElRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    // Clamp: prefer opening rightward / downward, but if that overflows,
    // push the menu back in so it never clips the viewport edge.
    const left = Math.max(margin, Math.min(x, vw - width - margin));
    const top  = Math.max(margin, Math.min(y, vh - height - margin));
    setContextMenuPos({ left, top });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [x, y]);

  // Reverse-geocode state for the context menu header row. The menu is mounted-
  // per-open by the parent, so this resets on every open without an explicit
  // clear. The stale-guard below drops a late resolve after unmount.
  const [reverseGeo, setReverseGeo] = useState<{
    loading: boolean; address: string | null; error: string | null;
    key: string; // lat|lng the result belongs to
  }>({ loading: false, address: null, error: null, key: '' });

  // Reverse-geocode stale-guard. The menu is mounted-per-open (the parent keys
  // it on the open coords), so "is this still the same open?" reduces to "is
  // this menu instance still mounted?". The ref flips false on unmount so a late
  // reverseGeocode resolve is dropped instead of writing back stale state.
  const mountedRef = useRef(true);
  useLayoutEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Centralize the lat|lng key so the click handler, loading indicator, and
  // result-conditional all use the exact same string.
  const headerKey = `${lat.toFixed(6)}|${lng.toFixed(6)}`;

  return (
    <div
      ref={contextMenuElRef}
      className="context-menu anim-scale-in-tl"
      style={{
        position: 'fixed',
        // First paint renders at the click point but invisible; the
        // layout-effect above measures the actual rendered size and
        // clamps left/top into the viewport, then flips visibility on.
        // Because the layout effect runs synchronously before the
        // browser paints, the user never sees the unclamped position.
        left: contextMenuPos ? contextMenuPos.left : x,
        top: contextMenuPos ? contextMenuPos.top : y,
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
          if (reverseGeo.loading && reverseGeo.key === headerKey) return;
          if (reverseGeo.address && reverseGeo.key === headerKey) return;
          setReverseGeo({ loading: true, address: null, error: null, key: headerKey });
          try {
            const res = await reverseGeocode(lat, lng);
            // Menu was dismissed or re-targeted while the request was in flight —
            // drop the result so it doesn't leak into the next menu open.
            if (!mountedRef.current) return;
            const name = res?.display_name || res?.address || null;
            if (name) {
              setReverseGeo({ loading: false, address: name, error: null, key: headerKey });
            } else {
              setReverseGeo({ loading: false, address: null, error: t('map.whats_here_empty'), key: headerKey });
            }
          } catch (err: any) {
            if (!mountedRef.current) return;
            setReverseGeo({ loading: false, address: null, error: err?.message || 'error', key: headerKey });
          }
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 4, opacity: 0.8 }}>
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        <span style={{ flex: 1 }}>{lat.toFixed(6)}, {lng.toFixed(6)}</span>
        <span style={{ fontSize: 10, opacity: 0.7, fontFamily: 'inherit' }}>
          {reverseGeo.loading && reverseGeo.key === headerKey
            ? t('map.whats_here_loading')
            : t('map.whats_here')}
        </span>
      </div>
      {/* Reverse-geocode result or error, shown only after the user taps
          the header row. Wraps + selectable so the user can copy the
          address. Max width is clipped by .context-menu parent. */}
      {reverseGeo.key === headerKey &&
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
              onTeleport(lat, lng);
              onClose();
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
              onNavigate(lat, lng);
              onClose();
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
                onSetAsGoldDittoA(lat, lng);
                onClose();
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
        onClick={() => {
          onCopy();
          onClose();
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
      {bookmarkMatch ? (
        <div
          style={{ ...contextMenuItemStyle, color: '#9499ac', cursor: 'not-allowed', opacity: 0.75 }}
          title={bookmarkMatch.name}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
            <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
          </svg>
          {t('map.already_bookmarked')}
        </div>
      ) : (
        <div
          className="context-menu-item"
          style={contextMenuItemStyle}
          onMouseEnter={highlightItem}
          onMouseLeave={unhighlightItem}
          onClick={() => {
            onAddBookmark(lat, lng, name);
            onClose();
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
            <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
          </svg>
          {t('map.add_bookmark')}
        </div>
      )}

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
              onAddWaypoint(lat, lng);
              onClose();
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
  );
};

export default MapContextMenu;
