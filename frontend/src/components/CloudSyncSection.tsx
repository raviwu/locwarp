import React, { useEffect, useState } from 'react'
import { useT } from '../i18n'
import {
  cloudSyncStatus,
  cloudSyncEnable,
  cloudSyncDisable,
  type CloudSyncStatus,
} from '../services/api'
import { useCloudSyncBusy } from '../contexts/CloudSyncBusyContext'

export function CloudSyncSection() {
  const t = useT()
  const [status, setStatus] = useState<CloudSyncStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { busy, run } = useCloudSyncBusy()

  const refresh = async () => {
    try {
      setStatus(await cloudSyncStatus())
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const onToggle = async () => {
    if (!status) return
    setError(null)
    try {
      const next = await run((signal) =>
        status.enabled ? cloudSyncDisable(signal) : cloudSyncEnable(undefined, signal),
      )
      setStatus(next)
    } catch (e) {
      setError(String(e))
      // Re-fetch backend truth so the checkbox reflects actual state after
      // an abort (35s timeout or Cancel) rather than showing the stale
      // pre-toggle value until the modal is closed and remounted.
      void refresh()
    }
  }

  if (!status) return null

  const canEnable = status.detected_icloud_path !== null

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 0',
    fontSize: 13,
    color: '#e8eaf0',
    cursor: 'pointer',
    userSelect: 'none',
  }

  const detailStyle: React.CSSProperties = {
    fontSize: 12,
    color: 'rgba(255,255,255,0.55)',
    margin: '4px 0 0 22px',
    lineHeight: 1.5,
  }

  const errorStyle: React.CSSProperties = {
    fontSize: 12,
    color: '#ff6b6b',
    margin: '4px 0 0 22px',
  }

  const sectionHeaderStyle: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 600,
    color: 'rgba(255,255,255,0.4)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    padding: '12px 0 4px',
    borderTop: '1px solid rgba(255,255,255,0.06)',
    marginTop: 8,
  }

  return (
    <div>
      <div style={sectionHeaderStyle}>
        ☁️ {t('cloud_sync.section_title')}
      </div>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={status.enabled}
          onChange={onToggle}
          disabled={busy || (!status.enabled && !canEnable)}
          style={{ cursor: 'pointer', margin: 0 }}
        />
        <span>
          {status.enabled
            ? t('cloud_sync.toggle_enabled')
            : status.detected_icloud_path
              ? t('cloud_sync.toggle_enable_icloud')
              : t('cloud_sync.toggle_enable_custom')}
        </span>
      </label>

      {status.enabled && status.sync_folder && (
        <p style={detailStyle}>
          {t('cloud_sync.detail_path', { path: status.sync_folder })}
          <br />
          {t('cloud_sync.detail_counts', {
            bookmarks: status.bookmarks.count,
            bookmark_categories: status.bookmarks.category_count,
            routes: status.routes.count,
            route_categories: status.routes.category_count,
          })}
        </p>
      )}

      {!status.enabled && status.detected_icloud_path && (
        <p style={detailStyle}>
          {t('cloud_sync.detected_path', { path: status.detected_icloud_path })}
        </p>
      )}

      {!status.enabled && !status.detected_icloud_path && (
        <p style={detailStyle}>
          {t('cloud_sync.no_icloud_hint')}
        </p>
      )}

      {error && <p style={errorStyle}>{error}</p>}
    </div>
  )
}
