// App config — spec §1 (config.ts): API base path, map geography, tile provider.
// step only needs the Hormuz geography + the OpenFreeMap source URL; later
// slices add tick interval and SSE retry constants here.

/** Strait of Hormuz bounding box: [west, south, east, north] (PRD §6.4). */
export const HORMUZ_BBOX: readonly [number, number, number, number] = [
  55.0, 25.0, 57.5, 27.5,
];

/** Map center derived from the bbox, [lng, lat] — ~56.25E, 26.25N. */
export const HORMUZ_CENTER: [number, number] = [
  (HORMUZ_BBOX[0] + HORMUZ_BBOX[2]) / 2,
  (HORMUZ_BBOX[1] + HORMUZ_BBOX[3]) / 2,
];

/** Initial zoom framing the strait on a desktop viewport. */
export const INITIAL_ZOOM = 8;

/**
 * OpenFreeMap vector tiles, used as a *source only* (Shortbread schema) under a
 * hand-authored custom style — spec §2 "Base map". This is a TileJSON endpoint;
 * no CDN JS/font is ever pulled (no-CDN rule, spec §2/§8). Tiles may be slow or
 * unreachable in some environments; the map tolerates that (map.ts swallows
 * transient source errors) exactly as it tolerates an unreachable /api.
 */
export const OPENFREEMAP_TILES_URL = 'https://tiles.openfreemap.org/planet';

/** Backend base path (relative origin — ADR-7). */
export const API_BASE = '/api';
