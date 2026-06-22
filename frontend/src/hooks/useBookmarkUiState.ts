import { useState, useEffect, useRef } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import {
  getCategoryStatus,
  todayLocal,
  type CategoryStatus,
} from '../utils/categoryStatus'

const AUTO_COLLAPSE_THRESHOLD = 30

interface UseBookmarkUiStateArgs {
  // Injected backend gateway — the hook never reaches services/api directly so
  // it stays unit-testable with a stub. BookmarkList passes useServices().api.
  api: Pick<ApiGateway, 'getBookmarkUiState' | 'setBookmarkUiState'>
  // Drives the AUTO_COLLAPSE_THRESHOLD crossing (count) and the persisted
  // expand/hide lists (category names).
  bookmarks: { category: string }[]
  categories: string[]
  // Per-category event window, keyed by category name. Used to seed a sensible
  // default collapsed-state for ended/upcoming categories under threshold.
  categoryDates?: Record<string, { start_date: string; end_date: string }>
}

export interface BookmarkUiState {
  collapsed: Record<string, boolean>
  toggleCategory: (cat: string) => void
  hidden: Set<string>
  hideCategory: (cat: string) => void
  unhideCategory: (cat: string) => void
  uiStateLoaded: boolean
}

/**
 * Bookmark panel UI-state: per-category collapse/expand + hidden categories,
 * persisted to ~/.locwarp/settings.json via /api/bookmarks/ui-state.
 *
 * Collapse rule (designed so "paste a lot of bookmarks and get them
 * auto-collapsed" always works):
 *   - While bookmarks.length > AUTO_COLLAPSE_THRESHOLD, all categories are
 *     collapsed by default. User can still manually expand one.
 *   - While <= threshold, use the user's saved expand list (or the per-category
 *     default — ended/upcoming collapse — if never saved).
 *   - Crossing the threshold (up or down) resets state to the rule, so a
 *     manual choice from the other regime doesn't leak. We intentionally do
 *     NOT gate on a "user touched anything" flag — that made the auto-rule
 *     inert when a saved list from an earlier session lingered.
 */
export function useBookmarkUiState({
  api,
  bookmarks,
  categories,
  categoryDates,
}: UseBookmarkUiStateArgs): BookmarkUiState {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  // Categories the user has temporarily hidden from the panel.
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  // True once the persisted hidden list has been merged in — gates the
  // persist effect so the initial fetch is not echoed straight back.
  const hiddenLoadedRef = useRef(false)
  const [uiStateLoaded, setUiStateLoaded] = useState(false)
  const uiStateSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savedExpandedRef = useRef<string[] | null>(null)
  const prevOverThresholdRef = useRef<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getBookmarkUiState()
      .then((state) => {
        if (cancelled) return
        savedExpandedRef.current = state.expanded_categories
        if (Array.isArray(state.hidden_categories)) {
          setHidden(new Set(state.hidden_categories))
        }
        hiddenLoadedRef.current = true
      })
      .catch(() => { hiddenLoadedRef.current = true })
      .finally(() => { if (!cancelled) setUiStateLoaded(true) })
    return () => { cancelled = true }
  }, [api])

  useEffect(() => {
    if (!uiStateLoaded) return
    if (categories.length === 0) return
    // Inline default-collapse calc so the effect deps stay on
    // `categoryDates` rather than a per-render helper closure.
    const today = todayLocal()
    const defaultCollapsedFor = (cat: string): boolean => {
      const d = categoryDates?.[cat]
      if (!d) return false
      const s: CategoryStatus = getCategoryStatus(d.start_date, d.end_date, today)
      return s === 'ended' || s === 'upcoming'
    }
    const isOver = bookmarks.length > AUTO_COLLAPSE_THRESHOLD
    const wasOver = prevOverThresholdRef.current
    if (wasOver === null || isOver !== wasOver) {
      if (isOver) {
        const all: Record<string, boolean> = {}
        categories.forEach((c) => { all[c] = true })
        setCollapsed(all)
      } else {
        const saved = savedExpandedRef.current
        if (saved === null) {
          const next: Record<string, boolean> = {}
          categories.forEach((c) => { next[c] = defaultCollapsedFor(c) })
          setCollapsed(next)
        } else {
          const savedSet = new Set(saved)
          const next: Record<string, boolean> = {}
          categories.forEach((c) => {
            // Saved snapshot wins: any explicitly-expanded category stays
            // expanded even if it later flips to ended/upcoming.
            next[c] = savedSet.has(c) ? false : defaultCollapsedFor(c)
          })
          setCollapsed(next)
        }
      }
    }
    prevOverThresholdRef.current = isOver
  }, [uiStateLoaded, bookmarks.length, categories, categoryDates])

  // Debounce saves so that rapid open/close of several categories sends
  // one POST 400ms after the last flip, not one per click.
  const scheduleUiStateSave = (nextCollapsed: Record<string, boolean>) => {
    if (!uiStateLoaded) return // don't overwrite during initial fetch
    if (uiStateSaveTimer.current) clearTimeout(uiStateSaveTimer.current)
    uiStateSaveTimer.current = setTimeout(() => {
      const expanded = categories.filter((c) => !nextCollapsed[c])
      void api.setBookmarkUiState({ expanded_categories: expanded }).catch(() => { /* best effort */ })
    }, 400)
  }

  // Persist the hidden set immediately on change (hide/unhide is a single
  // deliberate click — no debounce needed). Stale categories (deleted since
  // they were hidden) are dropped here so they never linger in settings.json.
  const persistHidden = (nextHidden: Set<string>) => {
    if (!hiddenLoadedRef.current) return // don't echo the initial fetch
    const known = new Set(categories)
    const cleaned = [...nextHidden].filter((c) => known.has(c))
    void api.setBookmarkUiState({ hidden_categories: cleaned }).catch(() => { /* best effort */ })
  }

  const hideCategory = (cat: string) => {
    setHidden((prev) => {
      const next = new Set(prev)
      next.add(cat)
      persistHidden(next)
      return next
    })
  }

  const unhideCategory = (cat: string) => {
    setHidden((prev) => {
      const next = new Set(prev)
      next.delete(cat)
      persistHidden(next)
      return next
    })
  }

  const toggleCategory = (cat: string) => {
    setCollapsed((prev) => {
      const next = { ...prev, [cat]: !prev[cat] }
      // Mirror to savedExpandedRef so a cross-down-under-threshold event
      // restores the user's most recent manual choice, not the stale
      // backend snapshot from session start.
      savedExpandedRef.current = categories.filter((c) => !next[c])
      scheduleUiStateSave(next)
      return next
    })
  }

  return { collapsed, toggleCategory, hidden, hideCategory, unhideCategory, uiStateLoaded }
}
