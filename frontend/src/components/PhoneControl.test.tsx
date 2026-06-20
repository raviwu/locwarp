import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within, waitFor, cleanup, act } from '@testing-library/react';
import PhoneControlButton from './PhoneControl';

// i18n: passthrough — the key (with interpolation) IS the rendered text so
// assertions can target stable strings instead of locale copy.
vi.mock('../i18n', () => ({
  useT: () => (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    return key + '|' + Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(',');
  },
}));

// Pin the backend origin constant so the component's fetch URLs are deterministic.
vi.mock('../contract/endpoints', () => ({ BASE_URL: 'http://test.local' }));

const baseInfo = {
  port: 8777,
  lan_ips: ['192.168.1.50'],
  pin: '4821',
  last_phone_hit_ago_s: null as number | null,
};

function mockPhoneInfo(overrides: Record<string, any> = {}) {
  const info = { ...baseInfo, ...overrides };
  return vi.fn(async (input: RequestInfo | URL) => {
    const u = String(input);
    if (u.endsWith('/api/phone/info')) {
      return { ok: true, status: 200, json: async () => info } as Response;
    }
    // rotate / firewall_repair fall through here in default tests
    return { ok: true, status: 200, json: async () => ({ ok: true }) } as Response;
  });
}

describe('PhoneControlButton', () => {
  // Real timers: the component opens a 2s poll interval while the modal is
  // open. We don't assert on the poll itself, and RTL's findBy*/waitFor wrap
  // the resulting state updates in act(), so real timers keep output pristine.
  afterEach(async () => {
    // Opening the modal kicks off a fetch that, on resolve, sets `selectedIp`,
    // which recreates `fetchInfo` and re-runs the open effect → a second
    // fetch (each with an extra r.json() microtask hop). Those can resolve
    // after the test's last assertion. Generously drain the microtask queue
    // and run unmount — all inside act() — so trailing state updates are
    // wrapped and don't emit "not wrapped in act(...)" warnings.
    await act(async () => {
      for (let i = 0; i < 10; i++) await Promise.resolve();
      cleanup();
      for (let i = 0; i < 10; i++) await Promise.resolve();
    });
    vi.restoreAllMocks();
  });

  it('does not render the modal until the trigger button is clicked', () => {
    vi.stubGlobal('fetch', mockPhoneInfo());
    render(<PhoneControlButton />);
    // Trigger button uses the i18n key 'phone.button'.
    expect(screen.getByText('phone.button')).toBeInTheDocument();
    // Modal title not present yet.
    expect(screen.queryByText('phone.modal_title')).not.toBeInTheDocument();
  });

  it('fetches /api/phone/info on open and renders the LAN URL and PIN', async () => {
    const fetchMock = mockPhoneInfo();
    vi.stubGlobal('fetch', fetchMock);
    render(<PhoneControlButton />);

    fireEvent.click(screen.getByText('phone.button'));

    // Let the fetchInfo promise chain resolve under fake timers.
    await waitFor(() => {
      expect(screen.getByText('phone.modal_title')).toBeInTheDocument();
    });
    await waitFor(() => {
      // URL = http://<ip>:<port>/phone
      expect(screen.getByText('http://192.168.1.50:8777/phone')).toBeInTheDocument();
    });
    // PIN value rendered.
    expect(screen.getByText('4821')).toBeInTheDocument();
    // The info endpoint was actually hit.
    expect(fetchMock).toHaveBeenCalledWith('http://test.local/api/phone/info');
  });

  it('copies the PIN to the clipboard and shows a toast when the PIN box is clicked', async () => {
    vi.stubGlobal('fetch', mockPhoneInfo());
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const showToast = vi.fn();

    render(<PhoneControlButton showToast={showToast} />);
    fireEvent.click(screen.getByText('phone.button'));

    const pin = await waitFor(() => screen.getByText('4821'));
    fireEvent.click(pin);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('4821');
    });
    expect(showToast).toHaveBeenCalledWith('phone.copied');
  });

  it('copies the LAN URL when the URL box is clicked', async () => {
    vi.stubGlobal('fetch', mockPhoneInfo());
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const showToast = vi.fn();

    render(<PhoneControlButton showToast={showToast} />);
    fireEvent.click(screen.getByText('phone.button'));

    const urlBox = await waitFor(() => screen.getByText('http://192.168.1.50:8777/phone'));
    fireEvent.click(urlBox);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('http://192.168.1.50:8777/phone');
    });
    expect(showToast).toHaveBeenCalledWith('phone.copied');
  });

  it('shows the reach-ok indicator when the phone hit the URL recently (<60s)', async () => {
    vi.stubGlobal('fetch', mockPhoneInfo({ last_phone_hit_ago_s: 5 }));
    render(<PhoneControlButton />);
    fireEvent.click(screen.getByText('phone.button'));

    // reach_ok key carries the interpolated sec var (rounded).
    await waitFor(() => {
      expect(screen.getByText('phone.reach_ok|sec=5')).toBeInTheDocument();
    });
    expect(screen.queryByText('phone.reach_unknown')).not.toBeInTheDocument();
  });

  it('shows reach-unknown when there is no recent phone hit', async () => {
    vi.stubGlobal('fetch', mockPhoneInfo({ last_phone_hit_ago_s: null }));
    render(<PhoneControlButton />);
    fireEvent.click(screen.getByText('phone.button'));

    await waitFor(() => {
      expect(screen.getByText('phone.reach_unknown')).toBeInTheDocument();
    });
  });

  it('surfaces an error message when /api/phone/info responds non-ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) } as Response)));
    render(<PhoneControlButton />);
    fireEvent.click(screen.getByText('phone.button'));

    await waitFor(() => {
      expect(screen.getByText('HTTP 503')).toBeInTheDocument();
    });
  });

  it('POSTs to /api/phone/rotate and re-fetches info when Rotate is clicked', async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const u = String(input);
      calls.push(`${init?.method ?? 'GET'} ${u}`);
      if (u.endsWith('/api/phone/info')) {
        return { ok: true, status: 200, json: async () => baseInfo } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ ok: true }) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    const showToast = vi.fn();

    render(<PhoneControlButton showToast={showToast} />);
    fireEvent.click(screen.getByText('phone.button'));

    const rotateBtn = await waitFor(() => screen.getByText('phone.rotate'));
    fireEvent.click(rotateBtn);

    await waitFor(() => {
      expect(calls.some((c) => c === 'POST http://test.local/api/phone/rotate')).toBe(true);
    });
    await waitFor(() => {
      expect(showToast).toHaveBeenCalledWith('phone.rotated');
    });
  });

  it('renders a NIC <select> when multiple non-virtual interfaces exist', async () => {
    vi.stubGlobal('fetch', mockPhoneInfo({
      lan_ips: ['192.168.1.50', '10.0.0.2'],
      nics: [
        { ip: '192.168.1.50', iface: 'en0', kind: 'wifi', primary: true },
        { ip: '10.0.0.2', iface: 'en1', kind: 'ethernet', primary: false },
      ],
    }));
    render(<PhoneControlButton />);
    fireEvent.click(screen.getByText('phone.button'));

    const select = await waitFor(() => screen.getByRole('combobox') as HTMLSelectElement);
    // Two non-virtual options.
    const options = within(select).getAllByRole('option');
    expect(options).toHaveLength(2);
    // Default selected IP is the first lan_ip -> URL reflects it.
    expect(screen.getByText('http://192.168.1.50:8777/phone')).toBeInTheDocument();

    // Switching the select updates the displayed URL. The change recreates
    // fetchInfo (selectedIp dep) → re-runs the open effect → a refetch; wait
    // for that to settle so the URL assertion and afterEach stay act-clean.
    fireEvent.change(select, { target: { value: '10.0.0.2' } });
    await waitFor(() => {
      expect(screen.getByText('http://10.0.0.2:8777/phone')).toBeInTheDocument();
    });
  });
});
