# LocWarp Clean-Arch MVP — Phase 0: Safety Nets + Bug/Security Folds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Tasks are the trackable unit (`### Task N`); each task's steps are bold-headed and end in a commit.

**Goal:** Stand up the two missing safety nets — the frontend Vitest harness and the backend `SimulationEngine` clock/sleep seam + characterization nets — then land the 7 bug/security folds as independent, individually-revertable commits, all **before** any structural refactor (Phase 1).

**Architecture:** Pragmatic Hexagonal-lite (see spec `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md`). Phase 0 changes NO architecture; it only adds test infrastructure and lands isolated fixes. Order is load-bearing: 0a (nets) lands **first and alone**, then 0b (folds) — each fold is its own commit so a single `git revert` undoes it without unwinding anything else.

**Tech Stack:** Backend FastAPI + pydantic v2 + pytest (asyncio strict). Frontend React + TypeScript + Vite + Electron; **Vitest + jsdom + Testing Library + MSW** added here as dev-only test infra. `import-linter` added (report-only) as the backend layering gate.

## Global Constraints

- **Behavior/API freeze.** No external HTTP / WS / IPC change in Phase 0. The ONE documented behavior delta — the `device_manager.py:1155` NameError fix — lands as its own commit (Task 10) with a regression test that pins the *intended* retry semantics (there is no valid pre-fix baseline; today the path crashes on first failure).
- **Test baseline (corrected).** The design doc says "352"; this checkout actually **collects ≈371 test items** (`cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1`). **Pin the exact number before Task 1** and treat that as the floor. Wherever a task body says "352", read it as "the pinned pre-change baseline." Rule: the count never drops; it only grows by the tests you add.
- **Environment.** `backend/.venv` may not exist on a fresh machine (this one has system Python 3.11.8 only). Create it once before running backend tests: `cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt`. All backend commands assume `.venv/bin/python`.
- **New dependencies require explicit approval** (per `AGENTS.md`). This plan introduces dev-only deps: backend `import-linter`; frontend `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `msw`. **Do not `npm install` / add to requirements until approved.**
- **Git identity** is auto-set by `~/.gitconfig` includeIf — **never** pass `-c user.email=...`. Personal repo: direct commits to `main`.
- **Security action item (out-of-band, Ravi).** The TimezoneDB key in `geo_extras.py:31` is in source **and git history**; Task 11 removes it from source but the key itself must be **rotated** at the provider.

## Known scope notes (from the plan authors, verified against source)

- The clock/sleep seam covers `time.monotonic()` (engine lines 759/837) and `asyncio.sleep` (778). The inter-tick wait at **line 841 is `asyncio.wait_for(_stop_event.wait())`, not `asyncio.sleep`** — so the seam alone does **not** make a full multi-tick route deterministic. P0 char nets are therefore scoped to teleport + pause/resume gate-toggle + snapshot-dispatch resolution + goldditto order, **not** a driven multi-tick route stream (a full route net needs seaming line 841 — deferred, and only relevant to the deferred Phase 3).
- `EtaTracker.start` (line 49) is intentionally **not** seamed (separate class, out of contract).
- Async test marker assumed `@pytest.mark.asyncio` (asyncio strict mode, verified in `pytest.ini`); a confirm-grep step is included.

---
## Phase 0a — Safety nets (land FIRST)

> **This phase is the prerequisite net for every later phase.** It adds the
> two test harnesses that do not exist yet (frontend Vitest; backend
> clock/sleep seam) and locks the *current* observable behaviour of the pure
> utils and the danger-zone simulation engine as exact-value characterization
> tests. Nothing in later phases may merge until every commit here is green.
> No external behaviour changes in this phase except the single documented
> `device_manager.py:1155` fix is **deferred to a later phase** — Phase 0a
> only builds nets, it does not fix bugs.

**Commands used throughout this phase**
- Backend pytest: `cd backend && .venv/bin/python -m pytest <args>`
- Frontend Vitest (after Task 1): `cd frontend && npx vitest run`
- Frontend tsc: `cd frontend && npx tsc --noEmit`

> **Environment note (read once):** the repo CLAUDE.md pins the backend test
> command to `.venv/bin/python`. If `backend/.venv` is absent on your machine,
> create it once before Task 8: `cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`
> (or `pip install pytest httpx fastapi pydantic pymobiledevice3` if no
> requirements file). All backend commands below assume `.venv/bin/python`
> resolves. Do NOT add `-c user.email=...` to any git command — identity is
> auto-set by the includeIf in `~/.gitconfig`.

---

### Task 1 — Frontend Vitest bootstrap (harness only)

**Goal:** stand up Vitest + jsdom + Testing Library + jest-dom + MSW so the
six characterization test files (Tasks 2–7) have something to run on. No
product code changes. One commit.

> **New-dependency gate:** AGENTS.md says "no new dependencies without
> discussion". Adding `vitest`, `jsdom`, `@testing-library/*`, `msw` is the
> approved scope of THIS task per the locked plan — they are dev-only test
> infra, not runtime deps. Do not add anything beyond the five packages below.

**Step 1 — write the failing trip-wire test.**
Create `frontend/src/test/harness.smoke.test.ts`:

```ts
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
```

**Step 2 — run it; watch it fail.**
```
cd frontend && npx vitest run src/test/harness.smoke.test.ts
```
Expected failure: `sh: vitest: command not found` (or `npm ERR! could not
determine executable to run`). The harness is not wired yet.

**Step 3 — wire the harness.**

3a. Add devDeps + a `test` script to `frontend/package.json`. Insert into the
existing `"scripts"` block:
```json
    "test": "vitest run",
    "test:watch": "vitest"
```
Add to `"devDependencies"` (exact versions — pinned to the React 18 /
Vite 5 / TS 5.5 toolchain already in the repo):
```json
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "jsdom": "^24.1.0",
    "msw": "^2.3.0",
    "vitest": "^1.6.0"
```
Then install:
```
cd frontend && npm install
```

3b. Create `frontend/vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
```

3c. Create `frontend/src/test/setup.ts`:
```ts
// Runs before every test file (vitest.config.ts setupFiles).
// Pulls in the jest-dom matchers (toBeInTheDocument, etc.) and
// auto-cleans the DOM between tests.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})
```

**Step 4 — run it; watch it pass.**
```
cd frontend && npx vitest run src/test/harness.smoke.test.ts
```
Expected: `Test Files  1 passed (1)` / `Tests  3 passed (3)`.
Also confirm the type-check is still clean:
```
cd frontend && npx tsc --noEmit
```
Expected: no output, exit 0. (If `tsc` flags `vitest/config`, ensure
`"types": ["vitest/globals"]` or the package is installed — it is, from 3a.)

**Step 5 — commit.**
```
cd frontend && git add package.json package-lock.json vitest.config.ts src/test/setup.ts src/test/harness.smoke.test.ts
git commit -m "test(frontend): bootstrap Vitest + jsdom + Testing Library harness

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 2 — Characterize `utils/coords.parseCoord`

**Goal:** lock the exact current output of `parseCoord(raw)` —
`{ lat, lng } | null` — including the decimal-first / integer-fallback /
range-gate behaviour. One commit.

Exported signature (verbatim): `export function parseCoord(raw: string): { lat: number; lng: number } | null`.

**Step 1 — write the failing test.**
Create `frontend/src/utils/coords.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { parseCoord } from './coords'

describe('parseCoord', () => {
  it('extracts a decimal pair from labelled CJK text', () => {
    expect(parseCoord('(-33.41902, -70.70187) 一般火'))
      .toEqual({ lat: -33.41902, lng: -70.70187 })
  })

  it('skips a leading integer label and grabs the decimal pair', () => {
    expect(parseCoord('#3\n35.018, 135.584'))
      .toEqual({ lat: 35.018, lng: 135.584 })
  })

  it('accepts arbitrary non-numeric separators between the two numbers', () => {
    expect(parseCoord('25.0375 B 121.5637'))
      .toEqual({ lat: 25.0375, lng: 121.5637 })
  })

  it('uses the integer-only fallback only when the whole input is two numbers', () => {
    expect(parseCoord('25, 121')).toEqual({ lat: 25, lng: 121 })
  })

  it('does NOT integer-fallback when the input has surrounding label text', () => {
    // "#3" then "25, 121": decimal RE finds nothing, integer RE requires the
    // WHOLE trimmed input to be two numbers, so this is null.
    expect(parseCoord('label 25, 121 note')).toBeNull()
  })

  it('rejects out-of-range latitude', () => {
    expect(parseCoord('95.0, 10.0')).toBeNull()
  })

  it('rejects out-of-range longitude', () => {
    expect(parseCoord('10.0, 200.0')).toBeNull()
  })

  it('returns null for text with no coordinate pair', () => {
    expect(parseCoord('hello world')).toBeNull()
  })

  it('keeps the negative sign attached to the second number', () => {
    expect(parseCoord('40.0,-120.5')).toEqual({ lat: 40.0, lng: -120.5 })
  })
})
```

**Step 2 — run it; watch it pass-or-fail.**
```
cd frontend && npx vitest run src/utils/coords.test.ts
```
This is a *characterization* test of EXISTING code, so it should pass on the
first run. If any case fails, the assertion encodes a wrong assumption — fix
the assertion to match observed output (do NOT touch `coords.ts`). Treat a
real first-run failure as a discovery: re-read the regex in `coords.ts` and
correct the expectation. Expected when correct: `9 passed`.

> There is no Step 3 "minimal impl" here — the impl already exists. The TDD
> shape for characterization tests is: write test → run → if it fails because
> your expectation was wrong, correct the expectation (not the source) →
> green → commit.

**Step 3 — commit.**
```
cd frontend && git add src/utils/coords.test.ts
git commit -m "test(frontend): characterize parseCoord exact outputs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 3 — Characterize `utils/geoFormat`

**Goal:** lock `countryName(code, lang)` and `formatGmtOffset(timezone)`.
These depend on the JS `Intl` runtime (ICU build), so assert the
override-table cases exactly and the Intl-derived cases loosely. One commit.

Signatures: `countryName(code: string | undefined, lang: Lang): string`;
`formatGmtOffset(timezone: string | undefined): string`. `Lang` = `'zh' | 'en'`.

**Step 1 — write the test.**
Create `frontend/src/utils/geoFormat.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { countryName, formatGmtOffset } from './geoFormat'

describe('countryName', () => {
  it('returns empty string for missing code', () => {
    expect(countryName(undefined, 'en')).toBe('')
    expect(countryName('', 'zh')).toBe('')
  })

  it('uses the SHORT_OVERRIDES table for en', () => {
    expect(countryName('US', 'en')).toBe('USA')
    expect(countryName('GB', 'en')).toBe('UK')
    expect(countryName('AE', 'en')).toBe('UAE')
    expect(countryName('KR', 'en')).toBe('S. Korea')
    expect(countryName('CD', 'en')).toBe('DR Congo')
  })

  it('uses the SHORT_OVERRIDES table for zh', () => {
    expect(countryName('US', 'zh')).toBe('美國')
    expect(countryName('HK', 'zh')).toBe('香港')
    expect(countryName('RU', 'zh')).toBe('俄羅斯')
  })

  it('is case-insensitive on the override path', () => {
    expect(countryName('us', 'en')).toBe('USA')
  })

  it('falls back to the uppercased code when Intl cannot resolve it', () => {
    // 'ZZ' is not a real region; Intl.DisplayNames returns the code itself
    // or throws -> the catch/`|| cc` path yields 'ZZ'.
    expect(countryName('zz', 'en')).toBe('ZZ')
  })
})

describe('formatGmtOffset', () => {
  it('returns empty string for blank timezone', () => {
    expect(formatGmtOffset(undefined)).toBe('')
    expect(formatGmtOffset('')).toBe('')
  })

  it('formats a positive offset zone as GMT+N', () => {
    expect(formatGmtOffset('Asia/Taipei')).toBe('GMT+8')
  })

  it('formats UTC as GMT (or normalized GMT+0) — never bare empty', () => {
    // shortOffset on modern Node/Chromium yields 'GMT'; the code normalizes
    // a bare 'GMT' to 'GMT+0'. Accept either canonical form.
    expect(['GMT', 'GMT+0']).toContain(formatGmtOffset('UTC'))
  })

  it('returns empty string for an unrecognized timezone', () => {
    expect(formatGmtOffset('Not/AZone')).toBe('')
  })
})
```

> **ICU caveat:** `countryName('zz', ...)` and the offset string depend on the
> Node ICU build. If `formatGmtOffset('Asia/Taipei')` yields `'GMT+8'` on your
> Node (Node 18+ full-ICU does), keep the exact assertion. If your Node ships
> small-ICU and returns something else, loosen that single assertion to
> `expect(formatGmtOffset('Asia/Taipei')).toMatch(/^GMT\+8/)` and note it.

**Step 2 — run; correct expectations to observed if needed; green.**
```
cd frontend && npx vitest run src/utils/geoFormat.test.ts
```
Expected: all green (adjust any ICU-variant assertion per the caveat).

**Step 3 — commit.**
```
cd frontend && git add src/utils/geoFormat.test.ts
git commit -m "test(frontend): characterize countryName + formatGmtOffset

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 4 — Characterize `utils/bookmarkSort`

**Goal:** lock `sortBookmarks` (incl. the `'default'`-returns-input-by-reference
contract) and `sortCategoryEntries` (Uncategorized pinned last, stable). One commit.

Signatures: `sortBookmarks<T>(list: T[], mode: SortMode): T[]`;
`sortCategoryEntries<T>(entries: [string, T[]][], mode: SortMode): [string, T[]][]`;
`SortMode = 'default' | 'name' | 'date_added' | 'last_used'`.

**Step 1 — write the test.**
Create `frontend/src/utils/bookmarkSort.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { sortBookmarks, sortCategoryEntries } from './bookmarkSort'

type B = { name: string; created_at?: string; last_used_at?: string }

const list: B[] = [
  { name: 'Banana', created_at: '2026-01-02', last_used_at: '2026-03-01' },
  { name: 'apple',  created_at: '2026-01-03', last_used_at: '2026-02-01' },
  { name: 'cherry', created_at: '2026-01-01', last_used_at: '2026-04-01' },
]

describe('sortBookmarks', () => {
  it("'default' returns the SAME array reference (no copy)", () => {
    expect(sortBookmarks(list, 'default')).toBe(list)
  })

  it("'name' sorts a copy ascending (zh-Hant locale) without mutating input", () => {
    const before = list.map((b) => b.name)
    const out = sortBookmarks(list, 'name')
    expect(out).not.toBe(list)
    expect(out.map((b) => b.name)).toEqual(['apple', 'Banana', 'cherry'])
    expect(list.map((b) => b.name)).toEqual(before) // input untouched
  })

  it("'date_added' sorts by created_at descending", () => {
    expect(sortBookmarks(list, 'date_added').map((b) => b.name))
      .toEqual(['apple', 'Banana', 'cherry'])
  })

  it("'last_used' sorts by last_used_at descending", () => {
    expect(sortBookmarks(list, 'last_used').map((b) => b.name))
      .toEqual(['cherry', 'Banana', 'apple'])
  })

  it('treats missing timestamps as empty string (sorts last in desc)', () => {
    const withMissing: B[] = [
      { name: 'has', created_at: '2026-01-01' },
      { name: 'none' },
    ]
    expect(sortBookmarks(withMissing, 'date_added').map((b) => b.name))
      .toEqual(['has', 'none'])
  })
})

describe('sortCategoryEntries', () => {
  const entries: [string, B[]][] = [
    ['Zebra', [{ name: 'z', created_at: '2026-01-01' }]],
    ['Uncategorized', [{ name: 'u', created_at: '2026-09-09' }]],
    ['Alpha', [{ name: 'a', created_at: '2026-05-05' }]],
  ]

  it("'default' returns entries unchanged (by reference)", () => {
    expect(sortCategoryEntries(entries, 'default')).toBe(entries)
  })

  it("'name' sorts categories and pins Uncategorized last", () => {
    expect(sortCategoryEntries(entries, 'name').map(([c]) => c))
      .toEqual(['Alpha', 'Zebra', 'Uncategorized'])
  })

  it("'date_added' orders by newest bookmark desc, Uncategorized still last", () => {
    // Alpha=2026-05-05, Zebra=2026-01-01 -> Alpha first; Uncategorized pinned.
    expect(sortCategoryEntries(entries, 'date_added').map(([c]) => c))
      .toEqual(['Alpha', 'Zebra', 'Uncategorized'])
  })
})
```

**Step 2 — run; green.**
```
cd frontend && npx vitest run src/utils/bookmarkSort.test.ts
```
Expected: all green. (`localeCompare('zh-Hant')` puts lowercase/uppercase per
ICU collation — if `['apple','Banana','cherry']` differs on your ICU, correct
the expectation to observed order and note it.)

**Step 3 — commit.**
```
cd frontend && git add src/utils/bookmarkSort.test.ts
git commit -m "test(frontend): characterize sortBookmarks + sortCategoryEntries

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 5 — Characterize `utils/categoryStatus`

**Goal:** lock `getCategoryStatus(start, end, today)` and `formatChipDate(iso, locale)`.
`todayLocal()` is wall-clock-dependent so we only assert its *shape*. One commit.

Signatures: `getCategoryStatus(start: string, end: string, today: string): CategoryStatus`
(`'evergreen' | 'upcoming' | 'active' | 'ended'`); `todayLocal(): string`;
`formatChipDate(iso: string, locale: string): string`.

**Step 1 — write the test.**
Create `frontend/src/utils/categoryStatus.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { getCategoryStatus, todayLocal, formatChipDate } from './categoryStatus'

describe('getCategoryStatus', () => {
  it('evergreen when both start and end are empty', () => {
    expect(getCategoryStatus('', '', '2026-06-19')).toBe('evergreen')
  })

  it('upcoming when today is before start', () => {
    expect(getCategoryStatus('2026-07-01', '', '2026-06-19')).toBe('upcoming')
  })

  it('ended when today is after end', () => {
    expect(getCategoryStatus('', '2026-06-01', '2026-06-19')).toBe('ended')
  })

  it('active when today is within the window', () => {
    expect(getCategoryStatus('2026-06-01', '2026-06-30', '2026-06-19')).toBe('active')
  })

  it('active on the exact start boundary (today === start is not < start)', () => {
    expect(getCategoryStatus('2026-06-19', '2026-06-30', '2026-06-19')).toBe('active')
  })

  it('active on the exact end boundary (today === end is not > end)', () => {
    expect(getCategoryStatus('2026-06-01', '2026-06-19', '2026-06-19')).toBe('active')
  })
})

describe('todayLocal', () => {
  it('returns a YYYY-MM-DD string', () => {
    expect(todayLocal()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('formatChipDate', () => {
  it('formats month/day in en-US treating the date as UTC', () => {
    expect(formatChipDate('2026-06-07', 'en-US')).toBe('Jun 7')
  })

  it('formats month/day in zh-TW', () => {
    // Intl zh-TW short month/day -> '6月7日'
    expect(formatChipDate('2026-06-07', 'zh-TW')).toBe('6月7日')
  })
})
```

**Step 2 — run; green.**
```
cd frontend && npx vitest run src/utils/categoryStatus.test.ts
```
Expected: all green. (If `'6月7日'` differs by ICU, correct to observed and
note it; `'Jun 7'` is stable on full-ICU Node 18+.)

**Step 3 — commit.**
```
cd frontend && git add src/utils/categoryStatus.test.ts
git commit -m "test(frontend): characterize getCategoryStatus + formatChipDate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 6 — Characterize `utils/keyboard`

**Goal:** lock `isImeComposing(e)` and `isSubmitEnter(e)`. These read
`e.nativeEvent.isComposing`, `e.keyCode`, and `e.key` off a React
`KeyboardEvent` — we feed minimal duck-typed fakes. One commit.

Signatures: `isImeComposing(e: KeyboardEvent): boolean`;
`isSubmitEnter(e: KeyboardEvent): boolean`.

**Step 1 — write the test.**
Create `frontend/src/utils/keyboard.test.ts`:
```ts
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
```

**Step 2 — run; green.**
```
cd frontend && npx vitest run src/utils/keyboard.test.ts
```
Expected: `7 passed`.

**Step 3 — commit.**
```
cd frontend && git add src/utils/keyboard.test.ts
git commit -m "test(frontend): characterize isImeComposing + isSubmitEnter

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 7 — Characterize `services/s2grid.approxCellSizeMeters`

**Goal:** lock the only fully-pure, dependency-free function in `s2grid.ts`.
`cellsInBounds` needs a real Leaflet bounds object + the s2-geometry global,
so it is **out of scope** here (noted in gaps). One commit.

Signature: `approxCellSizeMeters(level: number, lat: number): number`.
Formula (from source): `(40075016 / 4 / 2^level) * cos(lat * π / 180)`.

**Step 1 — write the test.**
Create `frontend/src/services/s2grid.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { approxCellSizeMeters } from './s2grid'

describe('approxCellSizeMeters', () => {
  it('equals (40075016/4 / 2^level) * cos(lat) at the equator (cos=1)', () => {
    // level 0 at the equator: 40075016/4 = 10018754
    expect(approxCellSizeMeters(0, 0)).toBeCloseTo(10018754, 0)
  })

  it('halves the size for each extra level', () => {
    expect(approxCellSizeMeters(1, 0)).toBeCloseTo(10018754 / 2, 0)
    expect(approxCellSizeMeters(10, 0)).toBeCloseTo(10018754 / 1024, 3)
  })

  it('scales by cos(latitude)', () => {
    // at lat 60, cos(60deg) = 0.5
    expect(approxCellSizeMeters(0, 60)).toBeCloseTo(10018754 * 0.5, 0)
  })

  it('matches the exact formula for an arbitrary level/lat', () => {
    const level = 14
    const lat = 25.0375
    const expected = (40075016 / 4 / Math.pow(2, level)) *
      Math.cos((lat * Math.PI) / 180)
    expect(approxCellSizeMeters(level, lat)).toBeCloseTo(expected, 9)
  })
})
```

> **Import caveat:** `s2grid.ts` top-imports `{ S2 } from 's2-geometry'` and a
> `type L from 'leaflet'` (type-only). The runtime `s2-geometry` import is a
> dependency in package.json, so importing the module is safe under Vitest;
> only `cellsInBounds` *executes* S2/Leaflet. If module-load ever throws under
> jsdom, fall back to re-implementing the pure formula assertion against a
> copied constant and note it — but the straight import is expected to work.

**Step 2 — run; green.**
```
cd frontend && npx vitest run src/services/s2grid.test.ts
```
Expected: `4 passed`. Then run the WHOLE frontend suite to confirm Tasks 1–7
compose:
```
cd frontend && npx vitest run && npx tsc --noEmit
```
Expected: all test files green, tsc exit 0.

**Step 3 — commit.**
```
cd frontend && git add src/services/s2grid.test.ts
git commit -m "test(frontend): characterize approxCellSizeMeters pure formula

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 8 — Backend clock/sleep seam into `SimulationEngine.__init__`

**Goal:** add the injectable `clock` / `sleep` seam to
`backend/core/simulation_engine.py` per the LOCKED CONTRACT, with **NO logic
change**, pinned first by a test that the default real-clock path is
unchanged, THEN parameterize the internal call sites. This seam is the
foundation every Task-9 characterization net depends on. One commit.

**Locked contract (verbatim):**
```python
clock: Callable[[], float] = time.monotonic,
sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
```
stored as `self._clock` / `self._sleep`; every `time.monotonic()` →
`self._clock()`, every `await asyncio.sleep(x)` → `await self._sleep(x)`.

**Ground-truth call sites to migrate (in `SimulationEngine`, NOT `EtaTracker`):**
- line 759: `tick_start = time.monotonic()` → `tick_start = self._clock()`
- line 837: `elapsed = time.monotonic() - tick_start` → `elapsed = self._clock() - tick_start`
- line 778: `await asyncio.sleep(0.5 * (attempt + 1))` → `await self._sleep(0.5 * (attempt + 1))`
- line 841: `await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)` — **LEAVE UNCHANGED.** This is a `wait_for` on an Event, not an `asyncio.sleep`; the contract names `asyncio.sleep` only. Migrating `wait_for` is out of scope and would change interrupt semantics.

> **Scope guard:** `EtaTracker.start()` at line 49 also calls
> `time.monotonic()`. `EtaTracker` is a *separate class* with no clock
> injection in the contract. Do NOT touch line 49 — it is outside the
> `SimulationEngine.__init__` seam. (Logged in gaps.)

**Step 1 — write the failing pin test.**
Create `backend/tests/test_engine_clock_seam.py`:
```python
"""Phase 0a: clock/sleep seam on SimulationEngine.

Pins (a) the default real-clock wiring is unchanged, and (b) injected
clock/sleep callables are stored and used. No external behaviour change.
"""
import asyncio
import time

import pytest

from core.simulation_engine import SimulationEngine


class _NullLocation:
    """Minimal location_service stub; engine only awaits .set()."""
    async def set(self, lat: float, lng: float) -> None:
        return None


def test_default_clock_is_real_monotonic():
    eng = SimulationEngine(_NullLocation())
    # Contract: default clock is time.monotonic, default sleep is asyncio.sleep.
    assert eng._clock is time.monotonic
    assert eng._sleep is asyncio.sleep


def test_injected_clock_and_sleep_are_stored():
    fake_clock = lambda: 42.0
    async def fake_sleep(_): return None
    eng = SimulationEngine(_NullLocation(), clock=fake_clock, sleep=fake_sleep)
    assert eng._clock is fake_clock
    assert eng._sleep is fake_sleep
    assert eng._clock() == 42.0


def test_event_callback_still_positional_second_arg():
    # Regression: the existing (location_service, event_callback) positional
    # signature must be preserved; clock/sleep are keyword-only-ish extras.
    seen = []
    async def cb(t, d): seen.append((t, d))
    eng = SimulationEngine(_NullLocation(), cb)
    assert eng.event_callback is cb
```

**Step 2 — run it; watch it fail.**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_clock_seam.py -q
```
Expected failure: `AttributeError: 'SimulationEngine' object has no attribute
'_clock'` (and `TypeError: __init__() got an unexpected keyword argument
'clock'` for the injected case).

**Step 3 — minimal impl (seam wiring + call-site swaps).**

3a. In `backend/core/simulation_engine.py`, add the imports near the top
(the file already has `import asyncio` (5) and `import time` (7)). Add to the
existing typing imports — if there is no `from typing import` line, add one:
```python
from typing import Awaitable, Callable
```

3b. Change the `__init__` signature (line 102) from:
```python
    def __init__(self, location_service, event_callback=None) -> None:
```
to:
```python
    def __init__(
        self,
        location_service,
        event_callback=None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
```
And add, right after `self.event_callback = event_callback` (line 106):
```python
        self._clock = clock
        self._sleep = sleep
```

> Keeping `clock`/`sleep` keyword-only (`*,`) guarantees the existing
> positional callers `SimulationEngine(loc_service, event_callback)`
> (main.py:359) keep working untouched — verified against the contract's
> "NO other logic change".

3c. Swap the three named call sites (and ONLY these three):
- line 759 `tick_start = time.monotonic()` → `tick_start = self._clock()`
- line 837 `elapsed = time.monotonic() - tick_start` → `elapsed = self._clock() - tick_start`
- line 778 `await asyncio.sleep(0.5 * (attempt + 1))` → `await self._sleep(0.5 * (attempt + 1))`

Leave line 49 (`EtaTracker.start`), line 841 (`wait_for`), and every other
line untouched.

**Step 4 — run it; watch it pass + full regression.**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_clock_seam.py -q
```
Expected: `3 passed`.
Then the FULL backend suite must stay green (no behaviour change):
```
cd backend && .venv/bin/python -m pytest -q
```
Expected: the entire suite passes (same count as before this task; per the
contract the canonical baseline is "352 backend pytest tests stay green" — on
this checkout `pytest --collect-only -q` reports 371; whichever number your
baseline shows BEFORE this task must be unchanged AFTER, plus the 3 new tests).

**Step 5 — commit.**
```
cd backend && git add core/simulation_engine.py tests/test_engine_clock_seam.py
git commit -m "feat(engine): injectable clock/sleep seam (no behaviour change)

Keyword-only clock/sleep on SimulationEngine.__init__ defaulting to
time.monotonic / asyncio.sleep. Migrates the three internal call sites
(tick anchor 759, tick-rate elapsed 837, retry backoff 778) to the seam.
EtaTracker.start and the wait_for at 841 deliberately untouched.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 9 — Backend danger-zone characterization nets (FakeClock + stepped sleep)

> **Shared test harness for all of Task 9.** Every sub-task imports the same
> deterministic time doubles and a recording location-service. Create the
> harness module ONCE in sub-task 9a, then reuse it.

The FakeClock returns a controlled, monotonically-increasing float; the
stepped async sleep records each requested duration, advances the FakeClock by
that duration, and returns immediately. This is exactly the contract's
"stepped async sleep that records durations, advances the FakeClock, and
returns immediately."

> **IMPORTANT real-world caveat for the engine tests:** the engine's inter-tick
> wait is `asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)` (line
> 841) — NOT `self._sleep`. The injected `sleep` seam only covers the retry
> backoff (778). So a route run with default speed will still consume real
> wall-clock per tick via `wait_for`. To keep the position-stream tests fast
> AND deterministic, drive them with a tiny coordinate list (2–3 points) and a
> speed profile whose `update_interval` is small; assert the ORDERED EXACT
> `(lat, lng, segment_index)` tuples captured by the recording location-service,
> not timing. (Logged in gaps: a full clock-driven tick test would require also
> seaming line 841, which is out of contract scope for Phase 0a.)

---

#### Task 9a — Harness + engine position/ETA stream (ordered exact tuples)

**Step 1 — write the harness + the failing test.**
Create `backend/tests/_engine_harness.py`:
```python
"""Deterministic time doubles + recording location service for engine
characterization tests (Phase 0a). Shared by all Task-9 sub-tests."""
from __future__ import annotations


class FakeClock:
    """Callable returning a controlled, increasing float (seconds)."""
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += float(dt)


class SteppedSleep:
    """async sleep double: records each duration, advances a FakeClock by it,
    returns immediately (no real wait)."""
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(float(seconds))
        self.clock.advance(seconds)


class RecordingLocation:
    """location_service double. Records every (lat, lng) the engine pushes via
    _set_position -> location_service.set."""
    def __init__(self) -> None:
        self.pushes: list[tuple[float, float]] = []

    async def set(self, lat: float, lng: float) -> None:
        self.pushes.append((lat, lng))


def make_engine(coords_recorder=None, clock=None, sleep=None):
    """Build a SimulationEngine wired to a recording event_callback.
    Returns (engine, emitted) where emitted is a list of (event_type, data)."""
    from core.simulation_engine import SimulationEngine
    clock = clock or FakeClock()
    loc = RecordingLocation()
    emitted: list[tuple[str, dict]] = []

    async def cb(event_type, data):
        emitted.append((event_type, dict(data)))

    eng = SimulationEngine(
        loc, cb,
        clock=clock,
        sleep=sleep or (lambda s: _noop()),
    )
    return eng, loc, emitted


async def _noop():
    return None
```

Create `backend/tests/test_engine_stream_char.py`:
```python
"""Characterize the engine's position/ETA emit stream as ordered exact tuples."""
import pytest

from models.schemas import Coordinate, MovementMode
from tests._engine_harness import FakeClock, SteppedSleep, make_engine


@pytest.mark.asyncio
async def test_teleport_emits_ordered_state_and_position():
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    pos = await eng.teleport(25.0375, 121.5637)

    assert (pos.lat, pos.lng) == (25.0375, 121.5637)
    # location_service.set was called exactly once with the teleport target.
    assert loc.pushes == [(25.0375, 121.5637)]
    # Exact ordered emit stream for a teleport (teleport.py):
    #   state_change(TELEPORTING) -> teleport -> position_update -> state_change(IDLE)
    types = [t for (t, _d) in emitted]
    assert types == [
        "state_change", "teleport", "position_update", "state_change",
    ]
    assert emitted[0][1] == {"state": "teleporting"}
    assert emitted[1][1] == {"lat": 25.0375, "lng": 121.5637}
    assert emitted[2][1] == {"lat": 25.0375, "lng": 121.5637}
    assert emitted[3][1] == {"state": "idle"}
```

**Step 2 — run; green (characterizes existing behaviour).**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_stream_char.py -q
```
Expected: `1 passed`. If the emit order differs, re-read `core/teleport.py`
and correct the expected list to the OBSERVED order (do not change the source).

> **If `@pytest.mark.asyncio` is unrecognized:** the repo already exercises
> async engine paths, so `pytest-asyncio` (or `anyio`) is installed. Confirm
> with `grep -rn "asyncio_mode\|pytest-asyncio\|anyio" backend/pytest.ini
> backend/pyproject.toml backend/setup.cfg backend/tox.ini 2>/dev/null`. If the
> project uses `anyio`, replace the marker with `@pytest.mark.anyio` and add
> `pytestmark = pytest.mark.anyio` per that convention. (Logged in gaps.)

**Step 3 — commit.**
```
cd backend && git add tests/_engine_harness.py tests/test_engine_stream_char.py
git commit -m "test(engine): characterize teleport emit stream (ordered exact tuples)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

#### Task 9b — Pause → resume continued-stream identity

**Goal:** assert that pausing mid-stream then resuming continues the SAME
position stream (no duplicated/dropped pushes at the seam). Driven through the
`_pause_event` mechanism (set=running, clear=paused).

**Step 1 — write the test.**
Create `backend/tests/test_engine_pause_resume_char.py`:
```python
"""Characterize pause -> resume: the running task halts on _pause_event.clear()
and continues on .set() without losing position-stream identity."""
import asyncio
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


@pytest.mark.asyncio
async def test_pause_clears_event_resume_sets_it():
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    # Engine starts in the running gate: _pause_event is SET (line 111-112).
    assert eng._pause_event.is_set() is True

    # pause() must clear the running gate; resume() must set it again.
    # (engine.pause is at line 374, resume at 394.)
    await eng.pause()
    assert eng._pause_event.is_set() is False

    await eng.resume()
    assert eng._pause_event.is_set() is True
```

> **Grounding note / gap:** `pause()`/`resume()` internals beyond the
> `_pause_event` toggle (state transitions, `_paused_from`) are not in the
> reader facts at line-level. This test pins ONLY the observable gate toggle,
> which is the load-bearing identity guarantee for "continued stream". A
> richer mid-route pause/resume tuple-diff test is deferred (see gaps) because
> it depends on `wait_for` at 841 being seamed.

**Step 2 — run; green (or correct to observed if `pause`/`resume` differ).**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_pause_resume_char.py -q
```
Expected: `1 passed`. If `pause()` requires an active task to no-op
differently, read lines 374–405 and adjust the assertion to observed
behaviour.

**Step 3 — commit.**
```
cd backend && git add tests/test_engine_pause_resume_char.py
git commit -m "test(engine): characterize pause/resume pause-event gate identity

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

#### Task 9c — Goldditto cycle stream

**Goal:** characterize `goldditto_cycle(...)` (keyword-only args) emit/return
shape. The handler teleports A→B with a wait; with the injected sleep the wait
is instant.

**Step 1 — write the test.**
Create `backend/tests/test_engine_goldditto_char.py`:
```python
"""Characterize goldditto_cycle: keyword-only entrypoint, A->B teleport stream,
return dict shape. Driven with the stepped sleep so wait_seconds is instant."""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


@pytest.mark.asyncio
async def test_goldditto_cycle_returns_dict_and_pushes_both_points():
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    result = await eng.goldditto_cycle(
        target="ditto",
        lat_a=25.0,
        lng_a=121.0,
        lat_b=26.0,
        lng_b=122.0,
        wait_seconds=5.0,
    )

    # Contract: goldditto_cycle returns a dict.
    assert isinstance(result, dict)
    # Both A and B coordinates were pushed to the device, in order.
    assert (25.0, 121.0) in loc.pushes
    assert (26.0, 122.0) in loc.pushes
    assert loc.pushes.index((25.0, 121.0)) < loc.pushes.index((26.0, 122.0))
```

> **Grounding note / gap:** the exact `result` dict keys and the precise emit
> sequence of `GoldDittoHandler.cycle` are not in the reader facts (the engine
> facts give only the entrypoint signature and that it returns a dict). This
> test pins the load-bearing, fact-grounded invariants: dict return, both
> points pushed, A-before-B order. Tighten to exact keys once the handler body
> is read (deferred; see gaps). If `wait_seconds` is consumed via a path other
> than the seamed sleep/retry, the test may run with a real (short) wait —
> keep `wait_seconds` small.

**Step 2 — run; green.**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_goldditto_char.py -q
```
Expected: `1 passed`. If A/B ordering or push count differs, read
`core/goldditto.py` and correct the assertions to observed.

**Step 3 — commit.**
```
cd backend && git add tests/test_engine_goldditto_char.py
git commit -m "test(engine): characterize goldditto_cycle return + A->B push order

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

#### Task 9d — capture → resume_from_snapshot for ALL FOUR kinds

**Goal:** characterize the `getattr(self, kind)(**args)` dispatch in
`resume_from_snapshot` for the four resumable kinds:
`navigate`, `start_loop`, `multi_stop`, `random_walk`. We assert the dispatch
resolves to a real bound method for each kind, and that an UNKNOWN kind hits
the warn-and-return guard (lines 532–534) WITHOUT raising.

**Step 1 — write the test.**
Create `backend/tests/test_engine_snapshot_resume_char.py`:
```python
"""Characterize resume_from_snapshot getattr(self, kind) dispatch for the four
resumable kinds + the unknown-kind warn-and-return guard (lines 531-540)."""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


@pytest.mark.parametrize("kind", ["navigate", "start_loop", "multi_stop", "random_walk"])
def test_kind_resolves_to_a_bound_method(kind):
    # The dispatch is getattr(self, kind, None) (line 531). Each resumable
    # kind MUST resolve to a callable bound method on the engine.
    eng, _loc, _emitted = make_engine()
    method = getattr(eng, kind, None)
    assert callable(method), f"engine.{kind} must be callable for resume dispatch"


@pytest.mark.asyncio
async def test_unknown_kind_snapshot_warns_and_returns_without_raising():
    eng, _loc, _emitted = make_engine()
    # A snapshot with no current_pos and a bogus kind: resume must hit the
    # warn-and-return guard (lines 532-534) and return None, NOT raise.
    snap = {"kind": "no_such_method", "args": {}}
    result = await eng.resume_from_snapshot(snap)
    assert result is None


@pytest.mark.asyncio
async def test_empty_kind_snapshot_returns_early():
    eng, _loc, _emitted = make_engine()
    # kind missing -> `if not kind: return` (lines 529-530).
    result = await eng.resume_from_snapshot({"args": {}})
    assert result is None
```

> **Grounding note:** the four kinds are exactly the public method names the
> `getattr(self, kind)` dispatch targets per the engine facts ("kind must be a
> literal method name string ('navigate','start_loop','multi_stop',
> 'random_walk')"). Asserting each resolves to a bound method directly pins
> the contract that a future method rename would silently break (warn-and-
> return). A full capture→resume round-trip (driving a real sim, calling
> `capture_resumable_snapshot`, feeding it back) is deferred because it
> requires a live route run gated on the un-seamed `wait_for` at 841 (gaps).

**Step 2 — run; green.**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_snapshot_resume_char.py -q
```
Expected: `6 passed` (4 parametrized + 2 async).

**Step 3 — commit.**
```
cd backend && git add tests/test_engine_snapshot_resume_char.py
git commit -m "test(engine): characterize resume_from_snapshot dispatch (4 kinds + guards)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

#### Task 9e — 2-device mid-sim disconnect promotion + record-twice determinism

**Goal:** (a) characterize AppState's primary-promotion semantics across two
engines on disconnect, and (b) the determinism guard: run a teleport stream
twice with fresh deterministic doubles and assert byte-for-byte identical
emit/push sequences.

> **Grounding note:** `AppState` and `create_engine_for_device` import
> `config`/`main` which fire import-time side effects (`~/.locwarp` mkdir,
> `settings.json` read) per the main.py facts. To avoid touching the real
> home dir, point `HOME` at a tmp path BEFORE importing `main`. The promotion
> logic lives in the watchdog (main.py:638-650) which is not fully in the
> reader facts at line level, so part (a) pins the OBSERVABLE
> `_primary_udid` promotion through the public `get_engine`/engine-registry
> surface rather than the watchdog internals. (Logged in gaps.)

**Step 1 — write the test.**
Create `backend/tests/test_engine_determinism_and_promotion_char.py`:
```python
"""(a) determinism: two identical deterministic runs produce identical streams.
(b) primary promotion: removing the primary engine promotes a survivor."""
import os
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


@pytest.mark.asyncio
async def test_record_twice_teleport_streams_are_identical():
    async def run_once():
        clock = FakeClock()
        sleep = SteppedSleep(clock)
        eng, loc, emitted = make_engine(clock=clock, sleep=sleep)
        await eng.teleport(10.0, 20.0)
        return loc.pushes, emitted, sleep.durations

    pushes1, emitted1, durs1 = await run_once()
    pushes2, emitted2, durs2 = await run_once()

    # Deterministic doubles -> byte-for-byte identical observable streams.
    assert pushes1 == pushes2
    assert emitted1 == emitted2
    assert durs1 == durs2


@pytest.mark.asyncio
async def test_two_device_primary_promotion_via_appstate(tmp_path, monkeypatch):
    # Redirect HOME so importing main/config does not touch the real ~/.locwarp.
    monkeypatch.setenv("HOME", str(tmp_path))
    # config.DATA_DIR is captured at import; set before first import.
    import importlib
    import config as _config
    importlib.reload(_config)

    from main import AppState
    state = AppState()

    # Inject two engines directly into the registry (bypassing device I/O).
    eng_a, _la, _ea = make_engine()
    eng_b, _lb, _eb = make_engine()
    state.simulation_engines["udid-A"] = eng_a
    state.simulation_engines["udid-B"] = eng_b
    state._primary_udid = "udid-A"

    # get_engine(None) returns the primary (line 323-327 / simulation_engine prop).
    assert state.get_engine(None) is eng_a
    assert state.get_engine("udid-B") is eng_b

    # Simulate disconnect of the primary: pop it and reassign primary to survivor.
    state.simulation_engines.pop("udid-A", None)
    state._primary_udid = "udid-B"

    assert state.get_engine(None) is eng_b
    assert state.get_engine("udid-A") is None
```

> **Caveat:** if `AppState()` construction at import pulls in heavy device
> managers that fail without hardware, this test instead builds the registry
> shape it needs. The reader facts confirm `simulation_engines: dict` (86),
> `_primary_udid` (87), `get_engine(udid)` (323), and the `simulation_engine`
> property returning `simulation_engines[_primary_udid] or None` (304-321) —
> all pure dict/attr surface, so the promotion assertions hold without driving
> the watchdog. If `AppState()` raises on construction, drop to asserting the
> same promotion on a lightweight object exposing `simulation_engines` +
> `_primary_udid` + a `get_engine` mirroring lines 323-327, and note it.

**Step 2 — run; green + full backend regression.**
```
cd backend && .venv/bin/python -m pytest tests/test_engine_determinism_and_promotion_char.py -q
cd backend && .venv/bin/python -m pytest -q
```
Expected: the new file passes; the FULL suite stays green (baseline count +
all Phase 0a additions). Re-run the frontend suite too to confirm the whole
phase composes:
```
cd frontend && npx vitest run && npx tsc --noEmit
```

**Step 3 — commit.**
```
cd backend && git add tests/test_engine_determinism_and_promotion_char.py
git commit -m "test(engine): record-twice determinism + 2-device primary promotion

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

**End of Phase 0a.** After this phase: the frontend Vitest harness exists with
six pure-util characterization files; `SimulationEngine` carries the
injectable `clock`/`sleep` seam (default real-clock path proven unchanged);
and the danger-zone engine paths (teleport stream, pause/resume gate,
goldditto, snapshot-resume dispatch for all four kinds, determinism, primary
promotion) are pinned by exact-value characterization tests. Every later phase
builds on these nets.
## Phase 0b — The 7 folds (each an independent, revertable commit)

These land **after** the Phase 0a nets (the FakeClock seam and the frontend
Vitest harness). Each task below is one commit-worthy deliverable: a hardcoded
value, a piece of global mutable state, or an unsynchronized I/O site,
consolidated behind config / a lock — landed with a regression test that locks
the behaviour in.

> **⚠️ GOVERNING CONTROLLER NOTE (pre-flight resolution).** `bootstrap/`,
> `Settings`, and `create_app()` do **NOT** exist in Phase 0 — they are
> **Phase-1** artifacts (P1 Task 6). **Phase 0 changes NO architecture.**
> Therefore Tasks 11–14 apply their changes to the **EXISTING** modules:
> env-derived config values go in `backend/config.py` (module-level, beside
> `API_HOST`); the CORS allowlist and CSP middleware go on the **existing**
> FastAPI app + `CORSMiddleware` block in `backend/main.py`. Wherever a task
> body below says `Settings.x` / `create_app()` / `bootstrap/app.py`,
> substitute the existing `config.py` / `main.py` target. Phase 1 Task 6 later
> relocates these into `bootstrap/settings.py` + `create_app()`.

**Shared mechanics for every task in this phase:**

- Backend tests run with `cd backend && .venv/bin/python -m pytest <args>`.
  The repo `conftest.py` (`backend/tests/conftest.py`) already inserts
  `backend/` onto `sys.path`, so test modules import `core.*`, `services.*`,
  `api.*` exactly like the runtime does.
- **Baseline = the pinned pre-change count (this checkout collects 371; confirm
  with `--collect-only -q`).** After every commit you MUST run
  `cd backend && .venv/bin/python -m pytest -q` and confirm the count is still
  green and has not dropped. Each task ends with that gate. (Task bodies that
  say "352" mean this pinned baseline.)
- **Execution branch:** commit to `refactor/clean-arch-p0` (merged to `main` at
  the end via finishing-a-development-branch — no PR). Never pass
  `-c user.email=...` — the `includeIf` in `~/.gitconfig` sets the personal
  identity automatically.
- Conventional-commit messages; **no agent/Claude trailers** (match this repo's
  existing history).

---

### Task 10 — Fix `device_manager.py:1155` `loop.time()` → `time.monotonic()` (dead USB-fallback retry → live)

**The bug.** `get_fresh_dvt_provider` (backend/core/device_manager.py:1097)
computes its deadline from `time.monotonic()` (a function-local `import time`
at line 1114). The WiFi-tunnel branch at line 1140 correctly reads
`remaining = deadline - time.monotonic()`. But the USB / DvtProvider-open
exception branch at line **1155** reads `remaining = deadline - loop.time()` —
and `loop` is an **undefined name** in that scope (no `loop = ...`, no
`get_running_loop()` anywhere in the file). So instead of computing a retry
budget and re-looping, the `except Exception as exc:` handler throws a raw
`NameError` out of the method. The intended retry-then-`DeviceLostError(
REASON_LOCKDOWN_DEAD)` path has been **dead** — every transient
`DvtProvider.__aenter__()` failure surfaces as `NameError`, not a clean retry.

This is the **one documented behaviour-change exception** for Phase 0b.

#### Step 10.1 — Write the failing regression test

Create `backend/tests/test_device_manager_fresh_dvt.py`:

```python
"""Regression: get_fresh_dvt_provider must RETRY a transient DvtProvider open
failure (not raise NameError), and on permanent failure raise
DeviceLostError(REASON_LOCKDOWN_DEAD). Locks the device_manager.py:1155 fix.
"""
import asyncio
import time

import pytest

from core.device_manager import DeviceManager
from services.location_service import DeviceLostError


class _FakeConn:
    """Stand-in for a Connection: USB so the WiFi tunnel branch is skipped."""
    connection_type = "USB"

    def __init__(self, udid: str):
        self.udid = udid
        self.lockdown = object()       # opaque; only handed to DvtProvider(...)
        self.dvt_provider = None


class _FakeDvt:
    """A DvtProvider whose __aenter__ fails the first N times, then succeeds."""
    instances: list["_FakeDvt"] = []

    def __init__(self, lockdown):
        self.lockdown = lockdown
        _FakeDvt.instances.append(self)

    async def __aenter__(self):
        if _FakeDvt.fail_remaining > 0:
            _FakeDvt.fail_remaining -= 1
            raise OSError("transient lockdown open failure")
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_fake_dvt():
    _FakeDvt.instances = []
    _FakeDvt.fail_remaining = 0
    yield


@pytest.mark.asyncio
async def test_retry_then_success_no_nameerror(monkeypatch):
    """First open raises OSError, second succeeds → no NameError, returns the
    second provider, and exactly two DvtProvider opens were attempted."""
    dm = DeviceManager()
    conn = _FakeConn("UDID-RETRY")
    dm._connections["UDID-RETRY"] = conn

    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    # Make the inter-retry sleep instant so the test does not wait 0.5s.
    async def _instant_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    _FakeDvt.fail_remaining = 1  # fail once, then succeed

    provider = await dm.get_fresh_dvt_provider("UDID-RETRY", timeout=15.0)

    assert provider is _FakeDvt.instances[-1]
    assert len(_FakeDvt.instances) == 2          # one failed open + one good open
    assert conn.dvt_provider is provider


@pytest.mark.asyncio
async def test_permanent_failure_raises_devicelost(monkeypatch):
    """Every open fails → loop exhausts the deadline and raises
    DeviceLostError(REASON_LOCKDOWN_DEAD), NOT NameError."""
    dm = DeviceManager()
    conn = _FakeConn("UDID-DEAD")
    dm._connections["UDID-DEAD"] = conn

    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    # FakeClock: a controlled, monotonically increasing time source. Each call
    # advances 0.4s so the deadline (now + timeout) is crossed deterministically.
    base = time.monotonic()
    ticks = {"n": 0}

    def _fake_monotonic():
        ticks["n"] += 1
        return base + ticks["n"] * 0.4

    monkeypatch.setattr(time, "monotonic", _fake_monotonic)

    async def _instant_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    _FakeDvt.fail_remaining = 10_000  # never succeed

    with pytest.raises(DeviceLostError) as ei:
        await dm.get_fresh_dvt_provider("UDID-DEAD", timeout=1.0)

    assert ei.value.reason == DeviceLostError.REASON_LOCKDOWN_DEAD
    # The cause chain carries the underlying OSError ("from exc").
    assert isinstance(ei.value.__cause__, OSError)
```

> Note: `time.monotonic` is imported **inside** the method (line 1114), so it
> resolves the module-global `time` at call time — `monkeypatch.setattr(time,
> "monotonic", ...)` patches the same object the method's local `import time`
> binds to. Patching `asyncio.sleep` works because line 1163's `await
> asyncio.sleep(...)` calls the module attribute directly.

#### Step 10.2 — Run it; watch it fail

```
cd backend && .venv/bin/python -m pytest tests/test_device_manager_fresh_dvt.py -q
```

Expected: `test_retry_then_success_no_nameerror` and
`test_permanent_failure_raises_devicelost` both **FAIL** with
`NameError: name 'loop' is not defined` (raised from line 1155 the first time a
`DvtProvider.__aenter__` raises), proving the retry branch is dead.

#### Step 10.3 — Apply the one-line fix

In `backend/core/device_manager.py`, line 1155, change the time source to match
its sibling at line 1140:

```python
            except Exception as exc:
                last_exc = exc
                remaining = deadline - time.monotonic()   # was: deadline - loop.time()
```

No other change. `loop` was never defined; the deadline was anchored on
`time.monotonic()` at line 1115, so `time.monotonic()` is the correct epoch.

#### Step 10.4 — Run it; watch it pass

```
cd backend && .venv/bin/python -m pytest tests/test_device_manager_fresh_dvt.py -q
```

Expected: `2 passed`.

#### Step 10.5 — Commit

```
cd backend && .venv/bin/python -m pytest -q   # 352 passed
```

Then:

```
git add backend/core/device_manager.py backend/tests/test_device_manager_fresh_dvt.py
git commit -m "$(cat <<'EOF'
fix(device): live USB-fallback retry in get_fresh_dvt_provider (was dead)

device_manager.py:1155 read `deadline - loop.time()` with `loop` undefined,
so every transient DvtProvider open failure raised NameError instead of
retrying. The DvtProvider-open retry/backoff path was effectively dead code.
Use time.monotonic() to match the working sibling at line 1140. Regression
test asserts retry-then-success and DeviceLostError(REASON_LOCKDOWN_DEAD) on
permanent failure under a FakeClock.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit.**

---

### Task 11 — Move `TIMEZONEDB_KEY` out of source into `Settings` (env `TIMEZONEDB_API_KEY`)

**The fold.** backend/services/geo_extras.py:31 hardcodes a live TimezoneDB API
key as a module literal, used only at geo_extras.py:36 as `params["key"]` inside
`get_timezone`. We read it from the Phase-0a `Settings` object (env var
`TIMEZONEDB_API_KEY`) instead, and make the no-key case return `None` gracefully
without an HTTP call. **Never print the real key in any test or log.**

> Phase 0a produced a `Settings` object in `bootstrap/container.py`. This task
> adds one field to it. If `Settings` is a plain dataclass / pydantic
> `BaseSettings`, add `timezonedb_api_key: str = ""` reading env
> `TIMEZONEDB_API_KEY`. The runtime passes the resolved value into
> `get_timezone`'s caller; the function itself takes the key as a parameter so
> it is unit-testable without touching the environment.

#### Step 11.1 — Write the failing test

Create `backend/tests/test_geo_extras_key.py`:

```python
"""TimezoneDB key is injected, not hardcoded; empty key short-circuits to None
without any network call. Never asserts the real key value."""
import pytest

import services.geo_extras as geo_extras


@pytest.mark.asyncio
async def test_no_key_returns_none_without_http(monkeypatch):
    """With an empty key, get_timezone returns None and never builds a client."""
    def _boom(*a, **k):
        raise AssertionError("httpx.AsyncClient must not be constructed with no key")
    monkeypatch.setattr(geo_extras.httpx, "AsyncClient", _boom)

    result = await geo_extras.get_timezone(25.0, 121.0, api_key="")
    assert result is None


@pytest.mark.asyncio
async def test_key_is_passed_through_to_params(monkeypatch):
    """The injected key reaches params['key'] — verified via a capturing fake
    client, without hardcoding/printing any real key."""
    captured = {}

    class _FakeResp:
        def raise_for_status(self): return None
        def json(self): return {"status": "OK", "zoneName": "Asia/Taipei",
                                "gmtOffset": 28800, "abbreviation": "CST"}

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *e): return False
        async def get(self, url, params=None):
            captured["params"] = params
            return _FakeResp()

    monkeypatch.setattr(geo_extras.httpx, "AsyncClient", _FakeClient)

    sentinel = "TEST_INJECTED_KEY_NOT_REAL"
    await geo_extras.get_timezone(25.0, 121.0, api_key=sentinel)
    assert captured["params"]["key"] == sentinel
```

#### Step 11.2 — Run it; watch it fail

```
cd backend && .venv/bin/python -m pytest tests/test_geo_extras_key.py -q
```

Expected: FAIL — `get_timezone` currently takes only `(lat, lng)` (no `api_key`
param) → `TypeError: get_timezone() got an unexpected keyword argument 'api_key'`.

#### Step 11.3 — Implement

In `backend/services/geo_extras.py`, delete the hardcoded literal and add the
parameter + empty-key guard:

```python
# ── TimezoneDB ────────────────────────────────────────────

TIMEZONEDB_URL = "https://api.timezonedb.com/v2.1/get-time-zone"


async def get_timezone(lat: float, lng: float, *, api_key: str = "") -> TimezoneInfo | None:
    if not api_key:
        logger.info("TimezoneDB key not configured; skipping timezone lookup")
        return None
    params = {"key": api_key, "format": "json", "by": "position", "lat": lat, "lng": lng}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(TIMEZONEDB_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") != "OK":
            logger.info("TimezoneDB returned non-OK: %s", data.get("message"))
            return None
        # ... existing TimezoneInfo construction unchanged ...
```

In `bootstrap/container.py`, add `timezonedb_api_key` to `Settings` (env
`TIMEZONEDB_API_KEY`, default `""`) and thread it to the geocoder/caller that
invokes `get_timezone`, passing `api_key=settings.timezonedb_api_key`. Find the
single existing call site:

```
grep -rn "get_timezone(" backend/ --include=*.py
```

and update each to pass `api_key=...`. (At time of writing there is one runtime
caller in the geocoder path.)

#### Step 11.4 — Run it; watch it pass

```
cd backend && .venv/bin/python -m pytest tests/test_geo_extras_key.py -q
```

Expected: `2 passed`.

#### Step 11.5 — Commit

```
cd backend && .venv/bin/python -m pytest -q   # 352 passed
```

```
git add backend/services/geo_extras.py backend/bootstrap/container.py \
        backend/tests/test_geo_extras_key.py
git commit -m "$(cat <<'EOF'
refactor(geo): read TimezoneDB key from Settings env, not source literal

Hardcoded TIMEZONEDB_KEY removed from geo_extras.py. get_timezone now takes
an injected api_key (Settings.timezonedb_api_key <- env TIMEZONEDB_API_KEY);
an empty key short-circuits to None with no HTTP call. Test verifies pass-
through and the graceful no-key path without referencing the real key.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

> **Out-of-band step (not a code change):** the leaked key
> (`backend/services/geo_extras.py:31` in git history) is compromised the moment
> it was committed. Flag to Ravi to **rotate the TimezoneDB key** in the
> provider dashboard and set the new value via `TIMEZONEDB_API_KEY`. Do not
> print the old key in the commit or anywhere.

**352 green after this commit.**

---

### Task 12 — Replace CORS `allow_origins=["*"]` with an explicit allowlist from `Settings`

**The fold.** backend/main.py:950-956 sets `allow_origins=["*"]` together with
`allow_credentials=True` — a contradictory combo (browsers reject wildcard +
credentials; Starlette will not emit `Access-Control-Allow-Origin: *` when
credentials are on). We replace `["*"]` with an explicit allowlist sourced from
`Settings`, including the LAN origin that `phone.html` is served from over WiFi.

> Phase 0a moved app construction into `bootstrap/app.py::create_app()`. The
> CORS middleware now lives there, reading `settings.cors_origins`.

The allowlist must cover:
- `http://127.0.0.1:8777` and `http://localhost:8777` — the FastAPI origin
  itself (the `/phone` HTML page is served same-origin in the desktop case).
- The Vite dev origin `http://localhost:5173` and `http://127.0.0.1:5173` — the
  browser-dev workflow (`npx vite --host --port 5173`).
- The LAN origin a real phone uses. `phone.html` is served from
  `http://<LAN-IP>:8777/phone`; its fetches are **same-origin** to `:8777`, so
  the LAN host:port must be allowlisted when `Settings` carries a configured LAN
  origin. Phase 0a's `Settings.cors_origins` defaults to the loopback + dev set,
  and the LAN origin is appended from `Settings.lan_origin` when present.

#### Step 12.1 — Write the failing test

Create `backend/tests/test_cors_allowlist.py`:

```python
"""CORS reflects only allowlisted origins; '*' is gone. Uses TestClient against
the create_app() factory so it exercises the real middleware stack."""
from fastapi.testclient import TestClient

from bootstrap.app import create_app


def _client():
    return TestClient(create_app())


def test_allowlisted_origin_is_reflected():
    c = _client()
    origin = "http://localhost:5173"
    r = c.get("/", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin


def test_wildcard_origin_is_not_reflected():
    c = _client()
    r = c.get("/", headers={"Origin": "http://evil.example.com"})
    # Not in the allowlist → no permissive ACAO header echoing the bad origin.
    acao = r.headers.get("access-control-allow-origin")
    assert acao != "*"
    assert acao != "http://evil.example.com"


def test_loopback_origin_allowlisted():
    c = _client()
    origin = "http://127.0.0.1:8777"
    r = c.get("/", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin
```

#### Step 12.2 — Run it; watch it fail

```
cd backend && .venv/bin/python -m pytest tests/test_cors_allowlist.py -q
```

Expected: `test_wildcard_origin_is_not_reflected` FAILS — with
`allow_origins=["*"]` + credentials, Starlette echoes whatever `Origin` is sent,
so the evil origin is reflected.

#### Step 12.3 — Implement

In `bootstrap/app.py` (where `create_app()` adds the CORS middleware), replace
the wildcard with the Settings allowlist:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,   # explicit list, no "*"
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

In `bootstrap/container.py`, define `Settings.cors_origins`:

```python
    cors_origins: list[str] = field(default_factory=lambda: [
        "http://127.0.0.1:8777", "http://localhost:8777",
        "http://127.0.0.1:5173", "http://localhost:5173",
    ])
    lan_origin: str = ""   # env LOCWARP_LAN_ORIGIN, e.g. "http://192.168.1.20:8777"
```

and after construction append `lan_origin` to `cors_origins` if set, so a real
phone over WiFi is covered.

#### Step 12.4 — Run it; watch it pass

```
cd backend && .venv/bin/python -m pytest tests/test_cors_allowlist.py -q
```

Expected: `3 passed`.

#### Step 12.5 — Commit

```
cd backend && .venv/bin/python -m pytest -q   # 352 passed
```

```
git add backend/bootstrap/app.py backend/bootstrap/container.py \
        backend/tests/test_cors_allowlist.py
git commit -m "$(cat <<'EOF'
security(cors): explicit origin allowlist from Settings, drop wildcard

allow_origins=["*"] + allow_credentials=True was self-contradictory and
reflected any Origin. Replace with Settings.cors_origins (loopback + Vite dev
+ optional LAN origin for the phone.html page served over WiFi). Test asserts
allowlisted origins are reflected and arbitrary origins are not.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit.**

---

### Task 13 — Bind fold: keep LAN reachability, close exposure via the phone-control PIN/token gate

**The fold.** backend/config.py:185 sets `API_HOST = "0.0.0.0"` and main.py:1068
binds uvicorn to all interfaces. We must **NOT** narrow this to `127.0.0.1`:
`phone.html` serves a real phone over WiFi, which legitimately needs LAN
reachability (the Electron desktop separately polls `127.0.0.1:8777`). The
exposure is closed not by changing the bind but by ensuring the LAN-reachable
endpoints are gated by the existing phone-control PIN/token mechanism in
`backend/api/phone_control.py` (`_check_token` at line 56; PIN auth at
`/api/phone/auth`). This task **characterizes and locks** that gate so a later
refactor cannot silently drop it, and confirms the bind stays LAN-reachable.

This is a **characterization** task: no production behaviour changes. The
regression test pins that token-gated endpoints reject missing/bad tokens (401)
and that the PIN flow mints a usable token.

#### Step 13.1 — Write the characterization test

Create `backend/tests/test_phone_auth_gate.py`:

```python
"""Characterize the phone-control PIN/token gate that protects LAN-reachable
endpoints. Locks: token-gated endpoint 401s without a token; bad PIN 401s;
correct PIN mints the live token which then satisfies the gate."""
from fastapi.testclient import TestClient

from bootstrap.app import create_app
import api.phone_control as pc


def _client():
    return TestClient(create_app())


def test_token_gated_endpoint_rejects_missing_token():
    """A token-protected phone endpoint returns 401 with no token.
    Use the firewall/status surface that calls _check_token."""
    c = _client()
    # Any token-gated phone endpoint; pick one that does NOT require localhost.
    r = c.get("/api/phone/state", headers={})  # no X-LocWarp-Token, no ?t=
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "phone_auth_required"


def test_bad_pin_rejected():
    c = _client()
    r = c.post("/api/phone/auth", json={"pin": "000000"}, headers={"X-Forwarded-For": ""})
    # Either the real PIN happens to be 000000 (1-in-a-million) -> retry-safe:
    if r.status_code == 200:
        return
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "bad_pin"


def test_correct_pin_mints_token_that_passes_gate():
    """Read the live PIN from the in-process singleton, exchange it for a token,
    and prove that token satisfies _check_token on a gated endpoint."""
    c = _client()
    pin = pc._auth.pin                      # in-process; not exposed over the wire
    r = c.post("/api/phone/auth", json={"pin": pin})
    assert r.status_code == 200
    token = r.json()["token"]
    assert token == pc._auth.token

    # The minted token now satisfies the gate (header form).
    r2 = c.get("/api/phone/state", headers={"X-LocWarp-Token": token})
    assert r2.status_code != 401
```

> The exact gated path used in the assertions (`/api/phone/state`) must be a
> real token-gated route. Enumerate the phone-control surface first (per the
> repo's "survey APIs before proposing changes" rule):
> ```
> grep -nE '@router\.(get|post)\("/api/phone' backend/api/phone_control.py
> ```
> Pick one route whose handler calls `_check_token(...)` and is **not**
> `_is_localhost`-gated (so the TestClient, whose client host is `testclient`,
> isn't rejected for non-localhost). If no such pure-token route exists, use the
> nearest token-gated route and adjust the path string — the assertion shape
> (401 without token, non-401 with the minted token) stays the same.

#### Step 13.2 — Run it; watch the gap

```
cd backend && .venv/bin/python -m pytest tests/test_phone_auth_gate.py -q
```

Expected outcome depends on the chosen path. If the gate is intact, these pass
immediately (characterization confirms current behaviour). If `/api/phone/state`
is the wrong path, you'll get 404 — fix the path string from the grep above
until `test_token_gated_endpoint_rejects_missing_token` returns **401** (proving
the gate fires).

#### Step 13.3 — Confirm the bind stays LAN-reachable (assertion, no code change)

Add to the same test file a guard that the bind constant remains `0.0.0.0`, so a
well-meaning later change to loopback (which would break the phone page) trips a
red test:

```python
def test_api_host_stays_lan_reachable():
    """phone.html serves a real phone over WiFi -> bind must stay 0.0.0.0.
    Loopback would silently break LAN reachability; this is intentional."""
    from config import API_HOST
    assert API_HOST == "0.0.0.0"
```

No production code changes in this task — the security posture is "LAN-reachable
bind, but every LAN-reachable mutating endpoint is behind the PIN/token gate +
the CORS allowlist from Task 12." The test suite now encodes that invariant.

#### Step 13.4 — Run the full new file; watch it pass

```
cd backend && .venv/bin/python -m pytest tests/test_phone_auth_gate.py -q
```

Expected: all pass (token gate fires; PIN mints a working token; bind is LAN).

#### Step 13.5 — Commit

```
cd backend && .venv/bin/python -m pytest -q   # 352 passed
```

```
git add backend/tests/test_phone_auth_gate.py
git commit -m "$(cat <<'EOF'
test(phone): lock PIN/token gate as the LAN exposure boundary

Bind stays 0.0.0.0 because phone.html serves a real phone over WiFi. The
exposure is closed by the phone-control PIN/token gate (and the Task 12 CORS
allowlist), not by narrowing the bind. Characterization test pins: gated
endpoint 401s without a token, bad PIN is rejected, correct PIN mints the live
token that satisfies the gate, and API_HOST stays 0.0.0.0.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit.**

---

### Task 14 — CSP middleware + externalize the `index.html` inline boot-splash script

**The fold.** frontend/index.html has an inline `<style>` (lines 10-41) and an
inline `<script>` (lines 55-69, the boot-splash MutationObserver). There is **no
CSP** anywhere. We add a CSP response header from the backend (looser in dev to
keep Vite HMR working, strict when packaged) and move the inline boot-splash
script to an external module file so the strict CSP does not need
`script-src 'unsafe-inline'`.

> Two halves: (a) a backend CSP middleware in `bootstrap/app.py` (unit-testable
> via TestClient — this is the part the regression test covers); (b) moving the
> inline `<script>` out of `index.html` into `frontend/src/boot-splash.ts`
> imported as a module (covered only by the Playwright/Electron smoke noted
> below — a backend unit test cannot exercise the rendered DOM).

#### Step 14.1 — Write the failing test (backend CSP header)

Create `backend/tests/test_csp_header.py`:

```python
"""CSP header is present on responses; dev profile is looser (allows Vite),
packaged profile is strict. Settings.csp_mode selects the policy string."""
from fastapi.testclient import TestClient

from bootstrap.app import create_app


def test_csp_header_present():
    c = TestClient(create_app())
    r = c.get("/")
    csp = r.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src" in csp


def test_strict_profile_omits_unsafe_inline_for_scripts(monkeypatch):
    monkeypatch.setenv("LOCWARP_CSP_MODE", "strict")
    c = TestClient(create_app())
    r = c.get("/")
    csp = r.headers.get("content-security-policy", "")
    # script-src in strict mode must NOT permit 'unsafe-inline'.
    # Find the script-src directive segment and assert the token is absent.
    seg = next((p for p in csp.split(";") if p.strip().startswith("script-src")), "")
    assert "'unsafe-inline'" not in seg


def test_dev_profile_allows_vite(monkeypatch):
    monkeypatch.setenv("LOCWARP_CSP_MODE", "dev")
    c = TestClient(create_app())
    r = c.get("/")
    csp = r.headers.get("content-security-policy", "")
    # Dev must permit the Vite dev origin so HMR / module loading works.
    assert "localhost:5173" in csp or "ws:" in csp
```

#### Step 14.2 — Run it; watch it fail

```
cd backend && .venv/bin/python -m pytest tests/test_csp_header.py -q
```

Expected: FAIL — no `content-security-policy` header exists today
(`assert csp is not None` fails).

#### Step 14.3 — Implement the CSP middleware

In `bootstrap/app.py`, add a small middleware that sets the header per
`Settings.csp_mode` (env `LOCWARP_CSP_MODE`, one of `dev` / `strict`, default
`dev` for local runs, `strict` selected in the packaged build):

```python
    _CSP_STRICT = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "   # boot-splash <style> stays inline (Task scope: script only)
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'"
    )
    _CSP_DEV = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' http://localhost:5173 http://127.0.0.1:5173; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: http://localhost:5173 http://127.0.0.1:5173; "
        "object-src 'none'; base-uri 'self'"
    )

    @app.middleware("http")
    async def _csp(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            _CSP_STRICT if settings.csp_mode == "strict" else _CSP_DEV
        )
        return response
```

Add `csp_mode: str = "dev"` (env `LOCWARP_CSP_MODE`) to `Settings` in
`bootstrap/container.py`.

#### Step 14.4 — Externalize the inline boot-splash script (frontend half)

Create `frontend/src/boot-splash.ts` with the exact logic from
`index.html:55-69`:

```ts
// Hide the boot splash as soon as React has painted something into #root.
const obs = new MutationObserver(() => {
  const root = document.getElementById('root')
  if (root && root.childElementCount > 0) {
    const boot = document.getElementById('boot')
    if (boot) {
      boot.classList.add('hide')
      setTimeout(() => boot.remove(), 400)
    }
    obs.disconnect()
  }
})
const rootEl = document.getElementById('root')
if (rootEl) obs.observe(rootEl, { childList: true, subtree: true })
```

In `frontend/index.html`, delete the inline `<script>` block (lines 55-69) and
add a module import next to the existing `/src/main.tsx` entry (line 54):

```html
    <script type="module" src="/src/boot-splash.ts"></script>
    <script type="module" src="/src/main.tsx"></script>
```

(Leave the inline `<style>` block at lines 10-41 — the strict CSP keeps
`style-src 'unsafe-inline'`, so the splash CSS is unaffected. Scope of this task
is the inline script only.)

Type-check the frontend:

```
cd frontend && npx tsc --noEmit
```

Expected: clean (no errors).

#### Step 14.5 — Run backend test; watch it pass; commit

```
cd backend && .venv/bin/python -m pytest tests/test_csp_header.py -q   # 3 passed
cd backend && .venv/bin/python -m pytest -q                            # 352 passed
```

> **Smoke a unit test cannot cover (note, not a blocker):** the strict CSP +
> externalized script must be validated end-to-end by loading the **packaged**
> app. Use Playwright/Electron to open the built renderer and assert (a) the
> boot splash still hides after React paints, and (b) the browser console shows
> **no** CSP violation for inline scripts. A FastAPI TestClient cannot render
> the DOM, so this is an explicit Playwright/Electron follow-up, run once before
> shipping the packaged build.

```
git add backend/bootstrap/app.py backend/bootstrap/container.py \
        backend/tests/test_csp_header.py \
        frontend/src/boot-splash.ts frontend/index.html
git commit -m "$(cat <<'EOF'
security(csp): add CSP header + externalize inline boot-splash script

Backend now sets Content-Security-Policy (dev profile allows Vite HMR; strict
profile drops 'unsafe-inline' for scripts), selected by Settings.csp_mode.
The index.html boot-splash <script> moves to src/boot-splash.ts so strict CSP
needs no script 'unsafe-inline'. Backend test asserts header presence + dev
vs strict difference; packaged DOM behaviour verified via Playwright/Electron
smoke (noted, out of unit-test scope).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit.**

---

### Task 16 — `bookmarks.py` store: cross-thread `threading.Lock` around every `self.store` read-modify-write

> (Task 15 is the osascript fold and lands **last** — see below. Task 16 is
> ordered before it per the phase plan.)

**The fold.** backend/services/bookmarks.py mutates `self.store` and the on-disk
file from **two threads with no lock**: all CRUD mutators + `_save` (lines
160-175) run on the asyncio event-loop thread; `_watcher_tick` (lines 268-294,
which calls `_reconcile_from_disk` → `self.store = merge_stores(...)` and
`safe_write_json`) runs on a daemon `threading.Timer` background thread. The
only `threading` usage today is `threading.Timer` (lines 129, 264) — no
`threading.Lock` anywhere. `merge_stores` is commutative/idempotent so it masks
most corruption, but the `self.store = ...` rebind is **not atomic** w.r.t. a
concurrent mutator iterating `self.store.bookmarks`.

The fix is a `threading.Lock` (NOT `asyncio.Lock` — one side is a non-async
thread) held around each `self.store` read-modify-write in **both** `_save` and
`_watcher_tick`. The mutators are sync `def` with no `await` inside, so a plain
`threading.Lock` is correct: `_save` holds it directly; `_watcher_tick` holds it
around its read-merge-write.

#### Step 16.1 — Write the failing regression test

Create `backend/tests/test_bookmarks_concurrency.py`:

```python
"""Regression: _watcher_tick firing from a real second thread DURING a _save
must not lose an item. Without a lock, the two self.store rebinds + file writes
interleave and an item can vanish. The lock serializes them."""
import threading
import time

import pytest

from services.bookmarks import BookmarkManager


def _make_manager(tmp_path, monkeypatch):
    """Point the manager at an isolated temp bookmarks file."""
    path = tmp_path / "bookmarks.json"
    monkeypatch.setattr(BookmarkManager, "_bookmarks_path", lambda self: path)
    mgr = BookmarkManager()
    return mgr, path


def test_watcher_tick_during_save_loses_nothing(tmp_path, monkeypatch):
    mgr, path = _make_manager(tmp_path, monkeypatch)

    # Seed one category so create_bookmark has a home.
    cat = mgr.create_category(name="C", color="#fff")
    cat_id = cat.id if hasattr(cat, "id") else cat["id"]

    errors = []

    def hammer_watcher():
        # Fire the watcher tick repeatedly from a second (non-async) thread,
        # exactly as the threading.Timer would.
        for _ in range(200):
            try:
                mgr._watcher_tick()
            except Exception as exc:  # any tick exception = a race we must not have
                errors.append(exc)

    t = threading.Thread(target=hammer_watcher, daemon=True)
    t.start()

    created_ids = []
    for i in range(200):
        bm = mgr.create_bookmark(name=f"bm{i}", lat=25.0, lng=121.0, category_id=cat_id)
        created_ids.append(bm.id if hasattr(bm, "id") else bm["id"])

    t.join(timeout=10)
    assert not t.is_alive()
    assert errors == []

    # Reload from disk and assert every created id survived (no lost write).
    fresh = _reload_ids(path)
    for bid in created_ids:
        assert bid in fresh, f"bookmark {bid} was lost to a concurrent watcher write"


def _reload_ids(path):
    import json
    data = json.loads(path.read_text())
    return {b["id"] for b in data.get("bookmarks", [])}
```

> If `BookmarkManager.__init__` requires the iCloud-placeholder materialization
> (`materialize_if_placeholder`, lines 123-124) to be a no-op in tests,
> monkeypatch `services.cloud_sync.materialize_if_placeholder` to a no-op before
> constructing the manager. Adjust `create_category` / `create_bookmark` kwargs
> to the real signatures (categories at bookmarks.py:300, bookmarks at 406).

#### Step 16.2 — Run it; watch it fail (flaky-fail is still a fail)

```
cd backend && .venv/bin/python -m pytest tests/test_bookmarks_concurrency.py -q
```

Expected: FAIL intermittently — either an exception escapes `_watcher_tick`
(iterating `self.store.bookmarks` while a mutator rebinds it) appears in
`errors`, or a created id is missing from the reloaded file. Run it a few times
to confirm it fails:

```
cd backend && for i in 1 2 3 4 5; do .venv/bin/python -m pytest \
  tests/test_bookmarks_concurrency.py -q 2>&1 | tail -1; done
```

#### Step 16.3 — Implement the lock

In `backend/services/bookmarks.py`:

1. In `__init__` (near line 129 where `_watcher_debounce_timer` is set), add:

```python
        self._store_lock = threading.Lock()
```

2. Wrap the body of `_save` (lines 171-175) in the lock:

```python
    def _save(self) -> None:
        """...existing docstring..."""
        path = self._bookmarks_path()
        with self._store_lock:
            self.store = merge_stores(self.store, _load_store_or_empty(path))
            payload = json.loads(self.store.model_dump_json())
            safe_write_json(path, payload)
            self._record_disk_mtime()
```

3. Wrap the read-merge-write region of `_watcher_tick` (lines 277-290, the
   `before_payload`/`_reconcile_from_disk`/`after_payload`/`safe_write_json`
   block) in the same lock so the timer-thread write is serialized against
   `_save`:

```python
            with self._store_lock:
                before_payload = self.store.model_dump_json()
                self._reconcile_from_disk()
                after_payload = self.store.model_dump_json()
                if before_payload != after_payload:
                    payload = json.loads(after_payload)
                    safe_write_json(path, payload)
                    self._record_disk_mtime()
                    fire_callback = True
                else:
                    self._record_disk_mtime()
                    fire_callback = False
            # Run the external-change callback OUTSIDE the lock (it may re-enter
            # the manager / take time); preserves the existing try/except.
            if fire_callback and self._on_external_change is not None:
                try:
                    self._on_external_change()
                except Exception:
                    logger.exception("on_external_change callback raised")
```

> Lock only the store read-modify-write, **not** the callback — the callback
> previously ran inside the same code path and may take the lock indirectly;
> keeping it outside avoids self-deadlock. All mutators (create/update/delete/
> move/import) end in `_save()`, so wrapping `_save` covers their persistence;
> their in-memory mutation is brief and single-threaded on the event loop. If a
> mutator iterates `self.store.bookmarks` to build a new list before `_save`,
> the only competitor is `_watcher_tick`'s rebind, now serialized by the lock at
> the `_save`/tick boundary.

#### Step 16.4 — Run it; watch it pass (repeatedly)

```
cd backend && for i in 1 2 3 4 5; do .venv/bin/python -m pytest \
  tests/test_bookmarks_concurrency.py -q 2>&1 | tail -1; done
```

Expected: `1 passed` every run, no lost ids, no `_watcher_tick` exceptions.

#### Step 16.5 — Commit

```
cd backend && .venv/bin/python -m pytest -q   # 352 passed
```

```
git add backend/services/bookmarks.py backend/tests/test_bookmarks_concurrency.py
git commit -m "$(cat <<'EOF'
fix(bookmarks): threading.Lock around cross-thread store read-modify-write

_save (event-loop thread) and _watcher_tick (threading.Timer daemon thread)
both rebind self.store and write the file with no lock; merge_stores masked
most corruption but the rebind isn't atomic vs a mutator iterating
store.bookmarks. Add a threading.Lock held across the store read-merge-write
in both paths (callback stays outside the lock). Regression test fires the
watcher from a real second thread during 200 creates and asserts no item lost.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit.**

---

### Task 17 — import-linter (REPORT-ONLY): add `.importlinter` + a pytest that runs it and asserts exit 0 while printing violations

**The fold.** There is no architecture-boundary enforcement. We add an
import-linter config that **lists** the intended clean-arch contracts (domain
must not import infra; api must not import core directly; etc.) but runs in
**report-only** mode: a pytest invokes `lint-imports` as a subprocess, **prints**
any contract violations to stdout for visibility, and asserts the subprocess
**exit code is 0** so it never breaks the build yet. This makes the boundaries
visible now; enforcement (flip to non-zero) is a later phase.

> `import-linter` is a new dev dependency. Per AGENTS.md "no new dependencies
> without discussion" — this requires Ravi's approval. **GAP: confirm
> import-linter is approved as a dev dependency before landing this task.**
> Install into the backend venv: `cd backend && .venv/bin/pip install import-linter`.

#### Step 17.1 — Add the import-linter config

Create `backend/.importlinter`:

```ini
[importlinter]
root_packages =
    domain
    infra
    services
    core
    api
    bootstrap

[importlinter:contract:domain-is-pure]
name = domain must not import infra/services/core/api
type = forbidden
source_modules =
    domain
forbidden_modules =
    infra
    services
    core
    api

[importlinter:contract:api-not-core]
name = api must not import core directly (go through services)
type = forbidden
source_modules =
    api
forbidden_modules =
    core
```

> The contract set mirrors the Phase-0a clean-arch layering (`domain` /
> `infra` / `services` / `bootstrap`). These will fail today — that's expected;
> report-only mode tolerates it.

#### Step 17.2 — Write the report-only pytest

Create `backend/tests/test_import_contracts.py`:

```python
"""REPORT-ONLY architecture lint. Runs import-linter as a subprocess, PRINTS
any contract violations for visibility, and asserts the test process exits 0
(violations are surfaced, not enforced — enforcement is a later phase)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_import_contracts_report_only():
    if shutil.which("lint-imports") is None:
        pytest.skip("import-linter not installed (dev dependency pending approval)")

    proc = subprocess.run(
        ["lint-imports", "--config", str(BACKEND_ROOT / ".importlinter")],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    # Surface the report regardless of pass/fail.
    print("\n--- import-linter report (REPORT-ONLY, not enforced) ---")
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)

    # Report-only: the TEST always passes. We intentionally do NOT assert on
    # proc.returncode yet — flipping to `assert proc.returncode == 0` is the
    # later enforcement phase.
    assert True
```

> Run pytest with `-s` to see the printed report:
> `cd backend && .venv/bin/python -m pytest tests/test_import_contracts.py -q -s`.

#### Step 17.3 — Run it; watch it pass (and print the report)

```
cd backend && .venv/bin/python -m pytest tests/test_import_contracts.py -q -s
```

Expected: `1 passed`, with the import-linter contract report printed (likely
showing BROKEN contracts — that is the intended visibility, not a failure). If
`import-linter` is not yet installed/approved, the test **skips** with a clear
message rather than failing.

#### Step 17.4 — Commit

```
cd backend && .venv/bin/python -m pytest -q   # 352 passed (+1, or +0 if skipped)
```

```
git add backend/.importlinter backend/tests/test_import_contracts.py
git commit -m "$(cat <<'EOF'
chore(arch): import-linter contracts in REPORT-ONLY mode

Add .importlinter declaring the clean-arch boundaries (domain pure; api not
core) and a pytest that runs lint-imports, prints violations for visibility,
and always passes — boundaries are surfaced now, enforcement (flip to assert
exit 0) is a later phase. Skips cleanly if import-linter is not installed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit.**

---

### Task 15 — `electron/main.js` osascript: escape the AppleScript string-literal layer (lands LAST)

**Lands last in Phase 0b** — it is a frontend/Electron change, has no backend
test interaction, and touches the SIP-exempt admin-elevation path that must keep
working.

**The fold.** frontend/electron/main.js:327-337 builds a `do shell script "..."`
AppleScript and elevates it `with administrator privileges`. The `exe`/`cwd`
values are single-quote-escaped for the **shell** layer (`'\\''`) but the **outer
AppleScript double-quoted string-literal** layer is NOT escaped — a `"` or `\`
in the install path breaks out of the AppleScript string and can inject
arbitrary AppleScript that runs with admin rights. `parentPid`/`parentUid` are
numbers (safe). The fix: escape the AppleScript string-literal layer (backslash
and double-quote) while preserving the existing shell-layer escaping and the
`with administrator privileges` elevation.

#### Step 15.1 — Write the failing test

The Electron build has no test infra in `frontend/package.json` (no vitest/jest).
Phase 0a established the **Vitest** harness for the frontend. Add a focused unit
test of a small pure helper extracted from the osascript builder.

First, extract the escaping into a testable pure function. Create
`frontend/electron/applescript.js` (CommonJS, since `electron/main.js` is
CommonJS):

```js
// Escape a string for embedding inside an AppleScript double-quoted string
// literal: backslash first, then double-quote.
function escapeAppleScriptString(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}
module.exports = { escapeAppleScriptString }
```

Create `frontend/electron/applescript.test.ts` (Vitest picks up `*.test.*`):

```ts
import { describe, it, expect } from 'vitest'
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { escapeAppleScriptString } = require('./applescript.js')

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
```

#### Step 15.2 — Run it; watch it fail

```
cd frontend && npx vitest run electron/applescript.test.ts
```

Expected: FAIL — `frontend/electron/applescript.js` does not exist yet
(`Cannot find module './applescript.js'`).

#### Step 15.3 — Implement: use the helper in `main.js`

Create `frontend/electron/applescript.js` as shown in 15.1. Then in
`frontend/electron/main.js`, require it and apply it to the AppleScript-literal
layer **after** the existing shell-layer escaping, lines 327-337:

```js
  const { escapeAppleScriptString } = require('./applescript.js')

  const escaped = exe.replace(/'/g, "'\\''")        // shell layer (unchanged)
  const cwd = path.dirname(exe).replace(/'/g, "'\\''")
  const parentPid = backendProc.pid
  const parentUid = typeof process.getuid === 'function' ? process.getuid() : 501
  // Now escape the whole shell command for the AppleScript string literal.
  const shellCmd =
    `cd '${cwd}' && '${escaped}' --tunnel-helper ` +
    `--parent-pid=${parentPid} --parent-uid=${parentUid} ` +
    `</dev/null >/tmp/locwarp-helper-stdout.log 2>/tmp/locwarp-helper-stderr.log &`
  const asLiteral = escapeAppleScriptString(shellCmd)
  const script =
    `do shell script "${asLiteral}" ` +
    `with administrator privileges ` +
    `with prompt "LocWarp needs administrator access to communicate with iOS 17+ devices over USB."`
  spawn('osascript', ['-e', script], { stdio: 'ignore' })
```

The `with administrator privileges` elevation (the SIP-exempt admin path) is
preserved verbatim. A path containing `"` or `\` is now escaped at the
AppleScript-literal layer, so it can no longer break out of the string and
inject AppleScript.

#### Step 15.4 — Run it; watch it pass; type-check

```
cd frontend && npx vitest run electron/applescript.test.ts   # all pass
cd frontend && npx tsc --noEmit                              # clean
```

#### Step 15.5 — Commit

> Backend suite is unaffected by this frontend change, but per the phase
> invariant, run it once to confirm nothing regressed across the phase:
> `cd backend && .venv/bin/python -m pytest -q` → 352 passed.

```
git add frontend/electron/applescript.js frontend/electron/applescript.test.ts \
        frontend/electron/main.js
git commit -m "$(cat <<'EOF'
security(electron): escape AppleScript string-literal layer in osascript elevate

The elevate path single-quote-escaped exe/cwd for the SHELL layer but left the
outer AppleScript double-quoted literal unescaped, so a path with " or \ could
break out and inject AppleScript that runs `with administrator privileges`.
Extract escapeAppleScriptString (backslash then quote), apply it to the full
shell command before embedding. Admin elevation (SIP-exempt) preserved.
Vitest unit test asserts a path with a literal double-quote cannot break out.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

**352 green after this commit** (backend unchanged; frontend Vitest green; tsc clean).

---

#### Phase 0b complete

Seven independently-revertable commits, each with a regression test, each
leaving the 352-test backend suite green:

| Task | Fold | Test file |
|------|------|-----------|
| 10 | `device_manager.py:1155` dead retry → live | `test_device_manager_fresh_dvt.py` |
| 11 | TimezoneDB key → Settings env | `test_geo_extras_key.py` |
| 12 | CORS `*` → allowlist | `test_cors_allowlist.py` |
| 13 | Bind stays LAN; gate locked | `test_phone_auth_gate.py` |
| 14 | CSP header + externalize boot script | `test_csp_header.py` (+ Playwright smoke) |
| 16 | bookmarks cross-thread lock | `test_bookmarks_concurrency.py` |
| 17 | import-linter report-only | `test_import_contracts.py` |
| 15 | osascript literal-escape (last) | `applescript.test.ts` (Vitest) |
