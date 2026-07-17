// Land source + line/point layers (spec §2 "Land"). Land is rebuilt once per
// snapshot only (no client tick, per spec): initial add + `setData` refresh.

import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import type { LayerSnapshot } from '../../state/types';
import { readCssVar } from '../../util/cssVar';
import { LAND_POINT_ICON_ID, registerIcons } from '../icons';
import { wireToGeoJson } from '../wireToGeoJson';

export const LAND_SOURCE_ID = 'land';
export const LAND_ROADS_LAYER_ID = 'land-roads';
export const LAND_RAIL_LAYER_ID = 'land-rail';
export const LAND_POINTS_LAYER_ID = 'land-points';

/** Line width stepped by `attrs.highway` (motorway thickest, then trunk, then
 * primary — spec §2). Literal-immediately-followed-by-its-width so any
 * flattening of this expression reads the pairs directly. */
const ROAD_WIDTH_EXPRESSION: unknown[] = [
  'match',
  ['get', 'highway', ['get', 'attrs']],
  'motorway',
  4,
  'trunk',
  3,
  'primary',
  2,
  1,
];

/** Adds the `land` GeoJSON source and its line/point layers. Call once, after
 * the base style's `load` fires. */
export function initLandLayer(map: MapLibreMap, snapshot: LayerSnapshot): void {
  registerIcons(map);

  const dun = readCssVar('--zij-dun', '#A38B62');

  map.addSource(LAND_SOURCE_ID, {
    type: 'geojson',
    data: wireToGeoJson(snapshot.features),
  });

  map.addLayer({
    id: LAND_ROADS_LAYER_ID,
    type: 'line',
    source: LAND_SOURCE_ID,
    filter: ['all', ['==', ['geometry-type'], 'LineString'], ['has', 'highway']],
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: {
      'line-color': dun,
      'line-width': ROAD_WIDTH_EXPRESSION as never,
      'line-opacity': 0.85,
    },
  });

  map.addLayer({
    id: LAND_RAIL_LAYER_ID,
    type: 'line',
    source: LAND_SOURCE_ID,
    filter: ['==', ['get', 'railway', ['get', 'attrs']], 'rail'],
    layout: { 'line-join': 'round' },
    paint: {
      'line-color': dun,
      'line-width': 1,
      'line-dasharray': [2, 2],
      'line-opacity': 0.7,
    },
  });

  map.addLayer({
    id: LAND_POINTS_LAYER_ID,
    type: 'symbol',
    source: LAND_SOURCE_ID,
    filter: ['==', ['geometry-type'], 'Point'],
    layout: {
      'icon-image': LAND_POINT_ICON_ID,
      'icon-size': 0.6,
      'icon-allow-overlap': true,
    },
    paint: {
      'icon-color': dun,
    },
  });
}

/** Re-renders the land source from a fresh snapshot (poll-once refresh —
 * spec §7 "Refresh all"). */
export function updateLandLayer(map: MapLibreMap, snapshot: LayerSnapshot): void {
  const source = map.getSource(LAND_SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData(wireToGeoJson(snapshot.features));
}

/** Clears the `land` source to zero features (spec §6: "all layer panes
 * clear immediately" on `region_changed`). No-op if the source hasn't been
 * added yet (map not loaded / layer never initialized). */
export function clearLandLayer(map: MapLibreMap): void {
  const source = map.getSource(LAND_SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData({ type: 'FeatureCollection', features: [] });
}
