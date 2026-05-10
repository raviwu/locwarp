import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useT } from '../i18n'
import BookmarkPickerPopover from './BookmarkPickerPopover'
import BookmarkDropdown from './BookmarkDropdown'

interface Bookmark {
  id?: string
  name: string
  lat: number
  lng: number
  category_id?: string
}

interface Category {
  id: string
  name: string
  color?: string
  start_date?: string
  end_date?: string
}

interface Props {
  connectedUdids: string[]
  isCycling: boolean
  // mapCenter was used by the old "Use map center" B-button. After the
  // 2026-05-10 refactor B is bookmark-only; mapCenter is intentionally
  // kept on the interface to avoid churning ControlPanel and App.tsx
  // wiring (out of scope), but is no longer consumed in the body.
  mapCenter: { lat: number; lng: number } | null
  // External A-setter — pushed in by MapView right-click "設為拉金盆 A 點".
  // We wrap the coord in an object so every push creates a fresh reference;
  // the useEffect dep then re-fires even if the user picks the same coord
  // twice in a row.
  externalAValue: { coord: string } | null
  // New: bookmark sources for the picker
  bookmarks: Bookmark[]
  categories: Category[]
  onConfirmLocation: (lat: number, lng: number) => Promise<void> | void
  onCycle: (
    target: 'A' | 'B' | 'auto',
    args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
  ) => Promise<void> | void
  // New: cascade delete callback. Returning a Promise lets the panel close
  // the popover only after the API roundtrip succeeds.
  onCategoryDeleteCascade: (categoryId: string) => Promise<void> | void
}

const LS_A = 'goldditto.A'
const LS_B_LEGACY = 'goldditto.B'              // pre-2026-05-10: stored "lat, lng"
const LS_B_BOOKMARK_ID = 'goldditto.B.bookmarkId' // new: bookmark id only
const LS_WAIT = 'goldditto.wait_seconds'
const COORD_MATCH_TOLERANCE = 1e-5

function parseLatLng(s: string): { lat: number; lng: number } | null {
  const m = s.trim().match(/^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/)
  if (!m) return null
  const lat = parseFloat(m[1])
  const lng = parseFloat(m[2])
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null
  return { lat, lng }
}

