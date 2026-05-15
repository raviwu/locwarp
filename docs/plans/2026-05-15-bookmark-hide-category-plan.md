# Bookmark Hide-Category + Move-To Scrollbar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user temporarily hide bookmark categories from the panel (with a "N hidden" unhide row), and give the context-menu "move to category" list a scrollbar.

**Architecture:** A new per-device `bookmark_hidden_categories` list mirrors the existing `bookmark_expanded_categories` — persisted in `~/.locwarp/settings.json` via the `/api/bookmarks/ui-state` endpoint, which becomes a per-field partial update so sending `hidden_categories` never clobbers `expanded_categories`. `BookmarkList.tsx` gains a `hidden` Set: a hover eye-off button on each category header adds to it, the groups loop skips it, and a collapsible "N 個已隱藏" row restores from it. The move-to fix is a pure CSS wrap (`maxHeight` + `overflowY`).

**Tech Stack:** Python 3.11 / FastAPI / Pydantic (backend), React + TypeScript (frontend), pytest. No new dependencies.

**Spec:** `docs/plans/2026-05-15-bookmark-hide-category-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/main.py` | `AppState` persisted fields | Add `_bookmark_hidden_categories` (init / `_load_settings` / `save_settings`) |
| `backend/api/bookmarks.py` | `/api/bookmarks/ui-state` endpoint | `BookmarkUiState.hidden_categories`; GET returns it; POST does per-field (`is not None`) updates |
| `backend/tests/test_bookmarks_api.py` | endpoint integration tests | New ui-state tests (isolated `SETTINGS_FILE`) |
| `frontend/src/services/api.ts` | ui-state API client | `getBookmarkUiState` / `setBookmarkUiState` carry `hidden_categories` as a partial object |
| `frontend/src/i18n/strings.ts` | i18n strings | `bm.hide_category`, `bm.unhide_category`, `bm.hidden_count` |
| `frontend/src/components/BookmarkList.tsx` | bookmark panel UI | `hidden` state + seed/persist/cleanup; header eye-off button; skip hidden groups; "N 個已隱藏" unhide row; scrollable move-to list |

**Note on cwd:** all `pytest` / `tsc` commands assume you are in `backend/` or `frontend/` respectively. The backend venv is the repo-root one: `backend/.venv/bin/python` (run from `backend/`).

---

## Task 1: Backend — `bookmark_hidden_categories` persistence + endpoint

**Files:**
- Modify: `backend/main.py` (`AppState.__init__` ~line 107, `_load_settings` ~line 164, `save_settings` ~line 237)
- Modify: `backend/api/bookmarks.py` (`BookmarkUiState` ~line 66, `get_bookmark_ui_state` ~line 255, `set_bookmark_ui_state` ~line 261)
- Test: `backend/tests/test_bookmarks_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_bookmarks_api.py`:

```python
# ── UI state: hidden categories ───────────────────────────────────────────

@pytest.fixture
def ui_state_client(tmp_path, monkeypatch):
    """TestClient with settings.json redirected to tmp_path so the ui-state
    endpoint's save_settings() does not touch the real ~/.locwarp/."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("main.SETTINGS_FILE", settings)
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    import main
    main.app_state._bookmark_expanded_categories = None
    main.app_state._bookmark_hidden_categories = None
    return TestClient(main.app)


def test_ui_state_get_returns_expanded_and_hidden(ui_state_client):
    resp = ui_state_client.get("/api/bookmarks/ui-state")
    assert resp.status_code == 200
    body = resp.json()
    assert "expanded_categories" in body
    assert "hidden_categories" in body


def test_ui_state_post_hidden_persists(ui_state_client):
    resp = ui_state_client.post(
        "/api/bookmarks/ui-state", json={"hidden_categories": ["私人", "測試"]}
    )
    assert resp.status_code == 200
    assert resp.json()["hidden_categories"] == ["私人", "測試"]
    # survives a fresh GET
    assert ui_state_client.get("/api/bookmarks/ui-state").json()["hidden_categories"] == ["私人", "測試"]


def test_ui_state_post_hidden_does_not_clobber_expanded(ui_state_client):
    ui_state_client.post("/api/bookmarks/ui-state", json={"expanded_categories": ["工作"]})
    ui_state_client.post("/api/bookmarks/ui-state", json={"hidden_categories": ["私人"]})
    body = ui_state_client.get("/api/bookmarks/ui-state").json()
    assert body["expanded_categories"] == ["工作"]
    assert body["hidden_categories"] == ["私人"]


def test_ui_state_post_expanded_does_not_clobber_hidden(ui_state_client):
    ui_state_client.post("/api/bookmarks/ui-state", json={"hidden_categories": ["私人"]})
    ui_state_client.post("/api/bookmarks/ui-state", json={"expanded_categories": ["工作"]})
    body = ui_state_client.get("/api/bookmarks/ui-state").json()
    assert body["hidden_categories"] == ["私人"]
    assert body["expanded_categories"] == ["工作"]


def test_ui_state_hidden_round_trips_through_settings(tmp_path, monkeypatch):
    """AppState writes bookmark_hidden_categories to settings.json and
    _load_settings reads it back."""
    import json
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("main.SETTINGS_FILE", settings)
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    import main
    main.app_state._bookmark_hidden_categories = ["私人", "舊資料"]
    main.app_state.save_settings()
    assert json.loads(settings.read_text())["bookmark_hidden_categories"] == ["私人", "舊資料"]
    main.app_state._bookmark_hidden_categories = None
    main.app_state._load_settings()
    assert main.app_state._bookmark_hidden_categories == ["私人", "舊資料"]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `backend/.venv/bin/python -m pytest tests/test_bookmarks_api.py -k ui_state -v`
Expected: FAIL — `hidden_categories` missing from responses; `AppState` has no `_bookmark_hidden_categories`.

- [ ] **Step 3: Add the `AppState` field**

In `backend/main.py`, after `self._bookmark_expanded_categories: list[str] | None = None` (~line 107):

```python
        self._bookmark_expanded_categories: list[str] | None = None
        # Which bookmark categories the user has temporarily hidden from the
        # panel. Per-device view preference — persisted in settings.json,
        # never iCloud-synced. None = never set.
        self._bookmark_hidden_categories: list[str] | None = None
