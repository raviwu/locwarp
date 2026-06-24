import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../i18n';

// Loose bookmark shape — mirrors the row/list shapes. Only the fields the
// context menu actually touches are required.
interface MenuBookmark {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
}

interface BookmarkContextMenuProps {
  // The right-clicked bookmark + the screen coords the menu anchors to.
  bm: MenuBookmark;
  x: number;
  y: number;
  // Close the menu (clears the parent's contextMenu state).
  onClose: () => void;
  // Injected reverse-geocode gateway (api.reverseGeocode). Kept as a prop so
  // this component stays free of ServicesContext coupling + unit-testable.
  reverseGeocode: (lat: number, lng: number) => Promise<any>;
  // --- The 9 actions, mirroring the map/history context menus ---------------
  deviceConnected: boolean;
  showWaypointOption: boolean;
  onTeleport: (lat: number, lng: number) => void;
  onNavigate: (lat: number, lng: number) => void;
  onSetAsGoldDittoA?: (lat: number, lng: number) => void;
  onAddWaypoint?: (lat: number, lng: number) => void;
  onEdit: (bm: MenuBookmark) => void;
  onCopy: (bm: MenuBookmark) => void;
  onDelete: (id: string) => void;
  onMoveToCategory: (id: string, cat: string) => void;
  // Categories for the "Move to" submenu, plus rendering helpers shared with
  // the list (kept as props so the menu doesn't re-derive colors).
  categories: string[];
  resolveColor: (name: string) => string;
  displayCat: (name: string) => string;
  // Toast hook for the "coords copied" feedback (copy action).
  onShowToast?: (msg: string) => void;
}

const ctxItemStyle: React.CSSProperties = {
  padding: '6px 12px',
  cursor: 'pointer',
  fontSize: 12,
  display: 'flex',
  alignItems: 'center',
  color: '#e0e0e0',
  transition: 'background 0.15s',
};

function ctxHighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}
function ctxUnhighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}

/**
 * Portal-rendered right-click context menu for a bookmark row.
 *
 * Owns three interdependent guard mechanisms that MUST stay together (splitting
 * them reintroduces a stale-address leak):
 *  1. Dismissal effect — pointerdown / contextmenu / Escape document listeners
 *     registered on a setTimeout(0) so the opening right-click doesn't self-close.
 *  2. Close-reset effect — clears the reverse-geocode state on unmount/close.
 *  3. Reverse-geocode stale-guard — an open-snapshot ref so a late reverseGeocode
 *     result is dropped if the menu has since closed / re-targeted.
 */
