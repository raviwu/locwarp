import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/react';

// i18n -> identity translator (same pattern as CoordInputStrip / WaypointMenu /
// S2LevelPicker tests). The popover uses plain string keys; the only places
// with interpolation are the relative-time labels, which concatenate a number
// with a raw key, so identity is enough to assert the badge + time markup.
const fakeT = (k: string, params?: Record<string, unknown>) =>
  params ? `${k}:${Object.values(params).join(',')}` : k;
vi.mock('../i18n', () => ({
  useT: () => fakeT,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: fakeT }),
}));

import { RecentPlacesPopover } from './RecentPlacesPopover';

// The row <div> is the parent of the per-row ⋮ menu button. Both the re-fly
// button (first child) and the right-click onContextMenu handler live on it.
function getRow(container: HTMLElement) {
  const menuBtn = container.querySelector('button[title="recent.menu_tooltip"]') as HTMLButtonElement;
  return menuBtn.parentElement as HTMLElement;
}

const NOW = 1_700_000_000; // fixed epoch-seconds for deterministic relative time

// A teleport entry ~5 minutes old.
function teleportEntry(over: Partial<Record<string, any>> = {}) {
  return {
    lat: 25.0339,
    lng: 121.5645,
    kind: 'teleport' as const,
    name: 'Taipei 101',
    ts: NOW - 300,
    ...over,
  };
}

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    recentPlaces: [teleportEntry()],
    bookmarkByCoord: new Map(),
    onRecentReFly: vi.fn(),
    onRecentClear: vi.fn(),
    onOpenContextMenu: vi.fn(),
    ...over,
  } as any;
}

// Open the popover by clicking the toggle button (the only button before the
// popover is open — it carries the recent_tooltip title).
function openPopover(container: HTMLElement) {
  const toggle = container.querySelector('button[title="map.recent_tooltip"]') as HTMLButtonElement;
  fireEvent.click(toggle);
  return toggle;
}

