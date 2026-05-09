# macOS Release Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship LocWarp as a downloadable macOS DMG (Apple Silicon, unsigned), automated via GitHub Actions on `v*` tag push.

**Architecture:** No app code changes — pure build pipeline. Stage 1 enables local Mac builds (electron-builder `dmg` target + PyInstaller for the Python backend). Stage 2 wraps the same commands in `.github/workflows/release.yml`, triggered by `git push --tags`, attaching the DMG to a GitHub Release. Code-signing and notarization are deferred to a future iteration.

**Tech Stack:** Node 20+, electron-builder, Python 3.11, PyInstaller, GitHub Actions (`macos-latest` runner), `softprops/action-gh-release@v2`.

**Spec:** Inline below — no separate spec doc. Key decisions:

- **Architecture:** `arm64`-only (no x64, no universal). Apple Silicon dominates new Macs and the maintainer's own machine.
- **Signing:** Unsigned. README will document the right-click → Open workaround.
- **Version bump:** Use `npm version minor` to go `0.2.99 → 0.3.0`, which auto-commits + tags. The tag triggers Stage 2's CI.
- **PyInstaller:** Reuse the existing `backend/locwarp-backend.spec`; it uses `collect_all` so Windows-only deps (`wintun.dll`) are handled gracefully.
- **Electron Locate-PC IPC:** Stays Windows-only. Mac users see no map "locate me" button or it errors silently. Out of scope for this plan.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `frontend/build/icon.icns` | Create | macOS app icon (1024×1024 PNG → 6 sizes inside .icns) |
| `frontend/package.json` | Modify | Add `mac` target, `dist:mac` script, productName entry |
| `backend/requirements-build.txt` | Create | PyInstaller pinned version |
| `build-installer-mac.sh` | Create | Mac equivalent of `build-installer.bat` |
| `.github/workflows/release.yml` | Create | Tag-triggered Mac DMG build + GitHub Release |
| `README.md` | Modify | Add "macOS install" section (right-click → Open workaround) |
| `README.en.md` | Modify | Same in English |

---

## Stage 1: Local macOS DMG Build

### Task 1: Generate `icon.icns` from existing PNG

**Files:**
- Modify (new): `frontend/build/icon.icns`

`iconutil` (built into macOS) needs an `.iconset` directory of pre-sized PNGs. We use `sips` (also built-in) to resize.

- [ ] **Step 1: Verify source PNG resolution**

```bash
sips -g pixelWidth -g pixelHeight /Users/raviwu/personal/locwarp/frontend/build/icon.png
```

Expected: at least 1024×1024. If smaller, stop and ask for a higher-resolution source.

- [ ] **Step 2: Generate iconset and convert to .icns**

```bash
cd /Users/raviwu/personal/locwarp/frontend/build
mkdir -p icon.iconset
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
cp icon.png icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset
rm -rf icon.iconset
ls icon.icns
```

Expected: `icon.icns` exists, ~1MB.

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/build/icon.icns
git commit -m "chore(build): add macOS .icns icon (generated from icon.png)"
```

---

### Task 2: Update `frontend/package.json` for Mac DMG

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Add `mac` target inside `build` block**

In `frontend/package.json`, the existing `build` block has only `win`. Add a `mac` sibling:

```jsonc
"mac": {
  "target": [
    { "target": "dmg", "arch": ["arm64"] }
  ],
  "category": "public.app-category.developer-tools",
  "icon": "build/icon.icns"
}
```

Place it as a sibling of the existing `win` block, inside `build`.

- [ ] **Step 2: Add `dist:mac` script**

In the `scripts` object, add:

```json
"dist:mac": "electron-builder --mac dmg"
```

- [ ] **Step 3: Update `extraResources` to bundle the Mac backend binary**

The current `extraResources` references `../dist-py/locwarp-backend` which on Mac PyInstaller will produce as a folder containing a Mach-O binary `locwarp-backend` (no `.exe`). The path stays the same. The `from`/`to` mapping should already work — verify by reading the existing block.

If the current block looks like:
```json
"extraResources": [
  { "from": "../dist-py/locwarp-backend", "to": "backend", "filter": ["**/*"] }
]
```

No change needed — Mac PyInstaller produces a folder of the same name, packaged the same way. Verify after running the actual build (Task 4).

- [ ] **Step 4: Verify TypeScript / lint still passes**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: clean. (No code change, but make sure no JSON syntax error.)

- [ ] **Step 5: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/package.json
git commit -m "build(mac): add electron-builder macOS dmg target (arm64)"
```

---

