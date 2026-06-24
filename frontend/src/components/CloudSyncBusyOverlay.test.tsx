import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CloudSyncBusyOverlay } from './CloudSyncBusyOverlay'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

let busyValue = false
let tookTooLongValue = false
const cancelMock = vi.fn()
vi.mock('../contexts/CloudSyncBusyContext', () => ({
  useCloudSyncBusy: () => ({
    busy: busyValue,
    tookTooLong: tookTooLongValue,
    cancel: cancelMock,
  }),
}))

describe('CloudSyncBusyOverlay', () => {
  beforeEach(() => {
    busyValue = false
    tookTooLongValue = false
    cancelMock.mockClear()
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

  it('does not show the taking-longer hint or Cancel button before the slow threshold', () => {
    busyValue = true
    tookTooLongValue = false
    render(<CloudSyncBusyOverlay />)
    expect(screen.queryByText('cloud_sync.busy_taking_longer')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'cloud_sync.busy_cancel' })).not.toBeInTheDocument()
  })

  it('shows the taking-longer hint + a Cancel button once tookTooLong, and Cancel calls cancel()', () => {
    busyValue = true
    tookTooLongValue = true
    render(<CloudSyncBusyOverlay />)

    // The blocking alert + aria-live semantics are preserved.
    const overlay = screen.getByRole('alert')
    expect(overlay).toHaveAttribute('aria-live', 'assertive')

    expect(screen.getByText('cloud_sync.busy_taking_longer')).toBeInTheDocument()
    const cancelBtn = screen.getByRole('button', { name: 'cloud_sync.busy_cancel' })
    fireEvent.click(cancelBtn)
    expect(cancelMock).toHaveBeenCalledTimes(1)
  })

  it('renders as an assertive alert region', () => {
    busyValue = true
    render(<CloudSyncBusyOverlay />)
    const region = screen.getByRole('alert')
    expect(region).toHaveAttribute('aria-live', 'assertive')
  })

  it('reads its z-index from the --z-overlay-blocking token (must sit above context menus/toasts)', () => {
    busyValue = true
    render(<CloudSyncBusyOverlay />)
    const region = screen.getByRole('alert')
    // jsdom preserves the literal var() string in the inline style.
    // --z-overlay-blocking (10001) must exceed the highest raw z-index still in
    // legacy CSS (.context-menu: 10000, .error-toast: 9999) so the full-screen
    // blocking overlay is never visually overdrawn by menus or toasts.
    // This test exists to prevent a regression where the token was downgraded to
    // --z-modal (1000), which let context menus render above the blocking overlay.
    expect(region.style.zIndex).toBe('var(--z-overlay-blocking)')
    expect(region.style.zIndex).not.toBe('var(--z-modal)')
    expect(region.style.zIndex).not.toBe('9999')
  })
})
