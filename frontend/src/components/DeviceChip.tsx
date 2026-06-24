import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useT } from '../i18n'
import type { DeviceInfo } from '../hooks/useDevice'
import type { DeviceRuntime } from '../hooks/useSimulation'
import DialogShell from './DialogShell'

export const DEVICE_COLORS: Record<'A' | 'B' | 'C', string> = {
  A: '#4285f4',
  B: '#ff9800',
  C: '#9c6ade',
}

export type DeviceLetter = 'A' | 'B' | 'C'

interface Props {
  letter: DeviceLetter
  device: DeviceInfo
  runtime?: DeviceRuntime
  variant?: 'connected' | 'trust_required'
  onDisconnect: () => void
  onForget: () => void
  onRestoreOne: () => void
  onReTrust?: () => void
  onEnableDev?: () => void
}

function stateKind(state?: string): 'idle' | 'running' | 'paused' | 'error' | 'disconnected' {
  if (!state) return 'idle'
  if (state === 'paused') return 'paused'
  if (state === 'disconnected') return 'disconnected'
  if (state === 'idle') return 'idle'
  return 'running'
}

export function DeviceChip({ letter, device, runtime, variant = 'connected', onDisconnect, onForget, onRestoreOne, onReTrust, onEnableDev }: Props) {
  const t = useT()
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [confirmForget, setConfirmForget] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  const kind = stateKind(runtime?.state)

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [menu])

  const dotColor = {
    idle: '#4ecdc4',
    running: '#6c8cff',
    paused: '#ffb627',
    error: '#ff6b6b',
    disconnected: '#ff6b6b',
  }[kind]

  const label = {
    idle: t('device.chip_state_idle'),
    running: t('device.chip_state_running'),
    paused: t('device.chip_state_paused'),
    error: t('device.chip_state_error'),
    disconnected: t('device.chip_state_disconnected'),
  }[kind]

  const isTrust = variant === 'trust_required'
  const trustDot = '#ffb627'
  const accent = DEVICE_COLORS[letter]
  const shortName = (device.name || 'iPhone').slice(0, 14)

  return (
    <>
      <div
        ref={ref}
        onContextMenu={(e) => {
          e.preventDefault()
          setMenu({ x: e.clientX, y: e.clientY })
        }}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          height: 24, padding: '0 8px',
          borderRadius: 12,
          background: 'rgba(255,255,255,0.06)',
          backdropFilter: 'blur(24px) saturate(160%)',
          WebkitBackdropFilter: 'blur(24px) saturate(160%)',
          border: '1px solid rgba(108, 140, 255, 0.18)',
          fontSize: 11,
          color: 'rgba(255,255,255,0.9)',
          cursor: 'context-menu',
          maxWidth: 160,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
        title={`${letter} · ${device.name}`}
      >
        <span
          style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isTrust ? trustDot : dotColor,
            boxShadow: kind === 'running' ? `0 0 6px ${dotColor}` : 'none',
            animation: kind === 'running' ? 'chip-pulse 1.6s ease-in-out infinite' : undefined,
            flexShrink: 0,
          }}
        />
        <span style={{ fontWeight: 600, color: accent }}>{letter}</span>
        <span style={{ opacity: 0.85, overflow: 'hidden', textOverflow: 'ellipsis' }}>· {shortName}</span>
        {isTrust ? (
          <span style={{
            marginLeft: 2, padding: '0 4px',
            borderRadius: 4,
            background: '#fff3cd',
            color: '#856404',
            fontSize: 10,
          }}>{t('device.pair_chip_trust')}</span>
        ) : (
          <span style={{ opacity: 0.6, marginLeft: 2 }}>· {label}</span>
        )}
      </div>
      {menu && createPortal(
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed', left: menu.x, top: menu.y,
            background: 'rgba(20,22,28,0.96)',
            backdropFilter: 'blur(18px) saturate(160%)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 8, padding: 4, minWidth: 160,
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            zIndex: 9999, fontSize: 12, color: '#eaeaea',
          }}
        >
          {isTrust ? (
            <MenuItem onClick={() => { setMenu(null); onReTrust?.() }}>{t('device.chip_retrust')}</MenuItem>
          ) : (
            <>
              <MenuItem onClick={() => { setMenu(null); onRestoreOne() }}>{t('device.chip_restore')}</MenuItem>
              {onEnableDev && <MenuItem onClick={() => { setMenu(null); onEnableDev() }}>{t('device.chip_enable_dev')}</MenuItem>}
              <MenuItem onClick={() => { setMenu(null); onDisconnect() }}>{t('device.chip_disconnect')}</MenuItem>
            </>
          )}
          <MenuItem onClick={() => { setMenu(null); setConfirmForget(true) }}>{t('device.chip_forget')}</MenuItem>
        </div>,
        document.body,
      )}
      <DialogShell
        open={confirmForget}
        onClose={() => setConfirmForget(false)}
        labelledBy="forget-title"
        backdropStyle={{ zIndex: 10000, background: 'rgba(0,0,0,0.5)', backdropFilter: 'none', WebkitBackdropFilter: 'none' }}
        panelStyle={{
          background: 'rgba(20,22,28,0.96)',
          backdropFilter: 'blur(18px) saturate(160%)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 10, padding: 16, maxWidth: 320,
          color: '#eaeaea', fontSize: 13,
        }}
      >
        <div id="forget-title" style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
          {t('device.forget_confirm_title')}
        </div>
        <div style={{ opacity: 0.8, lineHeight: 1.5, marginBottom: 14 }}>
          {t('device.forget_confirm_body')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={() => setConfirmForget(false)}>
            {t('device.forget_cancel')}
          </button>
          <button
            type="button"
            onClick={() => { setConfirmForget(false); onForget() }}
            style={{ background: '#c0392b', color: '#fff' }}
          >
            {t('device.forget_ok')}
          </button>
        </div>
      </DialogShell>
    </>
  )
}

function MenuItem({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '6px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        background: hover ? 'rgba(108,140,255,0.18)' : 'transparent',
      }}
    >
      {children}
    </div>
  )
}
