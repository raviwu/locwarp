import type { Lang } from '../i18n';
import { countryName } from './geoFormat';

// Sentinel for "bookmarks with no country_code". Not a valid ISO code, so it
// never collides with a real country.
export const UNKNOWN_COUNTRY = '__unknown__';

// Minimal structural shape — the util only reads country_code. There is no
// shared Bookmark type in the codebase (each component redeclares its own), so
// typing against this narrow interface keeps the util decoupled and lets the
// component pass its local Bookmark[] without conversion.
interface HasCountry {
  country_code?: string;
}

export interface CountryOption {
  code: string;   // ISO alpha-2 (lowercase) or UNKNOWN_COUNTRY
  name: string;   // localized display label
  count: number;  // number of bookmarks in this bucket
}

/**
 * Distinct countries present in the bookmark set, each with its count, sorted
 * by localized name. Appends an Unknown bucket (UNKNOWN_COUNTRY, labeled with
 * `unknownLabel`) ONLY when at least one bookmark has an empty/absent
 * country_code; that bucket always sorts last.
 */
export function availableCountries(
  bookmarks: HasCountry[],
  lang: Lang,
  unknownLabel: string,
): CountryOption[] {
  const counts = new Map<string, number>();
  let unknown = 0;
  for (const bm of bookmarks) {
    const code = (bm.country_code ?? '').trim().toLowerCase();
    if (!code) {
      unknown += 1;
      continue;
    }
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  const locale = lang === 'zh' ? 'zh-Hant' : 'en';
  const named: CountryOption[] = [...counts.entries()]
    .map(([code, count]) => ({ code, name: countryName(code, lang), count }))
    .sort((a, b) => a.name.localeCompare(b.name, locale));
  if (unknown > 0) {
    named.push({ code: UNKNOWN_COUNTRY, name: unknownLabel, count: unknown });
  }
  return named;
}

/**
 * Filter bookmarks by selected code.
 * - ''               => all (returns the input array unchanged, by reference)
 * - UNKNOWN_COUNTRY  => bookmarks with empty/absent country_code
 * - otherwise        => case-insensitive country_code match
 * Generic so it returns the caller's concrete element type unchanged.
 */
export function filterByCountry<T extends HasCountry>(items: T[], code: string): T[] {
  if (!code) return items;
  if (code === UNKNOWN_COUNTRY) {
    return items.filter((b) => !(b.country_code ?? '').trim());
  }
  const target = code.toLowerCase();
  return items.filter((b) => (b.country_code ?? '').trim().toLowerCase() === target);
}
