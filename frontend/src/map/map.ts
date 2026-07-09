import maplibregl, {
  Map as MapLibreMap,
  AttributionControl,
  type StyleSpecification,
} from 'maplibre-gl';
import { HORMUZ_CENTER, INITIAL_ZOOM, OPENFREEMAP_TILES_URL } from '../config';

declare global {
  interface Window {
    /** Test seam (locked outer contract): the live Map, set only after `load`. */
    __zijMap?: MapLibreMap;
  }
}

// Attribution is passed explicitly (not left to the tile provider) so the DOM
// deterministically credits both OpenStreetMap and OpenFreeMap — spec §2.
const OSM_ATTRIBUTION = '© OpenStreetMap contributors';
const OPENFREEMAP_ATTRIBUTION = 'OpenFreeMap';

/**
 * Night-ink background color, sourced from the --zij-ink token (spec §8), never
 * a hex literal duplicated per call. Falls back to the known token value only if
 * the stylesheet has not applied (e.g. a bare unit environment).
 */
export function readInkColor(): string {
  const token = getComputedStyle(document.documentElement)
    .getPropertyValue('--zij-ink')
    .trim();
  return token || '#101D30';
}

/**
 * Hand-authored custom style (spec §2 "Base map"): a night-ink `background`
 * layer plus the OpenFreeMap vector source with a couple of recolored context
 * layers. OpenFreeMap's stock light styles are not used — only its tiles.
 */
export function buildStyle(inkColor: string): StyleSpecification {
  return {
    version: 8,
    sources: {
      openfreemap: {
        type: 'vector',
        url: OPENFREEMAP_TILES_URL,
      },
    },
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: { 'background-color': inkColor },
      },
      {
        // Water recolored to the raised-ink step — night identity, not telemetry.
        id: 'water',
        type: 'fill',
        source: 'openfreemap',
        'source-layer': 'water',
        paint: { 'fill-color': '#16283F' },
      },
      {
        // Roads in muted dun (context, per §2 land palette guidance).
        id: 'roads',
        type: 'line',
        source: 'openfreemap',
        'source-layer': 'transportation',
        paint: { 'line-color': '#A38B62', 'line-width': 0.5, 'line-opacity': 0.5 },
      },
    ],
  };
}

/**
 * Boot a single interactive MapLibre map centered on the Hormuz bbox, styled in
 * night-ink, with an always-visible OSM + OpenFreeMap attribution control. The
 * live instance is exposed on `window.__zijMap` only once `load` fires.
 */
export function initMap(container: HTMLElement): MapLibreMap {
  const map = new maplibregl.Map({
    container,
    style: buildStyle(readInkColor()),
    center: HORMUZ_CENTER,
    zoom: INITIAL_ZOOM,
    // Own the attribution control explicitly for deterministic, always-present
    // credit (non-collapsible desktop, compact-collapsible narrow — spec §2).
    attributionControl: false,
  });

  map.addControl(
    new AttributionControl({
      compact: false,
      customAttribution: [OSM_ATTRIBUTION, OPENFREEMAP_ATTRIBUTION],
    }),
  );

  // Surface transient tile/source/network failures (OpenFreeMap slow or
  // unreachable, /api down) without failing the walking skeleton. Logged via
  // console.warn, deliberately not console.error (spec §2; the outer e2e
  // asserts zero console.error, and warnings are ignored by it).
  map.on('error', (e) => {
    console.warn('[zij] map error:', e.error?.message ?? e);
  });

  // `style.load` (fired once the style spec + sources/sprite/glyphs config
  // has been processed, per MapLibre's internal `Style._loaded`) is used
  // rather than the full `load` event (which additionally waits for the
  // *tiles* needed for the first visually complete render, i.e. a real
  // network round trip to the vector tile provider). `getCenter()` /
  // `getPaintProperty()` / the attribution control are all style-level
  // state, not tile-level, so `style.load` already reflects their final
  // values — and add/remove source/layer calls are valid as soon as
  // `style.load` has fired (MapLibre's `_checkLoaded()` guard). Gating this
  // seam on tile-fetch completion would make it needlessly network-latency
  // bound for every consumer of `window.__zijMap`.
  map.on('style.load', () => {
    window.__zijMap = map;
  });

  return map;
}