```

In `_load_settings` (~line 164), after the `bmExp` block:

```python
            bmExp = data.get("bookmark_expanded_categories")
            if isinstance(bmExp, list):
                self._bookmark_expanded_categories = [str(x) for x in bmExp]
            bmHid = data.get("bookmark_hidden_categories")
            if isinstance(bmHid, list):
                self._bookmark_hidden_categories = [str(x) for x in bmHid]
```

In `save_settings` (~line 237), in the payload dict alongside `bookmark_expanded_categories`:

```python
            "bookmark_expanded_categories": self._bookmark_expanded_categories,
            "bookmark_hidden_categories": self._bookmark_hidden_categories,
```

- [ ] **Step 4: Extend the endpoint**

In `backend/api/bookmarks.py`, replace the `BookmarkUiState` model (~line 66):

```python
class BookmarkUiState(BaseModel):
    # Both optional: a POST updates only the fields it carries, so the
    # frontend can persist expand and hide independently without one
    # request clobbering the other.
    expanded_categories: list[str] | None = None
    hidden_categories: list[str] | None = None
```

Replace `get_bookmark_ui_state` (~line 255):

```python
@router.get("/ui-state")
async def get_bookmark_ui_state():
    from main import app_state
    return {
        "expanded_categories": app_state._bookmark_expanded_categories,
        "hidden_categories": app_state._bookmark_hidden_categories,
    }
```

Replace `set_bookmark_ui_state` (~line 261):

```python
@router.post("/ui-state")
async def set_bookmark_ui_state(req: BookmarkUiState):
    from main import app_state
    # Per-field update: only touch a field the request actually carries.
    if req.expanded_categories is not None:
        app_state._bookmark_expanded_categories = list(req.expanded_categories)
    if req.hidden_categories is not None:
        app_state._bookmark_hidden_categories = list(req.hidden_categories)
    app_state.save_settings()
    return {
        "status": "ok",
        "expanded_categories": app_state._bookmark_expanded_categories,
        "hidden_categories": app_state._bookmark_hidden_categories,
    }
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `backend/.venv/bin/python -m pytest tests/test_bookmarks_api.py -k ui_state -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/api/bookmarks.py backend/tests/test_bookmarks_api.py
git commit -m "feat(bookmark): persist bookmark_hidden_categories via per-field ui-state endpoint"
```

---

## Task 2: Frontend API client — carry `hidden_categories`

**Files:**
- Modify: `frontend/src/services/api.ts:180-184`

> No frontend unit-test harness exists in this repo (`package.json` has only a `build` script). Frontend tasks verify with `tsc --noEmit` and a browser check at the end (Task 7).

- [ ] **Step 1: Update the API client**

Replace `frontend/src/services/api.ts:180-184` with:

