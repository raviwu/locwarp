import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { useT } from '../i18n'

interface Props {
  connectedUdids: string[]
  isCycling: boolean
  mapCenter: { lat: number; lng: number } | null
  // External A-setter — pushed in by MapView right-click "設為拉金盆 A 點".
  // We wrap the coord in an object so every push creates a fresh reference;
  // the useEffect dep then re-fires even if the user picks the same coord
  // twice in a row.
  externalAValue: { coord: string } | null
  onConfirmLocation: (lat: number, lng: number) => Promise<void> | void
  onCycle: (
    target: 'A' | 'B' | 'auto',
    args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
  ) => Promise<void> | void
}

const DEFAULT_B = '25.034897, 121.545827'
const LS_A = 'goldditto.A'
const LS_B = 'goldditto.B'
const LS_WAIT = 'goldditto.wait_seconds'

// Taiwan main-island bounding box (24.0–25.5°N, 120.5–122.0°E).
function randomTaiwanCoord(): string {
  const lat = 24.0 + Math.random() * 1.5
  const lng = 120.5 + Math.random() * 1.5
  return `${lat.toFixed(6)}, ${lng.toFixed(6)}`
}

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
  onConfirmLocation,
  onCycle,
}) => {
  const t = useT()

  const [aText, setAText] = useState(() => localStorage.getItem(LS_A) ?? '')
  const [bText, setBText] = useState(() => localStorage.getItem(LS_B) ?? DEFAULT_B)
  const [waitText, setWaitText] = useState(
    () => localStorage.getItem(LS_WAIT) ?? '3.0',
  )

  // Persist on change.
  useEffect(() => { localStorage.setItem(LS_A, aText) }, [aText])
  useEffect(() => { localStorage.setItem(LS_B, bText) }, [bText])
  useEffect(() => { localStorage.setItem(LS_WAIT, waitText) }, [waitText])

  // External A setter (map right-click).
  useEffect(() => {
    if (externalAValue) setAText(externalAValue.coord)
  }, [externalAValue])

  const a = useMemo(() => parseLatLng(aText), [aText])
  const b = useMemo(() => parseLatLng(bText), [bText])
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
  const disableRetries = disableFirstTry

  const handleConfirm = useCallback(async () => {
    if (!a) return
    await onConfirmLocation(a.lat, a.lng)
  }, [a, onConfirmLocation])

  const handleFirstTry = useCallback(async () => {
    if (!cycleArgs) return
    await onCycle('B', cycleArgs)
  }, [cycleArgs, onCycle])

  const handleRetries = useCallback(async () => {
    if (!cycleArgs) return
    await onCycle('auto', cycleArgs)
  }, [cycleArgs, onCycle])

  const handleRandomB = () => setBText(randomTaiwanCoord())
  const handleUseMapCenter = () => {
    if (mapCenter) setBText(`${mapCenter.lat.toFixed(6)}, ${mapCenter.lng.toFixed(6)}`)
  }

  return (
    <div className="goldditto-panel" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 8 }}>
      {noDevice && (
        <div style={{ color: '#f87171', fontSize: 12 }}>{t('goldditto.error.no_device')}</div>
      )}

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.a_label')}</span>
        <input
          type="text"
          value={aText}
          onChange={(e) => setAText(e.target.value)}
          placeholder="lat, lng"
          style={{
            padding: '6px 8px',
            border: aValid || aText === '' ? '1px solid #4b5563' : '1px solid #f87171',
            borderRadius: 4,
            background: '#1f2937',
            color: '#fff',
          }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.b_label')}</span>
        <input
          type="text"
          value={bText}
          onChange={(e) => setBText(e.target.value)}
          placeholder="lat, lng"
          style={{
            padding: '6px 8px',
            border: bValid ? '1px solid #4b5563' : '1px solid #f87171',
            borderRadius: 4,
            background: '#1f2937',
            color: '#fff',
          }}
        />
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={handleRandomB} className="action-btn" style={{ fontSize: 12, flex: 1 }}>
            {t('goldditto.random_b')}
          </button>
          <button onClick={handleUseMapCenter} className="action-btn" style={{ fontSize: 12, flex: 1 }}
                  disabled={!mapCenter}>
            {t('goldditto.use_map_center')}
          </button>
        </div>
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
        <button
          onClick={handleRetries}
          disabled={disableRetries}
          className="action-btn primary"
          style={{ padding: '8px 12px', opacity: disableRetries ? 0.5 : 1 }}
        >
          ③ {t('goldditto.retries')}
        </button>
      </div>
    </div>
  )
}

export default GoldDittoPanel
