/**
 * Task 10b — Characterization: api.startLoop sends timestamps in the request
 * body when provided, and omits the key when timestamps are absent/empty.
 *
 * Two pinned contracts:
 * 1. startLoop WITH timestamps → POST body contains timestamps array.
 * 2. startLoop WITHOUT timestamps (undefined) → POST body has no timestamps key.
 * 3. startLoop WITH empty timestamps ([]) → POST body has no timestamps key
 *    (guard: don't send a useless empty array to the backend).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { startLoop } from './api'

function makeFetchStub(status = 200, body: unknown = { status: 'started' }) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as any
}

function parsedBody(fetchMock: ReturnType<typeof makeFetchStub>): Record<string, unknown> {
  const call = fetchMock.mock.calls[0]
  const init = call[1] as RequestInit
  return JSON.parse(init.body as string)
}

const WPS = [
  { lat: 25.0, lng: 121.0 },
  { lat: 25.001, lng: 121.001 },
  { lat: 25.002, lng: 121.002 },
]

describe('api.startLoop — timestamps threading', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetchStub())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('includes timestamps in request body when a non-empty array is provided', async () => {
    const ts = [0.0, 4.5, 9.0]
    await startLoop(WPS, 'walking', undefined, undefined, undefined, undefined, undefined, undefined, undefined, ts)

    const body = parsedBody(globalThis.fetch as any)
    expect(body).toHaveProperty('timestamps')
    expect(body.timestamps).toEqual(ts)
  })

  it('omits timestamps key from request body when timestamps is undefined', async () => {
    // No timestamps argument → the body must NOT contain a timestamps key
    await startLoop(WPS, 'walking')

    const body = parsedBody(globalThis.fetch as any)
    expect(body).not.toHaveProperty('timestamps')
  })

  it('omits timestamps key from request body when timestamps is an empty array', async () => {
    // Empty array → treat the same as absent (no timed replay to activate)
    await startLoop(WPS, 'walking', undefined, undefined, undefined, undefined, undefined, undefined, undefined, [])

    const body = parsedBody(globalThis.fetch as any)
    expect(body).not.toHaveProperty('timestamps')
  })

  it('posts to /api/location/loop', async () => {
    const ts = [0.0, 5.0]
    await startLoop(WPS, 'walking', undefined, undefined, undefined, undefined, undefined, undefined, undefined, ts)

    const url = (globalThis.fetch as any).mock.calls[0][0] as string
    expect(url).toContain('/api/location/loop')
  })
})
