import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';

// i18n is mocked to a fixed language so the real BookmarkGeoLine child mounts.
// Mirrors BookmarkGeoLine.test.tsx / BookmarkList.test.tsx.
vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
}));

import { BookmarkRow } from './BookmarkRow';

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

const baseBm: Bm = {
  id: 'a',
  name: 'Alpha Cafe',
  lat: 25,
  lng: 121,
  category: 'Work',
};

// Defaults that satisfy the prop contract; each test overrides what it asserts.
function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    bm: baseBm,
    isSelected: false,
    multiSelect: false,
    flashedBmId: null,
    toggleSelected: vi.fn(),
    onBookmarkClick: vi.fn(),
    onContextMenu: vi.fn(),
    showCategoryInTitle: false,
    showCategoryDot: false,
    showPinIcon: false,
    allowRename: false,
    resolveColor: (_: string) => '#abcdef',
    displayCat: (n: string) => n,
    ...over,
  } as any;
}

describe('BookmarkRow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the bookmark name span', () => {
    render(<BookmarkRow {...makeProps()} />);
    expect(screen.getByText('Alpha Cafe')).toBeTruthy();
  });

  it('fires onBookmarkClick with the bookmark when the row is clicked (single-select)', () => {
    const onBookmarkClick = vi.fn();
    render(<BookmarkRow {...makeProps({ onBookmarkClick })} />);
    fireEvent.click(screen.getByText('Alpha Cafe').closest('.bookmark-item')!);
    expect(onBookmarkClick).toHaveBeenCalledTimes(1);
    expect(onBookmarkClick).toHaveBeenCalledWith(baseBm);
  });

  // --- Title variant: search list INCLUDES the category, grouped OMITS it ----
  it('OMITS the category segment from the title when showCategoryInTitle is false (grouped variant)', () => {
    render(<BookmarkRow {...makeProps({ showCategoryInTitle: false })} />);
    const titled = screen.getByText('Alpha Cafe').closest('div[title]') as HTMLElement;
    const title = titled.getAttribute('title');
    expect(title).toBe('Alpha Cafe · 25.00000, 121.00000');
    expect(title).not.toContain('Work');
  });

  it('INCLUDES the category segment in the title when showCategoryInTitle is true (search variant)', () => {
    render(<BookmarkRow {...makeProps({ showCategoryInTitle: true })} />);
    const titled = screen.getByText('Alpha Cafe').closest('div[title]') as HTMLElement;
    const title = titled.getAttribute('title');
    expect(title).toBe('Alpha Cafe · Work · 25.00000, 121.00000');
    expect(title).toContain('Work');
  });

  it('appends the region segment to the title when present (both variants)', () => {
    render(
      <BookmarkRow
        {...makeProps({ showCategoryInTitle: true, bm: { ...baseBm, region: 'Tokyo' } })}
      />,
    );
    const titled = screen.getByText('Alpha Cafe').closest('div[title]') as HTMLElement;
    expect(titled.getAttribute('title')).toBe(
      'Alpha Cafe · Work · 25.00000, 121.00000 · Tokyo',
    );
  });

  // --- Rename input: grouped variant only, gated on editingId match ----------
  it('renders the inline rename input only when allowRename and editingId matches', () => {
    const { rerender, container } = render(
      <BookmarkRow {...makeProps({ allowRename: true, editingId: 'a', editName: 'Alpha Cafe' })} />,
    );
    expect(container.querySelector('input.search-input')).not.toBeNull();
    // Editing replaces the name span entirely.
    expect(screen.queryByText('Alpha Cafe')).toBeNull();

    // editingId points at a different row => no rename input, name span shown.
    rerender(
      <BookmarkRow {...makeProps({ allowRename: true, editingId: 'other', editName: 'x' })} />,
    );
    expect(container.querySelector('input.search-input')).toBeNull();
    expect(screen.getByText('Alpha Cafe')).toBeTruthy();
  });

  it('never renders the rename input when allowRename is false even if editingId matches (search variant)', () => {
    const { container } = render(
      <BookmarkRow
        {...makeProps({ allowRename: false, editingId: 'a', editName: 'Alpha Cafe' })}
      />,
    );
    expect(container.querySelector('input.search-input')).toBeNull();
    expect(screen.getByText('Alpha Cafe')).toBeTruthy();
  });

  // --- Category dot vs pin icon: mutually-exclusive per variant --------------
  it('renders the category dot (with resolveColor) only when showCategoryDot is true', () => {
    const resolveColor = vi.fn(() => '#112233');
    const { container } = render(
      <BookmarkRow {...makeProps({ showCategoryDot: true, resolveColor })} />,
    );
    const dot = container.querySelector('div[title="Work"]') as HTMLElement;
    expect(dot).not.toBeNull();
    expect(resolveColor).toHaveBeenCalledWith('Work');
  });

  it('renders the bookmark-pin SVG only when showPinIcon is true', () => {
    const { container } = render(<BookmarkRow {...makeProps({ showPinIcon: true })} />);
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('omits both the dot and the pin when neither flag is set', () => {
    const { container } = render(<BookmarkRow {...makeProps()} />);
    expect(container.querySelector('div[title="Work"]')).toBeNull();
    expect(container.querySelector('svg path')).toBeNull();
  });

  // --- Multi-select: row click toggles selection instead of clicking ---------
  it('toggles selection (not onBookmarkClick) when clicked in multi-select mode', () => {
    const toggleSelected = vi.fn();
    const onBookmarkClick = vi.fn();
    render(
      <BookmarkRow
        {...makeProps({ multiSelect: true, toggleSelected, onBookmarkClick })}
      />,
    );
    fireEvent.click(screen.getByText('Alpha Cafe').closest('.bookmark-item')!);
    expect(toggleSelected).toHaveBeenCalledWith('a');
    expect(onBookmarkClick).not.toHaveBeenCalled();
  });

  it('renders the BookmarkGeoLine child (flag + geo text) when geo data is present', () => {
    render(
      <BookmarkRow
        {...makeProps({ bm: { ...baseBm, country_code: 'jp', city: 'Tokyo', timezone: 'Asia/Tokyo' } })}
      />,
    );
    const img = screen.getByRole('img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('https://flagcdn.com/w20/jp.png');
  });

  it('fires onContextMenu with the bookmark on right-click (single-select)', () => {
    const onContextMenu = vi.fn();
    render(<BookmarkRow {...makeProps({ onContextMenu })} />);
    fireEvent.contextMenu(screen.getByText('Alpha Cafe').closest('.bookmark-item')!);
    expect(onContextMenu).toHaveBeenCalledTimes(1);
    expect(onContextMenu.mock.calls[0][1]).toEqual(baseBm);
  });
});
