// Compact relative-age formatter — spec §4 ("Stale · {age}" / "Cached · {age}").
// The acceptance test only pins the fixed prefix (`badges.spec.ts` REQUIRED
// TEST SEAM #4); the exact `{age}` rendering is unconstrained. Kept
// pure (no DOM) so it stays trivially unit-testable, mirroring `formatUtc.ts`.

/** Formats the elapsed time between `iso` and now as a compact age string
 * (`"12s"`, `"5m"`, `"3h"`, `"2d"`). Returns `'—'` for a null/undefined/
 * unparseable input, matching `formatUtc`'s placeholder convention. */
export function formatAge(iso: string | null | undefined): string {
  if (!iso) {
    return '—';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  const diffS = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffS < 60) {
    return `${diffS}s`;
  }
  const diffM = Math.floor(diffS / 60);
  if (diffM < 60) {
    return `${diffM}m`;
  }
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) {
    return `${diffH}h`;
  }
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d`;
}
