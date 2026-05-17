# History Context Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the map's existing right-click context menu on each row of the "Recent destinations" history dropdown, so the user can teleport / navigate / copy / add-bookmark / set-Gold-Ditto / add-waypoint a past location without re-flying to it first.

**Architecture:** Single render path for the menu (no duplicated JSX): extend MapView's existing `contextMenu` state with one optional `name?` field and add a small `openContextMenuForRecent(entry, x, y)` helper. Each recent row gets two new triggers — right-click on the row and a `⋮` icon button — both feeding the same state. The "Add to bookmarks" item reads the optional `name` and forwards it to `handleAddBookmark`, which gains an optional `suggestedName` parameter so the dialog pre-fills instead of overwriting with reverse-geocode.

**Tech Stack:** React 18 + TypeScript + Vite + Leaflet (frontend lives in `frontend/`). No automated test suite — correctness gate is `tsc --noEmit` plus `npm run build`, behavior gate is a manual smoke test against `npm run dev` per spec §6.

**Spec:** `docs/superpowers/specs/2026-05-17-history-context-menu-design.md` (commit `880c7b3`).

---

## File Structure

All changes are in `frontend/`. No new files, no test files (frontend has no automated test suite).

| File | Why it changes |
|------|----------------|
| `frontend/src/components/MapView.tsx` | (1) `ContextMenuState` interface adds optional `name?: string`. (2) `openContextMenuForRecent` helper created. (3) Each recent-list row restructured from a single `<button>` to a `<div>` flex wrapper containing the existing re-fly `<button>` + a new `⋮` icon `<button>`. (4) Right-click handler on the wrapper. (5) The "Add to bookmarks" menu item forwards `contextMenu.name` to `onAddBookmark`. (6) Prop type for `onAddBookmark` gains a third optional arg. |
| `frontend/src/App.tsx` | `handleAddBookmark` signature extended with optional `suggestedName?: string`. The dialog seed `name` becomes `(suggestedName ?? '').trim()`. The existing `<MapView onAddBookmark={handleAddBookmark}>` wire keeps working (extra optional arg, no change needed at call site). |
| `frontend/src/i18n/strings.ts` | New string `recent.menu_tooltip` (zh: `更多動作`, en: `More actions`) used as the `⋮` button's `title` + `aria-label`. |

---

## Task 1: Extend `handleAddBookmark` to accept an optional suggested name

**Files:**
- Modify: `frontend/src/App.tsx:692-729`

This is the lowest-risk change and unblocks everything else. The signature gains an optional third parameter; existing callers continue to work because TypeScript treats the extra arg as optional.

- [ ] **Step 1: Edit `handleAddBookmark` signature and seed logic**

In `frontend/src/App.tsx`, locate the block starting at line 692:

```ts
  const handleAddBookmark = useCallback((lat: number, lng: number) => {
    setAddBmDialog({
      lat,
      lng,
      name: '',
      category: bm.categories[0]?.name || t('bm.default'),
      nameResolving: true,
    })
    // Reverse-geocode asynchronously to pre-fill the name + remember country.
    // User can still overwrite the suggestion. If the call fails we just leave
    // the field blank as before.
```

Replace with:

```ts
  const handleAddBookmark = useCallback((lat: number, lng: number, suggestedName?: string) => {
    // When the caller already knows a name (e.g. a recent-history entry
    // from a search), seed the dialog so reverse-geocode only fills the
    // country_code and won't overwrite the typed name — the existing
    // "if (prev.name.length > 0)" branch below already protects it.
    const seedName = (suggestedName || '').trim()
    setAddBmDialog({
      lat,
      lng,
      name: seedName,
      category: bm.categories[0]?.name || t('bm.default'),
      nameResolving: true,
    })
    // Reverse-geocode asynchronously to pre-fill the name + remember country.
    // User can still overwrite the suggestion. If the call fails we just leave
    // the field blank as before.
```

Everything below this block — the async reverse-geocode IIFE and the `useCallback` deps array — stays untouched.

- [ ] **Step 2: Typecheck**

