import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import RoutePasteDialog from './RoutePasteDialog';

// Minimal parse stub mirroring App.parseRoutePaste's shape.
const parse = (raw: string) => {
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
  const valid = lines.filter((l) => !l.includes('bad')).map(() => ({ lat: 1, lng: 2 }));
  return { valid, invalidCount: lines.length - valid.length, totalLines: lines.length };
};

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    open: true,
    text: '',
    parse,
    onTextChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    onClipboardBlocked: vi.fn(),
    ...over,
  } as any;
}

describe('RoutePasteDialog', () => {
  it('renders nothing when closed', () => {
    render(<RoutePasteDialog {...makeProps({ open: false })} />);
    expect(screen.queryByText('panel.route_paste_title')).toBeNull();
  });

  it('fires onTextChange while typing', () => {
    const onTextChange = vi.fn();
    render(<RoutePasteDialog {...makeProps({ onTextChange })} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '1 2\n3 4' } });
    expect(onTextChange).toHaveBeenCalledWith('1 2\n3 4');
  });

  it('disables submit with no valid lines, enables once valid lines exist', () => {
    const { rerender } = render(<RoutePasteDialog {...makeProps({ text: '' })} />);
    const empty = screen.getByText('panel.route_paste_submit (0)') as HTMLButtonElement;
    expect(empty.disabled).toBe(true);
    rerender(<RoutePasteDialog {...makeProps({ text: '1 2\n3 4\n5 6' })} />);
    const ready = screen.getByText('panel.route_paste_submit (3)') as HTMLButtonElement;
    expect(ready.disabled).toBe(false);
  });

  it('fires onSubmit on click (teleport + setWaypoints stay in App)', () => {
    const onSubmit = vi.fn();
    render(<RoutePasteDialog {...makeProps({ onSubmit, text: '1 2' })} />);
    fireEvent.click(screen.getByText('panel.route_paste_submit (1)'));
    // The dialog forwards the click to App's param-less submitRoutePaste; it
    // carries no parsed payload — App re-parses its own text state.
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('reads the clipboard and pipes it into onTextChange', async () => {
    const onTextChange = vi.fn();
    Object.assign(navigator, {
      clipboard: { readText: vi.fn().mockResolvedValue('25.0 121.0') },
    });
    render(<RoutePasteDialog {...makeProps({ onTextChange })} />);
    fireEvent.click(screen.getByText('panel.route_paste_from_clipboard'));
    await waitFor(() => expect(onTextChange).toHaveBeenCalledWith('25.0 121.0'));
  });

  it('fires onClipboardBlocked when the clipboard read throws', async () => {
    const onClipboardBlocked = vi.fn();
    Object.assign(navigator, {
      clipboard: { readText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    render(<RoutePasteDialog {...makeProps({ onClipboardBlocked })} />);
    fireEvent.click(screen.getByText('panel.route_paste_from_clipboard'));
    await waitFor(() => expect(onClipboardBlocked).toHaveBeenCalledTimes(1));
  });

  it('exposes the panel as a role=dialog (a11y)', () => {
    render(<RoutePasteDialog {...makeProps()} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });
});