```typescript
// Bookmark UI state (expand/collapse + hide per category, in settings.json)
export const getBookmarkUiState = () =>
  request<{ expanded_categories: string[] | null; hidden_categories: string[] | null }>(
    'GET', '/api/bookmarks/ui-state',
  )
// Partial update: pass only the keys you want to change — sending
// hidden_categories alone never clears expanded_categories, and vice versa.
export const setBookmarkUiState = (
  state: { expanded_categories?: string[]; hidden_categories?: string[] },
) =>
  request<{ status: string; expanded_categories: string[] | null; hidden_categories: string[] | null }>(
    'POST', '/api/bookmarks/ui-state', state,
  )
```

- [ ] **Step 2: Type-check (will fail at the existing caller)**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: FAIL — `BookmarkList.tsx:372` calls `setBookmarkUiState(expanded)` with a `string[]`, no longer assignable.

- [ ] **Step 3: Fix the existing caller**

In `frontend/src/components/BookmarkList.tsx`, in `scheduleUiStateSave` (~line 372), change:

```typescript
      void setBookmarkUiState(expanded).catch(() => { /* best effort */ });
```
to:
```typescript
      void setBookmarkUiState({ expanded_categories: expanded }).catch(() => { /* best effort */ });
```

- [ ] **Step 4: Type-check passes**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean (no output).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/components/BookmarkList.tsx
git commit -m "feat(bookmark): ui-state API client carries hidden_categories (partial updates)"
```

---

## Task 3: Frontend i18n strings

**Files:**
- Modify: `frontend/src/i18n/strings.ts`

- [ ] **Step 1: Add the strings**

In `frontend/src/i18n/strings.ts`, add alongside the other `bm.*` keys (the `t()` helper interpolates `{n}` — see existing `wifi.tunnel_detect_multiple`):

```typescript
  'bm.hide_category': { zh: '隱藏此分類', en: 'Hide category' },
  'bm.unhide_category': { zh: '取消隱藏', en: 'Unhide' },
  'bm.hidden_count': { zh: '{n} 個已隱藏', en: '{n} hidden' },
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/strings.ts
git commit -m "feat(bookmark): i18n strings for hide/unhide category"
```

---

## Task 4: Frontend — `hidden` state: seed, persist, stale-cleanup

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (state decl ~line 148; load effect ~line 313-323; new helper near `scheduleUiStateSave` ~line 367)

- [ ] **Step 1: Add the `hidden` state**

In `frontend/src/components/BookmarkList.tsx`, right after `const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});` (~line 148):

```typescript
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  // Categories the user has temporarily hidden from the panel. Keyed by the
  // same category string the `collapsed` map and `bookmarksByCategory` use.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // True once the persisted hidden list has been merged in — gates the
  // persist effect so the initial fetch is not echoed straight back.
  const hiddenLoadedRef = useRef(false);
```

- [ ] **Step 2: Seed `hidden` from the persisted ui-state**

In the load effect (~line 313-323), extend the `.then` to also seed `hidden`:

```typescript
  useEffect(() => {
    let cancelled = false;
    getBookmarkUiState()
      .then((state) => {
        if (cancelled) return;
        savedExpandedRef.current = state.expanded_categories;
        if (Array.isArray(state.hidden_categories)) {
          setHidden(new Set(state.hidden_categories));
        }
        hiddenLoadedRef.current = true;
      })
      .catch(() => { hiddenLoadedRef.current = true; })
      .finally(() => { if (!cancelled) setUiStateLoaded(true); });
    return () => { cancelled = true; };
  }, []);
