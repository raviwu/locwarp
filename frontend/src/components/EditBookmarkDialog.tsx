import React from 'react';
import { useT } from '../i18n';
import { trySplitLatLng } from '../utils/latlng';
import { useRawCoordText } from '../hooks/useRawCoordText';
import DialogShell from './DialogShell';

// Legacy NAME-shape bookmark (category is a plain string). Kept loose to match
// the shape BookmarkList passes through.
interface DialogBookmark {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  country_code?: string;
  timezone?: string;
  city?: string;
  region?: string;
  created_at?: string;
  last_used_at?: string;
}

interface EditBookmarkDialogProps {
  // The bookmark being edited (null => dialog closed). This is the LIVE
  // record — the parent re-derives it from its bookmarks list on every
  // render, it is never a snapshot frozen at open time. Only its `id` reaches
  // the submitted patch; every other field is either typed by the user in
  // this session or left off the wire entirely, so nothing here can revert a
  // concurrent edit (e.g. a rename synced in from another machine).
  bookmark: DialogBookmark | null;
  name: string;
  // lat / lng as raw strings so the single 'lat, lng' field can hold partial
  // input while the user types.
  lat: string;
  lng: string;
  // Per-field dirty flags: true once the user has changed that field in this
  // dialog session. Drives which value wins at submit time — see handleSubmit.
  nameDirty: boolean;
  latDirty: boolean;
  lngDirty: boolean;
  onNameChange: (name: string) => void;
  onLatChange: (lat: string) => void;
  onLngChange: (lng: string) => void;
  // Sparse by design: (id, { id, ...only the fields this session changed }).
  onSubmit: (id: string, patch: Partial<DialogBookmark>) => void;
  onClose: () => void;
}

/**
 * Full edit dialog (name + lat + lng) rendered into a portal. Triggered by the
 * context-menu "Edit". Controlled: bookmark / name / lat / lng live in
 * BookmarkList. The single 'lat, lng' field accepts a pasted pair via
 * trySplitLatLng; partial input keeps raw text in lat and clears lng.
 */
const EditBookmarkDialog: React.FC<EditBookmarkDialogProps> = ({
  bookmark,
  name,
  lat,
  lng,
  nameDirty,
  latDirty,
  lngDirty,
  onNameChange,
  onLatChange,
  onLngChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
  // The field shows the user's raw text — never a re-derived `${lat}, ${lng}`,
  // which moves the caret and lets a Backspace eat a longitude digit.
  const coordText = useRawCoordText(lat, lng);
  if (!bookmark) return null;

  const latNum = parseFloat(lat);
  const lngNum = parseFloat(lng);
  const latOutOfRange = Number.isFinite(latNum) && (latNum < -90 || latNum > 90);
  const lngOutOfRange = Number.isFinite(lngNum) && (lngNum < -180 || lngNum > 180);
  const outOfRange = latOutOfRange || lngOutOfRange;

  const handleSubmit = () => {
    const latNum = parseFloat(lat);
    const lngNum = parseFloat(lng);
    if (!bookmark.id) { onClose(); return; }
    if (latDirty && (!Number.isFinite(latNum) || latNum < -90 || latNum > 90)) return;
    if (lngDirty && (!Number.isFinite(lngNum) || lngNum < -180 || lngNum > 180)) return;
    // Only the fields the user actually changed in this session go on the
    // wire. The backend PUT is a partial update, so a field this patch omits
    // is left exactly as stored — which is strictly stronger than re-sending
    // the live record's value: an absent key cannot lose a race against a
    // concurrent edit (e.g. one synced in from the other Mac) at all.
    const patch: Partial<DialogBookmark> = { id: bookmark.id };
    if (nameDirty) patch.name = name.trim();
    if (latDirty) patch.lat = latNum;
    if (lngDirty) patch.lng = lngNum;
    onSubmit(bookmark.id, patch);
    onClose();
  };

  return (
    <DialogShell
      open={bookmark != null}
      onClose={onClose}
      labelledBy="edit-bm-title"
      backdropClassName="anim-fade-in"
      panelClassName="anim-scale-in"
      panelStyle={{
        background: 'rgba(26, 29, 39, 0.96)',
        backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
        border: '1px solid rgba(108, 140, 255, 0.2)',
        borderRadius: 12, padding: 18, width: 320, color: '#e0e0e0',
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
      }}
      panelProps={{ onContextMenu: (e) => e.stopPropagation() }}
    >
      <div id="edit-bm-title" style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
        {t('bm.edit')}
      </div>
      <input
        type="text"
        className="search-input"
        placeholder={t('bm.name_placeholder')}
        value={name}
        autoFocus
        onChange={(e) => onNameChange(e.target.value)}
        style={{ width: '100%', marginBottom: 8 }}
      />
      {/* Single 'lat, lng' field — paste or type the whole pair here.
          The trySplitLatLng helper also accepts tab/space separators. */}
      <input
        type="text"
        className="search-input"
        inputMode="decimal"
        placeholder={t('bm.latlng_single_placeholder')}
        value={coordText.value}
        onChange={(e) => {
          const v = e.target.value;
          coordText.setRaw(v);
          const split = trySplitLatLng(v);
          if (split) { onLatChange(split[0]); onLngChange(split[1]); }
          else {
            // User is still typing the lat part; keep raw text in lat
            // and clear lng until a valid pair is detected.
            onLatChange(v);
            onLngChange('');
          }
        }}
        style={{ width: '100%', marginBottom: 12 }}
      />
      {outOfRange && (
        <div style={{ fontSize: 11, color: '#f44336', marginBottom: 8 }}>
          {t('bm.latlng_out_of_range')}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          className="action-btn primary"
          style={{ flex: 1 }}
          disabled={
            !name.trim() ||
            !Number.isFinite(parseFloat(lat)) ||
            !Number.isFinite(parseFloat(lng))
          }
          onClick={handleSubmit}
        >{t('generic.save')}</button>
        <button className="action-btn" onClick={onClose}>
          {t('generic.cancel')}
        </button>
      </div>
    </DialogShell>
  );
};

export default EditBookmarkDialog;
