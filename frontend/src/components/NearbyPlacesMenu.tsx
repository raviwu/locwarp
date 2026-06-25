import React, { useEffect, useRef, useState } from 'react'
import { useT } from '../i18n'
// Import the api type via the contract re-export, NOT '../services/api':
// depcruise's no-view-imports-api rule (ERROR) forbids a view-ring component
// importing services/api even with `import type` (tsPreCompilationDeps).
import type { NearbyPoi } from '../contract/apiGateway'
import { contextMenuItemStyle, highlightItem, unhighlightItem } from '../utils/contextMenuStyle'

interface NearbyPlacesMenuProps {
  lat: number
  lng: number
  // Injected gateway (caller supplies (lat,lng) => api.nearbyPois(lat,lng)) so
  // this component stays free of ServicesContext coupling + unit-testable.
  nearbyPois: (lat: number, lng: number) => Promise<NearbyPoi[]>
  onTeleport: (lat: number, lng: number) => void
  onAddBookmark: (lat: number, lng: number, suggestedName?: string) => void
  deviceConnected: boolean
  onClose: () => void
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; pois: NearbyPoi[] }
  | { kind: 'error' }

const NearbyPlacesMenu: React.FC<NearbyPlacesMenuProps> = ({
  lat, lng, nearbyPois, onTeleport, onAddBookmark, deviceConnected, onClose,
}) => {
  const t = useT()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  // Stale-guard: drop a late resolve after unmount (mirrors MapContextMenu).
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    let cancelled = false
    nearbyPois(lat, lng)
      .then((pois) => {
        if (cancelled || !mountedRef.current) return
        setState({ kind: 'ready', pois })
      })
      .catch(() => {
        if (cancelled || !mountedRef.current) return
        setState({ kind: 'error' })
      })
    return () => {
      cancelled = true
      mountedRef.current = false
    }
  }, [lat, lng, nearbyPois])

  return (
    <div
      role="menu"
      aria-label={t('map.nearby_label')}
      className="context-menu"
      style={{ minWidth: 200, maxHeight: 320, overflow: 'auto', padding: '4px 0' }}
      onClick={(e) => e.stopPropagation()}
    >
      {state.kind === 'loading' && (
        <div style={{ padding: '8px 16px', color: '#9ac0ff', fontSize: 12 }}>
          {t('map.nearby_loading')}
        </div>
      )}
      {state.kind === 'error' && (
        <div style={{ padding: '8px 16px', color: '#ff8a80', fontSize: 12 }}>
          {t('map.nearby_error')}
        </div>
      )}
      {state.kind === 'ready' && state.pois.length === 0 && (
        <div style={{ padding: '8px 16px', color: '#9499ac', fontSize: 12 }}>
          {t('map.nearby_empty')}
        </div>
      )}
      {state.kind === 'ready' && state.pois.map((poi) => (
        <div key={poi.id} style={{ display: 'flex', alignItems: 'center' }}>
          <button
            type="button"
            role="menuitem"
            className="context-menu-item"
            style={{ ...contextMenuItemStyle, flex: 1, textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }}
            onMouseEnter={highlightItem}
            onMouseLeave={unhighlightItem}
            onClick={() => {
              onAddBookmark(poi.lat, poi.lng, poi.name)
              onClose()
            }}
          >
            <span style={{ flex: 1 }}>{poi.name}</span>
            <span style={{ fontSize: 10, opacity: 0.6, marginLeft: 8 }}>
              {Math.round(poi.distance_m)}m
            </span>
          </button>
          {deviceConnected && (
            <button
              type="button"
              role="menuitem"
              aria-label={`${t('map.teleport_here')} ${poi.name}`}
              className="context-menu-item"
              style={{ ...contextMenuItemStyle, background: 'transparent', border: 'none', font: 'inherit', padding: '6px 10px' }}
              onMouseEnter={highlightItem}
              onMouseLeave={unhighlightItem}
              onClick={() => {
                onTeleport(poi.lat, poi.lng)
                onClose()
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="2" x2="12" y2="6" />
                <line x1="12" y1="18" x2="12" y2="22" />
                <line x1="2" y1="12" x2="6" y2="12" />
                <line x1="18" y1="12" x2="22" y2="12" />
              </svg>
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

export default NearbyPlacesMenu
