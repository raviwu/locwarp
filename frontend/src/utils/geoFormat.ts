// Geo display formatting for bookmark labels — short country name + GMT
// offset. Both derive from the browser's built-in Intl data, so no
// country or timezone table ships with the app.
import type { Lang } from '../i18n';

// "越短越好": Intl.DisplayNames returns the full ICU name ("United
// States", "United Kingdom"); override the handful too long for a label.
const SHORT_OVERRIDES: Record<string, { zh: string; en: string }> = {
  US: { zh: '美國', en: 'USA' },
  GB: { zh: '英國', en: 'UK' },
  AE: { zh: '阿聯', en: 'UAE' },
  KR: { zh: '南韓', en: 'S. Korea' },
  KP: { zh: '北韓', en: 'N. Korea' },
  RU: { zh: '俄羅斯', en: 'Russia' },
  CZ: { zh: '捷克', en: 'Czechia' },
  CD: { zh: '剛果（金）', en: 'DR Congo' },
};

const _displayNamesCache: Partial<Record<Lang, Intl.DisplayNames>> = {};

function displayNamesFor(lang: Lang): Intl.DisplayNames | null {
  const cached = _displayNamesCache[lang];
  if (cached) return cached;
  try {
    const locale = lang === 'zh' ? 'zh-Hant' : 'en';
    const dn = new Intl.DisplayNames([locale], { type: 'region' });
    _displayNamesCache[lang] = dn;
    return dn;
  } catch {
    return null;
  }
}

// country code (any case) -> short, localized country name. Falls back to
// the uppercased ISO code when Intl cannot resolve it.
export function countryName(code: string | undefined, lang: Lang): string {
  if (!code) return '';
  const cc = code.toUpperCase();
  const override = SHORT_OVERRIDES[cc];
  if (override) return override[lang];
  const dn = displayNamesFor(lang);
  try {
    return (dn && dn.of(cc)) || cc;
  } catch {
    return cc;
  }
}

// IANA zone -> "GMT+8" / "GMT-5:30". Empty string when the zone is blank
// or unrecognized.
export function formatGmtOffset(timezone: string | undefined): string {
  if (!timezone) return '';
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      timeZoneName: 'shortOffset',
    }).formatToParts(new Date());
    const tzName = parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
    // shortOffset yields "GMT+8" / "GMT" (for UTC); normalize "GMT" → "GMT+0".
    return tzName === 'GMT' ? 'GMT+0' : tzName;
  } catch {
    return '';
  }
}
