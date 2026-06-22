import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import AddBookmarkDialog from './AddBookmarkDialog';

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    open: true,
    name: '',
    category: 'Default',
    categories: ['Default', 'Work'],
    hasPosition: true,
    displayCat: (n: string) => n,
    onNameChange: vi.fn(),
    onCategoryChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('AddBookmarkDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<AddBookmarkDialog {...makeProps({ open: false })} />);
    expect(container.firstChild).toBeNull();
  });

  it('fires onNameChange while typing', () => {
    const onNameChange = vi.fn();
    render(<AddBookmarkDialog {...makeProps({ onNameChange })} />);
    fireEvent.change(screen.getByPlaceholderText('bm.name_placeholder'), {
      target: { value: 'Cafe' },
    });
    expect(onNameChange).toHaveBeenCalledWith('Cafe');
  });

  it('fires onSubmit on the Save button', () => {
    const onSubmit = vi.fn();
    render(<AddBookmarkDialog {...makeProps({ name: 'Cafe', onSubmit })} />);
    fireEvent.click(screen.getByText('generic.save'));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('fires onSubmit on Enter', () => {
    const onSubmit = vi.fn();
    render(<AddBookmarkDialog {...makeProps({ name: 'Cafe', onSubmit })} />);
    fireEvent.keyDown(screen.getByPlaceholderText('bm.name_placeholder'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('shows the no-position hint when hasPosition is false', () => {
    render(<AddBookmarkDialog {...makeProps({ hasPosition: false })} />);
    expect(screen.getByText('bm.no_position')).toBeTruthy();
  });
});
