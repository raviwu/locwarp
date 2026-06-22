/**
 * Category color resolution — pure helpers shared by BookmarkList and the
 * row / context-menu children that render the category dot.
 */

// Preset palette for the color picker. Covers warm + cool + neutral so every
// category can find a visually distinct slot.
export const COLOR_PALETTE = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#14b8a6', '#3b82f6', '#6366f1', '#a855f7',
  '#ec4899', '#64748b',
];

const CATEGORY_COLORS: Record<string, string> = {
  Default: '#4285f4',
  Home: '#4caf50',
  Work: '#ff9800',
  Favorites: '#e91e63',
  Custom: '#9c27b0',
};

/**
 * Built-in color for a known category name, else a deterministic color hashed
 * from the name (stable across renders / restarts).
 */
export function getCategoryColor(name: string): string {
  if (CATEGORY_COLORS[name]) return CATEGORY_COLORS[name];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 60%, 55%)`;
}

/**
 * Build the resolveColor function for a given stored-color map. Prefers the
 * stored color (set at creation, editable via color picker); only falls back to
 * the built-in / name-hash color for legacy categories that have never had a
 * color assigned.
 */
export function makeResolveColor(
  categoryColors?: Record<string, string>,
): (name: string) => string {
  return (name: string): string => {
    const stored = categoryColors?.[name];
    if (stored) return stored;
    return getCategoryColor(name);
  };
}