### Task 3: Pin PyInstaller in dev requirements

**Files:**
- Create: `backend/requirements-build.txt`

The existing `backend/requirements-dev.txt` has pytest. PyInstaller deserves its own file so dev test runs don't pull it in.

- [ ] **Step 1: Create the file**

Write to `backend/requirements-build.txt`:

```
pyinstaller>=6.0,<7.0
```

- [ ] **Step 2: Install locally**

```bash
cd /Users/raviwu/personal/locwarp/backend
pip install -r requirements-build.txt
pyinstaller --version
```

Expected: prints e.g. `6.x.x`.

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/requirements-build.txt
git commit -m "build: pin pyinstaller in requirements-build.txt"
```

---

### Task 4: Mac build script `build-installer-mac.sh`

**Files:**
- Create: `build-installer-mac.sh`

Mirror of `build-installer.bat` (Windows) but for Mac.

- [ ] **Step 1: Create the script**

Write to `/Users/raviwu/personal/locwarp/build-installer-mac.sh`:

```bash
#!/usr/bin/env bash
# LocWarp one-shot Mac build: backend binary + Electron DMG.
# Prereqs (install once):
#   - Python 3.11 (or matching backend requirement) + venv with requirements*.txt
#   - Node 20+ with frontend/node_modules installed
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo
echo "============================================================"
echo " [1/3] Build backend with PyInstaller"
echo "============================================================"
cd "$ROOT/backend"
python3 -m PyInstaller locwarp-backend.spec --noconfirm \
    --distpath "$ROOT/dist-py" \
    --workpath "$ROOT/build-py/backend"

echo
echo "============================================================"
echo " [2/3] Build frontend with Vite"
echo "============================================================"
cd "$ROOT/frontend"
npm run build

echo
echo "============================================================"
echo " [3/3] Package Electron DMG"
echo "============================================================"
npm run dist:mac

