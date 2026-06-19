import { describe, it, expect } from 'vitest'
import { BASE_URL, WS_URL } from './endpoints'
import { HTTP_ORIGIN, WS_ORIGIN } from '../adapters/config'

describe('endpoints derive from config only', () => {
  it('BASE_URL is the http origin', () => {
    expect(BASE_URL).toBe(HTTP_ORIGIN)
  })

  it('WS_URL is the ws origin + /ws/status path', () => {
    expect(WS_URL).toBe(`${WS_ORIGIN}/ws/status`)
    expect(WS_URL).toBe('ws://127.0.0.1:8777/ws/status')
  })
})
