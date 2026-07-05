/**
 * Inner unit tests — plan/frontend-map/01-map-init.md "Inner loop" units #1 and #4.
 *
 * MapLibre GL JS requires a real WebGL context to construct a `Map` (jsdom has no
 * WebGL — deliberately out of scope, design/docs/TESTING.md §6: "MapLibre rendering
 * correctness ... we only feed it GeoJSON"). So the heavy external library is
 * replaced with a tiny fake that only records constructor options / addControl
 * calls; `initMap` itself (the code under test, from `src/map/map.ts`) is real and
 * unmocked. This proves the *wiring* — that `initMap` hands the Hormuz center/zoom
 * and an `AttributionControl` carrying both credits to the real MapLibre API shape
 * — without needing a GPU.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

interface RecordedMapOptions {
  center: [number, number];
  zoom: number;
  attributionControl: boolean;
  style: unknown;
}

class FakeMap {
  public options: RecordedMapOptions;
  public addedControls: unknown[] = [];
  private handlers: Record<string, Array<(...args: unknown[]) => void>> = {};

  constructor(options: RecordedMapOptions) {
    this.options = options;
  }

  addControl(control: unknown) {
    this.addedControls.push(control);
  }

  on(event: string, cb: (...args: unknown[]) => void) {
    (this.handlers[event] ??= []).push(cb);
  }
}

class FakeAttributionControl {
  public options: { compact?: boolean; customAttribution?: string | string[] };
  constructor(options: { compact?: boolean; customAttribution?: string | string[] } = {}) {
    this.options = options;
  }
}

vi.mock('maplibre-gl', () => ({
  default: { Map: FakeMap, AttributionControl: FakeAttributionControl },
  Map: FakeMap,
  AttributionControl: FakeAttributionControl,
}));

describe('initMap (map factory) — plan unit #1: centered on the Hormuz bbox center at the expected zoom', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('passes the real MapLibre constructor the Hormuz bbox center (~56.25E, 26.25N) and INITIAL_ZOOM', async () => {
    const { initMap } = await import('../../src/map/map');
    const { HORMUZ_CENTER, INITIAL_ZOOM } = await import('../../src/config');

    const container = document.createElement('div');
    const map = initMap(container) as unknown as FakeMap;

    expect(map.options.center).toEqual(HORMUZ_CENTER);
    expect(map.options.center[0]).toBeCloseTo(56.25, 5);
    expect(map.options.center[1]).toBeCloseTo(26.25, 5);
    expect(map.options.zoom).toBe(INITIAL_ZOOM);
  });
});

describe('initMap (map factory) — plan unit #4: AttributionControl carries both OSM + OpenFreeMap credits', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('adds a non-collapsible AttributionControl with OpenStreetMap and OpenFreeMap custom attribution', async () => {
    const { initMap } = await import('../../src/map/map');

    const container = document.createElement('div');
    const map = initMap(container) as unknown as FakeMap;

    expect(map.addedControls).toHaveLength(1);
    const control = map.addedControls[0] as FakeAttributionControl;
    expect(control).toBeInstanceOf(FakeAttributionControl);

    // Non-collapsible per spec §2 ("always present, non-collapsible on desktop").
    expect(control.options.compact).toBe(false);

    const attribution = control.options.customAttribution;
    expect(Array.isArray(attribution)).toBe(true);
    const attributionText = (attribution as string[]).join(' | ');
    expect(attributionText).toContain('OpenStreetMap');
    expect(attributionText).toContain('OpenFreeMap');
  });

  it('does not rely on the tile provider for attribution: attributionControl is disabled on the Map itself', async () => {
    const { initMap } = await import('../../src/map/map');

    const container = document.createElement('div');
    const map = initMap(container) as unknown as FakeMap;

    // initMap must own attribution explicitly (attributionControl: false) and add
    // its own AttributionControl — otherwise OpenFreeMap's tile-provider default
    // attribution (if any) could silently substitute for the required OSM credit.
    expect(map.options.attributionControl).toBe(false);
  });
});
