// Minimal SDF icon atlas (spec §2 "Performance budget": `map.addImage(id,
// data, {sdf:true})`). v0 registers two procedurally-built glyphs — a
// triangle for aircraft, a dot for land point anchors — rather than the
// polished SVG atlas under `public/icons/` (later refinement per the slice
// plan). Registering *some* image keeps `icon-image` populated so symbol
// layers never warn/error about a missing sprite image (the outer test
// asserts zero console errors during load/refresh).

import type { Map as MapLibreMap } from 'maplibre-gl';

export const AIRCRAFT_ICON_ID = 'zij-aircraft';
export const LAND_POINT_ICON_ID = 'zij-land-point';
export const MARINE_VESSEL_ICON_ID = 'zij-marine-vessel';

interface RasterIcon {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

function buildIcon(size: number, isInside: (x: number, y: number, center: number) => boolean): RasterIcon {
  const data = new Uint8ClampedArray(size * size * 4);
  const center = (size - 1) / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const idx = (y * size + x) * 4;
      const alpha = isInside(x, y, center) ? 255 : 0;
      data[idx] = 255;
      data[idx + 1] = 255;
      data[idx + 2] = 255;
      data[idx + 3] = alpha;
    }
  }
  return { width: size, height: size, data };
}

/** Small filled triangle (apex "up"); `icon-rotate` rotates it per-feature. */
function buildTriangle(size = 16): RasterIcon {
  return buildIcon(size, (x, y, center) => {
    const halfWidthAtY = (y / (size - 1)) * center;
    return Math.abs(x - center) <= halfWidthAtY;
  });
}

/** Small filled dot for land point anchors (ports/etc.). */
function buildDot(size = 12): RasterIcon {
  return buildIcon(size, (x, y, center) => {
    const dx = x - center;
    const dy = y - center;
    return dx * dx + dy * dy <= center * center;
  });
}

/** Small filled diamond for marine vessels — visually distinct from the
 * aircraft triangle/land dot while still cheap to build procedurally;
 * `icon-rotate` rotates it per-feature the same way as the aircraft glyph. */
function buildDiamond(size = 14): RasterIcon {
  return buildIcon(size, (x, y, center) => Math.abs(x - center) + Math.abs(y - center) <= center);
}

/** Registers this slice's minimal SDF glyphs. Idempotent — safe to call from
 * more than one layer initializer. */
export function registerIcons(map: MapLibreMap): void {
  if (!map.hasImage(AIRCRAFT_ICON_ID)) {
    map.addImage(AIRCRAFT_ICON_ID, buildTriangle(), { sdf: true });
  }
  if (!map.hasImage(LAND_POINT_ICON_ID)) {
    map.addImage(LAND_POINT_ICON_ID, buildDot(), { sdf: true });
  }
  if (!map.hasImage(MARINE_VESSEL_ICON_ID)) {
    map.addImage(MARINE_VESSEL_ICON_ID, buildDiamond(), { sdf: true });
  }
}