Run from repo root:

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output (clean exit). `handleAddBookmark` callers that pass only 2 args remain valid because the third is optional.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "refactor(app): handleAddBookmark accepts optional suggestedName"
```

---

## Task 2: Extend `ContextMenuState` with optional `name?` field

**Files:**
- Modify: `frontend/src/components/MapView.tsx:30-36`

Pure data-shape change — no behavior change yet. `name` stays undefined everywhere until Task 4 sets it.

- [ ] **Step 1: Edit the interface**

In `frontend/src/components/MapView.tsx`, find lines 30–36:

```ts
interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  lat: number;
  lng: number;
}
```

Replace with:

```ts
interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  lat: number;
  lng: number;
  // Set when the menu is opened from a history entry that has a known
  // name (e.g. an address from search). Forwarded to onAddBookmark to
  // pre-fill the dialog. Undefined when opened from a map right-click.
  name?: string;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output. The existing initializer at line 439 omits `name` — valid for optional fields. The map's `contextmenu` handler at line 810 does a full object replacement that also omits `name` — also valid.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "refactor(map): allow ContextMenuState to carry optional entry name"
```

---

## Task 3: Forward `contextMenu.name` from the "Add to bookmarks" menu item; extend `onAddBookmark` prop type

**Files:**
- Modify: `frontend/src/components/MapView.tsx:50` (prop type)
- Modify: `frontend/src/components/MapView.tsx:2561-2570` (menu item onClick)

Two surgical edits. After this task, when `contextMenu.name` is set (only happens after Task 4), the bookmark dialog pre-fills. When not set (every existing flow), behavior is unchanged.

- [ ] **Step 1: Extend the prop type signature**

In `frontend/src/components/MapView.tsx`, find line 50:

```ts
  onAddBookmark: (lat: number, lng: number) => void;
```

Replace with:

```ts
  onAddBookmark: (lat: number, lng: number, suggestedName?: string) => void;
```

- [ ] **Step 2: Forward the name in the menu item**

In the same file, find the "Add to bookmarks" menu item around line 2561:

```tsx
            onClick={() => {
              onAddBookmark(contextMenu.lat, contextMenu.lng);
              closeContextMenu();
            }}
```

Replace with:

```tsx
            onClick={() => {
              onAddBookmark(contextMenu.lat, contextMenu.lng, contextMenu.name);
              closeContextMenu();
            }}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output. `App.tsx` passes `handleAddBookmark` (already accepts 3 args after Task 1) so the prop type matches.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "refactor(map): forward contextMenu.name through Add Bookmark item"
```

---

## Task 4: Add the `recent.menu_tooltip` i18n string

**Files:**
- Modify: `frontend/src/i18n/strings.ts:354`

Trivial string addition. Done as its own task so the next task (the UI restructure) can `import` it without mixing concerns.

- [ ] **Step 1: Add the string**

In `frontend/src/i18n/strings.ts`, find line 354:

```ts
  'recent.kind_coord': { zh: '座標', en: 'Coord' },
