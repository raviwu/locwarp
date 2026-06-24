import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import EditBookmarkDialog from './EditBookmarkDialog';

const ORIG = {
  id: 'bm-1',
  name: 'Old Name',
  lat: 25,
  lng: 121,
  category: 'Work',
  country_code: 'tw',
};

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    bookmark: ORIG,
    name: 'Old Name',
    lat: '25',
    lng: '121',
    onNameChange: vi.fn(),
    onLatChange: vi.fn(),
    onLngChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('EditBookmarkDialog', () => {
  it('renders nothing when bookmark is null', () => {
    const { container } = render(<EditBookmarkDialog {...makeProps({ bookmark: null })} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText('bm.edit')).toBeNull();
  });

  it('splits a pasted "lat, lng" pair into both fields', () => {
    const onLatChange = vi.fn();
    const onLngChange = vi.fn();
    render(<EditBookmarkDialog {...makeProps({ onLatChange, onLngChange })} />);
    fireEvent.change(screen.getByPlaceholderText('bm.latlng_single_placeholder'), {
      target: { value: '-33.86, 151.20' },
    });
    expect(onLatChange).toHaveBeenCalledWith('-33.86');
    expect(onLngChange).toHaveBeenCalledWith('151.20');
  });

  it('keeps partial input in lat and clears lng while typing', () => {
    const onLatChange = vi.fn();
    const onLngChange = vi.fn();
    render(<EditBookmarkDialog {...makeProps({ onLatChange, onLngChange })} />);
    fireEvent.change(screen.getByPlaceholderText('bm.latlng_single_placeholder'), {
      target: { value: '-33.8' },
    });
    expect(onLatChange).toHaveBeenCalledWith('-33.8');
    expect(onLngChange).toHaveBeenCalledWith('');
  });

  it('submits the merged shape (original fields + edited name/lat/lng) on Save', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '26.5', lng: '122.5', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).toHaveBeenCalledWith('bm-1', {
      ...ORIG,
      name: 'New Name',
      lat: 26.5,
      lng: 122.5,
    });
  });

  it('does not submit when lng is out of range', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '26.5', lng: '999', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('does not submit when lat is out of range', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '200', lng: '122.5', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('closes without submitting when the bookmark has no id', () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({
          bookmark: { ...ORIG, id: undefined },
          name: 'New Name',
          lat: '26.5',
          lng: '122.5',
          onSubmit,
          onClose,
        })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    // id-missing early branch: bail out before the PUT, just close.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('shows an inline out-of-range error for a finite-but-invalid lat', () => {
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '200', lng: '122.5' })}
      />,
    );
    expect(screen.getByText('bm.latlng_out_of_range')).toBeTruthy();
  });

  it('does NOT show the out-of-range error for an in-range pair', () => {
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '26.5', lng: '122.5' })}
      />,
    );
    expect(screen.queryByText('bm.latlng_out_of_range')).toBeNull();
  });
});
