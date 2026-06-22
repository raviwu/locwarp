import { describe, it, expect } from 'vitest';
import {
  COLOR_PALETTE,
  getCategoryColor,
  makeResolveColor,
} from './categoryColor';

describe('getCategoryColor', () => {
  it('returns the built-in color for a known category', () => {
    expect(getCategoryColor('Default')).toBe('#4285f4');
    expect(getCategoryColor('Work')).toBe('#ff9800');
  });

  it('returns a deterministic hsl color for an unknown category', () => {
    const a = getCategoryColor('Trips');
    const b = getCategoryColor('Trips');
    expect(a).toBe(b);
    expect(a).toMatch(/^hsl\(\d+, 60%, 55%\)$/);
  });

  it('gives different unknown categories different hues (usually)', () => {
    expect(getCategoryColor('Alpha')).not.toBe(getCategoryColor('Zulu'));
  });
});

describe('COLOR_PALETTE', () => {
  it('exposes the preset swatches', () => {
    expect(COLOR_PALETTE.length).toBe(10);
    expect(COLOR_PALETTE[0]).toBe('#ef4444');
  });
});

describe('makeResolveColor', () => {
  it('prefers the stored color when present', () => {
    const resolve = makeResolveColor({ Work: '#123456' });
    expect(resolve('Work')).toBe('#123456');
  });

  it('falls back to the built-in / hash color when not stored', () => {
    const resolve = makeResolveColor({ Work: '#123456' });
    // Not in the stored map -> built-in.
    expect(resolve('Default')).toBe('#4285f4');
    // Not stored, not built-in -> hashed.
    expect(resolve('Trips')).toMatch(/^hsl\(/);
  });

  it('handles an undefined color map (all fallback)', () => {
    const resolve = makeResolveColor(undefined);
    expect(resolve('Default')).toBe('#4285f4');
    expect(resolve('Trips')).toMatch(/^hsl\(/);
  });
});
