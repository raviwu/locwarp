import React from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../i18n';
import { COLOR_PALETTE } from '../utils/categoryColor';

interface CategoryEditPatch {
  name: string;
  color: string;
  start_date: string;
  end_date: string;
}

interface EditCategoryModalProps {
  // The original category name being edited (null => modal closed). Passed back
  // to onSubmit unchanged so the parent knows which category to patch.
  categoryName: string | null;
  newName: string;
  color: string;
  startDate: string;
  endDate: string;
  onNewNameChange: (name: string) => void;
  onColorChange: (color: string) => void;
  onStartDateChange: (date: string) => void;
  onEndDateChange: (date: string) => void;
  // Emits (originalName, patch) — same shape as onCategoryEdit. Only fires when
  // the entry is valid (non-empty name, start <= end when both set).
  onSubmit: (originalName: string, patch: CategoryEditPatch) => void;
  onClose: () => void;
}

/**
 * Edit-category modal rendered into a portal. Color palette + custom color
 * picker + event start/end date pickers. Controlled: name / color / dates live
 * in BookmarkList.
 */
const EditCategoryModal: React.FC<EditCategoryModalProps> = ({
  categoryName,
  newName,
  color,
  startDate,
  endDate,
  onNewNameChange,
  onColorChange,
  onStartDateChange,
  onEndDateChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
  if (categoryName === null) return null;

  const datesInvalid = !!startDate && !!endDate && startDate > endDate;

  const handleSubmit = () => {
    const next = newName.trim();
    if (!next) return;
    if (datesInvalid) return;
    onSubmit(categoryName, {
      name: next,
      color,
      start_date: startDate,
      end_date: endDate,
    });
    onClose();
  };

  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(8,10,20,0.55)',
        backdropFilter: 'blur(4px)',
        WebkitBackdropFilter: 'blur(4px)',
        zIndex: 10000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'rgba(26,29,39,0.96)',
          border: '1px solid rgba(108,140,255,0.35)',
          borderRadius: 12, padding: 18, width: 340,
          boxShadow: '0 20px 60px rgba(12,18,40,0.65)',
          color: '#e0e0e0',
          display: 'flex', flexDirection: 'column', gap: 10,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600 }}>{t('bm.cat.edit_title')}</div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.name')}</span>
          <input
            className="search-input"
            value={newName}
            onChange={(e) => onNewNameChange(e.target.value)}
            style={{ padding: '4px 6px' }}
          />
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.color')}</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 28px)', gap: 6 }}>
            {COLOR_PALETTE.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => onColorChange(c)}
                style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: c,
                  border: color.toLowerCase() === c.toLowerCase()
                    ? '2px solid #fff'
                    : '1.5px solid rgba(255,255,255,0.12)',
                  cursor: 'pointer', padding: 0,
                }}
                title={c}
              />
            ))}
          </div>
          <input
            type="color"
            value={color}
            onChange={(e) => onColorChange(e.target.value)}
            title={t('bm.recolor_custom')}
            style={{ width: '100%', height: 28, border: 'none', borderRadius: 4, padding: 0, marginTop: 4 }}
          />
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.starts')}</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="date"
              value={startDate}
              onChange={(e) => onStartDateChange(e.target.value)}
              style={{ flex: 1, padding: '4px 6px', background: '#1e1e22', color: '#e0e0e0', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4 }}
            />
            <button
              className="action-btn"
              onClick={() => onStartDateChange('')}
              disabled={!startDate}
              style={{ fontSize: 11, padding: '3px 8px', opacity: startDate ? 1 : 0.4 }}
            >
              ✕ {t('bm.cat.dates_clear')}
            </button>
          </div>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.ends')}</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="date"
              value={endDate}
              onChange={(e) => onEndDateChange(e.target.value)}
              style={{ flex: 1, padding: '4px 6px', background: '#1e1e22', color: '#e0e0e0', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4 }}
            />
            <button
              className="action-btn"
              onClick={() => onEndDateChange('')}
              disabled={!endDate}
              style={{ fontSize: 11, padding: '3px 8px', opacity: endDate ? 1 : 0.4 }}
            >
              ✕ {t('bm.cat.dates_clear')}
            </button>
          </div>
        </label>

        <div style={{ fontSize: 10, opacity: 0.55 }}>{t('bm.cat.dates_hint')}</div>
        {datesInvalid && (
          <div style={{ fontSize: 11, color: '#f87171' }}>{t('bm.cat.dates_invalid')}</div>
        )}

        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 4 }}>
          <button className="action-btn" onClick={onClose} style={{ fontSize: 11 }}>
            {t('generic.cancel')}
          </button>
          <button
            className="action-btn"
            disabled={!newName.trim() || datesInvalid}
            onClick={handleSubmit}
            style={{ fontSize: 11 }}
          >
            {t('bm.cat.save')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
};

export default EditCategoryModal;
