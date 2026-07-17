/**
 * Unit tests for UTC formatting in `src/util/formatUtc.ts`.
 *
 * NFR6: every displayed timestamp is UTC, explicitly labeled, never a local
 * conversion. The test picks an ISO instant whose UTC hour differs from any
 * plausible local-timezone hour (23:00 UTC — every real timezone offset from
 * UTC-12 to UTC+14 lands on a different clock hour than 23), so a regression
 * to `getHours()`/local time would flip the expected string.
 */
import { describe, expect, it } from 'vitest';

import { formatUtc } from '../../src/util/formatUtc';

describe('formatUtc — plan unit #4: an ISO "...Z" timestamp formats as HH:MM:SS UTC', () => {
  it('formats using UTC getters, not local time', () => {
    // 23:07:09 UTC — chosen so no timezone offset (-12..+14) reproduces the
    // same clock hour via local getters, proving UTC getters are in use.
    expect(formatUtc('2026-07-06T23:07:09Z')).toBe('23:07:09 UTC');
  });

  it('zero-pads single-digit hours/minutes/seconds', () => {
    expect(formatUtc('2026-07-06T02:05:09Z')).toBe('02:05:09 UTC');
  });

  it('literally contains "UTC" (NFR6 — explicitly labeled, never bare local time)', () => {
    const formatted = formatUtc('2026-07-06T09:11:58Z');
    expect(formatted).toContain('UTC');
    expect(formatted).toBe('09:11:58 UTC');
  });
});

describe('formatUtc — plan unit #4: a null/absent timestamp_source renders a defined placeholder', () => {
  it('returns the pinned "—" placeholder for null', () => {
    expect(formatUtc(null)).toBe('—');
  });

  it('returns the same placeholder for undefined', () => {
    expect(formatUtc(undefined)).toBe('—');
  });

  it('returns the same placeholder for an unparseable string (defensive, not just missing)', () => {
    expect(formatUtc('not-a-timestamp')).toBe('—');
  });
});
