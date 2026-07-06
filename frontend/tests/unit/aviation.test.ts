/**
 * Inner unit tests — plan/frontend-map/02-layers-refresh.md "Inner loop" unit
 * #2 (Aviation symbol config), against `src/map/layers/aviation.ts` as
 * actually built.
 *
 * `initAviationLayer`/`updateAviationLayer` take a real MapLibre `Map`, but
 * only ever call the small subset of its API (`addSource`/`addLayer`/
 * `getSource`/`hasImage`/`addImage`) — a fake stand-in records those calls
 * without needing WebGL (same pattern as tests/unit/map-factory.test.ts from
 * step). `maplibre-gl` itself is only `import type`-ed here, so it is
 * never actually loaded at runtime and needs no vi.mock.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { AIR_LAYER_ID, AIR_SOURCE_ID, initAviationLayer, updateAviationLayer } from '../../src/map/layers/aviation';
import type { LayerSnapshot } from '../../src/state/types';

interface RecordedLayer {
  id: string;
  type: string;
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

const SNAPSHOT: LayerSnapshot = {
  meta: {
    layer: 'air',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-06T09:12:03Z',
    timestamp_source: '2026-07-06T09:11:58Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 1,
    retry_after_s: null,
    detail: null,
  },
  features: [
    {
      domain: 'air',
      source: 'opensky',
      source_id: '896451',
      label: 'IRA655',
      lat: 26.61,
      lon: 56.27,
      geometry_type: 'point',
      geometry: null,
      timestamp_source: '2026-07-06T09:11:58Z',
      timestamp_fetched: '2026-07-06T09:12:03Z',
      position_age_s: 5.0,
      status: 'live',
      integrity_flags: [],
      attrs: { true_track_deg: 118.4 },
    },
  ],
};

describe('initAviationLayer — plan unit #2: air-aircraft is a symbol layer rotated by true_track_deg in the brass color', () => {
  let map: FakeMap;

  beforeEach(() => {
    document.documentElement.style.removeProperty('--zij-brass');
    map = new FakeMap();
    initAviationLayer(map as never, SNAPSHOT);
  });

  it('adds the "air" GeoJSON source with one feature per wire feature', () => {
    expect(map.sources[AIR_SOURCE_ID]).toBeDefined();
    const data = map.sources[AIR_SOURCE_ID].serialize().data as { features: unknown[] };
    expect(data.features).toHaveLength(1);
  });

  it('adds "air-aircraft" as a symbol layer whose icon-rotate references true_track_deg', () => {
    const layer = map.getLayer(AIR_LAYER_ID);
    expect(layer).toBeDefined();
    expect(layer?.type).toBe('symbol');
    expect(JSON.stringify(layer?.layout?.['icon-rotate'])).toContain('true_track_deg');
  });

  it('paints icon-color with the brass token (#D99A3B fallback in a bare jsdom env with no stylesheet applied)', () => {
    const layer = map.getLayer(AIR_LAYER_ID);
    expect(layer?.paint?.['icon-color']).toBe('#D99A3B');
  });

  it('paints icon-color with the live --zij-brass custom property when the stylesheet has applied it', () => {
    document.documentElement.style.setProperty('--zij-brass', '#123456');
    const liveMap = new FakeMap();
    initAviationLayer(liveMap as never, SNAPSHOT);
    const layer = liveMap.getLayer(AIR_LAYER_ID);
    expect(layer?.paint?.['icon-color']).toBe('#123456');
  });
});

describe('updateAviationLayer — plan unit #5 (refresh idempotency): re-applying the same snapshot yields the same source data', () => {
  it('setData replaces the source contents fully; the same snapshot applied twice yields the same feature count/ids', () => {
    const map = new FakeMap();
    initAviationLayer(map as never, SNAPSHOT);

    updateAviationLayer(map as never, SNAPSHOT);
    const first = map.sources[AIR_SOURCE_ID].serialize().data as {
      features: Array<{ properties: { source_id: string } }>;
    };

    updateAviationLayer(map as never, SNAPSHOT);
    const second = map.sources[AIR_SOURCE_ID].serialize().data as {
      features: Array<{ properties: { source_id: string } }>;
    };

    expect(second.features).toHaveLength(first.features.length);
    expect(second.features.map((f) => f.properties.source_id)).toEqual(
      first.features.map((f) => f.properties.source_id),
    );
  });

  it('re-renders from a NEW snapshot (different feature set replaces, not appends, the old one)', () => {
    const map = new FakeMap();
    initAviationLayer(map as never, SNAPSHOT);

    const refreshed: LayerSnapshot = {
      ...SNAPSHOT,
      meta: { ...SNAPSHOT.meta, feature_count: 2 },
      features: [
        ...SNAPSHOT.features,
        { ...SNAPSHOT.features[0], source_id: '896453', label: 'QTR118' },
      ],
    };
    updateAviationLayer(map as never, refreshed);

    const data = map.sources[AIR_SOURCE_ID].serialize().data as {
      features: Array<{ properties: { source_id: string } }>;
    };
    expect(data.features.map((f) => f.properties.source_id)).toEqual(['896451', '896453']);
  });
});
