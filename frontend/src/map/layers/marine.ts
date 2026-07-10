// Marine source + symbol/circle layers (spec §2 "Marine"). Initial add +
// `setData` refresh (SSE snapshot) + tick-driven restyle (§9, client-tick
// de-emphasis/drop) + the two integrity ring overlays (FR9, NFR3). This
// module owns rendering only — it never runs its own timer; `main.ts` wires
// `Store`'s `snapshot:marine`/`tick:marine` events into the functions below.

import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import type { LayerSnapshot, WireFeature } from '../../state/types';
import { readCssVar } from '../../util/cssVar';
import { MARINE_VESSEL_ICON_ID, registerIcons } from '../icons';
import { wireToGeoJson } from '../wireToGeoJson';

export const MARINE_SOURCE_ID = 'marine';
export const MARINE_LAYER_ID = 'marine-vessels';
export const SPOOF_RING_LAYER_ID = 'marine-spoof-ring';
export const KINEMATICS_RING_LAYER_ID = 'marine-kinematics-ring';

/** `icon-rotate`: prefer `attrs.cog_deg` (COG per FR3), fall back to
 * `attrs.heading_deg` when `cog_deg` is null, else render upright (spec §2
 * Marine + its own resolution NOTE — `sog_kn`/`cog_deg` may legitimately be
 * absent per feature-schema.md nullability). Reads the FLATTENED top-level
 * `cog_deg`/`heading_deg` properties, NOT the two-argument `["get", key,
 * ["get","attrs"]]` form — `attrs` comes back JSON-STRINGIFIED in the tiled
 * representation style expressions actually evaluate against (MapLibre tiles
 * GeoJSON sources internally via geojson-vt, see wireToGeoJson.ts's own
 * header note), so a nested lookup would silently resolve to nothing and
 * vessels would never actually rotate. */
const ICON_ROTATE_EXPRESSION: unknown[] = ['coalesce', ['get', 'cog_deg'], ['get', 'heading_deg'], 0];

/** Data-driven off the client-computed `deemphasized` GeoJSON property (§9) —
 * `wireToGeoJson` always sets this (default `false`), so the wiring exists
 * from the very first render, before any tick has fired. */
const ICON_OPACITY_EXPRESSION: unknown[] = ['case', ['==', ['get', 'deemphasized'], true], 0.35, 1];

/** Hollow (stroke-only) circle fill shared by both integrity rings — fully
 * transparent so only the stroke renders. */
const HOLLOW_FILL = 'rgba(0, 0, 0, 0)';

/** Adds the `marine` GeoJSON source, the `marine-vessels` symbol layer, and
 * the two integrity ring circle layers. Call once, after the base style's
 * `load` fires. */
export function initMarineLayer(map: MapLibreMap, snapshot: LayerSnapshot): void {
  registerIcons(map);

  map.addSource(MARINE_SOURCE_ID, {
    type: 'geojson',
    data: wireToGeoJson(snapshot.features),
  });

  map.addLayer({
    id: MARINE_LAYER_ID,
    type: 'symbol',
    source: MARINE_SOURCE_ID,
    layout: {
      'icon-image': MARINE_VESSEL_ICON_ID,
      'icon-size': 0.75,
      'icon-allow-overlap': true,
      'icon-rotate': ICON_ROTATE_EXPRESSION as never,
      'icon-rotation-alignment': 'map',
    },
    paint: {
      'icon-color': readCssVar('--zij-teal', '#4E9DB4'),
      'icon-opacity': ICON_OPACITY_EXPRESSION as never,
    },
  });

  // Integrity rings (FR9, NFR3 "never conditionally hidden") — hollow
  // stroke-only circles filtered over the SAME source, drawn above the base
  // symbol layer (added after it). A vessel carrying both flags renders both
  // rings concentrically; the two filters are independent, mutually
  // non-exclusive checks. Filtered on `wireToGeoJson`'s flattened
  // `flag_<name>` BOOLEAN properties, not `["in", <flag>, ["get",
  // "integrity_flags"]]` — `integrity_flags` (an array) comes back
  // JSON-STRINGIFIED in the tiled representation filters actually evaluate
  // against, which would make `in` do unreliable substring matching over
  // that JSON text instead of a real membership check.
  map.addLayer({
    id: SPOOF_RING_LAYER_ID,
    type: 'circle',
    source: MARINE_SOURCE_ID,
    filter: ['==', ['get', 'flag_spoof_suspect_on_land'], true],
    paint: {
      'circle-radius': 11,
      'circle-color': HOLLOW_FILL,
      'circle-stroke-width': 2,
      'circle-stroke-color': '#E4572E',
    },
  });

  map.addLayer({
    id: KINEMATICS_RING_LAYER_ID,
    type: 'circle',
    source: MARINE_SOURCE_ID,
    filter: ['==', ['get', 'flag_implausible_kinematics'], true],
    paint: {
      'circle-radius': 16,
      'circle-color': HOLLOW_FILL,
      'circle-stroke-width': 2,
      'circle-stroke-color': '#F2C14E',
    },
  });
}

/** Re-renders the marine source from a fresh SSE `snapshot:marine` event. */
export function updateMarineLayer(map: MapLibreMap, snapshot: LayerSnapshot): void {
  const source = map.getSource(MARINE_SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData(wireToGeoJson(snapshot.features));
}

/** Client-tick restyle (§9) — re-renders from a recomputed feature list
 * (`Store.tick`/`state/derive.ts` has already flipped `deemphasized` and
 * dropped expired vessels entirely); `meta` is untouched by ticking. */
export function tickMarineLayer(map: MapLibreMap, features: WireFeature[]): void {
  const source = map.getSource(MARINE_SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData(wireToGeoJson(features));
}

/** Clears the `marine` source to zero features (spec §6: "all layer panes
 * clear immediately" on `region_changed`). No-op if the source hasn't been
 * added yet (map not loaded / layer never initialized). */
export function clearMarineLayer(map: MapLibreMap): void {
  const source = map.getSource(MARINE_SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData({ type: 'FeatureCollection', features: [] });
}
