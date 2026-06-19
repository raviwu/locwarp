import type { WsEvent } from '../../contract/wsEvents'
import type { WsRouter } from '../../ports/WsRouter'

type Handler = (e: WsEvent) => void

// Concrete WsRouter: a Map<type, Set<handler>>. dispatch() fans a single event
// out to EVERY handler registered for e.type, in insertion order, each wrapped
// in its own try/catch so one throwing subscriber cannot starve the others or
// kill the stream. This preserves the multi-subscriber fan-out semantics of the
// old useWebSocket subscribersRef Set — it is NOT a single-owner dispatcher.
export interface WsRouterImpl extends WsRouter {
  dispatch(e: WsEvent): void
}

export function createWsRouter(): WsRouterImpl {
  const buckets = new Map<string, Set<Handler>>()

  function subscribe(type: string, handler: Handler): () => void {
    let set = buckets.get(type)
    if (!set) {
      set = new Set<Handler>()
      buckets.set(type, set)
    }
    set.add(handler)
    return () => {
      const s = buckets.get(type)
      if (!s) return
      s.delete(handler)
      if (s.size === 0) buckets.delete(type)
    }
  }

  function dispatch(e: WsEvent): void {
    const set = buckets.get(e.type)
    if (!set) return
    // Snapshot so a handler that (un)subscribes during dispatch can't mutate the
    // set we're iterating.
    for (const handler of [...set]) {
      try {
        handler(e)
      } catch {
        // A subscriber's error must not kill the stream or block other handlers.
      }
    }
  }

  return { subscribe, dispatch }
}
