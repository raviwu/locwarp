import React from 'react';
import { useT } from '../i18n';
import DialogShell from './DialogShell';

interface ParseResult {
  valid: Array<{ lat: number; lng: number }>;
  invalidCount: number;
  totalLines: number;
}

interface RoutePasteDialogProps {
  open: boolean;
  text: string;
  // Pure per-line parser owned by the parent (App.parseRoutePaste). The dialog
  // only reads it to render stats + gate submit; the teleport / setWaypoints
  // work stays in App's onSubmit.
  parse: (raw: string) => ParseResult;
  onTextChange: (text: string) => void;
  onSubmit: () => void;
  onClose: () => void;
  // Fired when navigator.clipboard.readText() throws (permissions / no
  // clipboard) so the parent can surface its toast.
  onClipboardBlocked: () => void;
}

/**
 * Bulk-paste route coordinates dialog (portal). A textarea of "lat lng" lines
 * (first = route start) + a "paste from clipboard" shortcut; the parent parses
 * each line and runs the teleport + setWaypoints work on submit. Controlled:
 * text lives in App.
 */
const RoutePasteDialog: React.FC<RoutePasteDialogProps> = ({
  open,
  text,
  parse,
  onTextChange,
  onSubmit,
  onClose,
  onClipboardBlocked,
}) => {
  const t = useT();
  if (!open) return null;
  const { valid, invalidCount, totalLines } = parse(text);
  return (
    <DialogShell
      open={open}
      onClose={onClose}
      labelledBy="route-paste-title"
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
      <div id="route-paste-title" style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
        {t('panel.route_paste_title')}
      </div>
      <div style={{ fontSize: 11, opacity: 0.65, marginBottom: 10, whiteSpace: 'pre-line', lineHeight: 1.5 }}>
        {t('panel.route_paste_hint')}
      </div>
      <textarea
        value={text}
        onChange={(e) => onTextChange(e.target.value)}
        placeholder="25.0478 121.5319&#10;25.0500 121.5400&#10;25.0530 121.5500"
        style={{
          width: '100%', boxSizing: 'border-box',
          minHeight: 180, maxHeight: 280, resize: 'vertical',
          background: 'rgba(10, 12, 18, 0.7)',
          border: '1px solid rgba(108, 140, 255, 0.3)',
          borderRadius: 6, color: '#e8eaf0',
          padding: '8px 10px', fontFamily: 'monospace', fontSize: 12, lineHeight: 1.5,
          outline: 'none',
        }}
      />
      <div style={{ fontSize: 11, opacity: 0.7, marginTop: 8 }}>
        {totalLines > 0 && t('panel.route_paste_stats')
          .replace('{total}', String(totalLines))
          .replace('{valid}', String(valid.length))
          .replace('{invalid}', String(invalidCount))}
      </div>
      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
        {t('panel.route_paste_start_hint')}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'space-between', alignItems: 'center' }}>
        <button
          onClick={async () => {
            try {
              const clip = await navigator.clipboard.readText();
              if (clip) onTextChange(clip);
            } catch {
              onClipboardBlocked();
            }
          }}
          title={t('panel.route_paste_from_clipboard_tooltip')}
          style={{
            padding: '6px 12px', fontSize: 12, cursor: 'pointer',
            background: 'rgba(108, 140, 255, 0.18)', color: '#9bb0ff',
            border: '1px solid rgba(108, 140, 255, 0.4)', borderRadius: 6,
            display: 'inline-flex', alignItems: 'center', gap: 5,
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="9" y="2" width="6" height="4" rx="1"/>
            <path d="M9 4H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-3"/>
            <path d="M9 12h6M9 16h4"/>
          </svg>
          {t('panel.route_paste_from_clipboard')}
        </button>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px', fontSize: 12, cursor: 'pointer',
              background: 'transparent', color: '#9499ac',
              border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6,
            }}
          >{t('generic.cancel')}</button>
          <button
            onClick={onSubmit}
            disabled={valid.length === 0}
            style={{
              padding: '6px 14px', fontSize: 12, fontWeight: 600,
              cursor: valid.length === 0 ? 'not-allowed' : 'pointer',
              background: valid.length === 0 ? 'rgba(108,140,255,0.3)' : '#6c8cff',
              color: '#fff',
              border: 'none', borderRadius: 6,
            }}
          >{`${t('panel.route_paste_submit')} (${valid.length})`}</button>
        </div>
      </div>
    </DialogShell>
  );
};

export default RoutePasteDialog;
