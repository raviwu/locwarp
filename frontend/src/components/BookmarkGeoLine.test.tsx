import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// Only the language is mocked; geoFormat (Intl-backed) runs for real so
// the test asserts the actual country/offset strings the component shows.
let currentLang: 'zh' | 'en' = 'en';
vi.mock('../i18n', () => ({
  useI18n: () => ({ lang: currentLang, setLang: vi.fn(), t: (k: string) => k }),
}));

import { BookmarkGeoLine } from './BookmarkGeoLine';

describe('BookmarkGeoLine', () => {
  beforeEach(() => {
    currentLang = 'en';
  });

  it('renders flag · country · city · GMT offset joined by " · "', () => {
    const { container } = render(
      <BookmarkGeoLine countryCode="jp" city="Tokyo" timezone="Asia/Tokyo" />,
    );
    // Japan resolves via Intl.DisplayNames; offset via shortOffset.
    const text = container.querySelector('span > span')?.textContent;
    expect(text).toBe('Japan · Tokyo · GMT+9');
  });

  it('renders the flag image from flagcdn with an uppercased alt', () => {
    render(<BookmarkGeoLine countryCode="jp" city="Tokyo" timezone="Asia/Tokyo" />);
    const img = screen.getByRole('img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('https://flagcdn.com/w20/jp.png');
    expect(img.getAttribute('alt')).toBe('JP');
  });

  it('uses the short override + localized name in zh', () => {
    currentLang = 'zh';
    const { container } = render(
      <BookmarkGeoLine countryCode="us" city="Austin" timezone="America/Chicago" />,
    );
    const text = container.querySelector('span > span')?.textContent;
    // US override -> 美國 (zh); America/Chicago is GMT-5 or GMT-6 depending
    // on DST, so assert the stable parts.
    expect(text).toContain('美國');
    expect(text).toContain('Austin');
    expect(text).toMatch(/GMT-[56]/);
  });

  it('omits the city segment when city is missing', () => {
    const { container } = render(
      <BookmarkGeoLine countryCode="jp" timezone="Asia/Tokyo" />,
    );
    const text = container.querySelector('span > span')?.textContent;
    expect(text).toBe('Japan · GMT+9');
  });

  it('omits the offset segment when timezone is missing', () => {
    const { container } = render(<BookmarkGeoLine countryCode="jp" city="Tokyo" />);
    const text = container.querySelector('span > span')?.textContent;
    expect(text).toBe('Japan · Tokyo');
  });

  it('still renders the flag when only countryCode is present (textParts empty)', () => {
    // Unknown code that Intl can resolve to its own uppercase fallback is
    // not empty; use a code Intl returns as-is. "ZZ" is a user-assigned
    // code Intl may not resolve, falling back to "ZZ" — still a textPart.
    render(<BookmarkGeoLine countryCode="jp" />);
    const img = screen.getByRole('img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('https://flagcdn.com/w20/jp.png');
  });

  it('returns null when there is no countryCode and no resolvable text', () => {
    const { container } = render(<BookmarkGeoLine />);
    expect(container.firstChild).toBeNull();
  });

  it('hides the flag image on load error', () => {
    render(<BookmarkGeoLine countryCode="jp" city="Tokyo" timezone="Asia/Tokyo" />);
    const img = screen.getByRole('img') as HTMLImageElement;
    fireEvent.error(img);
    expect(img.style.display).toBe('none');
  });
});
