import React from 'react';
import { useT } from '../i18n';
import DialogShell from './DialogShell';

interface CatalogRefreshConfirmDialogProps {
  open: boolean;
  // How many bundled catalog entries are not yet in the local store.
  newCount: number;
  // How many EXISTING catalog-seeded bookmarks have diverged from the bundled
  // value (name/lat/lng/category_id) and would be overwritten by the sync.
  overwriteCount: number;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Informed-consent gate in front of the catalog "Refresh public events"
 * button. The sync (api.syncCatalog) force-overwrites every catalog-seeded
 * bookmark's name/lat/lng/address/category_id and re-stamps updated_at, which
 * silently wins the CRDT merge against a locally-edited copy on the other
 * synced Mac — see backend/services/bookmarks.py::import_catalog. This dialog
 * only adds a confirmation step; it does not change what the sync does.
 * Controlled: open state lives in BookmarkList, counts come from useCatalog.
 */
const CatalogRefreshConfirmDialog: React.FC<CatalogRefreshConfirmDialogProps> = ({
  open,
  newCount,
  overwriteCount,
  onConfirm,
  onClose,
}) => {
  const t = useT();
  return (
    <DialogShell
      open={open}
      onClose={onClose}
      labelledBy="catalog-refresh-confirm-title"
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
      <div id="catalog-refresh-confirm-title" style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
        {t('bm.catalog.confirm_title')}
      </div>
      <div style={{ fontSize: 12, opacity: 0.85, marginBottom: 6, lineHeight: 1.6 }}>
        {t('bm.catalog.confirm_added', { n: newCount })}
      </div>
      {overwriteCount > 0 ? (
        <div style={{
          fontSize: 12, lineHeight: 1.6, marginBottom: 16,
          padding: '8px 10px',
          background: 'rgba(244, 67, 54, 0.1)',
          border: '1px solid rgba(244, 67, 54, 0.3)', borderRadius: 6,
          color: '#ff8a80',
        }}>
          {t('bm.catalog.confirm_overwrite', { n: overwriteCount })}
        </div>
      ) : (
        <div style={{ fontSize: 12, opacity: 0.8, lineHeight: 1.6, marginBottom: 16 }}>
          {t('bm.catalog.confirm_no_overwrite')}
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
          onClick={onConfirm}
          style={{
            padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            background: '#6c8cff', color: '#fff',
            border: 'none', borderRadius: 6,
          }}
        >{t('bm.catalog.confirm_button')}</button>
      </div>
    </DialogShell>
  );
};

export default CatalogRefreshConfirmDialog;
