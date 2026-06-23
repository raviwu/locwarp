import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { spawnSync } from 'node:child_process'
import { existsSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Fail-on-probe regression for the dependency-cruiser layering gate.
 *
 * The scoped `error` rules (bookmarklist/app/mapview-no-direct-api) forbid a
 * gated view file from importing `services/api` / `adapters`. Nothing committed
 * proved depcruise actually FAILS (exit != 0) when such an import appears — a
 * silently-broken `error` severity (or a typo'd from/to glob) would let a real
 * regression sail through CI. This test plants a probe file that matches the
 * `mapview-no-direct-api` `from` prefix (^src/components/(MapView|...)), confirms
 * the cruise exits non-zero naming that rule, then removes the probe and proves
 * the tree is clean again.
 *
 * Cleanup is load-bearing: a leaked `*.tsx` under src/components would break a
 * later `tsc`/`depcruise` for everyone. Hence the beforeAll start-guard, the
 * try/finally around the probe, and the afterAll backstop — three independent
 * removals so no crash path can leave the file behind.
 */

// frontend/src/__tests__/gateFailOnProbe.test.ts → frontend/ is two dirs up.
const FRONTEND_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const PROBE_PATH = join(FRONTEND_DIR, 'src', 'components', 'MapViewGateProbe.tsx')
// Call the local binary directly — no npx network/registry round-trip, and it
// is the exact same `depcruise` the package.json script resolves.
const DEPCRUISE_BIN = join(FRONTEND_DIR, 'node_modules', '.bin', 'depcruise')

const PROBE_SOURCE =
  "import * as _api from '../services/api';\n" +
  'export default function MapViewGateProbe() { return null; }\n'

function runDepcruise(): { status: number | null; output: string } {
  const result = spawnSync(
    DEPCRUISE_BIN,
    ['src', '--config', '.dependency-cruiser.cjs'],
    { cwd: FRONTEND_DIR, encoding: 'utf8' },
  )
  if (result.error) throw result.error
  return { status: result.status, output: `${result.stdout ?? ''}${result.stderr ?? ''}` }
}

function removeProbe(): void {
  rmSync(PROBE_PATH, { force: true })
}

// Start-guard: a crashed prior run must not leave a stale probe lingering.
beforeAll(() => removeProbe())
afterAll(() => removeProbe())

describe('dependency-cruiser layering gate fails on a view → services/api probe', () => {
  it('exits non-zero naming the scoped error rule, then is clean once removed', () => {
    expect(existsSync(DEPCRUISE_BIN)).toBe(true)

    let withProbe: { status: number | null; output: string }
    try {
      writeFileSync(PROBE_PATH, PROBE_SOURCE, 'utf8')
      withProbe = runDepcruise()
    } finally {
      removeProbe()
    }

    // depcruise exits 1 when any `error`-severity rule is violated.
    expect(withProbe.status).toBe(1)
    expect(withProbe.status).not.toBe(0)
    // The scoped rule named, and the offending edge it caught.
    expect(withProbe.output).toContain('mapview-no-direct-api')
    expect(withProbe.output).toContain('src/components/MapViewGateProbe.tsx')
    expect(withProbe.output).toContain('src/services/api.ts')

    // Cleanup happened in `finally`; confirm and re-cruise the restored tree.
    expect(existsSync(PROBE_PATH)).toBe(false)
    const clean = runDepcruise()
    expect(clean.status).toBe(0)
    expect(clean.output).not.toContain('mapview-no-direct-api')
  })
})
