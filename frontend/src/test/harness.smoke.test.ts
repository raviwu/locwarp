import { describe, it, expect } from 'vitest'

describe('vitest harness', () => {
  it('runs a trivial assertion', () => {
    expect(1 + 1).toBe(2)
  })

  it('has jsdom globals (document) available', () => {
    expect(typeof document).toBe('object')
    expect(document.createElement('div').tagName).toBe('DIV')
  })

  it('has jest-dom matchers extended', () => {
    const el = document.createElement('span')
    el.textContent = 'hi'
    document.body.appendChild(el)
    // toBeInTheDocument comes from @testing-library/jest-dom via setup.ts
    expect(el).toBeInTheDocument()
  })
})
