import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

// i18n passthrough — t(key) returns the key (interpolation ignored, fine for assertions).
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}));

// Mock the geocode service so we control results / errors deterministically.
vi.mock('../services/api', () => ({
  searchAddress: vi.fn(),
}));

import AddressSearch from './AddressSearch';
import { searchAddress } from '../services/api';

const mockedSearch = searchAddress as unknown as ReturnType<typeof vi.fn>;

// Advance past the 300ms input debounce, then flush the awaited searchAddress
// promise + the setState that follows. Mixing fake timers with findBy/waitFor
// hangs (their polling is itself timer-driven), so we settle synchronously here
// and use getBy* afterwards.
async function flushDebounce() {
  await act(async () => {
    vi.advanceTimersByTime(300);
    // Let the resolved/rejected promise microtasks drain.
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AddressSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockedSearch.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('renders the search input with the placeholder key', () => {
    render(<AddressSearch onSelect={vi.fn()} />);
    expect(screen.getByPlaceholderText('search.placeholder')).toBeInTheDocument();
  });

  it('debounces input, calls searchAddress, and renders mapped results', async () => {
    mockedSearch.mockResolvedValue([
      { display_name: 'Tokyo Tower', lat: 35.6586, lng: 139.7454, address: 'Minato, Tokyo' },
      { name: 'Tokyo Station', lat: 35.6812, lng: 139.7671 },
    ]);

    render(<AddressSearch onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText('search.placeholder');

    fireEvent.change(input, { target: { value: 'tokyo' } });
    // Not called before the debounce window elapses.
    expect(mockedSearch).not.toHaveBeenCalled();

    await flushDebounce();

    expect(mockedSearch).toHaveBeenCalledWith('tokyo');
    expect(screen.getByText('Tokyo Tower')).toBeInTheDocument();
    expect(screen.getByText('Tokyo Station')).toBeInTheDocument();
    // The first result's address line is shown.
    expect(screen.getByText('Minato, Tokyo')).toBeInTheDocument();
  });

  it('does not search for queries shorter than 2 chars', async () => {
    render(<AddressSearch onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText('search.placeholder');

    fireEvent.change(input, { target: { value: 'a' } });
    await flushDebounce();

    expect(mockedSearch).not.toHaveBeenCalled();
  });

  it('fires onSelect with lat/lng/name when a result is clicked', async () => {
    mockedSearch.mockResolvedValue([
      { display_name: 'Osaka Castle', lat: 34.6873, lng: 135.5259 },
    ]);
    const onSelect = vi.fn();

    render(<AddressSearch onSelect={onSelect} />);
    const input = screen.getByPlaceholderText('search.placeholder');
    fireEvent.change(input, { target: { value: 'osaka' } });
    await flushDebounce();

    const item = screen.getByText('Osaka Castle');
    fireEvent.click(item);

    expect(onSelect).toHaveBeenCalledWith(34.6873, 135.5259, 'Osaka Castle');
    // Selecting puts the chosen name into the input and closes the dropdown.
    expect((input as HTMLInputElement).value).toBe('Osaka Castle');
  });

  it('shows an error message when the search service rejects', async () => {
    mockedSearch.mockRejectedValue(new Error('boom-network'));

    render(<AddressSearch onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText('search.placeholder');
    fireEvent.change(input, { target: { value: 'paris' } });
    await flushDebounce();

    expect(screen.getByText('boom-network')).toBeInTheDocument();
  });

  it('shows the no-results message when an empty array comes back', async () => {
    mockedSearch.mockResolvedValue([]);

    render(<AddressSearch onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText('search.placeholder');
    fireEvent.change(input, { target: { value: 'zzzz' } });
    await flushDebounce();

    expect(screen.getByText('search.no_results')).toBeInTheDocument();
  });

  it('defaults to the free provider when no google key is saved', () => {
    render(<AddressSearch onSelect={vi.fn()} />);
    // The provider toggle button shows the free-provider short label, not Google.
    expect(screen.getByText('search.provider_free_short')).toBeInTheDocument();
    expect(screen.queryByText('Google')).not.toBeInTheDocument();
  });

  it('opens the settings modal when the provider button is clicked', () => {
    render(<AddressSearch onSelect={vi.fn()} />);
    const providerBtn = screen.getByText('search.provider_free_short').closest('button')!;
    fireEvent.click(providerBtn);

    expect(screen.getByText('search.settings_title')).toBeInTheDocument();
    // Both provider option labels are present in the modal.
    expect(screen.getByText('search.provider_free_label')).toBeInTheDocument();
    expect(screen.getByText('search.provider_google_label')).toBeInTheDocument();
  });

  it('saves a google API key and switches the active provider to Google', () => {
    render(<AddressSearch onSelect={vi.fn()} />);
    fireEvent.click(screen.getByText('search.provider_free_short').closest('button')!);

    const keyInput = screen.getByPlaceholderText('AIza...');
    fireEvent.change(keyInput, { target: { value: 'AIzaSecretKey1234' } });
    fireEvent.click(screen.getByText('search.save_key'));

    // localStorage now holds the key + provider, and the toggle reads "Google".
    expect(localStorage.getItem('locwarp.google_geocode_key')).toBe('AIzaSecretKey1234');
    expect(localStorage.getItem('locwarp.geocode_provider')).toBe('google');
    expect(screen.getByText('Google')).toBeInTheDocument();
  });
});
