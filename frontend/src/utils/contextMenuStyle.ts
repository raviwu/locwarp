import type React from 'react';

// Shared context-menu item style + hover helpers. Lifted byte-for-byte out of
// MapView's (and WaypointMenu's local copy of) the module-level `contextMenuItemStyle`
// / `highlightItem` / `unhighlightItem` so the duplicated definitions become a
// single source of truth. The markup that consumes these stays identical.
export const contextMenuItemStyle: React.CSSProperties = {
  padding: '8px 16px',
  cursor: 'pointer',
  color: '#e0e0e0',
  fontSize: 13,
  display: 'flex',
  alignItems: 'center',
  transition: 'background 0.15s',
};

export function highlightItem(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}

export function unhighlightItem(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}
