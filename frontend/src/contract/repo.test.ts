import { describe, it, expect } from 'vitest'
import { REPO_SLUG, REPO_URL } from './repo'

describe('repo slug single source', () => {
  it('points the app-owned (DMG) surfaces at the raviwu fork', () => {
    // The macOS DMG is shipped from raviwu/locwarp — UpdateChecker + the
    // in-app About link must resolve here. Windows-only surfaces (README
    // .exe download) deliberately stay at keezxc1223 and do NOT use this.
    expect(REPO_SLUG).toBe('raviwu/locwarp')
  })

  it('derives the canonical repo URL from the slug (no second hardcode)', () => {
    expect(REPO_URL).toBe('https://github.com/raviwu/locwarp')
  })
})
