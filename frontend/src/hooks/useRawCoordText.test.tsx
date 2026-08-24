/**
 * The single "lat, lng" field must display the user's RAW text.
 *
 * Regression guard for the coordinate-truncation bug: the field used to re-derive
 * its value as `${lat}, ${lng}` on every keystroke, so any input that normalised
 * to the same pair (trailing space, tab separator, pasted leading whitespace) was
 * silently rewritten. The rewritten DOM string moved the caret to the end of the
 * input, and the user's next Backspace ate the last digit of the LONGITUDE
 * (121.5654 -> 121.565 = 40 m, a second press -> 121.56 = 545 m).
 */
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useRawCoordText } from './useRawCoordText';

describe('useRawCoordText', () => {
  it('starts from the derived text when the field is seeded by the parent', () => {
    const { result } = renderHook(() => useRawCoordText('25.033064', '121.5654'));
    expect(result.current.value).toBe('25.033064, 121.5654');
  });

  it('is empty when the parent has nothing seeded', () => {
    const { result } = renderHook(() => useRawCoordText('', ''));
    expect(result.current.value).toBe('');
  });

  it('keeps a trailing space the user typed', () => {
    const { result, rerender } = renderHook(
      ({ lat, lng }) => useRawCoordText(lat, lng),
      { initialProps: { lat: '', lng: '' } },
    );
    act(() => result.current.setRaw('25.033064, 121.5654 '));
    // The parent stores the parsed halves, which normalise the text away.
    rerender({ lat: '25.033064', lng: '121.5654' });
    expect(result.current.value).toBe('25.033064, 121.5654 ');
  });

  it('keeps the separator the user typed (tab)', () => {
    const { result, rerender } = renderHook(
      ({ lat, lng }) => useRawCoordText(lat, lng),
      { initialProps: { lat: '', lng: '' } },
    );
    act(() => result.current.setRaw('25.033064\t121.5654'));
    rerender({ lat: '25.033064', lng: '121.5654' });
    expect(result.current.value).toBe('25.033064\t121.5654');
  });

  it('keeps pasted leading whitespace', () => {
    const { result, rerender } = renderHook(
      ({ lat, lng }) => useRawCoordText(lat, lng),
      { initialProps: { lat: '', lng: '' } },
    );
    act(() => result.current.setRaw('  25.033064, 121.5654'));
    rerender({ lat: '25.033064', lng: '121.5654' });
    expect(result.current.value).toBe('  25.033064, 121.5654');
  });

  it('keeps unparseable partial input verbatim', () => {
    const { result, rerender } = renderHook(
      ({ lat, lng }) => useRawCoordText(lat, lng),
      { initialProps: { lat: '', lng: '' } },
    );
    act(() => result.current.setRaw('25.033064, '));
    // No valid pair yet: the parent keeps the raw text in lat and clears lng.
    rerender({ lat: '25.033064, ', lng: '' });
    expect(result.current.value).toBe('25.033064, ');
  });

  it('adopts the derived text when the parent reseeds the field', () => {
    const { result, rerender } = renderHook(
      ({ lat, lng }) => useRawCoordText(lat, lng),
      { initialProps: { lat: '', lng: '' } },
    );
    act(() => result.current.setRaw('25.033064, 121.5654 '));
    rerender({ lat: '25.033064', lng: '121.5654' });
    // Dialog reopened on a different bookmark — raw text no longer corresponds.
    rerender({ lat: '35.6586', lng: '139.7454' });
    expect(result.current.value).toBe('35.6586, 139.7454');
  });
});
