import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';

// i18n -> identity translator. Interpolation params (the size-hint {size}) are
// appended so the test can assert the interpolated approxCellSizeMeters value
// flows through. Mirrors CategorySection.test.tsx.
const fakeT = (k: string, params?: Record<string, unknown>) =>
  params ? `${k}:${Object.values(params).join(',')}` : k;
vi.mock('../i18n', () => ({
  useT: () => fakeT,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: fakeT }),
}));

import { S2LevelPicker } from './S2LevelPicker';

// Defaults satisfying the prop contract; each test overrides what it asserts.
function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    open: true,
    onClose: vi.fn(),
    s2Enabled: false,
    setS2Enabled: vi.fn(),
    s2Level: 17,
    setS2Level: vi.fn(),
    s2Suppressed: false,
    lat: 0,
    ...over,
  } as any;
}

describe('S2LevelPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // --- open gating ----------------------------------------------------------
  it('renders nothing when open=false', () => {
    const { container } = render(<S2LevelPicker {...makeProps({ open: false })} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the picker when open=true', () => {
    const { getByText } = render(<S2LevelPicker {...makeProps()} />);
    // The header label key renders.
    expect(getByText('map.s2_level_label')).toBeTruthy();
  });

  // --- level options (quick-pick chips L13..L19) ----------------------------
  it('renders the quick-pick level chips L13..L19', () => {
    const { getByRole } = render(<S2LevelPicker {...makeProps()} />);
    // The chips are <button>L{lv}</button>. Scope by button role so the chip
    // text doesn't collide with the L{s2Level} readout <span> (e.g. L17).
    for (const lv of [13, 14, 15, 16, 17, 18, 19]) {
      expect(getByRole('button', { name: `L${lv}` })).toBeTruthy();
    }
  });

  it('renders the current level readout (L{s2Level})', () => {
    const { container } = render(<S2LevelPicker {...makeProps({ s2Level: 20 })} />);
    // The monospace readout span next to the range slider shows L20. (L20 is
    // not one of the quick-pick chips, so this uniquely pins the readout.)
    const readout = Array.from(container.querySelectorAll('span')).find(
      (s) => s.textContent === 'L20',
    );
    expect(readout).toBeTruthy();
  });

  // --- clicking a level chip calls setS2Level with that level ---------------
  it('calls setS2Level with the chip level when a quick-pick chip is clicked', () => {
    const setS2Level = vi.fn();
    const { getByRole } = render(<S2LevelPicker {...makeProps({ setS2Level })} />);
    fireEvent.click(getByRole('button', { name: 'L14' }));
    expect(setS2Level).toHaveBeenCalledTimes(1);
    expect(setS2Level).toHaveBeenCalledWith(14);
  });

  // --- range slider drives setS2Level with the parsed value -----------------
  it('calls setS2Level with the parsed slider value on range change', () => {
    const setS2Level = vi.fn();
    const { container } = render(<S2LevelPicker {...makeProps({ setS2Level })} />);
    const range = container.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(range, { target: { value: '11' } });
    expect(setS2Level).toHaveBeenCalledWith(11);
  });

  // --- close button ---------------------------------------------------------
  it('calls onClose when the × button is clicked', () => {
    const onClose = vi.fn();
    const { getByLabelText } = render(<S2LevelPicker {...makeProps({ onClose })} />);
    fireEvent.click(getByLabelText('close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // --- on/off toggle --------------------------------------------------------
  it('renders the s2_off label + calls setS2Enabled when disabled', () => {
    const setS2Enabled = vi.fn();
    const { getByText } = render(
      <S2LevelPicker {...makeProps({ s2Enabled: false, setS2Enabled })} />,
    );
    const toggle = getByText('map.s2_off');
    fireEvent.click(toggle);
    expect(setS2Enabled).toHaveBeenCalledTimes(1);
  });

  it('renders the s2_on label when enabled', () => {
    const { getByText } = render(<S2LevelPicker {...makeProps({ s2Enabled: true })} />);
    expect(getByText('map.s2_on')).toBeTruthy();
  });

  // --- suppressed hint: shown only when enabled AND suppressed --------------
  it('shows the zoom-in hint when enabled AND suppressed', () => {
    const { queryByText } = render(
      <S2LevelPicker {...makeProps({ s2Enabled: true, s2Suppressed: true })} />,
    );
    expect(queryByText('map.s2_zoom_in_hint')).toBeTruthy();
  });

  it('hides the zoom-in hint when suppressed but the grid is disabled', () => {
    const { queryByText } = render(
      <S2LevelPicker {...makeProps({ s2Enabled: false, s2Suppressed: true })} />,
    );
    expect(queryByText('map.s2_zoom_in_hint')).toBeNull();
  });

  it('hides the zoom-in hint when enabled but not suppressed', () => {
    const { queryByText } = render(
      <S2LevelPicker {...makeProps({ s2Enabled: true, s2Suppressed: false })} />,
    );
    expect(queryByText('map.s2_zoom_in_hint')).toBeNull();
  });

  // --- size hint: interpolated approxCellSizeMeters flows through -----------
  it('renders the size hint with the interpolated cell-size label', () => {
    const { getByText } = render(<S2LevelPicker {...makeProps({ s2Level: 17, lat: 0 })} />);
    // fakeT appends the interpolated {size}; the picker formats approxCellSizeMeters
    // into a "N m" / "N.N km" label, so the key prefix + a trailing unit appear.
    const hint = getByText((text) => text.startsWith('map.s2_size_hint:'));
    expect(hint).toBeTruthy();
    expect(hint.textContent).toMatch(/map\.s2_size_hint:.*(m|km)$/);
  });
});
