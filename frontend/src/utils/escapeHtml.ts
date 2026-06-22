/**
 * Escape the five HTML-significant characters so user-supplied strings
 * (e.g. bookmark names) can be safely interpolated into the raw HTML
 * strings handed to `L.divIcon({ html })` / `L.popup().setContent()`.
 *
 * Pure: inputs -> string. No DOM, no Leaflet.
 */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
