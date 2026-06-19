import { describe, it, expect } from 'vitest'
import { isImeComposing, isSubmitEnter } from './keyboard'
import type { KeyboardEvent } from 'react'

// Minimal duck-typed React KeyboardEvent. The util only reads
// e.nativeEvent.isComposing, e.keyCode, and e.key.
function ke(opts: { key?: string; keyCode?: number; isComposing?: boolean }) {
  return {
    key: opts.key ?? '',
    keyCode: opts.keyCode ?? 0,
    nativeEvent: { isComposing: opts.isComposing ?? false },
  } as unknown as KeyboardEvent
}

describe('isImeComposing', () => {
  it('true when nativeEvent.isComposing is set', () => {
    expect(isImeComposing(ke({ isComposing: true }))).toBe(true)
  })

  it('true when keyCode is the 229 IME sentinel', () => {
    expect(isImeComposing(ke({ keyCode: 229 }))).toBe(true)
  })

  it('false when neither composing signal is present', () => {
    expect(isImeComposing(ke({ key: 'a', keyCode: 65 }))).toBe(false)
  })
})

describe('isSubmitEnter', () => {
  it('true for a plain Enter with no IME composition', () => {
    expect(isSubmitEnter(ke({ key: 'Enter' }))).toBe(true)
  })

  it('false for Enter while IME is composing (isComposing)', () => {
    expect(isSubmitEnter(ke({ key: 'Enter', isComposing: true }))).toBe(false)
  })

  it('false for Enter with the 229 sentinel keyCode', () => {
    expect(isSubmitEnter(ke({ key: 'Enter', keyCode: 229 }))).toBe(false)
  })

  it('false for a non-Enter key', () => {
    expect(isSubmitEnter(ke({ key: 'a' }))).toBe(false)
  })
})
