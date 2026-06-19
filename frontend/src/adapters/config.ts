// The ONLY origin source for the renderer. Every base URL / WS URL in the app
// MUST derive from these — do not hardcode 127.0.0.1:8777 anywhere else.
export const ORIGIN_HOST = '127.0.0.1'
export const ORIGIN_PORT = 8777

export const HTTP_ORIGIN = `http://${ORIGIN_HOST}:${ORIGIN_PORT}`
export const WS_ORIGIN = `ws://${ORIGIN_HOST}:${ORIGIN_PORT}`
