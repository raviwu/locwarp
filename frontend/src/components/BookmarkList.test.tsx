import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  within,
  waitFor,
  act,
} from '@testing-library/react';

// i18n -> identity translator + a fixed language so the real BookmarkGeoLine
// child (rendered, not mocked) can mount. Mirrors ControlPanel.test.tsx +
// BookmarkGeoLine.test.tsx patterns.
// t(key, vars) encodes vars into the returned string (rather than dropping
// them, as a plain identity fn would) so tests that need to see an
// interpolated count (e.g. the catalog refresh confirm dialog) can assert on
// it without pulling in the real STRINGS table.
vi.mock('../i18n', () => ({
  useT: () => (key: string, vars?: Record<string, unknown>) =>
    vars ? `${key}::${JSON.stringify(vars)}` : key,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
}));

// Backend ports. getBookmarkUiState / setBookmarkUiState are now injected via
// useServices().api (the DI mechanism for those two calls moved into the
// useBookmarkUiState hook); reverseGeocode is still DIRECT-imported by
// BookmarkList, so the module mock below remains. The SAME spies are wired
// into the ServicesProvider's api value so tests 2 + 3 keep firing on them.
// getBookmarkUiState defaults to an empty persisted state; reverseGeocode
// resolves a fake address. Tests override per-case via mockResolvedValueOnce /
// mockImplementationOnce.
const getBookmarkUiState = vi.fn();
const setBookmarkUiState = vi.fn();
const reverseGeocode = vi.fn();
vi.mock('../services/api', () => ({
  getBookmarkUiState: (...a: any[]) => getBookmarkUiState(...a),
  setBookmarkUiState: (...a: any[]) => setBookmarkUiState(...a),
  reverseGeocode: (...a: any[]) => reverseGeocode(...a),
}));

import BookmarkList from './BookmarkList';
import { ServicesProvider } from '../contexts/ServicesContext';
import { createWsRouter } from '../adapters/ws/router';

// Inject the same ui-state spies through useServices().api so the hook's two
// backend calls route to them, while reverseGeocode stays on the module mock.
function renderWithServices(ui: React.ReactElement) {
  const api = {
    getBookmarkUiState: (...a: any[]) => getBookmarkUiState(...a),
    setBookmarkUiState: (...a: any[]) => setBookmarkUiState(...a),
    reverseGeocode: (...a: any[]) => reverseGeocode(...a),
  } as any;
  return render(
    <ServicesProvider
      value={{ api, ws: createWsRouter(), sendMessage: vi.fn(), connected: true }}
    >
      {ui}
    </ServicesProvider>,
  );
}

type Bm = {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  country_code?: string;
  timezone?: string;
  city?: string;
  region?: string;
};

// Build N bookmarks spread across the given categories (round-robin).
function makeBookmarks(n: number, categories: string[]): Bm[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `bm-${i}`,
    name: `Place ${i}`,
    lat: 25 + i * 0.01,
    lng: 121 + i * 0.01,
    category: categories[i % categories.length],
  }));
}

function makeProps(over: Partial<Record<string, any>> = {}) {
  const categories = (over.categories as string[]) ?? ['Default', 'Work'];
  return {
    bookmarks: makeBookmarks(4, categories),
    categories,
    categoryColors: {},
    currentPosition: { lat: 25, lng: 121 },
    onBookmarkClick: vi.fn(),
    onTeleport: vi.fn(),
    onNavigate: vi.fn(),
    onSetAsGoldDittoA: vi.fn(),
    onAddWaypoint: vi.fn(),
    deviceConnected: true,
    showWaypointOption: false,
    onShowToast: vi.fn(),
    onBookmarkAdd: vi.fn(),
    onBookmarkDelete: vi.fn(),
    onBookmarkEdit: vi.fn(),
    onCategoryAdd: vi.fn(),
    onCategoryDelete: vi.fn(),
    onCategoryDeleteCascade: vi.fn(),
    onCategoryEdit: vi.fn(),
    categoryDates: {},
    showOnMap: false,
    onShowOnMapChange: vi.fn(),
    onImport: undefined,
    onBulkPaste: undefined,
    onExportClick: undefined,
    catalogStatus: undefined,
    catalogNewCount: undefined,
    catalogOverwriteCount: undefined,
    catalogError: undefined,
    catalogRefreshing: undefined,
    onCatalogRefresh: undefined,
    ...over,
  } as any;
}

