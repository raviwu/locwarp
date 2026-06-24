import React from 'react';
import { createPortal } from 'react-dom';
import { isSubmitEnter } from '../utils/keyboard';
import { useT } from '../i18n';
import { trySplitLatLng } from '../utils/latlng';

interface NewBookmark {
  name: string;
  lat: number;
  lng: number;
  category: string;
}

interface CustomBookmarkDialogProps {
  // Controlled by the parent. When false, nothing renders.
  open: boolean;
  name: string;
  // lat / lng as raw strings so the single 'lat, lng' field can hold partial
  // input while the user types.
  lat: string;
  lng: string;
  category: string;
  categories: string[];
  // Translate a category name for display (i18n-coupled, owned by the parent).
  displayCat: (name: string) => string;
  onNameChange: (name: string) => void;
  onLatChange: (lat: string) => void;
  onLngChange: (lng: string) => void;
  onCategoryChange: (category: string) => void;
  // Emits a validated, parsed bookmark (same shape as the inline version's
  // onBookmarkAdd call). The parent owns the post-submit field reset + close.
  onSubmit: (bm: NewBookmark) => void;
  onClose: () => void;
}

/**
 * Custom add-bookmark dialog rendered into a portal. Controlled: open / name /
 * lat / lng / category live in BookmarkList. The single 'lat, lng' field accepts
 * a pasted pair via trySplitLatLng. Validation (finite + in-range) runs here and
 * onSubmit only fires for a valid entry.
 */
const CustomBookmarkDialog: React.FC<CustomBookmarkDialogProps> = ({
  open,
  name,
  lat,
  lng,
  category,
  categories,
  displayCat,
  onNameChange,
  onLatChange,
  onLngChange,
  onCategoryChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
  if (!open) return null;

  const latNum = parseFloat(lat);
  const lngNum = parseFloat(lng);
  const latOutOfRange = Number.isFinite(latNum) && (latNum < -90 || latNum > 90);
  const lngOutOfRange = Number.isFinite(lngNum) && (lngNum < -180 || lngNum > 180);
  const outOfRange = latOutOfRange || lngOutOfRange;

  const handleSubmit = () => {
    const trimmed = name.trim();
    const latNum = parseFloat(lat);
    const lngNum = parseFloat(lng);
    if (!trimmed) return;
    if (!Number.isFinite(latNum) || latNum < -90 || latNum > 90) return;
    if (!Number.isFinite(lngNum) || lngNum < -180 || lngNum > 180) return;
    onSubmit({ name: trimmed, lat: latNum, lng: lngNum, category });
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
          {t('bm.add_custom')}
        </div>
        <input
          type="text"
          className="search-input"
          placeholder={t('bm.name_placeholder')}
          value={name}
          autoFocus
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (isSubmitEnter(e)) handleSubmit();
            if (e.key === 'Escape') onClose();
          }}
          style={{ width: '100%', marginBottom: 8 }}
        />
        {/* Single 'lat, lng' field. Paste or type the whole pair. */}
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
            else { onLatChange(v); onLngChange(''); }
          }}
          style={{ width: '100%', marginBottom: 8 }}
        />
        <select
          value={category}
          onChange={(e) => onCategoryChange(e.target.value)}
          style={{
            width: '100%', marginBottom: 12, padding: '6px 8px',
            background: '#1e1e22', color: '#e0e0e0', border: '1px solid #444',
            borderRadius: 4, fontSize: 12,
          }}
        >
          {categories.map((c) => (
            <option key={c} value={c}>{displayCat(c)}</option>
          ))}
        </select>
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
          >{t('generic.add')}</button>
          <button className="action-btn" onClick={onClose}>
            {t('generic.cancel')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
};

export default CustomBookmarkDialog;
