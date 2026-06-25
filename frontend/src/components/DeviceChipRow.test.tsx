import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { DeviceChipRow, MAX_DEVICES } from './DeviceChipRow'
import type { DeviceInfo } from '../hooks/useDevice'
import type { RuntimesMap } from '../hooks/useSimulation'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

function makeDevice(udid: string, name: string): DeviceInfo {
  return {
    udid,
    name,
    ios_version: '17.0',
    connection_type: 'usb',
    is_connected: true,
  }
}

function baseProps() {
  return {
    onAdd: vi.fn(),
    onDisconnect: vi.fn(),
    onForget: vi.fn(),
    onRestoreOne: vi.fn(),
  }
}

const emptyRuntimes: RuntimesMap = {}

beforeEach(() => {
  cleanup()
})

describe('DeviceChipRow rendering', () => {
  it('renders one chip per device with letters A, B, C in order', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[
          makeDevice('u1', 'Phone One'),
          makeDevice('u2', 'Phone Two'),
          makeDevice('u3', 'Phone Three'),
        ]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    expect(screen.getByTitle('A · Phone One')).toBeInTheDocument()
    expect(screen.getByTitle('B · Phone Two')).toBeInTheDocument()
    expect(screen.getByTitle('C · Phone Three')).toBeInTheDocument()
  })

  it('shows the add-device button with label when there are no devices', () => {
    const props = baseProps()
    render(
      <DeviceChipRow devices={[]} runtimes={emptyRuntimes} {...props} />,
    )
    // label text rendered next to the + when devices.length === 0
    expect(screen.getByText('device.add_device')).toBeInTheDocument()
  })

  it('shows the add button (no text label) when below max but non-empty', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'Phone One')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    // The + button still renders (title set), but the add_device text label is hidden.
    expect(screen.getByTitle('device.add_device')).toBeInTheDocument()
    expect(screen.queryByText('device.add_device')).not.toBeInTheDocument()
    expect(screen.getByText('+')).toBeInTheDocument()
  })

  it('hides the add button entirely at max (3) devices', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[
          makeDevice('u1', 'One'),
          makeDevice('u2', 'Two'),
          makeDevice('u3', 'Three'),
        ]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    expect(screen.queryByText('+')).not.toBeInTheDocument()
    expect(screen.queryByTitle('device.add_device')).not.toBeInTheDocument()
  })

  it('renders only the first 3 devices when more than max are passed', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[
          makeDevice('u1', 'One'),
          makeDevice('u2', 'Two'),
          makeDevice('u3', 'Three'),
          makeDevice('u4', 'Four'),
        ]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    expect(screen.getByTitle('A · One')).toBeInTheDocument()
    expect(screen.getByTitle('C · Three')).toBeInTheDocument()
    expect(screen.queryByText('· Four')).not.toBeInTheDocument()
  })
})

describe('DeviceChipRow trust_required chips', () => {
  function trustDevice(udid: string, name: string): DeviceInfo {
    return { udid, name, ios_version: '17.0', connection_type: 'usb', is_connected: false, pair_status: 'trust_required' }
  }

  it('renders a trust_required chip alongside connected chips', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'Connected One')]}
        trustRequired={[trustDevice('t1', 'Needs Trust')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    expect(screen.getByTitle('A · Connected One')).toBeInTheDocument()
    // trust chip rendered with its name + the existing trust badge label key;
    // letter is the name-initial 'N' (first char of 'Needs Trust')
    expect(screen.getByTitle('N · Needs Trust')).toBeInTheDocument()
    expect(screen.getByText('· Needs Trust')).toBeInTheDocument()
    expect(screen.getByText('device.pair_chip_trust')).toBeInTheDocument()
  })

  it('fires onReTrust with the udid from the trust chip menu', () => {
    const props = baseProps()
    const onReTrust = vi.fn()
    render(
      <DeviceChipRow
        devices={[]}
        trustRequired={[trustDevice('t1', 'Needs Trust')]}
        runtimes={emptyRuntimes}
        onReTrust={onReTrust}
        {...props}
      />,
    )
    // The trust chip is labeled by the device's own name-initial ('N' for 'Needs Trust').
    fireEvent.contextMenu(screen.getByTitle('N · Needs Trust'))
    fireEvent.click(screen.getByText('device.chip_retrust'))
    expect(onReTrust).toHaveBeenCalledWith('t1')
  })
})

