// Pure helpers for the category soft-archive feature.
// Spec: docs/superpowers/specs/2026-05-09-event-soft-archive-design.md §4.4.

export type CategoryStatus = 'evergreen' | 'upcoming' | 'active' | 'ended';

/**
 * Derive a category's temporal status from its event dates and "today".
 *
 * | start | end   | status                                  |
 * |-------|-------|------------------------------------------|
 * | ''    | ''    | evergreen (always shown)                 |
 * | set   | any   | upcoming when today < start              |
 * | any   | set   | ended when today > end                   |
 * | else  |       | active                                   |
 *
 * `today`, `start`, and `end` are all 'YYYY-MM-DD' strings; ISO date
 * strings sort lexically so no Date parsing is required.
 */
export function getCategoryStatus(
  start: string,
  end: string,
  today: string,
): CategoryStatus {
  if (!start && !end) return 'evergreen';
  if (start && today < start) return 'upcoming';
  if (end && today > end) return 'ended';
  return 'active';
}

/** User-local 'YYYY-MM-DD' (sv-SE locale formats the way we need). */
export function todayLocal(): string {
  return new Date().toLocaleDateString('sv-SE');
}

/**
 * Locale-aware month/day for the "Starts {date}" chip.
 *
 *   formatChipDate('2026-06-07', 'zh-TW') -> '6月7日'
 *   formatChipDate('2026-06-07', 'en-US') -> 'Jun 7'
 *
 * Treats the input as UTC so the formatter doesn't shift the wall-clock
 * day across timezones (we only care about month/day, not time).
 */
export function formatChipDate(iso: string, locale: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(dt);
}
