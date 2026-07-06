// Air source + symbol layer (spec §2 "Aviation"). This slice: initial add +
// `setData` refresh only — de-emphasis/popups/tick-driven restyle are later
// slices' concern (§9 is SSE/tick driven; v0 REST-only here).

import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import type { LayerSnapshot } from '../../state/types';
import { readCssVar } from '../../util/cssVar';
import { AIRCRAFT_ICON_ID, registerIcons } from '../icons';
import { wireToGeoJson } from '../wireToGeoJson';

export const AIR_SOURCE_ID = 'air';
export const AIR_LAYER_ID = 'air-aircraft';

/** Adds the `air` GeoJSON source and the `air-aircraft` symbol layer. Call
 * once, after the base style's `load` fires. */
export function initAviationLayer(map: MapLibreMap, snapshot: LayerSnapshot): void {
  registerIcons(map);

  map.addSource(AIR_SOURCE_ID, {
    type: 'geojson',
    data: wireToGeoJson(snapshot.features),
  });

  map.addLayer({
    id: AIR_LAYER_ID,
    type: 'symbol',
    source: AIR_SOURCE_ID,
    layout: {
      'icon-image': AIRCRAFT_ICON_ID,
      'icon-size': 0.75,
      'icon-allow-overlap': true,
      // Data-driven off attrs.true_track_deg (spec §2 "Aviation"); the
      // two-argument `["get", key, ["get","attrs"]]` form reaches the
      // nested attrs object without needing a flattened top-level key.
      'icon-rotate': ['coalesce', ['get', 'true_track_deg', ['get', 'attrs']], 0],
      'icon-rotation-alignment': 'map',
    },
    paint: {
      'icon-color': readCssVar('--zij-brass', '#D99A3B'),
    },
  });
}

/** Re-renders the air source from a fresh snapshot (poll-once refresh, no SSE
 * this slice — spec §7 "Refresh all"). */
export function updateAviationLayer(map: MapLibreMap, snapshot: LayerSnapshot): void {
  const source = map.getSource(AIR_SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData(wireToGeoJson(snapshot.features));
}
