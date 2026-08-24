import { useState } from 'react';
import { trySplitLatLng } from '../utils/coords';

/**
 * Holds the RAW text of a single "lat, lng" input while the parent keeps the
 * parsed halves.
 *
 * Why this exists: the dialogs used to render the field as a value re-derived
 * from the parsed halves (`${lat}, ${lng}`). Any text that normalised to the
 * same pair — a trailing space, a tab separator, pasted surrounding whitespace,
 * a missing space after the comma — was silently rewritten on that keystroke.
 * Because the DOM string changed, the browser put the caret at the END of the
 * input instead of where the user was editing, so the keystroke looked like a
 * no-op and the NEXT one landed at the end: one Backspace ate the last digit of
 * the longitude (121.5654 -> 121.565, ~40 m), a second ate the next one
 * (121.56, ~545 m). The truncated coordinate was then saved as typed-in ground
 * truth, so the bookmark was wrong from the moment it was created.
 *
 * Returning the raw text keeps the DOM string byte-identical to what the user
 * typed, so the caret is never moved and no digit can be silently eaten.
 */
export function useRawCoordText(lat: string, lng: string) {
  const derived = lat && lng ? `${lat}, ${lng}` : lat || lng;
  const [raw, setRaw] = useState(derived);

  // The parent reseeded the field — the dialog reopened on another bookmark, or
  // the parent reset it after a submit — when its lat/lng no longer parse out of
  // our raw text. Fall back to the derived text for that render; the next
  // keystroke makes the raw text authoritative again.
  const split = trySplitLatLng(raw);
  const matches = split
    ? split[0] === lat && split[1] === lng
    : raw === lat && lng === '';

  return { value: matches ? raw : derived, setRaw };
}
