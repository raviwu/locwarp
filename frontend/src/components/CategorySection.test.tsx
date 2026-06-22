import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/react';

// i18n -> identity translator + a fixed language so the real BookmarkRow /
// BookmarkGeoLine children mount. Mirrors BookmarkRow.test.tsx / BookmarkList
// .test.tsx. Interpolation params (e.g. the upcoming-badge {date}) are appended
// so tests can assert the interpolated formatChipDate value flows through.
const fakeT = (k: string, params?: Record<string, unknown>) =>
  params ? `${k}:${Object.values(params).join(',')}` : k;
vi.mock('../i18n', () => ({
  useT: () => fakeT,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: fakeT }),
}));

import { CategorySection } from './CategorySection';

type Bm = {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
};

const bms: Bm[] = [
  { id: 'a', name: 'Alpha', lat: 25, lng: 121, category: 'Work' },
  { id: 'b', name: 'Beta', lat: 26, lng: 122, category: 'Work' },
];

// Defaults that satisfy the prop contract; each test overrides what it asserts.
function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    cat: 'Work',
    bms,
    collapsed: false,
    color: '#abcdef',
    status: 'evergreen' as const,
    dates: undefined,
    chipLocale: 'en-US',
    sortMode: 'default' as const,
    displayCat: (n: string) => n,
    multiSelect: false,
    selectedIds: new Set<string>(),
    onToggleSelectAll: vi.fn(),
    onToggleCollapse: vi.fn(),
    onHide: vi.fn(),
    flashedBmId: null,
    toggleSelected: vi.fn(),
    onBookmarkClick: vi.fn(),
    onContextMenu: vi.fn(),
    editingId: null,
    editName: '',
    setEditingId: vi.fn(),
    setEditName: vi.fn(),
    onBookmarkEdit: vi.fn(),
    ...over,
  } as any;
}

// Find the tri-state header checkbox (the only input in the header row).
function headerCheckbox(container: HTMLElement): HTMLInputElement | null {
  const group = container.querySelector('.bookmark-group') as HTMLElement;
  const header = group.firstElementChild as HTMLElement;
  return header.querySelector('input[type="checkbox"]') as HTMLInputElement | null;
}

