import { useEffect, useState } from 'react'
import type { WsRouter } from '../ports/WsRouter'
import type { WsEvent } from '../contract/wsEvents'

// Tracks the latest coarse connect phase streamed by the backend
// (connect_progress WS event). Rendered in the DeviceStatus spinner region
// so a slow connect is distinguishable from a hang. Single global value —
// there is one connecting device at a time in the spinner region. The
// 'connected' phase is terminal and clears the indicator (the device list
// refresh + connected dot take over from there).
export function useConnectProgress(ws?: WsRouter): { connectPhase: string | null } {
  const [connectPhase, setConnectPhase] = useState<string | null>(null)
  useEffect(() => {
    if (!ws) return
    const off = ws.subscribe('connect_progress', (e: WsEvent) => {
      const phase = e.phase as string | undefined
      if (!phase) return
      if (phase === 'connected') {
        setConnectPhase(null)
        return
      }
      setConnectPhase(phase)
    })
    return () => { off() }
  }, [ws])
  return { connectPhase }
}
