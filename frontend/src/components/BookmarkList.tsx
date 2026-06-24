import React, { useState, useRef } from 'react';
import { BookmarkRow } from './BookmarkRow';
import { CategorySection } from './CategorySection';
import BookmarkContextMenu from './BookmarkContextMenu';
import AddBookmarkDialog from './AddBookmarkDialog';
import CustomBookmarkDialog from './CustomBookmarkDialog';
import EditBookmarkDialog from './EditBookmarkDialog';
import EditCategoryModal from './EditCategoryModal';
import CategoryManagerPanel from './CategoryManagerPanel';
import { useT, useI18n } from '../i18n';
import { useServices } from '../contexts/ServicesContext';
import { useBookmarkUiState } from '../hooks/useBookmarkUiState';
import { useBookmarkSelection } from '../hooks/useBookmarkSelection';
import { sortBookmarks, sortCategoryEntries, type SortMode } from '../utils/bookmarkSort';
import { makeResolveColor } from '../utils/categoryColor';
import {
  getCategoryStatus,
  todayLocal,
  type CategoryStatus,
} from '../utils/categoryStatus';

interface Bookmark {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  // ISO 3166-1 alpha-2 (lowercase), optional. Rendered as a small flag
  // icon on the bookmark's geo line when present.
  country_code?: string;
  // Offline-resolved geo metadata (see backend geo_offline.resolve).
  timezone?: string;  // IANA zone, e.g. 'Asia/Taipei'
  city?: string;      // nearest notable city
  region?: string;    // admin1 — province / state / county
  created_at?: string;  // ISO timestamp, used by 'date added' sort
  last_used_at?: string;  // ISO timestamp, used by 'last used' sort
}

interface Position {
  lat: number;
  lng: number;
}

interface BookmarkListProps {
  bookmarks: Bookmark[];
  categories: string[];
  // Stored color per category (name → hex). Overrides the hash-from-name
  // fallback so renaming a category doesn't re-roll its dot color.
  categoryColors?: Record<string, string>;
  currentPosition: Position | null;
  // Left-click on a bookmark row. Pans the map only — never moves GPS.
  // When the "click also flies GPS" toggle is on, the row dispatches to
  // onTeleport instead, so the bookmark also moves the iPhone.
  onBookmarkClick: (bm: Bookmark) => void;
  // Right-click jump actions. Mirror the map context menu so bookmark
  // right-click has parity with map / history right-click.
  onTeleport: (lat: number, lng: number) => void;
  onNavigate: (lat: number, lng: number) => void;
  onSetAsGoldDittoA?: (lat: number, lng: number) => void;
  onAddWaypoint?: (lat: number, lng: number) => void;
  // Gates Teleport / Navigate (greyed when no device) and Add Waypoint
  // (hidden when not in a route mode). Mirrors MapView prop semantics.
  deviceConnected: boolean;
  showWaypointOption: boolean;
  // Toast hook for "coords copied" / What's-here transient feedback.
  onShowToast?: (msg: string) => void;
  onBookmarkAdd: (bm: Bookmark) => void;
  onBookmarkDelete: (id: string) => void;
  onBookmarkEdit: (id: string, bm: Partial<Bookmark>) => void;
  onCategoryAdd: (name: string) => void;
  onCategoryDelete: (name: string) => void;
  onCategoryDeleteCascade?: (name: string, bookmarkCount: number) => void;
  onCategoryEdit?: (
    name: string,
    patch: { name: string; color: string; start_date: string; end_date: string },
  ) => void;
  // Per-category event dates, keyed by category name (matches the
  // existing categoryColors prop).
  categoryDates?: Record<string, { start_date: string; end_date: string }>;
  showOnMap?: boolean;
  onShowOnMapChange?: (v: boolean) => void;
  onImport?: (file: File) => Promise<void>;
  // Bundled public-event catalog "Refresh public events" button. The
  // status drives label + disabled state; new-count is shown inline.
  // When the catalog endpoint 404s the parent passes `missing`, which
  // hides the button entirely.
  catalogStatus?: 'loading' | 'ok' | 'missing' | 'failed';
  catalogNewCount?: number;
  catalogError?: string | null;
  catalogRefreshing?: boolean;
  onCatalogRefresh?: () => Promise<void> | void;
  // Bulk paste: opens a textarea dialog where the user can drop
  // whitespace-separated "lat lng name" lines and push them all as
  // bookmarks at once. Wired separately from onImport so the file-
  // picker flow stays untouched.
  onBulkPaste?: () => void;
  // Replaces exportUrl. The legacy single-URL property is retained for
  // backward compat but ignored when onExportClick is wired.
  onExportClick?: (anchor: DOMRect) => void;
  exportUrl?: string;
}

