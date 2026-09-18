// Runs before every test file (vitest.config.ts setupFiles).
// Pulls in the jest-dom matchers (toBeInTheDocument, etc.) and
// auto-cleans the DOM between tests.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Node >= 26 ships a built-in global `localStorage` accessor that resolves to
// `undefined` unless the process is started with --localstorage-file. Because
// the global NAME already exists (non-enumerable, on the object vitest's jsdom
// environment uses as both `globalThis` and `window`), jsdom's own storage is
// never installed, and every test touching localStorage throws
// "Cannot read properties of undefined". Install a spec-shaped in-memory
// Storage so the suite does not depend on the host node version at all.
class MemoryStorage implements Storage {
  private map = new Map<string, string>()

  get length(): number {
    return this.map.size
  }

  key(index: number): string | null {
    return Array.from(this.map.keys())[index] ?? null
  }

  getItem(key: string): string | null {
    // Spec: a missing key is null, and keys/values are always strings.
    return this.map.has(String(key)) ? this.map.get(String(key))! : null
  }

  setItem(key: string, value: string): void {
    this.map.set(String(key), String(value))
  }

  removeItem(key: string): void {
    this.map.delete(String(key))
  }

  clear(): void {
    this.map.clear()
  }
}

for (const key of ['localStorage', 'sessionStorage'] as const) {
  if (typeof globalThis[key] === 'undefined') {
    Object.defineProperty(globalThis, key, {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    })
  }
}

afterEach(() => {
  cleanup()
})
