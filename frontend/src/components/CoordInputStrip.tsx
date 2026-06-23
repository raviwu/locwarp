import React, { useEffect, useState } from 'react';
import { useT } from '../i18n';
import { parseCoord } from '../utils/coords';
import { isSubmitEnter } from '../utils/keyboard';

interface CoordInputStripProps {
  // Gates the teleport / navigate buttons (a disconnected device can't move).
  // The preview button stays enabled regardless (camera-only fly). Defaults to
  // true to mirror MapView's deviceConnected default.
  deviceConnected?: boolean;

  // Real teleport / navigate — both forward the 'coord' source so App can tag
  // the recent-history entry. MapView passes its own onTeleport / onNavigate
  // props straight through. After a successful submit the input is cleared.
  onTeleport: (lat: number, lng: number, source?: 'menu' | 'coord') => void;
  onNavigate: (lat: number, lng: number, source?: 'menu' | 'coord') => void;
  // Preview-only fly. MapView wraps its (onCoordPreview ?? mapRef.setView)
  // fallback into this single callback so this component stays Leaflet-free.
  // The input is intentionally NOT cleared after a preview so the user can
  // promote it to a real teleport / navigate.
  onPreview: (lat: number, lng: number) => void;

  // Toast surface — used for the invalid-coord and clipboard-denied messages.
  // Optional to mirror MapView's onShowToast prop.
  onShowToast?: (msg: string) => void;

  // Reports the measured `.status-bar` height back to MapView. The strip owns
  // the ResizeObserver (it observes the bottom status bar so the whole bottom-
  // left stack can sit exactly above it), but the wrapping flex column lives in
  // MapView (it also holds the bulk-paste + transport rows), so MapView consumes
  // the height to set the column's `bottom` offset. Called on mount, on
  // status-bar resize, and on window resize. Optional for jsdom tests that
  // don't care about the offset.
  onStatusBarHeight?: (height: number) => void;
}

// Coordinate-input overlay (replaces the sidebar's two-field coord input).
// parseCoord scrapes the first valid lat/lng out of arbitrary pasted text —
// bracket decoration, trailing notes ("一般火"), and label prefixes are all
// discarded so users don't have to hand-clean copies from Google Maps / chat /
// spreadsheets. Extracted VERBATIM from MapView's inline JSX (Phase 4b, task
// p4b2bii) — same classNames / markup / inline styles / i18n keys. Owns the
// coordInput state + the status-bar-height ResizeObserver. The strip is the
// last row of MapView's bottom-left flex column; the observer lives here and
// reports the measured status-bar height up via onStatusBarHeight so MapView
// can offset that column above the bottom status bar.
export const CoordInputStrip: React.FC<CoordInputStripProps> = ({
  deviceConnected = true,
  onTeleport,
  onNavigate,
  onPreview,
  onShowToast,
  onStatusBarHeight,
}) => {
  const t = useT();
  const [coordInput, setCoordInput] = useState('');

  // Lifts the bottom-left stack to clear the bottom status bar. The status bar
  // wraps to extra rows when the window narrows (flexWrap), so its rendered
  // height varies. We observe it directly so the stack sits exactly above
  // whatever height it ends up. The measured height is reported up to MapView
  // (which owns the wrapping flex column) via onStatusBarHeight.
  useEffect(() => {
    const el = document.querySelector('.status-bar') as HTMLElement | null;
    if (!el) return;
    const update = () => onStatusBarHeight?.(Math.ceil(el.getBoundingClientRect().height));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener('resize', update);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', update);
    };
    // onStatusBarHeight is a stable App-level callback; mirror the original
    // empty-dep, mount-once effect so we don't re-observe on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitCoordGo = (kind: 'teleport' | 'navigate' = 'teleport') => {
    const parsed = parseCoord(coordInput);
    if (!parsed) {
      if (onShowToast) onShowToast(t('panel.coord_invalid'));
      return;
    }
    if (kind === 'navigate') onNavigate(parsed.lat, parsed.lng, 'coord');
    else onTeleport(parsed.lat, parsed.lng, 'coord');
    setCoordInput('');
  };
  // Preview-only: pan the map view to the parsed coordinate without touching
  // the iPhone GPS. Lets the user "peek" at a coordinate before deciding to
  // teleport. Keeps the input populated so the next click can promote it to a
  // real teleport / navigate.
  const submitCoordPreview = () => {
    const parsed = parseCoord(coordInput);
    if (!parsed) {
      if (onShowToast) onShowToast(t('panel.coord_invalid'));
      return;
    }
    onPreview(parsed.lat, parsed.lng);
  };

  return (
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
        placeholder={t('panel.coord_placeholder')}
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
            if (onShowToast) onShowToast(t('panel.paste_denied'));
          }
        }}
        title={t('panel.paste_tooltip')}
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
        {t('panel.paste')}
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
      >{t('panel.coord_teleport')}</button>
      <button
        onClick={submitCoordPreview}
        disabled={!coordInput.trim()}
        title={t('panel.coord_preview_tooltip')}
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
        {t('panel.coord_preview')}
      </button>
      <button
        onClick={() => submitCoordGo('navigate')}
        disabled={!coordInput.trim() || !deviceConnected}
        title={t('panel.coord_navigate_tooltip')}
        style={{
          background: 'transparent',
          color: !coordInput.trim() || !deviceConnected ? 'rgba(76, 175, 80, 0.4)' : '#4caf50',
          border: `1px solid ${!coordInput.trim() || !deviceConnected ? 'rgba(76, 175, 80, 0.3)' : 'rgba(76, 175, 80, 0.55)'}`,
          borderRadius: 4,
          padding: '4px 10px', fontSize: 11, fontWeight: 600,
          cursor: !coordInput.trim() || !deviceConnected ? 'not-allowed' : 'pointer',
        }}
      >{t('panel.coord_navigate')}</button>
    </div>
  );
};