const BookmarkList: React.FC<BookmarkListProps> = ({
  bookmarks,
  categories,
  categoryColors,
  currentPosition,
  onBookmarkClick,
  onTeleport,
  onNavigate,
  onSetAsGoldDittoA,
  onAddWaypoint,
  deviceConnected,
  showWaypointOption,
  onShowToast,
  onBookmarkAdd,
  onBookmarkDelete,
  onBookmarkEdit,
  onCategoryAdd,
  onCategoryDelete,
  onCategoryDeleteCascade,
  onCategoryEdit,
  categoryDates,
  showOnMap = false,
  onShowOnMapChange,
  onImport,
  catalogStatus,
  catalogNewCount,
  catalogError,
  catalogRefreshing,
  onCatalogRefresh,
  onBulkPaste,
  onExportClick,
  exportUrl,
}) => {
  // Prefer the stored color (set at creation, editable via color picker). Only
  // fall back to the built-in / name-hash color for legacy categories that have
  // never had a color assigned. (Pure logic lives in utils/categoryColor.)
  const resolveColor = makeResolveColor(categoryColors);
  const t = useT();
  const { lang } = useI18n();
  const chipLocale = lang === 'zh' ? 'zh-TW' : 'en-US';
  // Backend may store the built-in default category as the Chinese '預設'.
  // Translate at render time so EN users see "Default" without touching storage.
  const displayCat = (name: string) => (name === '預設' ? t('bm.default') : name);
  // Backend gateway injected via the hexagon-lite ServicesContext. The
  // bookmark UI-state hook routes its two ui-state calls through it, and the
  // context menu's reverse-geocode goes through api.reverseGeocode — so this
  // view imports NOTHING from services/api or adapters.
  const { api } = useServices();
  // Per-category collapse/expand + hidden-category UI-state (threshold
  // auto-collapse, debounced expanded persist, immediate hidden persist) lives
  // in a dedicated hook so the persistence semantics stay in one place.
  const {
    collapsed,
    toggleCategory,
    hidden,
    hideCategory,
    unhideCategory,
    uiStateLoaded,
  } = useBookmarkUiState({ api, bookmarks, categories, categoryDates });
  // Whether the "N 個已隱藏" row is expanded to show its category list.
  const [hiddenRowOpen, setHiddenRowOpen] = useState(false);
  const lastClickTs = useRef<number>(0);
  const [flashedBmId, setFlashedBmId] = useState<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newName, setNewName] = useState('');
  const [newCategory, setNewCategory] = useState(categories[0] || 'Default');
  const [showCategoryMgr, setShowCategoryMgr] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState('');
  // Edit-category dialog. Open when non-null; the value is the category
  // name being edited. Form fields below are local to the dialog.
  const [editCatName, setEditCatName] = useState<string | null>(null);
  const [editCatNewName, setEditCatNewName] = useState('');
  const [editCatColor, setEditCatColor] = useState('#6c8cff');
  const [editCatStart, setEditCatStart] = useState('');
  const [editCatEnd, setEditCatEnd] = useState('');
  const openEditCategory = (cat: string) => {
    setEditCatName(cat);
    setEditCatNewName(cat);
    setEditCatColor(resolveColor(cat));
    const d = categoryDates?.[cat];
    setEditCatStart(d?.start_date ?? '');
    setEditCatEnd(d?.end_date ?? '');
  };
  const closeEditCategory = () => setEditCatName(null);

  const [contextMenu, setContextMenu] = useState<{ bm: Bookmark; x: number; y: number } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  // Full edit dialog (name + lat + lng) — triggered by context menu "Edit".
  const [editDialog, setEditDialog] = useState<Bookmark | null>(null);
  const [editDialogName, setEditDialogName] = useState('');
  const [editDialogLat, setEditDialogLat] = useState('');
  const [editDialogLng, setEditDialogLng] = useState('');
  const [showCustomDialog, setShowCustomDialog] = useState(false);
  const [customName, setCustomName] = useState('');
  const [customLat, setCustomLat] = useState('');
  const [customLng, setCustomLng] = useState('');
  const [customCategory, setCustomCategory] = useState(categories[0] || 'Default');
  const [search, setSearch] = useState('');
  // Multi-select mode: tick rows and batch-delete. When active, row clicks
  // toggle selection instead of teleporting. State + bulk-delete logic lives in
  // a dedicated hook so the confirm/fan-out semantics stay in one place.
  const {
    multiSelect,
    selectedIds,
    toggleSelected,
    setSelectedIds,
    enterMultiSelect,
    exitMultiSelect,
    toggleSelectAll,
    handleBulkDelete,
  } = useBookmarkSelection({ bookmarks, onBookmarkDelete, t });
  // "Click also flies GPS" toggle persisted in localStorage so the choice
  // survives restart. Default true = legacy behavior (clicking a bookmark
  // teleports iPhone). When false, click only pans the map view (preview).
  // The right-click menu still exposes Teleport / Navigate / Gold A /
  // Waypoint independently of this toggle.
  const [flyGps, setFlyGpsRaw] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem('locwarp.bookmark_fly_gps');
      return v === null ? true : v === '1';
    } catch { return true; }
  });
  const setFlyGps = (v: boolean) => {
    setFlyGpsRaw(v);
    try { localStorage.setItem('locwarp.bookmark_fly_gps', v ? '1' : '0'); } catch { /* ignore */ }
  };

  // Sort mode persisted in localStorage so it survives restart.
  const [sortMode, setSortModeRaw] = useState<SortMode>(() => {
    try {
      const v = localStorage.getItem('locwarp.bookmark_sort') as SortMode | null;
      if (v === 'default' || v === 'name' || v === 'date_added' || v === 'last_used') return v;
    } catch { /* ignore */ }
    return 'default';
  });
  const setSortMode = (m: SortMode) => {
    setSortModeRaw(m);
    try { localStorage.setItem('locwarp.bookmark_sort', m); } catch { /* ignore */ }
  };

  // The context menu's three interlocking guard mechanisms (dismissal
  // listeners, close-reset, reverse-geocode stale-guard) moved into
  // BookmarkContextMenu — they must travel together, see that component.

  // Click handler: flash the bookmark green for 500ms as visual feedback
  // and apply a 150ms debounce so accidental double-clicks don't fire
  // twice. When `flyGps` is on (default), left-click teleports the iPhone
  // via onTeleport; when off, it only pans the map via onBookmarkClick.
  // The right-click menu's Teleport / Navigate / Gold A / Waypoint stay
  // available regardless of the toggle.
  const handleBookmarkClick = (bm: Bookmark) => {
    const now = Date.now();
    if (now - lastClickTs.current < 150) return;
    lastClickTs.current = now;
    if (flyGps) {
      onTeleport(bm.lat, bm.lng);
    } else {
      onBookmarkClick(bm);
    }
    if (bm.id) {
      setFlashedBmId(bm.id);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlashedBmId(null), 500);
    }
  };

  const handleAddBookmark = () => {
    if (!newName.trim() || !currentPosition) return;
    onBookmarkAdd({
      name: newName.trim(),
      lat: currentPosition.lat,
      lng: currentPosition.lng,
      category: newCategory,
    });
    setNewName('');
    setShowAddDialog(false);
  };

  const handleContextMenu = (e: React.MouseEvent, bm: Bookmark) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ bm, x: e.clientX, y: e.clientY });
  };

  const bookmarksByCategory = categories.reduce<Record<string, Bookmark[]>>((acc, cat) => {
    acc[cat] = bookmarks.filter((bm) => bm.category === cat);
    return acc;
  }, {});

  // Include uncategorized
  const uncategorized = bookmarks.filter((bm) => !categories.includes(bm.category));
  if (uncategorized.length > 0) {
    bookmarksByCategory['Uncategorized'] = uncategorized;
  }

  return (
    <div>
      {/* Header with add / manage buttons. flex-wrap so extra buttons drop
          to a new row on narrow library panels instead of pushing the gear
          off-screen. */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <button
          className="action-btn"
          onClick={() => setShowAddDialog(!showAddDialog)}
          style={{ padding: '3px 8px', fontSize: 12 }}
          title={t('bm.add_here')}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          {t('bm.add')}
        </button>
        <button
          className="action-btn"
          onClick={() => {
            setCustomCategory(categories[0] || 'Default');
            setShowCustomDialog(true);
          }}
          style={{ padding: '3px 8px', fontSize: 12 }}
          title={t('bm.add_custom_tooltip')}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="10" r="3" />
            <path d="M12 2a8 8 0 00-8 8c0 6 8 12 8 12s8-6 8-12a8 8 0 00-8-8z" />
          </svg>
          {t('bm.add_custom')}
        </button>
        {(onExportClick || exportUrl) && (
          <button
            className="action-btn"
            onClick={(e) => {
              if (onExportClick) {
                onExportClick((e.currentTarget as HTMLButtonElement).getBoundingClientRect())
              }
            }}
            style={{ padding: '3px 6px', fontSize: 12, marginLeft: 'auto', display: 'inline-flex', alignItems: 'center' }}
            title={t('bm.export_tooltip')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
        )}
        {onBulkPaste && (
          <button
            className="action-btn"
            onClick={onBulkPaste}
            style={{ padding: '3px 6px', fontSize: 12, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', marginLeft: (onExportClick || exportUrl) ? 0 : 'auto' }}
            title={t('bm.bulk_paste_tooltip')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              <line x1="15" y1="12" x2="18" y2="12" />
              <line x1="15" y1="16" x2="18" y2="16" />
            </svg>
          </button>
        )}
        {onImport && (
          <label
            className="action-btn"
            style={{ padding: '3px 6px', fontSize: 12, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', marginLeft: (onExportClick || exportUrl || onBulkPaste) ? 0 : 'auto' }}
            title={t('bm.import_tooltip')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <input
              type="file"
              accept="application/json,.json"
              style={{ display: 'none' }}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) await onImport(f);
                e.target.value = '';
              }}
            />
          </label>
        )}
        {onCatalogRefresh && catalogStatus !== 'missing' && (() => {
          const loading = catalogStatus === 'loading';
          const failed = catalogStatus === 'failed';
          const count = catalogNewCount ?? 0;
          const upToDate = catalogStatus === 'ok' && count === 0;
          const disabled = loading || failed || upToDate || !!catalogRefreshing;
          const label = failed
            ? t('bm.catalog.failed')
            : upToDate
              ? t('bm.catalog.up_to_date')
              : loading
                ? t('bm.catalog.refresh')
                : t('bm.catalog.refresh_count', { n: count });
          const title = failed
            ? (catalogError ?? '')
            : upToDate
              ? t('bm.catalog.up_to_date_tooltip')
              : '';
          return (
            <button
              className="action-btn"
              onClick={() => { void onCatalogRefresh(); }}
              disabled={disabled}
              title={title || undefined}
              style={{ padding: '3px 8px', fontSize: 12, opacity: disabled ? 0.5 : 1 }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="23 4 23 10 17 10" />
                <polyline points="1 20 1 14 7 14" />
                <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
              </svg>
              {label}
            </button>
          );
        })()}
        <button
          className="action-btn"
          onClick={() => {
            if (multiSelect) {
              exitMultiSelect();
            } else {
              // Opening multi-select closes any other mutually-exclusive
              // panel that'd otherwise stack on top and confuse the user.
              setShowCategoryMgr(false);
              enterMultiSelect();
            }
          }}
          style={{
            padding: '3px 6px', fontSize: 12, display: 'inline-flex', alignItems: 'center',
            background: multiSelect ? 'rgba(108,140,255,0.2)' : undefined,
            borderColor: multiSelect ? 'rgba(108,140,255,0.6)' : undefined,
          }}
          title={multiSelect ? t('bm.exit_multi_select') : t('bm.multi_select_tooltip')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="9 11 12 14 22 4" />
            <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
          </svg>
        </button>
        <button
          className="action-btn"
          onClick={() => {
            setShowCategoryMgr((prev) => {
              const next = !prev;
              if (next && multiSelect) exitMultiSelect();
              return next;
            });
          }}
          style={{ padding: '3px 8px', fontSize: 12 }}
          title={t('bm.manage_categories')}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </div>

      {/* Search box. Sticks to top of the scroll container so users with
          long lists don't have to scroll back up to start a new search. */}
      <div style={{
        position: 'sticky', top: -12, zIndex: 5,
        background: '#1e1e24',
        marginLeft: -12, marginRight: -12,
        padding: '8px 12px',
        borderBottom: '1px solid rgba(108, 140, 255, 0.08)',
        marginBottom: 8,
      }}>
        <div style={{ position: 'relative' }}>
        <svg
          width="12" height="12" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2"
          style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', opacity: 0.4, pointerEvents: 'none' }}
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          className="search-input"
          placeholder={t('bm.search_placeholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: '100%', paddingLeft: 26, paddingRight: search ? 24 : 8, fontSize: 12 }}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            title={t('bm.search_clear')}
            style={{
              position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
              background: 'none', border: 'none', color: '#bbb',
              cursor: 'pointer', padding: '2px 6px', fontSize: 14, lineHeight: 1,
            }}
          >×</button>
        )}
        </div>
      </div>

      {/* Show-all-on-map toggle */}
      {onShowOnMapChange && (
        <label
          className="lw-checkbox"
          style={{ display: 'flex', marginTop: 8, fontSize: 11.5 }}
        >
          <input
            type="checkbox"
            checked={showOnMap}
            onChange={(e) => onShowOnMapChange(e.target.checked)}
          />
          <span className="lw-checkbox-box"></span>
          <span className="lw-checkbox-label">{t('bm.show_on_map')}</span>
        </label>
      )}

      {/* Click-also-flies-GPS toggle. When on, left-click on a bookmark
          teleports the iPhone; when off, it only pans the map view.
          Right-click menu actions are unaffected. */}
      <label
        className="lw-checkbox"
        title={t('bm.fly_gps_tooltip')}
        style={{ display: 'flex', marginTop: 6, fontSize: 11.5 }}
      >
        <input
          type="checkbox"
          checked={flyGps}
          onChange={(e) => setFlyGps(e.target.checked)}
        />
        <span className="lw-checkbox-box"></span>
        <span className="lw-checkbox-label">{t('bm.fly_gps')}</span>
      </label>

      {/* Sort control — choose how the bookmark list is ordered. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 11, color: '#bbb' }}>
        <span style={{ opacity: 0.7 }}>{t('bm.sort_label')}</span>
        <select
          value={sortMode}
          onChange={(e) => setSortMode(e.target.value as SortMode)}
          style={{
            flex: 1, background: '#1e1e22', color: '#e0e0e0',
            border: '1px solid rgba(255,255,255,0.12)', borderRadius: 4,
            padding: '3px 6px', fontSize: 11,
          }}
        >
          {/* Explicit inline colors so the popup list is readable on
              Windows native select dropdown (which defaults to white bg). */}
          <option value="default" style={{ background: '#1e1e22', color: '#e0e0e0' }}>{t('bm.sort_default')}</option>
          <option value="name" style={{ background: '#1e1e22', color: '#e0e0e0' }}>{t('bm.sort_name')}</option>
          <option value="date_added" style={{ background: '#1e1e22', color: '#e0e0e0' }}>{t('bm.sort_date_added')}</option>
          <option value="last_used" style={{ background: '#1e1e22', color: '#e0e0e0' }}>{t('bm.sort_last_used')}</option>
        </select>
      </div>

      {/* Add bookmark dialog */}
      <AddBookmarkDialog
        open={showAddDialog}
        name={newName}
        category={newCategory}
        categories={categories}
        hasPosition={!!currentPosition}
        displayCat={displayCat}
        onNameChange={setNewName}
        onCategoryChange={setNewCategory}
        onSubmit={handleAddBookmark}
        onClose={() => setShowAddDialog(false)}
      />

      {/* Category manager */}
      {showCategoryMgr && (
        <CategoryManagerPanel
          categories={categories}
          bookmarkCounts={categories.reduce<Record<string, number>>((acc, cat) => {
            acc[cat] = (bookmarksByCategory[cat] ?? []).length;
            return acc;
          }, {})}
          resolveColor={resolveColor}
          displayCat={displayCat}
          newCategoryName={newCategoryName}
          onNewCategoryNameChange={setNewCategoryName}
          onCategoryAdd={onCategoryAdd}
          onCategoryDelete={onCategoryDelete}
          onCategoryDeleteCascade={onCategoryDeleteCascade}
          onCategoryEdit={onCategoryEdit ? openEditCategory : undefined}
        />
      )}

      <EditCategoryModal
        categoryName={editCatName}
        newName={editCatNewName}
        color={editCatColor}
        startDate={editCatStart}
        endDate={editCatEnd}
        onNewNameChange={setEditCatNewName}
        onColorChange={setEditCatColor}
        onStartDateChange={setEditCatStart}
        onEndDateChange={setEditCatEnd}
        onSubmit={(name, patch) => onCategoryEdit?.(name, patch)}
        onClose={closeEditCategory}
      />

      {/* Search mode: flat filtered list, no category grouping */}
      {search.trim() !== '' && (() => {
        const q = search.trim().toLowerCase();
        const matches = sortBookmarks(bookmarks.filter((bm) => {
          const name = (bm.name ?? '').toLowerCase();
          const coord = `${bm.lat.toFixed(5)}, ${bm.lng.toFixed(5)}`;
          return name.includes(q) || coord.includes(q);
        }), sortMode);
        if (matches.length === 0) {
          return (
            <div style={{ fontSize: 12, opacity: 0.5, padding: '10px 0', textAlign: 'center' }}>
              {t('bm.search_no_results')}
            </div>
          );
        }
        return (
          <div style={{ paddingLeft: 4 }}>
            {matches.map((bm) => {
              const isSelected = bm.id ? selectedIds.has(bm.id) : false;
              return (
                <BookmarkRow
                  key={bm.id ?? `${bm.lat}-${bm.lng}`}
                  bm={bm}
                  isSelected={isSelected}
                  multiSelect={multiSelect}
                  flashedBmId={flashedBmId}
                  toggleSelected={toggleSelected}
                  onBookmarkClick={handleBookmarkClick}
                  onContextMenu={handleContextMenu}
                  showCategoryInTitle
                  showCategoryDot
                  showPinIcon={false}
                  allowRename={false}
                  resolveColor={resolveColor}
                  displayCat={displayCat}
                />
              );
            })}
          </div>
        );
      })()}

      {/* Bookmark groups — only when NOT searching */}
      {search.trim() === '' && sortCategoryEntries(
        Object.entries(bookmarksByCategory).filter(([cat]) => !hidden.has(cat)),
        sortMode,
      )
        .map(([cat, bms]) => {
        const _d = categoryDates?.[cat];
        const status: CategoryStatus = _d
          ? getCategoryStatus(_d.start_date, _d.end_date, todayLocal())
          : 'evergreen';
        return (
          <CategorySection
            key={cat}
            cat={cat}
            bms={bms}
            collapsed={!!collapsed[cat]}
            color={resolveColor(cat)}
            status={status}
            dates={_d}
            chipLocale={chipLocale}
            sortMode={sortMode}
            displayCat={displayCat}
            multiSelect={multiSelect}
            selectedIds={selectedIds}
            onToggleSelectAll={(catIds, allSelected) => {
              setSelectedIds((prev) => {
                const next = new Set(prev);
                if (allSelected) {
                  catIds.forEach((id) => next.delete(id));
                } else {
                  catIds.forEach((id) => next.add(id));
                }
                return next;
              });
            }}
            onToggleCollapse={toggleCategory}
            onHide={hideCategory}
            flashedBmId={flashedBmId}
            toggleSelected={toggleSelected}
            onBookmarkClick={handleBookmarkClick}
            onContextMenu={handleContextMenu}
            editingId={editingId}
            editName={editName}
            setEditingId={setEditingId}
            setEditName={setEditName}
            onBookmarkEdit={onBookmarkEdit}
          />
        );
      })}

      {bookmarks.length === 0 && (
        <div style={{ fontSize: 12, opacity: 0.5, padding: '8px 0', textAlign: 'center' }}>
          {t('bm.empty')}
        </div>
      )}

      {/* Multi-select toolbar — sticks to the bottom of the scroll area
          so the user can scroll through the list unchecking items to
          keep, then hit Delete without scrolling back up. */}
      {multiSelect && (
        <div
          style={{
            position: 'sticky',
            bottom: -12, zIndex: 10,
            marginLeft: -12, marginRight: -12,
            marginTop: 16,
            padding: '8px 12px',
            background: 'rgba(26, 29, 39, 0.98)',
            backdropFilter: 'blur(6px)',
            borderTop: '1px solid rgba(108,140,255,0.35)',
            boxShadow: '0 -6px 12px rgba(0,0,0,0.35)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
            <button
              className="action-btn"
              onClick={toggleSelectAll}
              style={{ padding: '3px 8px', fontSize: 11 }}
            >
              {selectedIds.size === bookmarks.length && bookmarks.length > 0
                ? t('bm.deselect_all')
                : t('bm.select_all')}
            </button>
            <span style={{ opacity: 0.7, marginLeft: 'auto' }}>
              {selectedIds.size} / {bookmarks.length}
            </span>
            <button
              className="action-btn"
              onClick={handleBulkDelete}
              disabled={selectedIds.size === 0}
              style={{
                padding: '3px 10px', fontSize: 11, fontWeight: 600,
                color: selectedIds.size === 0 ? '#888' : '#ff6b6b',
                borderColor: selectedIds.size === 0 ? undefined : 'rgba(255,107,107,0.4)',
                cursor: selectedIds.size === 0 ? 'not-allowed' : 'pointer',
              }}
            >
              {t('bm.delete_selected').replace('{n}', String(selectedIds.size))}
            </button>
          </div>
        </div>
      )}

      {/* Unhide row — only when not searching and at least one category is hidden.
          Intersect with current categories so a since-deleted category never shows. */}
      {search.trim() === '' && (() => {
        const hiddenList = categories.filter((c) => hidden.has(c));
        if (hiddenList.length === 0) return null;
        return (
          <div style={{ marginTop: 4, borderTop: '1px solid #444', paddingTop: 4 }}>
            <div
              onClick={() => setHiddenRowOpen((v) => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '5px 4px', cursor: 'pointer',
                fontSize: 11, opacity: 0.6,
              }}
            >
              <svg
                width="10" height="10" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2"
                style={{
                  transform: hiddenRowOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s',
                }}
              >
                <polyline points="9,18 15,12 9,6" />
              </svg>
              <span>{t('bm.hidden_count', { n: hiddenList.length })}</span>
            </div>
            {hiddenRowOpen && (
              <div style={{ paddingLeft: 20 }}>
                {hiddenList.map((cat) => (
                  <div
                    key={cat}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '4px 6px', fontSize: 12, opacity: 0.7,
                    }}
                  >
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: resolveColor(cat), flexShrink: 0,
                    }} />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {displayCat(cat)}
                    </span>
                    <button
                      type="button"
                      title={t('bm.unhide_category')}
                      onClick={() => unhideCategory(cat)}
                      style={{
                        background: 'none', border: 'none', padding: 2,
                        cursor: 'pointer', color: 'inherit', opacity: 0.7,
                        display: 'inline-flex', alignItems: 'center',
                      }}
                    >
                      {/* eye icon */}
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* Context menu — portal + the 3 interlocking guard mechanisms live in
          BookmarkContextMenu. Keyed on the open snapshot so each right-click
          mounts a fresh instance (the stale-guard relies on per-open mount). */}
      {contextMenu && (
        <BookmarkContextMenu
          key={`${contextMenu.bm.id ?? `${contextMenu.bm.lat},${contextMenu.bm.lng}`}-${contextMenu.x}-${contextMenu.y}`}
          bm={contextMenu.bm}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          reverseGeocode={api.reverseGeocode}
          deviceConnected={deviceConnected}
          showWaypointOption={showWaypointOption}
          onTeleport={onTeleport}
          onNavigate={onNavigate}
          onSetAsGoldDittoA={onSetAsGoldDittoA}
          onAddWaypoint={onAddWaypoint}
          onEdit={(bm) => {
            setEditDialog(bm);
            setEditDialogName(bm.name);
            setEditDialogLat(bm.lat.toString());
            setEditDialogLng(bm.lng.toString());
          }}
          onCopy={async (bm) => {
            const text = `${bm.name} ${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`;
            try {
              await navigator.clipboard.writeText(text);
            } catch {
              const ta = document.createElement('textarea');
              ta.value = text;
              document.body.appendChild(ta);
              ta.select();
              try { document.execCommand('copy'); } catch { /* ignore */ }
              document.body.removeChild(ta);
            }
            if (onShowToast) onShowToast(t('map.coords_copied'));
          }}
          onDelete={async (id) => {
            try {
              await onBookmarkDelete(id);
            } catch (err: any) {
              if (onShowToast) onShowToast(t('bm.delete_failed', { error: err?.message || '' }));
            }
          }}
          onMoveToCategory={(id, cat) => onBookmarkEdit(id, { category: cat })}
          categories={categories}
          resolveColor={resolveColor}
          displayCat={displayCat}
        />
      )}

      {/* Edit dialog — name + lat + lng */}
      <EditBookmarkDialog
        bookmark={editDialog}
        name={editDialogName}
        lat={editDialogLat}
        lng={editDialogLng}
        onNameChange={setEditDialogName}
        onLatChange={setEditDialogLat}
        onLngChange={setEditDialogLng}
        onSubmit={onBookmarkEdit}
        onClose={() => setEditDialog(null)}
      />

      <CustomBookmarkDialog
        open={showCustomDialog}
        name={customName}
        lat={customLat}
        lng={customLng}
        category={customCategory}
        categories={categories}
        displayCat={displayCat}
        onNameChange={setCustomName}
        onLatChange={setCustomLat}
        onLngChange={setCustomLng}
        onCategoryChange={setCustomCategory}
        onSubmit={(bm) => {
          onBookmarkAdd(bm);
          setCustomName(''); setCustomLat(''); setCustomLng('');
          setShowCustomDialog(false);
        }}
        onClose={() => setShowCustomDialog(false)}
      />
    </div>
  );
};

export default BookmarkList;
