/**
 * Inner unit tests — plan/frontend/02-badges.md "Inner loop" (implicit unit:
 * the `{age}` renderer `Stale · {age}` / `Cached · {age}` depend on), against
 * `src/util/formatAge.ts` as actually built. Mirrors `formatUtc.test.ts`'s
 * shape: a pure function, no DOM.
 *
 * `Date.now()` is pinned via `vi.useFakeTimers()` + `vi.setSystemTime(...)`
 * so every boundary (s/m/h/d) is deterministic rather than depending on the
 * wall clock at test-run time.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { vi } from 'vitest';

import { formatAge } from '../../src/util/formatAge';

describe('formatAge — compact relative age used by the Stale/Cached-fallback badge labels', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-09T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders whole seconds for an age under a minute', () => {
    expect(formatAge('2026-07-09T11:59:48Z')).toBe('12s');
  });

  it('renders whole minutes for an age under an hour', () => {
    expect(formatAge('2026-07-09T11:55:00Z')).toBe('5m');
  });

  it('renders whole hours for an age under a day', () => {
    expect(formatAge('2026-07-09T09:00:00Z')).toBe('3h');
  });

  it('renders whole days for an age of a day or more', () => {
    expect(formatAge('2026-07-07T12:00:00Z')).toBe('2d');
  });

  it('clamps a non-positive diff (future timestamp / clock skew) at "0s" rather than a negative number', () => {
    expect(formatAge('2026-07-09T12:00:05Z')).toBe('0s');
  });

  it('returns the pinned "—" placeholder for null, undefined, and an unparseable string', () => {
    expect(formatAge(null)).toBe('—');
    expect(formatAge(undefined)).toBe('—');
    expect(formatAge('not-a-timestamp')).toBe('—');
  });
});
