import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  // Echo {placeholders} back so stats / submit labels are observable.
  useT: () => (k: string) => k,
}));

import BulkPasteDialog from './BulkPasteDialog';

// Minimal parse stub mirroring App.parseBulkPaste's shape: any non-empty line
// counts; lines containing the literal "bad" are invalid.
const parse = (raw: string) => {
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
  const valid = lines.filter((l) => !l.includes('bad')).map(() => ({ lat: 1, lng: 2 }));
  return { valid, invalidCount: lines.length - valid.length, totalLines: lines.length };
};

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    open: true,
    text: '',
    category: 'Trips',
    categories: ['Trips', 'Food'],
    busy: false,
    parse,
    onTextChange: vi.fn(),
    onCategoryChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('BulkPasteDialog', () => {
  it('renders nothing when closed', () => {
    render(<BulkPasteDialog {...makeProps({ open: false })} />);
    expect(screen.queryByText('bm.bulk_paste_title')).toBeNull();
  });

  it('fires onTextChange while typing in the textarea', () => {
    const onTextChange = vi.fn();
    render(<BulkPasteDialog {...makeProps({ onTextChange })} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '1 2 here' } });
    expect(onTextChange).toHaveBeenCalledWith('1 2 here');
  });

  it('disables submit when no valid lines and enables once valid lines exist', () => {
    const { rerender } = render(<BulkPasteDialog {...makeProps({ text: '' })} />);
    // empty -> 0 valid -> disabled, label shows (0)
    const empty = screen.getByText('bm.bulk_paste_submit (0)') as HTMLButtonElement;
    expect(empty.disabled).toBe(true);
    rerender(<BulkPasteDialog {...makeProps({ text: '1 2 a\n3 4 b' })} />);
    const ready = screen.getByText('bm.bulk_paste_submit (2)') as HTMLButtonElement;
    expect(ready.disabled).toBe(false);
  });

  it('fires onSubmit on click (the sim-driving createBookmark loop stays in App)', () => {
    const onSubmit = vi.fn();
    render(<BulkPasteDialog {...makeProps({ onSubmit, text: '1 2 a' })} />);
    fireEvent.click(screen.getByText('bm.bulk_paste_submit (1)'));
    // The dialog forwards the click to App's param-less submitBulkPaste; it
    // carries no parsed payload — App re-parses its own text state.
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('fires onCategoryChange when the category select changes', () => {
    const onCategoryChange = vi.fn();
    render(<BulkPasteDialog {...makeProps({ onCategoryChange })} />);
    fireEvent.change(screen.getByDisplayValue('Trips'), { target: { value: 'Food' } });
    expect(onCategoryChange).toHaveBeenCalledWith('Food');
  });

  it('blocks cancel + submit while busy', () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    render(<BulkPasteDialog {...makeProps({ onClose, onSubmit, busy: true, text: '1 2 a' })} />);
    const cancel = screen.getByText('generic.cancel') as HTMLButtonElement;
    expect(cancel.disabled).toBe(true);
    fireEvent.click(cancel);
    expect(onClose).not.toHaveBeenCalled();
    // busy label shows "..." and the submit button is disabled
    const submit = screen.getByText('...') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('exposes the panel as a role=dialog (a11y)', () => {
    render(<BulkPasteDialog {...makeProps()} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });

  it('does NOT close on Escape when busy', () => {
    const onClose = vi.fn();
    render(<BulkPasteDialog {...makeProps({ onClose, busy: true })} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
});
