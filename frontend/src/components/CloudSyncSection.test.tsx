import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CloudSyncSection } from './CloudSyncSection'
import type { CloudSyncStatus } from '../services/api'

// Passthrough i18n: t(key, vars) -> "key" with any vars appended so
// assertions can target both the key and the interpolated values.
vi.mock('../i18n', () => ({
  useT:
    () =>
    (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
}))

vi.mock('../services/api', () => ({
  cloudSyncStatus: vi.fn(),
  cloudSyncEnable: vi.fn(),
  cloudSyncDisable: vi.fn(),
}))

// Controllable busy context: `run` simply invokes fn (no overlay logic here).
const runMock = vi.fn(async (fn: () => Promise<unknown>) => fn())
let busyValue = false
vi.mock('../contexts/CloudSyncBusyContext', () => ({
  useCloudSyncBusy: () => ({ busy: busyValue, run: runMock }),
}))

import {
  cloudSyncStatus,
  cloudSyncEnable,
  cloudSyncDisable,
} from '../services/api'

const STATUS = (over: Partial<CloudSyncStatus> = {}): CloudSyncStatus => ({
  enabled: false,
  sync_folder: null,
  detected_icloud_path: null,
  prompt_dismissed: false,
  bookmarks: { path: '/bm', count: 0, category_count: 0 },
  routes: { path: '/rt', count: 0, category_count: 0 },
  ...over,
})

describe('CloudSyncSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    busyValue = false
    runMock.mockImplementation(async (fn: () => Promise<unknown>) => fn())
  })

  it('renders nothing until status resolves', async () => {
    // Never-resolving status -> component returns null.
    vi.mocked(cloudSyncStatus).mockReturnValue(new Promise(() => {}) as never)
    const { container } = render(<CloudSyncSection />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the disabled-with-iCloud-detected state and a checked-off toggle', async () => {
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({ detected_icloud_path: '/iCloud/LocWarp' }),
    )
    render(<CloudSyncSection />)

    const checkbox = await screen.findByRole('checkbox')
    expect(checkbox).not.toBeChecked()
    // iCloud detected -> enable-via-icloud label, and detected_path hint.
    expect(
      screen.getByText('cloud_sync.toggle_enable_icloud'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/cloud_sync\.detected_path/),
    ).toBeInTheDocument()
    // Enable is allowed because an iCloud path is detected.
    expect(checkbox).not.toBeDisabled()
  })

  it('disables the toggle and shows the no-iCloud hint when nothing detected', async () => {
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({ detected_icloud_path: null }),
    )
    render(<CloudSyncSection />)

    const checkbox = await screen.findByRole('checkbox')
    // Not enabled + cannot enable (no detected path) -> disabled.
    expect(checkbox).toBeDisabled()
    expect(
      screen.getByText('cloud_sync.toggle_enable_custom'),
    ).toBeInTheDocument()
    expect(screen.getByText('cloud_sync.no_icloud_hint')).toBeInTheDocument()
  })

  it('renders the enabled state with folder path and resource counts', async () => {
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({
        enabled: true,
        sync_folder: '/iCloud/LocWarp',
        bookmarks: { path: '/bm', count: 7, category_count: 3 },
        routes: { path: '/rt', count: 4, category_count: 2 },
      }),
    )
    render(<CloudSyncSection />)

    const checkbox = await screen.findByRole('checkbox')
    expect(checkbox).toBeChecked()
    expect(screen.getByText('cloud_sync.toggle_enabled')).toBeInTheDocument()
    // Path detail interpolates the sync_folder.
    expect(screen.getByText(/iCloud\/LocWarp/)).toBeInTheDocument()
    // Counts detail interpolates the bookmark/route numbers.
    const counts = screen.getByText(/cloud_sync\.detail_counts/)
    expect(counts).toHaveTextContent('"bookmarks":7')
    expect(counts).toHaveTextContent('"routes":4')
    expect(counts).toHaveTextContent('"bookmark_categories":3')
    expect(counts).toHaveTextContent('"route_categories":2')
  })

  it('enables sync via run() when toggling a disabled section on', async () => {
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({ detected_icloud_path: '/iCloud/LocWarp' }),
    )
    const enabledStatus = STATUS({
      enabled: true,
      sync_folder: '/iCloud/LocWarp',
      detected_icloud_path: '/iCloud/LocWarp',
    })
    vi.mocked(cloudSyncEnable).mockResolvedValue(enabledStatus)

    render(<CloudSyncSection />)
    const checkbox = await screen.findByRole('checkbox')
    fireEvent.click(checkbox)

    await waitFor(() =>
      expect(screen.getByText('cloud_sync.toggle_enabled')).toBeInTheDocument(),
    )
    expect(runMock).toHaveBeenCalledTimes(1)
    expect(cloudSyncEnable).toHaveBeenCalledTimes(1)
    expect(cloudSyncDisable).not.toHaveBeenCalled()
    expect(await screen.findByRole('checkbox')).toBeChecked()
  })

  it('disables sync via run() when toggling an enabled section off', async () => {
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({ enabled: true, sync_folder: '/iCloud/LocWarp' }),
    )
    vi.mocked(cloudSyncDisable).mockResolvedValue(STATUS({ enabled: false }))

    render(<CloudSyncSection />)
    const checkbox = await screen.findByRole('checkbox')
    expect(checkbox).toBeChecked()
    fireEvent.click(checkbox)

    await waitFor(() =>
      expect(
        screen.getByText('cloud_sync.toggle_enable_custom'),
      ).toBeInTheDocument(),
    )
    expect(cloudSyncDisable).toHaveBeenCalledTimes(1)
    expect(cloudSyncEnable).not.toHaveBeenCalled()
    expect((await screen.findByRole('checkbox'))).not.toBeChecked()
  })

  it('surfaces a toggle error without changing the enabled state', async () => {
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({ detected_icloud_path: '/iCloud/LocWarp' }),
    )
    vi.mocked(cloudSyncEnable).mockRejectedValue(new Error('migrate boom'))

    render(<CloudSyncSection />)
    const checkbox = await screen.findByRole('checkbox')
    fireEvent.click(checkbox)

    expect(await screen.findByText(/migrate boom/)).toBeInTheDocument()
    // Still in the disabled state after the failed enable.
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('disables the toggle while a sync op is busy', async () => {
    busyValue = true
    vi.mocked(cloudSyncStatus).mockResolvedValue(
      STATUS({ enabled: true, sync_folder: '/iCloud/LocWarp' }),
    )
    render(<CloudSyncSection />)
    const checkbox = await screen.findByRole('checkbox')
    expect(checkbox).toBeDisabled()
  })

  it('re-fetches status (refresh) after an AbortError so UI reconciles with backend truth', async () => {
    // Initial state: disabled, iCloud detected.
    vi.mocked(cloudSyncStatus).mockResolvedValueOnce(
      STATUS({ detected_icloud_path: '/iCloud/LocWarp' }),
    )
    // After the failed toggle, refresh() fetches status again (enabled).
    vi.mocked(cloudSyncStatus).mockResolvedValueOnce(
      STATUS({ enabled: true, sync_folder: '/iCloud/LocWarp', detected_icloud_path: '/iCloud/LocWarp' }),
    )
    // Toggle throws an AbortError (35s timeout / Cancel path).
    const abortErr = new DOMException('The operation was aborted.', 'AbortError')
    vi.mocked(cloudSyncEnable).mockRejectedValue(abortErr)

    render(<CloudSyncSection />)
    const checkbox = await screen.findByRole('checkbox')
    fireEvent.click(checkbox)

    // After the abort the component must re-fetch: cloudSyncStatus called 2x total.
    await waitFor(() => expect(cloudSyncStatus).toHaveBeenCalledTimes(2))
    // The second fetch returned enabled=true, so the checkbox now reflects that.
    await waitFor(() => expect(screen.getByRole('checkbox')).toBeChecked())
  })
})