echo
echo "Done. DMG in $ROOT/frontend/release/"
ls -lh "$ROOT/frontend/release"/*.dmg
```

Make executable:

```bash
chmod +x /Users/raviwu/personal/locwarp/build-installer-mac.sh
```

- [ ] **Step 2: Run it locally end-to-end**

```bash
cd /Users/raviwu/personal/locwarp
./build-installer-mac.sh
```

Expected: produces `frontend/release/LocWarp-0.2.99-arm64.dmg` (version follows current `package.json` 0.2.99 — we bump to 0.3.0 in Task 6).

If it fails:
- Backend PyInstaller failure → likely a missing dep on Mac. Read the error, install whatever is missing, re-run. PyInstaller spec is mostly cross-platform so most likely a Python version mismatch.
- electron-builder failure → probably icon path or DMG-specific issue. Read the error.

- [ ] **Step 3: Verify the DMG**

```bash
open /Users/raviwu/personal/locwarp/frontend/release/LocWarp-0.2.99-arm64.dmg
# Drag LocWarp.app to /Applications inside the mounted DMG.
# Right-click LocWarp.app in /Applications → Open → Open (bypasses Gatekeeper)
# App should launch, backend should start, you should see the LocWarp UI.
```

If the app launches and the backend connects, the build pipeline is working. **DO NOT** test iPhone-pairing here — that's app behaviour, not build correctness.

- [ ] **Step 4: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add build-installer-mac.sh
git commit -m "build(mac): add build-installer-mac.sh one-shot DMG builder"
```

---

### Task 5: Add `.gitignore` entries for Mac build artifacts

**Files:**
- Modify: `.gitignore`

The current `.gitignore` already ignores `dist-py/`, `build-py/`, `frontend/release/`. Add Mac-specific build leftovers:

- [ ] **Step 1: Append to `.gitignore`**

Append at the end:

```
# ── macOS build artifacts ───────────────────────────
*.dmg
frontend/build/icon.iconset/
```

- [ ] **Step 2: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add .gitignore
git commit -m "chore(gitignore): ignore Mac DMG and intermediate iconset"
```

---

### Task 6: Bump version 0.2.99 → 0.3.0

**Files:**
- Modify: `frontend/package.json` (auto)
- Modify: `frontend/package-lock.json` (auto)

**Only run after Tasks 1-5 are confirmed working.**

- [ ] **Step 1: Bump**

```bash
cd /Users/raviwu/personal/locwarp/frontend
npm version minor
```

This:
- Sets `package.json` `"version": "0.3.0"`
- Updates `package-lock.json`
- Creates a commit `0.3.0`
- Creates a tag `v0.3.0`

- [ ] **Step 2: Verify**

```bash
cd /Users/raviwu/personal/locwarp
git log --oneline -3
git tag --list 'v0.3.*'
```

Expected: a new commit `0.3.0` on `main`, tag `v0.3.0` pointing at it.

- [ ] **Step 3: Re-build with new version**

```bash
cd /Users/raviwu/personal/locwarp
./build-installer-mac.sh
ls frontend/release/
```

Expected: `LocWarp-0.3.0-arm64.dmg`.

---

### Task 7: Manual GitHub release for v0.3.0

**Files:** none (uses `gh` CLI)

- [ ] **Step 1: Push the commit + tag**

```bash
cd /Users/raviwu/personal/locwarp
git push origin main --follow-tags
```

`--follow-tags` pushes both the branch and any annotated tags reachable from it.

- [ ] **Step 2: Build release notes**

The repo has `.github/release-footer.md` with the standard footer. Use it:

```bash
NOTES=$(cat <<'EOF'
## Highlights

- 拉金盆 (Pull Gold Ditto) mode: GoldDitto cycle with bookmark-driven A/B selection
- Bookmark management: cascade-delete category, four-format export (JSON / Markdown / GeoJSON / CSV), format-detecting import
- macOS DMG (Apple Silicon) — first Mac release

## Install

**Windows:** download `LocWarp-Setup-0.3.0.exe` and run.

**macOS:** download `LocWarp-0.3.0-arm64.dmg`. The DMG is unsigned — first launch:

1. Double-click the DMG, drag `LocWarp.app` to `/Applications`.
2. In `/Applications`, right-click `LocWarp.app` → Open → Open.
3. macOS remembers your choice; subsequent launches don't need this.

EOF
)
NOTES="$NOTES

$(cat .github/release-footer.md)"
```

- [ ] **Step 3: Create the release**

```bash
cd /Users/raviwu/personal/locwarp
gh release create v0.3.0 \
  ./frontend/release/LocWarp-0.3.0-arm64.dmg \
  --title "v0.3.0" \
  --notes "$NOTES"
```

(If you also have a Windows .exe handy, add it to the args. Otherwise Mac-only is fine.)

- [ ] **Step 4: Verify on GitHub**

```bash
gh release view v0.3.0
```

Expected: shows the release with the DMG attached.

---

## Stage 2: GitHub Actions Automation

### Task 8: Write `.github/workflows/release.yml`

**Files:**
- Create: `.github/workflows/release.yml`

Triggers on `v*` tag push. Builds on `macos-latest` (Apple Silicon as of 2024). Uploads the DMG to the auto-created GitHub Release.

- [ ] **Step 1: Create the workflow**

Write to `/Users/raviwu/personal/locwarp/.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ['v*']

permissions:
  contents: write   # required for softprops/action-gh-release

jobs:
  macos:
    runs-on: macos-latest
    timeout-minutes: 30

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install backend deps
        working-directory: backend
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-build.txt

      - name: Build backend with PyInstaller
        working-directory: backend
        run: |
          python -m PyInstaller locwarp-backend.spec --noconfirm \
            --distpath ../dist-py \
            --workpath ../build-py/backend

      - name: Install frontend deps
        working-directory: frontend
        run: npm ci

      - name: Build frontend (Vite)
        working-directory: frontend
        run: npm run build

      - name: Package DMG (electron-builder)
        working-directory: frontend
        run: npm run dist:mac

      - name: List release artifacts
        run: ls -lh frontend/release/

      - name: Upload to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: frontend/release/*.dmg
          fail_on_unmatched_files: true
          generate_release_notes: true
          append_body: true
          body_path: .github/release-footer.md
```

Notes on choices:
- `macos-latest` runs on Apple Silicon since Sept 2024. Produces arm64 binaries natively.
- `npm ci` (not `npm install`) for reproducibility from `package-lock.json`.
- `permissions: contents: write` is required by `softprops/action-gh-release` to attach files to releases.
- `generate_release_notes: true` makes GitHub auto-fill from the commits since the previous tag. `append_body` + `body_path` then appends the static footer.
- `fail_on_unmatched_files: true` makes the workflow fail loudly if the DMG glob matched zero files (e.g. electron-builder named the output something unexpected).

- [ ] **Step 2: Validate the workflow YAML offline**

If `actionlint` is on your `$PATH`, run it. If not, GitHub will validate on first push — that's fine.

```bash
which actionlint && actionlint .github/workflows/release.yml || echo "actionlint not installed; will validate on push"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add .github/workflows/release.yml
git commit -m "ci(release): GitHub Actions workflow for macOS DMG on v* tag"
```

---

### Task 9: Test the workflow with a throwaway tag

**Files:** none (CI verification)

- [ ] **Step 1: Push the commit (no tag yet)**

```bash
git push origin main
```

This pushes the workflow file but doesn't trigger it (no tag was pushed).

- [ ] **Step 2: Create and push a test tag**

```bash
git tag v0.3.1-rc.1
git push origin v0.3.1-rc.1
```

This is a pre-release tag. The workflow will fire and create a GitHub release named `v0.3.1-rc.1` with the DMG attached.

- [ ] **Step 3: Watch the workflow**

```bash
gh run watch
```

(Or visit `https://github.com/keezxc1223/locwarp/actions`.)

Expected: green check, ~10-15 minutes total (most of it is `pip install`, PyInstaller, and `electron-builder`).

- [ ] **Step 4: Verify the release was created**

```bash
gh release view v0.3.1-rc.1
```

Expected: release exists, DMG attached, body has the auto-generated changelog plus your footer.

- [ ] **Step 5: Clean up the test tag and release**

```bash
gh release delete v0.3.1-rc.1 --yes
git push origin :refs/tags/v0.3.1-rc.1
git tag -d v0.3.1-rc.1
```

- [ ] **Step 6: (No commit — the workflow is already on main from Step 8.)**

---

### Task 10: Document the release process in README

**Files:**
- Modify: `README.md` (Chinese)
- Modify: `README.en.md` (English)

Add a "Release Process" section (or a "For Maintainers" section if one doesn't exist).

- [ ] **Step 1: Read the existing README structure**

```bash
grep -n "^#" /Users/raviwu/personal/locwarp/README.md | head -20
```

Find where to insert. Probably near the end, before any "License" section.

- [ ] **Step 2: Append release section**

To `README.md`, append (in Traditional Chinese):

```markdown
## 發布流程 (For Maintainers)

```bash
cd frontend
npm version minor   # 0.x.y → 0.(x+1).0  — 自動 commit + tag
git push origin main --follow-tags
```

`v*` tag push 會觸發 GitHub Actions (`.github/workflows/release.yml`)，自動 build macOS DMG 並建立 release。

Windows .exe 目前需手動 build (`build-installer.bat`) 並手動 attach 到該 release。

### macOS 安裝注意事項
DMG 沒有簽名 (Apple Developer ID)。第一次開啟 LocWarp.app 要：
1. 雙擊 DMG → 拖 `LocWarp.app` 到 `/Applications`
2. 在 `/Applications` 裡 **右鍵** → Open → Open
3. macOS 記住此選擇，之後雙擊正常啟動
```

To `README.en.md`, append (English):

```markdown
## Release Process (For Maintainers)

```bash
cd frontend
npm version minor   # 0.x.y → 0.(x+1).0  — auto-commits + tags
git push origin main --follow-tags
```

Pushing a `v*` tag triggers `.github/workflows/release.yml`, which builds the macOS DMG and creates a release.

The Windows `.exe` is still built manually (`build-installer.bat`) and uploaded to the same release.

### macOS install
The DMG is unsigned. First launch:
1. Double-click the DMG, drag `LocWarp.app` to `/Applications`.
2. Right-click `LocWarp.app` in `/Applications` → Open → Open.
3. macOS remembers; subsequent launches are normal.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add README.md README.en.md
git commit -m "docs: document release process and macOS install"
```

---

## Self-Review Checklist (run before handing off)

- [ ] Each task's commit happens after the corresponding step succeeds — no commits land before verification.
- [ ] Stage 1 produces a runnable DMG locally before Stage 2 is started.
- [ ] No broken type/lint errors introduced.
- [ ] `.gitignore` covers DMG and iconset intermediate (Task 5).
- [ ] Version bump (Task 6) happens AFTER local build is confirmed working — so a broken bump doesn't pollute history.
- [ ] Stage 2 workflow uses `npm ci`, not `npm install` (reproducibility).
- [ ] Stage 2 workflow has `permissions: contents: write` (required for release uploads).
- [ ] Test tag (`v0.3.1-rc.1`) cleanup is complete before declaring done.
- [ ] Both READMEs updated, not just one.

## Out of scope (document but don't do)

- Apple Developer ID signing + notarization (defer until external user count justifies the $99/year cost)
- Windows `.exe` in CI (out of scope this iteration; user keeps building locally)
- Universal binary (arm64 + x64); only arm64 for now
- Auto-update / Squirrel.Mac (not needed at this maturity)
- Release-notes automation beyond GitHub's auto-generation + static footer
