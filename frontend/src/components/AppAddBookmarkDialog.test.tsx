import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import AppAddBookmarkDialog, { AppAddBookmarkState } from './AppAddBookmarkDialog';

function makeDialog(over: Partial<AppAddBookmarkState> = {}): AppAddBookmarkState {
  return {
    lat: 25.0478,
    lng: 121.5319,
    name: '',
    category: 'Trips',
    ...over,
  };
}

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    dialog: makeDialog(),
    categories: ['Trips', 'Food'],
    onNameChange: vi.fn(),
    onCategoryChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('AppAddBookmarkDialog', () => {
  it('renders nothing when dialog is null', () => {
    render(<AppAddBookmarkDialog {...makeProps({ dialog: null })} />);
    expect(screen.queryByText('bm.add')).toBeNull();
  });

  it('shows the target coord and fires onNameChange while typing', () => {
    const onNameChange = vi.fn();
    render(<AppAddBookmarkDialog {...makeProps({ onNameChange })} />);
    expect(screen.getByText('25.04780, 121.53190')).toBeTruthy();
    const input = screen.getByPlaceholderText('bm.name_placeholder') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Taipei Station' } });
    expect(onNameChange).toHaveBeenCalledWith('Taipei Station');
  });

  it('shows the resolving placeholder + spinner during reverse-geocode pre-fill', () => {
    render(<AppAddBookmarkDialog {...makeProps({ dialog: makeDialog({ nameResolving: true }) })} />);
    // resolving placeholder swaps in
    expect(screen.getByPlaceholderText('bm.name_resolving')).toBeTruthy();
    // the short resolving hint badge is visible
    expect(screen.getByText('bm.name_resolving_short')).toBeTruthy();
  });

  it('renders the pre-filled name + country flag once geocode resolves', () => {
    render(
      <AppAddBookmarkDialog
        {...makeProps({ dialog: makeDialog({ name: '台北車站', countryCode: 'tw', nameResolving: false }) })}
      />,
    );
    expect(screen.getByDisplayValue('台北車站')).toBeTruthy();
    const flag = screen.getByAltText('TW') as HTMLImageElement;
    expect(flag.src).toContain('flagcdn.com/w20/tw.png');
  });

  it('disables Add until a non-empty name is present, then fires onSubmit', () => {
    const onSubmit = vi.fn();
    const { rerender } = render(<AppAddBookmarkDialog {...makeProps({ onSubmit })} />);
    const addBtn = screen.getByText('generic.add') as HTMLButtonElement;
    expect(addBtn.disabled).toBe(true);
    rerender(
      <AppAddBookmarkDialog {...makeProps({ onSubmit, dialog: makeDialog({ name: 'Pin' }) })} />,
    );
    const enabled = screen.getByText('generic.add') as HTMLButtonElement;
    expect(enabled.disabled).toBe(false);
    fireEvent.click(enabled);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('submits on Enter and closes on Escape', () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    render(
      <AppAddBookmarkDialog {...makeProps({ onSubmit, onClose, dialog: makeDialog({ name: 'Pin' }) })} />,
    );
    const input = screen.getByDisplayValue('Pin');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onCategoryChange when the category select changes', () => {
    const onCategoryChange = vi.fn();
    render(<AppAddBookmarkDialog {...makeProps({ onCategoryChange })} />);
    fireEvent.change(screen.getByDisplayValue('Trips'), { target: { value: 'Food' } });
    expect(onCategoryChange).toHaveBeenCalledWith('Food');
  });
});
