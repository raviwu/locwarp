import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import WaypointFlyDialog, { WaypointFlyTarget } from './WaypointFlyDialog';

function makeTarget(over: Partial<WaypointFlyTarget> = {}): WaypointFlyTarget {
  return { lat: 25.047801, lng: 121.531902, index: 2, ...over };
}

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    confirm: makeTarget(),
    onSetAsStart: vi.fn(),
    onConfirm: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('WaypointFlyDialog', () => {
  it('renders nothing when confirm is null', () => {
    render(<WaypointFlyDialog {...makeProps({ confirm: null })} />);
    expect(screen.queryByText('panel.wp_fly_title')).toBeNull();
  });

  it('shows the target coord to 6 decimals', () => {
    render(<WaypointFlyDialog {...makeProps()} />);
    expect(screen.getByText('25.047801, 121.531902')).toBeTruthy();
  });

  it('offers "set as start + fly" for a non-start waypoint and emits its index', () => {
    const onSetAsStart = vi.fn();
    render(<WaypointFlyDialog {...makeProps({ onSetAsStart, confirm: makeTarget({ index: 3 }) })} />);
    fireEvent.click(screen.getByText('panel.wp_fly_set_as_start'));
    expect(onSetAsStart).toHaveBeenCalledWith(3);
  });

  it('falls back to plain teleport (onConfirm) for the start waypoint (index 0)', () => {
    const onConfirm = vi.fn();
    const onSetAsStart = vi.fn();
    render(
      <WaypointFlyDialog {...makeProps({ onConfirm, onSetAsStart, confirm: makeTarget({ index: 0 }) })} />,
    );
    // No "set as start" button when index is 0.
    expect(screen.queryByText('panel.wp_fly_set_as_start')).toBeNull();
    fireEvent.click(screen.getByText('panel.wp_fly_confirm'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onSetAsStart).not.toHaveBeenCalled();
  });

  it('fires onClose from the cancel button', () => {
    const onClose = vi.fn();
    render(<WaypointFlyDialog {...makeProps({ onClose })} />);
    fireEvent.click(screen.getByText('generic.cancel'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
