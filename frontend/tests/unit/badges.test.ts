/**
 * Unit tests for `src/ui/badges.ts`: freshness/count badge DOM, the
 * status/color seam, the countdown, Caveats-always-enabled, and
 * status-detail. Pure DOM, jsdom — no map, no network.
 *
 * `data-status` + `[data-testid="status-indicator"]` is how badges.ts wires
 * the LayerStatus -> color mapping (layout.css keys its `--status-*`
 * background off `.zij-badge[data-status='...']`); jsdom does not load
 * external stylesheets, so these unit tests assert the `data-status`
 * attribute itself (the seam that drives the color) rather than a computed
 * CSS color — the Playwright test (`badges.spec.ts`) is what asserts
 * the actual rendered color in a real browser.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

  it('a status-only update (both timestamps null, e.g. loading) renders the "—" placeholder for BOTH timestamps', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');

    badge.update(meta());
    badge.update(meta({ status: 'loading', timestamp_fetched: null, timestamp_source: null }));

    const container = parent.querySelector('[data-testid="badge-air"]') as HTMLElement;
    expect(container.querySelector('[data-testid="freshness-fetched"]')?.textContent).toBe('—');
    expect(container.querySelector('[data-testid="freshness-source"]')?.textContent).toBe('—');
  });
});

describe('mountBadge — LayerStatus -> data-status + label, all seven values', () => {
  function render(status: string, overrides: Partial<LayerSnapshotMeta> = {}) {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    badge.update(meta({ status, ...overrides }));
    const container = parent.querySelector('[data-testid="badge-air"]') as HTMLElement;
    return {
      container,
      dataStatus: container.dataset.status,
      label: container.querySelector('[data-testid="status-label"]')?.textContent ?? '',
    };
  }

  it('live -> data-status="live", label "Live"', () => {
    const { dataStatus, label } = render('live');
    expect(dataStatus).toBe('live');
    expect(label).toBe('Live');
  });

  it('loading -> data-status="loading", label "Loading…"', () => {
    const { dataStatus, label } = render('loading', { timestamp_fetched: null, timestamp_source: null });
    expect(dataStatus).toBe('loading');
    expect(label).toBe('Loading…');
  });

  it('error -> data-status="error", label "Error"', () => {
    const { dataStatus, label } = render('error', { detail: 'upstream 503' });
    expect(dataStatus).toBe('error');
    expect(label).toBe('Error');
  });

  it('reconnecting -> data-status="reconnecting" (grouped with loading per feature-schema.md LayerStatus ' +
    'note, but the label is distinct), label "Reconnecting…"', () => {
    const { dataStatus, label } = render('reconnecting', { detail: 'websocket dropped' });
    expect(dataStatus).toBe('reconnecting');
    expect(label).toBe('Reconnecting…');
  });

  it('stale -> data-status="stale", label carries the fixed "Stale · " prefix + formatAge(timestamp_source)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-09T12:00:00Z'));
    try {
      const { dataStatus, label } = render('stale', {
        timestamp_fetched: '2026-07-09T11:59:00Z',
        timestamp_source: '2026-07-09T09:00:00Z', // 3h before the pinned "now"
      });
      expect(dataStatus).toBe('stale');
      expect(label).toBe('Stale · 3h');
    } finally {
      vi.useRealTimers();
    }
  });

  it('cached-fallback -> data-status="cached-fallback", label carries the fixed "Cached · " prefix + ' +
    'formatAge(timestamp_fetched)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-09T12:00:00Z'));
    try {
      const { dataStatus, label } = render('cached-fallback', {
        timestamp_fetched: '2026-07-07T12:00:00Z', // 2d before the pinned "now"
        timestamp_source: '2026-07-07T11:55:00Z',
      });
      expect(dataStatus).toBe('cached-fallback');
      expect(label).toBe('Cached · 2d');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('mountBadge — rate-limited countdown ticks down from ' +
  'retry_after_s and clears on transition (no leaked timer)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('seeds the label from retry_after_s and decrements by 1 every second', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    const label = parent.querySelector('[data-testid="badge-air"] [data-testid="status-label"]') as HTMLElement;

    badge.update(meta({ status: 'rate-limited', retry_after_s: 5 }));
    expect(label.textContent).toBe('Rate-limited · retry in 5s');

    vi.advanceTimersByTime(1000);
    expect(label.textContent).toBe('Rate-limited · retry in 4s');

    vi.advanceTimersByTime(3000);
    expect(label.textContent).toBe('Rate-limited · retry in 1s');
  });

  it('clamps at "0s" and stops ticking rather than going negative', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    const label = parent.querySelector('[data-testid="badge-air"] [data-testid="status-label"]') as HTMLElement;

    badge.update(meta({ status: 'rate-limited', retry_after_s: 2 }));
    vi.advanceTimersByTime(2000);
    expect(label.textContent).toBe('Rate-limited · retry in 0s');

    // Advance well past where a naive countdown would go negative.
    vi.advanceTimersByTime(5000);
    expect(label.textContent).toBe('Rate-limited · retry in 0s');
  });

  it('clears the countdown interval when a later update() moves status away from rate-limited', () => {
    const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval');
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    const label = parent.querySelector('[data-testid="badge-air"] [data-testid="status-label"]') as HTMLElement;

    badge.update(meta({ status: 'rate-limited', retry_after_s: 10 }));
    expect(clearIntervalSpy).not.toHaveBeenCalled(); // no prior interval to clear yet

    badge.update(meta({ status: 'live' }));
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    expect(label.textContent).toBe('Live');

    // The old countdown must not still be ticking in the background — advance
    // well past several of its would-be ticks and confirm the label is
    // untouched (a leaked interval would silently keep calling render()).
    vi.advanceTimersByTime(5000);
    expect(label.textContent).toBe('Live');

    clearIntervalSpy.mockRestore();
  });
});

describe('mountBadge — Caveats control is always rendered and enabled, ' +
  'regardless of status', () => {
  const statuses = ['live', 'stale', 'loading', 'rate-limited', 'error', 'cached-fallback', 'reconnecting'];

  it.each(statuses)('status=%s', (status) => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    badge.update(meta({ status, retry_after_s: status === 'rate-limited' ? 5 : null }));

    const caveats = parent.querySelector('[data-testid="badge-air"] [data-testid="caveats-button"]') as
      | HTMLButtonElement
      | null;
    expect(caveats, `caveats button must be present in status="${status}"`).not.toBeNull();
    expect(caveats?.disabled, `caveats button must be enabled in status="${status}"`).toBe(false);
  });
});

describe('mountBadge — status-detail carries meta.detail verbatim', () => {
  it('data-detail equals meta.detail on error', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    badge.update(meta({ status: 'error', detail: 'upstream 503' }));

    const detailEl = parent.querySelector('[data-testid="badge-air"] [data-testid="status-detail"]') as HTMLElement;
    expect(detailEl.dataset.detail).toBe('upstream 503');
  });

  it('data-detail is empty when meta.detail is null (e.g. live)', () => {
    const parent = document.createElement('div');
    const badge = mountBadge(parent, 'air');
    badge.update(meta({ status: 'live', detail: null }));

    const detailEl = parent.querySelector('[data-testid="badge-air"] [data-testid="status-detail"]') as HTMLElement;
    expect(detailEl.dataset.detail).toBe('');
  });
});

describe(
  'mountBadge — data-enabled seam ' +
    '(REQUIRED TEST SEAM #1) + Toggle/Refresh wiring',
  () => {
    it('defaults to data-enabled="true" on mount, before any update()', () => {
      const parent = document.createElement('div');
      mountBadge(parent, 'air');

      const container = parent.querySelector('[data-testid="badge-air"]') as HTMLElement;
      expect(container.dataset.enabled).toBe('true');
    });

    it('setEnabled(false) flips data-enabled to "false"; setEnabled(true) flips it back', () => {
      const parent = document.createElement('div');
      const badge = mountBadge(parent, 'land');
      const container = parent.querySelector('[data-testid="badge-land"]') as HTMLElement;

      badge.setEnabled(false);
      expect(container.dataset.enabled).toBe('false');

      badge.setEnabled(true);
      expect(container.dataset.enabled).toBe('true');
    });

    it('setEnabled() never touches data-status — independent of the wire LayerStatus', () => {
      const parent = document.createElement('div');
      const badge = mountBadge(parent, 'air');
      badge.update(meta({ status: 'live' }));

      badge.setEnabled(false);

      const container = parent.querySelector('[data-testid="badge-air"]') as HTMLElement;
      expect(container.dataset.status).toBe('live');
      expect(container.dataset.enabled).toBe('false');
    });

    it('clicking [data-testid="toggle-button"] invokes the injected onToggle callback exactly once', () => {
      const parent = document.createElement('div');
      const onToggle = vi.fn();
      mountBadge(parent, 'land', { onToggle });

      const toggleButton = parent.querySelector(
        '[data-testid="badge-land"] [data-testid="toggle-button"]',
      ) as HTMLButtonElement;
      toggleButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(onToggle).toHaveBeenCalledTimes(1);
    });

    it('clicking [data-testid="refresh-button"] invokes the injected onRefresh callback exactly once', () => {
      const parent = document.createElement('div');
      const onRefresh = vi.fn();
      mountBadge(parent, 'air', { onRefresh });

      const refreshButton = parent.querySelector(
        '[data-testid="badge-air"] [data-testid="refresh-button"]',
      ) as HTMLButtonElement;
      refreshButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(onRefresh).toHaveBeenCalledTimes(1);
    });

    it('clicking [data-testid="caveats-button"] invokes the injected onCaveats callback exactly once ' +
      '(the click-wiring behind the badge\'s entry point into the panel)', () => {
      const parent = document.createElement('div');
      const onCaveats = vi.fn();
      mountBadge(parent, 'marine', { onCaveats });

      const caveatsButton = parent.querySelector(
        '[data-testid="badge-marine"] [data-testid="caveats-button"]',
      ) as HTMLButtonElement;
      caveatsButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(onCaveats).toHaveBeenCalledTimes(1);
    });
  },
);

describe(
  'mountBadge — refresh-button disables while ' +
    'data-status="loading" and re-enables on the next non-loading update (REQUIRED TEST SEAM #5)',
  () => {
    it('refresh-button is enabled by default (initial live status)', () => {
      const parent = document.createElement('div');
      const badge = mountBadge(parent, 'air');
      badge.update(meta({ status: 'live' }));

      const refreshButton = parent.querySelector(
        '[data-testid="badge-air"] [data-testid="refresh-button"]',
      ) as HTMLButtonElement;
      expect(refreshButton.disabled).toBe(false);
    });

    it('update() with status "loading" disables the refresh-button', () => {
      const parent = document.createElement('div');
      const badge = mountBadge(parent, 'air');
      badge.update(meta({ status: 'live' }));

      badge.update(meta({ status: 'loading', timestamp_fetched: null, timestamp_source: null }));

      const refreshButton = parent.querySelector(
        '[data-testid="badge-air"] [data-testid="refresh-button"]',
      ) as HTMLButtonElement;
      expect(refreshButton.disabled).toBe(true);
    });

    it('a subsequent non-loading update (e.g. live) re-enables the refresh-button', () => {
      const parent = document.createElement('div');
      const badge = mountBadge(parent, 'air');
      badge.update(meta({ status: 'loading', timestamp_fetched: null, timestamp_source: null }));

      badge.update(meta({ status: 'live', feature_count: 3 }));

      const refreshButton = parent.querySelector(
        '[data-testid="badge-air"] [data-testid="refresh-button"]',
      ) as HTMLButtonElement;
      expect(refreshButton.disabled).toBe(false);
    });

    it('the disabled state is independently re-derived per domain — a loading air badge does not disable land\'s button', () => {
      const parent = document.createElement('div');
      const airBadge = mountBadge(parent, 'air');
      const landBadge = mountBadge(parent, 'land');
      landBadge.update(meta({ status: 'live', layer: 'land' }));

      airBadge.update(meta({ status: 'loading', timestamp_fetched: null, timestamp_source: null }));

      const landRefresh = parent.querySelector(
        '[data-testid="badge-land"] [data-testid="refresh-button"]',
      ) as HTMLButtonElement;
      expect(landRefresh.disabled).toBe(false);
    });
  },
);
