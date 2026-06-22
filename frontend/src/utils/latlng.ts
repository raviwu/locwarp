/**
 * Split "24.14, 120.65" (or tab/whitespace-separated) into [lat, lng] so a user
 * can paste a Google-Maps-style pair into a single field instead of splitting it
 * themselves. Returns null when the string is not a clean numeric pair (e.g. the
 * user is still typing the first number) so callers can keep the raw text.
 */
export function trySplitLatLng(s: string): [string, string] | null {
  const m = s.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\t ]\s*(-?\d+(?:\.\d+)?)\s*$/);
  return m ? [m[1], m[2]] : null;
}
