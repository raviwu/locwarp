import type { KeyboardEvent } from 'react';

/**
 * True while an IME (Chinese / Japanese / Korean, etc.) is composing a
 * character. The Enter that confirms candidate selection must NOT be treated
 * as a submit. `keyCode === 229` is the sentinel browsers emit for any keydown
 * still being processed by the IME; it is a defensive fallback for engines that
 * do not set `isComposing` reliably. The two co-occur in modern browsers and
 * are not mutually exclusive.
 */
export function isImeComposing(e: KeyboardEvent): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}

/**
 * True only for a deliberate Enter that should submit — Enter pressed when NOT
 * mid-IME-composition.
 */
export function isSubmitEnter(e: KeyboardEvent): boolean {
  return e.key === 'Enter' && !isImeComposing(e);
}
