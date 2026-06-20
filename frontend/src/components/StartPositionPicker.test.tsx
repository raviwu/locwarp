import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StartPositionPicker from './StartPositionPicker'
import type {
  BookmarkDropdownItem,
  BookmarkDropdownCategory,
} from './BookmarkDropdown'

// i18n passthrough: t(key) → key, so we can assert on raw label keys.
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

describe('StartPositionPicker', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders the section label and the bookmark dropdown', () => {
    render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={vi.fn()}
      />,
    )
    // label uses the i18n key (passthrough)
    expect(screen.getByText('panel.start_picker_label')).toBeInTheDocument()
    // the dropdown is rendered with the picker's aria-label
    const select = screen.getByRole('combobox', { name: 'panel.start_picker_label' })
    expect(select).toBeInTheDocument()
    // each bookmark surfaces as an option
    expect(screen.getByRole('option', { name: 'Ramen Shop' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Whiskey Den' })).toBeInTheDocument()
  })

  it('calls onPick with lat/lng/name when a bookmark is selected', () => {
    const onPick = vi.fn()
    render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={onPick}
      />,
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'b3' } })
    expect(onPick).toHaveBeenCalledTimes(1)
    expect(onPick).toHaveBeenCalledWith(35.3, 139.3, 'Whiskey Den')
  })

  it('persists the selected id to localStorage under the storage key', () => {
    render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={vi.fn()}
      />,
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'b2' } })
    expect(localStorage.getItem('locwarp.start.nav')).toBe('b2')
  })

  it('hydrates the initial selection from localStorage for the storage key', () => {
    localStorage.setItem('locwarp.start.nav', 'b1')
    render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={vi.fn()}
      />,
    )
    const select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('b1')
  })

  it('does not fire onPick on initial render from a persisted selection', () => {
    localStorage.setItem('locwarp.start.nav', 'b1')
    const onPick = vi.fn()
    render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={onPick}
      />,
    )
    expect(onPick).not.toHaveBeenCalled()
  })

  it('clears the persisted selection when reset back to the placeholder', () => {
    localStorage.setItem('locwarp.start.nav', 'b1')
    render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={vi.fn()}
      />,
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } })
    expect(localStorage.getItem('locwarp.start.nav')).toBeNull()
  })

  it('re-loads the saved selection when the storage key changes (mode switch)', () => {
    localStorage.setItem('locwarp.start.nav', 'b1')
    localStorage.setItem('locwarp.start.loop', 'b3')
    const { rerender } = render(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.nav"
        onPick={vi.fn()}
      />,
    )
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('b1')

    rerender(
      <StartPositionPicker
        bookmarks={bookmarks}
        categories={categories}
        storageKey="locwarp.start.loop"
        onPick={vi.fn()}
      />,
    )
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('b3')
  })
})
