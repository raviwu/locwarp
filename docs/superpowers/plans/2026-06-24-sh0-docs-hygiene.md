# SH0 — Docs & Repo Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the clean-arch status blocks and ring inventories in `CLAUDE.md` / `AGENTS.md` / the refactor design spec into line with reality (P0–P5 all merged), and commit the two untracked clean-arch plan files — so every future agent session reads correct guidance.

**Architecture:** Pure documentation + repo-hygiene batch. No code changes, no runtime risk. Each task is a precise find→replace verified by grep, plus a final automated-gate + manual-doc smoke check.

**Tech Stack:** Markdown, git.

## Global Constraints

- Personal repo: ships as **direct commits to `main`**, identity auto-set by `~/.gitconfig` includeIf — never pass `-c user.email=...`.
- Doc-only batch: the backend pytest suite (**914 collected**) and frontend vitest suite are untouched; run them once at batch end purely to prove no accidental code change.
- Source of truth for current clean-arch status: memory note `project_clean_arch_refactor_status.md` ("P0–P5 ALL complete, merged to main 2026-06-23").
- Keep `CLAUDE.md` and `AGENTS.md` in sync (they intentionally mirror each other).

---

### Task 1: Un-stale the clean-arch status block (X1)

**Why:** The status block says "Phase 4a … pending real-data smoke + merge … Phase 4b + Phase 5 deferred. Do not start P4b / Phase 5 without explicit approval." But `git log` shows all P4b (`p4b2bii…`) and P5 (`refactor(p5)…`) commits are merged to `main`. This block is `@`-imported into every Claude session and will make future agents refuse legitimate follow-up work or redo merged work.

**Files:**
- Modify: `CLAUDE.md:11`
- Modify: `AGENTS.md:11`
- Modify: `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md:4`

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Confirm the stale strings are present**

```bash
cd /Users/raviwu/personal/locwarp
grep -n "Do not start P4b / Phase 5" CLAUDE.md AGENTS.md
grep -n "pending real-data smoke + merge" CLAUDE.md AGENTS.md docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md
git log --oneline --all | grep -iE "refactor\(p5\)|p4b2bii" | head -3   # proves P4b/P5 merged
```
Expected: grep finds the stale phrases on `CLAUDE.md:11`, `AGENTS.md:11`, spec line 4; git log shows the p5 / p4b2bii commits.

- [ ] **Step 2: Replace the `CLAUDE.md:11` status block**

Replace the entire line 11 (the `**Status (2026-06-22):** …` paragraph ending in `… without explicit approval from Ravi.`) with:

```markdown
**Status (2026-06-23):** Clean-arch phases **P0–P5 all merged to `main`** (2026-06-23). Inward-only rings enforced; **seven import-linter contracts ENFORCED (`7 kept, 0 broken`)** plus the frontend dependency-cruiser gate (`0 errors`). P3 carved `domain/movement.py` (EtaTracker + `build_resume_snapshot` + RouteInterpolator). P4a inverted bookmark/route file-I/O behind `BookmarkRepository`/`RouteRepository` ports (`infra/persistence/json_store.py` built ONLY at the composition root — services never import infra; `merge_stores` lives in `domain/store_merge.py`, shim in services; shared `force_seed_items` primitive encodes the empty-`updated_at` pitfall). P4b decomposed the frontend god-components (MapView per-layer hooks, popovers/menus, shared primitives under `components/` + `hooks/` + `adapters/`). P5 added the fail-on-probe CI gates (import-linter + dependency-cruiser) and the single-origin/port cleanup. Watcher/lock/mtime stay on the managers; **no RouteManager lock**. Current status of record: memory note `project_clean_arch_refactor_status.md`.
```

- [ ] **Step 3: Replace the `AGENTS.md:11` status block**

Replace the entire line 11 (same stale paragraph) with the identical text from Step 2, except change the trailing sentence to drop the Claude-only memory reference (AGENTS.md is tool-agnostic):

