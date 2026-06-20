import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// i18n mock: `t` is a passthrough returning the key so we can assert on
// labels without depending on the real string table.
vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import PauseControl from './PauseControl';

const baseValue = { enabled: false, min: 1, max: 5 };

describe('PauseControl', () => {
  it('renders the label key via t() and an unchecked checkbox when disabled', () => {
    render(
      <PauseControl labelKey={'pause.min' as never} value={baseValue} onChange={vi.fn()} />,
    );
    expect(screen.getByText('pause.min')).toBeInTheDocument();
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it('hides the min/max inputs while disabled', () => {
    render(
      <PauseControl labelKey={'pause.min' as never} value={baseValue} onChange={vi.fn()} />,
    );
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
  });

  it('shows the min/max number inputs when enabled', () => {
    render(
      <PauseControl
        labelKey={'pause.min' as never}
        value={{ enabled: true, min: 2, max: 8 }}
        onChange={vi.fn()}
      />,
    );
    const spinners = screen.getAllByRole('spinbutton') as HTMLInputElement[];
    expect(spinners).toHaveLength(2);
    expect(spinners[0].value).toBe('2');
    expect(spinners[1].value).toBe('8');
  });

  it('calls onChange with enabled:true when the checkbox is toggled on', () => {
    const onChange = vi.fn();
    render(
      <PauseControl labelKey={'pause.min' as never} value={baseValue} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onChange).toHaveBeenCalledWith({ enabled: true, min: 1, max: 5 });
  });

  it('calls onChange with the new min, preserving other fields', () => {
    const onChange = vi.fn();
    render(
      <PauseControl
        labelKey={'pause.min' as never}
        value={{ enabled: true, min: 2, max: 8 }}
        onChange={onChange}
      />,
    );
    const minInput = (screen.getAllByRole('spinbutton') as HTMLInputElement[])[0];
    fireEvent.change(minInput, { target: { value: '3' } });
    expect(onChange).toHaveBeenCalledWith({ enabled: true, min: 3, max: 8 });
  });

  it('calls onChange with the new max, preserving other fields', () => {
    const onChange = vi.fn();
    render(
      <PauseControl
        labelKey={'pause.min' as never}
        value={{ enabled: true, min: 2, max: 8 }}
        onChange={onChange}
      />,
    );
    const maxInput = (screen.getAllByRole('spinbutton') as HTMLInputElement[])[1];
    fireEvent.change(maxInput, { target: { value: '12' } });
    expect(onChange).toHaveBeenCalledWith({ enabled: true, min: 2, max: 12 });
  });

  it('ignores a negative min (guard: n >= 0)', () => {
    const onChange = vi.fn();
    render(
      <PauseControl
        labelKey={'pause.min' as never}
        value={{ enabled: true, min: 2, max: 8 }}
        onChange={onChange}
      />,
    );
    const minInput = (screen.getAllByRole('spinbutton') as HTMLInputElement[])[0];
    fireEvent.change(minInput, { target: { value: '-4' } });
    expect(onChange).not.toHaveBeenCalled();
  });
});
