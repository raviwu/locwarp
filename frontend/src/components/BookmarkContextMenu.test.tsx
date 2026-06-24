import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// i18n -> identity translator so the menu's text keys render verbatim.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
}));

import BookmarkContextMenu from './BookmarkContextMenu';

const bm = {
  id: 'bm-0',
  name: 'Place 0',
  lat: 25.123456,
  lng: 121.654321,
  category: 'Default',
};

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    bm,
    x: 50,
    y: 50,
    onClose: vi.fn(),
    reverseGeocode: vi.fn().mockResolvedValue({ display_name: 'Fake Address' }),
    deviceConnected: true,
    showWaypointOption: false,
    onTeleport: vi.fn(),
    onNavigate: vi.fn(),
    onSetAsGoldDittoA: vi.fn(),
    onAddWaypoint: vi.fn(),
    onEdit: vi.fn(),
    onCopy: vi.fn(),
    onDelete: vi.fn(),
    onMoveToCategory: vi.fn(),
    categories: ['Default', 'Work'],
    resolveColor: (_: string) => '#fff',
    displayCat: (n: string) => n,
    onShowToast: vi.fn(),
    ...over,
  } as any;
}

beforeEach(() => {
  vi.useRealTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('BookmarkContextMenu', () => {
  it('triggers reverseGeocode once when the coords header is clicked and shows the result', async () => {
    const reverseGeocode = vi.fn().mockResolvedValue({ display_name: 'Fake Address' });
    render(<BookmarkContextMenu {...makeProps({ reverseGeocode })} />);

    const header = screen.getByText('map.whats_here');
    await act(async () => {
      fireEvent.click(header.parentElement as HTMLElement);
    });
    expect(reverseGeocode).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Fake Address')).toBeTruthy();
  });

  it('drops a reverse-geocode result that resolves after the menu closed (stale-guard)', async () => {
    // Deferred promise so we can unmount before it resolves.
    let resolveGeo!: (v: any) => void;
    const reverseGeocode = vi.fn(
      () => new Promise((res) => { resolveGeo = res; }),
    );

    // Parent that owns an `open` flag so onClose actually unmounts the menu —
    // mirroring how BookmarkList keys/mounts the menu per open.
    function Harness() {
      const [open, setOpen] = useState(true);
      return open ? (
        <BookmarkContextMenu
          {...makeProps({ reverseGeocode, onClose: () => setOpen(false) })}
        />
      ) : null;
    }
    render(<Harness />);

    // The dismissal listeners (incl. Escape) register on setTimeout(0); flush
    // it so the subsequent Escape actually closes the menu.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    const header = screen.getByText('map.whats_here');
    fireEvent.click(header.parentElement as HTMLElement);
    expect(reverseGeocode).toHaveBeenCalledTimes(1);

    // Close (Escape) BEFORE the geocode resolves -> menu unmounts.
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByText('map.whats_here')).toBeNull());

    // Resolve the late geocode — the stale-guard must drop it.
    await act(async () => {
      resolveGeo({ display_name: 'Late Stale Address' });
      await Promise.resolve();
    });
    expect(screen.queryByText('Late Stale Address')).toBeNull();
  });

  it('closes on Escape', async () => {
    const onClose = vi.fn();
    render(<BookmarkContextMenu {...makeProps({ onClose })} />);
    // Listeners register on setTimeout(0); flush it.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('fires an action callback (teleport) and closes', () => {
    const onTeleport = vi.fn();
    const onClose = vi.fn();
    render(<BookmarkContextMenu {...makeProps({ onTeleport, onClose })} />);
    fireEvent.click(screen.getByText('map.teleport_here'));
    expect(onTeleport).toHaveBeenCalledWith(bm.lat, bm.lng);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('shows the disabled disconnected row and hides teleport/navigate when deviceConnected=false', () => {
    render(<BookmarkContextMenu {...makeProps({ deviceConnected: false })} />);
    // The device-gated branch renders the disconnected notice instead of the
    // teleport/navigate action rows.
    expect(screen.getByText('map.device_disconnected')).toBeTruthy();
    expect(screen.queryByText('map.teleport_here')).toBeNull();
    expect(screen.queryByText('map.navigate_here')).toBeNull();
  });

  it('lists only the OTHER categories in the move-to submenu and fires onMoveToCategory on click', () => {
    const onMoveToCategory = vi.fn();
    const onClose = vi.fn();
    // bm.category === 'Default'; the submenu filters that out, leaving 'Work'.
    render(
      <BookmarkContextMenu
        {...makeProps({
          categories: ['Default', 'Work'],
          onMoveToCategory,
          onClose,
        })}
      />,
    );
    // The current category must NOT appear as a move target...
    expect(screen.queryByText('bm.move_to')).toBeTruthy();
    // 'Default' is bm.category; the only move-to row in the submenu is 'Work'.
    // (displayCat is identity, so the text is the raw category name.)
    const workRow = screen.getByText('Work');
    fireEvent.click(workRow);
    expect(onMoveToCategory).toHaveBeenCalledWith(bm.id, 'Work');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('hides the move-to submenu entirely when only the current category exists', () => {
    render(<BookmarkContextMenu {...makeProps({ categories: ['Default'] })} />);
    // categories.length <= 1 -> no "Move to" header at all.
    expect(screen.queryByText('bm.move_to')).toBeNull();
  });

  it('fires onDelete(bm.id) and closes when Delete is clicked', () => {
    const onDelete = vi.fn();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<BookmarkContextMenu {...makeProps({ onDelete, onClose })} />);
    fireEvent.click(screen.getByText('generic.delete'));
    expect(onDelete).toHaveBeenCalledWith(bm.id);
    expect(onClose).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });
});

describe('BookmarkContextMenu delete confirmation (U13)', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('does NOT call onDelete when the confirm is dismissed', () => {
    const onDelete = vi.fn();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<BookmarkContextMenu {...makeProps({ onDelete, onClose })} />);
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).not.toHaveBeenCalled();
    // Menu still closes either way (parity with the other action rows).
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onDelete(bm.id) when the confirm is accepted', () => {
    const onDelete = vi.fn();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<BookmarkContextMenu {...makeProps({ onDelete, onClose })} />);
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(bm.id);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