export const GoldDittoPanel: React.FC<Props> = ({
  connectedUdids,
  isCycling,
  mapCenter,
  externalAValue,
  bookmarks,
  categories,
  onConfirmLocation,
  onCycle,
  onCategoryDeleteCascade,
}) => {
  const t = useT()

  const [aText, setAText] = useState(() => localStorage.getItem(LS_A) ?? '')
  const [bBookmarkId, setBBookmarkId] = useState<string | null>(
    () => localStorage.getItem(LS_B_BOOKMARK_ID),
  )
  const [waitText, setWaitText] = useState(
    () => localStorage.getItem(LS_WAIT) ?? '3.0',
  )

  const [pickerSide, setPickerSide] = useState<'A' | 'B' | null>(null)
  const [pickerAnchor, setPickerAnchor] = useState<DOMRect | null>(null)
  const aBtnRef = useRef<HTMLButtonElement | null>(null)

  const [pickerCatA, setPickerCatA] = useState<string | null>(
    () => localStorage.getItem('goldditto.picker.A.lastCategory'),
  )

  const bookmarksByCategoryId = useMemo(() => {
    const out: Record<string, Bookmark[]> = {}
    for (const bm of bookmarks) {
      const cid = bm.category_id ?? 'default'
      if (!out[cid]) out[cid] = []
      out[cid].push(bm)
    }
    return out
  }, [bookmarks])

  const categoryDatesById = useMemo(
    () => Object.fromEntries(
      categories.map(c => [c.id, {
        start_date: c.start_date ?? '',
        end_date: c.end_date ?? '',
      }]),
    ),
    [categories],
  )

  const [confirmEnd, setConfirmEnd] = useState<{ catId: string; count: number } | null>(null)

  // Persist on change.
  useEffect(() => { localStorage.setItem(LS_A, aText) }, [aText])
  useEffect(() => {
    if (bBookmarkId) localStorage.setItem(LS_B_BOOKMARK_ID, bBookmarkId)
    else localStorage.removeItem(LS_B_BOOKMARK_ID)
  }, [bBookmarkId])
  useEffect(() => { localStorage.setItem(LS_WAIT, waitText) }, [waitText])

  // One-shot migration: if no new key but legacy "lat, lng" coord exists,
  // try to match a bookmark within COORD_MATCH_TOLERANCE; otherwise drop it.
  // `bookmarks` loads async (empty array until useBookmarks resolves); the
  // guard `bookmarks.length === 0 ? return` defers the decision until at
  // least one bookmark is visible. If the user genuinely has zero bookmarks,
  // the migration sits idle (cheap no-op) until they add one or pick B.
  const migratedRef = useRef(false)
  useEffect(() => {
    if (migratedRef.current) return
    if (bBookmarkId) {
      migratedRef.current = true
      localStorage.removeItem(LS_B_LEGACY)
      return
    }
    const legacy = localStorage.getItem(LS_B_LEGACY)
    if (!legacy) {
      migratedRef.current = true
      return
    }
    if (bookmarks.length === 0) return  // wait for async bookmarks load
    const parsed = parseLatLng(legacy)
    if (parsed) {
      const matches = bookmarks.filter(
        (bm) =>
          Math.abs(bm.lat - parsed.lat) < COORD_MATCH_TOLERANCE &&
          Math.abs(bm.lng - parsed.lng) < COORD_MATCH_TOLERANCE &&
          bm.id,
      )
      if (matches.length === 1 && matches[0].id) {
        setBBookmarkId(matches[0].id)
      }
    }
    localStorage.removeItem(LS_B_LEGACY)
    migratedRef.current = true
  }, [bBookmarkId, bookmarks])

  // External A setter (map right-click).
  useEffect(() => {
    if (externalAValue) setAText(externalAValue.coord)
  }, [externalAValue])

  const a = useMemo(() => parseLatLng(aText), [aText])
  const b = useMemo(() => {
    if (!bBookmarkId) return null
    const bm = bookmarks.find((x) => x.id === bBookmarkId)
    return bm ? { lat: bm.lat, lng: bm.lng } : null
  }, [bBookmarkId, bookmarks])
  const waitSeconds = useMemo(() => {
    const v = parseFloat(waitText)
    if (Number.isNaN(v)) return null
    return Math.min(10, Math.max(0.5, v))
  }, [waitText])

  const noDevice = connectedUdids.length === 0
  const aValid = a !== null
  const bValid = b !== null
  const waitValid = waitSeconds !== null
  const sameAB = a && b && Math.abs(a.lat - b.lat) < 1e-6 && Math.abs(a.lng - b.lng) < 1e-6

  const cycleArgs = useMemo(() => {
    if (!a || !b || waitSeconds === null) return null
    return {
      lat_a: a.lat, lng_a: a.lng,
      lat_b: b.lat, lng_b: b.lng,
      wait_seconds: waitSeconds,
    }
  }, [a, b, waitSeconds])

  const disableConfirm = noDevice || !aValid || isCycling
  const disableFirstTry = noDevice || !aValid || !bValid || !waitValid || isCycling

  const handleConfirm = useCallback(async () => {
    if (!a) return
    await onConfirmLocation(a.lat, a.lng)
  }, [a, onConfirmLocation])

  const handleFirstTry = useCallback(async () => {
    if (!cycleArgs) return
    await onCycle('B', cycleArgs)
  }, [cycleArgs, onCycle])

  const openPicker = (side: 'A' | 'B', btn: HTMLButtonElement | null) => {
    if (!btn) return
    setPickerSide(side)
    setPickerAnchor(btn.getBoundingClientRect())
  }

  const handlePick = (bm: { lat: number; lng: number }) => {
    // Picker is now A-side only; B uses the inline BookmarkDropdown.
    if (pickerSide === 'A') {
      setAText(`${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`)
    }
  }

  const handleCategoryChange = (catId: string) => {
    if (pickerSide === 'A') {
      setPickerCatA(catId)
      try { localStorage.setItem('goldditto.picker.A.lastCategory', catId) } catch { /* ignore */ }
    }
  }

  const handleEndEventRequest = (catId: string, count: number) => {
    setConfirmEnd({ catId, count })
  }

  const handleEndEventConfirm = async () => {
    if (!confirmEnd) return
    await onCategoryDeleteCascade(confirmEnd.catId)
    setConfirmEnd(null)
    setPickerSide(null)
  }

  return (
    <div className="goldditto-panel" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 8 }}>
      {noDevice && (
        <div style={{ color: '#f87171', fontSize: 12 }}>{t('goldditto.error.no_device')}</div>
      )}

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.a_label')}</span>
        <div style={{ display: 'flex', gap: 4 }}>
          <input
            type="text"
            value={aText}
            onChange={(e) => setAText(e.target.value)}
            placeholder="lat, lng"
            style={{
              flex: 1,
              padding: '6px 8px',
              border: aValid || aText === '' ? '1px solid #4b5563' : '1px solid #f87171',
              borderRadius: 4,
              background: '#1f2937',
              color: '#fff',
            }}
          />
          <button
            ref={aBtnRef}
            type="button"
            className="action-btn"
            title={t('goldditto.pick_from_bookmarks_tooltip_a')}
            onClick={() => openPicker('A', aBtnRef.current)}
            style={{ padding: '6px 8px', fontSize: 12 }}
          >📚</button>
        </div>
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.b_label')}</span>
        <BookmarkDropdown
          bookmarks={bookmarks}
          categories={categories.map((c) => ({ id: c.id, name: c.name }))}
          value={bBookmarkId}
          onChange={(bm) => setBBookmarkId(bm?.id ?? null)}
          placeholderText={t('goldditto.b_picker_placeholder')}
          emptyText={t('goldditto.b_picker_empty')}
          ariaLabel={t('goldditto.b_label')}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.wait_label')} (0.5–10.0)</span>
        <input
          type="number"
          step="0.1"
          min="0.5"
          max="10"
          value={waitText}
          onChange={(e) => setWaitText(e.target.value)}
          style={{
            padding: '6px 8px',
            border: waitValid ? '1px solid #4b5563' : '1px solid #f87171',
            borderRadius: 4,
            background: '#1f2937',
            color: '#fff',
            width: 100,
          }}
        />
      </label>

      {sameAB && (
        <div style={{ color: '#fbbf24', fontSize: 12 }}>{t('goldditto.warn_same_ab')}</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
        <button
          onClick={handleConfirm}
          disabled={disableConfirm}
          className="action-btn primary"
          style={{ padding: '8px 12px', opacity: disableConfirm ? 0.5 : 1 }}
        >
          ① {t('goldditto.confirm')}
        </button>
        <button
          onClick={handleFirstTry}
          disabled={disableFirstTry}
          className="action-btn primary"
          style={{ padding: '8px 12px', opacity: disableFirstTry ? 0.5 : 1 }}
        >
          ② {t('goldditto.first_try')}
        </button>
      </div>

      <BookmarkPickerPopover
        open={pickerSide !== null}
        side={pickerSide ?? 'A'}
        anchorRect={pickerAnchor}
        categories={categories}
        bookmarksByCategoryId={bookmarksByCategoryId}
        categoryDates={categoryDatesById}
        initialCategoryId={pickerCatA}
        isCycling={isCycling}
        onClose={() => setPickerSide(null)}
        onPickCoord={handlePick}
        onCategoryChange={handleCategoryChange}
        onEndEvent={handleEndEventRequest}
      />

      {confirmEnd && createPortal(
        <div
          onClick={() => setConfirmEnd(null)}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(8,10,20,0.55)',
            backdropFilter: 'blur(4px)',
            zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'rgba(26,29,39,0.96)',
              border: '1px solid rgba(255,107,107,0.35)',
              borderRadius: 12,
              padding: 18, width: 320,
              boxShadow: '0 20px 60px rgba(12,18,40,0.65)',
              color: '#e0e0e0',
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>
              {t('bm.delete.cascade_title').replace('{name}',
                categories.find(c => c.id === confirmEnd.catId)?.name ?? '')}
            </div>
            <div style={{ fontSize: 12, marginBottom: 14 }}>
              {t('bm.delete.cascade_body').replace('{n}', String(confirmEnd.count))}
            </div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button className="action-btn" onClick={() => setConfirmEnd(null)}>
                {t('generic.cancel')}
              </button>
              <button
                className="action-btn"
                onClick={handleEndEventConfirm}
                style={{ color: '#ff6b6b', borderColor: 'rgba(255,107,107,0.4)' }}
              >
                {t('bm.delete.cascade_confirm')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}

export default GoldDittoPanel