```

Insert the new line directly after it:

```ts
  'recent.kind_coord': { zh: '座標', en: 'Coord' },
  'recent.menu_tooltip': { zh: '更多動作', en: 'More actions' },
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/strings.ts
git commit -m "i18n: add recent.menu_tooltip string for history kebab button"
```

---

## Task 5: Restructure each recent-list row to add the right-click + `⋮` triggers

**Files:**
- Modify: `frontend/src/components/MapView.tsx:2276-2347` (recent row render)

This is the user-visible change. The row's outer `<button>` becomes a `<div>` flex wrapper carrying the row-hover background; inside it live two siblings — the existing re-fly `<button>` (now flex:1) and a new `⋮` icon `<button>` (shrink-0). The wrapper also carries `onContextMenu`.

A small inline helper `openContextMenuForRecent(entry, x, y)` is declared close to the recent-list render so it captures `setContextMenu` and the `entry` shape. It does a **full object replacement** (no spread) to avoid any stale field leakage from a prior opening.

- [ ] **Step 1: Locate the current row render**

In `frontend/src/components/MapView.tsx`, the existing row (around lines 2304–2347) looks like this:

```tsx
                  return (
                    <button
                      key={`${entry.ts}-${idx}`}
                      onClick={() => {
                        if (onRecentReFly) onRecentReFly(entry);
                        setRecentOpen(false);
                      }}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        width: '100%',
                        padding: '9px 12px',
                        background: 'transparent', border: 'none',
                        borderBottom: idx < recentPlaces.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                        color: '#e8eaf0', textAlign: 'left',
                        cursor: 'pointer', transition: 'background 0.12s',
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.04)'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent'; }}
                    >
                      <span style={{
                        flexShrink: 0,
                        fontSize: 10, fontWeight: 700,
                        letterSpacing: '0.05em',
                        color: badge.color,
                        background: badge.bg,
                        border: `1px solid ${badge.color}33`,
                        borderRadius: 4,
                        padding: '3px 6px',
                        minWidth: 34,
                        textAlign: 'center',
                      }}>{badge.label}</span>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 500,
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                        }}>{display}</div>
                        <div style={{
                          fontSize: 10, opacity: 0.55, fontFamily: 'monospace', marginTop: 2,
                        }}>
                          {entry.lat.toFixed(5)}, {entry.lng.toFixed(5)} · {agoLabel}
                        </div>
                      </div>
                    </button>
                  );
