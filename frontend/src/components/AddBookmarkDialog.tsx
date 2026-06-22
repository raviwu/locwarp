import React from 'react';
import { isSubmitEnter } from '../utils/keyboard';
import { useT } from '../i18n';

interface AddBookmarkDialogProps {
  // Controlled by the parent. When false, nothing renders.
  open: boolean;
  name: string;
  category: string;
  categories: string[];
  // True when the current GPS position is known; gates the Save action and
  // shows the "no position" hint when absent.
  hasPosition: boolean;
  // Translate a category name for display (i18n-coupled, owned by the parent).
  displayCat: (name: string) => string;
  onNameChange: (name: string) => void;
  onCategoryChange: (category: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}

/**
 * Inline add-bookmark dialog (drops into the library panel flow, not a portal).
 * Controlled: open / name / category live in BookmarkList; this component only
 * renders + emits change/submit/close.
 */
const AddBookmarkDialog: React.FC<AddBookmarkDialogProps> = ({
  open,
  name,
  category,
  categories,
  hasPosition,
  displayCat,
  onNameChange,
  onCategoryChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
  if (!open) return null;
  return (
    <div
      style={{
        background: '#2a2a2e',
        border: '1px solid #444',
        borderRadius: 6,
        padding: 12,
        marginBottom: 8,
      }}
    >
      <input
        type="text"
        className="search-input"
        placeholder={t('bm.name_placeholder')}
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
        onKeyDown={(e) => isSubmitEnter(e) && onSubmit()}
        style={{ width: '100%', marginBottom: 8 }}
        autoFocus
      />
      <select
        value={category}
        onChange={(e) => onCategoryChange(e.target.value)}
        style={{
          width: '100%',
          marginBottom: 8,
          padding: '6px 8px',
          background: '#1e1e22',
          color: '#e0e0e0',
          border: '1px solid #444',
          borderRadius: 4,
          fontSize: 12,
        }}
      >
        {categories.map((cat) => (
          <option key={cat} value={cat}>
            {displayCat(cat)}
          </option>
        ))}
      </select>
      <div style={{ display: 'flex', gap: 6 }}>
        <button className="action-btn primary" onClick={onSubmit} style={{ flex: 1, fontSize: 12 }}>
          {t('generic.save')}
        </button>
        <button className="action-btn" onClick={onClose} style={{ fontSize: 12 }}>
          {t('generic.cancel')}
        </button>
      </div>
      {!hasPosition && (
        <div style={{ fontSize: 11, color: '#f44336', marginTop: 6 }}>
          {t('bm.no_position')}
        </div>
      )}
    </div>
  );
};

export default AddBookmarkDialog;
