import React from 'react';
import { createPortal } from 'react-dom';
import { isSubmitEnter } from '../utils/keyboard';
import { useT } from '../i18n';

// The App-level add-bookmark dialog's controlled state. Distinct from the
// inline BookmarkList AddBookmarkDialog: this one is a portal, carries the
// target lat/lng + the async reverse-geocode pre-fill flags (nameResolving /
// countryCode), and is opened by a map click rather than the library panel.
export interface AppAddBookmarkState {
  lat: number;
  lng: number;
  name: string;
  category: string;
  countryCode?: string;
  nameResolving?: boolean;
}

interface AppAddBookmarkDialogProps {
  // null => closed. Owns lat/lng + the reverse-geocode-driven name / country.
  dialog: AppAddBookmarkState | null;
  // Category names for the picker (parent maps id<->name on submit).
  categories: string[];
  onNameChange: (name: string) => void;
  onCategoryChange: (category: string) => void;
  // Sim-/store-driving submit stays in App; this only fires the callback.
  onSubmit: () => void;
  onClose: () => void;
}

/**
 * App-level add-bookmark dialog rendered into a portal. Pre-fills its name
 * field via the parent's async reverse-geocode (surfaced through the
 * `nameResolving` flag + `countryCode` flag on `dialog`); the actual geocode
 * call + createBookmark live in App. Controlled: name / category live in App.
 */
const AppAddBookmarkDialog: React.FC<AppAddBookmarkDialogProps> = ({
  dialog,
  categories,
  onNameChange,
  onCategoryChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
  if (!dialog) return null;
  return createPortal(
    <div
      onClick={(e) => e.stopPropagation()}
      className="anim-scale-in"
      style={{
        position: 'fixed', top: 60, left: '50%', transform: 'translateX(-50%)',
        zIndex: 1000, background: 'rgba(26, 29, 39, 0.96)',
        backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
        border: '1px solid rgba(108, 140, 255, 0.2)',
        borderRadius: 12, padding: 16, width: 300,
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{t('bm.add')}</div>
      <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 8 }}>
        {dialog.lat.toFixed(5)}, {dialog.lng.toFixed(5)}
      </div>
      <div style={{ position: 'relative', marginBottom: 8 }}>
        <input
          type="text"
          className="search-input"
          placeholder={dialog.nameResolving ? t('bm.name_resolving') : t('bm.name_placeholder')}
          autoFocus
          value={dialog.name}
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (isSubmitEnter(e)) onSubmit();
            if (e.key === 'Escape') onClose();
          }}
          style={{ width: '100%', paddingRight: dialog.nameResolving ? 30 : 8 }}
        />
        {dialog.nameResolving && (
          <span style={{
            position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
            fontSize: 10, color: '#9ac0ff', fontFamily: 'monospace',
            animation: 'pulse 1.2s ease-in-out infinite',
          }}>
            {t('bm.name_resolving_short')}
          </span>
        )}
        {dialog.countryCode && !dialog.nameResolving && (
          <img
            src={`https://flagcdn.com/w20/${dialog.countryCode}.png`}
            alt={dialog.countryCode.toUpperCase()}
            width={16}
            height={12}
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              borderRadius: 2, boxShadow: '0 0 0 1px rgba(255,255,255,0.15)',
            }}
          />
        )}
      </div>
      <select
        value={dialog.category}
        onChange={(e) => onCategoryChange(e.target.value)}
        style={{
          width: '100%', marginBottom: 10, padding: '6px 8px',
          background: '#1e1e22', color: '#e0e0e0', border: '1px solid #444',
          borderRadius: 4, fontSize: 12,
        }}
      >
        {categories.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          className="action-btn primary"
          style={{ flex: 1 }}
          disabled={!dialog.name.trim()}
          onClick={onSubmit}
        >{t('generic.add')}</button>
        <button className="action-btn" onClick={onClose}>{t('generic.cancel')}</button>
      </div>
    </div>,
    document.body,
  );
};

export default AppAddBookmarkDialog;
