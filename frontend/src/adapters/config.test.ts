import { describe, it, expect } from 'vitest'
import { ORIGIN_HOST, ORIGIN_PORT, HTTP_ORIGIN, WS_ORIGIN } from './config'

describe('config single origin', () => {
  it('exposes the canonical host and port', () => {
    expect(ORIGIN_HOST).toBe('127.0.0.1')
    expect(ORIGIN_PORT).toBe(8777)
  })

  it('derives http and ws origins from host+port (no second hardcode)', () => {
    expect(HTTP_ORIGIN).toBe('http://127.0.0.1:8777')
    expect(WS_ORIGIN).toBe('ws://127.0.0.1:8777')
  })
})