```

- [ ] **Step 3: Add a hidden-persistence + stale-cleanup helper**

After `scheduleUiStateSave` (~line 374), add:

```typescript
  // Persist the hidden set immediately on change (hide/unhide is a single
  // deliberate click — no debounce needed). Stale categories (deleted since
  // they were hidden) are dropped here so they never linger in settings.json.
  const persistHidden = (nextHidden: Set<string>) => {
    if (!hiddenLoadedRef.current) return; // don't echo the initial fetch
    const known = new Set(categories);
    const cleaned = [...nextHidden].filter((c) => known.has(c));
    void setBookmarkUiState({ hidden_categories: cleaned }).catch(() => { /* best effort */ });
  };

  const hideCategory = (cat: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.add(cat);
      persistHidden(next);
      return next;
    });
  };

  const unhideCategory = (cat: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.delete(cat);
      persistHidden(next);
      return next;
    });
  };
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean. (`hidden` / `hideCategory` / `unhideCategory` are defined but not yet used — TS allows unused `const`s, but if the repo's tsconfig has `noUnusedLocals`, this step's check may flag them; that is expected and resolved in Task 5. If `tsc` errors only on these unused symbols, proceed — Task 5 consumes them.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx
git commit -m "feat(bookmark): hidden-category state with seed, persist, stale-cleanup"
```

---

## Task 5: Frontend — header eye-off button + skip hidden groups

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (groups loop ~line 1106; category header ~line 1119-1196)

- [ ] **Step 1: Skip hidden categories in the groups loop**

In `frontend/src/components/BookmarkList.tsx`, change the groups loop opening (~line 1106) from:

```typescript
      {search.trim() === '' && Object.entries(bookmarksByCategory).map(([cat, bms]) => {
```
to:
```typescript
      {search.trim() === '' && Object.entries(bookmarksByCategory)
        .filter(([cat]) => !hidden.has(cat))
        .map(([cat, bms]) => {
```

- [ ] **Step 2: Add the eye-off button to the category header**

In the category header row, the count `<span>` is the last child (~line 1193-1195):

```typescript
            <span style={{ marginLeft: 'auto', opacity: 0.4, fontWeight: 400, fontSize: 10 }}>
              {bms.length}
            </span>
```

Insert the hide button immediately after that `</span>` (still inside the header `<div>` whose `onClick` is `toggleCategory`). The button's `onClick` stops propagation so it hides instead of toggling collapse:

```typescript
            <span style={{ marginLeft: 'auto', opacity: 0.4, fontWeight: 400, fontSize: 10 }}>
              {bms.length}
            </span>
            <button
              type="button"
              className="bookmark-hide-btn"
              title={t('bm.hide_category')}
              onClick={(e) => { e.stopPropagation(); hideCategory(cat); }}
              style={{
                background: 'none', border: 'none', padding: 2, marginLeft: 2,
                cursor: 'pointer', color: 'inherit', opacity: 0.55,
                display: 'inline-flex', alignItems: 'center',
              }}
            >
              {/* eye-off icon */}
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
                <line x1="1" y1="1" x2="23" y2="23" />
              </svg>
            </button>
```

- [ ] **Step 3: Make the button hover-only via CSS**

Append to `frontend/src/components/BookmarkList.tsx`'s companion stylesheet — search the repo for where `.bookmark-group` / `.bookmark-item` styles live (`grep -rn "bookmark-group" frontend/src/`). Add to that CSS file:

```css
.bookmark-hide-btn { visibility: hidden; }
.bookmark-group:hover .bookmark-hide-btn { visibility: visible; }
.bookmark-hide-btn:hover { opacity: 1 !important; }
```

If no such stylesheet exists (styles are all inline), instead make the button always faintly visible — drop this CSS step and leave the inline `opacity: 0.55` from Step 2 as-is. State which path you took in the commit message.

- [ ] **Step 4: Type-check**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx
# include the CSS file if Step 3 modified one
git commit -m "feat(bookmark): hover eye-off button hides a category from the panel"
```

---

## Task 6: Frontend — "N 個已隱藏" unhide row

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (after the groups loop closes, before the `contextMenu` portal ~line 1368)

- [ ] **Step 1: Add the collapsible unhide row**

Find where the groups `.map(...)` closes — it is the `})}` that ends the block opened in Task 5 Step 1, just before `{contextMenu && createPortal(` (~line 1368). Insert immediately before `{contextMenu && createPortal(`:

```typescript
      {/* Unhide row — only when not searching and at least one category is hidden.
          Intersect with current categories so a since-deleted category never shows. */}
      {search.trim() === '' && (() => {
        const hiddenList = categories.filter((c) => hidden.has(c));
        if (hiddenList.length === 0) return null;
        return (
          <div style={{ marginTop: 4, borderTop: '1px solid #333', paddingTop: 4 }}>
            <div
              onClick={() => setHiddenRowOpen((v) => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '5px 4px', cursor: 'pointer',
                fontSize: 11, opacity: 0.6,
              }}
            >
              <svg
                width="10" height="10" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2"
                style={{
                  transform: hiddenRowOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s',
                }}
              >
                <polyline points="9,18 15,12 9,6" />
              </svg>
              <span>{t('bm.hidden_count', { n: hiddenList.length })}</span>
            </div>
            {hiddenRowOpen && (
              <div style={{ paddingLeft: 20 }}>
                {hiddenList.map((cat) => (
                  <div
                    key={cat}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '4px 6px', fontSize: 12, opacity: 0.7,
                    }}
                  >
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: resolveColor(cat), flexShrink: 0,
                    }} />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {displayCat(cat)}
                    </span>
                    <button
                      type="button"
                      title={t('bm.unhide_category')}
                      onClick={() => unhideCategory(cat)}
                      style={{
                        background: 'none', border: 'none', padding: 2,
                        cursor: 'pointer', color: 'inherit', opacity: 0.7,
                        display: 'inline-flex', alignItems: 'center',
                      }}
                    >
                      {/* eye icon */}
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}
```

- [ ] **Step 2: Add the `hiddenRowOpen` state**

In `frontend/src/components/BookmarkList.tsx`, right after the `hidden` state added in Task 4 (~line 148-ish):

```typescript
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // Whether the "N 個已隱藏" row is expanded to show its category list.
  const [hiddenRowOpen, setHiddenRowOpen] = useState(false);
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx
git commit -m "feat(bookmark): collapsible \"N hidden\" row to restore hidden categories"
```

---

## Task 7: Frontend — scrollbar on the move-to-category list (#2)

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (context-menu "move to" block ~line 1446-1477)

- [ ] **Step 1: Wrap the category list in a scroll container**

In the `contextMenu` portal, the "move to" block (~line 1446-1477) currently is:

```typescript
            {categories.length > 1 && (
              <>
                <div style={{ height: 1, background: '#444', margin: '4px 0' }} />
                <div style={{ padding: '4px 12px', fontSize: 10, opacity: 0.5 }}>{t('bm.move_to')}</div>
                {categories
                  .filter((c) => c !== contextMenu.bm.category)
                  .map((cat) => (
                    <div
                      key={cat}
                      style={ctxItemStyle}
                      ...
```

Wrap the `.map(...)` output in a scrollable `<div>`. Change to:

```typescript
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
                        ...
                    ))}
                </div>
              </>
            )}
```

(Keep every existing prop and child of the inner `<div key={cat}>` exactly as-is — only the wrapping `<div style={{ maxHeight: 240, overflowY: 'auto' }}>` and its closing tag are added, and the `.map` block is indented one level.)

- [ ] **Step 2: Type-check**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx
git commit -m "fix(bookmark): scrollable move-to-category list in the context menu"
```

---

## Task 8: Verification — full backend suite + browser check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS — all tests, including the 5 new ui-state tests, no regressions.

- [ ] **Step 2: Frontend type-check**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Browser smoke (manual)**

Start the app (`make start` or the dev launcher). In the bookmark panel:
1. Hover a category header → the eye-off button appears → click it → the category (header + items) disappears from the list.
2. A `N 個已隱藏 ▸` row appears at the bottom → expand it → the hidden category is listed → click its eye icon → it reappears in the main list.
3. Hide a category, reload the app → it is still hidden (persisted).
4. Type in the search box → search results still include bookmarks from a hidden category.
5. Right-click a bookmark with many categories present → the "move to" list scrolls and every category is reachable.

- [ ] **Step 4: Commit any fixes**

If Steps 1-3 surfaced issues, fix and commit. Otherwise nothing to commit.

---

## Self-Review

**Spec coverage:**
- "per-device `bookmark_hidden_categories` in settings.json" → Task 1 (AppState init/load/save).
- "endpoint per-field partial update" → Task 1 (Step 4) + tests `test_ui_state_post_*_does_not_clobber_*`.
- "api.ts carries hidden, partial object" → Task 2.
- "header eye-off hide trigger, stopPropagation" → Task 5 (Step 2).
- "groups loop skips hidden" → Task 5 (Step 1).
- "N 個已隱藏 collapsible unhide row" → Task 6.
- "persist on hide/unhide, seed on mount" → Task 4 (Steps 2-3).
- "stale cleanup (intersect with current categories)" → Task 4 (`persistHidden`) + Task 6 (`hiddenList` intersect for render).
- "search unaffected" → Task 5/Task 6 both gate on `search.trim() === ''`; no search-path change — covered by Task 8 Step 3.4.
- "#2 scrollable move-to list" → Task 7.
- i18n strings → Task 3.

**Placeholder scan:** No TBD/TODO. Task 5 Step 3 has a conditional ("if no such stylesheet exists") — this is a real decision branch with both paths fully specified, not a placeholder.

**Type consistency:** `hidden: Set<string>`, `setHidden`, `hideCategory`, `unhideCategory`, `persistHidden`, `hiddenLoadedRef`, `hiddenRowOpen`, `setHiddenRowOpen` — defined in Task 4/6, consumed in Task 5/6 with matching signatures. `setBookmarkUiState({ expanded_categories?, hidden_categories? })` — defined Task 2, called in Task 2 (Step 3), Task 4 (`persistHidden`). `getBookmarkUiState` return shape `{ expanded_categories, hidden_categories }` — defined Task 2, consumed Task 4 Step 2. `t('bm.hidden_count', { n })` — string defined Task 3, used Task 6. Backend `_bookmark_hidden_categories` — defined Task 1, used by GET/POST in same task.
