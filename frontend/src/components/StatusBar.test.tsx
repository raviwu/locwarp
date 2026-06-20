import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StatusBar from './StatusBar'
import { SimMode } from '../hooks/useSimulation'

// --- Mocks ------------------------------------------------------------
// i18n passthrough: t(key) → key, so we can assert on raw label keys.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

// Heavy / side-effecting children — replaced with inert stubs.
vi.mock('./LangToggle', () => ({ default: () => <div data-testid="lang-toggle" /> }))
vi.mock('./PhoneControl', () => ({ default: () => <div data-testid="phone-control" /> }))
vi.mock('./SettingsModal', () => ({ default: () => null }))

// useUpdateCheck drives the trailing "NEW" pill. Default: no update.
const mockUpdateCheck = vi.fn(() => ({ latest: null as string | null, releaseUrl: null as string | null }))
vi.mock('./UpdateChecker', () => ({ useUpdateCheck: () => mockUpdateCheck() }))

// WeatherIcon's helpers are real (pure); only the SVG component is stubbed
// so we don't render its animation markup. categorize/labelKeyFor stay real.
vi.mock('./WeatherIcon', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./WeatherIcon')>()
  return { ...actual, WeatherIcon: () => <span data-testid="weather-icon" /> }
})

// --- Helpers ----------------------------------------------------------
type Props = React.ComponentProps<typeof StatusBar>

