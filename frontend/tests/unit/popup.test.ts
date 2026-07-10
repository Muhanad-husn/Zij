/**
 * Inner unit tests — plan/frontend/06-marine-integrity.md "Inner loop" unit
 * #5 (marine popup lists flag name(s) inline when `integrity_flags` is
 * non-empty), against `src/map/popup.ts` as actually built.
 *
 * CRITICAL REGRESSION LOCK: MapLibre JSON-STRINGIFIES non-primitive GeoJSON
 * property values (`attrs`, `integrity_flags`) in the tiled representation a
 * layer `click` event delivers (see wireToGeoJson.ts's header note). These
 * tests therefore feed the click handler feature properties in that
 * stringified shape — exactly what broke the first implementation pass
 * (`"[]".length === 2` → truthy → `.join` on a string → `TypeError`). The
 * popup must read the flattened scalar `sog_kn`/`cog_deg` and defensively
 * parse `integrity_flags`.
 *
 * `maplibre-gl`'s Popup needs a real Map to `addTo()` — mocked with a
 * chainable fake that records the DOM content handed to `setDOMContent`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const popupHolder = vi.hoisted(() => ({
  instances: [] as Array<{ content: HTMLElement | null; addedTo: unknown }>,
}));

vi.mock('maplibre-gl', () => {
  class FakePopup {
    content: HTMLElement | null = null;
    addedTo: unknown = null;
    constructor(_options: unknown) {
      popupHolder.instances.push(this);
    }
    setLngLat(_lngLat: unknown) {
      return this;
    }
    setDOMContent(content: HTMLElement) {
      this.content = content;
      return this;
    }
    addTo(map: unknown) {
      this.addedTo = map;
      return this;
    }
  }
  return { default: { Popup: FakePopup } };
});

import { initMarinePopup } from '../../src/map/popup';
import { MARINE_LAYER_ID } from '../../src/map/layers/marine';

type ClickHandler = (e: unknown) => void;

class FakeMap {
  public handlers: Record<string, ClickHandler> = {};
  on(event: string, layerId: string, handler: ClickHandler) {
    this.handlers[`${event}:${layerId}`] = handler;
  }
  getCanvas() {
    return { style: {} as Record<string, string> };
  }
}

/** A click-event feature exactly as MapLibre delivers it: non-primitive
 * property values arrive JSON-STRINGIFIED; flattened scalars stay primitive. */
function clickEvent(props: Record<string, unknown>) {
  return {
    features: [
      {
        geometry: { type: 'Point', coordinates: [56.27, 26.61] },
        properties: props,
      },
    ],
  };
}

function tiledVesselProps(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    source_id: '422011111',
    label: 'SHINE STAR',
    sog_kn: 12.4,
    cog_deg: 341,
    position_age_s: 0,
    attrs: JSON.stringify({ sog_kn: 12.4, cog_deg: 341, heading_deg: 340 }),
    integrity_flags: JSON.stringify([]),
    ...overrides,
  };
}

describe('marine popup — plan unit #5: MMSI/SOG/COG + inline flag naming, tiled (stringified) properties', () => {
  let map: FakeMap;
  let click: ClickHandler;

  beforeEach(() => {
    popupHolder.instances.length = 0;
    map = new FakeMap();
    initMarinePopup(map as never);
    click = map.handlers[`click:${MARINE_LAYER_ID}`];
  });

  function openAndGetContent(props: Record<string, unknown>): HTMLElement {
    click(clickEvent(props));
    const content = popupHolder.instances[0]?.content;
    if (!content) throw new Error('popup content was never set');
    return content;
  }

  it('creates exactly ONE shared Popup instance at wiring time (spec §2 perf budget)', () => {
    expect(popupHolder.instances).toHaveLength(1);
  });

  it('renders MMSI verbatim and SOG/COG from the flattened scalar properties', () => {
    const content = openAndGetContent(tiledVesselProps());
    expect(content.querySelector('[data-testid="popup-mmsi"]')?.textContent).toBe('422011111');
    expect(content.querySelector('[data-testid="popup-sog"]')?.textContent).toContain('12.4');
    expect(content.querySelector('[data-testid="popup-cog"]')?.textContent).toContain('341');
  });

  it('does NOT render popup-flags (and does not throw) for a no-flags vessel whose integrity_flags is the STRING "[]"', () => {
    // The regression: "[]".length === 2 is truthy — the flags branch must not
    // enter, and nothing may throw (`.join` on a string was the original crash).
    const content = openAndGetContent(tiledVesselProps({ integrity_flags: '[]' }));
    expect(content.querySelector('[data-testid="popup-flags"]')).toBeNull();
  });

  it('names a single flag: data-flags carries the raw value, text is human-readable (FR9 "popup names the flag")', () => {
    const content = openAndGetContent(
      tiledVesselProps({ integrity_flags: JSON.stringify(['spoof_suspect_on_land']) }),
    );
    const flags = content.querySelector('[data-testid="popup-flags"]');
    expect(flags?.getAttribute('data-flags')).toBe('spoof_suspect_on_land');
    expect(flags?.textContent ?? '').toMatch(/spoof/i);
  });

  it('comma-joins BOTH raw values and names both flags for a both-flags vessel', () => {
    const content = openAndGetContent(
      tiledVesselProps({ integrity_flags: JSON.stringify(['spoof_suspect_on_land', 'implausible_kinematics']) }),
    );
    const flags = content.querySelector('[data-testid="popup-flags"]');
    expect(flags?.getAttribute('data-flags')).toBe('spoof_suspect_on_land,implausible_kinematics');
    expect(flags?.textContent ?? '').toMatch(/spoof/i);
    expect(flags?.textContent ?? '').toMatch(/kinematics/i);
  });

  it('also accepts a real array (untiled callers, e.g. future direct use)', () => {
    const content = openAndGetContent(tiledVesselProps({ integrity_flags: ['implausible_kinematics'] }));
    expect(content.querySelector('[data-testid="popup-flags"]')?.getAttribute('data-flags')).toBe(
      'implausible_kinematics',
    );
  });

  it('treats malformed integrity_flags JSON as no flags rather than throwing', () => {
    const content = openAndGetContent(tiledVesselProps({ integrity_flags: '{not json' }));
    expect(content.querySelector('[data-testid="popup-flags"]')).toBeNull();
  });

  it('re-clicking a different vessel swaps content on the SAME popup instance (never a second popup)', () => {
    openAndGetContent(tiledVesselProps());
    click(clickEvent(tiledVesselProps({ source_id: '422033333', label: 'GHOST TANKER' })));
    expect(popupHolder.instances).toHaveLength(1);
    expect(
      popupHolder.instances[0].content?.querySelector('[data-testid="popup-mmsi"]')?.textContent,
    ).toBe('422033333');
  });
});