const BookmarkContextMenu: React.FC<BookmarkContextMenuProps> = ({
  bm,
  x,
  y,
  onClose,
  reverseGeocode,
  deviceConnected,
  showWaypointOption,
  onTeleport,
  onNavigate,
  onSetAsGoldDittoA,
  onAddWaypoint,
  onEdit,
  onCopy,
  onDelete,
  onMoveToCategory,
  categories,
  resolveColor,
  displayCat,
}) => {
  const t = useT();

  // Reverse-geocode state for the menu's coords header. Reset whenever the
  // menu unmounts/closes — see the close-reset effect below.
  const [reverseGeo, setReverseGeo] = useState<{
    loading: boolean; address: string | null; error: string | null;
    key: string; // lat|lng the result belongs to
  }>({ loading: false, address: null, error: null, key: '' });

  // 1. Dismissal effect. Close on ESC, or on any click / right-click that
  // isn't on the menu itself. Uses pointerdown so it fires before React
  // click handlers inside the menu. Registered on the next tick so the
  // opening right-click's bubbling doesn't dismiss the menu immediately.
  useEffect(() => {
    const onOutside = (e: Event) => {
      const target = e.target as Element | null;
      if (target && target.closest?.('[data-bookmark-context-menu]')) return;
      onClose();
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const id = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside);
      document.addEventListener('contextmenu', onOutside);
      document.addEventListener('keydown', onEsc);
    }, 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener('pointerdown', onOutside);
      document.removeEventListener('contextmenu', onOutside);
      document.removeEventListener('keydown', onEsc);
    };
  }, [onClose]);

  // 2. Close-reset effect. Drop any in-flight or completed reverse-geocode
  // result when the menu unmounts, so a stale address from a previous
  // right-click can never leak into a new lookup.
  useEffect(() => {
    return () => {
      setReverseGeo({ loading: false, address: null, error: null, key: '' });
    };
  }, []);

  // 3. Reverse-geocode stale-guard. The menu is mounted-per-open (the parent
  // keys it on the open), so "is this still the same open?" reduces to "is
  // this menu instance still mounted?". The ref flips false on unmount so a
  // late reverseGeocode resolve is dropped instead of writing back stale state.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Centralize the lat|lng key so the click handler, loading indicator, and
  // result-conditional all use the exact same string.
  const headerKey = `${bm.lat.toFixed(6)}|${bm.lng.toFixed(6)}`;

  return createPortal(
    <>
      <div
        data-bookmark-context-menu
        style={{
          position: 'fixed',
          // Clamp to viewport so the menu never falls off-screen.
          left: Math.min(x, window.innerWidth - 200),
          top: Math.min(y, window.innerHeight - 360),
          zIndex: 9999,
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
      >
        {/* 1. Coords header — clickable to trigger reverse-geocode. */}
        <div
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
          onMouseEnter={ctxHighlight}
          onMouseLeave={ctxUnhighlight}
          onClick={async (e) => {
            e.stopPropagation();
            if (reverseGeo.loading && reverseGeo.key === headerKey) return;
            if (reverseGeo.address && reverseGeo.key === headerKey) return;
            setReverseGeo({ loading: true, address: null, error: null, key: headerKey });
            try {
              const res = await reverseGeocode(bm.lat, bm.lng);
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
          <span style={{ flex: 1 }}>{bm.lat.toFixed(6)}, {bm.lng.toFixed(6)}</span>
          <span style={{ fontSize: 10, opacity: 0.7, fontFamily: 'inherit' }}>
            {reverseGeo.loading && reverseGeo.key === headerKey
              ? t('map.whats_here_loading')
              : t('map.whats_here')}
          </span>
        </div>
        {/* Reverse-geocode result or error, shown only after the user taps the header row. */}
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
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                onTeleport(bm.lat, bm.lng);
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
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                onNavigate(bm.lat, bm.lng);
                onClose();
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                <polygon points="3,11 22,2 13,21 11,13" />
              </svg>
              {t('map.navigate_here')}
            </div>
          </>
        ) : (
          <div
            style={{ ...ctxItemStyle, color: '#ff6b6b', cursor: 'not-allowed', opacity: 0.75 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
              <circle cx="12" cy="12" r="10" />
              <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
            </svg>
            {t('map.device_disconnected')}
          </div>
        )}

        {/* 4. Set as Gold Ditto A (always wired in practice). */}
        {onSetAsGoldDittoA && (
          <div
            style={ctxItemStyle}
            onMouseEnter={ctxHighlight}
            onMouseLeave={ctxUnhighlight}
            onClick={() => {
              onSetAsGoldDittoA(bm.lat, bm.lng);
              onClose();
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
              <path d="M12 2 L13.5 9 L21 12 L13.5 15 L12 22 L10.5 15 L3 12 L10.5 9 Z" />
            </svg>
            {t('goldditto.set_as_a')}
          </div>
        )}

        {/* 5. Add as Waypoint (only in a route mode). */}
        {showWaypointOption && onAddWaypoint && (
          <div
            style={ctxItemStyle}
            onMouseEnter={ctxHighlight}
            onMouseLeave={ctxUnhighlight}
            onClick={() => {
              onAddWaypoint(bm.lat, bm.lng);
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
        )}

        <div style={{ height: 1, background: '#444', margin: '4px 0' }} />

        {/* 6. Edit. */}
        <div
          style={ctxItemStyle}
          onMouseEnter={ctxHighlight}
          onMouseLeave={ctxUnhighlight}
          onClick={() => {
            onEdit(bm);
            onClose();
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
            <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
          {t('bm.edit')}
        </div>

        {/* 7. Copy (name + lat/lng). */}
        <div
          style={ctxItemStyle}
          onMouseEnter={ctxHighlight}
          onMouseLeave={ctxUnhighlight}
          onClick={() => {
            onCopy(bm);
            onClose();
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
          {t('bm.copy')}
        </div>

        {/* 8. Delete. */}
        <div
          style={ctxItemStyle}
          onMouseEnter={ctxHighlight}
          onMouseLeave={ctxUnhighlight}
          onClick={() => {
            if (bm.id && window.confirm(t('bm.delete_one_confirm', { name: bm.name }))) {
              onDelete(bm.id);
            }
            onClose();
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f44336" strokeWidth="2" style={{ marginRight: 6 }}>
            <polyline points="3,6 5,6 21,6" />
            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
          </svg>
          <span style={{ color: '#f44336' }}>{t('generic.delete')}</span>
        </div>

        {/* 9. Move to category (only when more than one category exists). */}
        {categories.length > 1 && (
          <>
            <div style={{ height: 1, background: '#444', margin: '4px 0' }} />
            <div style={{ padding: '4px 12px', fontSize: 10, opacity: 0.5 }}>{t('bm.move_to')}</div>
            <div style={{ maxHeight: 240, overflowY: 'auto' }}>
              {categories
                .filter((c) => c !== bm.category)
                .map((cat) => (
                  <div
                    key={cat}
                    style={ctxItemStyle}
                    onMouseEnter={ctxHighlight}
                    onMouseLeave={ctxUnhighlight}
                    onClick={() => {
                      if (bm.id) {
                        onMoveToCategory(bm.id, cat);
                      }
                      onClose();
                    }}
                  >
                    <div
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        background: resolveColor(cat),
                        marginRight: 6,
                      }}
                    />
                    {displayCat(cat)}
                  </div>
                ))}
            </div>
          </>
        )}
      </div>
    </>,
    document.body,
  );
};

export default BookmarkContextMenu;
