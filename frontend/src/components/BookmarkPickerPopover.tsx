import React, { useState, useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useT } from '../i18n'
import { getCategoryStatus, todayLocal } from '../utils/categoryStatus'

interface Bookmark {
  id?: string
  name: string
  lat: number
  lng: number
  category_id?: string
  // Tolerate either the new `category_id` from backend or the legacy
  // `category` (name) field used elsewhere in the UI; the popover only
  // renders bookmarks already filtered by the parent.
  category?: string
}

interface Category {
  id: string
  name: string
  color?: string
}

interface Props {
  open: boolean
  side: 'A' | 'B'
  anchorRect: DOMRect | null  // anchor button bounding rect from getBoundingClientRect
  categories: Category[]
  bookmarksByCategoryId: Record<string, Bookmark[]>
  initialCategoryId: string | null  // last-used per side
  isCycling: boolean  // disables End-event button
  onClose: () => void
  onPickCoord: (bm: Bookmark) => void
  onCategoryChange: (catId: string) => void  // parent persists last-used per side
  onEndEvent?: (catId: string, bookmarkCount: number) => void  // omit for B side if you want
  // Per-category event dates, keyed by category id (the picker has
  // ids handy already; BookmarkList uses by-name because of legacy).
  categoryDates?: Record<string, { start_date: string; end_date: string }>
}

const POPOVER_WIDTH = 280
const POPOVER_MAX_HEIGHT = 360

export const BookmarkPickerPopover: React.FC<Props> = ({
  open, side, anchorRect, categories, bookmarksByCategoryId,
  initialCategoryId, isCycling, onClose, onPickCoord, onCategoryChange, onEndEvent,
  categoryDates,
}) => {
  const t = useT()
  const includeEndedKey = `goldditto.picker.${side}.includeEnded`
  const [includeEnded, setIncludeEnded] = useState<boolean>(
    () => (typeof window !== 'undefined' ? localStorage.getItem(includeEndedKey) === 'true' : false),
  )

  const visibleCategories = useMemo(() => {
    const today = todayLocal()
    return categories.filter((c) => {
      const d = categoryDates?.[c.id]
      if (!d) return true
      if (includeEnded) return true
      return getCategoryStatus(d.start_date, d.end_date, today) !== 'ended'
    })
  }, [categories, categoryDates, includeEnded])

  // Default to first visible category (or 'default') when no last-used category
  // is saved — spec §9 requires the picker to open with something selected so
  // the user immediately sees content rather than a disabled '—' placeholder.
  const fallbackCatId = visibleCategories[0]?.id ?? categories[0]?.id ?? 'default'
  const [selectedCatId, setSelectedCatId] = useState<string | null>(
    initialCategoryId ?? fallbackCatId,
  )

  useEffect(() => {
    const stillVisible = visibleCategories.some((c) => c.id === initialCategoryId)
    setSelectedCatId(
      initialCategoryId && stillVisible
        ? initialCategoryId
        : (visibleCategories[0]?.id ?? fallbackCatId),
    )
  }, [initialCategoryId, open, visibleCategories, fallbackCatId])

  // Dismiss on outside click / ESC
  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      const target = e.target as Element | null
      if (target && target.closest?.('[data-bookmark-picker-popover]')) return
      onClose()
    }
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const id = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside)
      document.addEventListener('keydown', onEsc)
    }, 0)
    return () => {
      clearTimeout(id)
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open, onClose])

  const visible = useMemo(() => {
    if (!selectedCatId) return [] as Bookmark[]
    return bookmarksByCategoryId[selectedCatId] ?? []
  }, [selectedCatId, bookmarksByCategoryId])

  if (!open || !anchorRect) return null

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - POPOVER_MAX_HEIGHT - 8)
  const left = Math.min(anchorRect.left, window.innerWidth - POPOVER_WIDTH - 8)

  return createPortal(
    <div
      data-bookmark-picker-popover
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'fixed', top, left,
        width: POPOVER_WIDTH, maxHeight: POPOVER_MAX_HEIGHT,
        background: '#1e1e22',
        border: '1px solid rgba(108, 140, 255, 0.3)',
        borderRadius: 8,
        boxShadow: '0 12px 28px rgba(0,0,0,0.5)',
        padding: 10,
        display: 'flex', flexDirection: 'column', gap: 8,
        zIndex: 9999,
        color: '#e0e0e0', fontSize: 12,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600 }}>
        {side === 'A' ? t('bm.picker.title_a') : t('bm.picker.title_b')}
      </div>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 11, opacity: 0.7 }}>
        <input
          type="checkbox"
          checked={includeEnded}
          onChange={(e) => {
            setIncludeEnded(e.target.checked)
            try {
              localStorage.setItem(includeEndedKey, String(e.target.checked))
            } catch { /* ignore quota */ }
          }}
        />
        {t('bm.picker.include_ended')}
      </label>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ opacity: 0.7 }}>{t('bm.picker.category_label')}</span>
        <select
          value={selectedCatId ?? ''}
          onChange={(e) => {
            const v = e.target.value || null
            setSelectedCatId(v)
            if (v) onCategoryChange(v)
          }}
          style={{
            background: '#1e1e22', color: '#e0e0e0',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4, padding: '4px 6px',
          }}
        >
          <option value="" disabled>—</option>
          {visibleCategories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </label>

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 80, paddingRight: 2 }}>
        {visible.length === 0 ? (
          <div style={{ opacity: 0.5, padding: '12px 0', textAlign: 'center' }}>
            {t('bm.picker.empty')}
          </div>
        ) : (
          visible.map((bm) => (
            <div
              key={bm.id ?? `${bm.lat}-${bm.lng}`}
              onClick={() => { onPickCoord(bm); onClose() }}
              style={{
                padding: '6px 4px',
                borderBottom: '1px solid rgba(255,255,255,0.06)',
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#2a2a2e' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              <div>{bm.name}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10, opacity: 0.55 }}>
                {bm.lat.toFixed(6)}, {bm.lng.toFixed(6)}
              </div>
            </div>
          ))
        )}
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        <button className="action-btn" onClick={onClose} style={{ flex: 1, fontSize: 11 }}>
          {t('bm.picker.close')}
        </button>
        {onEndEvent && selectedCatId && selectedCatId !== 'default' && (
          <button
            className="action-btn"
            disabled={isCycling}
            title={isCycling ? t('bm.picker.end_event_disabled_cycling') : undefined}
            onClick={() => {
              if (selectedCatId) onEndEvent(selectedCatId, visible.length)
            }}
            style={{
              flex: 1, fontSize: 11,
              color: '#ff6b6b',
              borderColor: 'rgba(255,107,107,0.4)',
              opacity: isCycling ? 0.5 : 1,
            }}
          >
            {t('bm.picker.end_event')}
          </button>
        )}
      </div>
    </div>,
    document.body,
  )
}

export default BookmarkPickerPopover