```markdown
**Status (2026-06-23):** Clean-arch phases **P0–P5 all merged to `main`** (2026-06-23). Inward-only rings enforced; **seven import-linter contracts ENFORCED (`7 kept, 0 broken`)** plus the frontend dependency-cruiser gate (`0 errors`). P3 carved `domain/movement.py` (EtaTracker + `build_resume_snapshot` + RouteInterpolator). P4a inverted bookmark/route file-I/O behind `BookmarkRepository`/`RouteRepository` ports (`infra/persistence/json_store.py` built ONLY at the composition root — services never import infra; `merge_stores` lives in `domain/store_merge.py`, shim in services; shared `force_seed_items` primitive encodes the empty-`updated_at` pitfall). P4b decomposed the frontend god-components (MapView per-layer hooks, popovers/menus, shared primitives under `components/` + `hooks/` + `adapters/`). P5 added the fail-on-probe CI gates (import-linter + dependency-cruiser) and the single-origin/port cleanup. Watcher/lock/mtime stay on the managers; **no RouteManager lock**.
```

- [ ] **Step 4: Replace the spec line 4 Status bullet**

In `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md`, replace the `- **Status:** …` bullet (line 4) with:

```markdown
- **Status:** **P0–P5 all merged to `main` (2026-06-23).** This is a historical design doc; current clean-arch status of record lives in `CLAUDE.md` / `AGENTS.md` and memory note `project_clean_arch_refactor_status.md`.
```

- [ ] **Step 5: Verify the stale guidance is gone**

```bash
cd /Users/raviwu/personal/locwarp
grep -rn "Do not start P4b" CLAUDE.md AGENTS.md && echo "STILL STALE" || echo "OK: guard removed"
grep -rn "pending real-data smoke" CLAUDE.md AGENTS.md docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md && echo "STILL STALE" || echo "OK"
grep -n "P0–P5 all merged" CLAUDE.md AGENTS.md
```
Expected: `OK: guard removed`, `OK`, and the new "P0–P5 all merged" line present in both files.

- [ ] **Step 6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add CLAUDE.md AGENTS.md docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md
git commit -m "docs(sh0): un-stale clean-arch status — P0–P5 all merged (X1)"
```

---

### Task 2: Add `backup.py` + `store_merge.py` to the domain-ring inventory (X3)

**Why:** The backend-rings inventory line lists `domain/ (pure: models, events.py, movement.py, errors.py, ports/)` but omits `domain/backup.py` and `domain/store_merge.py`, both of which exist and are referenced elsewhere in the same file (`CLAUDE.md:71,102`).

**Files:**
- Modify: `CLAUDE.md:16`
- Modify: `AGENTS.md:17`

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Confirm the incomplete inventory line**

```bash
cd /Users/raviwu/personal/locwarp
grep -n "domain/\` (pure" CLAUDE.md AGENTS.md
ls backend/domain/backup.py backend/domain/store_merge.py   # both exist
```
Expected: the inventory line is found (CLAUDE.md:16, AGENTS.md:17); both domain files exist.

- [ ] **Step 2: Edit `CLAUDE.md:16`**

Replace `→ \`domain/\` (pure: models, \`events.py\`, \`movement.py\`, \`errors.py\`, \`ports/\`).` with:

```markdown
→ `domain/` (pure: models, `events.py`, `movement.py`, `errors.py`, `store_merge.py`, `backup.py`, `ports/`).
```

- [ ] **Step 3: Edit `AGENTS.md:17`**

Replace `→ \`domain/\` (pure: \`models/\`, \`events.py\`, \`movement.py\`, \`errors.py\`, \`ports/\`).` with:

```markdown
→ `domain/` (pure: `models/`, `events.py`, `movement.py`, `errors.py`, `store_merge.py`, `backup.py`, `ports/`).
```

- [ ] **Step 4: Verify**

```bash
cd /Users/raviwu/personal/locwarp
grep -n "store_merge.py\`, \`backup.py\`, \`ports/\`" CLAUDE.md AGENTS.md
```
Expected: both files show the updated inventory line.

- [ ] **Step 5: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add CLAUDE.md AGENTS.md
git commit -m "docs(sh0): list domain/store_merge.py + backup.py in ring inventory (X3)"
```

---

### Task 3: Clarify the managers' ring placement (X2)

**Why:** The audit flagged that the docs can read as if `BookmarkManager` / `RouteManager` live in the `core/` ring; they are `services/`-ring stateful adapters in `services/bookmarks.py` and `services/route_store.py` (there are no `*_manager.py` files). The CRDT section (`CLAUDE.md:71`) talks about "the managers" without naming their ring or files.

**Files:**
- Modify: `CLAUDE.md:71` (CRDT semantics section)

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Confirm no line misplaces the managers in `core/`, and locate the CRDT section**

```bash
cd /Users/raviwu/personal/locwarp
grep -n "core/.*[Mm]anager\|[Mm]anager.*core/" CLAUDE.md AGENTS.md || echo "OK: no explicit core/ misattribution"
grep -n "the managers keep CRUD" CLAUDE.md
ls backend/services/bookmarks.py backend/services/route_store.py   # the real homes
```
Expected: no explicit `core/`-manager misattribution; the CRDT sentence is at `CLAUDE.md:71`; both service files exist. (If Step 1 *does* surface a `core/`-manager line, replace `core/` with `services/` there and skip to Step 3.)

- [ ] **Step 2: Add an explicit ring + file clarification to the CRDT section**

In `CLAUDE.md:71`, the sentence currently reads `… the managers keep CRUD + the watcher + \`_store_lock\` + mtime and call the repo for disk ops.` Replace that clause with:

