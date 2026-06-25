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

/**
 * True when the event target is a text-entry element — an INPUT, a TEXTAREA,
 * or any contentEditable host. The app-level global keydown listener uses
 * this to BAIL OUT so single-key shortcuts (Space / R / P / B) never fire
 * while the user is typing into the address search, a coordinate field, or
 * any dialog input. Takes the raw `EventTarget` (native `KeyboardEvent.target`
 * is `EventTarget | null`) so it works outside React's synthetic events.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (target === null) return false;
  const el = target as HTMLElement;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
  return el.isContentEditable === true;
}
