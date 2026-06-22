import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useBookmarkUiState } from './useBookmarkUiState'

// Stub api gateway — only the two ui-state methods the hook touches. Each test
// resets the spies and provides a default persisted state (nothing saved).
const getBookmarkUiState = vi.fn()
const setBookmarkUiState = vi.fn()
const stubApi = () =>
  ({ getBookmarkUiState, setBookmarkUiState } as any)

// Build N category-tagged bookmark stubs (round-robin) — only `.category` is
// read by the hook; count drives the AUTO_COLLAPSE_THRESHOLD crossing.
function makeBookmarks(n: number, categories: string[]) {
  return Array.from({ length: n }, (_, i) => ({
    category: categories[i % categories.length],
  }))
}

beforeEach(() => {
  getBookmarkUiState.mockReset()
  setBookmarkUiState.mockReset()
  getBookmarkUiState.mockResolvedValue({
    expanded_categories: null,
    hidden_categories: null,
  })
  setBookmarkUiState.mockResolvedValue({
    status: 'ok',
    expanded_categories: null,
    hidden_categories: null,
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useBookmarkUiState — threshold crossing recompute', () => {
  // The collapse recompute fires ONLY on a prevOverThreshold crossing, not on
  // every render. Crossing UP auto-collapses all; crossing DOWN restores the
  // live toggle choice (savedExpandedRef), not the session-start snapshot.
  it('crosses up (auto-collapse) then down (restore live toggle, not session snapshot)', async () => {
    const categories = ['Default', 'Work', 'Trips']
    // "Work" is an ENDED event (past end_date), so its DEFAULT collapsed-state
    // is `true`. Session-start saved snapshot is null → at mount Work collapses
    // by default. This is what lets us distinguish "restore live toggle" from
    // "restore session-start snapshot": the live toggle EXPANDS Work, and a
    // correct cross-down keeps it expanded (savedExpandedRef), whereas falling
    // back to the session-start (null) snapshot would re-collapse it.
    const categoryDates = { Work: { start_date: '', end_date: '2000-01-01' } }
    // Stable references across rerenders so the mount effect ([api]) runs once
    // and refs (savedExpandedRef / prevOverThresholdRef) are never reset by a
    // remount. Only `bookmarks` varies — passed through rerender props.
    const api = stubApi()
    const few = makeBookmarks(4, categories)
    const many = makeBookmarks(31, categories)

    const { result, rerender } = renderHook(
      ({ bookmarks }: { bookmarks: { category: string }[] }) =>
        useBookmarkUiState({ api, bookmarks, categories, categoryDates }),
      { initialProps: { bookmarks: few } },
    )

    await waitFor(() => expect(result.current.uiStateLoaded).toBe(true))
    // The mount fetch must have fired exactly once (no remount).
    expect(getBookmarkUiState).toHaveBeenCalledTimes(1)
    // Under threshold, no saved snapshot: Work collapses by default (ended),
    // the other two (no dates) stay expanded.
    await waitFor(() =>
      expect(result.current.collapsed).toEqual({
        Default: false,
        Work: true,
        Trips: false,
      }),
    )

    // User manually EXPANDS the ended "Work" category. toggleCategory mutates
    // savedExpandedRef → the live expanded set is now [Default, Work, Trips].
    act(() => { result.current.toggleCategory('Work') })
    expect(result.current.collapsed.Work).toBe(false)

    // Cross UP (> 30 bookmarks) → recompute fires → ALL collapse.
    act(() => { rerender({ bookmarks: many }) })
    await waitFor(() =>
      expect(result.current.collapsed).toEqual({
        Default: true,
        Work: true,
        Trips: true,
      }),
    )

    // Cross DOWN (back under threshold) → recompute restores the LIVE manual
    // choice: Work stays EXPANDED because savedExpandedRef now contains it.
    // Restoring the session-start snapshot (null → ended default) would have
    // re-collapsed Work — so this asserts the savedExpandedRef side-effect.
    act(() => { rerender({ bookmarks: few }) })
    await waitFor(() =>
      expect(result.current.collapsed).toEqual({
        Default: false,
        Work: false,
        Trips: false,
      }),
    )
    // Still no remount across the two crossings.
    expect(getBookmarkUiState).toHaveBeenCalledTimes(1)
  })
})

describe('useBookmarkUiState — hidden persistence', () => {
  // Hidden = immediate single { hidden_categories } POST; the initial fetch is
  // NOT echoed back as a write (hiddenLoadedRef gate).
  it('persists hidden as one immediate partial POST and never echoes the initial fetch', async () => {
    const categories = ['Default', 'Work']
    const { result } = renderHook(() =>
      useBookmarkUiState({
        api: stubApi(),
        bookmarks: makeBookmarks(4, categories),
        categories,
        categoryDates: {},
      }),
    )

    await waitFor(() => expect(getBookmarkUiState).toHaveBeenCalledTimes(1))
    // After load, no write should have happened (no echo of the initial fetch).
    expect(setBookmarkUiState).not.toHaveBeenCalled()

    act(() => { result.current.hideCategory('Work') })

    await waitFor(() => expect(setBookmarkUiState).toHaveBeenCalledTimes(1))
    const body = setBookmarkUiState.mock.calls[0][0]
    expect(body).toEqual({ hidden_categories: ['Work'] })
    // Partial POST: never carries expanded_categories.
    expect(body).not.toHaveProperty('expanded_categories')
    expect(result.current.hidden.has('Work')).toBe(true)
  })
})

describe('useBookmarkUiState — expanded persistence', () => {
  // Expanded = debounced into ONE { expanded_categories } POST after 400ms.
  it('debounces expanded into a single { expanded_categories } POST after 400ms', async () => {
    const categories = ['Default', 'Work']
    const { result } = renderHook(() =>
      useBookmarkUiState({
        api: stubApi(),
        bookmarks: makeBookmarks(4, categories),
        categories,
        categoryDates: {},
      }),
    )

    // Drain the mount fetch on real timers, then switch to fake timers for the
    // debounce window.
    await waitFor(() => expect(result.current.uiStateLoaded).toBe(true))
    await waitFor(() => expect(result.current.collapsed.Default).toBe(false))
    expect(setBookmarkUiState).not.toHaveBeenCalled()

    vi.useFakeTimers()

    // Two flips in quick succession — both collapse → expanded list is [].
    act(() => { result.current.toggleCategory('Default') })
    act(() => { result.current.toggleCategory('Work') })

    // Before the window elapses: no POST.
    act(() => { vi.advanceTimersByTime(399) })
    expect(setBookmarkUiState).not.toHaveBeenCalled()

    // Crossing 400ms: exactly one POST, carrying only expanded_categories.
    act(() => { vi.advanceTimersByTime(2) })
    expect(setBookmarkUiState).toHaveBeenCalledTimes(1)
    const body = setBookmarkUiState.mock.calls[0][0]
    expect(body).toHaveProperty('expanded_categories')
    expect(body).not.toHaveProperty('hidden_categories')
    expect(body.expanded_categories).toEqual([])
  })
})
