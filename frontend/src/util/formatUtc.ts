// Pure UTC timestamp formatter — spec §4/§8, NFR6 ("every displayed timestamp
// is UTC, explicitly labeled ... no local-time conversion anywhere"). Kept as
// a standalone pure function (no DOM, no Date.now()) so it stays trivially
// unit-testable.

/** Zero-pad a non-negative integer to `width` digits. */
function pad(n: number, width = 2): string {
  return String(n).padStart(width, '0');
}

/**
 * Formats an ISO-8601 timestamp as `HH:MM:SS UTC`, using UTC getters
 * exclusively (never `getHours()`/local time). Returns `'—'` for a null/
 * undefined/unparseable input so callers can pass optional wire timestamps
 * directly.
 */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) {
    return '—';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())} UTC`;
}
