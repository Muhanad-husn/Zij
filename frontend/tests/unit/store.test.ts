/**
 * Inner unit tests — plan/frontend/01-sse-client.md "Inner loop" unit #3
 * (idempotent full replace), against `src/state/store.ts` as actually built.
 *
 * Pure state container, no DOM/network — exercised directly.
 */
import { describe, expect, it, vi } from 'vitest';

import { Store } from '../../src/state/store';
import type { LayerSnapshot } from '../../src/state/types';

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
