import React, { useState, useEffect, useRef } from 'react';
import { isSubmitEnter } from '../utils/keyboard';
import { createPortal } from 'react-dom';
import { BookmarkRow } from './BookmarkRow';
import { CategorySection } from './CategorySection';
import { useT, useI18n } from '../i18n';
import { reverseGeocode } from '../services/api';
import { useServices } from '../contexts/ServicesContext';
import { useBookmarkUiState } from '../hooks/useBookmarkUiState';
import { sortBookmarks, sortCategoryEntries, type SortMode } from '../utils/bookmarkSort';
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

// Preset palette for the color picker. Covers warm + cool + neutral so every
// category can find a visually distinct slot.
const COLOR_PALETTE = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#14b8a6', '#3b82f6', '#6366f1', '#a855f7',
  '#ec4899', '#64748b',
];

const CATEGORY_COLORS: Record<string, string> = {
  Default: '#4285f4',
  Home: '#4caf50',
  Work: '#ff9800',
  Favorites: '#e91e63',
  Custom: '#9c27b0',
};

function getCategoryColor(name: string): string {
  if (CATEGORY_COLORS[name]) return CATEGORY_COLORS[name];
  // Deterministic color from name
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 60%, 55%)`;
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
  // fall back to CATEGORY_COLORS / name hash for legacy categories that have
  // never had a color assigned.
  const resolveColor = (name: string): string => {
    const stored = categoryColors?.[name];
    if (stored) return stored;
    return getCategoryColor(name);
  };
  const t = useT();
  const { lang } = useI18n();
  const chipLocale = lang === 'zh' ? 'zh-TW' : 'en-US';
  // Backend may store the built-in default category as the Chinese '預設'.
  // Translate at render time so EN users see "Default" without touching storage.
  const displayCat = (name: string) => (name === '預設' ? t('bm.default') : name);
  // Backend gateway injected via the hexagon-lite ServicesContext. The
  // bookmark UI-state hook routes its two ui-state calls through it; the
  // direct-imported reverseGeocode is migrated in a later task.
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
  // Split "24.14, 120.65" (or tab/whitespace) into [lat, lng] so a user can
  // paste a Google-Maps-style pair into just the lat field instead of
  // splitting it themselves.
  const trySplitLatLng = (s: string): [string, string] | null => {
    const m = s.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\t ]\s*(-?\d+(?:\.\d+)?)\s*$/);
    return m ? [m[1], m[2]] : null;
  };

  const [contextMenu, setContextMenu] = useState<{ bm: Bookmark; x: number; y: number } | null>(null);
  // Reverse-geocode state for the menu's coords header. Reset whenever
  // the menu closes — see the dismissal useEffect below.
  const [reverseGeo, setReverseGeo] = useState<{
    loading: boolean; address: string | null; error: string | null;
    key: string; // lat|lng the result belongs to
  }>({ loading: false, address: null, error: null, key: '' });
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
  // toggle selection instead of teleporting.
  const [multiSelect, setMultiSelect] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const exitMultiSelect = () => {
    setMultiSelect(false);
    setSelectedIds(new Set());
  };
  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    const msg = t('bm.delete_confirm').replace('{n}', String(selectedIds.size));
    if (!window.confirm(msg)) return;
    const ids = Array.from(selectedIds);
    await Promise.all(ids.map((id) => {
      try { return Promise.resolve(onBookmarkDelete(id)); } catch { return Promise.resolve(); }
    }));
    exitMultiSelect();
  };
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

  // Close the context menu on ESC, or on any click / right-click that
  // isn't on the menu itself. Uses pointerdown so it fires before React
  // click handlers inside the menu.
  useEffect(() => {
    if (!contextMenu) return;
    const onOutside = (e: Event) => {
      const target = e.target as Element | null;
      if (target && target.closest?.('[data-bookmark-context-menu]')) return;
      setContextMenu(null);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null);
    };
    // Register on the next tick so the opening right-click's bubbling
    // doesn't dismiss the menu the moment we render it.
    const id = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside);
      document.addEventListener('contextmenu', onOutside);
      document.addEventListener('keydown', onEsc);
    }, 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener('pointerdown', onOutside);
      document.removeEventListener('contextmenu', onOutside);
      document.removeEventListener('keydown', onEsc);
    };
  }, [contextMenu]);

  // Drop any in-flight or completed reverse-geocode result when the
  // menu closes, so a stale address from a previous right-click can
  // never leak into a new lookup.
  useEffect(() => {
    if (!contextMenu) {
      setReverseGeo({ loading: false, address: null, error: null, key: '' });
    }
  }, [contextMenu]);

  // Tracks the current `contextMenu` value so async handlers can detect
  // whether the menu was dismissed or re-targeted mid-flight and drop
  // their result instead of writing back stale state.
  const contextMenuRef = useRef<typeof contextMenu>(null);
  useEffect(() => {
    contextMenuRef.current = contextMenu;
  }, [contextMenu]);

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

  const handleAddCustom = () => {
    const name = customName.trim();
    const lat = parseFloat(customLat);
    const lng = parseFloat(customLng);
    if (!name) return;
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) return;
    if (!Number.isFinite(lng) || lng < -180 || lng > 180) return;
    onBookmarkAdd({ name, lat, lng, category: customCategory });
    setCustomName(''); setCustomLat(''); setCustomLng('');
    setShowCustomDialog(false);
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
              setMultiSelect(true);
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
      {showAddDialog && (
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
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => isSubmitEnter(e) && handleAddBookmark()}
            style={{ width: '100%', marginBottom: 8 }}
            autoFocus
          />
          <select
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
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
            <button className="action-btn primary" onClick={handleAddBookmark} style={{ flex: 1, fontSize: 12 }}>
              {t('generic.save')}
            </button>
            <button className="action-btn" onClick={() => setShowAddDialog(false)} style={{ fontSize: 12 }}>
              {t('generic.cancel')}
            </button>
          </div>
          {!currentPosition && (
            <div style={{ fontSize: 11, color: '#f44336', marginTop: 6 }}>
              {t('bm.no_position')}
            </div>
          )}
        </div>
      )}

      {/* Category manager */}
      {showCategoryMgr && (
        <div
          style={{
            background: '#2a2a2e',
            border: '1px solid #444',
            borderRadius: 6,
            padding: 12,
            marginBottom: 8,
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6, opacity: 0.7 }}>
            {t('bm.manage_categories')}
          </div>
          {categories.map((cat) => (
            <div
              key={cat}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 0',
                fontSize: 12,
                position: 'relative',
              }}
            >
              <div
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  background: resolveColor(cat),
                  border: '1.5px solid rgba(255,255,255,0.15)',
                  flexShrink: 0,
                  boxShadow: '0 1px 2px rgba(0,0,0,0.3)',
                }}
              />
              <span style={{ flex: 1 }}>{displayCat(cat)}</span>
              {cat !== 'Default' && cat !== '預設' && onCategoryEdit && (
                <button
                  onClick={() => openEditCategory(cat)}
                  title={t('bm.cat.edit_title')}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--fg-muted, #888)',
                    cursor: 'pointer',
                    padding: '2px 4px',
                    fontSize: 11,
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                    <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
              )}
              {cat !== 'Default' && cat !== '預設' && (
                <CategoryDeleteDropdown
                  category={cat}
                  bookmarkCount={(bookmarksByCategory[cat] ?? []).length}
                  onSoftDelete={() => onCategoryDelete(cat)}
                  onCascadeDelete={
                    onCategoryDeleteCascade
                      ? () => onCategoryDeleteCascade(cat, (bookmarksByCategory[cat] ?? []).length)
                      : undefined
                  }
                />
              )}
            </div>
          ))}
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <input
              type="text"
              className="search-input"
              placeholder={t('bm.add_category')}
              value={newCategoryName}
              onChange={(e) => setNewCategoryName(e.target.value)}
              onKeyDown={(e) => {
                if (isSubmitEnter(e) && newCategoryName.trim()) {
                  onCategoryAdd(newCategoryName.trim());
                  setNewCategoryName('');
                }
              }}
              style={{ flex: 1 }}
            />
            <button
              className="action-btn"
              onClick={() => {
                if (newCategoryName.trim()) {
                  onCategoryAdd(newCategoryName.trim());
                  setNewCategoryName('');
                }
              }}
              style={{ fontSize: 11 }}
            >
              {t('bm.new_category')}
            </button>
          </div>
        </div>
      )}

      {editCatName !== null && createPortal(
        <div
          onClick={closeEditCategory}
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
                value={editCatNewName}
                onChange={(e) => setEditCatNewName(e.target.value)}
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
                    onClick={() => setEditCatColor(c)}
                    style={{
                      width: 28, height: 28, borderRadius: '50%',
                      background: c,
                      border: editCatColor.toLowerCase() === c.toLowerCase()
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
                value={editCatColor}
                onChange={(e) => setEditCatColor(e.target.value)}
                title={t('bm.recolor_custom')}
                style={{ width: '100%', height: 28, border: 'none', borderRadius: 4, padding: 0, marginTop: 4 }}
              />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.starts')}</span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="date"
                  value={editCatStart}
                  onChange={(e) => setEditCatStart(e.target.value)}
                  style={{ flex: 1, padding: '4px 6px', background: '#1e1e22', color: '#e0e0e0', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4 }}
                />
                <button
                  className="action-btn"
                  onClick={() => setEditCatStart('')}
                  disabled={!editCatStart}
                  style={{ fontSize: 11, padding: '3px 8px', opacity: editCatStart ? 1 : 0.4 }}
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
                  value={editCatEnd}
                  onChange={(e) => setEditCatEnd(e.target.value)}
                  style={{ flex: 1, padding: '4px 6px', background: '#1e1e22', color: '#e0e0e0', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4 }}
                />
                <button
                  className="action-btn"
                  onClick={() => setEditCatEnd('')}
                  disabled={!editCatEnd}
                  style={{ fontSize: 11, padding: '3px 8px', opacity: editCatEnd ? 1 : 0.4 }}
                >
                  ✕ {t('bm.cat.dates_clear')}
                </button>
              </div>
            </label>

            <div style={{ fontSize: 10, opacity: 0.55 }}>{t('bm.cat.dates_hint')}</div>
            {editCatStart && editCatEnd && editCatStart > editCatEnd && (
              <div style={{ fontSize: 11, color: '#f87171' }}>{t('bm.cat.dates_invalid')}</div>
            )}

            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 4 }}>
              <button className="action-btn" onClick={closeEditCategory} style={{ fontSize: 11 }}>
                {t('generic.cancel')}
              </button>
              <button
                className="action-btn"
                disabled={
                  !editCatNewName.trim() ||
                  (!!editCatStart && !!editCatEnd && editCatStart > editCatEnd)
                }
                onClick={() => {
                  if (!onCategoryEdit || !editCatName) return;
                  const next = editCatNewName.trim();
                  if (!next) return;
                  if (editCatStart && editCatEnd && editCatStart > editCatEnd) return;
                  onCategoryEdit(editCatName, {
                    name: next,
                    color: editCatColor,
                    start_date: editCatStart,
                    end_date: editCatEnd,
                  });
                  closeEditCategory();
                }}
                style={{ fontSize: 11 }}
              >
                {t('bm.cat.save')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

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
              onClick={() => {
                const allIds = bookmarks.map((b) => b.id).filter((x): x is string => !!x);
                if (selectedIds.size === allIds.length) {
                  setSelectedIds(new Set());
                } else {
                  setSelectedIds(new Set(allIds));
                }
              }}
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

      {/* Context menu (dismissed via document click listener — see useEffect) */}
      {contextMenu && (() => {
        // Centralize the lat|lng key so the click handler, loading
        // indicator, and result-conditional all use the exact same
        // string — and so the async handler can drop stale writes
        // that resolve after the menu was dismissed or re-targeted.
        const openSnapshot = contextMenu;
        const headerKey = `${contextMenu.bm.lat.toFixed(6)}|${contextMenu.bm.lng.toFixed(6)}`;
        return createPortal(
        <>
          <div
            data-bookmark-context-menu
            style={{
              position: 'fixed',
              // Clamp to viewport so the menu never falls off-screen.
              left: Math.min(contextMenu.x, window.innerWidth - 200),
              top: Math.min(contextMenu.y, window.innerHeight - 360),
              zIndex: 9999,
              background: 'rgba(26, 29, 39, 0.95)',
              backdropFilter: 'blur(10px)',
              WebkitBackdropFilter: 'blur(10px)',
              border: '1px solid rgba(108, 140, 255, 0.18)',
              borderRadius: 10,
              padding: '4px 0',
              boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.04) inset',
              minWidth: 180,
              maxWidth: 'calc(100vw - 16px)',
              maxHeight: 'calc(100vh - 16px)',
              overflow: 'auto',
            }}
          >
            {/* 1. Coords header — clickable to trigger reverse-geocode. */}
            <div
              style={{
                padding: '8px 16px 6px',
                color: '#9ac0ff',
                fontSize: 12,
                fontFamily: 'monospace',
                display: 'flex',
                alignItems: 'center',
                cursor: 'pointer',
                gap: 4,
              }}
              title={t('map.whats_here_tooltip')}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={async (e) => {
                e.stopPropagation();
                if (reverseGeo.loading && reverseGeo.key === headerKey) return;
                if (reverseGeo.address && reverseGeo.key === headerKey) return;
                setReverseGeo({ loading: true, address: null, error: null, key: headerKey });
                try {
                  const res = await reverseGeocode(contextMenu.bm.lat, contextMenu.bm.lng);
                  // Menu was dismissed or re-targeted while the request was in flight —
                  // drop the result so it doesn't leak into the next menu open.
                  if (contextMenuRef.current !== openSnapshot) return;
                  const name = res?.display_name || res?.address || null;
                  if (name) {
                    setReverseGeo({ loading: false, address: name, error: null, key: headerKey });
                  } else {
                    setReverseGeo({ loading: false, address: null, error: t('map.whats_here_empty'), key: headerKey });
                  }
                } catch (err: any) {
                  if (contextMenuRef.current !== openSnapshot) return;
                  setReverseGeo({ loading: false, address: null, error: err?.message || 'error', key: headerKey });
                }
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 4, opacity: 0.8 }}>
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              <span style={{ flex: 1 }}>{contextMenu.bm.lat.toFixed(6)}, {contextMenu.bm.lng.toFixed(6)}</span>
              <span style={{ fontSize: 10, opacity: 0.7, fontFamily: 'inherit' }}>
                {reverseGeo.loading && reverseGeo.key === headerKey
                  ? t('map.whats_here_loading')
                  : t('map.whats_here')}
              </span>
            </div>
            {/* Reverse-geocode result or error, shown only after the user taps the header row. */}
            {reverseGeo.key === headerKey &&
             (reverseGeo.address || reverseGeo.error) && (
              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  padding: '2px 16px 8px',
                  color: reverseGeo.error ? '#ff8a80' : '#d0d0d0',
                  fontSize: 11.5,
                  lineHeight: 1.5,
                  userSelect: 'text',
                  cursor: 'text',
                  wordBreak: 'break-word',
                }}
              >
                {reverseGeo.address ?? reverseGeo.error}
              </div>
            )}
            <div style={{ height: 1, background: '#444', margin: '2px 0 4px' }} />

            {/* 2 + 3. Teleport / Navigate (device-gated). */}
            {deviceConnected ? (
              <>
                <div
                  style={ctxItemStyle}
                  onMouseEnter={ctxHighlight}
                  onMouseLeave={ctxUnhighlight}
                  onClick={() => {
                    onTeleport(contextMenu.bm.lat, contextMenu.bm.lng);
                    setContextMenu(null);
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="2" x2="12" y2="6" />
                    <line x1="12" y1="18" x2="12" y2="22" />
                    <line x1="2" y1="12" x2="6" y2="12" />
                    <line x1="18" y1="12" x2="22" y2="12" />
                  </svg>
                  {t('map.teleport_here')}
                </div>
                <div
                  style={ctxItemStyle}
                  onMouseEnter={ctxHighlight}
                  onMouseLeave={ctxUnhighlight}
                  onClick={() => {
                    onNavigate(contextMenu.bm.lat, contextMenu.bm.lng);
                    setContextMenu(null);
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <polygon points="3,11 22,2 13,21 11,13" />
                  </svg>
                  {t('map.navigate_here')}
                </div>
              </>
            ) : (
              <div
                style={{ ...ctxItemStyle, color: '#ff6b6b', cursor: 'not-allowed', opacity: 0.75 }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <circle cx="12" cy="12" r="10" />
                  <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
                </svg>
                {t('map.device_disconnected')}
              </div>
            )}

            {/* 4. Set as Gold Ditto A (always wired in practice). */}
            {onSetAsGoldDittoA && (
              <div
                style={ctxItemStyle}
                onMouseEnter={ctxHighlight}
                onMouseLeave={ctxUnhighlight}
                onClick={() => {
                  onSetAsGoldDittoA(contextMenu.bm.lat, contextMenu.bm.lng);
                  setContextMenu(null);
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <path d="M12 2 L13.5 9 L21 12 L13.5 15 L12 22 L10.5 15 L3 12 L10.5 9 Z" />
                </svg>
                {t('goldditto.set_as_a')}
              </div>
            )}

            {/* 5. Add as Waypoint (only in a route mode). */}
            {showWaypointOption && onAddWaypoint && (
              <div
                style={ctxItemStyle}
                onMouseEnter={ctxHighlight}
                onMouseLeave={ctxUnhighlight}
                onClick={() => {
                  onAddWaypoint(contextMenu.bm.lat, contextMenu.bm.lng);
                  setContextMenu(null);
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <circle cx="12" cy="12" r="3" />
                  <line x1="12" y1="5" x2="12" y2="1" />
                  <line x1="12" y1="23" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="1" y2="12" />
                  <line x1="23" y1="12" x2="19" y2="12" />
                </svg>
                {t('map.add_waypoint')}
              </div>
            )}

            <div style={{ height: 1, background: '#444', margin: '4px 0' }} />

            {/* 6. Edit. */}
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                const bm = contextMenu.bm;
                setEditDialog(bm);
                setEditDialogName(bm.name);
                setEditDialogLat(bm.lat.toString());
                setEditDialogLng(bm.lng.toString());
                setContextMenu(null);
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              {t('bm.edit')}
            </div>

            {/* 7. Copy (name + lat/lng). */}
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={async () => {
                const text = `${contextMenu.bm.name} ${contextMenu.bm.lat.toFixed(6)}, ${contextMenu.bm.lng.toFixed(6)}`;
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
                setContextMenu(null);
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              </svg>
              {t('bm.copy')}
            </div>

            {/* 8. Delete. */}
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                if (contextMenu.bm.id) onBookmarkDelete(contextMenu.bm.id);
                setContextMenu(null);
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f44336" strokeWidth="2" style={{ marginRight: 6 }}>
                <polyline points="3,6 5,6 21,6" />
                <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
              </svg>
              <span style={{ color: '#f44336' }}>{t('generic.delete')}</span>
            </div>

            {/* 9. Move to category (only when more than one category exists). */}
            {categories.length > 1 && (
              <>
                <div style={{ height: 1, background: '#444', margin: '4px 0' }} />
                <div style={{ padding: '4px 12px', fontSize: 10, opacity: 0.5 }}>{t('bm.move_to')}</div>
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                  {categories
                    .filter((c) => c !== contextMenu.bm.category)
                    .map((cat) => (
                      <div
                        key={cat}
                        style={ctxItemStyle}
                        onMouseEnter={ctxHighlight}
                        onMouseLeave={ctxUnhighlight}
                        onClick={() => {
                          if (contextMenu.bm.id) {
                            onBookmarkEdit(contextMenu.bm.id, { category: cat });
                          }
                          setContextMenu(null);
                        }}
                      >
                        <div
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            background: resolveColor(cat),
                            marginRight: 6,
                          }}
                        />
                        {displayCat(cat)}
                      </div>
                    ))}
                </div>
              </>
            )}
          </div>
        </>,
        document.body,
        );
      })()}

      {/* Edit dialog — name + lat + lng */}
      {editDialog && createPortal(
        <div
          onClick={() => setEditDialog(null)}
          className="anim-fade-in"
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(8, 10, 20, 0.55)',
            backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
            zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            onContextMenu={(e) => e.stopPropagation()}
            className="anim-scale-in"
            style={{
              background: 'rgba(26, 29, 39, 0.96)',
              backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
              border: '1px solid rgba(108, 140, 255, 0.2)',
              borderRadius: 12, padding: 18, width: 320, color: '#e0e0e0',
              boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
              {t('bm.edit')}
            </div>
            <input
              type="text"
              className="search-input"
              placeholder={t('bm.name_placeholder')}
              value={editDialogName}
              autoFocus
              onChange={(e) => setEditDialogName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditDialog(null);
              }}
              style={{ width: '100%', marginBottom: 8 }}
            />
            {/* Single 'lat, lng' field — paste or type the whole pair here.
                The trySplitLatLng helper also accepts tab/space separators. */}
            <input
              type="text"
              className="search-input"
              inputMode="decimal"
              placeholder={t('bm.latlng_single_placeholder')}
              value={
                editDialogLat && editDialogLng
                  ? `${editDialogLat}, ${editDialogLng}`
                  : editDialogLat || editDialogLng
              }
              onChange={(e) => {
                const v = e.target.value;
                const split = trySplitLatLng(v);
                if (split) { setEditDialogLat(split[0]); setEditDialogLng(split[1]); }
                else {
                  // User is still typing the lat part; keep raw text in lat
                  // and clear lng until a valid pair is detected.
                  setEditDialogLat(v);
                  setEditDialogLng('');
                }
              }}
              style={{ width: '100%', marginBottom: 12 }}
            />
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                className="action-btn primary"
                style={{ flex: 1 }}
                disabled={
                  !editDialogName.trim() ||
                  !Number.isFinite(parseFloat(editDialogLat)) ||
                  !Number.isFinite(parseFloat(editDialogLng))
                }
                onClick={() => {
                  const lat = parseFloat(editDialogLat);
                  const lng = parseFloat(editDialogLng);
                  if (!editDialog.id) { setEditDialog(null); return; }
                  if (!Number.isFinite(lat) || lat < -90 || lat > 90) return;
                  if (!Number.isFinite(lng) || lng < -180 || lng > 180) return;
                  // Backend PUT requires the full Bookmark shape, so merge
                  // the edits over the original to keep category + address.
                  onBookmarkEdit(editDialog.id, {
                    ...editDialog,
                    name: editDialogName.trim(),
                    lat, lng,
                  });
                  setEditDialog(null);
                }}
              >{t('generic.save')}</button>
              <button className="action-btn" onClick={() => setEditDialog(null)}>
                {t('generic.cancel')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {showCustomDialog && createPortal(
        <div
          onClick={() => setShowCustomDialog(false)}
          className="anim-fade-in"
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(8, 10, 20, 0.55)',
            backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
            zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="anim-scale-in"
            style={{
              background: 'rgba(26, 29, 39, 0.96)',
              backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
              border: '1px solid rgba(108, 140, 255, 0.2)',
              borderRadius: 12, padding: 18, width: 320, color: '#e0e0e0',
              boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
              {t('bm.add_custom')}
            </div>
            <input
              type="text"
              className="search-input"
              placeholder={t('bm.name_placeholder')}
              value={customName}
              autoFocus
              onChange={(e) => setCustomName(e.target.value)}
              onKeyDown={(e) => {
                if (isSubmitEnter(e)) handleAddCustom();
                if (e.key === 'Escape') setShowCustomDialog(false);
              }}
              style={{ width: '100%', marginBottom: 8 }}
            />
            {/* Single 'lat, lng' field. Paste or type the whole pair. */}
            <input
              type="text"
              className="search-input"
              inputMode="decimal"
              placeholder={t('bm.latlng_single_placeholder')}
              value={
                customLat && customLng
                  ? `${customLat}, ${customLng}`
                  : customLat || customLng
              }
              onChange={(e) => {
                const v = e.target.value;
                const split = trySplitLatLng(v);
                if (split) { setCustomLat(split[0]); setCustomLng(split[1]); }
                else { setCustomLat(v); setCustomLng(''); }
              }}
              style={{ width: '100%', marginBottom: 8 }}
            />
            <select
              value={customCategory}
              onChange={(e) => setCustomCategory(e.target.value)}
              style={{
                width: '100%', marginBottom: 12, padding: '6px 8px',
                background: '#1e1e22', color: '#e0e0e0', border: '1px solid #444',
                borderRadius: 4, fontSize: 12,
              }}
            >
              {categories.map((c) => (
                <option key={c} value={c}>{displayCat(c)}</option>
              ))}
            </select>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                className="action-btn primary"
                style={{ flex: 1 }}
                disabled={
                  !customName.trim() ||
                  !Number.isFinite(parseFloat(customLat)) ||
                  !Number.isFinite(parseFloat(customLng))
                }
                onClick={handleAddCustom}
              >{t('generic.add')}</button>
              <button className="action-btn" onClick={() => setShowCustomDialog(false)}>
                {t('generic.cancel')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};

const ctxItemStyle: React.CSSProperties = {
  padding: '6px 12px',
  cursor: 'pointer',
  fontSize: 12,
  display: 'flex',
  alignItems: 'center',
  color: '#e0e0e0',
  transition: 'background 0.15s',
};

function ctxHighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}
function ctxUnhighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}

interface DropdownProps {
  category: string
  bookmarkCount: number
  onSoftDelete: () => void
  onCascadeDelete?: () => void
}

const CategoryDeleteDropdown: React.FC<DropdownProps> = ({
  category, bookmarkCount, onSoftDelete, onCascadeDelete,
}) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onOutside)
    return () => document.removeEventListener('pointerdown', onOutside)
  }, [open])

  const confirmCascade = () => {
    if (!onCascadeDelete) return
    const msg = t('bm.delete.cascade_body').replace('{n}', String(bookmarkCount))
    if (window.confirm(`${t('bm.delete.cascade_title').replace('{name}', category)}\n\n${msg}`)) {
      onCascadeDelete()
    }
  }

  const confirmSoft = () => {
    const msg = t('bm.delete.soft_body').replace('{n}', String(bookmarkCount))
    if (window.confirm(`${t('bm.delete.soft_title').replace('{name}', category)}\n\n${msg}`)) {
      onSoftDelete()
    }
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none', border: 'none',
          color: '#f44336', cursor: 'pointer',
          padding: '2px 4px', fontSize: 11,
        }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="3,6 5,6 21,6" />
          <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
        </svg>
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%', right: 0, zIndex: 50,
            background: '#2a2a2e',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 6,
            padding: '4px 0',
            minWidth: 240,
            boxShadow: '0 6px 18px rgba(0,0,0,0.5)',
          }}
        >
          <div
            onClick={() => { setOpen(false); confirmSoft() }}
            style={{ padding: '6px 12px', fontSize: 11, cursor: 'pointer' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
          >
            {t('bm.delete.softdelete_label')}
          </div>
          {onCascadeDelete && (
            <div
              onClick={() => { setOpen(false); confirmCascade() }}
              style={{
                padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                color: '#ff6b6b',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              {t('bm.delete.cascade_label').replace('{n}', String(bookmarkCount))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default BookmarkList;
