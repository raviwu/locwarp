import type { WsEvent } from '../contract/wsEvents'

export interface WsRouter {
  subscribe(type: string, handler: (e: WsEvent) => void): () => void
}
