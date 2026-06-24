import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import CustomBookmarkDialog from './CustomBookmarkDialog';

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    open: true,
    name: '',
    lat: '',
    lng: '',
    category: 'Default',
    categories: ['Default', 'Work'],
    displayCat: (n: string) => n,
    onNameChange: vi.fn(),
    onLatChange: vi.fn(),
    onLngChange: vi.fn(),
    onCategoryChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('CustomBookmarkDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<CustomBookmarkDialog {...makeProps({ open: false })} />);
    // Portal renders into document.body; nothing should be added when closed.
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText('bm.add_custom')).toBeNull();
  });

  it('splits a pasted "lat, lng" pair into both fields', () => {
    const onLatChange = vi.fn();
    const onLngChange = vi.fn();
    render(<CustomBookmarkDialog {...makeProps({ onLatChange, onLngChange })} />);
    fireEvent.change(screen.getByPlaceholderText('bm.latlng_single_placeholder'), {
      target: { value: '24.14, 120.65' },
    });
    expect(onLatChange).toHaveBeenCalledWith('24.14');
    expect(onLngChange).toHaveBeenCalledWith('120.65');
  });

  it('keeps partial input in lat and clears lng while typing', () => {
    const onLatChange = vi.fn();
    const onLngChange = vi.fn();
    render(<CustomBookmarkDialog {...makeProps({ onLatChange, onLngChange })} />);
    fireEvent.change(screen.getByPlaceholderText('bm.latlng_single_placeholder'), {
      target: { value: '24.1' },
    });
    expect(onLatChange).toHaveBeenCalledWith('24.1');
    expect(onLngChange).toHaveBeenCalledWith('');
  });

  it('submits a validated, parsed bookmark on the Add button', () => {
    const onSubmit = vi.fn();
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '24.14', lng: '120.65', category: 'Work', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.add'));
    expect(onSubmit).toHaveBeenCalledWith({
      name: 'Pin',
      lat: 24.14,
      lng: 120.65,
      category: 'Work',
    });
  });

  it('does not submit when lat is out of range', () => {
    const onSubmit = vi.fn();
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '200', lng: '120.65', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.add'));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows an inline out-of-range error for a finite-but-invalid lat', () => {
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '200', lng: '120.65' })}
      />,
    );
    // The error key renders verbatim (identity translator).
    expect(screen.getByText('bm.latlng_out_of_range')).toBeTruthy();
  });

  it('does NOT show the out-of-range error for an in-range pair', () => {
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '24.14', lng: '120.65' })}
      />,
    );
    expect(screen.queryByText('bm.latlng_out_of_range')).toBeNull();
  });

  it('does NOT show the out-of-range error while lat is still partial/empty', () => {
    render(<CustomBookmarkDialog {...makeProps({ name: 'Pin', lat: '24.', lng: '' })} />);
    // parseFloat('24.') === 24 is in range, lng empty (NaN, not finite) => no out-of-range error.
    expect(screen.queryByText('bm.latlng_out_of_range')).toBeNull();
  });
});
