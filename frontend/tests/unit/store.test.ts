/**
 * Unit tests for `src/state/store.ts`: idempotent full replace.
 *
 * Pure state container, no DOM/network — exercised directly.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Store } from '../../src/state/store';
import type { LayerSnapshot } from '../../src/state/types';

// The toggle tests mock the fire-and-forget POST
// `Store.toggleLayer` makes via `api/client`'s `toggleLayer` wrapper — the
// mock intercepts by resolved module id, so it applies regardless of the
// relative specifier `store.ts` itself uses (`../api/client`).
vi.mock('../../src/api/client', () => ({
  toggleLayer: vi.fn().mockResolvedValue(undefined),
}));

function snapshot(overrides: Partial<LayerSnapshot['meta']> = {}, features: LayerSnapshot['features'] = []): LayerSnapshot {
  return {
    meta: {
      layer: 'air',
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: '2026-07-09T10:05:03Z',
      timestamp_source: '2026-07-09T10:04:58Z',
      cadence_s: 600,
      stale_after_s: 1200,
      feature_count: features.length,
      retry_after_s: null,
      detail: null,
      ...overrides,
    },
    features,
  };
}

const FEATURE = {
  domain: 'air',
  source: 'opensky',
  source_id: '896451',
  label: 'IRA655',
  lat: 26.61,
  lon: 56.27,
  geometry_type: 'point' as const,
  geometry: null,
  timestamp_source: '2026-07-09T10:04:58Z',
  timestamp_fetched: '2026-07-09T10:05:03Z',
  position_age_s: 5.0,
  status: 'live',
  integrity_flags: [],
  attrs: {},
};

describe('Store.applySnapshot — plan unit #3: idempotent full replace (full-state-on-connect, ADR-12)', () => {
  it('replaces the layer state wholesale: meta and features exactly match the applied snapshot', () => {
    const store = new Store();
    const snap = snapshot({}, [FEATURE]);

    store.applySnapshot('air', snap);

    const layer = store.getState().layers.air;
    expect(layer.meta).toEqual(snap.meta);
    expect(layer.features).toEqual(snap.features);
    expect(layer.enabled).toBe(true);
  });

  it('re-applying the SAME snapshot twice produces the same resulting state — a no-op delta, not an accumulation', () => {
    const store = new Store();
    const snap = snapshot({}, [FEATURE]);

    store.applySnapshot('air', snap);
    const firstFeatures = store.getState().layers.air.features;

    store.applySnapshot('air', snap);
    const secondFeatures = store.getState().layers.air.features;

    // Full replace, not append: the feature list length/content is
    // unchanged by re-applying the identical snapshot a second time.
    expect(secondFeatures).toHaveLength(firstFeatures.length);
    expect(secondFeatures).toEqual(firstFeatures);
    expect(store.getState().layers.air.meta).toEqual(snap.meta);
  });

  it('applying a snapshot with FEWER features than the previous one shrinks the stored list (a true replace, not a merge)', () => {
    const store = new Store();
    const first = snapshot({}, [FEATURE, { ...FEATURE, source_id: '896452' }]);
    store.applySnapshot('air', first);
    expect(store.getState().layers.air.features).toHaveLength(2);

    const second = snapshot({}, [FEATURE]);
    store.applySnapshot('air', second);

    expect(store.getState().layers.air.features).toHaveLength(1);
    expect(store.getState().layers.air.features[0].source_id).toBe('896451');
  });

  it('emits "snapshot:{domain}" with the applied snapshot payload on every apply, including repeats', () => {
    const store = new Store();
    const listener = vi.fn();
    store.on('snapshot:air', listener);
    const snap = snapshot({}, [FEATURE]);

    store.applySnapshot('air', snap);
    store.applySnapshot('air', snap);

    expect(listener).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenNthCalledWith(1, snap);
    expect(listener).toHaveBeenNthCalledWith(2, snap);
  });

  it('applying a snapshot to one domain does not touch another domain\'s layer state', () => {
    const store = new Store();
    store.applySnapshot('air', snapshot({}, [FEATURE]));

    const land = store.getState().layers.land;
    expect(land.meta).toBeNull();
    expect(land.features).toEqual([]);
  });
});

describe(
  'Store.toggleLayer — optimistic flip + ' +
    'fire-and-forget POST, reconciled by next status event',
  () => {
    beforeEach(async () => {
      vi.clearAllMocks();
      const { toggleLayer: postToggleLayer } = await import('../../src/api/client');
      // Safe default so any test that doesn't override it still resolves —
      // overridden per-test below where the exact resolution matters.
      (postToggleLayer as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    });

    it('flips state.layers[domain].enabled and emits "enabled:{domain}" synchronously — ' +
      'before the POST promise has any chance to resolve', async () => {
      const { toggleLayer: postToggleLayer } = await import('../../src/api/client');
      const postMock = postToggleLayer as unknown as ReturnType<typeof vi.fn>;
      // Never resolves during this test — proves the state flip does not wait on it.
      postMock.mockReturnValue(new Promise(() => undefined));

      const store = new Store();
      const listener = vi.fn();
      store.on('enabled:land', listener);
      expect(store.getState().layers.land.enabled).toBe(true);

      store.toggleLayer('land', false);

      expect(store.getState().layers.land.enabled).toBe(false);
      expect(listener).toHaveBeenCalledTimes(1);
      expect(listener).toHaveBeenCalledWith(false);
    });

    it('issues the POST via api/client.toggleLayer with the domain and the new enabled value', async () => {
      const { toggleLayer: postToggleLayer } = await import('../../src/api/client');
      const postMock = postToggleLayer as unknown as ReturnType<typeof vi.fn>;
      postMock.mockResolvedValue({ layer: 'air', enabled: false });

      const store = new Store();
      store.toggleLayer('air', false);

      expect(postMock).toHaveBeenCalledTimes(1);
      expect(postMock).toHaveBeenCalledWith('air', false);
    });

    it('a rejected POST does not roll back the optimistic state (no un-toggle on failure)', async () => {
      const { toggleLayer: postToggleLayer } = await import('../../src/api/client');
      const postMock = postToggleLayer as unknown as ReturnType<typeof vi.fn>;
      postMock.mockRejectedValue(new Error('network down'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

      const store = new Store();
      store.toggleLayer('marine', false);
      expect(store.getState().layers.marine.enabled).toBe(false);

      // Let the rejected promise's `.catch` microtask run.
      await Promise.resolve();
      await Promise.resolve();

      expect(store.getState().layers.marine.enabled).toBe(false);
      expect(warnSpy).toHaveBeenCalled();
      warnSpy.mockRestore();
    });

    it('re-enabling (toggleLayer(domain, true)) flips enabled back to true', () => {
      const store = new Store();
      store.toggleLayer('land', false);
      expect(store.getState().layers.land.enabled).toBe(false);

      store.toggleLayer('land', true);
      expect(store.getState().layers.land.enabled).toBe(true);
    });
  },
);

describe(
  'Store.applySnapshot/applyLayerStatus — ' +
    'a disabled domain drops incoming SSE rather than resurrecting itself',
  () => {
    beforeEach(async () => {
      vi.clearAllMocks();
      const { toggleLayer: postToggleLayer } = await import('../../src/api/client');
      (postToggleLayer as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    });

    it('applySnapshot on a disabled domain is a no-op: no state write, no "snapshot:{domain}" emit', () => {
      const store = new Store();
      store.toggleLayer('land', false);
      const listener = vi.fn();
      store.on('snapshot:land', listener);

      store.applySnapshot('land', snapshot({ layer: 'land' }, [FEATURE]));

      expect(listener).not.toHaveBeenCalled();
      expect(store.getState().layers.land.enabled).toBe(false);
      expect(store.getState().layers.land.features).toEqual([]);
    });

    it('applyLayerStatus on a disabled domain is a no-op: no state write, no "status:{domain}" emit', () => {
      const store = new Store();
      store.toggleLayer('air', false);
      const listener = vi.fn();
      store.on('status:air', listener);

      store.applyLayerStatus('air', snapshot({ status: 'loading' }).meta);

      expect(listener).not.toHaveBeenCalled();
      expect(store.getState().layers.air.meta).toBeNull();
    });

    it('once re-enabled, a subsequent applySnapshot is applied normally again', () => {
      const store = new Store();
      store.toggleLayer('air', false);
      store.applySnapshot('air', snapshot({}, [FEATURE])); // dropped while disabled

      store.toggleLayer('air', true);
      const snap = snapshot({}, [FEATURE]);
      store.applySnapshot('air', snap);

      expect(store.getState().layers.air.enabled).toBe(true);
      expect(store.getState().layers.air.features).toEqual(snap.features);
    });
  },
);

describe(
  'Store.applyRegionChanged — #98 regression: a region change clears DATA but preserves each ' +
    "domain's enabled toggle (toggleLayer is the only path back to enabled:true)",
  () => {
    beforeEach(async () => {
      vi.clearAllMocks();
      const { toggleLayer: postToggleLayer } = await import('../../src/api/client');
      (postToggleLayer as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    });

    it('a toggled-off domain stays disabled across a region change; its data is still cleared', () => {
      const store = new Store();
      store.applySnapshot('land', snapshot({ layer: 'land' }, [FEATURE]));
      store.toggleLayer('land', false);

      store.applyRegionChanged({ region_id: 'red_sea', bbox: [32, 12, 44, 28] });

      const land = store.getState().layers.land;
      expect(land.enabled).toBe(false); // the #98 bug: this silently flipped back to true
      expect(land.meta).toBeNull();
      expect(land.features).toEqual([]);
    });

    it('domains the user never touched remain enabled (data cleared as before)', () => {
      const store = new Store();
      store.applySnapshot('air', snapshot({}, [FEATURE]));
      store.toggleLayer('land', false);

      store.applyRegionChanged({ region_id: 'red_sea', bbox: [32, 12, 44, 28] });

      expect(store.getState().layers.air.enabled).toBe(true);
      expect(store.getState().layers.marine.enabled).toBe(true);
      expect(store.getState().layers.air.features).toEqual([]);
    });

    it("the disabled-domain SSE guard still holds after the region change — the new region's snapshot cannot resurrect a toggled-off layer", () => {
      const store = new Store();
      store.toggleLayer('land', false);
      store.applyRegionChanged({ region_id: 'red_sea', bbox: [32, 12, 44, 28] });
      const listener = vi.fn();
      store.on('snapshot:land', listener);

      store.applySnapshot('land', snapshot({ layer: 'land', region_id: 'red_sea' }, [FEATURE]));

      expect(listener).not.toHaveBeenCalled();
      expect(store.getState().layers.land.features).toEqual([]);
      expect(store.getState().layers.land.enabled).toBe(false);
    });
  },
);