```markdown
… the managers — `BookmarkManager` (`backend/services/bookmarks.py`) and `RouteManager` (`backend/services/route_store.py`), both **`services/`-ring** stateful adapters (there are no `*_manager.py` files) — keep CRUD + the watcher + `_store_lock` + mtime and call the repo for disk ops.
```

- [ ] **Step 3: Verify**

```bash
cd /Users/raviwu/personal/locwarp
grep -n "services/\`-ring\*\* stateful adapters" CLAUDE.md
```
Expected: the clarified sentence is present.

- [ ] **Step 4: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add CLAUDE.md
git commit -m "docs(sh0): name the managers' services-ring + real files in CRDT section (X2)"
```

---

### Task 4: Commit the two untracked clean-arch plan files (X4)

**Why:** `docs/superpowers/plans/2026-06-22-clean-arch-p3-carve-movement-math.md` and `…-p4a-repository-around-crdt-store.md` show as untracked (`??`) while every other P-series plan is committed; `git log --all` has no history for them.

**Files:**
- (No content change — adding existing files to git.)

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Confirm they are untracked with no history**

```bash
cd /Users/raviwu/personal/locwarp
git status --short docs/superpowers/plans/2026-06-22-clean-arch-p3-carve-movement-math.md docs/superpowers/plans/2026-06-22-clean-arch-p4a-repository-around-crdt-store.md
git log --oneline --all -- docs/superpowers/plans/2026-06-22-clean-arch-p4a-repository-around-crdt-store.md | head -1 || true
```
Expected: both files show `??`; `git log` output is empty.

- [ ] **Step 2: Commit them**

```bash
cd /Users/raviwu/personal/locwarp
git add docs/superpowers/plans/2026-06-22-clean-arch-p3-carve-movement-math.md \
        docs/superpowers/plans/2026-06-22-clean-arch-p4a-repository-around-crdt-store.md
git commit -m "docs(sh0): track the p3 + p4a clean-arch plan files (X4)"
```

- [ ] **Step 3: Verify**

```bash
cd /Users/raviwu/personal/locwarp
git status --short | grep -E "clean-arch-p3|clean-arch-p4a" && echo "STILL UNTRACKED" || echo "OK: tracked"
git log --oneline -1 -- docs/superpowers/plans/2026-06-22-clean-arch-p4a-repository-around-crdt-store.md
```
Expected: `OK: tracked`; `git log` now shows the commit.

---

### Task 5: Automated gate + manual doc smoke (SH0 acceptance)

**Files:** none.

**Interfaces:**
- Consumes: Tasks 1–4
- Produces: none

- [ ] **Step 1: Prove no code was changed (automated gate)**

```bash
cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q
cd /Users/raviwu/personal/locwarp/frontend && npx vitest run
```
Expected: backend 914 passed; frontend vitest all green. (Doc-only batch — these must be unchanged from baseline.)

- [ ] **Step 2: Manual doc smoke (user-verifiable)**

Open `CLAUDE.md` and `AGENTS.md` and read the clean-arch section near the top.
- Expected: the status reads "P0–P5 all merged"; there is **no** "Do not start P4b / Phase 5" guard.
- Expected: the ring inventory lists `store_merge.py` and `backup.py` under `domain/`.
- Expected: the CRDT section names `BookmarkManager`/`RouteManager` as `services/`-ring with their real file paths.

Then:
```bash
cd /Users/raviwu/personal/locwarp
git status --short        # clean tree
git log --oneline -5      # SH0 commits present
```
- Expected: clean working tree; the four SH0 commits are in history; the p3/p4a plan files no longer appear as `??`.

**SH0 acceptance:** docs read correctly; tree clean; automated gate unchanged-green.
