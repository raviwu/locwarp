import React, { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// i18n -> identity translator so the menu's text keys render verbatim.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
}));

import MapContextMenu from './MapContextMenu';

const COORD = { lat: 25.123456, lng: 121.654321 };

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    lat: COORD.lat,
    lng: COORD.lng,
    x: 50,
    y: 50,
    name: undefined,
    reverseGeocode: vi.fn().mockResolvedValue({ display_name: 'Fake Address' }),
    bookmarkMatch: undefined,
    deviceConnected: true,
    showWaypointOption: false,
    onTeleport: vi.fn(),
    onNavigate: vi.fn(),
    onSetAsGoldDittoA: vi.fn(),
    onCopy: vi.fn(),
    onAddBookmark: vi.fn(),
    onAddWaypoint: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('MapContextMenu', () => {
  // --- reverse-geocode: fires once + shows the resolved address -------------
  it('triggers reverseGeocode once when the coords header is clicked and shows the result', async () => {
    const reverseGeocode = vi.fn().mockResolvedValue({ display_name: 'Fake Address' });
    render(<MapContextMenu {...makeProps({ reverseGeocode })} />);

    const header = screen.getByText('map.whats_here');
    await act(async () => {
      fireEvent.click(header.parentElement as HTMLElement);
    });
    expect(reverseGeocode).toHaveBeenCalledTimes(1);
    expect(reverseGeocode).toHaveBeenCalledWith(COORD.lat, COORD.lng);
    expect(await screen.findByText('Fake Address')).toBeTruthy();
  });

  // --- stale-guard: a late resolve after unmount is dropped -----------------
  it('drops a reverse-geocode result that resolves after the menu unmounted (per-open unmount)', async () => {
    // Deferred promise so we can unmount before it resolves.
    let resolveGeo!: (v: any) => void;
    const reverseGeocode = vi.fn(
      () => new Promise((res) => { resolveGeo = res; }),
    );

    // Parent that owns an `open` flag so the menu mounts/unmounts per open,
    // mirroring how MapView renders `{contextMenu.visible && <MapContextMenu …/>}`.
    function Harness() {
      const [open, setOpen] = useState(true);
      return open ? (
        <MapContextMenu
          {...makeProps({ reverseGeocode, onClose: () => setOpen(false) })}
        />
      ) : (
        <button onClick={() => {}}>closed</button>
      );
    }
    const { rerender } = render(<Harness />);

    // Kick off the reverse-geocode (request in flight, unresolved).
    const header = screen.getByText('map.whats_here');
    fireEvent.click(header.parentElement as HTMLElement);
    expect(reverseGeocode).toHaveBeenCalledTimes(1);

    // Unmount the menu BEFORE the geocode resolves: render the parent with the
    // menu gone (conditional unmount). The mountedRef flips false on unmount.
    rerender(<div />);
    await waitFor(() => expect(screen.queryByText('map.whats_here')).toBeNull());

    // Resolve the late geocode — the late address must never appear. NOTE: this
    // pins the OBSERVABLE behavior (per-open unmount → no stale address). Under
    // React 18 a setState on an unmounted component is already a silent no-op, so
    // the `mountedRef` guard is belt-and-suspenders (defensive, not isolable by a
    // test); MapView's per-open `key` means there is no still-mounted-but-
    // re-targeted path for the guard to affect. Behavior-equivalent to the
    // monolith, which used a render-side `reverseGeo.key === headerKey` check.
    await act(async () => {
      resolveGeo({ display_name: 'Late Stale Address' });
      await Promise.resolve();
    });
    expect(screen.queryByText('Late Stale Address')).toBeNull();
  });

  // --- each of the 7 actions fires its callback ------------------------------
  it('fires onTeleport(lat,lng) and closes when Teleport is clicked', () => {
    const onTeleport = vi.fn();
    const onClose = vi.fn();
    render(<MapContextMenu {...makeProps({ onTeleport, onClose })} />);
    fireEvent.click(screen.getByText('map.teleport_here'));
    expect(onTeleport).toHaveBeenCalledWith(COORD.lat, COORD.lng);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onNavigate(lat,lng) and closes when Navigate is clicked', () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(<MapContextMenu {...makeProps({ onNavigate, onClose })} />);
    fireEvent.click(screen.getByText('map.navigate_here'));
    expect(onNavigate).toHaveBeenCalledWith(COORD.lat, COORD.lng);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onSetAsGoldDittoA(lat,lng) and closes when Set-as-A is clicked', () => {
    const onSetAsGoldDittoA = vi.fn();
    const onClose = vi.fn();
    render(<MapContextMenu {...makeProps({ onSetAsGoldDittoA, onClose })} />);
    fireEvent.click(screen.getByText('goldditto.set_as_a'));
    expect(onSetAsGoldDittoA).toHaveBeenCalledWith(COORD.lat, COORD.lng);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onCopy and closes when Copy is clicked', () => {
    const onCopy = vi.fn();
    const onClose = vi.fn();
    render(<MapContextMenu {...makeProps({ onCopy, onClose })} />);
    fireEvent.click(screen.getByText('map.copy_coords'));
    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onAddBookmark(lat,lng,name) and closes when Add Bookmark is clicked', () => {
    const onAddBookmark = vi.fn();
    const onClose = vi.fn();
    render(
      <MapContextMenu {...makeProps({ onAddBookmark, onClose, name: 'Some Place' })} />,
    );
    fireEvent.click(screen.getByText('map.add_bookmark'));
    expect(onAddBookmark).toHaveBeenCalledWith(COORD.lat, COORD.lng, 'Some Place');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onAddWaypoint(lat,lng) and closes when Add Waypoint is clicked', () => {
    const onAddWaypoint = vi.fn();
    const onClose = vi.fn();
    render(
      <MapContextMenu
        {...makeProps({ onAddWaypoint, onClose, showWaypointOption: true })}
      />,
    );
    fireEvent.click(screen.getByText('map.add_waypoint'));
    expect(onAddWaypoint).toHaveBeenCalledWith(COORD.lat, COORD.lng);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // --- gating ----------------------------------------------------------------
  it('shows the disconnected notice and hides teleport/navigate when deviceConnected=false', () => {
    render(<MapContextMenu {...makeProps({ deviceConnected: false })} />);
    expect(screen.getByText('map.device_disconnected')).toBeTruthy();
    expect(screen.queryByText('map.teleport_here')).toBeNull();
    expect(screen.queryByText('map.navigate_here')).toBeNull();
  });

  it('hides the add-waypoint item when showWaypointOption is false', () => {
    render(<MapContextMenu {...makeProps({ showWaypointOption: false })} />);
    expect(screen.queryByText('map.add_waypoint')).toBeNull();
  });

  it('renders the disabled already-bookmarked item (not Add Bookmark) when a match exists', () => {
    const onAddBookmark = vi.fn();
    render(
      <MapContextMenu
        {...makeProps({ onAddBookmark, bookmarkMatch: { name: 'Saved Place' } })}
      />,
    );
    expect(screen.getByText('map.already_bookmarked')).toBeTruthy();
    expect(screen.queryByText('map.add_bookmark')).toBeNull();
    // The disabled row is inert — clicking it must NOT fire onAddBookmark.
    fireEvent.click(screen.getByText('map.already_bookmarked'));
    expect(onAddBookmark).not.toHaveBeenCalled();
  });

  // --- viewport-clamp layout-effect: renders + settles, no infinite loop -----
  it('runs the viewport-clamp layout-effect once and settles (visible, no reposition loop)', async () => {
    // Spy getBoundingClientRect so the clamp has a real size to work with.
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({
        width: 200, height: 300, top: 0, left: 0, right: 200, bottom: 300, x: 0, y: 0,
        toJSON: () => ({}),
      } as DOMRect);
    try {
      const { container } = render(<MapContextMenu {...makeProps()} />);
      const menu = container.querySelector('.context-menu') as HTMLElement;
      expect(menu).toBeTruthy();
      // After the synchronous layout-effect, the menu flips to visible and the
      // position is clamped. If the dep list included the painted position the
      // effect would re-run forever; instead it settles on one paint.
      await waitFor(() => {
        expect(menu.style.visibility).toBe('visible');
      });
    } finally {
      rectSpy.mockRestore();
    }
  });

  // --- container stops click propagation (so MapView's outside-click dismiss
  //     does not fire when clicking inside the menu) ---------------------------
  it('stops click propagation from the menu container', () => {
    const outerClick = vi.fn();
    const { container } = render(
      <div onClick={outerClick}>
        <MapContextMenu {...makeProps()} />
      </div>,
    );
    const menu = container.querySelector('.context-menu') as HTMLElement;
    expect(menu).toBeTruthy();
    fireEvent.click(menu);
    expect(outerClick).not.toHaveBeenCalled();
  });
});
