import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { categorize, labelKeyFor, WeatherIcon, type WeatherCat } from './WeatherIcon';

describe('categorize — WMO weather_code → category', () => {
  it('returns null for null/undefined', () => {
    expect(categorize(null)).toBeNull();
    expect(categorize(undefined)).toBeNull();
  });

  it('maps clear sky (0)', () => {
    expect(categorize(0)).toBe('clear');
  });

  it('maps mainly clear / partly cloudy (1, 2) to partly', () => {
    expect(categorize(1)).toBe('partly');
    expect(categorize(2)).toBe('partly');
  });

  it('maps overcast (3) to cloudy', () => {
    expect(categorize(3)).toBe('cloudy');
  });

  it('maps fog codes (45, 48)', () => {
    expect(categorize(45)).toBe('fog');
    expect(categorize(48)).toBe('fog');
  });

  it('maps drizzle range 51..57', () => {
    expect(categorize(51)).toBe('drizzle');
    expect(categorize(53)).toBe('drizzle');
    expect(categorize(57)).toBe('drizzle');
  });

  it('maps rain ranges 61..67 and shower 80..82', () => {
    expect(categorize(61)).toBe('rain');
    expect(categorize(67)).toBe('rain');
    expect(categorize(80)).toBe('rain');
    expect(categorize(82)).toBe('rain');
  });

  it('maps snow ranges 71..77 and 85/86', () => {
    expect(categorize(71)).toBe('snow');
    expect(categorize(77)).toBe('snow');
    expect(categorize(85)).toBe('snow');
    expect(categorize(86)).toBe('snow');
  });

  it('maps thunderstorm codes (95, 96, 99) to storm', () => {
    expect(categorize(95)).toBe('storm');
    expect(categorize(96)).toBe('storm');
    expect(categorize(99)).toBe('storm');
  });

  it('falls back to cloudy for unknown/uncategorized codes', () => {
    expect(categorize(4)).toBe('cloudy');
    expect(categorize(58)).toBe('cloudy');
    expect(categorize(100)).toBe('cloudy');
  });
});

describe('labelKeyFor — category → i18n key', () => {
  const cases: Array<[WeatherCat, string]> = [
    ['clear', 'weather.clear'],
    ['partly', 'weather.partly'],
    ['cloudy', 'weather.cloudy'],
    ['fog', 'weather.fog'],
    ['drizzle', 'weather.drizzle'],
    ['rain', 'weather.rain'],
    ['snow', 'weather.snow'],
    ['storm', 'weather.storm'],
  ];

  it.each(cases)('returns %s → %s', (cat, key) => {
    expect(labelKeyFor(cat)).toBe(key);
  });

  it('returns null for null category', () => {
    expect(labelKeyFor(null)).toBeNull();
  });
});

describe('WeatherIcon — render', () => {
  it('renders an svg using the default size of 16', () => {
    const { container } = render(<WeatherIcon cat="clear" />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('width', '16');
    expect(svg).toHaveAttribute('height', '16');
  });

  it('honors a custom size prop', () => {
    const { container } = render(<WeatherIcon cat="rain" size={32} />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('width', '32');
    expect(svg).toHaveAttribute('height', '32');
  });

  it('renders the sun-rays animation group for clear', () => {
    const { container } = render(<WeatherIcon cat="clear" />);
    expect(container.querySelector('.wx-sun-rays')).not.toBeNull();
    // clear sky uses a single sun circle, no cloud
    expect(container.querySelectorAll('circle')).toHaveLength(1);
  });

  it('renders falling rain drops for rain', () => {
    const { container } = render(<WeatherIcon cat="rain" />);
    expect(container.querySelectorAll('.wx-rain-drop')).toHaveLength(3);
  });

  it('renders snow flakes for snow', () => {
    const { container } = render(<WeatherIcon cat="snow" />);
    expect(container.querySelectorAll('.wx-snow-flake')).toHaveLength(6);
  });

  it('renders the lightning bolt for storm', () => {
    const { container } = render(<WeatherIcon cat="storm" />);
    expect(container.querySelector('.wx-bolt')).not.toBeNull();
  });

  it('renders fog lines for fog', () => {
    const { container } = render(<WeatherIcon cat="fog" />);
    expect(container.querySelectorAll('line')).toHaveLength(2);
    expect(container.querySelector('.wx-rain-drop')).toBeNull();
  });
});
