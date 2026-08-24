// Shared coordinate-parsing helpers. Used by the coord-fly input and the
// bulk-paste route / bookmark dialogs. Goal: scrape the first valid
// lat/lng pair out of arbitrary text so users can paste lines like
// "(-33.41902, -70.70187) 一般火" or "#3\n35.018, 135.584" without
// hand-cleaning them first.

// Brackets / quotes / degree symbols are turned into spaces so they can't
// glue numbers to surrounding labels and so leftover-text extraction (for
// the bookmark "name" field) doesn't have to special-case them.
const DECORATION_RE = /[()\[\]{}（）【】「」『』"'`°]/g;

// Decimal-required main pattern. The lookarounds (?<![\d.]) / (?![\d.])
// stop us from chopping a longer number like "12.345" mid-way and keep us
// from grabbing the "3" out of a label like "#3" then pairing it with the
// next number on the line. The `[^-\d.]+` between the two numbers means
// any non-numeric junk works as a separator: `, ` / `,lng=` / ` B ` /
// `:` / arbitrary CJK characters all qualify. `-` is intentionally
// excluded so a negative sign on the second number stays attached.
const COORD_DECIMAL_RE = /(?<![\d.])(-?\d+\.\d+)[^-\d.]+(-?\d+\.\d+)(?![\d.])/g;

// Fallback for users who type integer-only coords like "25, 121". Only
// used when the entire trimmed input is just two numbers, so a stray
// integer label can never be misread as a coord here.
const COORD_INTEGER_RE = /^(-?\d+(?:\.\d+)?)\s*[,;\s]+\s*(-?\d+(?:\.\d+)?)$/;

function inRange(lat: number, lng: number): boolean {
  return Number.isFinite(lat) && lat >= -90 && lat <= 90 &&
    Number.isFinite(lng) && lng >= -180 && lng <= 180;
}

// A map-share URL carries SEVERAL coordinate pairs, and the leftmost one is the
// worst: `/@lat,lng,17z` is where the camera was pointing, which sits tens to
// hundreds of metres from the place itself (117 m for a Taipei 101 share link).
// A plain left-to-right scrape therefore silently picks the wrong point. The
// precedence below is the one CLAUDE.md already fixes for the catalog seeder:
// the `!3d/!4d` pin first, then an explicit `ll=`/`q=` pair, and only then does
// the generic scrape get to fall back on `/@`.
const MAPS_PIN_RE = /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/;
const MAPS_QUERY_RE = /[?&](?:ll|q|sll|daddr)=(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/;

// Returns the authoritative pair from a map URL, or null when the text is not a
// map URL (or its preferred pair is out of range, in which case the caller's
// generic scrape still gets its turn).
function parseMapUrlCoord(raw: string): { lat: number; lng: number } | null {
  for (const re of [MAPS_PIN_RE, MAPS_QUERY_RE]) {
    const m = raw.match(re);
    if (!m) continue;
    const lat = parseFloat(m[1]);
    const lng = parseFloat(m[2]);
    if (inRange(lat, lng)) return { lat, lng };
  }
  return null;
}

// Returns the first valid lat/lng pair found anywhere in `raw`, or null.
// Any other text in the input is ignored — labels, prefixes ("#3", "OK"),
// trailing notes ("一般火"), brackets, etc. all get discarded.
export function parseCoord(raw: string): { lat: number; lng: number } | null {
  const pin = parseMapUrlCoord(raw);
  if (pin) return pin;
  const cleaned = raw.replace(DECORATION_RE, ' ');
  COORD_DECIMAL_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = COORD_DECIMAL_RE.exec(cleaned)) !== null) {
    const lat = parseFloat(m[1]);
    const lng = parseFloat(m[2]);
    if (inRange(lat, lng)) return { lat, lng };
  }
  const fb = cleaned.trim().match(COORD_INTEGER_RE);
  if (fb) {
    const lat = parseFloat(fb[1]);
    const lng = parseFloat(fb[2]);
    if (inRange(lat, lng)) return { lat, lng };
  }
  return null;
}

// Strict whole-input pair splitter. Unlike parseCoord (which scrapes the
// first valid pair out of arbitrary text and range-checks it), this returns
// the RAW string halves with NO range check, so the bookmark dialogs can keep
// partial text while the user is still typing. Separator class is exactly one
// comma / tab / space — intentionally narrower than parseCoord's fallback.
export function trySplitLatLng(s: string): [string, string] | null {
  const m = s.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\t ]\s*(-?\d+(?:\.\d+)?)\s*$/);
  return m ? [m[1], m[2]] : null;
}
