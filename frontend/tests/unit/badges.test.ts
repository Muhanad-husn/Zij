/**
 * Inner unit tests — plan/frontend-map/02-layers-refresh.md "Inner loop"
 * units #4/#5 (freshness/count badge DOM), against `src/ui/badges.ts` as
 * actually built. Pure DOM, jsdom — no map, no network.
 */
import { describe, expect, it } from 'vitest';

import { mountBadge } from '../../src/ui/badges';
import type { LayerSnapshotMeta } from '../../src/state/types';

function meta(overrides: Partial<LayerSnapshotMeta> = {}): LayerSnapshotMeta {
  return {
    layer: 'air',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-06T09:12:03Z',
    timestamp_source: '2026-07-06T09:11:58Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 2,
    retry_after_s: null,
    detail: null,
    ...overrides,
  };
}

describe('mountBadge — plan units #4/#5: freshness + count DOM seams', () => {
  it('mounts a container carrying [data-testid="badge-{domain}"]', () => {
    const parent = document.createElement('div');
    mountBadge(parent, 'air');

    const container = parent.querySelector('[data-testid="badge-air"]');
    expect(container).not.toBeNull();
  });

  it('update() renders both timestamps via formatUtc (HH:MM:SS UTC) and the feature count', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');

    badge.update(meta());

    const container = parent.querySelector('[data-testid="badge-air"]') as HTMLElement;
    expect(container.querySelector('[data-testid="freshness-fetched"]')?.textContent).toBe('09:12:03 UTC');
    expect(container.querySelector('[data-testid="freshness-source"]')?.textContent).toBe('09:11:58 UTC');
    expect(container.querySelector('[data-testid="feature-count"]')?.textContent).toContain('2');
  });

  it('renders the formatUtc placeholder when timestamp_source is null', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'land');

    badge.update(meta({ timestamp_source: null }));

    const container = parent.querySelector('[data-testid="badge-land"]') as HTMLElement;
    expect(container.querySelector('[data-testid="freshness-source"]')?.textContent).toBe('—');
  });

  it('a second update() call fully replaces the previous rendered values (idempotent re-render, not accumulation)', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');

    badge.update(meta());
    badge.update(meta({ timestamp_fetched: '2026-07-06T09:22:03Z', feature_count: 3 }));

    const container = parent.querySelector('[data-testid="badge-air"]') as HTMLElement;
    expect(container.querySelector('[data-testid="freshness-fetched"]')?.textContent).toBe('09:22:03 UTC');
    expect(container.querySelector('[data-testid="feature-count"]')?.textContent).toContain('3');
  });
});
