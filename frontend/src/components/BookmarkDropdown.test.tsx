import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import BookmarkDropdown, {
  BookmarkDropdownItem,
  BookmarkDropdownCategory,
} from './BookmarkDropdown'

// i18n passthrough: t(key) returns the key.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

const categories: BookmarkDropdownCategory[] = [
  { id: 'cat-food', name: 'Food' },
  { id: 'cat-bar', name: 'Bars' },
]

const bookmarks: BookmarkDropdownItem[] = [
  { id: 'b1', name: 'Ramen Shop', lat: 35.1, lng: 139.1, category_id: 'cat-food' },
  { id: 'b2', name: 'Sushi Bar', lat: 35.2, lng: 139.2, category_id: 'cat-food' },
  { id: 'b3', name: 'Whiskey Den', lat: 35.3, lng: 139.3, category_id: 'cat-bar' },
]

describe('BookmarkDropdown', () => {
  it('renders the empty placeholder when there are no bookmarks', () => {
    render(
      <BookmarkDropdown
        bookmarks={[]}
        categories={categories}
        value={null}
        onChange={vi.fn()}
        placeholderText="Pick one"
        emptyText="No bookmarks yet"
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('No bookmarks yet')
    // No <select> rendered in the empty state.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('renders each bookmark grouped under its category', () => {
    render(
      <BookmarkDropdown
        bookmarks={bookmarks}
        categories={categories}
        value={null}
        onChange={vi.fn()}
        placeholderText="Pick one"
        emptyText="empty"
        ariaLabel="bm-select"
      />,
    )
    const select = screen.getByRole('combobox', { name: 'bm-select' })
    // All three bookmark options present.
    expect(within(select).getByRole('option', { name: 'Ramen Shop' })).toBeInTheDocument()
    expect(within(select).getByRole('option', { name: 'Sushi Bar' })).toBeInTheDocument()
    expect(within(select).getByRole('option', { name: 'Whiskey Den' })).toBeInTheDocument()

    // optgroups carry the category names as labels.
    const food = select.querySelector('optgroup[label="Food"]')
    const bars = select.querySelector('optgroup[label="Bars"]')
    expect(food).not.toBeNull()
    expect(bars).not.toBeNull()
    expect(within(food as HTMLElement).getAllByRole('option')).toHaveLength(2)
    expect(within(bars as HTMLElement).getAllByRole('option')).toHaveLength(1)
  })

  it('shows the placeholder as a disabled option and reflects value', () => {
    render(
      <BookmarkDropdown
        bookmarks={bookmarks}
        categories={categories}
        value="b2"
        onChange={vi.fn()}
        placeholderText="Choose a place"
        emptyText="empty"
      />,
    )
    const select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('b2')
    const placeholder = within(select).getByRole('option', { name: 'Choose a place' })
    expect(placeholder).toBeDisabled()
  })

  it('calls onChange with the selected bookmark object', () => {
    const onChange = vi.fn()
    render(
      <BookmarkDropdown
        bookmarks={bookmarks}
        categories={categories}
        value={null}
        onChange={onChange}
        placeholderText="Pick one"
        emptyText="empty"
      />,
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'b3' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'b3', name: 'Whiskey Den', lat: 35.3, lng: 139.3 }),
    )
  })

  it('calls onChange with null when cleared back to the placeholder', () => {
    const onChange = vi.fn()
    render(
      <BookmarkDropdown
        bookmarks={bookmarks}
        categories={categories}
        value="b1"
        onChange={onChange}
        placeholderText="Pick one"
        emptyText="empty"
      />,
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('places bookmarks with unknown/missing category into the "Other" group', () => {
    const withOrphan: BookmarkDropdownItem[] = [
      ...bookmarks,
      { id: 'b4', name: 'Mystery Spot', lat: 1, lng: 2, category_id: 'nope' },
      { id: 'b5', name: 'No Category', lat: 3, lng: 4 },
    ]
    render(
      <BookmarkDropdown
        bookmarks={withOrphan}
        categories={categories}
        value={null}
        onChange={vi.fn()}
        placeholderText="Pick one"
        emptyText="empty"
      />,
    )
    const select = screen.getByRole('combobox')
    // The "Other" optgroup uses the i18n key (mocked to passthrough).
    const other = select.querySelector('optgroup[label="panel.bookmark_dropdown_other"]')
    expect(other).not.toBeNull()
    expect(within(other as HTMLElement).getByRole('option', { name: 'Mystery Spot' })).toBeInTheDocument()
    expect(within(other as HTMLElement).getByRole('option', { name: 'No Category' })).toBeInTheDocument()
  })
})