```

- [ ] **Step 2: Replace the row with the wrapped flex layout + triggers**

Replace the entire `return ( <button ... /> );` block above with:

```tsx
                  // Open the shared context menu anchored at the given
                  // viewport coords, carrying the entry's name so the
                  // Add Bookmark item can pre-fill the dialog. Full
                  // object replacement (no spread) so no stale field
                  // from a prior opening leaks in.
                  const openMenuAt = (x: number, y: number) => {
                    setContextMenu({
                      visible: true,
                      x, y,
                      lat: entry.lat,
                      lng: entry.lng,
                      name: entry.name || undefined,
                    });
                    setRecentOpen(false);
                  };
                  return (
                    <div
                      key={`${entry.ts}-${idx}`}
                      style={{
                        display: 'flex', alignItems: 'stretch',
                        width: '100%',
                        borderBottom: idx < recentPlaces.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                        transition: 'background 0.12s',
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.04)'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
                      onContextMenu={(e) => {
                        // Suppress the browser's native menu and stop
                        // the event from bubbling to the dropdown's
                        // outside-click handler.
                        e.preventDefault();
                        e.stopPropagation();
                        openMenuAt(e.clientX, e.clientY);
                      }}
                    >
                      <button
                        onClick={() => {
                          if (onRecentReFly) onRecentReFly(entry);
                          setRecentOpen(false);
                        }}
                        style={{
                          flex: 1, minWidth: 0,
                          display: 'flex', alignItems: 'center', gap: 10,
                          padding: '9px 12px',
                          background: 'transparent', border: 'none',
                          color: '#e8eaf0', textAlign: 'left',
                          cursor: 'pointer',
                        }}
                      >
                        <span style={{
                          flexShrink: 0,
                          fontSize: 10, fontWeight: 700,
                          letterSpacing: '0.05em',
                          color: badge.color,
                          background: badge.bg,
                          border: `1px solid ${badge.color}33`,
                          borderRadius: 4,
                          padding: '3px 6px',
                          minWidth: 34,
                          textAlign: 'center',
                        }}>{badge.label}</span>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{
                            fontSize: 13, fontWeight: 500,
                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          }}>{display}</div>
                          <div style={{
                            fontSize: 10, opacity: 0.55, fontFamily: 'monospace', marginTop: 2,
                          }}>
                            {entry.lat.toFixed(5)}, {entry.lng.toFixed(5)} · {agoLabel}
                          </div>
                        </div>
                      </button>
                      <button
                        title={tRef.current('recent.menu_tooltip')}
                        aria-label={tRef.current('recent.menu_tooltip')}
                        onClick={(e) => {
                          e.stopPropagation();
                          openMenuAt(e.clientX, e.clientY);
                        }}
                        style={{
                          flexShrink: 0, alignSelf: 'stretch',
                          padding: '0 10px',
                          background: 'transparent', border: 'none',
                          color: '#9499ac',
                          cursor: 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          transition: 'color 0.12s, background 0.12s',
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.color = '#e8eaf0';
                          (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.06)';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.color = '#9499ac';
                          (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="12" cy="5"  r="1" />
                          <circle cx="12" cy="12" r="1" />
                          <circle cx="12" cy="19" r="1" />
                        </svg>
                      </button>
                    </div>
                  );
```

Why these choices:
- The wrapper `<div>` carries the row-level hover background; the inner re-fly `<button>` is transparent so the row background shows through. The `⋮` button has its own hover tint that overrides on top — clear "this specific action is highlighted" feedback.
- `openMenuAt` is declared inside `.map((entry, idx) => { ... })`, so it closes over the current `entry`. No new top-level helper needed.
- `setRecentOpen(false)` closes the dropdown when the menu opens — keeps the focus on the menu and avoids overlap clutter. (Mirrors the existing left-click flow which also closes the dropdown.)
- The `⋮` icon is three dots stacked vertically (standard kebab glyph), 14×14, stroke-only — matches every other icon in the menu.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 4: Production build sanity check**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`. The pre-existing dynamic-import warning about `services/api.ts` is unchanged and unrelated.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "feat(map): right-click + kebab menu on recent history entries"
```

---

## Task 6: Manual smoke test

**Files:** none

Per spec §6 the frontend has no automated test suite — verification is manual against the dev server. This task is the gate before declaring done.

- [ ] **Step 1: Start the dev server**

```bash
cd frontend && npm run dev
```

The server runs in the foreground; open the URL it prints (typically `http://localhost:5173`) in a browser, or use `npm start` to also launch Electron.

- [ ] **Step 2: Populate history with mixed entries**

With a device connected (or via coord input if none), perform a few actions so the recent list has variety:

1. Teleport to a coord (creates a `teleport` or `coord_teleport` entry).
2. Navigate to a coord (creates a `navigate` or `coord_navigate` entry).
3. Use the address search to teleport to a named place like "Tokyo Tower" (creates a `search` entry with `name` populated).

Open the "Recent destinations" dropdown (top-right of the map).

- [ ] **Step 3: Walk through the verification matrix**

For each check, confirm the observed behavior matches "Expected":

| # | Action | Expected |
|---|--------|----------|
| 1 | Left-click the body of any recent row | Re-flies as before (no regression). |
| 2 | Right-click on any row | Context menu opens at the cursor with the same items as the map's right-click menu. |
| 3 | Left-click the `⋮` icon | Same context menu opens; dropdown closes. |
| 4 | From a search-kind entry, click "Add to bookmarks" | Add Bookmark dialog opens with the entry's name pre-filled in the Name field. |
| 5 | From a `coord_teleport` entry without a name, click "Add to bookmarks" | Dialog opens with Name empty; reverse-geocode fills it (existing behavior). |
| 6 | Click Teleport / Navigate / Copy / Set Gold Ditto A | Each behaves identically to the same item invoked from the map. |
| 7 | Enter a route mode (Loop or MultiStop), re-open the menu from a row | "Add waypoint" appears at the bottom of the menu (same gating as map). |
| 8 | Disconnect the device, right-click a row | Menu opens; Teleport/Navigate show the disabled "device disconnected" state. |
| 9 | Right-click on the map background | Map right-click menu still works exactly as before. |

If any row fails, stop and triage rather than papering over.

- [ ] **Step 4: Stop the dev server**

`Ctrl-C` the foreground process.

- [ ] **Step 5: (no commit — manual-test task)**

This task has no code changes. If smoke test surfaced any defects, fix them in a follow-up task with its own commit.

---

## Out of scope (do not implement here)

These were explicitly excluded by the spec and brainstorm decisions — do **not** sneak them in:

- Extracting `<MapContextMenu>` into a standalone component.
- A "Remove from history" menu item.
- Showing the entry's `name` (rather than its lat/lng) in the menu header when opened from a history row.
- Any storage / backend / persistence change to how recent entries are recorded.
