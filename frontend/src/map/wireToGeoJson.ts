// Wire Feature[] → GeoJSON FeatureCollection (spec §2 "Wire → GeoJSON").
// Points construct their own Point geometry from lat/lon (wire geometry is
// null for points); line/polygon geometry is already valid GeoJSON and used
// as-is. Properties carry `attrs` both flattened top-level AND nested under
// `properties.attrs`, per spec §2 ("flattened alongside attrs object") — this
// lets style expressions use either the flattened key or the two-argument
// `["get", key, ["get", "attrs"]]` form.

import type { WireFeature } from '../state/types';

export function wireToGeoJson(features: WireFeature[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: features.map((f): GeoJSON.Feature => ({
      type: 'Feature',
      geometry:
        f.geometry_type === 'point'
          ? { type: 'Point', coordinates: [f.lon, f.lat] }
          : (f.geometry as GeoJSON.Geometry),
      properties: {
        ...f.attrs,
        attrs: f.attrs,
        domain: f.domain,
        source: f.source,
        source_id: f.source_id,
        label: f.label,
        status: f.status,
        timestamp_source: f.timestamp_source,
        timestamp_fetched: f.timestamp_fetched,
        position_age_s: f.position_age_s,
        integrity_flags: f.integrity_flags,
      },
    })),
  };
}
