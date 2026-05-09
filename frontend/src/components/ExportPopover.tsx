import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useT } from '../i18n'
import { bookmarksExportUrl, BookmarkExportFormat } from '../services/api'

interface Category { id: string; name: string }

interface Props {
  open: boolean
  anchorRect: DOMRect | null
  categories: Category[]
  onClose: () => void
}

export const ExportPopover: React.FC<Props> = ({ open, anchorRect, categories, onClose }) => {
  const t = useT()
  const [scope, setScope] = useState<'all' | 'one'>('all')
  const [categoryId, setCategoryId] = useState<string>(categories[0]?.id ?? 'default')
  const [format, setFormat] = useState<BookmarkExportFormat>('json')
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
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

  if (!open || !anchorRect) return null

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 280)
  const left = Math.min(anchorRect.left, window.innerWidth - 280)

  const url = bookmarksExportUrl({
    category_id: scope === 'one' ? categoryId : null,
    format,
  })

  return createPortal(
    <div
      ref={ref}
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'fixed', top, left, width: 260,
        background: '#1e1e22',
        border: '1px solid rgba(108,140,255,0.3)',
        borderRadius: 8,
        padding: 12,
        boxShadow: '0 12px 28px rgba(0,0,0,0.5)',
        zIndex: 9999,
        color: '#e0e0e0', fontSize: 12,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}
    >
      <div style={{ fontWeight: 600 }}>{t('bm.export.title')}</div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} />
        {t('bm.export.scope_all')}
      </label>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <input type="radio" checked={scope === 'one'} onChange={() => setScope('one')} />
        {t('bm.export.scope_one')}
      </label>
      {scope === 'one' && (
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          style={{
            background: '#1e1e22', color: '#e0e0e0',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4, padding: '4px 6px',
          }}
        >
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      )}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', margin: '4px 0' }} />
      <div style={{ fontSize: 11, opacity: 0.7 }}>{t('bm.export.format_label')}</div>
      {(['json', 'markdown', 'geojson', 'csv'] as BookmarkExportFormat[]).map((f) => (
        <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="radio" checked={format === f} onChange={() => setFormat(f)} />
          {t(`bm.export.format_${f}` as any)}
        </label>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
        <button className="action-btn" onClick={onClose} style={{ flex: 1 }}>
          {t('generic.cancel')}
        </button>
        <a
          className="action-btn primary"
          href={url}
          download
          onClick={() => onClose()}
          style={{ flex: 1, textAlign: 'center' }}
        >
          {t('bm.export.download')}
        </a>
      </div>
    </div>,
    document.body,
  )
}

export default ExportPopover
