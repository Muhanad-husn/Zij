/**
 * Inner unit tests — plan/frontend-map/02-layers-refresh.md "Inner loop" unit
 * #3 (Land line styling), against `src/map/layers/land.ts` as actually built.
 *
 * Same fake-map pattern as tests/unit/aviation.test.ts — only the small
 * `addSource`/`addLayer`/`getSource`/`hasImage`/`addImage` surface is used by
 * `initLandLayer`, so no real MapLibre/WebGL is required.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import {
  LAND_POINTS_LAYER_ID,
  LAND_RAIL_LAYER_ID,
  LAND_ROADS_LAYER_ID,
  LAND_SOURCE_ID,
  clearLandLayer,
  initLandLayer,
} from '../../src/map/layers/land';
import type { LayerSnapshot } from '../../src/state/types';

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

/** Flattens a nested style-expression array into its scalar leaves, in order
 * — same technique the outer e2e spec uses, so this unit test doesn't depend
 * on which expression operator (match/step/case/...) the developer chose. */
function flattenExpression(value: unknown): unknown[] {
  const out: unknown[] = [];
  const walk = (v: unknown) => {
    if (Array.isArray(v)) {
      v.forEach(walk);
    } else {
      out.push(v);
    }
  };
  walk(value);
  return out;
}

function numericValueFollowingLiteral(expr: unknown, literal: string): number {
  const flat = flattenExpression(expr);
  const idx = flat.indexOf(literal);
  if (idx === -1 || typeof flat[idx + 1] !== 'number') {
    throw new Error(`Expected a numeric value immediately after literal "${literal}" in expression: ${JSON.stringify(expr)}`);
  }
  return flat[idx + 1] as number;
}

const SNAPSHOT: LayerSnapshot = {
  meta: {
    layer: 'land',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-05T02:00:11Z',
    timestamp_source: '2026-07-04T00:00:00Z',
    cadence_s: 86400,
    stale_after_s: 172800,
    feature_count: 1,
    retry_after_s: null,
    detail: null,
  },
  features: [
    {
      domain: 'land',
      source: 'overpass',
      source_id: 'way/1001',
      label: 'Coastal Motorway',
      lat: 27.16,
      lon: 56.28,
      geometry_type: 'linestring',
      geometry: {
        type: 'LineString',
        coordinates: [
          [56.28, 27.16],
          [56.31, 27.18],
        ],
      },
      timestamp_source: '2026-07-04T00:00:00Z',
      timestamp_fetched: '2026-07-05T02:00:11Z',
      position_age_s: 118211.0,
      status: 'live',
      integrity_flags: [],
      attrs: { highway: 'motorway', ref: 'E15', surface: 'asphalt' },
    },
  ],
};

describe('initLandLayer — plan unit #3: line-width steps by attrs.highway, motorway thicker than primary', () => {
  let map: FakeMap;

  beforeEach(() => {
    map = new FakeMap();
    initLandLayer(map as never, SNAPSHOT);
  });

  it('adds "land-roads" as a line layer in the dun color', () => {
    const layer = map.getLayer(LAND_ROADS_LAYER_ID);
    expect(layer).toBeDefined();
    expect(layer?.type).toBe('line');
    expect(layer?.paint?.['line-color']).toBe('#A38B62');
  });

  it('widths motorway > trunk > primary in the line-width expression', () => {
    const layer = map.getLayer(LAND_ROADS_LAYER_ID);
    const width = layer?.paint?.['line-width'];

    const motorway = numericValueFollowingLiteral(width, 'motorway');
    const trunk = numericValueFollowingLiteral(width, 'trunk');
    const primary = numericValueFollowingLiteral(width, 'primary');

    expect(motorway).toBeGreaterThan(trunk);
    expect(trunk).toBeGreaterThan(primary);
  });

  it('filters "land-roads" to LineString features only (points render on land-points instead)', () => {
    const layer = map.getLayer(LAND_ROADS_LAYER_ID);
    expect(JSON.stringify(layer?.filter)).toContain('LineString');
  });
});

describe('initLandLayer — bonus unit: land-rail is a dashed line layer', () => {
  it('adds "land-rail" as a line layer with a non-empty line-dasharray', () => {
    const map = new FakeMap();
    initLandLayer(map as never, SNAPSHOT);

    const layer = map.getLayer(LAND_RAIL_LAYER_ID);
    expect(layer).toBeDefined();
    expect(layer?.type).toBe('line');
    const dasharray = layer?.paint?.['line-dasharray'];
    expect(Array.isArray(dasharray)).toBe(true);
    expect((dasharray as unknown[]).length).toBeGreaterThan(0);
  });
});

describe('initLandLayer — plan unit #3: point anchors render as symbols', () => {
  it('adds "land-points" as a symbol layer filtered to Point geometries', () => {
    const map = new FakeMap();
    initLandLayer(map as never, SNAPSHOT);

    const layer = map.getLayer(LAND_POINTS_LAYER_ID);
    expect(layer).toBeDefined();
    expect(layer?.type).toBe('symbol');
    expect(JSON.stringify(layer?.filter)).toContain('Point');
  });
});

describe('initLandLayer — source wiring', () => {
  it('adds the "land" GeoJSON source with one feature per wire feature', () => {
    const map = new FakeMap();
    initLandLayer(map as never, SNAPSHOT);

    expect(map.sources[LAND_SOURCE_ID]).toBeDefined();
    const data = map.sources[LAND_SOURCE_ID].serialize().data as { features: unknown[] };
    expect(data.features).toHaveLength(1);
  });
});

describe('clearLandLayer — plan unit #5 (region_changed): the "land" source is emptied, not merely re-fetched', () => {
  it('replaces a populated source with an empty FeatureCollection', () => {
    const map = new FakeMap();
    initLandLayer(map as never, SNAPSHOT);
    expect((map.sources[LAND_SOURCE_ID].serialize().data as { features: unknown[] }).features).toHaveLength(1);

    clearLandLayer(map as never);

    const data = map.sources[LAND_SOURCE_ID].serialize().data as { type: string; features: unknown[] };
    expect(data.type).toBe('FeatureCollection');
    expect(data.features).toHaveLength(0);
  });

  it('is a no-op when the source was never added (map not yet loaded / layer never initialized)', () => {
    const map = new FakeMap();
    expect(() => clearLandLayer(map as never)).not.toThrow();
    expect(map.sources[LAND_SOURCE_ID]).toBeUndefined();
  });
});
