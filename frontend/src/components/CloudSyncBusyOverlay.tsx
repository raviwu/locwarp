import React from 'react'
import { useT } from '../i18n'
import { useCloudSyncBusy } from '../contexts/CloudSyncBusyContext'

/**
 * Modal-style overlay shown while a cloud-sync toggle is mid-flight.
 *
 * Blocks all underlying interaction so the user cannot try to edit
 * bookmarks while ``migrate_pair`` is rewriting the underlying file.
 */
export function CloudSyncBusyOverlay() {
  const t = useT()
  const { busy, tookTooLong, cancel } = useCloudSyncBusy()
  if (!busy) return null

  const backdrop: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'rgba(8, 10, 16, 0.62)',
    zIndex: 'var(--z-overlay-blocking)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    backdropFilter: 'blur(4px)',
    WebkitBackdropFilter: 'blur(4px)',
  }
  const card: React.CSSProperties = {
    background: 'rgba(18, 22, 30, 0.96)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 14,
    padding: '24px 28px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 12,
    minWidth: 260,
    maxWidth: 360,
    boxShadow: '0 16px 48px rgba(0,0,0,0.45)',
  }
  const title: React.CSSProperties = {
    fontSize: 15,
    fontWeight: 600,
    color: '#e8eaf0',
    textAlign: 'center',
  }
  const hint: React.CSSProperties = {
    fontSize: 12,
    color: 'rgba(255,255,255,0.6)',
    textAlign: 'center',
    lineHeight: 1.55,
    margin: 0,
  }
  const spinner: React.CSSProperties = {
    width: 28,
    height: 28,
    borderRadius: '50%',
    border: '3px solid rgba(255,255,255,0.14)',
    borderTopColor: 'var(--accent-blue)',
    animation: 'locwarp-cloud-sync-spin 0.9s linear infinite',
  }
  const cancelBtn: React.CSSProperties = {
    marginTop: 4,
    padding: '6px 16px',
    fontSize: 12,
    fontWeight: 600,
    color: '#e8eaf0',
    background: 'rgba(255,255,255,0.08)',
    border: '1px solid rgba(255,255,255,0.16)',
    borderRadius: 8,
    cursor: 'pointer',
  }

  return (
    <div role="alert" aria-live="assertive" style={backdrop}>
      <style>
        {`@keyframes locwarp-cloud-sync-spin {
          to { transform: rotate(360deg); }
        }`}
      </style>
      <div style={card}>
        <div style={spinner} aria-hidden />
        <div style={title}>{t('cloud_sync.busy_title')}</div>
        <p style={hint}>{t('cloud_sync.busy_hint')}</p>
        {tookTooLong && (
          <>
            <p style={hint}>{t('cloud_sync.busy_taking_longer')}</p>
            <button type="button" style={cancelBtn} onClick={cancel}>
              {t('cloud_sync.busy_cancel')}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
