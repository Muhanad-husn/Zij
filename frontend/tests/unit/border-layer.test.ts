/**
 * OUTER acceptance test (DEC-1) — issue #115: the hand-authored MapLibre style
 * (`buildStyle()`, src/map/map.ts) declares only `background`/`water`/`roads`,
 * so the OpenMapTiles-schema `boundary` source-layer (admin borders) is never
 * added and the map shows no country borders.
 *
 * Locked contract, pinned against `buildStyle()` directly (unit-first per the
 * standing frontend rule — no MapLibre/WebGL/network involved, so a Playwright
 * e2e spec would add nothing a unit spec against the pure style object doesn't
 * already prove):
 *
 *   1. `buildStyle()` includes a `type: 'line'` layer sourced from the
 *      `openfreemap` vector source's `boundary` source-layer.
 *   2. That layer's filter accepts admin_level-2 (country) boundary features
 *      and rejects other admin levels (state/county/etc. — OpenMapTiles uses
 *      2/3/4/6/8/10) — evaluated semantically via the real MapLibre style-spec
 *      filter compiler, not by pattern-matching the filter's on-the-wire shape
 *      (which may legitimately be legacy `['==', 'admin_level', 2]` or
 *      expression `['==', ['get','admin_level'], 2]` syntax).
 *   3. Its `line-color` is a real, non-empty color, and — spec §2 "Base map":
 *      recolored context layers, not telemetry — distinct from both the
 *      night-ink background color and the three reserved domain telemetry
 *      tokens (air/marine/land), so borders read as basemap context, never as
 *      a fourth telemetry layer.
 *   4. The pre-existing `background`/`water`/`roads` layers are untouched and
 *      keep their relative order — the border layer is additive to the base
 *      style, not a replacement, and must not reorder the layers telemetry
 *      renders on top of at runtime.
 *
 * Committed red (xfail-equivalent): `buildStyle()` does not yet add a
 * `boundary` layer, so every assertion below fails. Vitest has no `xfail`;
 * `test.fails` is the strict expected-failure idiom here — it inverts the
 * pass/fail result and, symmetrically to pytest's `strict=True`, itself FAILS
 * the run once the body starts passing (i.e. once the real behavior lands),
 * which is exactly the signal to remove `.fails` and land the final green
 * commit.
 */
import { describe, expect, it, vi } from 'vitest';
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';

// `buildStyle` is a pure function (no WebGL/network), but `src/map/map.ts`
// still imports the `maplibre-gl` value at module scope (for `initMap`) — stub
// it out exactly as the sibling build-style.test.ts does, so importing the
// module under test never requires a real WebGL context. `vi.mock` calls are
// hoisted above imports by Vitest, so ordering here is not load-bearing.
vi.mock('maplibre-gl', () => ({
  default: { Map: class {}, AttributionControl: class {} },
  Map: class {},
  AttributionControl: class {},
}));

interface LineLayer {
  id: string;
  type: string;
  source?: string;
  'source-layer'?: string;
  filter?: unknown;
  paint?: Record<string, unknown>;
}

describe('buildStyle — outer acceptance (#115): country borders in the base-map style', () => {
  it.fails(
    'adds a line layer over the boundary source-layer, filtered to admin_level 2, in a muted context color distinct from telemetry, without disturbing background/water/roads',
    async () => {
      const { buildStyle } = await import('../../src/map/map');

      const inkColor = '#101D30';
      const style = buildStyle(inkColor);
      const layers = style.layers as unknown as LineLayer[];

      // --- 1. a line layer sourced from the boundary source-layer exists ---
      const borderLayers = layers.filter(
        (l) => l.type === 'line' && l['source-layer'] === 'boundary',
      );
      expect(borderLayers.length).toBe(1);
      const border = borderLayers[0];
      expect(border.source).toBe('openfreemap');

      // --- 2. filtered to country level (admin_level == 2), evaluated ---
      // semantically rather than by shape, so either legacy or expression
      // filter syntax satisfies this.
      expect(border.filter).toBeDefined();
      const compiled = featureFilter(border.filter as never);

      const countryFeature = { type: 'Feature' as const, properties: { admin_level: 2 } };
      const stateFeature = { type: 'Feature' as const, properties: { admin_level: 4 } };
      const countyFeature = { type: 'Feature' as const, properties: { admin_level: 6 } };

      expect(compiled.filter({ zoom: 3 }, countryFeature as never)).toBe(true);
      expect(compiled.filter({ zoom: 3 }, stateFeature as never)).toBe(false);
      expect(compiled.filter({ zoom: 3 }, countyFeature as never)).toBe(false);

      // --- 3. color: real, non-empty, distinct from ink and from the three ---
      // reserved domain telemetry tokens (borders are basemap context, never
      // a fourth telemetry layer — spec §2/§8).
      const lineColor = border.paint?.['line-color'];
      expect(typeof lineColor).toBe('string');
      expect((lineColor as string).length).toBeGreaterThan(0);

      const background = layers.find((l) => l.id === 'background');
      expect(background).toBeDefined();
      const backgroundColor = background?.paint?.['background-color'];
      expect(lineColor).not.toBe(backgroundColor);

      const reservedDomainTokens = ['#D99A3B', '#4E9DB4', '#A38B62']; // brass/teal/dun (air/marine/land)
      for (const token of reservedDomainTokens) {
        expect((lineColor as string).toLowerCase()).not.toBe(token.toLowerCase());
      }

      // --- 4. background/water/roads remain present, unchanged, in order ---
      const ids = layers.map((l) => l.id);
      expect(ids).toContain('background');
      expect(ids).toContain('water');
      expect(ids).toContain('roads');
      expect(ids.indexOf('background')).toBeLessThan(ids.indexOf('water'));
      expect(ids.indexOf('water')).toBeLessThan(ids.indexOf('roads'));

      const water = layers.find((l) => l.id === 'water');
      expect(water?.paint?.['fill-color']).toBe('#16283F');
      const roads = layers.find((l) => l.id === 'roads');
      expect(roads?.paint?.['line-color']).toBe('#A38B62');
    },
  );
});
