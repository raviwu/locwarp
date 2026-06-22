import React from 'react';
import { BookmarkGeoLine } from './BookmarkGeoLine';
import { isSubmitEnter } from '../utils/keyboard';

// Legacy NAME-shape bookmark (category is a plain string). Kept intentionally
// loose so this row stays a dumb leaf that the BookmarkList god-component can
// feed from either of its two list paths.
interface RowBookmark {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  country_code?: string;
  timezone?: string;
  city?: string;
  region?: string;
}

interface BookmarkRowProps {
  bm: RowBookmark;
  isSelected: boolean;
  multiSelect: boolean;
  // Green "just-jumped" flash highlight. The row compares this against bm.id.
  flashedBmId: string | null;
  // Selection toggle (multi-select checkbox + whole-row click in multi mode).
  toggleSelected: (id: string) => void;
  // Single-select left-click handler (pan / teleport — owned by the parent).
  onBookmarkClick: (bm: RowBookmark) => void;
  // Right-click context menu opener (owned by the parent).
  onContextMenu: (e: React.MouseEvent, bm: RowBookmark) => void;

  // --- Variant switches (the two call sites differ only in these) ---------
  // Search list: title includes the category segment. Grouped list: omits it.
  showCategoryInTitle: boolean;
  // The colored category dot rendered before the name (search list only).
  showCategoryDot: boolean;
  // The bookmark-pin SVG glyph rendered before the name (grouped list only).
  showPinIcon: boolean;
  // Inline rename: grouped list only. When false the rename path is dead and
  // editingId/editName/setEditingId/setEditName/onBookmarkEdit are ignored.
  allowRename: boolean;

  // --- Rename state/handlers (only consulted when allowRename) ------------
  editingId?: string | null;
  editName?: string;
  setEditingId?: (id: string | null) => void;
  setEditName?: (name: string) => void;
  onBookmarkEdit?: (id: string, bm: Partial<RowBookmark>) => void;

  // --- Decoration helpers (category dot color + display text) -------------
  resolveColor?: (name: string) => string;
  displayCat?: (name: string) => string;
}

// A single bookmark row. Replaces the two near-identical per-bookmark blocks
// that used to live inline in BookmarkList (the flat search list + the grouped
// list). The two call sites differ ONLY by the variant switches above; every
// other piece of markup (className, styles, hover/click handlers, the flash
// highlight, the BookmarkGeoLine child) is shared verbatim.
export const BookmarkRow: React.FC<BookmarkRowProps> = ({
  bm,
  isSelected,
  multiSelect,
  flashedBmId,
  toggleSelected,
  onBookmarkClick,
  onContextMenu,
  showCategoryInTitle,
  showCategoryDot,
  showPinIcon,
  allowRename,
  editingId,
  editName,
  setEditingId,
  setEditName,
  onBookmarkEdit,
  resolveColor,
  displayCat,
}) => {
  const flashed = !!bm.id && flashedBmId === bm.id;
  const catSegment = showCategoryInTitle
    ? ` · ${displayCat ? displayCat(bm.category) : bm.category}`
    : '';
  const title = `${bm.name}${catSegment} · ${bm.lat.toFixed(5)}, ${bm.lng.toFixed(5)}${bm.region ? ` · ${bm.region}` : ''}`;
  const isEditing = allowRename && editingId === bm.id;

  return (
    <div
      className="bookmark-item"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 6px',
        cursor: 'pointer',
        borderRadius: 4,
        fontSize: 12,
        transition: 'background 0.15s',
        background: flashed
          ? 'rgba(34, 197, 94, 0.22)'
          : (multiSelect && isSelected ? 'rgba(108,140,255,0.18)' : 'transparent'),
      }}
      onClick={() => {
        if (multiSelect) {
          if (bm.id) toggleSelected(bm.id);
        } else {
          onBookmarkClick(bm);
        }
      }}
      onContextMenu={(e) => { if (!multiSelect) onContextMenu(e, bm); else e.preventDefault(); }}
      onMouseEnter={(e) => {
        if (!(multiSelect && isSelected) && !flashed) (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.background = flashed
          ? 'rgba(34, 197, 94, 0.22)'
          : (multiSelect && isSelected ? 'rgba(108,140,255,0.18)' : 'transparent');
      }}
    >
      {multiSelect && (
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => { if (bm.id) toggleSelected(bm.id); }}
          onClick={(e) => e.stopPropagation()}
          style={{ margin: 0, flexShrink: 0 }}
        />
      )}
      {showCategoryDot && (
        <div
          style={{
            width: 8, height: 8, borderRadius: '50%',
            background: resolveColor ? resolveColor(bm.category) : 'transparent', flexShrink: 0,
          }}
          title={displayCat ? displayCat(bm.category) : bm.category}
        />
      )}
      {showPinIcon && (
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          style={{ opacity: 0.5, flexShrink: 0 }}
        >
          <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
        </svg>
      )}
      {isEditing ? (
        <input
          type="text"
          className="search-input"
          value={editName}
          onChange={(e) => setEditName?.(e.target.value)}
          onKeyDown={(e) => {
            if (isSubmitEnter(e) && bm.id) {
              onBookmarkEdit?.(bm.id, { name: editName });
              setEditingId?.(null);
            }
            if (e.key === 'Escape') setEditingId?.(null);
          }}
          onBlur={() => setEditingId?.(null)}
          onClick={(e) => e.stopPropagation()}
          style={{ flex: 1, padding: '2px 4px', fontSize: 11 }}
          autoFocus
        />
      ) : (
        <div
          style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}
          title={title}
        >
          <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {bm.name}
          </span>
          <BookmarkGeoLine countryCode={bm.country_code} city={bm.city} timezone={bm.timezone} />
        </div>
      )}
    </div>
  );
};
