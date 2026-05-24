# Bookmark Context Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give bookmark right-click parity with map/history right-click (Teleport / Navigate / Set as Gold A / Add Waypoint + coords header + reverse-geocode), and remove the "click also flies GPS" toggle so bookmark left-click is always a map pan-only preview.

**Architecture:** Plumb existing App-level callbacks (already wired to `MapView`) through `ControlPanel` into `BookmarkList`. Replace `BookmarkList`'s existing 4-item context menu with a superset menu containing the new jump-mode rows, the existing edit/copy/delete/move-to rows, and a coords header with What's-here reverse-geocode — visually matching `MapView`'s menu. Independently, delete the `flyGps` localStorage toggle + checkbox UI and switch left-click to always call `handleMapPanOnly`.

**Tech Stack:** TypeScript, React 18, Vite. No new dependencies. No backend changes.

**Reference spec:** `docs/superpowers/specs/2026-05-24-bookmark-context-menu-design.md`

---

## File Map

| File | Change kind | Responsibility |
|---|---|---|
| `frontend/src/components/BookmarkList.tsx` | Modify | Add jump-mode menu rows, coord-header + reverse-geocode, consume new props, drop `flyGps` + `onBookmarkPreview` |
| `frontend/src/components/ControlPanel.tsx` | Modify | Plumb new props through, drop `onBookmarkPreview` |
| `frontend/src/App.tsx` | Modify | Wire new props to ControlPanel; swap `onBookmarkClick` from `handleTeleport` to `handleMapPanOnly`; drop `onBookmarkPreview` line |
| `frontend/src/i18n/strings.ts` | Modify | Delete `bm.fly_gps` and `bm.fly_gps_tooltip` keys |

No new files. No tests added (the repo has no frontend test runner — verification is `tsc --noEmit` + manual smoke).

---

## Working Directory

All commands run from repo root unless noted.
- Type check: `cd frontend && npx tsc --noEmit`
- Dev (browser): `cd frontend && npx vite --host --port 5173`

---

## Task 1: Plumb new props through the App → ControlPanel → BookmarkList chain

