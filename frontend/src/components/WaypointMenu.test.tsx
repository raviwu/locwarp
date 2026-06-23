import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';

// i18n -> identity translator (same pattern as S2LevelPicker.test.tsx). The
// menu uses plain string keys with no interpolation, so identity is enough.
const fakeT = (k: string, params?: Record<string, unknown>) =>
  params ? `${k}:${Object.values(params).join(',')}` : k;
vi.mock('../i18n', () => ({
  useT: () => fakeT,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: fakeT }),
}));

import { WaypointMenu } from './WaypointMenu';

// Defaults satisfying the prop contract; each test overrides what it asserts.
function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    visible: true,
    x: 100,
    y: 100,
    index: 2,
    isStart: false,
    onSetAsStart: vi.fn(),
    onInsertAfter: vi.fn(),
    onRemove: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('WaypointMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // --- visible gating -------------------------------------------------------
  it('renders nothing when visible=false', () => {
    const { container } = render(<WaypointMenu {...makeProps({ visible: false })} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the menu when visible=true', () => {
    const { getByText } = render(<WaypointMenu {...makeProps()} />);
    // All three action labels render for a non-start waypoint with all handlers.
    expect(getByText('map.wp_set_as_start')).toBeTruthy();
    expect(getByText('map.wp_insert_after')).toBeTruthy();
    expect(getByText('map.wp_delete')).toBeTruthy();
  });

  // --- header label ---------------------------------------------------------
  it('shows the #index header for a non-start waypoint', () => {
    const { getByText } = render(<WaypointMenu {...makeProps({ index: 5, isStart: false })} />);
    expect(getByText('#5')).toBeTruthy();
  });

  it('shows the localized start label for a start waypoint', () => {
    const { getByText, queryByText } = render(
      <WaypointMenu {...makeProps({ index: 0, isStart: true })} />,
    );
    expect(getByText('panel.waypoint_start')).toBeTruthy();
    // And the #index form is NOT shown for a start waypoint.
    expect(queryByText('#0')).toBeNull();
  });

  // --- set-as-start gating: hidden when isStart -----------------------------
  it('hides set-as-start when the waypoint is the start', () => {
    const { queryByText } = render(<WaypointMenu {...makeProps({ isStart: true })} />);
    expect(queryByText('map.wp_set_as_start')).toBeNull();
    // The other two actions still render for a start waypoint.
    expect(queryByText('map.wp_insert_after')).toBeTruthy();
    expect(queryByText('map.wp_delete')).toBeTruthy();
  });

  // --- handler gating: an omitted callback hides its item -------------------
  it('hides set-as-start when onSetAsStart is undefined', () => {
    const { queryByText } = render(
      <WaypointMenu {...makeProps({ onSetAsStart: undefined })} />,
    );
    expect(queryByText('map.wp_set_as_start')).toBeNull();
  });

  it('hides insert-after when onInsertAfter is undefined', () => {
    const { queryByText } = render(
      <WaypointMenu {...makeProps({ onInsertAfter: undefined })} />,
    );
    expect(queryByText('map.wp_insert_after')).toBeNull();
  });

  it('hides delete when onRemove is undefined', () => {
    const { queryByText } = render(<WaypointMenu {...makeProps({ onRemove: undefined })} />);
    expect(queryByText('map.wp_delete')).toBeNull();
  });

  // --- actions fire the right callback with the index + close first ---------
  it('fires onSetAsStart(index) and closes when set-as-start is clicked', () => {
    const onSetAsStart = vi.fn();
    const onClose = vi.fn();
    const { getByText } = render(
      <WaypointMenu {...makeProps({ index: 3, onSetAsStart, onClose })} />,
    );
    fireEvent.click(getByText('map.wp_set_as_start'));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSetAsStart).toHaveBeenCalledTimes(1);
    expect(onSetAsStart).toHaveBeenCalledWith(3);
  });

  it('fires onInsertAfter(index) and closes when insert-after is clicked', () => {
    const onInsertAfter = vi.fn();
    const onClose = vi.fn();
    const { getByText } = render(
      <WaypointMenu {...makeProps({ index: 4, onInsertAfter, onClose })} />,
    );
    fireEvent.click(getByText('map.wp_insert_after'));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onInsertAfter).toHaveBeenCalledTimes(1);
    expect(onInsertAfter).toHaveBeenCalledWith(4);
  });

  it('fires onRemove(index) and closes when delete is clicked', () => {
    const onRemove = vi.fn();
    const onClose = vi.fn();
    const { getByText } = render(
      <WaypointMenu {...makeProps({ index: 6, onRemove, onClose })} />,
    );
    fireEvent.click(getByText('map.wp_delete'));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(6);
  });

  // --- container stops click propagation (so the document-level outside-click
  //     dismiss does not fire when clicking inside the menu) -----------------
  it('stops click propagation from the menu container', () => {
    const outerClick = vi.fn();
    const { container } = render(
      <div onClick={outerClick}>
        <WaypointMenu {...makeProps()} />
      </div>,
    );
    const menu = container.querySelector('.context-menu') as HTMLElement;
    expect(menu).toBeTruthy();
    fireEvent.click(menu);
    expect(outerClick).not.toHaveBeenCalled();
  });
});
