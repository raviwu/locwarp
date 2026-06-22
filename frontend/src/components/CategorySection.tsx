import React from 'react';
import { BookmarkRow } from './BookmarkRow';
import { useT } from '../i18n';
import { sortBookmarks, type SortMode } from '../utils/bookmarkSort';
import {
  formatChipDate,
  type CategoryStatus,
} from '../utils/categoryStatus';

// NAME-shape bookmark (category is a plain string). Kept loose to match the
// BookmarkList god-component's grouped feed and the dumb-leaf BookmarkRow.
interface SectionBookmark {
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

interface CategorySectionProps {
  // Raw category name (storage key) — used for callbacks and selection math.
  cat: string;
  // Bookmarks belonging to this category (already filtered by the parent).
  bms: SectionBookmark[];
  // Collapse state for this category.
  collapsed: boolean;
  // Resolved category dot color.
  color: string;
  // Temporal status — drives the ended/upcoming badge.
  status: CategoryStatus;
  // Event dates for this category, when present — feeds the "upcoming" chip.
  dates?: { start_date: string; end_date: string };
  // Locale for the "Starts {date}" chip.
  chipLocale: string;
  // Sort applied to the rows inside the expanded body.
  sortMode: SortMode;

  // Display-name mapper (translates the built-in default category).
  displayCat: (name: string) => string;

  // --- Multi-select (tri-state header checkbox) ----------------------------
  multiSelect: boolean;
  // Current global selection set — the tri-state math is derived from this.
  selectedIds: Set<string>;
  // Toggle select-all for this category's ids (caller mutates selectedIds).
  onToggleSelectAll: (catIds: string[], allSelected: boolean) => void;

  // --- Header callbacks ----------------------------------------------------
  onToggleCollapse: (cat: string) => void;
  onHide: (cat: string) => void;

  // --- Row props (forwarded verbatim to each BookmarkRow) ------------------
  flashedBmId: string | null;
  toggleSelected: (id: string) => void;
  onBookmarkClick: (bm: SectionBookmark) => void;
  onContextMenu: (e: React.MouseEvent, bm: SectionBookmark) => void;
  editingId: string | null;
  editName: string;
  setEditingId: (id: string | null) => void;
  setEditName: (name: string) => void;
  onBookmarkEdit: (id: string, bm: Partial<SectionBookmark>) => void;
}

// One per-category group block of the GROUPED bookmark list: the chevron/color/
// name/status-badge/count/hide header (plus the multi-select tri-state header
// checkbox) wrapping the collapsed body of <BookmarkRow>s. Extracted verbatim
// from BookmarkList's grouped IIFE — no behavior change.
export const CategorySection: React.FC<CategorySectionProps> = ({
  cat,
  bms,
  collapsed,
  color,
  status,
  dates,
  chipLocale,
  sortMode,
  displayCat,
  multiSelect,
  selectedIds,
  onToggleSelectAll,
  onToggleCollapse,
  onHide,
  flashedBmId,
  toggleSelected,
  onBookmarkClick,
  onContextMenu,
  editingId,
  editName,
  setEditingId,
  setEditName,
  onBookmarkEdit,
}) => {
  const t = useT();
  const catIds = bms.map((b) => b.id).filter((x): x is string => !!x);
  const selectedInCat = catIds.filter((id) => selectedIds.has(id)).length;
  const allSelectedInCat = catIds.length > 0 && selectedInCat === catIds.length;
  const someSelectedInCat = selectedInCat > 0 && !allSelectedInCat;
  const _d = dates;
  const headerOpacity =
    status === 'ended' ? 0.5 : status === 'upcoming' ? 0.7 : 1;

  return (
    <div className="bookmark-group" style={{ marginBottom: 4, opacity: headerOpacity }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 4px',
          cursor: 'pointer',
          fontSize: 12,
          fontWeight: 600,
          opacity: 0.8,
        }}
        onClick={() => onToggleCollapse(cat)}
      >
        {multiSelect && (
          <input
            type="checkbox"
            checked={allSelectedInCat}
            ref={(el) => { if (el) el.indeterminate = someSelectedInCat; }}
            onChange={() => onToggleSelectAll(catIds, allSelectedInCat)}
            onClick={(e) => e.stopPropagation()}
            style={{ margin: 0, flexShrink: 0, cursor: 'pointer' }}
            title={allSelectedInCat ? t('bm.deselect_category') : t('bm.select_category')}
          />
        )}
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          style={{
            transform: collapsed ? 'rotate(0deg)' : 'rotate(90deg)',
            transition: 'transform 0.2s',
          }}
        >
          <polyline points="9,18 15,12 9,6" />
        </svg>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: color,
            flexShrink: 0,
          }}
        />
        <span>{displayCat(cat)}</span>
        {status === 'ended' && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 4,
            background: '#3a3a3e', color: '#9aa0a6', marginLeft: 4,
          }}>{t('bm.cat.status_ended')}</span>
        )}
        {status === 'upcoming' && _d && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 4,
            background: 'rgba(59,130,246,0.18)', color: '#7aa9ff', marginLeft: 4,
          }}>
            {t('bm.cat.status_upcoming', {
              date: formatChipDate(_d.start_date, chipLocale),
            })}
          </span>
        )}
        <span style={{ marginLeft: 'auto', opacity: 0.4, fontWeight: 400, fontSize: 10 }}>
          {bms.length}
        </span>
        <button
          type="button"
          className="bookmark-hide-btn"
          title={t('bm.hide_category')}
          onClick={(e) => { e.stopPropagation(); onHide(cat); }}
          style={{
            background: 'none', border: 'none', padding: 2, marginLeft: 2,
            cursor: 'pointer', color: 'inherit',
            display: 'inline-flex', alignItems: 'center',
          }}
        >
          {/* eye-off icon (decorative — the button's title is the label) */}
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        </button>
      </div>

      {!collapsed && (
        <div style={{ paddingLeft: 20 }}>
          {bms.length === 0 && (
            <div style={{ fontSize: 11, opacity: 0.4, padding: '4px 0' }}>{t('bm.blank')}</div>
          )}
          {sortBookmarks(bms, sortMode).map((bm) => {
            const isSelected = bm.id ? selectedIds.has(bm.id) : false;
            return (
              <BookmarkRow
                key={bm.id ?? `${bm.lat}-${bm.lng}`}
                bm={bm}
                isSelected={isSelected}
                multiSelect={multiSelect}
                flashedBmId={flashedBmId}
                toggleSelected={toggleSelected}
                onBookmarkClick={onBookmarkClick}
                onContextMenu={onContextMenu}
                showCategoryInTitle={false}
                showCategoryDot={false}
                showPinIcon
                allowRename
                editingId={editingId}
                editName={editName}
                setEditingId={setEditingId}
                setEditName={setEditName}
                onBookmarkEdit={onBookmarkEdit}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};
