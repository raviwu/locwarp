import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useBookmarkSelection } from './useBookmarkSelection'

type Bm = { id?: string }

const identityT = (k: string) => k

function makeBookmarks(ids: string[]): Bm[] {
  return ids.map((id) => ({ id }))
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useBookmarkSelection', () => {
  it('toggleSelected adds then removes an id', () => {
    const onBookmarkDelete = vi.fn()
    const { result } = renderHook(() =>
      useBookmarkSelection({
        bookmarks: makeBookmarks(['a', 'b']),
        onBookmarkDelete,
        t: identityT,
      }),
    )

    act(() => result.current.toggleSelected('a'))
    expect(result.current.selectedIds.has('a')).toBe(true)

    act(() => result.current.toggleSelected('a'))
    expect(result.current.selectedIds.has('a')).toBe(false)
  })

  it('select-all then bulk-delete fires one confirm and one onBookmarkDelete per id', async () => {
    const onBookmarkDelete = vi.fn()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const bookmarks = makeBookmarks(['a', 'b', 'c'])
    const { result } = renderHook(() =>
      useBookmarkSelection({ bookmarks, onBookmarkDelete, t: identityT }),
    )

    act(() => {
      result.current.enterMultiSelect()
    })
    act(() => {
      result.current.toggleSelectAll()
    })
    expect(result.current.selectedIds.size).toBe(3)

    await act(async () => {
      await result.current.handleBulkDelete()
    })

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(onBookmarkDelete).toHaveBeenCalledTimes(3)
    const deleted = onBookmarkDelete.mock.calls.map((c) => c[0]).sort()
    expect(deleted).toEqual(['a', 'b', 'c'])
    // exits multi-select after the batch
    expect(result.current.multiSelect).toBe(false)
    expect(result.current.selectedIds.size).toBe(0)
  })

  it('dismissed confirm performs zero deletes', async () => {
    const onBookmarkDelete = vi.fn()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const bookmarks = makeBookmarks(['a', 'b', 'c'])
    const { result } = renderHook(() =>
      useBookmarkSelection({ bookmarks, onBookmarkDelete, t: identityT }),
    )

    act(() => {
      result.current.toggleSelectAll()
    })
    expect(result.current.selectedIds.size).toBe(3)

    await act(async () => {
      await result.current.handleBulkDelete()
    })

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(onBookmarkDelete).not.toHaveBeenCalled()
  })

  it('empty selection short-circuits: no confirm, no delete', async () => {
    const onBookmarkDelete = vi.fn()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { result } = renderHook(() =>
      useBookmarkSelection({
        bookmarks: makeBookmarks(['a']),
        onBookmarkDelete,
        t: identityT,
      }),
    )

    await act(async () => {
      await result.current.handleBulkDelete()
    })

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(onBookmarkDelete).not.toHaveBeenCalled()
  })

  it('toggleSelectAll clears when everything is already selected', () => {
    const onBookmarkDelete = vi.fn()
    const { result } = renderHook(() =>
      useBookmarkSelection({
        bookmarks: makeBookmarks(['a', 'b']),
        onBookmarkDelete,
        t: identityT,
      }),
    )

    act(() => result.current.toggleSelectAll())
    expect(result.current.selectedIds.size).toBe(2)
    act(() => result.current.toggleSelectAll())
    expect(result.current.selectedIds.size).toBe(0)
  })
})
