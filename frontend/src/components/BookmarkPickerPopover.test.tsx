import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { BookmarkPickerPopover } from './BookmarkPickerPopover'

// i18n passthrough: t(key) returns the key.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

const anchorRect = {
  bottom: 100,
  left: 50,
  top: 80,
  right: 150,
  width: 100,
  height: 20,
  x: 50,
  y: 80,
  toJSON: () => ({}),
} as DOMRect

const categories = [
  { id: 'cat-food', name: 'Food', color: '#f00' },
  { id: 'cat-bar', name: 'Bars', color: '#0f0' },
]

const ramen = { id: 'b1', name: 'Ramen Shop', lat: 35.123456, lng: 139.987654, category_id: 'cat-food' }
const sushi = { id: 'b2', name: 'Sushi Bar', lat: 35.222222, lng: 139.333333, category_id: 'cat-food' }
const whiskey = { id: 'b3', name: 'Whiskey Den', lat: 35.5, lng: 139.5, category_id: 'cat-bar' }

const bookmarksByCategoryId = {
  'cat-food': [ramen, sushi],
  'cat-bar': [whiskey],
}

function baseProps(overrides: Partial<React.ComponentProps<typeof BookmarkPickerPopover>> = {}) {
  return {
    open: true,
    side: 'A' as const,
    anchorRect,
    categories,
    bookmarksByCategoryId,
    initialCategoryId: 'cat-food',
    isCycling: false,
    onClose: vi.fn(),
    onPickCoord: vi.fn(),
    onCategoryChange: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
})

describe('BookmarkPickerPopover', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<BookmarkPickerPopover {...baseProps({ open: false })} />)
    expect(container.firstChild).toBeNull()
    expect(document.querySelector('[data-bookmark-picker-popover]')).toBeNull()
  })

  it('renders nothing when anchorRect is null', () => {
    render(<BookmarkPickerPopover {...baseProps({ anchorRect: null })} />)
    expect(document.querySelector('[data-bookmark-picker-popover]')).toBeNull()
  })

  it('renders the bookmarks of the initially-selected category with formatted coords', () => {
    render(<BookmarkPickerPopover {...baseProps()} />)
    expect(screen.getByText('Ramen Shop')).toBeInTheDocument()
    expect(screen.getByText('Sushi Bar')).toBeInTheDocument()
    // 6-decimal coordinate line.
    expect(screen.getByText('35.123456, 139.987654')).toBeInTheDocument()
    // Bookmarks from the non-selected category are not shown.
    expect(screen.queryByText('Whiskey Den')).not.toBeInTheDocument()
  })

  it('calls onPickCoord with the bookmark and then onClose when a row is clicked', () => {
    const onPickCoord = vi.fn()
    const onClose = vi.fn()
    render(<BookmarkPickerPopover {...baseProps({ onPickCoord, onClose })} />)
    fireEvent.click(screen.getByText('Ramen Shop'))
    expect(onPickCoord).toHaveBeenCalledTimes(1)
    expect(onPickCoord).toHaveBeenCalledWith(ramen)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('switches the visible list when a different category is chosen and persists last-used', () => {
    const onCategoryChange = vi.fn()
    render(<BookmarkPickerPopover {...baseProps({ onCategoryChange })} />)
    const select = screen.getByDisplayValue('Food') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'cat-bar' } })
    expect(onCategoryChange).toHaveBeenCalledWith('cat-bar')
    expect(screen.getByText('Whiskey Den')).toBeInTheDocument()
    expect(screen.queryByText('Ramen Shop')).not.toBeInTheDocument()
  })

  it('shows the empty message when the selected category has no bookmarks', () => {
    render(
      <BookmarkPickerPopover
        {...baseProps({ bookmarksByCategoryId: { 'cat-food': [] }, initialCategoryId: 'cat-food' })}
      />,
    )
    expect(screen.getByText('bm.picker.empty')).toBeInTheDocument()
  })

  it('hides ended categories unless "include ended" is checked', () => {
    const categoryDates = {
      'cat-bar': { start_date: '2000-01-01', end_date: '2000-12-31' }, // long ended
    }
    render(<BookmarkPickerPopover {...baseProps({ categoryDates, initialCategoryId: 'cat-food' })} />)
    const select = screen.getByDisplayValue('Food')
    // Ended category not offered.
    expect(within(select).queryByRole('option', { name: 'Bars' })).not.toBeInTheDocument()

    // Tick "include ended" → ended category becomes selectable.
    fireEvent.click(screen.getByRole('checkbox'))
    expect(within(select).getByRole('option', { name: 'Bars' })).toBeInTheDocument()
    expect(localStorage.getItem('goldditto.picker.A.includeEnded')).toBe('true')
  })

  it('fires onEndEvent with category id and current bookmark count', () => {
    const onEndEvent = vi.fn()
    render(<BookmarkPickerPopover {...baseProps({ onEndEvent })} />)
    fireEvent.click(screen.getByText('bm.picker.end_event'))
    expect(onEndEvent).toHaveBeenCalledWith('cat-food', 2)
  })

  it('disables the End-event button while cycling', () => {
    const onEndEvent = vi.fn()
    render(<BookmarkPickerPopover {...baseProps({ onEndEvent, isCycling: true })} />)
    const btn = screen.getByText('bm.picker.end_event') as HTMLButtonElement
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    expect(onEndEvent).not.toHaveBeenCalled()
  })

  it('renders the A-side title', () => {
    render(<BookmarkPickerPopover {...baseProps({ side: 'A' })} />)
    expect(screen.getByText('bm.picker.title_a')).toBeInTheDocument()
  })

  it('calls onClose when the Close button is clicked', () => {
    const onClose = vi.fn()
    render(<BookmarkPickerPopover {...baseProps({ onClose })} />)
    fireEvent.click(screen.getByText('bm.picker.close'))
    expect(onClose).toHaveBeenCalled()
  })
})
