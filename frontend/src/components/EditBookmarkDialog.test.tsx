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
    // Existing tests below predate per-field dirty tracking and exercise the
    // dialog as if every field the caller passed a value for was actively
    // edited — so default all three dirty, and let the new dirty-specific
    // tests override individual flags.
    nameDirty: true,
    latDirty: true,
    lngDirty: true,
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

  it('submits the sparse patch (id + the edited name/lat/lng) on Save', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '26.5', lng: '122.5', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).toHaveBeenCalledWith('bm-1', {
      id: ORIG.id,
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

  it('exposes the panel as a role=dialog (a11y)', () => {
    render(<EditBookmarkDialog {...makeProps()} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });

  it('closes on Escape pressed anywhere in the dialog', () => {
    const onClose = vi.fn();
    render(<EditBookmarkDialog {...makeProps({ onClose })} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('still submits the sparse patch unchanged after migration', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({ name: 'New Name', lat: '26.5', lng: '122.5', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).toHaveBeenCalledWith('bm-1', {
      id: ORIG.id,
      name: 'New Name',
      lat: 26.5,
      lng: 122.5,
    });
  });

  // --- per-field dirty tracking (bookmark-revert fix) ----------------------
  it('puts only the dirty fields on the wire — nothing else is carried along', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({
          name: 'Old Name',
          nameDirty: false,
          lat: '26.5',
          lng: '122.5',
          latDirty: true,
          lngDirty: true,
          onSubmit,
        })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    // Exact shape: the record's other fields (category, country_code, …) are
    // not re-sent either, so the backend PUT leaves every one of them alone.
    expect(onSubmit).toHaveBeenCalledWith('bm-1', { id: 'bm-1', lat: 26.5, lng: 122.5 });
    const patch = onSubmit.mock.calls[0][1];
    expect('name' in patch).toBe(false);
  });

  it('omits an untouched field rather than re-sending the live record value', () => {
    const onSubmit = vi.fn();
    // The record's name has changed to 'Renamed Elsewhere' since the dialog
    // opened — e.g. synced in from another machine. The local `name` state
    // still holds what was seeded at open time ('Old Name'). Only lat/lng are
    // dirty, so `name` is left off the wire entirely and the concurrent
    // rename cannot be reverted by this save.
    render(
      <EditBookmarkDialog
        {...makeProps({
          bookmark: { ...ORIG, name: 'Renamed Elsewhere' },
          name: 'Old Name',
          nameDirty: false,
          lat: '26.5',
          lng: '122.5',
          latDirty: true,
          lngDirty: true,
          onSubmit,
        })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    // No `name` key at all — neither the stale open-time text nor the live
    // record's value. The backend leaves the stored name exactly as it is.
    expect(onSubmit).toHaveBeenCalledWith('bm-1', {
      id: ORIG.id,
      lat: 26.5,
      lng: 122.5,
    });
  });

  it('submits the typed value for a field the user DID edit, even if the live record also changed', () => {
    const onSubmit = vi.fn();
    render(
      <EditBookmarkDialog
        {...makeProps({
          bookmark: { ...ORIG, name: 'Renamed Elsewhere' },
          name: 'User Typed Name',
          nameDirty: true,
          lat: '25',
          lng: '121',
          latDirty: false,
          lngDirty: false,
          onSubmit,
        })}
      />,
    );
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).toHaveBeenCalledWith('bm-1', {
      id: ORIG.id,
      name: 'User Typed Name',
      // lat/lng untouched -> omitted, so the stored coordinates stand.
    });
  });

  // --- coordinate-truncation regression (see CustomBookmarkDialog) ---------
  function ControlledEdit() {
    const [lat, setLat] = React.useState('25');
    const [lng, setLng] = React.useState('121');
    return (
      <EditBookmarkDialog
        {...makeProps({ lat, lng, onLatChange: setLat, onLngChange: setLng })}
      />
    );
  }

  it.each([
    ['a trailing space', '25.033064, 121.5654 '],
    ['a tab separator', '25.033064\t121.5654'],
    ['pasted leading whitespace', '  25.033064, 121.5654'],
    ['no space after the comma', '25.033064,121.5654'],
  ])('does not rewrite the text the user typed — %s', (_label, typed) => {
    render(<ControlledEdit />);
    const field = screen.getByPlaceholderText('bm.latlng_single_placeholder') as HTMLInputElement;
    fireEvent.change(field, { target: { value: typed } });
    expect(field.value).toBe(typed);
  });
});
