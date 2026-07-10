/**
 * Inner unit tests — plan/frontend/06-marine-integrity.md "Inner loop" units
 * #2 (client-tick age math vs config thresholds) and #3 (past `drop_after_s`
 * a marine feature is removed; land is untouched), against
 * `src/state/derive.ts` and `Store.tick` as actually built.
 *
 * `computeFeatureAgeS`/`tickLayerFeatures` are pure (no DOM/network), so the
 * math is pinned directly with fixed timestamps. The `Store.tick` describe
 * covers the wiring the pure functions can't see: config gating, the
 * marine-only drop threshold, and land's exemption from ticking entirely.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { computeFeatureAgeS, tickLayerFeatures } from '../../src/state/derive';
import { Store } from '../../src/state/store';
import type { AppConfig, LayerSnapshot, WireFeature } from '../../src/state/types';

/** Fixed wall-clock base so age math is deterministic. */
const T0_ISO = '2026-07-10T12:00:00Z';
const T0_MS = Date.parse(T0_ISO);

function feature(overrides: Partial<WireFeature> = {}): WireFeature {
  return {
    domain: 'marine',
    source: 'aisstream',
    source_id: '422011111',
    label: null,
    lat: 26.61,
    lon: 56.27,
    geometry_type: 'point',
    geometry: null,
    timestamp_source: T0_ISO,
    timestamp_fetched: T0_ISO,
    position_age_s: 0,
    status: 'live',
    integrity_flags: [],
    attrs: { sog_kn: 12.4, cog_deg: 341.0 },
    ...overrides,
  };
}

describe('computeFeatureAgeS — plan unit #2: age = position_age_s + elapsed since timestamp_fetched', () => {
  it('adds wall-clock elapsed to the wire position_age_s', () => {
    const f = feature({ position_age_s: 30 });
    expect(computeFeatureAgeS(f, T0_MS + 10_000)).toBe(40);
  });

  it('treats a null position_age_s as 0 (feature-schema.md nullability)', () => {
    const f = feature({ position_age_s: null });
    expect(computeFeatureAgeS(f, T0_MS + 5_000)).toBe(5);
  });

  it('clamps negative elapsed (clock skew: timestamp_fetched in the future) to 0', () => {
    const f = feature({ position_age_s: 7 });
    expect(computeFeatureAgeS(f, T0_MS - 60_000)).toBe(7);
  });

  it('falls back to position_age_s alone on an unparseable timestamp_fetched', () => {
    const f = feature({ position_age_s: 12, timestamp_fetched: 'not-a-timestamp' });
    expect(computeFeatureAgeS(f, T0_MS + 99_000)).toBe(12);
  });
});

describe('tickLayerFeatures — plan units #2/#3: de-emphasize past threshold, drop past drop_after_s', () => {
  it('marks a feature deemphasized only once its age exceeds deemphasize_after_s', () => {
    const fresh = feature({ source_id: 'fresh', position_age_s: 0 });
    const silent = feature({ source_id: 'silent', position_age_s: 100 });
    const out = tickLayerFeatures([fresh, silent], T0_MS + 1_000, 60);
    expect(out.map((f) => [f.source_id, f.deemphasized])).toEqual([
      ['fresh', false],
      ['silent', true],
    ]);
  });

  it('drops a feature past dropAfterS entirely, leaving younger siblings intact (per-feature removal)', () => {
    const young = feature({ source_id: 'young', position_age_s: 0 });
    const old = feature({ source_id: 'old', position_age_s: 7_200 });
    const out = tickLayerFeatures([young, old], T0_MS + 1_000, 1_800, 7_000);
    expect(out.map((f) => f.source_id)).toEqual(['young']);
  });

  it('never drops when dropAfterS is not given (air: de-emphasize only, spec §2 Aviation)', () => {
    const ancient = feature({ source_id: 'ancient', position_age_s: 1_000_000 });
    const out = tickLayerFeatures([ancient], T0_MS, 60);
    expect(out).toHaveLength(1);
    expect(out[0].deemphasized).toBe(true);
  });

  it('returns a NEW array with NEW feature objects — input is never mutated', () => {
    const input = [feature({ source_id: 'a', position_age_s: 100 })];
    const out = tickLayerFeatures(input, T0_MS, 60);
    expect(out).not.toBe(input);
    expect(out[0]).not.toBe(input[0]);
    expect(input[0].deemphasized).toBeUndefined();
  });
});

