import React from 'react';
import { useT } from '../i18n';
import { approxCellSizeMeters } from '../services/s2grid';

interface S2LevelPickerProps {
  // Whether the picker is open. The OPEN state (s2PickerOpen) stays LIFTED in
  // MapView — this component renders nothing when closed.
  open: boolean;
  // Close handler — wired to the × button. MapView's setS2PickerOpen(false).
  onClose: () => void;

  // S2 grid state + setters from useS2Grid (FROZEN setter shapes — they take
  // functional updaters in the JSX: setS2Enabled((v) => !v), setS2Level(lv)).
  s2Enabled: boolean;
  setS2Enabled: React.Dispatch<React.SetStateAction<boolean>>;
  s2Level: number;
  setS2Level: React.Dispatch<React.SetStateAction<number>>;
  s2Suppressed: boolean;

  // The map-center latitude, used ONLY for the approxCellSizeMeters size hint.
  // Passed as a plain number so the component stays pure / jsdom-renderable
  // (no Leaflet map dependency). MapView reads it from mapRef.current at render.
  lat: number;
}

// S2 cell grid level picker — opens via right-click on the S2 toggle button OR
// via the small chip beside the legend. Snaps to discrete levels 8..22, default
// 17 (Niantic decor cell). Extracted VERBATIM from MapView's inline JSX (Phase
// 4b, task p4b2bii) — same classNames / markup / inline styles / i18n keys. The
// open state (s2PickerOpen) stays lifted in MapView; this renders when `open`.
export const S2LevelPicker: React.FC<S2LevelPickerProps> = ({
  open,
  onClose,
  s2Enabled,
  setS2Enabled,
  s2Level,
  setS2Level,
  s2Suppressed,
  lat,
}) => {
  const t = useT();
  if (!open) return null;
  return (
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
        <span style={{ fontWeight: 600 }}>{t('map.s2_level_label')}</span>
        <button
          onClick={() => onClose()}
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
          const m = approxCellSizeMeters(s2Level, lat);
          const label = m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
          return t('map.s2_size_hint', { size: label });
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
          {t('map.s2_zoom_in_hint')}
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
        >{s2Enabled ? t('map.s2_on') : t('map.s2_off')}</button>
        <span style={{ fontSize: 10, color: '#666c80' }}>{t('map.s2_picker_hint')}</span>
      </div>
    </div>
  );
};
