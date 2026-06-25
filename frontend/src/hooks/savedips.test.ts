import { describe, it, expect, beforeEach } from 'vitest'
import { readSavedipEntry } from './savedips'

describe('readSavedipEntry', () => {
  beforeEach(() => { localStorage.clear() })

  it('returns null when no savedips are stored', () => {
    expect(readSavedipEntry('u1')).toBeNull()
  })

  it('returns the entry matching the udid', () => {
    localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify([
      { ip: '10.0.0.2', port: 49152, udid: 'u2', lastUsed: 200 },
      { ip: '10.0.0.1', port: 49153, udid: 'u1', lastUsed: 100 },
    ]))
    expect(readSavedipEntry('u1')).toEqual({ ip: '10.0.0.1', port: 49153, udid: 'u1' })
  })

  it('falls back to the first (most recent) entry when udid is null', () => {
    localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify([
      { ip: '10.0.0.2', port: 49152, udid: 'u2', lastUsed: 200 },
      { ip: '10.0.0.1', port: 49153, udid: 'u1', lastUsed: 100 },
    ]))
    expect(readSavedipEntry(null)).toEqual({ ip: '10.0.0.2', port: 49152, udid: 'u2' })
  })

  it('falls back to the first entry when the udid does not match any', () => {
    localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify([
      { ip: '10.0.0.2', port: 49152, udid: 'u2', lastUsed: 200 },
    ]))
    expect(readSavedipEntry('nope')).toEqual({ ip: '10.0.0.2', port: 49152, udid: 'u2' })
  })

  it('returns null on corrupt JSON', () => {
    localStorage.setItem('locwarp.tunnel.savedips', '{not json')
    expect(readSavedipEntry('u1')).toBeNull()
  })
})
