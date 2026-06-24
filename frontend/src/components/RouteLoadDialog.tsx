import React from 'react';
import { useT } from '../i18n';
import DialogShell from './DialogShell';

export interface RouteLoadTarget {
  name: string;
  waypoints: { lat: number; lng: number }[];
}

interface RouteLoadDialogProps {
  // null => closed. The route to load (name + waypoints).
  confirm: RouteLoadTarget | null;
  // Emits flyToStart: false => show waypoints only; true => fly to start + show.
  // The teleport / setWaypoints sim work lives in App's onConfirm.
  onConfirm: (flyToStart: boolean) => void;
  onClose: () => void;
}

/**
 * Load-saved-route confirm dialog (portal). Shows the route name + start coord
 * and offers "show only" vs "fly to start + show". The sim-driving work stays
 * in App. Controlled: the target route lives in App.
 */
const RouteLoadDialog: React.FC<RouteLoadDialogProps> = ({
  confirm,
  onConfirm,
  onClose,
}) => {
  const t = useT();
  if (!confirm) return null;
  return (
    <DialogShell
      open={confirm != null}
      onClose={onClose}
      labelledBy="route-load-title"
      backdropStyle={{ zIndex: 2000 }}
      panelStyle={{
        width: 380, maxWidth: '92vw',
        background: 'rgba(26, 29, 39, 0.96)',
        border: '1px solid rgba(108, 140, 255, 0.25)', borderRadius: 12,
        padding: 22, color: '#e8eaf0',
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65)',
        fontSize: 13,
      }}
    >
      <div id="route-load-title" style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
        {t('panel.route_load_title')}
      </div>
      {confirm.name && (
        <div style={{
          fontSize: 13, marginBottom: 8, padding: '6px 10px',
          background: 'rgba(108, 140, 255, 0.1)',
          border: '1px solid rgba(108, 140, 255, 0.2)', borderRadius: 6,
        }}>
          {confirm.name}
        </div>
      )}
      <div style={{ fontSize: 12, opacity: 0.8, marginBottom: 6, lineHeight: 1.6 }}>
        {t('panel.route_load_hint', { n: confirm.waypoints.length })}
      </div>
      {confirm.waypoints.length > 0 && (
        <div style={{
          fontFamily: 'monospace', fontSize: 12,
          padding: '8px 10px', marginBottom: 16,
          background: 'rgba(10, 12, 18, 0.5)',
          border: '1px solid rgba(108, 140, 255, 0.2)', borderRadius: 6,
        }}>
          {t('panel.route_load_start')} {confirm.waypoints[0].lat.toFixed(6)}, {confirm.waypoints[0].lng.toFixed(6)}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button
          onClick={onClose}
          style={{
            padding: '6px 14px', fontSize: 12, cursor: 'pointer',
            background: 'transparent', color: '#9499ac',
            border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6,
          }}
        >{t('generic.cancel')}</button>
        <button
          onClick={() => onConfirm(false)}
          style={{
            padding: '6px 14px', fontSize: 12, cursor: 'pointer',
            background: 'transparent', color: '#e8eaf0',
            border: '1px solid rgba(108, 140, 255, 0.5)', borderRadius: 6,
          }}
        >{t('panel.route_load_show_only')}</button>
        <button
          onClick={() => onConfirm(true)}
          style={{
            padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            background: '#6c8cff', color: '#fff',
            border: 'none', borderRadius: 6,
          }}
        >{t('panel.route_load_fly_start')}</button>
      </div>
    </DialogShell>
  );
};

export default RouteLoadDialog;