function baseProps(overrides: Partial<Props> = {}): Props {
  return {
    isConnected: true,
    deviceName: 'iPhone',
    iosVersion: '17.0',
    currentPosition: { lat: 35.123456, lng: 139.654321 },
    speed: 42,
    mode: SimMode.Navigate,
    cooldown: 0,
    cooldownEnabled: true,
    onToggleCooldown: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  mockUpdateCheck.mockReturnValue({ latest: null, releaseUrl: null })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('StatusBar — coordinate + speed/mode display', () => {
  it('renders the current coordinates to 6 decimal places', () => {
    render(<StatusBar {...baseProps()} />)
    expect(screen.getByText('35.123456, 139.654321')).toBeInTheDocument()
  })

  it('renders speed and the localized mode label key', () => {
    render(<StatusBar {...baseProps({ speed: 88, mode: SimMode.Loop })} />)
    expect(screen.getByText('88 km/h')).toBeInTheDocument()
    // modeLabelKeys[Loop] === 'mode.loop' (passthrough i18n)
    expect(screen.getByText('mode.loop')).toBeInTheDocument()
  })

  it('omits the coordinate block when currentPosition is null', () => {
    render(<StatusBar {...baseProps({ currentPosition: null })} />)
    expect(screen.queryByText(/35\.123456/)).not.toBeInTheDocument()
    // speed/mode still render
    expect(screen.getByText('42 km/h')).toBeInTheDocument()
  })

  it('shows a country flag image when countryCode is provided', () => {
    render(<StatusBar {...baseProps({ countryCode: 'jp' })} />)
    const flag = screen.getByRole('img', { name: 'JP' }) as HTMLImageElement
    expect(flag.src).toContain('flagcdn.com/w40/jp.png')
  })
})

describe('StatusBar — weather chip', () => {
  it('renders the weather chip with temperature and label when weather + temp present', () => {
    render(<StatusBar {...baseProps({ weatherCode: 0, tempC: 21.4 })} />)
    expect(screen.getByTestId('weather-icon')).toBeInTheDocument()
    // 21.4 rounds to 21°C
    expect(screen.getByText('21°C')).toBeInTheDocument()
    // categorize(0) → 'clear' → labelKeyFor → 'weather.clear'
    expect(screen.getByText('weather.clear')).toBeInTheDocument()
  })

  it('does not render the weather chip when weatherCode is null', () => {
    render(<StatusBar {...baseProps({ weatherCode: null, tempC: 20 })} />)
    expect(screen.queryByTestId('weather-icon')).not.toBeInTheDocument()
  })
})

describe('StatusBar — cooldown toggle', () => {
  it('shows the enabled label when cooldown is enabled and not dual', () => {
    render(<StatusBar {...baseProps({ cooldownEnabled: true })} />)
    expect(screen.getByText('status.cooldown_enabled')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeChecked()
  })

  it('shows the disabled label and unchecks when cooldown is off', () => {
    render(<StatusBar {...baseProps({ cooldownEnabled: false })} />)
    expect(screen.getByText('status.cooldown_disabled')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('fires onToggleCooldown with the new checked state', () => {
    const onToggleCooldown = vi.fn()
    render(<StatusBar {...baseProps({ cooldownEnabled: false, onToggleCooldown })} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onToggleCooldown).toHaveBeenCalledWith(true)
  })

  it('force-disables the toggle in dual-device mode and never fires the callback', () => {
    const onToggleCooldown = vi.fn()
    render(<StatusBar {...baseProps({ cooldownEnabled: true, dualDevice: true, onToggleCooldown })} />)
    const cb = screen.getByRole('checkbox') as HTMLInputElement
    expect(cb).toBeDisabled()
    expect(cb).not.toBeChecked() // forced off regardless of saved setting
    fireEvent.click(cb)
    expect(onToggleCooldown).not.toHaveBeenCalled()
  })
})

describe('StatusBar — timezone chip', () => {
  it('renders the tz chip with the +Nh offset when destination differs by >=1h', () => {
    // Pin "now" so the diff math is deterministic. Derive the destination
    // GMT offset from the env's local offset + a 9h shift, so the chip's
    // computed diff is exactly +9h regardless of the CI machine timezone.
    const now = new Date('2026-06-20T03:00:00Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    const localOffsetSec = -now.getTimezoneOffset() * 60
    const gmtOffsetSeconds = localOffsetSec + 9 * 3600

    render(
      <StatusBar
        {...baseProps({ timezoneZone: 'Asia/Tokyo', gmtOffsetSeconds })}
      />,
    )
    // The offset chip text — sign + diffH + 'h'.
    expect(screen.getByText('+9h')).toBeInTheDocument()
    // The chip is a clickable button (entry point to the detail modal).
    const chip = screen.getByText('+9h').closest('button')
    expect(chip).not.toBeNull()
  })

  it('hides the tz chip when the destination offset differs by less than 1h', () => {
    const now = new Date('2026-06-20T03:00:00Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    const localOffsetSec = -now.getTimezoneOffset() * 60
    // Only 30 minutes of difference → below the 3600s threshold → no chip.
    const gmtOffsetSeconds = localOffsetSec + 1800

    render(
      <StatusBar
        {...baseProps({ timezoneZone: 'Asia/Kolkata', gmtOffsetSeconds })}
      />,
    )
    // The offset chip text is exactly "+Nh" / "-Nh"; none should appear.
    expect(screen.queryByText(/^[+-]\d+h$/)).not.toBeInTheDocument()
  })

  it('does not render the tz chip when timezoneZone is null', () => {
    render(<StatusBar {...baseProps({ timezoneZone: null, gmtOffsetSeconds: 99999 })} />)
    expect(screen.queryByText('+9h')).not.toBeInTheDocument()
  })

  it('opens the timezone detail modal when the chip is clicked', () => {
    const now = new Date('2026-06-20T03:00:00Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    const localOffsetSec = -now.getTimezoneOffset() * 60
    const gmtOffsetSeconds = localOffsetSec + 9 * 3600

    render(
      <StatusBar
        {...baseProps({ timezoneZone: 'Asia/Tokyo', gmtOffsetSeconds })}
      />,
    )
    fireEvent.click(screen.getByText('+9h').closest('button')!)
    // Modal title uses the i18n key (passthrough).
    expect(screen.getByText('tz.modal_title')).toBeInTheDocument()
  })
})

describe('StatusBar — optional action buttons', () => {
  it('renders the restore button and fires onRestore when clicked', () => {
    const onRestore = vi.fn()
    render(<StatusBar {...baseProps({ onRestore })} />)
    const btn = screen.getByText('status.restore')
    fireEvent.click(btn)
    expect(onRestore).toHaveBeenCalledTimes(1)
  })

  it('shows the restore_all label in dual mode', () => {
    render(<StatusBar {...baseProps({ onRestore: vi.fn(), dualDevice: true })} />)
    expect(screen.getByText('status.restore_all')).toBeInTheDocument()
  })

  it('does not render the restore cluster when onRestore is absent', () => {
    render(<StatusBar {...baseProps()} />)
    expect(screen.queryByText('status.restore')).not.toBeInTheDocument()
  })
})

describe('StatusBar — version pill', () => {
  it('renders the plain version when no update is available', () => {
    render(<StatusBar {...baseProps()} />)
    expect(screen.queryByText('NEW')).not.toBeInTheDocument()
  })

  it('renders the NEW update pill when an update is available', () => {
    mockUpdateCheck.mockReturnValue({ latest: 'v9.9.9', releaseUrl: 'https://example.com/r' })
    render(<StatusBar {...baseProps()} />)
    expect(screen.getByText('NEW')).toBeInTheDocument()
  })
})
