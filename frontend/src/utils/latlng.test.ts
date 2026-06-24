import { describe, it, expect } from 'vitest';
import { trySplitLatLng } from './latlng';

describe('trySplitLatLng', () => {
  it('splits a comma-separated pair', () => {
    expect(trySplitLatLng('24.14, 120.65')).toEqual(['24.14', '120.65']);
  });

  it('splits a pair with no space after the comma', () => {
    expect(trySplitLatLng('24.14,120.65')).toEqual(['24.14', '120.65']);
  });

  it('splits a whitespace-separated pair', () => {
    expect(trySplitLatLng('24.14 120.65')).toEqual(['24.14', '120.65']);
  });

  it('splits a tab-separated pair', () => {
    expect(trySplitLatLng('24.14\t120.65')).toEqual(['24.14', '120.65']);
  });

  it('handles negative coordinates', () => {
    expect(trySplitLatLng('-33.86, -151.20')).toEqual(['-33.86', '-151.20']);
  });

  it('splits integer (no-decimal) pairs', () => {
    expect(trySplitLatLng('25, 121')).toEqual(['25', '121']);
  });

  it('trims surrounding whitespace', () => {
    expect(trySplitLatLng('  24.14, 120.65  ')).toEqual(['24.14', '120.65']);
  });

  it('returns null while the user is still typing the first number', () => {
    expect(trySplitLatLng('24.1')).toBeNull();
  });

  it('returns null for a single trailing comma', () => {
    expect(trySplitLatLng('24.14,')).toBeNull();
  });

  it('returns null for non-numeric input', () => {
    expect(trySplitLatLng('Taipei 101')).toBeNull();
  });

  it('still exports trySplitLatLng from the latlng module (shim)', () => {
    expect(typeof trySplitLatLng).toBe('function')
    expect(trySplitLatLng('1.0, 2.0')).toEqual(['1.0', '2.0'])
  })
});
