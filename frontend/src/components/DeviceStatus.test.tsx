import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// i18n: passthrough that returns the key (so assertions can match on keys).
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

// services/api is hit by Discover / repair / port-scan handlers. Mock so no
// real network happens; default resolved values keep handlers inert.
vi.mock('../services/api', () => ({
  wifiTunnelDiscover: vi.fn().mockResolvedValue({ devices: [] }),
  wifiTunnelFindPort: vi.fn().mockResolvedValue({ ports: [] }),
  wifiRepair: vi.fn().mockResolvedValue({ name: 'iPhone', ios_version: '17.0' }),
}))

import DeviceStatus from './DeviceStatus'

interface Device {
  id: string
  udid: string
  name: string
  iosVersion: string
  connectionType?: string
}

function makeDevice(over: Partial<Device> = {}): Device {
  return {
    id: 'dev-1',
    udid: 'udid-1',
    name: "Ravi's iPhone",
    iosVersion: '17.4',
    connectionType: 'USB',
    ...over,
  }
}

describe('DeviceStatus', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  const baseProps = {
    device: null,
    devices: [] as Device[],
    isConnected: false,
    onScan: vi.fn(),
    onSelect: vi.fn(),
  }

  it('renders the connected device name and iOS version', () => {
    const device = makeDevice()
    render(<DeviceStatus {...baseProps} device={device} devices={[device]} isConnected />)
    expect(screen.getByText("Ravi's iPhone")).toBeInTheDocument()
    // iOS version line renders "iOS 17.4"
    expect(screen.getByText(/iOS 17\.4/)).toBeInTheDocument()
  })

  it('shows "No device" placeholder when device is null', () => {
    render(<DeviceStatus {...baseProps} />)
    expect(screen.getByText('No device')).toBeInTheDocument()
  })

  it('opens the device dropdown and lists every device on toggle', () => {
    const a = makeDevice({ id: 'a', udid: 'ua', name: 'iPhone A' })
    const b = makeDevice({ id: 'b', udid: 'ub', name: 'iPhone B' })
    render(<DeviceStatus {...baseProps} devices={[a, b]} />)

    // The dropdown summary button shows the count.
    const toggle = screen.getByText('2 devices found')
    // Device rows aren't in the DOM until the dropdown is opened.
    expect(screen.queryByText('iPhone A')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByText('iPhone A')).toBeInTheDocument()
    expect(screen.getByText('iPhone B')).toBeInTheDocument()
  })

  it('fires onSelect with the device id when a dropdown row is clicked', () => {
    const onSelect = vi.fn()
    const a = makeDevice({ id: 'a', udid: 'ua', name: 'iPhone A' })
    render(<DeviceStatus {...baseProps} devices={[a]} onSelect={onSelect} />)

    fireEvent.click(screen.getByText('1 devices found'))
    fireEvent.click(screen.getByText('iPhone A'))
    expect(onSelect).toHaveBeenCalledWith('a')
  })

  it('invokes onScan when the scan button is clicked', async () => {
    const onScan = vi.fn().mockResolvedValue(undefined)
    render(<DeviceStatus {...baseProps} onScan={onScan} />)
    // The scan button shows "USB" label in idle state.
    fireEvent.click(screen.getByText('USB'))
    expect(onScan).toHaveBeenCalledTimes(1)
    // handleScan resolves onScan then flips scanning state back off; wait for
    // that post-click state settle so no act() warning leaks.
    await waitFor(() => expect(screen.getByText('device.scan_none')).toBeInTheDocument())
  })

  it('auto-expands the dropdown when a device needs re-trust', () => {
    const trust = makeDevice({ id: 't', udid: 'ut', name: 'Needs Trust', pair_status: 'trust_required' } as any)
    render(<DeviceStatus {...baseProps} devices={[trust]} />)
    // No user click: the dropdown is auto-opened, so the device row + the
    // existing trust badge (device.pair_chip_trust) render immediately.
    expect(screen.getByText('Needs Trust')).toBeInTheDocument()
    expect(screen.getByText('device.pair_chip_trust')).toBeInTheDocument()
  })

  it('does NOT auto-expand when all devices are healthy', () => {
    const ok = makeDevice({ id: 'a', udid: 'ua', name: 'Healthy' })
    render(<DeviceStatus {...baseProps} devices={[ok]} />)
    // Collapsed by default: the row is not rendered until the summary is clicked.
    expect(screen.queryByText('Healthy')).not.toBeInTheDocument()
    expect(screen.getByText('1 devices found')).toBeInTheDocument()
  })
})
