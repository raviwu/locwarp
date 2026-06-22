import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import EditCategoryModal from './EditCategoryModal';

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    categoryName: 'Trips',
    newName: 'Trips',
    color: '#6366f1',
    startDate: '',
    endDate: '',
    onNewNameChange: vi.fn(),
    onColorChange: vi.fn(),
    onStartDateChange: vi.fn(),
    onEndDateChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn(),
    ...over,
  } as any;
}

describe('EditCategoryModal', () => {
  it('renders nothing when categoryName is null', () => {
    const { container } = render(<EditCategoryModal {...makeProps({ categoryName: null })} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText('bm.cat.edit_title')).toBeNull();
  });

  it('fires onNewNameChange while typing the name', () => {
    const onNewNameChange = vi.fn();
    render(<EditCategoryModal {...makeProps({ onNewNameChange })} />);
    fireEvent.change(screen.getByDisplayValue('Trips'), { target: { value: 'Vacations' } });
    expect(onNewNameChange).toHaveBeenCalledWith('Vacations');
  });

  it('fires onColorChange when a palette swatch is clicked', () => {
    const onColorChange = vi.fn();
    render(<EditCategoryModal {...makeProps({ onColorChange })} />);
    // The palette swatches carry their hex as a title.
    fireEvent.click(screen.getByTitle('#22c55e'));
    expect(onColorChange).toHaveBeenCalledWith('#22c55e');
  });

  it('submits (originalName, patch) with the current values on Save', () => {
    const onSubmit = vi.fn();
    render(
      <EditCategoryModal
        {...makeProps({
          categoryName: 'Trips',
          newName: 'Vacations',
          color: '#ef4444',
          startDate: '2026-01-01',
          endDate: '2026-12-31',
          onSubmit,
        })}
      />,
    );
    fireEvent.click(screen.getByText('bm.cat.save'));
    expect(onSubmit).toHaveBeenCalledWith('Trips', {
      name: 'Vacations',
      color: '#ef4444',
      start_date: '2026-01-01',
      end_date: '2026-12-31',
    });
  });

  it('disables Save and does not submit when start > end', () => {
    const onSubmit = vi.fn();
    render(
      <EditCategoryModal
        {...makeProps({
          newName: 'Vacations',
          startDate: '2026-12-31',
          endDate: '2026-01-01',
          onSubmit,
        })}
      />,
    );
    const save = screen.getByText('bm.cat.save') as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(onSubmit).not.toHaveBeenCalled();
    // The invalid-range message renders.
    expect(screen.getByText('bm.cat.dates_invalid')).toBeTruthy();
  });
});
