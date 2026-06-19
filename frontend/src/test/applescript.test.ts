import { describe, it, expect } from 'vitest'
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { escapeAppleScriptString } = require('../../electron/applescript.js')

describe('escapeAppleScriptString', () => {
  it('escapes a double quote so it cannot terminate the AppleScript string', () => {
    const evil = '/Apps/Loc"; do shell script "rm -rf ~" ; "Warp'
    const out = escapeAppleScriptString(evil)
    // The raw, unescaped " that would close the AppleScript literal is gone:
    // every " in the output is preceded by a backslash.
    for (let i = 0; i < out.length; i++) {
      if (out[i] === '"') {
        expect(out[i - 1]).toBe('\\')
      }
    }
  })

  it('escapes backslashes first so escaping is not double-applied wrong', () => {
    expect(escapeAppleScriptString('a\\b')).toBe('a\\\\b')
    expect(escapeAppleScriptString('a"b')).toBe('a\\"b')
    expect(escapeAppleScriptString('a\\"b')).toBe('a\\\\\\"b')
  })

  it('leaves a benign path untouched', () => {
    expect(escapeAppleScriptString('/Applications/LocWarp.app/Contents')).toBe(
      '/Applications/LocWarp.app/Contents',
    )
  })
})
