import React from 'react';
import { useT } from '../i18n';
import {
  contextMenuItemStyle,
  highlightItem,
  unhighlightItem,
} from '../utils/contextMenuStyle';

interface WaypointMenuProps {
  // Whether the menu is shown. The wpMenu state (visible/x/y/index/isStart)
  // stays LIFTED in MapView — this component renders nothing when not visible.
  visible: boolean;
  // Viewport coordinates of the originating click (used to position the menu).
  x: number;
  y: number;
  // The waypoint's index, shown in the header (#index) and passed to actions.
  index: number;
  // Whether this waypoint is the route start (gates the set-as-start action
  // off and flips the header label to the localized "start" string).
  isStart: boolean;

  // Action callbacks — each is OPTIONAL: when omitted, the corresponding menu
  // item is gated out (mirrors the original inline JSX which gated on the
  // handler-mirror ref being truthy). MapView passes thin closures over the
  // wire-once handler-mirror refs so freshness is preserved.
  onSetAsStart?: (index: number) => void;
  onInsertAfter?: (index: number) => void;
  onRemove?: (index: number) => void;
  // Dismissal — wired to MapView's closeWpMenu. Each action also closes the
  // menu before firing (handled by the MapView closures), matching the
  // original close-then-fire ordering.
  onClose: () => void;
}

// Per-waypoint mini context menu (set-as-start / insert-after / delete) opened
// by left-clicking a waypoint marker. Independent from the right-click context
// menu so opening one does not close / reposition the other. Extracted VERBATIM
// from MapView's inline JSX (Phase 4b, task p4b2bii) — same classNames / markup
// / inline styles / i18n keys / per-action index+isStart gating. The wpMenu
// state stays lifted in MapView; this renders when `visible`.
export const WaypointMenu: React.FC<WaypointMenuProps> = ({
  visible,
  x,
  y,
  index,
  isStart,
  onSetAsStart,
  onInsertAfter,
  onRemove,
  onClose,
}) => {
  const t = useT();
  if (!visible) return null;
  return (
    <div
      className="context-menu anim-scale-in-tl"
      style={{
        position: 'fixed',
        // Offset slightly so the cursor lands inside the menu rather
        // than on its edge (otherwise the document-level click handler
        // might immediately close it).
        left: Math.max(8, Math.min(x + 6, window.innerWidth - 188)),
        top: Math.max(8, Math.min(y + 6, window.innerHeight - 100)),
        zIndex: 1000,
        background: 'rgba(26, 29, 39, 0.96)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        border: '1px solid rgba(108, 140, 255, 0.18)',
        borderRadius: 10,
        padding: '4px 0',
        boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.04) inset',
        minWidth: 180,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        style={{
          padding: '6px 14px 4px',
          fontSize: 11,
          opacity: 0.55,
          fontFamily: 'monospace',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          marginBottom: 2,
        }}
      >
        {isStart ? t('panel.waypoint_start') : `#${index}`}
      </div>
      {!isStart && onSetAsStart && (
        <div
          style={contextMenuItemStyle}
          onMouseEnter={highlightItem}
          onMouseLeave={unhighlightItem}
          onClick={() => {
            onClose();
            onSetAsStart(index);
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#43a047" strokeWidth="2" style={{ marginRight: 8 }}>
            <line x1="4" y1="22" x2="4" y2="3" />
            <path d="M4 4h12l-2 4 2 4H4" fill="#43a04733" />
          </svg>
          {t('map.wp_set_as_start')}
        </div>
      )}
      {onInsertAfter && (
        <div
          style={contextMenuItemStyle}
          onMouseEnter={highlightItem}
          onMouseLeave={unhighlightItem}
          onClick={() => {
            onClose();
            onInsertAfter(index);
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6c8cff" strokeWidth="2" style={{ marginRight: 8 }}>
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          {t('map.wp_insert_after')}
        </div>
      )}
      {onRemove && (
        <div
          style={{ ...contextMenuItemStyle, color: '#ff6b6b' }}
          onMouseEnter={highlightItem}
          onMouseLeave={unhighlightItem}
          onClick={() => {
            onClose();
            onRemove(index);
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
          </svg>
          {t('map.wp_delete')}
        </div>
      )}
    </div>
  );
};
