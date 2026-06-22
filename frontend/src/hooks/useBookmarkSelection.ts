import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

interface SelectableBookmark {
  id?: string
}

interface UseBookmarkSelectionArgs<B extends SelectableBookmark> {
  // The full bookmark list — drives select-all and the bulk-delete fan-out.
  bookmarks: B[]
  // Parent delete callback. handleBulkDelete fans out one call per selected id.
  onBookmarkDelete: (id: string) => void
  // i18n translator — used to build the confirm() copy. Injected (not imported)
  // so the hook stays decoupled from the i18n module and unit-testable. Typed
  // to the single key it consumes; a translator accepting all keys is
  // assignable here (contravariant param), so callers pass useT() directly.
  t: (key: 'bm.delete_confirm') => string
}

export interface BookmarkSelection {
  // Whether multi-select mode is active. Row clicks toggle selection when on.
  multiSelect: boolean
  selectedIds: Set<string>
  toggleSelected: (id: string) => void
  // Replace the whole selection set (used by per-category select-all).
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>
  // Enter multi-select (no-op if already on).
  enterMultiSelect: () => void
  // Leave multi-select AND clear the selection.
  exitMultiSelect: () => void
  // Footer "select all / deselect all" toggle: all selected => clear; else
  // select every bookmark that has an id.
  toggleSelectAll: () => void
  // window.confirm gate, then one onBookmarkDelete per selected id, then exit.
  handleBulkDelete: () => Promise<void>
}

/**
 * Bookmark multi-select state + bulk-delete logic, carved out of BookmarkList.
 *
 * handleBulkDelete preserves the exact original behavior: a single
 * window.confirm (using the {n}-interpolated 'bm.delete_confirm' copy), then
 * a Promise.all fan-out of onBookmarkDelete (each call individually guarded so
 * one throw doesn't abort the batch), then exitMultiSelect. Deletes nothing
 * when the confirm is dismissed or the selection is empty.
 */
export function useBookmarkSelection<B extends SelectableBookmark>({
  bookmarks,
  onBookmarkDelete,
  t,
}: UseBookmarkSelectionArgs<B>): BookmarkSelection {
  const [multiSelect, setMultiSelect] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const enterMultiSelect = () => setMultiSelect(true)

  const exitMultiSelect = () => {
    setMultiSelect(false)
    setSelectedIds(new Set())
  }

  const toggleSelectAll = () => {
    const allIds = bookmarks.map((b) => b.id).filter((x): x is string => !!x)
    setSelectedIds((prev) =>
      prev.size === allIds.length ? new Set() : new Set(allIds),
    )
  }

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return
    const msg = t('bm.delete_confirm').replace('{n}', String(selectedIds.size))
    if (!window.confirm(msg)) return
    const ids = Array.from(selectedIds)
    await Promise.all(
      ids.map((id) => {
        try {
          return Promise.resolve(onBookmarkDelete(id))
        } catch {
          return Promise.resolve()
        }
      }),
    )
    exitMultiSelect()
  }

  return {
    multiSelect,
    selectedIds,
    toggleSelected,
    setSelectedIds,
    enterMultiSelect,
    exitMultiSelect,
    toggleSelectAll,
    handleBulkDelete,
  }
}
