import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CloudSyncBusyOverlay } from './CloudSyncBusyOverlay'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

let busyValue = false
vi.mock('../contexts/CloudSyncBusyContext', () => ({
  useCloudSyncBusy: () => ({ busy: busyValue }),
}))

describe('CloudSyncBusyOverlay', () => {
  beforeEach(() => {
    busyValue = false
  })

  it('renders nothing when not busy', () => {
    busyValue = false
    const { container } = render(<CloudSyncBusyOverlay />)
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders the blocking alert overlay with title and hint when busy', () => {
    busyValue = true
    render(<CloudSyncBusyOverlay />)

    const overlay = screen.getByRole('alert')
    expect(overlay).toBeInTheDocument()
    expect(overlay).toHaveAttribute('aria-live', 'assertive')
    expect(screen.getByText('cloud_sync.busy_title')).toBeInTheDocument()
    expect(screen.getByText('cloud_sync.busy_hint')).toBeInTheDocument()
  })
})
