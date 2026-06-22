import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/react';

// i18n -> identity translator + a fixed language so the real BookmarkRow /
// BookmarkGeoLine children mount. Mirrors BookmarkRow.test.tsx / BookmarkList
// .test.tsx.
vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
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
