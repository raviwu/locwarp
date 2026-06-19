import { useEffect, useMemo } from 'react'
import { useWebSocket } from '../../hooks/useWebSocket'
import { createWsRouter } from './router'
import type { WsEvent } from '../../contract/wsEvents'

// Bridges the existing useWebSocket subscribe-fanout onto a typed WsRouter.
// Flattens the wire frame {type, data} into a flat WsEvent {type, ...data} so
// typed subscribers see one object keyed by `type`. Reuses useWebSocket's proven
// reconnect/backoff/JSON-guard; this hook adds the typed routing layer only.
//
// Synchronous guarantee: router.dispatch is called directly inside the
// useWebSocket subscriber callback — no setState, no effect deferral.
// This preserves the same "no React-batching drops" property as the existing
// subscriber fan-out (see useWebSocket.ts comment about React 18 auto-batching).
export function useWsRouter() {
  const { subscribe, sendMessage, connected } = useWebSocket()
  // Stable ref: useMemo with empty deps creates the router once per mount.
  // Subscriptions registered via router.subscribe() survive re-renders because
  // the router object identity never changes.
  const router = useMemo(() => createWsRouter(), [])

  useEffect(() => {
    // subscribe() has a stable identity (empty-deps useCallback in useWebSocket)
    // so this effect fires once and the unsubscribe cleanup runs on unmount only.
    // No duplicate subscriptions on re-render; no leak.
    return subscribe((msg) => {
      // Flatten {type, data} -> {type, ...data} synchronously.
      // dispatch() runs synchronously — no setState, no scheduling deferral —
      // matching the guarantees of the original useWebSocket fan-out.
      const flat: WsEvent = { type: msg.type, ...(msg.data ?? {}) }
      router.dispatch(flat)
    })
  }, [subscribe, router])

  return { router, sendMessage, connected }
}
