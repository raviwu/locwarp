import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import RouteLoadDialog, { RouteLoadTarget } from './RouteLoadDialog';

function makeTarget(over: Partial<RouteLoadTarget> = {}): RouteLoadTarget {
  return {
    name: 'Morning loop',
    waypoints: [
      { lat: 25.047801, lng: 121.531902 },
      { lat: 25.05, lng: 121.54 },
    ],
    ...over,
  };
}

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    confirm: makeTarget(),
    onConfirm: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('RouteLoadDialog', () => {
  it('renders nothing when confirm is null', () => {
    render(<RouteLoadDialog {...makeProps({ confirm: null })} />);
    expect(screen.queryByText('panel.route_load_title')).toBeNull();
  });

  it('shows the route name + start coord', () => {
    render(<RouteLoadDialog {...makeProps()} />);
    expect(screen.getByText('Morning loop')).toBeTruthy();
    expect(screen.getByText(/25\.047801, 121\.531902/)).toBeTruthy();
  });

  it('emits onConfirm(false) for "show only"', () => {
    const onConfirm = vi.fn();
    render(<RouteLoadDialog {...makeProps({ onConfirm })} />);
    fireEvent.click(screen.getByText('panel.route_load_show_only'));
    expect(onConfirm).toHaveBeenCalledWith(false);
  });

  it('emits onConfirm(true) for "fly to start + show"', () => {
    const onConfirm = vi.fn();
    render(<RouteLoadDialog {...makeProps({ onConfirm })} />);
    fireEvent.click(screen.getByText('panel.route_load_fly_start'));
    expect(onConfirm).toHaveBeenCalledWith(true);
  });

  it('fires onClose from the cancel button', () => {
    const onClose = vi.fn();
    render(<RouteLoadDialog {...makeProps({ onClose })} />);
    fireEvent.click(screen.getByText('generic.cancel'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
