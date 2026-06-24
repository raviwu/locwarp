import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

// Identity translator so i18n keys render verbatim — mirrors BookmarkList.test.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
}))

import CategoryManagerPanel from './CategoryManagerPanel'

afterEach(() => {
  vi.restoreAllMocks()
})

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    categories: ['Default', 'Work', 'Trips'],
    bookmarkCounts: { Default: 1, Work: 2, Trips: 3 },
    resolveColor: () => '#6c8cff',
    displayCat: (c: string) => c,
    newCategoryName: '',
    onNewCategoryNameChange: vi.fn(),
    onCategoryAdd: vi.fn(),
    onCategoryDelete: vi.fn(),
    onCategoryDeleteCascade: vi.fn(),
    onCategoryEdit: vi.fn(),
    ...over,
  } as any
}

describe('CategoryManagerPanel', () => {
  it('renders each category name', () => {
    render(<CategoryManagerPanel {...makeProps()} />)
    expect(screen.getByText('Work')).toBeTruthy()
    expect(screen.getByText('Trips')).toBeTruthy()
    expect(screen.getByText('Default')).toBeTruthy()
  })

  it('does not show edit/delete controls for the built-in Default category', () => {
    render(<CategoryManagerPanel {...makeProps()} />)
    const editButtons = screen.getAllByTitle('bm.cat.edit_title')
    // Only the two non-default categories get an edit pencil.
    expect(editButtons.length).toBe(2)
  })

  it('adds a category via the Enter key and clears the input', () => {
    const onCategoryAdd = vi.fn()
    const onNewCategoryNameChange = vi.fn()
    render(
      <CategoryManagerPanel
        {...makeProps({ newCategoryName: 'Beaches', onCategoryAdd, onNewCategoryNameChange })}
      />,
    )
    const input = screen.getByPlaceholderText('bm.add_category')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onCategoryAdd).toHaveBeenCalledWith('Beaches')
    expect(onNewCategoryNameChange).toHaveBeenCalledWith('')
  })

  it('adds a category via the new-category button', () => {
    const onCategoryAdd = vi.fn()
    render(<CategoryManagerPanel {...makeProps({ newCategoryName: 'Beaches', onCategoryAdd })} />)
    fireEvent.click(screen.getByText('bm.new_category'))
    expect(onCategoryAdd).toHaveBeenCalledWith('Beaches')
  })

  it('soft-deletes a category through the dropdown after confirm', () => {
    const onCategoryDelete = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CategoryManagerPanel {...makeProps({ onCategoryDelete })} />)

    // Open the Work category's delete dropdown (it's the row that has 'Work').
    const workRow = screen.getByText('Work').closest('div') as HTMLElement
    // The dropdown trigger is the trash button (no title) inside the row.
    const trashBtns = within(workRow.parentElement as HTMLElement).getAllByRole('button')
    // Find the trash trigger within the Work row specifically.
    const rowButtons = within(workRow).queryAllByRole('button')
    const trigger = rowButtons[rowButtons.length - 1]
    fireEvent.click(trigger)

    fireEvent.click(screen.getByText('bm.delete.softdelete_label'))
    expect(onCategoryDelete).toHaveBeenCalledWith('Work')
    void trashBtns
  })

  it('cascade-deletes with the bookmark count after confirm', () => {
    const onCategoryDeleteCascade = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CategoryManagerPanel {...makeProps({ onCategoryDeleteCascade })} />)

    const tripsRow = screen.getByText('Trips').closest('div') as HTMLElement
    const rowButtons = within(tripsRow).queryAllByRole('button')
    fireEvent.click(rowButtons[rowButtons.length - 1])

    // Cascade label interpolates the count (3 for Trips).
    fireEvent.click(
      screen.getByText((txt) => txt.startsWith('bm.delete.cascade_label')),
    )
    expect(onCategoryDeleteCascade).toHaveBeenCalledWith('Trips', 3)
  })
})

describe('CategoryManagerPanel delete-dropdown a11y (U22)', () => {
  it('the delete trigger exposes an accessible name', () => {
    render(<CategoryManagerPanel {...makeProps()} />)
    // One trigger per non-default category (Work, Trips).
    expect(screen.getAllByRole('button', { name: /bm\.cat\.delete_title/ }).length).toBe(2)
  })

  it('opens a role=menu of role=menuitem choices; clicking soft-delete triggers it', () => {
    const onCategoryDelete = vi.fn()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CategoryManagerPanel {...makeProps({ onCategoryDelete })} />)
    const trigger = screen.getAllByRole('button', { name: /bm\.cat\.delete_title/ })[0]
    fireEvent.click(trigger)
    expect(screen.getByRole('menu')).toBeTruthy()
    const soft = screen.getByRole('menuitem', { name: /bm\.delete\.softdelete_label/ })
    expect(soft.tagName).toBe('BUTTON')
    fireEvent.click(soft)
    expect(onCategoryDelete).toHaveBeenCalledWith('Work')
    confirmSpy.mockRestore()
  })

  it('the delete-dropdown menu container has an accessible name', () => {
    render(<CategoryManagerPanel {...makeProps()} />)
    // Open the first non-default category's delete dropdown.
    const trigger = screen.getAllByRole('button', { name: /bm\.cat\.delete_title/ })[0]
    fireEvent.click(trigger)
    // The role="menu" container must have an accessible name so screen-reader
    // users know what the menu controls (U22 a11y requirement).
    const menu = screen.getByRole('menu', { name: /bm\.cat\.delete_title/ })
    expect(menu).toBeTruthy()
  })
})
