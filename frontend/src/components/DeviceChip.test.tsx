import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { DeviceChip } from './DeviceChip'
import type { DeviceInfo } from '../hooks/useDevice'
import type { DeviceRuntime } from '../hooks/useSimulation'

// i18n passthrough: t(key) -> key so labels are assertable by their key.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

function makeDevice(over: Partial<DeviceInfo> = {}): DeviceInfo {
  return {
    udid: 'udid-1',
    name: 'My iPhone',
    ios_version: '17.0',
    connection_type: 'usb',
    is_connected: true,
    ...over,
  }
}

function makeRuntime(state: string): DeviceRuntime {
  return {
    udid: 'udid-1',
    state,
    currentPos: null,
    destination: null,
    routePath: [],
    progress: 0,
    eta: 0,
    distanceRemaining: 0,
    distanceTraveled: 0,
    waypointIndex: null,
    currentSpeedKmh: 0,
    error: null,
    lapCount: 0,
    cooldown: 0,
  }
}

const noop = () => {}

function baseProps() {
  return {
    onDisconnect: vi.fn(),
    onForget: vi.fn(),
    onRestoreOne: vi.fn(),
  }
}

beforeEach(() => {
  cleanup()
})

describe('DeviceChip rendering', () => {
  it('renders the device letter, short name, and idle state label by default', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice({ name: 'My iPhone' })}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('· My iPhone')).toBeInTheDocument()
    // No runtime => stateKind() === 'idle'
    expect(screen.getByText('· device.chip_state_idle')).toBeInTheDocument()
  })

  it('truncates a long device name to 14 chars', () => {
    render(
      <DeviceChip
        letter="B"
        device={makeDevice({ name: 'SuperLongDeviceNameThatExceeds' })}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    // 'SuperLongDeviceNameThatExceeds'.slice(0,14) === 'SuperLongDevic'
    expect(screen.getByText('· SuperLongDevic')).toBeInTheDocument()
  })

  it('falls back to "iPhone" when device.name is empty', () => {
    render(
      <DeviceChip
        letter="C"
        device={makeDevice({ name: '' })}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('· iPhone')).toBeInTheDocument()
  })

  it('shows the running state label when runtime.state indicates running', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        runtime={makeRuntime('moving')}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('· device.chip_state_running')).toBeInTheDocument()
  })

  it('shows the paused state label when runtime.state === "paused"', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        runtime={makeRuntime('paused')}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('· device.chip_state_paused')).toBeInTheDocument()
  })

  it('shows the disconnected state label when runtime.state === "disconnected"', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        runtime={makeRuntime('disconnected')}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('· device.chip_state_disconnected')).toBeInTheDocument()
  })

  it('exposes a title attribute combining letter and full device name', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice({ name: 'My iPhone' })}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByTitle('A · My iPhone')).toBeInTheDocument()
  })
})

describe('DeviceChip context menu + callbacks', () => {
  function openMenu(title: string) {
    const chip = screen.getByTitle(title)
    fireEvent.contextMenu(chip)
  }

  it('opens the context menu on right-click and shows menu items', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.queryByText('device.chip_restore')).not.toBeInTheDocument()
    openMenu('A · My iPhone')
    expect(screen.getByText('device.chip_restore')).toBeInTheDocument()
    expect(screen.getByText('device.chip_disconnect')).toBeInTheDocument()
    expect(screen.getByText('device.chip_forget')).toBeInTheDocument()
  })

  it('does NOT show the enable-dev item when onEnableDev is omitted', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    openMenu('A · My iPhone')
    expect(screen.queryByText('device.chip_enable_dev')).not.toBeInTheDocument()
  })

  it('shows the enable-dev item when onEnableDev is provided and fires it on click', () => {
    const onEnableDev = vi.fn()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
        onEnableDev={onEnableDev}
      />,
    )
    openMenu('A · My iPhone')
    const item = screen.getByText('device.chip_enable_dev')
    fireEvent.click(item)
    expect(onEnableDev).toHaveBeenCalledTimes(1)
  })

  it('fires onRestoreOne and closes the menu when the restore item is clicked', () => {
    const props = baseProps()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={props.onDisconnect}
        onForget={props.onForget}
        onRestoreOne={props.onRestoreOne}
      />,
    )
    openMenu('A · My iPhone')
    fireEvent.click(screen.getByText('device.chip_restore'))
    expect(props.onRestoreOne).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('device.chip_restore')).not.toBeInTheDocument()
  })

  it('fires onDisconnect when the disconnect item is clicked', () => {
    const props = baseProps()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={props.onDisconnect}
        onForget={props.onForget}
        onRestoreOne={props.onRestoreOne}
      />,
    )
    openMenu('A · My iPhone')
    fireEvent.click(screen.getByText('device.chip_disconnect'))
    expect(props.onDisconnect).toHaveBeenCalledTimes(1)
  })
})

describe('DeviceChip trust_required variant', () => {
  it('renders the trust badge and a re-trust menu item', () => {
    const onReTrust = vi.fn()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice({ name: 'Needs Trust', is_connected: false, pair_status: 'trust_required' })}
        variant="trust_required"
        onReTrust={onReTrust}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    expect(screen.getByText('device.pair_chip_trust')).toBeInTheDocument()
    fireEvent.contextMenu(screen.getByTitle('A · Needs Trust'))
    fireEvent.click(screen.getByText('device.chip_retrust'))
    expect(onReTrust).toHaveBeenCalledTimes(1)
  })
})

describe('DeviceChip forget confirmation flow', () => {
  function openMenu() {
    fireEvent.contextMenu(screen.getByTitle('A · My iPhone'))
  }

  it('opens a confirm dialog (does not call onForget) when the forget item is clicked', () => {
    const props = baseProps()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={props.onDisconnect}
        onForget={props.onForget}
        onRestoreOne={props.onRestoreOne}
      />,
    )
    openMenu()
    fireEvent.click(screen.getByText('device.chip_forget'))
    // Confirm modal text appears; onForget not yet called.
    expect(screen.getByText('device.forget_confirm_title')).toBeInTheDocument()
    expect(screen.getByText('device.forget_confirm_body')).toBeInTheDocument()
    expect(props.onForget).not.toHaveBeenCalled()
  })

  it('fires onForget when the confirm OK button is clicked', () => {
    const props = baseProps()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={props.onDisconnect}
        onForget={props.onForget}
        onRestoreOne={props.onRestoreOne}
      />,
    )
    openMenu()
    fireEvent.click(screen.getByText('device.chip_forget'))
    fireEvent.click(screen.getByText('device.forget_ok'))
    expect(props.onForget).toHaveBeenCalledTimes(1)
    // Modal closes after confirm.
    expect(screen.queryByText('device.forget_confirm_title')).not.toBeInTheDocument()
  })

  it('does NOT fire onForget when the confirm Cancel button is clicked', () => {
    const props = baseProps()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={props.onDisconnect}
        onForget={props.onForget}
        onRestoreOne={props.onRestoreOne}
      />,
    )
    openMenu()
    fireEvent.click(screen.getByText('device.chip_forget'))
    fireEvent.click(screen.getByText('device.forget_cancel'))
    expect(props.onForget).not.toHaveBeenCalled()
    expect(screen.queryByText('device.forget_confirm_title')).not.toBeInTheDocument()
  })
})