describe('RecentPlacesPopover', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Pin Date.now so the relative-time label is deterministic.
    vi.spyOn(Date, 'now').mockReturnValue(NOW * 1000);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // --- gating ---------------------------------------------------------------
  it('renders nothing when recentPlaces is undefined', () => {
    const { container } = render(
      <RecentPlacesPopover {...makeProps({ recentPlaces: undefined })} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the toggle button (collapsed) without the popover list', () => {
    const { container, queryByText } = render(<RecentPlacesPopover {...makeProps()} />);
    expect(container.querySelector('button[title="map.recent_tooltip"]')).toBeTruthy();
    // List is closed: the title row + the row's name are not in the DOM yet.
    expect(queryByText('map.recent_title')).toBeNull();
    expect(queryByText('Taipei 101')).toBeNull();
  });

  it('shows a count badge with the number of entries while collapsed', () => {
    const { getByText } = render(
      <RecentPlacesPopover {...makeProps({ recentPlaces: [teleportEntry(), teleportEntry({ ts: NOW - 60 })] })} />,
    );
    expect(getByText('2')).toBeTruthy();
  });

  // --- open + per-row rendering --------------------------------------------
  it('opens the popover and renders a row with its badge + relative time', () => {
    const { container, getByText } = render(<RecentPlacesPopover {...makeProps()} />);
    openPopover(container);
    // Title row appears.
    expect(getByText('map.recent_title')).toBeTruthy();
    // The teleport badge label (identity key) + the entry name render.
    expect(getByText('recent.kind_teleport')).toBeTruthy();
    expect(getByText('Taipei 101')).toBeTruthy();
    // 300s old -> "5 minutes_ago". The coord line + the time share one node.
    expect(getByText(/5 time\.minutes_ago/)).toBeTruthy();
  });

  it('renders the empty-state message when the list is empty', () => {
    const { container, getByText, queryByText } = render(
      <RecentPlacesPopover {...makeProps({ recentPlaces: [] })} />,
    );
    openPopover(container);
    expect(getByText('map.recent_empty')).toBeTruthy();
    // No clear button when there is nothing to clear.
    expect(queryByText('map.recent_clear')).toBeNull();
  });

  it('renders the bookmark name + geo line for a coord-matched row', () => {
    const e = teleportEntry();
    const key = `${e.lat.toFixed(5)}|${e.lng.toFixed(5)}`;
    const bookmarkByCoord = new Map([
      [key, { name: 'My Bookmark', country_code: 'TW', city: 'Taipei', timezone: 'Asia/Taipei' }],
    ]);
    const { container, getByText, queryByText } = render(
      <RecentPlacesPopover {...makeProps({ bookmarkByCoord })} />,
    );
    openPopover(container);
    // The row shows the BOOKMARK name, not the entry name.
    expect(getByText('My Bookmark')).toBeTruthy();
    expect(queryByText('Taipei 101')).toBeNull();
  });

  // --- re-fly ---------------------------------------------------------------
  it('fires onRecentReFly with the entry when the row is clicked', () => {
    const onRecentReFly = vi.fn();
    const { container } = render(<RecentPlacesPopover {...makeProps({ onRecentReFly })} />);
    openPopover(container);
    // The row's main (re-fly) button is the FIRST button inside the row.
    const reflyBtn = within(getRow(container)).getAllByRole('button')[0];
    fireEvent.click(reflyBtn);
    expect(onRecentReFly).toHaveBeenCalledTimes(1);
    expect(onRecentReFly).toHaveBeenCalledWith(teleportEntry());
  });

  it('closes the popover after a re-fly click', () => {
    const { container, queryByText, getByText } = render(<RecentPlacesPopover {...makeProps()} />);
    openPopover(container);
    expect(getByText('map.recent_title')).toBeTruthy();
    const reflyBtn = within(getRow(container)).getAllByRole('button')[0];
    fireEvent.click(reflyBtn);
    // Popover collapses.
    expect(queryByText('map.recent_title')).toBeNull();
  });

  // --- context menu (right-click + ⋮) --------------------------------------
  it('opens the shared context menu via onOpenContextMenu on right-click of a row', () => {
    const onOpenContextMenu = vi.fn();
    const { container } = render(<RecentPlacesPopover {...makeProps({ onOpenContextMenu })} />);
    openPopover(container);
    const row = getRow(container);
    fireEvent.contextMenu(row, { clientX: 50, clientY: 60 });
    expect(onOpenContextMenu).toHaveBeenCalledTimes(1);
    // (lat, lng, name, x, y) — the entry's coords + name, then the click point.
    expect(onOpenContextMenu).toHaveBeenCalledWith(25.0339, 121.5645, 'Taipei 101', 50, 60);
  });

  it('opens the context menu via the ⋮ button', () => {
    const onOpenContextMenu = vi.fn();
    const { container } = render(<RecentPlacesPopover {...makeProps({ onOpenContextMenu })} />);
    openPopover(container);
    const menuBtn = container.querySelector('button[title="recent.menu_tooltip"]') as HTMLButtonElement;
    fireEvent.click(menuBtn, { clientX: 5, clientY: 6 });
    expect(onOpenContextMenu).toHaveBeenCalledTimes(1);
    expect(onOpenContextMenu.mock.calls[0][0]).toBe(25.0339);
    expect(onOpenContextMenu.mock.calls[0][2]).toBe('Taipei 101');
  });

  // --- clear-confirm (two-step) --------------------------------------------
  it('requires the confirm step before onRecentClear fires', () => {
    const onRecentClear = vi.fn();
    const { container, getByText, queryByText } = render(
      <RecentPlacesPopover {...makeProps({ onRecentClear })} />,
    );
    openPopover(container);
    // Step 1: the single clear button. Clicking it does NOT clear.
    fireEvent.click(getByText('map.recent_clear'));
    expect(onRecentClear).not.toHaveBeenCalled();
    // Step 2: the confirm + cancel pair now show.
    expect(getByText('map.recent_clear_confirm')).toBeTruthy();
    expect(getByText('generic.cancel')).toBeTruthy();
    // Confirm fires onRecentClear once.
    fireEvent.click(getByText('map.recent_clear_confirm'));
    expect(onRecentClear).toHaveBeenCalledTimes(1);
    // Popover collapses after a confirmed clear.
    expect(queryByText('map.recent_title')).toBeNull();
  });

  it('cancel reverts the clear-confirm without firing onRecentClear', () => {
    const onRecentClear = vi.fn();
    const { container, getByText, queryByText } = render(
      <RecentPlacesPopover {...makeProps({ onRecentClear })} />,
    );
    openPopover(container);
    fireEvent.click(getByText('map.recent_clear'));
    fireEvent.click(getByText('generic.cancel'));
    expect(onRecentClear).not.toHaveBeenCalled();
    // Back to the single clear button; confirm pair gone.
    expect(getByText('map.recent_clear')).toBeTruthy();
    expect(queryByText('map.recent_clear_confirm')).toBeNull();
  });

  it('hides the clear button entirely when onRecentClear is undefined', () => {
    const { container, queryByText } = render(
      <RecentPlacesPopover {...makeProps({ onRecentClear: undefined })} />,
    );
    openPopover(container);
    expect(queryByText('map.recent_clear')).toBeNull();
  });

  // --- draggable header: document listeners attach + detach -----------------
  it('attaches capture-phase document drag listeners on header pointerdown and removes them on mouseup', () => {
    const addSpy = vi.spyOn(document, 'addEventListener');
    const removeSpy = vi.spyOn(document, 'removeEventListener');
    const { container } = render(<RecentPlacesPopover {...makeProps()} />);
    openPopover(container);
    // The draggable header is the title row (cursor:move). Find the node
    // holding the recent_title span; its parent div carries the mousedown.
    const header = Array.from(container.querySelectorAll('div')).find(
      (d) => (d as HTMLElement).style.cursor === 'move',
    ) as HTMLElement;
    expect(header).toBeTruthy();

    // mousedown on the header (NOT on a child button) wires move + up on
    // document with capture:true.
    fireEvent.mouseDown(header, { clientX: 10, clientY: 10 });
    expect(addSpy).toHaveBeenCalledWith('mousemove', expect.any(Function), true);
    expect(addSpy).toHaveBeenCalledWith('mouseup', expect.any(Function), true);

    // mouseup removes both capture-phase listeners.
    fireEvent.mouseUp(document, { clientX: 10, clientY: 10 });
    expect(removeSpy).toHaveBeenCalledWith('mousemove', expect.any(Function), true);
    expect(removeSpy).toHaveBeenCalledWith('mouseup', expect.any(Function), true);
  });

  it('dragging the header moves the popover (translate offset follows the pointer)', () => {
    const { container } = render(<RecentPlacesPopover {...makeProps()} />);
    openPopover(container);
    const header = Array.from(container.querySelectorAll('div')).find(
      (d) => (d as HTMLElement).style.cursor === 'move',
    ) as HTMLElement;
    // The draggable panel is the header's parent (it carries the transform).
    const panel = header.parentElement as HTMLElement;
    expect(panel.style.transform).toBe('translate(0px, 0px)');

    fireEvent.mouseDown(header, { clientX: 100, clientY: 100 });
    // A document-level mousemove (capture) shifts the offset by the delta.
    fireEvent.mouseMove(document, { clientX: 130, clientY: 115 });
    expect(panel.style.transform).toBe('translate(30px, 15px)');
    fireEvent.mouseUp(document);
  });

  it('does not start a drag when mousedown lands on a header child button', () => {
    const addSpy = vi.spyOn(document, 'addEventListener');
    const { container, getByText } = render(<RecentPlacesPopover {...makeProps()} />);
    openPopover(container);
    // mousedown on the clear button must NOT wire the drag listeners (so the
    // button click still works).
    fireEvent.mouseDown(getByText('map.recent_clear'));
    expect(addSpy).not.toHaveBeenCalledWith('mousemove', expect.any(Function), true);
  });
});