**Why first:** All later tasks consume these props. Doing the type/prop wiring first means the menu-building task can focus purely on UI without juggling props.

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx:37-83` (interface), `:112-138` (destructure)
- Modify: `frontend/src/components/ControlPanel.tsx:83-100` (interface — exact lines may shift, look for the prop block ending with `onBookmarkPreview?: (bm: Bookmark) => void;`), `:270-310` (destructure list ending around `onBookmarkPreview,`), `:936-965` (the `<BookmarkList ... />` JSX block)
- Modify: `frontend/src/App.tsx:1516` (the `<ControlPanel ... />` JSX block — find every existing prop and add the new ones in the same block)

- [ ] **Step 1: Add new props to BookmarkList interface**

Open `frontend/src/components/BookmarkList.tsx`. Find the `interface BookmarkListProps {` block (around line 37). Locate the existing `onBookmarkPreview?: (bm: Bookmark) => void;` line (and its 3-line comment above it, lines 45-47).

Replace lines 44-48:

```typescript
  onBookmarkClick: (bm: Bookmark) => void;
  // Camera-only fly: pans the map to the bookmark coordinate without
  // moving the iPhone GPS. Used when the "click also flies GPS"
  // checkbox is unticked. Optional: if not supplied the toggle hides.
  onBookmarkPreview?: (bm: Bookmark) => void;
```

with:

```typescript
  // Left-click on a bookmark row. Pans the map only — never moves GPS.
  // All GPS jump actions are reached via right-click (see onTeleport etc.).
  onBookmarkClick: (bm: Bookmark) => void;
  // Right-click jump actions. Mirror the map context menu so bookmark
  // right-click has parity with map / history right-click.
  onTeleport: (lat: number, lng: number) => void;
  onNavigate: (lat: number, lng: number) => void;
  onSetAsGoldDittoA?: (lat: number, lng: number) => void;
  onAddWaypoint?: (lat: number, lng: number) => void;
  // Gates Teleport / Navigate (greyed when no device) and Add Waypoint
  // (hidden when not in a route mode). Mirrors MapView prop semantics.
  deviceConnected: boolean;
  showWaypointOption: boolean;
  // Toast hook for "coords copied" / What's-here transient feedback.
  onShowToast?: (msg: string) => void;
```

- [ ] **Step 2: Update the destructure list**

Still in `BookmarkList.tsx`, find the `const BookmarkList: React.FC<BookmarkListProps> = ({` block (around line 112). Replace the line `  onBookmarkPreview,` with:

```typescript
  onTeleport,
  onNavigate,
  onSetAsGoldDittoA,
  onAddWaypoint,
  deviceConnected,
  showWaypointOption,
  onShowToast,
```

(There is no `onBookmarkPreview` to replace — we are removing it here, the new props take its slot in the destructure list.)

- [ ] **Step 3: Update the import line at the top of BookmarkList.tsx**

Open `frontend/src/components/BookmarkList.tsx`. Find line 5:

```typescript
import { getBookmarkUiState, setBookmarkUiState } from '../services/api';
```

Replace with:

```typescript
import { getBookmarkUiState, setBookmarkUiState, reverseGeocode } from '../services/api';
```

- [ ] **Step 4: Mirror the prop changes in ControlPanel's interface**

Open `frontend/src/components/ControlPanel.tsx`. Find `onBookmarkPreview?: (bm: Bookmark) => void;` in the props interface (around line 97). Replace that single line with:

```typescript
  onTeleport: (lat: number, lng: number) => void;
  onNavigate: (lat: number, lng: number) => void;
  onSetAsGoldDittoA?: (lat: number, lng: number) => void;
  onAddWaypoint?: (lat: number, lng: number) => void;
  deviceConnected: boolean;
  showWaypointOption: boolean;
  onShowToast?: (msg: string) => void;
```

Note: `onTeleport` and `onNavigate` are already in `ControlPanelProps` (used internally at lines 426, 428, 438, 611) — leave the existing declarations alone and **only** add the items the interface does not already have. Re-check the existing interface around lines 83-100 before pasting; if `onTeleport`/`onNavigate` are already typed, only add `onSetAsGoldDittoA`, `onAddWaypoint`, `deviceConnected`, `showWaypointOption`, `onShowToast`.

- [ ] **Step 5: Update ControlPanel's destructure list**

Still in `ControlPanel.tsx`, find the destructure block at around line 270. Locate the line `  onBookmarkPreview,` and replace it with whichever of these are not already in the destructure list:

```typescript
  onSetAsGoldDittoA,
  onAddWaypoint,
  deviceConnected,
  showWaypointOption,
  onShowToast,
```

(Skip `onTeleport`, `onNavigate` if already present.)

- [ ] **Step 6: Update the `<BookmarkList ... />` JSX in ControlPanel**

Still in `ControlPanel.tsx`, find the `<BookmarkList` element around line 936. Locate the line:

```typescript
                    onBookmarkPreview={onBookmarkPreview}
```

Replace it with:

```typescript
                    onTeleport={onTeleport}
                    onNavigate={onNavigate}
                    onSetAsGoldDittoA={onSetAsGoldDittoA}
                    onAddWaypoint={onAddWaypoint}
                    deviceConnected={deviceConnected}
                    showWaypointOption={showWaypointOption}
                    onShowToast={onShowToast}
```

- [ ] **Step 7: Update the `<ControlPanel ... />` JSX in App.tsx**

Open `frontend/src/App.tsx`. Find the `<ControlPanel` opening at line 1516. Find the line:

```typescript
          onBookmarkPreview={(b: any) => handleMapPanOnly(b.lat, b.lng)}
```

Replace it with:

```typescript
          onSetAsGoldDittoA={handleSetGoldDittoA}
          onAddWaypoint={handleAddWaypoint}
          deviceConnected={device.connectedDevice !== null}
          showWaypointOption={sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop || sim.mode === SimMode.Navigate}
          onShowToast={showToast}
```

(Use the **exact** same right-hand sides as the existing `<MapView>` props at lines 2102–2106 — they are the same callbacks. If any of those App-level identifiers do not yet exist, abort and ask — the spec assumed they were already wired into MapView and they are; double-check before deviating.)

`onTeleport={handleTeleport}` and `onNavigate={handleNavigate}` already exist on the `<ControlPanel>` JSX block — do not duplicate.

- [ ] **Step 8: Also update the `onBookmarkClick` line in App.tsx to be the pan-only handler**

Still in `App.tsx`, find:

```typescript
          onBookmarkClick={(b: any) => handleTeleport(b.lat, b.lng)}
```

Replace with:

```typescript
          onBookmarkClick={(b: any) => handleMapPanOnly(b.lat, b.lng)}
```

This swap is part of the same edit window as Step 7. Doing it now (rather than in the "remove flyGps" task) keeps the type-check passing — at this stage the new props are wired but the `BookmarkList` body still references `onBookmarkPreview`, which we haven't removed yet. **TypeScript will complain about an unknown prop `onBookmarkPreview` removed from the interface vs. the (already-deleted) JSX line. Verify in Step 9.**

- [ ] **Step 9: Type-check and fix any errors**

Run:

```bash
cd frontend && npx tsc --noEmit
```

Expected errors after this step:
- `BookmarkList.tsx` — references to `onBookmarkPreview` in the body (lines 442-446, 722-736) are now broken because the destructure dropped the name. **These get fixed in Task 3** — they should appear as "Cannot find name 'onBookmarkPreview'" or similar.

To unblock the type-check while leaving Task 3's content intact, temporarily comment out (or `// @ts-expect-error` ) the two body sites that reference `onBookmarkPreview`:

```typescript
  // Inside handleBookmarkClick (around line 442):
  // @ts-expect-error removed in Task 3
  if (!flyGps && onBookmarkPreview) {
    // @ts-expect-error removed in Task 3
    onBookmarkPreview(bm);
  } else {
    onBookmarkClick(bm);
  }
```

And around line 722:
```typescript
      {/* @ts-expect-error removed in Task 3 */}
      {onBookmarkPreview && (
```

Better alternative: skip the `@ts-expect-error` hack and accept that this task ends with one broken file. Commit Task 1 changes as `wip` and finish in Task 2.

**Recommended:** Do not commit Task 1 alone — fold it into Task 2's commit. Mark Task 1 done on the checklist, but keep the working tree dirty until Task 2's type-check passes. (Task 2 is small, and a single commit "feat: bookmark right-click jump-mode menu (plumbing + menu UI)" is more readable than two commits where one breaks the build.)

- [ ] **Step 10: Do not commit yet**

Proceed to Task 2 with the working tree dirty.

---

## Task 2: Replace BookmarkList's context menu with the unified menu

**Why this size:** The menu replacement is one cohesive change — splitting it would leave the codebase in a half-built state. The body is ~120 lines but it's all linear JSX siblings with no shared logic.

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx`
  - Add reverseGeo state near line 196 (next to the existing `contextMenu` state)
  - Replace the entire portal-rendered menu JSX (currently lines 1480–1596)

- [ ] **Step 1: Add reverseGeo state alongside the existing contextMenu state**

In `BookmarkList.tsx`, find line 196:

```typescript
  const [contextMenu, setContextMenu] = useState<{ bm: Bookmark; x: number; y: number } | null>(null);
```

Add the following directly below (becomes line 197):

```typescript
  // Reverse-geocode state for the menu's coords header. Reset whenever
  // the menu closes — see the dismissal useEffect below.
  const [reverseGeo, setReverseGeo] = useState<{
    loading: boolean; address: string | null; error: string | null;
    key: string; // lat|lng the result belongs to
  }>({ loading: false, address: null, error: null, key: '' });
```

- [ ] **Step 2: Clear reverseGeo when the menu is dismissed**

Find the dismissal `useEffect` block at line 280–303 (the one starting `if (!contextMenu) return;`). In its **cleanup function** (currently `return () => { clearTimeout(id); document.removeEventListener('pointerdown', onOutside); document.removeEventListener('contextmenu', onOutside); document.removeEventListener('keydown', onEsc); };`), add a line to reset reverseGeo when the menu becomes null. The simplest fix: add a second `useEffect` right after the existing one:

```typescript
  // Drop any in-flight or completed reverse-geocode result when the
  // menu closes, so a stale address from a previous right-click can
  // never leak into a new lookup.
  useEffect(() => {
    if (!contextMenu) {
      setReverseGeo({ loading: false, address: null, error: null, key: '' });
    }
  }, [contextMenu]);
```

- [ ] **Step 3: Replace the menu portal body**

Find the menu block at line 1480 (`{contextMenu && createPortal(`). Replace the entire block from line 1480 through to the closing `document.body,\n      )}\n` (around line 1596) with the following. The block is long — paste it as one unit.

```typescript
      {/* Context menu (dismissed via document click listener — see useEffect) */}
      {contextMenu && createPortal(
        <>
          <div
            data-bookmark-context-menu
            style={{
              position: 'fixed',
              // Clamp to viewport so the menu never falls off-screen.
              left: Math.min(contextMenu.x, window.innerWidth - 200),
              top: Math.min(contextMenu.y, window.innerHeight - 360),
              zIndex: 9999,
              background: 'rgba(26, 29, 39, 0.95)',
              backdropFilter: 'blur(10px)',
              WebkitBackdropFilter: 'blur(10px)',
              border: '1px solid rgba(108, 140, 255, 0.18)',
              borderRadius: 10,
              padding: '4px 0',
              boxShadow: '0 10px 32px rgba(12, 18, 40, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.04) inset',
              minWidth: 180,
              maxWidth: 'calc(100vw - 16px)',
              maxHeight: 'calc(100vh - 16px)',
              overflow: 'auto',
            }}
          >
            {/* 1. Coords header — clickable to trigger reverse-geocode. */}
            <div
              style={{
                padding: '8px 16px 6px',
                color: '#9ac0ff',
                fontSize: 12,
                fontFamily: 'monospace',
                display: 'flex',
                alignItems: 'center',
                cursor: 'pointer',
                gap: 4,
              }}
              title={t('map.whats_here_tooltip')}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={async (e) => {
                e.stopPropagation();
                const key = `${contextMenu.bm.lat.toFixed(6)}|${contextMenu.bm.lng.toFixed(6)}`;
                if (reverseGeo.loading && reverseGeo.key === key) return;
                if (reverseGeo.address && reverseGeo.key === key) return;
                setReverseGeo({ loading: true, address: null, error: null, key });
                try {
                  const res = await reverseGeocode(contextMenu.bm.lat, contextMenu.bm.lng);
                  const name = res?.display_name || res?.address || null;
                  if (name) {
                    setReverseGeo({ loading: false, address: name, error: null, key });
                  } else {
                    setReverseGeo({ loading: false, address: null, error: t('map.whats_here_empty'), key });
                  }
                } catch (err: any) {
                  setReverseGeo({ loading: false, address: null, error: err?.message || 'error', key });
                }
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 4, opacity: 0.8 }}>
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              <span style={{ flex: 1 }}>{contextMenu.bm.lat.toFixed(6)}, {contextMenu.bm.lng.toFixed(6)}</span>
              <span style={{ fontSize: 10, opacity: 0.7, fontFamily: 'inherit' }}>
                {reverseGeo.loading && reverseGeo.key === `${contextMenu.bm.lat.toFixed(6)}|${contextMenu.bm.lng.toFixed(6)}`
                  ? t('map.whats_here_loading')
                  : t('map.whats_here')}
              </span>
            </div>
            {/* Reverse-geocode result or error, shown only after the user taps the header row. */}
            {reverseGeo.key === `${contextMenu.bm.lat.toFixed(6)}|${contextMenu.bm.lng.toFixed(6)}` &&
             (reverseGeo.address || reverseGeo.error) && (
              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  padding: '2px 16px 8px',
                  color: reverseGeo.error ? '#ff8a80' : '#d0d0d0',
                  fontSize: 11.5,
                  lineHeight: 1.5,
                  userSelect: 'text',
                  cursor: 'text',
                  wordBreak: 'break-word',
                }}
              >
                {reverseGeo.address ?? reverseGeo.error}
              </div>
            )}
            <div style={{ height: 1, background: '#444', margin: '2px 0 4px' }} />

            {/* 2 + 3. Teleport / Navigate (device-gated). */}
            {deviceConnected ? (
              <>
                <div
                  style={ctxItemStyle}
                  onMouseEnter={ctxHighlight}
                  onMouseLeave={ctxUnhighlight}
                  onClick={() => {
                    onTeleport(contextMenu.bm.lat, contextMenu.bm.lng);
                    setContextMenu(null);
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="2" x2="12" y2="6" />
                    <line x1="12" y1="18" x2="12" y2="22" />
                    <line x1="2" y1="12" x2="6" y2="12" />
                    <line x1="18" y1="12" x2="22" y2="12" />
                  </svg>
                  {t('map.teleport_here')}
                </div>
                <div
                  style={ctxItemStyle}
                  onMouseEnter={ctxHighlight}
                  onMouseLeave={ctxUnhighlight}
                  onClick={() => {
                    onNavigate(contextMenu.bm.lat, contextMenu.bm.lng);
                    setContextMenu(null);
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <polygon points="3,11 22,2 13,21 11,13" />
                  </svg>
                  {t('map.navigate_here')}
                </div>
              </>
            ) : (
              <div
                style={{ ...ctxItemStyle, color: '#ff6b6b', cursor: 'not-allowed', opacity: 0.75 }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <circle cx="12" cy="12" r="10" />
                  <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
                </svg>
                {t('map.device_disconnected')}
              </div>
            )}

            {/* 4. Set as Gold Ditto A (always wired in practice). */}
            {onSetAsGoldDittoA && (
              <div
                style={ctxItemStyle}
                onMouseEnter={ctxHighlight}
                onMouseLeave={ctxUnhighlight}
                onClick={() => {
                  onSetAsGoldDittoA(contextMenu.bm.lat, contextMenu.bm.lng);
                  setContextMenu(null);
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <path d="M12 2 L13.5 9 L21 12 L13.5 15 L12 22 L10.5 15 L3 12 L10.5 9 Z" />
                </svg>
                {t('goldditto.set_as_a')}
              </div>
            )}

            {/* 5. Add as Waypoint (only in a route mode). */}
            {showWaypointOption && onAddWaypoint && (
              <div
                style={ctxItemStyle}
                onMouseEnter={ctxHighlight}
                onMouseLeave={ctxUnhighlight}
                onClick={() => {
                  onAddWaypoint(contextMenu.bm.lat, contextMenu.bm.lng);
                  setContextMenu(null);
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <circle cx="12" cy="12" r="3" />
                  <line x1="12" y1="5" x2="12" y2="1" />
                  <line x1="12" y1="23" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="1" y2="12" />
                  <line x1="23" y1="12" x2="19" y2="12" />
                </svg>
                {t('map.add_waypoint')}
              </div>
            )}

            <div style={{ height: 1, background: '#444', margin: '4px 0' }} />

            {/* 6. Edit. */}
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                const bm = contextMenu.bm;
                setEditDialog(bm);
                setEditDialogName(bm.name);
                setEditDialogLat(bm.lat.toString());
                setEditDialogLng(bm.lng.toString());
                setContextMenu(null);
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              {t('bm.edit')}
            </div>

            {/* 7. Copy (name + lat/lng). */}
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={async () => {
                const text = `${contextMenu.bm.name} ${contextMenu.bm.lat.toFixed(6)}, ${contextMenu.bm.lng.toFixed(6)}`;
                try {
                  await navigator.clipboard.writeText(text);
                } catch {
                  const ta = document.createElement('textarea');
                  ta.value = text;
                  document.body.appendChild(ta);
                  ta.select();
                  try { document.execCommand('copy'); } catch { /* ignore */ }
                  document.body.removeChild(ta);
                }
                if (onShowToast) onShowToast(t('map.coords_copied'));
                setContextMenu(null);
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              </svg>
              {t('bm.copy')}
            </div>

            {/* 8. Delete. */}
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                if (contextMenu.bm.id) onBookmarkDelete(contextMenu.bm.id);
                setContextMenu(null);
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f44336" strokeWidth="2" style={{ marginRight: 6 }}>
                <polyline points="3,6 5,6 21,6" />
                <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
              </svg>
              <span style={{ color: '#f44336' }}>{t('generic.delete')}</span>
            </div>

            {/* 9. Move to category (only when more than one category exists). */}
            {categories.length > 1 && (
              <>
                <div style={{ height: 1, background: '#444', margin: '4px 0' }} />
                <div style={{ padding: '4px 12px', fontSize: 10, opacity: 0.5 }}>{t('bm.move_to')}</div>
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                  {categories
                    .filter((c) => c !== contextMenu.bm.category)
                    .map((cat) => (
                      <div
                        key={cat}
                        style={ctxItemStyle}
                        onMouseEnter={ctxHighlight}
                        onMouseLeave={ctxUnhighlight}
                        onClick={() => {
                          if (contextMenu.bm.id) {
                            onBookmarkEdit(contextMenu.bm.id, { category: cat });
                          }
                          setContextMenu(null);
                        }}
                      >
                        <div
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            background: resolveColor(cat),
                            marginRight: 6,
                          }}
                        />
                        {displayCat(cat)}
                      </div>
                    ))}
                </div>
              </>
            )}
          </div>
        </>,
        document.body,
      )}
```

Notes:
- The Edit / Copy / Delete / Move-to bodies are copied verbatim from the previous menu (same identifiers: `setEditDialog`, `setEditDialogName`, `setEditDialogLat`, `setEditDialogLng`, `onBookmarkDelete`, `onBookmarkEdit`, `resolveColor`, `displayCat`, `categories`). Do not refactor them in this task.
- Existing helpers `ctxItemStyle`, `ctxHighlight`, `ctxUnhighlight` are reused — they should already be defined in the file (search for them — they are defined either near the bottom or as `const ctxItemStyle = { ... }` earlier in the file). If they are not defined (only the map menu has equivalents named `contextMenuItemStyle`/`highlightItem`), grep for the current usages first:

  ```bash
  cd /Users/raviwu/personal/locwarp && grep -n "ctxItemStyle\|ctxHighlight\|ctxUnhighlight" frontend/src/components/BookmarkList.tsx | head -10
  ```

  If they exist (current menu already uses them), nothing to do. If they don't exist (they were just rendered inline in the prior version — re-check), add them above the component as:

  ```typescript
  const ctxItemStyle: React.CSSProperties = {
    padding: '8px 16px',
    cursor: 'pointer',
    color: '#e0e0e0',
    fontSize: 13,
    display: 'flex',
    alignItems: 'center',
    transition: 'background 0.15s',
  };

  function ctxHighlight(e: React.MouseEvent<HTMLDivElement>) {
    (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
  }

  function ctxUnhighlight(e: React.MouseEvent<HTMLDivElement>) {
    (e.currentTarget as HTMLDivElement).style.background = 'transparent';
  }
  ```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: errors only for the still-referenced `onBookmarkPreview` and `flyGps` symbols (lines 442-446 and 722-736). All other errors should be resolved. If you see "Cannot find name 'reverseGeocode'", recheck Task 1 Step 3.

- [ ] **Step 5: Do not commit yet**

Proceed to Task 3 with working tree dirty.

---

## Task 3: Remove fly-GPS toggle (state, UI, branch) and `onBookmarkPreview`

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (state at lines 235-248, branch at 438-452, UI at 719-736)

- [ ] **Step 1: Remove the flyGps state declaration**

In `BookmarkList.tsx`, find lines 235-248 (the comment "Click also flies GPS toggle persisted in localStorage" plus the `useState` and setter). Delete the entire block:

```typescript
  // "Click also flies GPS" toggle persisted in localStorage so the choice
  // survives restart. Default true = legacy behavior (clicking a bookmark
  // teleports iPhone). When false, click only pans the map view (preview).
  const [flyGps, setFlyGpsRaw] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem('locwarp.bookmark_fly_gps');
      // Default to true unless the user has explicitly stored '0'.
      return v === null ? true : v === '1';
    } catch { return true; }
  });
  const setFlyGps = (v: boolean) => {
    setFlyGpsRaw(v);
    try { localStorage.setItem('locwarp.bookmark_fly_gps', v ? '1' : '0'); } catch { /* ignore */ }
  };
```

- [ ] **Step 2: Simplify handleBookmarkClick**

In `BookmarkList.tsx`, find `handleBookmarkClick` at line 438. The current body is:

```typescript
  const handleBookmarkClick = (bm: Bookmark) => {
    const now = Date.now();
    if (now - lastClickTs.current < 150) return;
    lastClickTs.current = now;
    if (!flyGps && onBookmarkPreview) {
      onBookmarkPreview(bm);
    } else {
      onBookmarkClick(bm);
    }
    if (bm.id) {
      setFlashedBmId(bm.id);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlashedBmId(null), 500);
    }
  };
```

Replace the entire function body with:

```typescript
  const handleBookmarkClick = (bm: Bookmark) => {
    const now = Date.now();
    if (now - lastClickTs.current < 150) return;
    lastClickTs.current = now;
    onBookmarkClick(bm);
    if (bm.id) {
      setFlashedBmId(bm.id);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlashedBmId(null), 500);
    }
  };
```

- [ ] **Step 3: Remove the fly-GPS checkbox UI block**

In `BookmarkList.tsx`, find lines 719-736 (the `{/* Click-also-flies-GPS toggle. Only useful when ... */}` comment plus the `{onBookmarkPreview && (` JSX block). Delete the entire block, including the surrounding blank line if any:

```typescript
      {/* Click-also-flies-GPS toggle. Only useful when the parent wires up
          the camera-only preview path; otherwise hide so the checkbox
          doesn't look like a no-op. */}
      {onBookmarkPreview && (
        <label
          className="lw-checkbox"
          title={t('bm.fly_gps_tooltip')}
          style={{ display: 'flex', marginTop: 6, fontSize: 11.5 }}
        >
          <input
            type="checkbox"
            checked={flyGps}
            onChange={(e) => setFlyGps(e.target.checked)}
          />
          <span className="lw-checkbox-box"></span>
          <span className="lw-checkbox-label">{t('bm.fly_gps')}</span>
        </label>
      )}
```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean. No errors. If errors remain, they will point to stragglers — search:

```bash
cd /Users/raviwu/personal/locwarp && grep -n "flyGps\|onBookmarkPreview\|bookmark_fly_gps" frontend/src/components/BookmarkList.tsx
```

The only acceptable remaining hit is none. Fix each remaining reference by deleting it.

- [ ] **Step 5: Commit the combined Task 1-2-3 changes**

```bash
cd /Users/raviwu/personal/locwarp && git add frontend/src/App.tsx frontend/src/components/ControlPanel.tsx frontend/src/components/BookmarkList.tsx && git status
```

Verify the only changed files are those three, then commit:

```bash
git commit -m "$(cat <<'EOF'
feat(bookmark): right-click menu parity with map/history + drop fly-GPS toggle

Add Teleport / Navigate / Set as Gold A / Add Waypoint (route modes only) plus
the coords header + What's-here reverse-geocode to the bookmark right-click
menu, matching the map and history right-click menus. Remove the click-also-
flies-GPS checkbox: bookmark left-click is now always a map pan-only preview.
All GPS jump actions are reached via right-click.

Spec: docs/superpowers/specs/2026-05-24-bookmark-context-menu-design.md
EOF
)"
```

---

## Task 4: Delete obsolete i18n keys

**Files:**
- Modify: `frontend/src/i18n/strings.ts` (lines 610-611)

- [ ] **Step 1: Delete the two unused keys**

Open `frontend/src/i18n/strings.ts`. Find lines 610-611:

```typescript
  'bm.fly_gps': { zh: '點擊也要飛 GPS (取消打勾則只飛畫面)', en: 'Click also flies GPS (uncheck to only pan the map)' },
  'bm.fly_gps_tooltip': { zh: '打勾:點座標會把 iPhone 瞬移過去 (預設)。取消打勾:只把畫面飛過去看看,不影響 iPhone 定位。', en: 'When ticked, clicking a bookmark teleports iPhone GPS (default). When unticked, only the map view pans there; iPhone GPS stays put.' },
```

Delete both lines.

- [ ] **Step 2: Confirm nothing else references those keys**

```bash
cd /Users/raviwu/personal/locwarp && grep -rn "bm\.fly_gps\|bm\.fly_gps_tooltip" frontend/src/
```

Expected: no output. If anything is still referencing them, return to Task 3 and remove that consumer first.

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd /Users/raviwu/personal/locwarp && git add frontend/src/i18n/strings.ts && git commit -m "i18n: drop bm.fly_gps + bm.fly_gps_tooltip (toggle removed)"
```

---

## Task 5: Manual smoke test

**Why:** There are no automated tests for this UI surface. Visual verification is the only way to catch a regression here. The CLAUDE.md `Working directories` block specifies `cd frontend && npx vite --host --port 5173` for browser dev.

- [ ] **Step 1: Start the backend and frontend**

Per `CLAUDE.md`:

```bash
# Terminal 1 — backend
cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python main.py
```

```bash
# Terminal 2 — frontend
cd /Users/raviwu/personal/locwarp/frontend && npx vite --host --port 5173
```

Open `http://localhost:5173` in a browser.

- [ ] **Step 2: Walk the verification checklist**

For each item below, perform the action and tick the checkbox. If any item fails, do **not** mark Task 5 complete — file the deviation, fix, re-test.

**Without a device connected:**
- [ ] Bookmark left-click pans the map to the bookmark (no toast, no teleport, no preview pin? — actually `handleMapPanOnly` does set a preview pin; verify pin appears at the bookmark location).
- [ ] Bookmark right-click opens the new menu.
- [ ] Coords header shows lat/lng with 6-decimal precision and "what's here" hint.
- [ ] Clicking the header triggers reverse-geocode (loading → address or error within ~5s).
- [ ] Teleport / Navigate row is replaced by a single red "Device disconnected" placeholder.
- [ ] Edit opens the edit dialog with prefilled name/lat/lng.
- [ ] Copy puts "<name> <lat>, <lng>" on the clipboard (paste into a textfield to confirm).
- [ ] Delete prompts (existing behavior) and removes the bookmark.
- [ ] Move to <category> reassigns the bookmark and the menu closes.
- [ ] ESC closes the menu; clicking outside closes the menu.

**With a device connected:**
- [ ] Right-click → Teleport jumps the simulated GPS to the bookmark.
- [ ] Right-click → Navigate triggers route navigation.
- [ ] Right-click → "Set as Gold Ditto A" populates the Gold Ditto panel A field.

**In a route mode (Loop / MultiStop / Navigate):**
- [ ] "Add as Waypoint" row appears in the menu.
- [ ] Clicking it appends the bookmark as a waypoint.

**Out of any route mode (e.g. SimMode.Teleport):**
- [ ] "Add as Waypoint" row is absent.

**Multi-select mode:**
- [ ] Right-click on a bookmark row while multi-select is active does NOT open the menu (preserves the existing behavior — line 1098, 1283 already short-circuits `handleContextMenu`).

**Fly-GPS toggle removed:**
- [ ] The "Click also flies GPS" checkbox is gone from the bookmark panel header.
- [ ] No console error mentioning `bm.fly_gps` or `flyGps`.

**Sort orders:**
- [ ] Bookmark sort by Default / Name / Date Added / Last Used works as before (this change does not alter sort logic).

- [ ] **Step 3: Stop the dev servers**

Ctrl-C both terminals. If anything failed, debug and recommit before considering the plan done.

---

## Self-Review checklist (already run by the planner)

1. **Spec coverage:**
   - Spec §4.1 (menu layout): Task 2.
   - Spec §4.2 (left-click simplification): Task 3 + App-level swap in Task 1 Step 8.
   - Spec §4.3 (no `last_used_at` change): no task — verified by absence.
   - Spec §4.4 (BookmarkList props delta): Tasks 1-2.
   - Spec §4.5 (reverseGeo state ownership): Task 2 Step 1-2.
   - Spec §4.6 (ESC dismissal): no change required.
   - Spec §5 (implementation outline): tasks 1-5 cover.
   - Spec §6 (testing): Task 5.
   - Spec §7 (rollout): direct commit to main, no flag — covered by commit cadence in tasks.
2. **Placeholders:** None. All steps contain executable commands or paste-ready code.
3. **Type consistency:** Prop names (`onTeleport`, `onNavigate`, `onSetAsGoldDittoA`, `onAddWaypoint`, `deviceConnected`, `showWaypointOption`, `onShowToast`) match across BookmarkList interface (Task 1.1), BookmarkList destructure (Task 1.2), ControlPanel interface (Task 1.4), ControlPanel destructure (Task 1.5), ControlPanel→BookmarkList JSX (Task 1.6), App→ControlPanel JSX (Task 1.7), and Task 2 menu consumption.
