import React, { useMemo } from 'react'
import { useT } from '../i18n'

export interface BookmarkDropdownItem {
  id?: string
  name: string
  lat: number
  lng: number
  category_id?: string
}

export interface BookmarkDropdownCategory {
  id: string
  name: string
}

interface Props {
  bookmarks: BookmarkDropdownItem[]
  categories: BookmarkDropdownCategory[]
  /** Selected bookmark id; null = nothing selected (placeholder shown). */
  value: string | null
  onChange: (bm: BookmarkDropdownItem | null) => void
  placeholderText: string
  emptyText: string
  ariaLabel?: string
}

const BookmarkDropdown: React.FC<Props> = ({
  bookmarks,
  categories,
  value,
  onChange,
  placeholderText,
  emptyText,
  ariaLabel,
}) => {
  const t = useT()

  // Group bookmarks by category_id. Bookmarks with a missing or unknown
  // category_id fall into a synthetic "Other" group rendered at the end.
  const grouped = useMemo(() => {
    const knownIds = new Set(categories.map((c) => c.id))
    const byCat: Record<string, BookmarkDropdownItem[]> = {}
    const orphans: BookmarkDropdownItem[] = []
    for (const bm of bookmarks) {
      const cid = bm.category_id
      if (cid && knownIds.has(cid)) {
        if (!byCat[cid]) byCat[cid] = []
        byCat[cid].push(bm)
      } else {
        orphans.push(bm)
      }
    }
    return { byCat, orphans }
  }, [bookmarks, categories])

  if (bookmarks.length === 0) {
    return (
      <div
        style={{ fontSize: 12, color: '#9ca3af', padding: '6px 8px' }}
        role="status"
      >
        {emptyText}
      </div>
    )
  }

  // React requires unique keys; bookmarks without `id` get a synthetic key.
  // Such bookmarks cannot be selected (their <option> value won't match `value`),
  // but they still render in their group so the user sees the full list.
  const synthKey = (bm: BookmarkDropdownItem, idx: number) =>
    bm.id ?? `__noid_${idx}_${bm.name}`

  return (
    <select
      aria-label={ariaLabel}
      value={value ?? ''}
      onChange={(e) => {
        const id = e.target.value
        if (!id) {
          onChange(null)
          return
        }
        const found = bookmarks.find((bm) => bm.id === id) ?? null
        onChange(found)
      }}
      style={{
        width: '100%',
        padding: '6px 8px',
        border: '1px solid #4b5563',
        borderRadius: 4,
        background: '#1f2937',
        color: '#fff',
        fontSize: 12,
      }}
    >
      <option value="" disabled>
        {placeholderText}
      </option>
      {categories.map((cat) => {
        const items = grouped.byCat[cat.id]
        if (!items || items.length === 0) return null
        return (
          <optgroup key={cat.id} label={cat.name}>
            {items.map((bm, i) => (
              <option key={synthKey(bm, i)} value={bm.id ?? ''}>
                {bm.name}
              </option>
            ))}
          </optgroup>
        )
      })}
      {grouped.orphans.length > 0 && (
        <optgroup label={t('panel.bookmark_dropdown_other')}>
          {grouped.orphans.map((bm, i) => (
            <option key={synthKey(bm, i)} value={bm.id ?? ''}>
              {bm.name}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  )
}

export default BookmarkDropdown
