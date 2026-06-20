import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// Controllable i18n mock: tests flip `currentLang` to drive `lang`,
// and assert `setLang` is invoked on click.
const setLang = vi.fn();
let currentLang: 'zh' | 'en' = 'zh';

vi.mock('../i18n', () => ({
  useI18n: () => ({ lang: currentLang, setLang, t: (k: string) => k }),
}));

import LangToggle from './LangToggle';

describe('LangToggle', () => {
  beforeEach(() => {
    setLang.mockClear();
    currentLang = 'zh';
  });

  it('renders both language buttons', () => {
    render(<LangToggle />);
    expect(screen.getByRole('button', { name: '中文' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'EN' })).toBeInTheDocument();
  });

  it('marks the active language (zh) with the accent color and weight', () => {
    currentLang = 'zh';
    render(<LangToggle />);
    const zh = screen.getByRole('button', { name: '中文' });
    const en = screen.getByRole('button', { name: 'EN' });
    expect(zh).toHaveStyle({ color: 'rgb(108, 140, 255)', fontWeight: '600' });
    // inactive button uses the muted color, not the accent
    expect(en).not.toHaveStyle({ color: 'rgb(108, 140, 255)' });
  });

  it('marks the active language (en) when lang is en', () => {
    currentLang = 'en';
    render(<LangToggle />);
    const en = screen.getByRole('button', { name: 'EN' });
    expect(en).toHaveStyle({ color: 'rgb(108, 140, 255)', fontWeight: '600' });
  });

  it('calls setLang("zh") when the 中文 button is clicked', () => {
    render(<LangToggle />);
    fireEvent.click(screen.getByRole('button', { name: '中文' }));
    expect(setLang).toHaveBeenCalledTimes(1);
    expect(setLang).toHaveBeenCalledWith('zh');
  });

  it('calls setLang("en") when the EN button is clicked', () => {
    render(<LangToggle />);
    fireEvent.click(screen.getByRole('button', { name: 'EN' }));
    expect(setLang).toHaveBeenCalledTimes(1);
    expect(setLang).toHaveBeenCalledWith('en');
  });
});
