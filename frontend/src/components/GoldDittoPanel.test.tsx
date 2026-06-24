import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import GoldDittoPanel from './GoldDittoPanel'

// i18n: passthrough — t(key) returns the key so we can assert on stable strings.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

// Heavy child — replace with a lightweight probe that surfaces the props we
// care about and lets us drive onPickCoord / onEndEvent from the test.
vi.mock('./BookmarkPickerPopover', () => ({
  __esModule: true,
  default: (props: {
    open: boolean
    side: string
    onPickCoord: (bm: { lat: number; lng: number }) => void
    onEndEvent?: (catId: string, count: number) => void
  }) =>
    props.open ? (
      <div data-testid="picker" data-side={props.side}>
        <button
          data-testid="picker-pick"
          onClick={() => props.onPickCoord({ lat: 12.5, lng: 34.25 })}
        >
          pick
        </button>
        <button
          data-testid="picker-end"
          onClick={() => props.onEndEvent?.('cat-1', 3)}
        >
          end
        </button>
      </div>
    ) : null,
}))

const baseProps = () => ({
  connectedUdids: ['udid-1'],
  isCycling: false,
  mapCenter: null,
  externalAValue: null,
  bookmarks: [],
  categories: [{ id: 'cat-1', name: 'Festival' }],
  onConfirmLocation: vi.fn(),
  onCycle: vi.fn(),
  onCategoryDeleteCascade: vi.fn(),
})

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('GoldDittoPanel', () => {
  it('shows the no-device error and disables both action buttons when no device is connected', () => {
    render(<GoldDittoPanel {...baseProps()} connectedUdids={[]} />)
    expect(screen.getByText('goldditto.error.no_device')).toBeInTheDocument()
    // ① confirm and ② first-try buttons both disabled with no device.
    const confirm = screen.getByText(/goldditto\.confirm/)
    const firstTry = screen.getByText(/goldditto\.first_try/)
    expect(confirm).toBeDisabled()
    expect(firstTry).toBeDisabled()
  })

  it('enables ① confirm once a valid A coord is entered and fires onConfirmLocation with parsed lat/lng', async () => {
    const props = baseProps()
    render(<GoldDittoPanel {...props} />)
    const confirm = screen.getByText(/goldditto\.confirm/)
    // No A coord yet -> confirm disabled.
    expect(confirm).toBeDisabled()

    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '25.033, 121.565' } })

    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(props.onConfirmLocation).toHaveBeenCalledTimes(1)
    expect(props.onConfirmLocation).toHaveBeenCalledWith(25.033, 121.565)
  })

  it('fires onCycle with target "B" and clamped wait_seconds when A, B, and wait are all valid', () => {
    const props = baseProps()
    render(<GoldDittoPanel {...props} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '10, 20' } })
    fireEvent.change(inputs[1], { target: { value: '30, 40' } })

    const wait = screen.getByRole('spinbutton') // the number input
    fireEvent.change(wait, { target: { value: '4.5' } })

    const firstTry = screen.getByText(/goldditto\.first_try/)
    expect(firstTry).toBeEnabled()
    fireEvent.click(firstTry)

    expect(props.onCycle).toHaveBeenCalledTimes(1)
    expect(props.onCycle).toHaveBeenCalledWith('B', {
      lat_a: 10,
      lng_a: 20,
      lat_b: 30,
      lng_b: 40,
      wait_seconds: 4.5,
    })
  })

  it('clamps wait_seconds above 10 down to 10 in the onCycle args', () => {
    const props = baseProps()
    render(<GoldDittoPanel {...props} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '1, 2' } })
    fireEvent.change(inputs[1], { target: { value: '3, 4' } })
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '99' } })

    fireEvent.click(screen.getByText(/goldditto\.first_try/))
    expect(props.onCycle).toHaveBeenCalledWith(
      'B',
      expect.objectContaining({ wait_seconds: 10 }),
    )
  })

  it('shows the same-A/B warning when A and B resolve to the same coord', () => {
    const props = baseProps()
    render(<GoldDittoPanel {...props} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '5, 6' } })
    expect(screen.queryByText('goldditto.warn_same_ab')).toBeNull()
    fireEvent.change(inputs[1], { target: { value: '5, 6' } })
    expect(screen.getByText('goldditto.warn_same_ab')).toBeInTheDocument()
  })

  it('disables ② first-try while a cycle is in progress', () => {
    const props = baseProps()
    const { rerender } = render(<GoldDittoPanel {...props} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '10, 20' } })
    fireEvent.change(inputs[1], { target: { value: '30, 40' } })
    expect(screen.getByText(/goldditto\.first_try/)).toBeEnabled()

    rerender(<GoldDittoPanel {...props} isCycling={true} />)
    expect(screen.getByText(/goldditto\.first_try/)).toBeDisabled()
  })

  it('seeds A from externalAValue (map right-click push)', () => {
    const props = baseProps()
    const { rerender } = render(<GoldDittoPanel {...props} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    expect((inputs[0] as HTMLInputElement).value).toBe('')
    rerender(
      <GoldDittoPanel {...props} externalAValue={{ coord: '48.8566, 2.3522' }} />,
    )
    expect(
      (screen.getAllByPlaceholderText('lat, lng')[0] as HTMLInputElement).value,
    ).toBe('48.8566, 2.3522')
  })

  it('opens the bookmark picker and writes the picked coord into the A field', () => {
    const props = baseProps()
    render(<GoldDittoPanel {...props} />)
    // The 📚 button for the A row is the first one.
    const pickButtons = screen.getAllByTitle(/pick_from_bookmarks_tooltip/)
    fireEvent.click(pickButtons[0])
    expect(screen.getByTestId('picker')).toHaveAttribute('data-side', 'A')

    fireEvent.click(screen.getByTestId('picker-pick'))
    const aInput = screen.getAllByPlaceholderText('lat, lng')[0] as HTMLInputElement
    expect(aInput.value).toBe('12.500000, 34.250000')
  })

  it('confirms an end-event cascade: shows modal, calls onCategoryDeleteCascade on confirm', async () => {
    const props = baseProps()
    props.onCategoryDeleteCascade = vi.fn().mockResolvedValue(undefined)
    render(<GoldDittoPanel {...props} />)
    fireEvent.click(screen.getAllByTitle(/pick_from_bookmarks_tooltip/)[0])
    fireEvent.click(screen.getByTestId('picker-end'))

    // Modal appears with the cascade confirm button.
    const confirmBtn = await screen.findByText('bm.delete.cascade_confirm')
    expect(confirmBtn).toBeInTheDocument()

    fireEvent.click(confirmBtn)
    await waitFor(() =>
      expect(props.onCategoryDeleteCascade).toHaveBeenCalledWith('cat-1'),
    )
    // After the async cascade resolves the modal closes.
    await waitFor(() =>
      expect(screen.queryByText('bm.delete.cascade_confirm')).toBeNull(),
    )
  })

  it('restores A/B/wait from localStorage on mount', () => {
    localStorage.setItem('goldditto.A', '1.1, 2.2')
    localStorage.setItem('goldditto.B', '3.3, 4.4')
    localStorage.setItem('goldditto.wait_seconds', '7.0')
    render(<GoldDittoPanel {...baseProps()} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    expect((inputs[0] as HTMLInputElement).value).toBe('1.1, 2.2')
    expect((inputs[1] as HTMLInputElement).value).toBe('3.3, 4.4')
    expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('7.0')
  })

  it('shows the missing-B hint under a disabled ② when only A is filled', async () => {
    render(<GoldDittoPanel {...baseProps()} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '10, 20' } }) // A valid, B empty
    expect(screen.getByText(/goldditto\.first_try/)).toBeDisabled()
    expect(screen.getByText('goldditto.need_b')).toBeInTheDocument()
  })

  it('hides the prerequisite hint once A, B and wait are all valid (② enabled)', async () => {
    render(<GoldDittoPanel {...baseProps()} />)
    const inputs = screen.getAllByPlaceholderText('lat, lng')
    fireEvent.change(inputs[0], { target: { value: '10, 20' } })
    fireEvent.change(inputs[1], { target: { value: '30, 40' } })
    expect(screen.getByText(/goldditto\.first_try/)).toBeEnabled()
    expect(screen.queryByText('goldditto.need_b')).toBeNull()
    expect(screen.queryByText('goldditto.need_a')).toBeNull()
  })
})
