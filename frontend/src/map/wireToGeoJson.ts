// Wire Feature[] → GeoJSON FeatureCollection (spec §2 "Wire → GeoJSON").
// Points construct their own Point geometry from lat/lon (wire geometry is
// null for points); line/polygon geometry is already valid GeoJSON and used
// as-is. Properties carry `attrs` both flattened top-level AND nested under
// `properties.attrs`, per spec §2 ("flattened alongside attrs object") — this
// lets style expressions use either the flattened key or the two-argument
// `["get", key, ["get", "attrs"]]` form.
//
// IMPORTANT: MapLibre tiles GeoJSON sources internally (geojson-vt); any
// non-primitive property value (arrays/objects, e.g. `attrs`/
// `integrity_flags`) comes back JSON-STRINGIFIED in the tiled representation
// that style-expression eval, filters, click events, and
// `queryRenderedFeatures` all read (`source.serialize().data` is the one
// exception — it returns this function's ORIGINAL, untiled data verbatim).
// The FLATTENED top-level primitives (`cog_deg`, `sog_kn`, `flag_*` below,
// etc.) are what expressions/filters/click handlers must read — never the
// nested `attrs` object or the raw `integrity_flags` array at eval time.

import type { WireFeature } from '../state/types';

/** `IntegrityFlag` values (feature-schema.md) this module knows how to
 * flatten into a filter-safe boolean property. Open enum — a future flag
 * value not listed here simply gets no `flag_*` boolean (harmless; nothing
 * currently filters on it). */
const KNOWN_INTEGRITY_FLAGS = ['spoof_suspect_on_land', 'implausible_kinematics'] as const;

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
        // Client-computed de-emphasis flag (spec §9) — always present, even
        // before any tick has run, so `icon-opacity` paint wiring is
        // data-driven from the very first render (marine-integrity.spec.ts).
        deemphasized: f.deemphasized ?? false,
        // Flattened per-flag booleans (primitives — safe at filter-eval time,
        // unlike the `integrity_flags` array above, which is stringified in
        // the tiled representation filters actually evaluate against).
        ...Object.fromEntries(
          KNOWN_INTEGRITY_FLAGS.map((flag) => [`flag_${flag}`, f.integrity_flags.includes(flag)]),
        ),
      },
    })),
  };
}
