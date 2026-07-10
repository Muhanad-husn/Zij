/**
 * Inner unit tests — plan/frontend/06-marine-integrity.md "Inner loop" units
 * #1 (rotation fallback order), #3 (drop is removed-before-setData), and #4
 * (integrity ring filters + concentric both-flags rendering), against
 * `src/map/layers/marine.ts` + `src/map/wireToGeoJson.ts` as actually built.
 *
 * Same FakeMap pattern as tests/unit/aviation.test.ts — records
 * addSource/addLayer calls without WebGL; `maplibre-gl` is only
 * `import type`-ed by marine.ts, so nothing needs mocking.
 *
 * NOTE (tiled-representation constraint, see wireToGeoJson.ts's header):
 * MapLibre JSON-stringifies non-primitive GeoJSON property values in the
 * tiled representation that expressions/filters actually evaluate against.
 * The assertions below deliberately pin the FLATTENED primitive reads
 * (`cog_deg`, `heading_deg`, `flag_*` booleans) — a regression back to the
 * nested `["get", key, ["get","attrs"]]` / `["in", flag, integrity_flags]`
 * forms would silently break rotation and ring matching at runtime.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import {
  KINEMATICS_RING_LAYER_ID,
  MARINE_LAYER_ID,
  MARINE_SOURCE_ID,
  SPOOF_RING_LAYER_ID,
  clearMarineLayer,
  initMarineLayer,
  tickMarineLayer,
  updateMarineLayer,
} from '../../src/map/layers/marine';
import { tickLayerFeatures } from '../../src/state/derive';
import { wireToGeoJson } from '../../src/map/wireToGeoJson';
import type { LayerSnapshot, WireFeature } from '../../src/state/types';

interface RecordedLayer {
  id: string;
  type: string;
  filter?: unknown;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
}

class FakeGeoJSONSource {
  public data: unknown;
  constructor(data: unknown) {
    this.data = data;
  }
  setData(data: unknown) {
    this.data = data;
  }
  serialize() {
    return { data: this.data };
  }
}

class FakeMap {
  public sources: Record<string, FakeGeoJSONSource> = {};
  public layers: RecordedLayer[] = [];
  private images = new Set<string>();

  addSource(id: string, options: { data: unknown }) {
    this.sources[id] = new FakeGeoJSONSource(options.data);
  }
  getSource(id: string) {
    return this.sources[id];
  }
  addLayer(layer: RecordedLayer) {
    this.layers.push(layer);
  }
  getLayer(id: string) {
    return this.layers.find((l) => l.id === id);
  }
  hasImage(id: string) {
    return this.images.has(id);
  }
  addImage(id: string) {
    this.images.add(id);
  }
}

const T0_ISO = '2026-07-10T12:00:00Z';
const T0_MS = Date.parse(T0_ISO);

function vessel(sourceId: string, overrides: Partial<WireFeature> = {}): WireFeature {
  return {
    domain: 'marine',
    source: 'aisstream',
    source_id: sourceId,
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
    attrs: { sog_kn: 12.4, cog_deg: 341.0, heading_deg: 340 },
    ...overrides,
  };
}

function snapshot(features: WireFeature[]): LayerSnapshot {
  return {
    meta: {
      layer: 'marine',
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

function sourceIds(map: FakeMap): string[] {
  const data = map.sources[MARINE_SOURCE_ID].serialize().data as {
    features: Array<{ properties: { source_id: string } }>;
  };
  return data.features.map((f) => f.properties.source_id);
}

describe('initMarineLayer — plan unit #1: symbol layer rotated by cog_deg → heading_deg → upright', () => {
  let map: FakeMap;

  beforeEach(() => {
    document.documentElement.style.removeProperty('--zij-teal');
    map = new FakeMap();
    initMarineLayer(map as never, snapshot([vessel('422011111')]));
  });

  it('adds the "marine" GeoJSON source and the "marine-vessels" symbol layer', () => {
    expect(map.sources[MARINE_SOURCE_ID]).toBeDefined();
    const layer = map.getLayer(MARINE_LAYER_ID);
    expect(layer?.type).toBe('symbol');
  });

  it('icon-rotate coalesces flattened cog_deg first, heading_deg second, 0 (upright) last', () => {
    const rotate = map.getLayer(MARINE_LAYER_ID)?.layout?.['icon-rotate'];
    // The exact fallback ORDER is the unit under test (plan unit #1) — and
    // the flattened single-arg `get` form, never the nested attrs lookup
    // (stringified at expression-eval time, see file-header NOTE).
    expect(rotate).toEqual(['coalesce', ['get', 'cog_deg'], ['get', 'heading_deg'], 0]);
  });

  it('paints icon-color with the teal token (#4E9DB4 fallback in bare jsdom)', () => {
    expect(map.getLayer(MARINE_LAYER_ID)?.paint?.['icon-color']).toBe('#4E9DB4');
  });

  it('icon-opacity is data-driven off the client-computed deemphasized property', () => {
    const opacity = map.getLayer(MARINE_LAYER_ID)?.paint?.['icon-opacity'];
    expect(JSON.stringify(opacity)).toContain('deemphasized');
  });
});

describe('integrity ring layers — plan unit #4: per-flag filters, hollow, distinct, never hidden', () => {
  let map: FakeMap;

  beforeEach(() => {
    map = new FakeMap();
    initMarineLayer(map as never, snapshot([vessel('422033333', { integrity_flags: ['spoof_suspect_on_land'] })]));
  });

  it('adds both rings as circle layers on the marine source, filtered on the flattened flag booleans', () => {
    const spoof = map.getLayer(SPOOF_RING_LAYER_ID);
    const kinematics = map.getLayer(KINEMATICS_RING_LAYER_ID);
    expect(spoof?.type).toBe('circle');
    expect(kinematics?.type).toBe('circle');
    expect(JSON.stringify(spoof?.filter)).toContain('flag_spoof_suspect_on_land');
    expect(JSON.stringify(kinematics?.filter)).toContain('flag_implausible_kinematics');
  });

  it('draws both rings hollow (fully transparent fill) with a nonzero stroke', () => {
    for (const id of [SPOOF_RING_LAYER_ID, KINEMATICS_RING_LAYER_ID]) {
      const paint = map.getLayer(id)?.paint ?? {};
      expect(paint['circle-color']).toBe('rgba(0, 0, 0, 0)');
      expect(Number(paint['circle-stroke-width'])).toBeGreaterThan(0);
    }
  });

  it('uses visually distinct stroke colors for the two rings (spec §2 "distinct color/dash")', () => {
    const spoofStroke = map.getLayer(SPOOF_RING_LAYER_ID)?.paint?.['circle-stroke-color'];
    const kinematicsStroke = map.getLayer(KINEMATICS_RING_LAYER_ID)?.paint?.['circle-stroke-color'];
    expect(spoofStroke).not.toBe(kinematicsStroke);
  });

  it('never sets layout visibility "none" on either ring (NFR3: never conditionally hidden)', () => {
    for (const id of [SPOOF_RING_LAYER_ID, KINEMATICS_RING_LAYER_ID]) {
      expect(map.getLayer(id)?.layout?.visibility).not.toBe('none');
    }
  });

  it('a both-flags vessel gets BOTH flattened flag booleans, so both ring filters match it (concentric)', () => {
    const both = wireToGeoJson([
      vessel('422044444', { integrity_flags: ['spoof_suspect_on_land', 'implausible_kinematics'] }),
    ]);
    const props = both.features[0].properties as Record<string, unknown>;
    expect(props.flag_spoof_suspect_on_land).toBe(true);
    expect(props.flag_implausible_kinematics).toBe(true);
  });

  it('a no-flags vessel gets BOTH flag booleans false — neither ring matches', () => {
    const none = wireToGeoJson([vessel('422011111')]);
    const props = none.features[0].properties as Record<string, unknown>;
    expect(props.flag_spoof_suspect_on_land).toBe(false);
    expect(props.flag_implausible_kinematics).toBe(false);
  });
});

describe('tickMarineLayer — plan unit #3: a dropped vessel is removed from the source data, siblings survive', () => {
  it('re-renders the source from a tick-derived list that already excludes the dropped vessel', () => {
    const map = new FakeMap();
    const keeper = vessel('keeper', { position_age_s: 0 });
    const goner = vessel('goner', { position_age_s: 100 });
    initMarineLayer(map as never, snapshot([keeper, goner]));
    expect(sourceIds(map)).toEqual(['keeper', 'goner']);

    // derive.ts does the removal; tickMarineLayer setDatas the survivors —
    // together this is the "removed from the GeoJSON before setData" unit.
    const survivors = tickLayerFeatures([keeper, goner], T0_MS + 1_000, 4, 16);
    tickMarineLayer(map as never, survivors);

    expect(sourceIds(map)).toEqual(['keeper']);
  });

  it('is a no-op when the marine source was never added (map not yet loaded)', () => {
    const map = new FakeMap();
    expect(() => tickMarineLayer(map as never, [])).not.toThrow();
  });
});

describe('updateMarineLayer / clearMarineLayer — snapshot replace + region-change clear', () => {
  it('a new snapshot replaces (not appends to) the previous feature set', () => {
    const map = new FakeMap();
    initMarineLayer(map as never, snapshot([vessel('a')]));
    updateMarineLayer(map as never, snapshot([vessel('b'), vessel('c')]));
    expect(sourceIds(map)).toEqual(['b', 'c']);
  });

  it('clearMarineLayer empties the source to a zero-feature FeatureCollection', () => {
    const map = new FakeMap();
    initMarineLayer(map as never, snapshot([vessel('a')]));
    clearMarineLayer(map as never);
    const data = map.sources[MARINE_SOURCE_ID].serialize().data as { type: string; features: unknown[] };
    expect(data.type).toBe('FeatureCollection');
    expect(data.features).toHaveLength(0);
  });
});
