// Single source for the GitHub repo this app build belongs to. The macOS DMG
// ships from raviwu/locwarp, so every app-owned surface that links "home"
// (UpdateChecker's release check, the ControlPanel About link) must route
// through this constant — never re-hardcode the slug. The Windows .exe lives
// in the upstream keezxc1223/locwarp repo, so Windows-only README download
// links stay at keezxc1223 and deliberately do NOT consume this.
export const REPO_SLUG = 'raviwu/locwarp'
export const REPO_URL = `https://github.com/${REPO_SLUG}`