// --- Store.tick wiring: config gating, marine-only drop, land exemption ----

function snapshot(domain: 'air' | 'marine' | 'land', features: WireFeature[]): LayerSnapshot {
  return {
    meta: {
      layer: domain,
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: T0_ISO,
      timestamp_source: T0_ISO,
      cadence_s: 60,
      stale_after_s: 120,
      feature_count: features.length,
      retry_after_s: null,
      detail: null,
    },
    features,
  };
}

/** Minimal AppConfig with the only fields tick() reads. */
function config(marineDeemph: number, marineDrop: number, airDeemph = 60): AppConfig {
  return {
    layers: {
      air: { deemphasize_after_s: airDeemph },
      marine: { deemphasize_after_s: marineDeemph, drop_after_s: marineDrop },
      land: {},
    },
  } as AppConfig;
}

describe('Store.tick — config gating, marine drop, land exemption (spec §9, plan unit #3)', () => {
  beforeEach(() => {
    // toggleLayer/applySnapshot are not exercised here, but Store's
    // fire-and-forget POST path must never hit a real network in a unit run.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('is a no-op before setConfig() has supplied thresholds', () => {
    const store = new Store();
    store.applySnapshot('marine', snapshot('marine', [feature({ position_age_s: 9_999 })]));
    const events: string[] = [];
    store.on('tick:marine', () => events.push('tick:marine'));
    store.tick(T0_MS + 1_000);
    expect(events).toEqual([]);
    expect(store.getState().layers.marine.features).toHaveLength(1);
  });

  it('drops an over-age marine vessel and emits tick:marine with the survivor list', () => {
    const store = new Store();
    store.setConfig(config(4, 16));
    store.applySnapshot(
      'marine',
      snapshot('marine', [
        feature({ source_id: 'keeper', position_age_s: 0 }),
        feature({ source_id: 'goner', position_age_s: 100 }),
      ]),
    );
    const payloads: WireFeature[][] = [];
    store.on('tick:marine', (p) => payloads.push(p as WireFeature[]));

    store.tick(T0_MS + 1_000);

    expect(payloads).toHaveLength(1);
    expect(payloads[0].map((f) => f.source_id)).toEqual(['keeper']);
    expect(store.getState().layers.marine.features.map((f) => f.source_id)).toEqual(['keeper']);
  });

  it('de-emphasizes but NEVER drops air (no drop threshold, spec §2 Aviation)', () => {
    const store = new Store();
    store.setConfig(config(4, 16, 60));
    store.applySnapshot('air', snapshot('air', [feature({ domain: 'air', position_age_s: 9_999 })]));

    store.tick(T0_MS + 1_000);

    const air = store.getState().layers.air.features;
    expect(air).toHaveLength(1);
    expect(air[0].deemphasized).toBe(true);
  });

  it('leaves land completely untouched — no tick:land event, features unmodified (spec §2 Land)', () => {
    const store = new Store();
    store.setConfig(config(4, 16));
    const landFeature = feature({ domain: 'land', source_id: 'road-1', position_age_s: 9_999_999 });
    store.applySnapshot('land', snapshot('land', [landFeature]));
    const events: string[] = [];
    store.on('tick:land', () => events.push('tick:land'));

    store.tick(T0_MS + 1_000);

    expect(events).toEqual([]);
    const land = store.getState().layers.land.features;
    expect(land).toHaveLength(1);
    expect(land[0].deemphasized).toBeUndefined();
  });
});
