import React from 'react';
import { useT } from '../i18n';
import DialogShell from './DialogShell';

interface ParseResult {
  valid: Array<{ lat: number; lng: number }>;
  invalidCount: number;
  totalLines: number;
}

interface BulkPasteDialogProps {
  open: boolean;
  text: string;
  category: string;
  categories: string[];
  // True while the parent runs the async createBookmark loop; disables the
  // form + buttons so the user can't double-submit or close mid-write.
  busy: boolean;
  // Pure per-line parser owned by the parent (App.parseBulkPaste). The dialog
  // only reads it to render the valid/invalid stats + gate the submit button;
  // the actual createBookmark loop stays in App's onSubmit.
  parse: (raw: string) => ParseResult;
  onTextChange: (text: string) => void;
  onCategoryChange: (category: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}

/**
 * Bulk-paste bookmarks dialog (portal). A textarea of "lat lng label" lines +
 * a target category; the parent parses each line and runs the createBookmark
 * loop on submit. Controlled: text / category / busy live in App.
 */
const BulkPasteDialog: React.FC<BulkPasteDialogProps> = ({
  open,
  text,
  category,
  categories,
  busy,
  parse,
  onTextChange,
  onCategoryChange,
  onSubmit,
  onClose,
}) => {
  const t = useT();
  if (!open) return null;
  const { valid, invalidCount, totalLines } = parse(text);
  return (
    <DialogShell
      open={open}
      onClose={onClose}
      busy={busy}
      labelledBy="bulk-paste-title"
      backdropStyle={{ zIndex: 2000 }}
      panelStyle={{
        width: 460, maxWidth: '92vw', maxHeight: '86vh',
        display: 'flex', flexDirection: 'column',
        background: 'rgba(26, 29, 39, 0.96)',
        border: '1px solid rgba(108, 140, 255, 0.25)', borderRadius: 12,
        padding: 22, color: '#e8eaf0',
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65)',
        fontSize: 13,
      }}
    >
      <div id="bulk-paste-title" style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
        {t('bm.bulk_paste_title')}
      </div>
      <div style={{ fontSize: 11, opacity: 0.65, marginBottom: 10, whiteSpace: 'pre-line', lineHeight: 1.5 }}>
        {t('bm.bulk_paste_hint')}
      </div>
      <textarea
        value={text}
        onChange={(e) => onTextChange(e.target.value)}
        placeholder="25.0478 121.5319 台北車站&#10;24.1456 120.6839 台中"
        style={{
          width: '100%', boxSizing: 'border-box',
          minHeight: 160, maxHeight: 240, resize: 'vertical',
          background: 'rgba(10, 12, 18, 0.7)',
          border: '1px solid rgba(108, 140, 255, 0.3)',
          borderRadius: 6, color: '#e8eaf0',
          padding: '8px 10px', fontFamily: 'monospace', fontSize: 12, lineHeight: 1.5,
          outline: 'none',
        }}
      />
      <div style={{ fontSize: 11, opacity: 0.7, marginTop: 8 }}>
        {totalLines > 0 && t('bm.bulk_paste_stats')
          .replace('{total}', String(totalLines))
          .replace('{valid}', String(valid.length))
          .replace('{invalid}', String(invalidCount))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
        <span style={{ fontSize: 12, opacity: 0.75 }}>{t('bm.bulk_paste_category')}:</span>
        <select
          value={category}
          onChange={(e) => onCategoryChange(e.target.value)}
          className="search-input"
          style={{ flex: 1, padding: '4px 8px', fontSize: 12 }}
        >
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <button
          onClick={() => { if (!busy) onClose(); }}
          disabled={busy}
          style={{
            padding: '6px 14px', fontSize: 12, cursor: busy ? 'not-allowed' : 'pointer',
            background: 'transparent', color: '#9499ac',
            border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6,
            opacity: busy ? 0.6 : 1,
          }}
        >{t('generic.cancel')}</button>
        <button
          onClick={onSubmit}
          disabled={busy || valid.length === 0}
          style={{
            padding: '6px 14px', fontSize: 12, fontWeight: 600,
            cursor: (busy || valid.length === 0) ? 'not-allowed' : 'pointer',
            background: valid.length === 0 ? 'rgba(108,140,255,0.3)' : '#6c8cff',
            color: '#fff',
            border: 'none', borderRadius: 6,
            opacity: busy ? 0.6 : 1,
          }}
        >
          {busy ? '...' : `${t('bm.bulk_paste_submit')} (${valid.length})`}
        </button>
      </div>
    </DialogShell>
  );
};

export default BulkPasteDialog;
