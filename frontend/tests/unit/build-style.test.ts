/**
 * Inner unit tests — plan/frontend-map/01-map-init.md "Inner loop" units #2 and #3.
 *
 * `maplibre-gl` is mocked out entirely here (a minimal stand-in for the value
 * import in src/map/map.ts) because these tests only exercise the pure
 * `buildStyle`/`readInkColor` functions and must not depend on a real WebGL
 * context (none exists in jsdom).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('maplibre-gl', () => ({
  default: { Map: class {}, AttributionControl: class {} },
  Map: class {},
  AttributionControl: class {},
}));

describe('buildStyle — plan unit #2: background paint is --zij-ink, parameterized (not a per-call hardcoded literal)', () => {
  beforeEach(() => {
    vi.resetModules();
    document.documentElement.style.removeProperty('--zij-ink');
  });

  it('readInkColor() reads the --zij-ink custom property from the document, and buildStyle uses exactly that value', async () => {
    const { buildStyle, readInkColor } = await import('../../src/map/map');

    // jsdom does not apply imported stylesheets, so the token is set inline —
    // this is what the real page does via styles/tokens.css's `:root { --zij-ink: #101D30; }`.
    document.documentElement.style.setProperty('--zij-ink', '#101D30');

    const ink = readInkColor();
    expect(ink).toBe('#101D30');

    const style = buildStyle(ink);
    const background = style.layers.find((l) => l.id === 'background');
    expect(background).toBeDefined();
    expect((background as { paint: { 'background-color': string } }).paint['background-color']).toBe(
      '#101D30',
    );
  });

  it('buildStyle is parameterized, not hardcoded: a different ink color produces a different background', async () => {
    const { buildStyle } = await import('../../src/map/map');

    const style = buildStyle('#123456');
    const background = style.layers.find((l) => l.id === 'background');
    expect((background as { paint: { 'background-color': string } }).paint['background-color']).toBe(
      '#123456',
    );
  });

  it('readInkColor falls back to the known token value if the stylesheet has not applied (bare unit env)', async () => {
    const { readInkColor } = await import('../../src/map/map');

    // No --zij-ink set on documentElement in this test (cleared in beforeEach).
    expect(readInkColor()).toBe('#101D30');
  });
});

describe('buildStyle — plan unit #3: tile source points at the configured OpenFreeMap provider, not a CDN', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('the vector source URL is exactly OPENFREEMAP_TILES_URL from config.ts', async () => {
    const { buildStyle } = await import('../../src/map/map');
    const { OPENFREEMAP_TILES_URL } = await import('../../src/config');

    expect(OPENFREEMAP_TILES_URL).toBe('https://tiles.openfreemap.org/planet');

    const style = buildStyle('#101D30');
    const source = style.sources.openfreemap as { type: string; url: string };
    expect(source.type).toBe('vector');
    expect(source.url).toBe(OPENFREEMAP_TILES_URL);
  });

  it('is not a CDN style/tile URL (no unpkg/jsdelivr/cdn host, no bundled CDN JS asset)', async () => {
    const { buildStyle } = await import('../../src/map/map');

    const style = buildStyle('#101D30');
    const source = style.sources.openfreemap as { url: string };
    expect(source.url).not.toMatch(/unpkg\.com|jsdelivr\.net|cdn\./i);
    expect(source.url).toContain('tiles.openfreemap.org');

    // All layers styled against this source use it by reference, not a second
    // ad hoc source — one source of truth for the tile provider.
    const nonBackgroundLayers = style.layers.filter((l) => l.id !== 'background') as Array<{
      source?: string;
    }>;
    expect(nonBackgroundLayers.length).toBeGreaterThan(0);
    for (const layer of nonBackgroundLayers) {
      expect(layer.source).toBe('openfreemap');
    }
  });
});
