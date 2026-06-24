import type { WsEvent, WsEventType } from '../contract/wsEvents'

export interface WsRouter {
  subscribe(type: WsEventType, handler: (e: WsEvent) => void): () => void
}