// The grouped list renders a chevron header per category; its expanded body
// follows. Returns true when the category whose header text === `cat` is
// expanded (chevron rotated 90deg => collapsed[cat] is false).
function isCategoryExpanded(cat: string): boolean {
  const headers = Array.from(
    document.querySelectorAll('.bookmark-group'),
  ) as HTMLElement[];
  for (const group of headers) {
    const label = group.querySelector('span');
    if (label && label.textContent === cat) {
      const chevron = group.querySelector('svg[style*="rotate"]') as
        | SVGElement
        | null;
      // rotate(90deg) === expanded, rotate(0deg) === collapsed.
      const transform = chevron?.getAttribute('style') ?? '';
      return transform.includes('rotate(90deg)');
    }
  }
  throw new Error(`category header not found: ${cat}`);
}

beforeEach(() => {
  getBookmarkUiState.mockReset();
  setBookmarkUiState.mockReset();
  reverseGeocode.mockReset();
  // Default: nothing persisted yet (expanded_categories null => "all expanded
  // when under threshold" rule). hidden_categories null => nothing hidden.
  getBookmarkUiState.mockResolvedValue({
    expanded_categories: null,
    hidden_categories: null,
  });
  setBookmarkUiState.mockResolvedValue({
    status: 'ok',
    expanded_categories: null,
    hidden_categories: null,
  });
  reverseGeocode.mockResolvedValue({ display_name: 'Fake Address, Test City' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('BookmarkList characterization', () => {
  // ---------------------------------------------------------------------------
  // 1. AUTO_COLLAPSE_THRESHOLD = 30
  //    > 30 bookmarks => every category collapses; <= 30 => expanded (when no
  //    saved snapshot and no event dates that force a default collapse).
  // ---------------------------------------------------------------------------
  it('auto-collapses all categories when bookmark count > 30, keeps them expanded at <= 30', async () => {
    const categories = ['Default', 'Work', 'Trips'];

    // 31 bookmarks => over the threshold => all collapsed.
    const over = renderWithServices(
      <BookmarkList
        {...makeProps({
          categories,
          bookmarks: makeBookmarks(31, categories),
        })}
      />,
    );
    // The collapse effect runs after the ui-state fetch resolves.
    await waitFor(() => {
      expect(isCategoryExpanded('Default')).toBe(false);
    });
    expect(isCategoryExpanded('Work')).toBe(false);
    expect(isCategoryExpanded('Trips')).toBe(false);
    over.unmount();

    // 30 bookmarks => exactly AT the threshold => NOT over => expanded.
    renderWithServices(
      <BookmarkList
        {...makeProps({
          categories,
          bookmarks: makeBookmarks(30, categories),
        })}
      />,
    );
    await waitFor(() => {
      expect(isCategoryExpanded('Default')).toBe(true);
    });
    expect(isCategoryExpanded('Work')).toBe(true);
    expect(isCategoryExpanded('Trips')).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // 2. Hidden-categories persist as a PARTIAL POST, and the initial
  //    getBookmarkUiState load is NOT echoed back as a write (load gate).
  // ---------------------------------------------------------------------------
  it('persists hidden categories as a partial POST (no expanded_categories key) and does not echo the initial fetch', async () => {
    renderWithServices(<BookmarkList {...makeProps({ categories: ['Default', 'Work'] })} />);

    // Wait for the initial ui-state fetch to complete (gates the persist
    // effects). After load, NO write should have happened yet.
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    expect(setBookmarkUiState).not.toHaveBeenCalled();

    // Click the hide (eye-off) button on the "Work" category header.
    const workGroup = Array.from(
      document.querySelectorAll('.bookmark-group'),
    ).find((g) => g.querySelector('span')?.textContent === 'Work') as HTMLElement;
    const hideBtn = within(workGroup).getByTitle('bm.hide_category');
    fireEvent.click(hideBtn);

    await waitFor(() => expect(setBookmarkUiState).toHaveBeenCalledTimes(1));
    const body = setBookmarkUiState.mock.calls[0][0];
    expect(body).toEqual({ hidden_categories: ['Work'] });
    // Partial POST: it must NOT carry expanded_categories.
    expect(body).not.toHaveProperty('expanded_categories');
  });

  // ---------------------------------------------------------------------------
  // 3. Expanded-state persist is debounced (~400ms) into ONE POST carrying
  //    { expanded_categories }.
  // ---------------------------------------------------------------------------
  it('debounces expanded-state persistence into a single setBookmarkUiState({expanded_categories}) call', async () => {
    // Fetch resolves synchronously (already-resolved promise) but the effect
    // chain still needs a flush; use real timers for the await, then fake
    // timers for the debounce window.
    renderWithServices(<BookmarkList {...makeProps({ categories: ['Default', 'Work'] })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(isCategoryExpanded('Default')).toBe(true));
    expect(setBookmarkUiState).not.toHaveBeenCalled();

    vi.useFakeTimers();

    // Collapse "Default" then "Work" in quick succession (two flips).
    const groups = Array.from(
      document.querySelectorAll('.bookmark-group'),
    ) as HTMLElement[];
    const headerOf = (cat: string) =>
      groups.find((g) => g.querySelector('span')?.textContent === cat)!
        .firstElementChild as HTMLElement;
    fireEvent.click(headerOf('Default'));
    fireEvent.click(headerOf('Work'));

    // Before the debounce window elapses: no POST.
    act(() => {
      vi.advanceTimersByTime(399);
    });
    expect(setBookmarkUiState).not.toHaveBeenCalled();

    // Cross the 400ms boundary: exactly one POST, carrying expanded_categories.
    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(setBookmarkUiState).toHaveBeenCalledTimes(1);
    const body = setBookmarkUiState.mock.calls[0][0];
    expect(body).toHaveProperty('expanded_categories');
    expect(Array.isArray(body.expanded_categories)).toBe(true);
    // Both categories were collapsed, so neither is in the expanded list.
    expect(body.expanded_categories).toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // 4. Context-menu reverse-geocode stale-guard: a result that resolves AFTER
  //    the menu closed must be dropped (never shown).
  // ---------------------------------------------------------------------------
  it('drops a reverse-geocode result that resolves after the context menu closed (stale-guard)', async () => {
    // Make reverseGeocode resolve on a manually-controlled deferred so we can
    // close the menu before it resolves.
    let resolveGeo!: (v: any) => void;
    reverseGeocode.mockImplementationOnce(
      () => new Promise((res) => { resolveGeo = res; }),
    );

    renderWithServices(<BookmarkList {...makeProps({ categories: ['Default', 'Work'] })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(isCategoryExpanded('Default')).toBe(true));

    // Right-click the first bookmark row to open the context menu.
    const row = screen.getAllByText('Place 0')[0].closest('.bookmark-item')!;
    fireEvent.contextMenu(row);

    // The coords header row carries the "what's here" affordance — click it to
    // trigger reverseGeocode.
    const header = await screen.findByText('map.whats_here');
    fireEvent.click(header.parentElement as HTMLElement);
    expect(reverseGeocode).toHaveBeenCalledTimes(1);

    // Close the menu (ESC) BEFORE the geocode resolves.
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() =>
      expect(screen.queryByText('map.whats_here')).toBeNull(),
    );

    // Now resolve the late geocode. The stale-guard (contextMenuRef snapshot)
    // must drop it — the address must never appear.
    await act(async () => {
      resolveGeo({ display_name: 'Late Stale Address' });
      await Promise.resolve();
    });
    expect(screen.queryByText('Late Stale Address')).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // 5. Multi-select batch delete: enable multi-select -> select all -> delete
  //    -> window.confirm fires, then onBookmarkDelete called once per id.
  // ---------------------------------------------------------------------------
  it('batch-deletes all selected bookmarks after a single confirm', async () => {
    const onBookmarkDelete = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(4, categories); // ids bm-0..bm-3
    const confirmSpy = vi
      .spyOn(window, 'confirm')
      .mockReturnValue(true);

    renderWithServices(
      <BookmarkList
        {...makeProps({ categories, bookmarks, onBookmarkDelete })}
      />,
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    // Enable multi-select via its toolbar button (title carries the i18n key).
    fireEvent.click(screen.getByTitle('bm.multi_select_tooltip'));

    // Select-all button appears in the sticky footer.
    fireEvent.click(screen.getByText('bm.select_all'));

    // Delete-selected button text interpolates the count: "bm.delete_selected"
    // with {n} replaced by 4.
    const deleteBtn = screen.getByText((txt) =>
      txt.startsWith('bm.delete_selected'),
    );
    await act(async () => {
      fireEvent.click(deleteBtn);
    });

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onBookmarkDelete).toHaveBeenCalledTimes(4);
    const deletedIds = onBookmarkDelete.mock.calls.map((c) => c[0]).sort();
    expect(deletedIds).toEqual(['bm-0', 'bm-1', 'bm-2', 'bm-3']);

    confirmSpy.mockRestore();
  });

  it('does not delete when the confirm is dismissed', async () => {
    const onBookmarkDelete = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(4, categories);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderWithServices(
      <BookmarkList
        {...makeProps({ categories, bookmarks, onBookmarkDelete })}
      />,
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTitle('bm.multi_select_tooltip'));
    fireEvent.click(screen.getByText('bm.select_all'));
    const deleteBtn = screen.getByText((txt) =>
      txt.startsWith('bm.delete_selected'),
    );
    await act(async () => {
      fireEvent.click(deleteBtn);
    });

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onBookmarkDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  // ---------------------------------------------------------------------------
  // 6. Search-vs-grouped row parity: the same bookmark's name must render
  //    identically in the flat search list and in the grouped list. This
  //    guards an upcoming de-duplication of the row markup.
  // ---------------------------------------------------------------------------
  it('renders the same bookmark name in the search list as in the grouped list', async () => {
    const categories = ['Default', 'Work'];
    const bookmarks: Bm[] = [
      { id: 'a', name: 'Alpha Cafe', lat: 25, lng: 121, category: 'Default' },
      { id: 'b', name: 'Beta Bar', lat: 26, lng: 122, category: 'Work' },
    ];
    renderWithServices(<BookmarkList {...makeProps({ categories, bookmarks })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(isCategoryExpanded('Default')).toBe(true));

    // Grouped (no search): capture the rendered name span text + the row's
    // title attribute for "Alpha Cafe".
    const groupedRow = screen
      .getByText('Alpha Cafe')
      .closest('.bookmark-item') as HTMLElement;
    const groupedNameText = within(groupedRow).getByText('Alpha Cafe')
      .textContent;

    // Type a query that filters down to exactly the one bookmark.
    const searchInput = screen.getByPlaceholderText('bm.search_placeholder');
    fireEvent.change(searchInput, { target: { value: 'Alpha' } });

    // The grouped list is replaced by the flat search list. Beta Bar is gone;
    // Alpha Cafe remains, rendered with the same name text.
    expect(screen.queryByText('Beta Bar')).toBeNull();
    const searchRow = screen
      .getByText('Alpha Cafe')
      .closest('.bookmark-item') as HTMLElement;
    const searchNameText = within(searchRow).getByText('Alpha Cafe')
      .textContent;

    expect(searchNameText).toBe(groupedNameText);
    expect(searchNameText).toBe('Alpha Cafe');
  });
});

describe('BookmarkList import busy state (U14)', () => {
  it('disables the import control while an import is in flight, re-enables after', async () => {
    let resolveImport!: () => void;
    const onImport = vi.fn(() => new Promise<void>((res) => { resolveImport = res; }));
    renderWithServices(<BookmarkList {...makeProps({ onImport })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    const label = screen.getByTitle('bm.import_tooltip');
    const input = label.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{}'], 'b.json', { type: 'application/json' });

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });
    // In-flight: control is marked busy (aria-disabled) and shows the busy label.
    expect(label).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('bm.import_busy')).toBeTruthy();
    expect(onImport).toHaveBeenCalledTimes(1);

    await act(async () => { resolveImport(); await Promise.resolve(); });
    // Settled: no longer busy.
    expect(label).toHaveAttribute('aria-disabled', 'false');
  });
});

describe('BookmarkList left-click teleport gating + feedback (U16/U17)', () => {
  afterEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

  it('with a device connected + flyGps on, left-click teleports AND toasts that GPS moved', async () => {
    const onTeleport = vi.fn();
    const onShowToast = vi.fn();
    renderWithServices(
      <BookmarkList {...makeProps({ deviceConnected: true, onTeleport, onShowToast })} />,
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('Place 0'));
    expect(onTeleport).toHaveBeenCalledWith(25, 121);
    expect(onShowToast).toHaveBeenCalledWith('bm.click_moves_gps');
  });

  it('with NO device connected, left-click does NOT teleport and shows a no-device toast', async () => {
    const onTeleport = vi.fn();
    const onBookmarkClick = vi.fn();
    const onShowToast = vi.fn();
    renderWithServices(
      <BookmarkList
        {...makeProps({ deviceConnected: false, onTeleport, onBookmarkClick, onShowToast })}
      />,
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('Place 0'));
    expect(onTeleport).not.toHaveBeenCalled();
    // Falls back to map-pan (preview) instead of a fake teleport.
    expect(onBookmarkClick).toHaveBeenCalled();
    expect(onShowToast).toHaveBeenCalledWith('bm.click_no_device');
  });
});

describe('BookmarkList country filter', () => {
  // Self-contained wrapper so we can rerender with new props (the shared
  // renderWithServices does not expose the wrapper for rerender).
  function wrapped(props: any) {
    const api = {
      getBookmarkUiState: (...a: any[]) => getBookmarkUiState(...a),
      setBookmarkUiState: (...a: any[]) => setBookmarkUiState(...a),
      reverseGeocode: (...a: any[]) => reverseGeocode(...a),
    } as any;
    return (
      <ServicesProvider value={{ api, ws: createWsRouter(), sendMessage: vi.fn(), connected: true }}>
        <BookmarkList {...props} />
      </ServicesProvider>
    );
  }

  // jp x3 (Tokyo, Osaka in Trips; Kyoto in Work), tw x1 (Taipei in Trips).
  const GEO = [
    { id: 'b1', name: 'Tokyo',  lat: 35, lng: 139, category: 'Trips', country_code: 'jp' },
    { id: 'b2', name: 'Osaka',  lat: 34, lng: 135, category: 'Trips', country_code: 'jp' },
    { id: 'b3', name: 'Kyoto',  lat: 35, lng: 135, category: 'Work',  country_code: 'jp' },
    { id: 'b4', name: 'Taipei', lat: 25, lng: 121, category: 'Trips', country_code: 'tw' },
  ];
  const CATS = ['Trips', 'Work'];

  // Visible category header labels (mirrors the existing isCategoryExpanded
  // helper: each .bookmark-group's first <span> is the category name).
  function visibleCategories(): string[] {
    return Array.from(document.querySelectorAll('.bookmark-group'))
      .map((g) => g.querySelector('span')?.textContent ?? '');
  }

  it('renders an All + per-country dropdown when >= 2 countries exist', async () => {
    render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');
    const select = screen.getByLabelText('bm.country_label') as HTMLSelectElement;
    const opts = Array.from(select.options);
    // Value order is deterministic (Japan/Taiwan or JP/TW both sort j < t);
    // assert values + counts rather than ICU display names to stay robust.
    expect(opts.map((o) => o.value)).toEqual(['', 'jp', 'tw']);
    expect(opts[0].textContent).toBe('bm.country_all');
    expect(opts.find((o) => o.value === 'jp')!.textContent).toMatch(/\(3\)$/);
    expect(opts.find((o) => o.value === 'tw')!.textContent).toMatch(/\(1\)$/);
  });

  it('does NOT render the dropdown when fewer than 2 countries exist', async () => {
    const oneCountry = GEO.filter((b) => b.country_code === 'jp');
    render(wrapped(makeProps({ bookmarks: oneCountry, categories: CATS })));
    await screen.findByText('Tokyo');
    expect(screen.queryByLabelText('bm.country_label')).toBeNull();
  });

  it('narrows the grouped view to the selected country and hides empty groups', async () => {
    render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');
    expect(visibleCategories().sort()).toEqual(['Trips', 'Work']);

    const select = screen.getByLabelText('bm.country_label');
    fireEvent.change(select, { target: { value: 'tw' } });

    // tw has only Taipei (Trips). Work has no tw bookmark => hidden.
    expect(screen.getByText('Taipei')).toBeInTheDocument();
    expect(screen.queryByText('Tokyo')).toBeNull();
    expect(visibleCategories()).toEqual(['Trips']);
  });

  it('narrows search results to the selected country', async () => {
    render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');

    fireEvent.change(screen.getByLabelText('bm.country_label'), { target: { value: 'tw' } });
    fireEvent.change(screen.getByPlaceholderText('bm.search_placeholder'), { target: { value: 'a' } });

    // 'a' matches Osaka (jp) and Taipei (tw); the country filter narrows the
    // search base to tw, so only Taipei survives.
    expect(screen.getByText('Taipei')).toBeInTheDocument();
    expect(screen.queryByText('Osaka')).toBeNull();
  });

  it('falls back to All when the selected country no longer exists', async () => {
    const { rerender } = render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');
    fireEvent.change(screen.getByLabelText('bm.country_label'), { target: { value: 'tw' } });
    expect(screen.queryByText('Tokyo')).toBeNull();

    // tw bookmark removed -> only jp left. Stale 'tw' filter must fall back to
    // All (effectiveCountry === ''), so every jp bookmark is visible again.
    const jpOnly = GEO.filter((b) => b.country_code === 'jp');
    rerender(wrapped(makeProps({ bookmarks: jpOnly, categories: CATS })));
    await screen.findByText('Tokyo');
    expect(screen.getByText('Osaka')).toBeInTheDocument();
    expect(screen.getByText('Kyoto')).toBeInTheDocument();
  });
});

describe('BookmarkList custom-coordinate dialog state lifetime', () => {
  // Abandoning the 自訂座標 dialog used to leave customName / customLat /
  // customLng in BookmarkList state — they were cleared only on a successful
  // submit. Reopening the dialog for a DIFFERENT place then showed the old
  // coordinate pre-filled, and because the Add button only checks that lat/lng
  // parse, a fresh name could be saved against the previous place's point.
  function openCustomDialog() {
    fireEvent.click(screen.getByTitle('bm.add_custom_tooltip'));
  }

  function coordField() {
    return screen.getByPlaceholderText(
      'bm.latlng_single_placeholder',
    ) as HTMLInputElement;
  }

  function nameField() {
    return screen.getByPlaceholderText(
      'bm.name_placeholder',
    ) as HTMLInputElement;
  }

  it('clears name and coordinate when the dialog is reopened after a cancel', () => {
    renderWithServices(<BookmarkList {...makeProps()} />);

    openCustomDialog();
    fireEvent.change(nameField(), { target: { value: 'Place A' } });
    fireEvent.change(coordField(), { target: { value: '24.1477, 120.6736' } });
    fireEvent.click(screen.getByText('generic.cancel'));

    openCustomDialog();
    expect(nameField().value).toBe('');
    expect(coordField().value).toBe('');
  });

  it('does not save the previous place\'s coordinate under a new name', () => {
    const onBookmarkAdd = vi.fn();
    renderWithServices(<BookmarkList {...makeProps({ onBookmarkAdd })} />);

    openCustomDialog();
    fireEvent.change(nameField(), { target: { value: 'Place A' } });
    fireEvent.change(coordField(), { target: { value: '24.1477, 120.6736' } });
    fireEvent.click(screen.getByText('generic.cancel'));

    // Second add: only a name is typed. With the stale coordinate gone the Add
    // button must stay disabled instead of silently persisting Place A's point.
    openCustomDialog();
    fireEvent.change(nameField(), { target: { value: 'Place B' } });
    const add = screen.getByText('generic.add') as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    fireEvent.click(add);
    expect(onBookmarkAdd).not.toHaveBeenCalled();
  });
});

describe('BookmarkList edit dialog — live values for untouched fields (bookmark-revert fix)', () => {
  // Self-contained wrapper so we can rerender with mutated `bookmarks` props
  // to simulate a concurrent iCloud-synced edit landing while the edit
  // dialog is open (mirrors the `wrapped` helper in the country-filter suite
  // above, which is scoped to its own describe block).
  function wrapped(props: any) {
    const api = {
      getBookmarkUiState: (...a: any[]) => getBookmarkUiState(...a),
      setBookmarkUiState: (...a: any[]) => setBookmarkUiState(...a),
      reverseGeocode: (...a: any[]) => reverseGeocode(...a),
    } as any;
    return (
      <ServicesProvider value={{ api, ws: createWsRouter(), sendMessage: vi.fn(), connected: true }}>
        <BookmarkList {...props} />
      </ServicesProvider>
    );
  }

  function openEditDialogFor(name: string) {
    const row = screen.getAllByText(name)[0].closest('.bookmark-item')!;
    fireEvent.contextMenu(row);
    fireEvent.click(screen.getByText('bm.edit'));
  }

  function coordField() {
    return screen.getByPlaceholderText(
      'bm.latlng_single_placeholder',
    ) as HTMLInputElement;
  }

  it('submits the LIVE name (not the one captured at open time) when only coordinates were edited', async () => {
    const onBookmarkEdit = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(2, categories); // bm-0 'Place 0', bm-1 'Place 1'
    const { rerender } = render(
      wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })),
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    // Open the Edit dialog for bm-0 while its live name is still 'Place 0'.
    openEditDialogFor('Place 0');
    expect(screen.getByDisplayValue('Place 0')).toBeInTheDocument();

    // The bookmark is renamed on the OTHER Mac and synced in — the bookmarks
    // prop underneath the still-open dialog changes.
    const renamed = bookmarks.map((b) =>
      b.id === 'bm-0' ? { ...b, name: 'Renamed On Other Mac' } : b,
    );
    rerender(wrapped(makeProps({ categories, bookmarks: renamed, onBookmarkEdit })));

    // Edit ONLY the coordinates in this dialog session — never touch name.
    fireEvent.change(coordField(), { target: { value: '25.5, 121.5' } });
    fireEvent.click(screen.getByText('generic.save'));

    expect(onBookmarkEdit).toHaveBeenCalledTimes(1);
    const [id, patch] = onBookmarkEdit.mock.calls[0];
    expect(id).toBe('bm-0');
    // The live name wins — the dialog never re-submits the name it captured
    // at open time.
    expect(patch.name).toBe('Renamed On Other Mac');
    expect(patch.lat).toBe(25.5);
    expect(patch.lng).toBe(121.5);
  });

  it('submits the typed name when the user DID edit it, even if the live record changed too', async () => {
    const onBookmarkEdit = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(2, categories);
    const { rerender } = render(
      wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })),
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    openEditDialogFor('Place 0');

    const renamed = bookmarks.map((b) =>
      b.id === 'bm-0' ? { ...b, name: 'Renamed On Other Mac' } : b,
    );
    rerender(wrapped(makeProps({ categories, bookmarks: renamed, onBookmarkEdit })));

    // The user DOES edit the name field in this session — their typed value
    // must win over both the stale open-time snapshot and the concurrent
    // live rename.
    fireEvent.change(screen.getByPlaceholderText('bm.name_placeholder'), {
      target: { value: 'User Typed Name' },
    });
    fireEvent.click(screen.getByText('generic.save'));

    expect(onBookmarkEdit).toHaveBeenCalledTimes(1);
    const [id, patch] = onBookmarkEdit.mock.calls[0];
    expect(id).toBe('bm-0');
    expect(patch.name).toBe('User Typed Name');
  });

  it('closes the dialog without submitting when the record is deleted elsewhere while open', async () => {
    const onBookmarkEdit = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(2, categories);
    const { rerender } = render(
      wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })),
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    openEditDialogFor('Place 0');
    expect(screen.getByText('bm.edit')).toBeInTheDocument();

    // bm-0 is deleted on the other Mac and the deletion syncs in.
    const withoutBm0 = bookmarks.filter((b) => b.id !== 'bm-0');
    rerender(wrapped(makeProps({ categories, bookmarks: withoutBm0, onBookmarkEdit })));

    await waitFor(() =>
      expect(screen.queryByPlaceholderText('bm.name_placeholder')).toBeNull(),
    );
    expect(onBookmarkEdit).not.toHaveBeenCalled();
  });

  // ---------------------------------------------------------------------------
  // C2: the vanished-record effect must actually clear editDialogId, not just
  // let EditBookmarkDialog render null while a stale id lingers in state. The
  // test above can't tell the two apart (both make the dialog disappear when
  // the record vanishes) — this one re-adds the record and asserts the
  // dialog stays closed, which only holds if editDialogId was truly dropped.
  // ---------------------------------------------------------------------------
  it('drops the stale id when its record vanishes, so the dialog does not silently reopen if the id reappears', async () => {
    const onBookmarkEdit = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(2, categories);
    const { rerender } = render(
      wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })),
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    openEditDialogFor('Place 0');
    expect(screen.getByPlaceholderText('bm.name_placeholder')).toBeInTheDocument();

    // bm-0 deleted elsewhere; the dialog disappears (as above).
    const withoutBm0 = bookmarks.filter((b) => b.id !== 'bm-0');
    rerender(wrapped(makeProps({ categories, bookmarks: withoutBm0, onBookmarkEdit })));
    await waitFor(() =>
      expect(screen.queryByPlaceholderText('bm.name_placeholder')).toBeNull(),
    );

    // bm-0 reappears with the SAME id (e.g. the delete/re-add raced, or a
    // later sync restored it). If editDialogId had merely been left stale
    // while the dialog rendered null off a live `bookmark == null` check,
    // it would resolve to the reappeared record here and the dialog would
    // silently pop back open with no user action. It must stay closed.
    rerender(wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })));
    await screen.findByText('Place 0');
    expect(screen.queryByPlaceholderText('bm.name_placeholder')).toBeNull();
    expect(onBookmarkEdit).not.toHaveBeenCalled();
  });

  // ---------------------------------------------------------------------------
  // C1: the per-field dirty flags must be reset on EVERY dialog open, not
  // just cleared once at mount. A leftover `nameDirty=true` from a prior
  // session (opened on a different bookmark, then cancelled without
  // submitting) must never survive into the next session and override that
  // session's live value.
  // ---------------------------------------------------------------------------
  it('does not leak a dirty flag from a cancelled session into the next dialog open', async () => {
    const onBookmarkEdit = vi.fn();
    const categories = ['Default', 'Work'];
    const bookmarks = makeBookmarks(2, categories); // bm-0 'Place 0', bm-1 'Place 1'
    const { rerender } = render(
      wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })),
    );
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    // Open bm-0's dialog, dirty its name field, then cancel without saving.
    openEditDialogFor('Place 0');
    fireEvent.change(screen.getByPlaceholderText('bm.name_placeholder'), {
      target: { value: 'Stale Name From Bm0 Session' },
    });
    fireEvent.click(screen.getByText('generic.cancel'));

    // Open bm-1's dialog. Never touch its name field this session.
    openEditDialogFor('Place 1');

    // bm-1 is renamed on the other Mac while THIS dialog is open.
    const renamed = bookmarks.map((b) =>
      b.id === 'bm-1' ? { ...b, name: 'Renamed Bm1 On Other Mac' } : b,
    );
    rerender(wrapped(makeProps({ categories, bookmarks: renamed, onBookmarkEdit })));

    // Edit ONLY coordinates in this session.
    fireEvent.change(coordField(), { target: { value: '30, 130' } });
    fireEvent.click(screen.getByText('generic.save'));

    expect(onBookmarkEdit).toHaveBeenCalledTimes(1);
    const [id, patch] = onBookmarkEdit.mock.calls[0];
    expect(id).toBe('bm-1');
    // If bm-0's leftover nameDirty had survived into this session, submit
    // would force `patch.name` from the local text captured at THIS dialog's
    // open time ('Place 1') instead of spreading bm-1's live current name —
    // masking the very rename this session is supposed to pick up.
    expect(patch.name).toBe('Renamed Bm1 On Other Mac');
    expect(patch.lat).toBe(30);
    expect(patch.lng).toBe(130);
  });

  // ---------------------------------------------------------------------------
  // C3: an id-less bookmark (the `id` field on this component's Bookmark
  // interface is optional) must not silently pop a dialog whose Save then
  // discards. In practice every bookmark reaching this list comes from the
  // backend GET response, which always stamps a real string id (possibly
  // "" for a hand-imported record missing one, but never `undefined`) — see
  // the comment at the onEdit call site. This pins that: Edit is a no-op
  // when `id` is genuinely absent from the object.
  // ---------------------------------------------------------------------------
  it('does not open the edit dialog for a bookmark with no id at all', async () => {
    const onBookmarkEdit = vi.fn();
    const categories = ['Default'];
    const bookmarks = [
      { name: 'No Id Place', lat: 1, lng: 2, category: 'Default' },
    ];
    render(wrapped(makeProps({ categories, bookmarks, onBookmarkEdit })));
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    openEditDialogFor('No Id Place');
    expect(screen.queryByPlaceholderText('bm.name_placeholder')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Catalog refresh confirm dialog (informed consent before force-sync). The
// Refresh button must open a confirm dialog showing both the new-entry count
// and the overwrite count instead of calling onCatalogRefresh directly; only
// Confirm calls it (exactly once), Cancel is a no-op.
// ---------------------------------------------------------------------------
describe('BookmarkList catalog refresh confirm dialog', () => {
  function catalogProps(over: Partial<Record<string, any>> = {}) {
    return makeProps({
      catalogStatus: 'ok',
      catalogNewCount: 3,
      catalogOverwriteCount: 2,
      onCatalogRefresh: vi.fn(),
      ...over,
    });
  }

  it('clicking Refresh opens the confirm dialog without calling the API', async () => {
    const onCatalogRefresh = vi.fn();
    renderWithServices(<BookmarkList {...catalogProps({ onCatalogRefresh })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByText(/bm\.catalog\.refresh_count/));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(onCatalogRefresh).not.toHaveBeenCalled();
  });

  it('shows both the new count and the overwrite count', async () => {
    renderWithServices(<BookmarkList {...catalogProps()} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText(/bm\.catalog\.refresh_count/));

    expect(screen.getByText('bm.catalog.confirm_added::{"n":3}')).toBeInTheDocument();
    expect(screen.getByText('bm.catalog.confirm_overwrite::{"n":2}')).toBeInTheDocument();
  });

  it('shows the reassuring no-overwrite variant when the overwrite count is 0', async () => {
    renderWithServices(<BookmarkList {...catalogProps({ catalogOverwriteCount: 0 })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText(/bm\.catalog\.refresh_count/));

    expect(screen.getByText('bm.catalog.confirm_no_overwrite')).toBeInTheDocument();
    expect(screen.queryByText(/bm\.catalog\.confirm_overwrite::/)).toBeNull();
  });

  it('Cancel closes the dialog and calls no API', async () => {
    const onCatalogRefresh = vi.fn();
    renderWithServices(<BookmarkList {...catalogProps({ onCatalogRefresh })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText(/bm\.catalog\.refresh_count/));
    fireEvent.click(screen.getByText('generic.cancel'));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onCatalogRefresh).not.toHaveBeenCalled();
  });

  it('Confirm calls the refresh path exactly once', async () => {
    const onCatalogRefresh = vi.fn();
    renderWithServices(<BookmarkList {...catalogProps({ onCatalogRefresh })} />);
    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText(/bm\.catalog\.refresh_count/));
    fireEvent.click(screen.getByText('bm.catalog.confirm_button'));

    expect(onCatalogRefresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