describe('CategorySection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // --- Chevron rotate state: expanded vs collapsed --------------------------
  it('renders the chevron rotated 90deg when expanded (collapsed=false)', () => {
    const { container } = render(<CategorySection {...makeProps({ collapsed: false })} />);
    const chevron = container.querySelector('svg[style*="rotate"]') as SVGElement;
    expect(chevron.getAttribute('style')).toContain('rotate(90deg)');
  });

  it('renders the chevron rotated 0deg when collapsed (collapsed=true)', () => {
    const { container } = render(<CategorySection {...makeProps({ collapsed: true })} />);
    const chevron = container.querySelector('svg[style*="rotate"]') as SVGElement;
    expect(chevron.getAttribute('style')).toContain('rotate(0deg)');
  });

  // --- Tri-state header checkbox: checked / indeterminate / unchecked -------
  it('checks the header checkbox when ALL in-category ids are selected', () => {
    const { container } = render(
      <CategorySection
        {...makeProps({ multiSelect: true, selectedIds: new Set(['a', 'b']) })}
      />,
    );
    const cb = headerCheckbox(container)!;
    expect(cb.checked).toBe(true);
    expect(cb.indeterminate).toBe(false);
  });

  it('sets indeterminate (via ref-callback) when SOME but not all are selected', () => {
    const { container } = render(
      <CategorySection
        {...makeProps({ multiSelect: true, selectedIds: new Set(['a']) })}
      />,
    );
    const cb = headerCheckbox(container)!;
    expect(cb.checked).toBe(false);
    expect(cb.indeterminate).toBe(true);
  });

  it('leaves the header checkbox unchecked + not indeterminate when NONE are selected', () => {
    const { container } = render(
      <CategorySection
        {...makeProps({ multiSelect: true, selectedIds: new Set<string>() })}
      />,
    );
    const cb = headerCheckbox(container)!;
    expect(cb.checked).toBe(false);
    expect(cb.indeterminate).toBe(false);
  });

  it('omits the header checkbox entirely when not in multi-select mode', () => {
    const { container } = render(<CategorySection {...makeProps({ multiSelect: false })} />);
    expect(headerCheckbox(container)).toBeNull();
  });

  it('calls onToggleSelectAll with the in-category ids + the all-selected flag', () => {
    const onToggleSelectAll = vi.fn();
    const { container } = render(
      <CategorySection
        {...makeProps({
          multiSelect: true,
          selectedIds: new Set(['a']),
          onToggleSelectAll,
        })}
      />,
    );
    fireEvent.click(headerCheckbox(container)!);
    expect(onToggleSelectAll).toHaveBeenCalledTimes(1);
    // some-selected => allSelected flag is false.
    expect(onToggleSelectAll).toHaveBeenCalledWith(['a', 'b'], false);
  });

  // --- Hide button: title ---------------------------------------------------
  it('renders the hide button with title="bm.hide_category"', () => {
    const { container } = render(<CategorySection {...makeProps()} />);
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    expect(within(group).getByTitle('bm.hide_category')).toBeTruthy();
  });

  it('calls onHide with the category name (and does not toggle collapse) when the hide button is clicked', () => {
    const onHide = vi.fn();
    const onToggleCollapse = vi.fn();
    const { container } = render(
      <CategorySection {...makeProps({ onHide, onToggleCollapse })} />,
    );
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    fireEvent.click(within(group).getByTitle('bm.hide_category'));
    expect(onHide).toHaveBeenCalledWith('Work');
    // stopPropagation: clicking hide must NOT toggle the collapse.
    expect(onToggleCollapse).not.toHaveBeenCalled();
  });

  // --- Header toggle: firstElementChild click toggles collapse -------------
  it('calls onToggleCollapse with the category when the header (firstElementChild) is clicked', () => {
    const onToggleCollapse = vi.fn();
    const { container } = render(
      <CategorySection {...makeProps({ onToggleCollapse })} />,
    );
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    (group.firstElementChild as HTMLElement).click();
    expect(onToggleCollapse).toHaveBeenCalledTimes(1);
    expect(onToggleCollapse).toHaveBeenCalledWith('Work');
  });

  // --- Temporal status badges + group opacity ------------------------------
  it('renders the ended badge + 0.5 group opacity when status="ended"', () => {
    const { container } = render(
      <CategorySection {...makeProps({ status: 'ended' })} />,
    );
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    // The whole group is dimmed to 0.5 for ended events.
    expect(group.getAttribute('style')).toContain('opacity: 0.5');
    // The ended badge text key renders inside the header.
    const header = group.firstElementChild as HTMLElement;
    const badge = Array.from(header.querySelectorAll('span')).find(
      (s) => s.textContent === 'bm.cat.status_ended',
    );
    expect(badge).toBeTruthy();
  });

  it('renders the upcoming badge with the interpolated date chip when status="upcoming" + dates', () => {
    const { container } = render(
      <CategorySection
        {...makeProps({
          status: 'upcoming',
          dates: { start_date: '2030-01-15', end_date: '2030-01-20' },
        })}
      />,
    );
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    // Upcoming events dim the group to 0.7.
    expect(group.getAttribute('style')).toContain('opacity: 0.7');
    const header = group.firstElementChild as HTMLElement;
    // The badge text is the upcoming key + the interpolated formatChipDate of
    // start_date ('2030-01-15' -> 'Jan 15' for en-US). The fakeT mock appends
    // interpolation params so we can pin that the chip date flows through.
    const badge = Array.from(header.querySelectorAll('span')).find((s) =>
      (s.textContent ?? '').startsWith('bm.cat.status_upcoming'),
    );
    expect(badge).toBeTruthy();
    expect(badge!.textContent).toBe('bm.cat.status_upcoming:Jan 15');
  });

  it('omits the upcoming badge when status="upcoming" but dates are missing', () => {
    const { container } = render(
      <CategorySection {...makeProps({ status: 'upcoming', dates: undefined })} />,
    );
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    const header = group.firstElementChild as HTMLElement;
    const badge = Array.from(header.querySelectorAll('span')).find((s) =>
      (s.textContent ?? '').startsWith('bm.cat.status_upcoming'),
    );
    expect(badge).toBeUndefined();
  });

  // --- Empty body + collapse gating ----------------------------------------
  it('renders the bm.blank placeholder when expanded with no bookmarks', () => {
    const { container } = render(
      <CategorySection {...makeProps({ bms: [], collapsed: false })} />,
    );
    const blank = Array.from(container.querySelectorAll('div')).find(
      (d) => d.textContent === 'bm.blank',
    );
    expect(blank).toBeTruthy();
  });

  it('renders no BookmarkRow children when collapsed (even with bookmarks)', () => {
    const { container } = render(
      <CategorySection {...makeProps({ collapsed: true })} />,
    );
    // The expanded body (paddingLeft:20 wrapper) is the only place rows mount;
    // when collapsed the body is absent, so neither bookmark name renders.
    expect(container.textContent).not.toContain('Alpha');
    expect(container.textContent).not.toContain('Beta');
  });

  // --- DOM contract: name span text + group class --------------------------
  it('renders the category name in a header span via displayCat', () => {
    const { container } = render(
      <CategorySection {...makeProps({ displayCat: (n: string) => `<${n}>` })} />,
    );
    const group = container.querySelector('.bookmark-group') as HTMLElement;
    const header = group.firstElementChild as HTMLElement;
    const nameSpan = Array.from(header.querySelectorAll('span')).find(
      (s) => s.textContent === '<Work>',
    );
    expect(nameSpan).toBeTruthy();
  });
});
