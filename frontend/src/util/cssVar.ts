// Shared CSS custom-property reader (spec §8: "one source of truth" for
// domain colors — map/map.ts's `readInkColor` established this pattern for
// --zij-ink in step; this generalizes it for --zij-brass/--zij-dun etc.).

export function readCssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
