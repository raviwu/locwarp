import { useState, useCallback, useEffect, useRef } from 'react'
import * as api from '../services/api'

export interface Bookmark {
  id: string
  name: string
  lat: number
  lng: number
  category_id?: string
  note?: string
  created_at?: string
}

export interface BookmarkCategory {
  id: string
  name: string
  color: string
  sort_order?: number
  // Soft-archive event window. Empty string = unbounded; both empty = evergreen.
  start_date?: string
  end_date?: string
}

export function useBookmarks() {
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [categories, setCategories] = useState<BookmarkCategory[]>([])
  const [loading, setLoading] = useState(false)
  const mountedRef = useRef(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [bms, cats] = await Promise.all([
        api.getBookmarks(),
        api.getCategories(),
      ])
      if (!mountedRef.current) return
      setBookmarks(Array.isArray(bms) ? bms : bms.bookmarks ?? [])
      setCategories(Array.isArray(cats) ? cats : [])
    } catch (err) {
      console.error('Failed to load bookmarks:', err)
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  // Load on mount
  useEffect(() => {
    mountedRef.current = true
    refresh()
    return () => {
      mountedRef.current = false
    }
  }, [refresh])

  const createBookmark = useCallback(
    async (bm: Omit<Bookmark, 'id'>) => {
      const created = await api.createBookmark(bm)
      await refresh()
      return created
    },
    [refresh],
  )

  const deleteBookmark = useCallback(
    async (id: string) => {
      await api.deleteBookmark(id)
      setBookmarks((prev) => prev.filter((b) => b.id !== id))
    },
    [],
  )

  const updateBookmark = useCallback(
    async (id: string, data: Partial<Bookmark>) => {
      const updated = await api.updateBookmark(id, data)
      await refresh()
      return updated
    },
    [refresh],
  )

  const moveBookmarks = useCallback(
    async (ids: string[], categoryId: string) => {
      await api.moveBookmarks(ids, categoryId)
      await refresh()
    },
    [refresh],
  )

  const createCategory = useCallback(
    async (cat: api.CategoryPayload) => {
      const created = await api.createCategory(cat)
      await refresh()
      return created
    },
    [refresh],
  )

  const deleteCategory = useCallback(
    async (id: string, cascade = false) => {
      // Optimistic: drop the category and either delete or re-home its
      // bookmarks locally so the panel updates instantly. The authoritative
      // refresh below reconciles; on backend failure, refresh() restores
      // the unchanged server state and we re-raise.
      setCategories((prev) => prev.filter((c) => c.id !== id))
      setBookmarks((prev) =>
        cascade
          ? prev.filter((b) => b.category_id !== id)
          : prev.map((b) =>
              b.category_id === id ? { ...b, category_id: 'default' } : b,
            ),
      )
      try {
        await api.deleteCategory(id, cascade)
        await refresh()
      } catch (e) {
        await refresh()
        throw e
      }
    },
    [refresh],
  )

  const updateCategory = useCallback(
    async (id: string, data: api.CategoryPayload) => {
      const updated = await api.updateCategory(id, data)
      await refresh()
      return updated
    },
    [refresh],
  )

  return {
    bookmarks,
    categories,
    loading,
    createBookmark,
    updateBookmark,
    deleteBookmark,
    moveBookmarks,
    createCategory,
    deleteCategory,
    updateCategory,
    refresh,
  }
}
