import React from 'react';
import { useT } from '../i18n';
import DialogShell from './DialogShell';

export interface WaypointFlyTarget {
  lat: number;
  lng: number;
  index: number;
}

interface WaypointFlyDialogProps {
  // null => closed. The waypoint the user tapped (coord + its list index).
  confirm: WaypointFlyTarget | null;
  // index > 0: rotate the route so this waypoint becomes the start, then fly.
  // The rotation/teleport sim work lives in App's onSetAsStart.
  onSetAsStart: (index: number) => void;
  // index 0 (the start itself): plain teleport — re-align iPhone to the start.
  // The teleport sim work lives in App's onConfirm.
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Waypoint "fly to this coord" confirm dialog (portal). For a non-start
 * waypoint it offers "set as start + fly" (rotates the route); for the start
 * waypoint it falls back to a plain teleport. The sim-driving work stays in
 * App. Controlled: the target waypoint lives in App.
 */
const WaypointFlyDialog: React.FC<WaypointFlyDialogProps> = ({
  confirm,
  onSetAsStart,
  onConfirm,
  onClose,
}) => {
  const t = useT();
  if (!confirm) return null;
  return (
    <DialogShell
      open={confirm != null}
      onClose={onClose}
      labelledBy="wp-fly-title"
      backdropStyle={{ zIndex: 2000 }}
      panelStyle={{
        width: 360, maxWidth: '92vw',
        background: 'rgba(26, 29, 39, 0.96)',
        border: '1px solid rgba(108, 140, 255, 0.25)', borderRadius: 12,
        padding: 22, color: '#e8eaf0',
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65)',
        fontSize: 13,
      }}
    >
      <div id="wp-fly-title" style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
        {t('panel.wp_fly_title')}
      </div>
      <div style={{ fontSize: 12, opacity: 0.8, marginBottom: 6, lineHeight: 1.6 }}>
        {t('panel.wp_fly_hint')}
      </div>
      <div style={{
        fontFamily: 'monospace', fontSize: 13,
        padding: '8px 10px', marginBottom: 4,
        background: 'rgba(10, 12, 18, 0.5)',
        border: '1px solid rgba(108, 140, 255, 0.2)',
        borderRadius: 6,
      }}>
        {confirm.lat.toFixed(6)}, {confirm.lng.toFixed(6)}
      </div>
      <div style={{ fontSize: 11, opacity: 0.55, marginBottom: 16 }}>
        {t('panel.wp_fly_keep_mode')}
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button
          onClick={onClose}
          style={{
            padding: '6px 14px', fontSize: 12, cursor: 'pointer',
            background: 'transparent', color: '#9499ac',
            border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6,
          }}
        >{t('generic.cancel')}</button>
        {confirm.index > 0 ? (
          <button
            onClick={() => onSetAsStart(confirm.index)}
            style={{
              padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: '#6c8cff', color: '#fff',
              border: 'none', borderRadius: 6,
            }}
            title={t('panel.waypoints_set_as_start')}
          >{t('panel.wp_fly_set_as_start')}</button>
        ) : (
          // index 0 IS the start — no rotation possible. Fall back
          // to the plain teleport so clicking the start coord still
          // lets the user re-align the iPhone to it.
          <button
            onClick={onConfirm}
            style={{
              padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: '#6c8cff', color: '#fff',
              border: 'none', borderRadius: 6,
            }}
          >{t('panel.wp_fly_confirm')}</button>
        )}
      </div>
    </DialogShell>
  );
};

export default WaypointFlyDialog;
