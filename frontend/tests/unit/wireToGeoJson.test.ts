/**
 * Unit tests for Wire→GeoJSON conversion in `src/map/wireToGeoJson.ts`.
 *
 * Pure function, no DOM/WebGL dependency — exercised directly against wire
 * `Feature` shapes modeled on `design/contracts/feature-schema.md` ("Wire
 * examples → Air" / "→ Land"), the same fixtures used by the e2e spec.
 */
import { describe, expect, it } from 'vitest';

import { wireToGeoJson } from '../../src/map/wireToGeoJson';
import type { WireFeature } from '../../src/state/types';

const AIR_POINT_FEATURE: WireFeature = {
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
  attrs: {
    altitude_m: 10668.0,
    true_track_deg: 118.4,
    position_source: 'ADS-B',
    on_ground: false,
  },
};

const LAND_LINE_FEATURE: WireFeature = {
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
};

describe('wireToGeoJson — plan unit #1: a point wire Feature (geometry null) becomes a GeoJSON Point', () => {
  it('constructs {type:"Point", coordinates:[lon,lat]} from lat/lon when geometry_type is "point" and geometry is null', () => {
    const fc = wireToGeoJson([AIR_POINT_FEATURE]);

    expect(fc.type).toBe('FeatureCollection');
    expect(fc.features).toHaveLength(1);
    const [feature] = fc.features;
    expect(feature.type).toBe('Feature');
    expect(feature.geometry).toEqual({ type: 'Point', coordinates: [56.27, 26.61] });
  });
});

describe('wireToGeoJson — plan unit #1: a wire LineString geometry passes through unchanged', () => {
  it('uses the wire geometry object verbatim (not reconstructed from lat/lon) for a linestring feature', () => {
    const fc = wireToGeoJson([LAND_LINE_FEATURE]);

    const [feature] = fc.features;
    expect(feature.geometry).toEqual(LAND_LINE_FEATURE.geometry);
  });
});

describe('wireToGeoJson — plan unit #1: source_id is preserved as a top-level properties.source_id', () => {
  it('carries the wire source_id verbatim into properties.source_id (used by future popups/FR2/FR3)', () => {
    const fc = wireToGeoJson([AIR_POINT_FEATURE, LAND_LINE_FEATURE]);

    expect(fc.features[0].properties?.source_id).toBe('896451');
    expect(fc.features[1].properties?.source_id).toBe('way/1001');
  });
});

describe('wireToGeoJson — plan unit #1: attrs/status/timestamp_* are reachable from properties', () => {
  it('flattens attrs top-level AND nests them under properties.attrs, per the two-argument ["get", key, ["get","attrs"]] seam', () => {
    const fc = wireToGeoJson([AIR_POINT_FEATURE]);
    const { properties } = fc.features[0];

    expect(properties).toBeDefined();
    // Flattened top-level (single-argument ["get", key] style expressions).
    expect(properties?.true_track_deg).toBe(118.4);
    expect(properties?.altitude_m).toBe(10668.0);
    // Nested under attrs (two-argument ["get", key, ["get","attrs"]] style expressions).
    expect(properties?.attrs).toEqual(AIR_POINT_FEATURE.attrs);
  });

  it('reaches status and both timestamps directly on properties', () => {
    const fc = wireToGeoJson([AIR_POINT_FEATURE]);
    const { properties } = fc.features[0];

    expect(properties?.status).toBe('live');
    expect(properties?.timestamp_source).toBe('2026-07-06T09:11:58Z');
    expect(properties?.timestamp_fetched).toBe('2026-07-06T09:12:03Z');
  });
});
