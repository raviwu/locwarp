import { useEffect, useRef, useState } from 'react'
import type { WsRouter } from '../ports/WsRouter'
import type { WsEvent } from '../contract/wsEvents'

// Tracks the latest coarse connect phase streamed by the backend
// (connect_progress WS event). Rendered in the DeviceStatus spinner region
// so a slow connect is distinguishable from a hang. Single global value —
// there is one connecting device at a time in the spinner region. The
// 'connected' phase is terminal and clears the indicator immediately. A
// safety timeout backstop also clears the phase when no further
// connect_progress arrives within STALE_MS — this covers every failure mode
// (RSD exhaustion, DDI failure, tunnel failure) that emits no terminal event,
// so a stale "RSD attempt 5/10" label can never persist indefinitely.
const STALE_MS = 20_000

export function useConnectProgress(ws?: WsRouter): { connectPhase: string | null } {
  const [connectPhase, setConnectPhase] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const armTimer = () => {
    clearTimer()
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      setConnectPhase(null)
    }, STALE_MS)
  }

  useEffect(() => {
    if (!ws) return
    const off = ws.subscribe('connect_progress', (e: WsEvent) => {
      const phase = e.phase as string | undefined
      if (!phase) return
      if (phase === 'connected') {
        clearTimer()
        setConnectPhase(null)
        return
      }
      setConnectPhase(phase)
      armTimer()
    })
    return () => {
      off()
      clearTimer()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws])

  return { connectPhase }
}
