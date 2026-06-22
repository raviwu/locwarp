import React, { useState, useEffect, useRef } from 'react'
import { isSubmitEnter } from '../utils/keyboard'
import { useT } from '../i18n'

interface CategoryManagerPanelProps {
  categories: string[]
  // Live count of bookmarks per category name — drives the delete-dropdown
  // copy ("delete category + N bookmarks").
  bookmarkCounts: Record<string, number>
  // Category color resolver (stored color, falling back to name hash).
  resolveColor: (cat: string) => string
  // EN/ZH display-name mapping (translates the built-in default category).
  displayCat: (cat: string) => string
  newCategoryName: string
  onNewCategoryNameChange: (v: string) => void
  onCategoryAdd: (name: string) => void
  onCategoryDelete: (name: string) => void
  onCategoryDeleteCascade?: (name: string, bookmarkCount: number) => void
  // Optional — the edit (pencil) button is hidden when not wired.
  onCategoryEdit?: (cat: string) => void
}

/**
 * Category-manager panel, extracted from BookmarkList. Controlled via props;
 * emits the same callback shapes BookmarkList passed before. Embeds the
 * CategoryDeleteDropdown that used to live at the bottom of BookmarkList so the
 * two pieces of category-management UI travel together.
 *
 * The "Default" / "預設" built-in category never shows edit / delete controls.
 */
const CategoryManagerPanel: React.FC<CategoryManagerPanelProps> = ({
  categories,
  bookmarkCounts,
  resolveColor,
  displayCat,
  newCategoryName,
  onNewCategoryNameChange,
  onCategoryAdd,
  onCategoryDelete,
  onCategoryDeleteCascade,
  onCategoryEdit,
}) => {
  const t = useT()
  return (
    <div
      style={{
        background: '#2a2a2e',
        border: '1px solid #444',
        borderRadius: 6,
        padding: 12,
        marginBottom: 8,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6, opacity: 0.7 }}>
        {t('bm.manage_categories')}
      </div>
      {categories.map((cat) => (
        <div
          key={cat}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 0',
            fontSize: 12,
            position: 'relative',
          }}
        >
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: '50%',
              background: resolveColor(cat),
              border: '1.5px solid rgba(255,255,255,0.15)',
              flexShrink: 0,
              boxShadow: '0 1px 2px rgba(0,0,0,0.3)',
            }}
          />
          <span style={{ flex: 1 }}>{displayCat(cat)}</span>
          {cat !== 'Default' && cat !== '預設' && onCategoryEdit && (
            <button
              onClick={() => onCategoryEdit(cat)}
              title={t('bm.cat.edit_title')}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--fg-muted, #888)',
                cursor: 'pointer',
                padding: '2px 4px',
                fontSize: 11,
              }}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
            </button>
          )}
          {cat !== 'Default' && cat !== '預設' && (
            <CategoryDeleteDropdown
              category={cat}
              bookmarkCount={bookmarkCounts[cat] ?? 0}
              onSoftDelete={() => onCategoryDelete(cat)}
              onCascadeDelete={
                onCategoryDeleteCascade
                  ? () => onCategoryDeleteCascade(cat, bookmarkCounts[cat] ?? 0)
                  : undefined
              }
            />
          )}
        </div>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input
          type="text"
          className="search-input"
          placeholder={t('bm.add_category')}
          value={newCategoryName}
          onChange={(e) => onNewCategoryNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (isSubmitEnter(e) && newCategoryName.trim()) {
              onCategoryAdd(newCategoryName.trim())
              onNewCategoryNameChange('')
            }
          }}
          style={{ flex: 1 }}
        />
        <button
          className="action-btn"
          onClick={() => {
            if (newCategoryName.trim()) {
              onCategoryAdd(newCategoryName.trim())
              onNewCategoryNameChange('')
            }
          }}
          style={{ fontSize: 11 }}
        >
          {t('bm.new_category')}
        </button>
      </div>
    </div>
  )
}

interface DropdownProps {
  category: string
  bookmarkCount: number
  onSoftDelete: () => void
  onCascadeDelete?: () => void
}

const CategoryDeleteDropdown: React.FC<DropdownProps> = ({
  category, bookmarkCount, onSoftDelete, onCascadeDelete,
}) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onOutside)
    return () => document.removeEventListener('pointerdown', onOutside)
  }, [open])

  const confirmCascade = () => {
    if (!onCascadeDelete) return
    const msg = t('bm.delete.cascade_body').replace('{n}', String(bookmarkCount))
    if (window.confirm(`${t('bm.delete.cascade_title').replace('{name}', category)}\n\n${msg}`)) {
      onCascadeDelete()
    }
  }

  const confirmSoft = () => {
    const msg = t('bm.delete.soft_body').replace('{n}', String(bookmarkCount))
    if (window.confirm(`${t('bm.delete.soft_title').replace('{name}', category)}\n\n${msg}`)) {
      onSoftDelete()
    }
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none', border: 'none',
          color: '#f44336', cursor: 'pointer',
          padding: '2px 4px', fontSize: 11,
        }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="3,6 5,6 21,6" />
          <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
        </svg>
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%', right: 0, zIndex: 50,
            background: '#2a2a2e',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 6,
            padding: '4px 0',
            minWidth: 240,
            boxShadow: '0 6px 18px rgba(0,0,0,0.5)',
          }}
        >
          <div
            onClick={() => { setOpen(false); confirmSoft() }}
            style={{ padding: '6px 12px', fontSize: 11, cursor: 'pointer' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
          >
            {t('bm.delete.softdelete_label')}
          </div>
          {onCascadeDelete && (
            <div
              onClick={() => { setOpen(false); confirmCascade() }}
              style={{
                padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                color: '#ff6b6b',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              {t('bm.delete.cascade_label').replace('{n}', String(bookmarkCount))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default CategoryManagerPanel
