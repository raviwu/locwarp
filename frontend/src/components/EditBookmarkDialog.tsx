import React from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../i18n';
import { trySplitLatLng } from '../utils/latlng';

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
  // The bookmark being edited (null => dialog closed). Submit merges the edited
  // fields over this so category + address survive the backend PUT.
  bookmark: DialogBookmark | null;
  name: string;
  // lat / lng as raw strings so the single 'lat, lng' field can hold partial
  // input while the user types.
  lat: string;
  lng: string;
  onNameChange: (name: string) => void;
  onLatChange: (lat: string) => void;
  onLngChange: (lng: string) => void;
  // Emits the SAME shape as the inline version: (id, { ...original, name, lat, lng }).
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
  onNameChange,
  onLatChange,
  onLngChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
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
    if (!Number.isFinite(latNum) || latNum < -90 || latNum > 90) return;
    if (!Number.isFinite(lngNum) || lngNum < -180 || lngNum > 180) return;
    // Backend PUT requires the full Bookmark shape, so merge the edits over the
    // original to keep category + address.
    onSubmit(bookmark.id, {
      ...bookmark,
      name: name.trim(),
      lat: latNum,
      lng: lngNum,
    });
    onClose();
  };

  return createPortal(
    <div
      onClick={onClose}
      className="anim-fade-in"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(8, 10, 20, 0.55)',
        backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
        zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        onContextMenu={(e) => e.stopPropagation()}
        className="anim-scale-in"
        style={{
          background: 'rgba(26, 29, 39, 0.96)',
          backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
          border: '1px solid rgba(108, 140, 255, 0.2)',
          borderRadius: 12, padding: 18, width: 320, color: '#e0e0e0',
          boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
          {t('bm.edit')}
        </div>
        <input
          type="text"
          className="search-input"
          placeholder={t('bm.name_placeholder')}
          value={name}
          autoFocus
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose();
          }}
          style={{ width: '100%', marginBottom: 8 }}
        />
        {/* Single 'lat, lng' field — paste or type the whole pair here.
            The trySplitLatLng helper also accepts tab/space separators. */}
        <input
          type="text"
          className="search-input"
          inputMode="decimal"
          placeholder={t('bm.latlng_single_placeholder')}
          value={
            lat && lng
              ? `${lat}, ${lng}`
              : lat || lng
          }
          onChange={(e) => {
            const v = e.target.value;
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
      </div>
    </div>,
    document.body,
  );
};

export default EditBookmarkDialog;
