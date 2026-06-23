import React, { useState, useEffect } from 'react';
import { useT } from '../i18n';
import { BookmarkGeoLine } from './BookmarkGeoLine';

// One recent-destination entry (last 20 teleport / navigate / search actions).
export interface RecentPlaceEntry {
  lat: number;
  lng: number;
  kind: 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate';
  name: string;
  ts: number;
}

// The bookmark-by-coord match value: a bookmark pin (subset used by a row).
export interface RecentBookmarkMatch {
  name: string;
  country_code?: string;
  city?: string;
  timezone?: string;
}

interface RecentPlacesPopoverProps {
  // The recent-destination list. The whole control renders nothing when this
  // is undefined (mirrors MapView's `{recentPlaces && (…)}` outer gate); an
  // empty array still renders the button + the "empty" popover state.
  recentPlaces?: RecentPlaceEntry[];

  // Lookup: `${lat.toFixed(5)}|${lng.toFixed(5)}` → matching bookmark. Owned by
  // MapView (also consumed by its context menu), passed in so a matched row can
  // render the bookmark's name + geo line. Read with the same toFixed(5) key.
  bookmarkByCoord: Map<string, RecentBookmarkMatch>;

  // Re-fly: clicking a row re-runs that entry's original action (teleport /
  // navigate / search). Optional to mirror MapView's onRecentReFly prop.
  onRecentReFly?: (entry: RecentPlaceEntry) => void;
  // Clear all recent destinations. When omitted, the clear button is hidden.
  onRecentClear?: () => void;

  // Opens MapView's shared right-click context menu anchored at the given
  // viewport coords, carrying the entry's lat/lng + (optional) name so the
  // Add Bookmark item can pre-fill the dialog. MapView wires this to its
  // setContextMenu — the menu JSX itself stays in MapView.
  onOpenContextMenu: (lat: number, lng: number, name: string | undefined, x: number, y: number) => void;
}

// Recent destinations button + draggable popover (topright, below the tile
// layer switcher). Click the clock to toggle a list of the last 20 places the
// user flew to; click an entry to re-fly using that entry's original action.
// Extracted VERBATIM from MapView's inline JSX (Phase 4b, task p4b2bii) — same
// classNames / markup / inline styles / i18n keys / per-row badge + relative-
// time + bookmark-match rendering. Owns its own open / clear-confirm / drag-
// offset state + the capture-phase document drag listeners (which were always
// local to this popover in MapView); MapView passes the data + the re-fly /
// clear / open-context-menu callbacks.
export const RecentPlacesPopover: React.FC<RecentPlacesPopoverProps> = ({
  recentPlaces,
  bookmarkByCoord,
  onRecentReFly,
  onRecentClear,
  onOpenContextMenu,
}) => {
  const t = useT();
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

  // The whole control renders nothing when recentPlaces is undefined
  // (mirrors MapView's `{recentPlaces && (…)}` outer gate).
  if (!recentPlaces) return null;

  return (
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
        title={t('map.recent_tooltip')}
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
            <span>{t('map.recent_title')}</span>
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
                  title={t('map.recent_clear_tooltip')}
                >{t('map.recent_clear')}</button>
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
                  >{t('map.recent_clear_confirm')}</button>
                  <button
                    onClick={() => setClearConfirming(false)}
                    style={{
                      background: 'transparent',
                      border: '1px solid rgba(255, 255, 255, 0.15)',
                      color: '#9499ac', fontSize: 11,
                      cursor: 'pointer',
                      padding: '2px 8px', borderRadius: 4,
                    }}
                  >{t('generic.cancel')}</button>
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
                teleport:        { label: t('recent.kind_teleport'),   color: '#6c8cff', bg: 'rgba(108, 140, 255, 0.16)' },
                navigate:        { label: t('recent.kind_navigate'),   color: '#4caf50', bg: 'rgba(76, 175, 80, 0.16)' },
                search:          { label: t('recent.kind_search'),     color: '#f48fb1', bg: 'rgba(244, 143, 177, 0.16)' },
                coord_teleport:  { label: t('recent.kind_coord'),      color: '#ffb74d', bg: 'rgba(255, 183, 77, 0.16)' },
                coord_navigate:  { label: t('recent.kind_coord'),      color: '#ffb74d', bg: 'rgba(255, 183, 77, 0.16)' },
              };
              const badge = badgeByKind[entry.kind] ?? { label: entry.kind, color: '#9499ac', bg: 'rgba(148, 153, 172, 0.16)' };
              const now = Math.floor(Date.now() / 1000);
              const ago = now - (entry.ts || 0);
              let agoLabel = '';
              if (ago < 60) agoLabel = t('time.just_now');
              else if (ago < 3600) agoLabel = `${Math.floor(ago / 60)} ${t('time.minutes_ago')}`;
              else if (ago < 86400) agoLabel = `${Math.floor(ago / 3600)} ${t('time.hours_ago')}`;
              else if (ago < 86400 * 7) agoLabel = `${Math.floor(ago / 86400)} ${t('time.days_ago')}`;
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
                onOpenContextMenu(entry.lat, entry.lng, entry.name || undefined, x, y);
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
                    title={t('recent.menu_tooltip')}
                    aria-label={t('recent.menu_tooltip')}
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
                {t('map.recent_empty')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