describe('DeviceChipRow callbacks wire the device udid', () => {
  function renderRow(props: ReturnType<typeof baseProps>) {
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'One'), makeDevice('u2', 'Two')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
  }

  it('calls onAdd when the add button is clicked', () => {
    const props = baseProps()
    render(
      <DeviceChipRow devices={[]} runtimes={emptyRuntimes} {...props} />,
    )
    fireEvent.click(screen.getByText('device.add_device').closest('button')!)
    expect(props.onAdd).toHaveBeenCalledTimes(1)
  })

  it('calls onForget with the correct udid via the chip forget flow', () => {
    const props = baseProps()
    renderRow(props)
    // Open chip B's context menu and run the forget -> confirm flow.
    fireEvent.contextMenu(screen.getByTitle('B · Two'))
    fireEvent.click(screen.getByText('device.chip_forget'))
    fireEvent.click(screen.getByText('device.forget_ok'))
    expect(props.onForget).toHaveBeenCalledTimes(1)
    expect(props.onForget).toHaveBeenCalledWith('u2')
  })

  it('calls onDisconnect with the correct udid', () => {
    const props = baseProps()
    renderRow(props)
    fireEvent.contextMenu(screen.getByTitle('A · One'))
    fireEvent.click(screen.getByText('device.chip_disconnect'))
    expect(props.onDisconnect).toHaveBeenCalledWith('u1')
  })

  it('calls onRestoreOne with the correct udid', () => {
    const props = baseProps()
    renderRow(props)
    fireEvent.contextMenu(screen.getByTitle('B · Two'))
    fireEvent.click(screen.getByText('device.chip_restore'))
    expect(props.onRestoreOne).toHaveBeenCalledWith('u2')
  })

  it('passes onEnableDev through and wires the udid when provided', () => {
    const props = baseProps()
    const onEnableDev = vi.fn()
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'One')]}
        runtimes={emptyRuntimes}
        onEnableDev={onEnableDev}
        {...props}
      />,
    )
    fireEvent.contextMenu(screen.getByTitle('A · One'))
    fireEvent.click(screen.getByText('device.chip_enable_dev'))
    expect(onEnableDev).toHaveBeenCalledWith('u1')
  })
})

describe('DeviceChipRow trust chip name-initial label (FU#2)', () => {
  function trustDevice(udid: string, name: string): DeviceInfo {
    return { udid, name, ios_version: '17.0', connection_type: 'usb', is_connected: false, pair_status: 'trust_required' }
  }

  it('two trust chips with distinct-initial names each show their own name-initial', () => {
    const props = baseProps()
    const onReTrust = vi.fn()
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'Connected One'), makeDevice('u2', 'Connected Two')]}
        trustRequired={[trustDevice('t1', 'Alpha iPhone'), trustDevice('t2', 'Beta iPhone')]}
        runtimes={emptyRuntimes}
        onReTrust={onReTrust}
        {...props}
      />,
    )
    // Each trust chip is labeled by its device's own name-initial.
    expect(screen.getByTitle('A · Alpha iPhone')).toBeInTheDocument()
    expect(screen.getByTitle('B · Beta iPhone')).toBeInTheDocument()
    // Labels are distinct (A vs B).
    const chipA = screen.getByTitle('A · Alpha iPhone')
    const chipB = screen.getByTitle('B · Beta iPhone')
    const letterA = chipA.getAttribute('title')!.split(' ·')[0]
    const letterB = chipB.getAttribute('title')!.split(' ·')[0]
    expect(letterA).not.toBe(letterB)
  })

  it('trust chip letter is derived from the device name, not position (2 connected + 1 trust)', () => {
    const props = baseProps()
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'Connected One'), makeDevice('u2', 'Connected Two')]}
        trustRequired={[trustDevice('t1', 'Xiao Mi')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    )
    // Connected chips keep A, B (positional).
    expect(screen.getByTitle('A · Connected One')).toBeInTheDocument()
    expect(screen.getByTitle('B · Connected Two')).toBeInTheDocument()
    // Trust chip: first char of 'Xiao Mi' is 'X', not 'C' (what the old positional formula gave).
    expect(screen.getByTitle('X · Xiao Mi')).toBeInTheDocument()
  })
})

describe('DeviceChipRow device cap is unified at MAX_DEVICES (U18)', () => {
  it('exposes MAX_DEVICES === 3', () => {
    expect(MAX_DEVICES).toBe(3);
  });

  it('still shows the + add button at 2 connected devices (room for a 3rd)', () => {
    const props = baseProps();
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'One'), makeDevice('u2', 'Two')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    );
    expect(screen.getByText('+')).toBeInTheDocument();
    expect(screen.getByTitle('device.add_device')).toBeInTheDocument();
  });

  it('hides the + add button when connected + trust_required together reach MAX_DEVICES', () => {
    function trustDevice(udid: string, name: string): DeviceInfo {
      return { udid, name, ios_version: '17.0', connection_type: 'usb', is_connected: false, pair_status: 'trust_required' }
    }
    const props = baseProps();
    render(
      <DeviceChipRow
        devices={[makeDevice('u1', 'One'), makeDevice('u2', 'Two')]}
        trustRequired={[trustDevice('t1', 'Needs Trust')]}
        runtimes={emptyRuntimes}
        {...props}
      />,
    );
    // 2 connected + 1 trust_required = 3 = MAX_DEVICES → + button must be hidden
    expect(screen.queryByText('+')).not.toBeInTheDocument();
    expect(screen.queryByTitle('device.add_device')).not.toBeInTheDocument();
  });
})
