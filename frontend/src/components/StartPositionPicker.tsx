import React, { useState, useCallback } from 'react'
import { useT } from '../i18n'
import BookmarkDropdown, {
  BookmarkDropdownItem,
  BookmarkDropdownCategory,
} from './BookmarkDropdown'

interface Props {
  bookmarks: BookmarkDropdownItem[]
  categories: BookmarkDropdownCategory[]
  onPick: (lat: number, lng: number, name: string) => void
}

const StartPositionPicker: React.FC<Props> = ({ bookmarks, categories, onPick }) => {
  const t = useT()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const handleChange = useCallback(
    (bm: BookmarkDropdownItem | null) => {
      if (!bm) {
        setSelectedId(null)
        return
      }
      // Briefly mark as selected so the <select> shows the picked label
      // while the teleport request is in-flight; in practice the parent
      // unmounts us almost immediately because currentPosition becomes
      // non-null. Reset to null so a same-pick replay still fires.
      setSelectedId(bm.id ?? null)
      onPick(bm.lat, bm.lng, bm.name)
      // Reset on the next tick so a reuse of the same bookmark works if
      // the parent doesn't unmount us (e.g. teleport failed).
      setTimeout(() => setSelectedId(null), 0)
    },
    [onPick],
  )

  return (
    <div className="section" style={{ margin: '0 0 8px 0' }}>
      <div
        className="section-title"
        style={{ display: 'flex', alignItems: 'center', gap: 6 }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M12 22s-8-7.5-8-13a8 8 0 0116 0c0 5.5-8 13-8 13z" />
          <circle cx="12" cy="9" r="3" />
        </svg>
        {t('panel.start_picker_label')}
      </div>
      <div className="section-content">
        <BookmarkDropdown
          bookmarks={bookmarks}
          categories={categories}
          value={selectedId}
          onChange={handleChange}
          placeholderText={t('panel.start_picker_placeholder')}
          emptyText={t('panel.start_picker_empty')}
          ariaLabel={t('panel.start_picker_label')}
        />
      </div>
    </div>
  )
}

export default StartPositionPicker
