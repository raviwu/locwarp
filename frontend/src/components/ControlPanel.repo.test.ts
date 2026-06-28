// frontend/src/components/ControlPanel.repo.test.ts
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { REPO_SLUG } from '../contract/repo'

const src = readFileSync(
  resolve(__dirname, 'ControlPanel.tsx'),
  'utf-8',
)

describe('ControlPanel About link', () => {
  it('uses the shared REPO_SLUG, not a hardcoded keezxc1223 slug', () => {
    // The in-app footer ("LocWarp by …") ships inside the macOS DMG, so it
    // must point home to the raviwu fork via the shared constant.
    expect(src).toContain('REPO_SLUG')
    expect(src).not.toContain('keezxc1223')
  })

  it('the shared slug is the raviwu fork', () => {
    expect(REPO_SLUG).toBe('raviwu/locwarp')
  })
})
