/**
 * DEC-1 locked outer acceptance test — frontend-map/01-map-init (issue #19), the
 * v0 walking skeleton. Committed RED-BY-CONSTRUCTION: `frontend/` does not exist
 * yet (no Vite app, no MapLibre init, no Playwright config), so this test cannot
 * even run today — that absence *is* the honest red for a greenfield slice. Once
 * the implementer scaffolds `frontend/` and builds `map/map.ts` per
 * `design/specs/frontend.md` §2/§8 and `plans/frontend-map/01-map-init.md`, this
 * file starts running for real.
 *
 * Locked contract clauses (each must be independently satisfied, not just the
 * union): canvas mounts; map is centered on the Hormuz region; attribution shows
 * both "OpenStreetMap" and "OpenFreeMap"; the map background is the night-ink
 * color `--zij-ink` (#101D30), not the default light basemap; zero uncaught
 * console errors during load.
 *
 * REQUIRED TEST SEAM (implementer must expose this — not the test-author's to
 * relax): after the map's `load` event fires, the app must assign the live
 * MapLibre `Map` instance to `window.__zijMap`. This is the only way to read
 * WebGL-backed state (center, paint properties) that isn't observable from the
 * DOM. Shape:
 *
 *   declare global { interface Window { __zijMap?: import('maplibre-gl').Map } }
 *
 * `window.__zijMap` must be set only once the instance has fired `load` (so
 * `getCenter()`/`getPaintProperty()` reflect the final, styled state) — e.g.
 * `map.on('load', () => { (window as any).__zijMap = map; })`.
 *
 * This test is not the test-author's to loosen and not the implementer's to
 * touch.
 *
 * RECONCILIATION (slice frontend-map/02-layers-refresh, issue #20): slice 02
 * made the app fetch `GET /api/layers/{air,land}/snapshot` on the map's `load`
 * event. This test has no live FastAPI backend (playwright.config.ts serves
 * only the built static bundle), so those two requests 404/500 through Vite's
 * preview proxy, each logging a `console.error`, which trips this test's
 * existing "zero console errors" clause even though the map itself boots
 * cleanly. This is a genuine change to the app's boot post-condition, not a
 * loosening of any locked clause: a `page.route('**\/api/**')` stub is added
 * below, registered before `page.goto('/')`, fulfilling both snapshot
 * endpoints with a minimal valid empty `LayerSnapshot` (shape per
 * `design/contracts/feature-schema.md`) so the data-layer fetches the app now
 * issues on load succeed quietly. This test still asserts nothing about the
 * air/land layers themselves (that's `layers-refresh.spec.ts`'s job) — it
 * stays a pure map-boot test. All five original clauses below are unchanged.
 */

import { test, expect } from '@playwright/test';

/** Minimal valid empty LayerSnapshot per design/contracts/feature-schema.md
 * §"LayerSnapshot & metadata". Only used to keep the app's on-load snapshot
 * fetches (added in slice 02) from 404/500-ing against this test's live-backend-less
 * preview server; this test asserts nothing about the resulting layers. */
function emptySnapshot(layer: 'air' | 'land') {
  return {
    meta: {
      layer,
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: '2026-07-06T09:12:03Z',
      timestamp_source: '2026-07-06T09:11:58Z',
      cadence_s: layer === 'air' ? 600 : 86400,
      stale_after_s: layer === 'air' ? 1200 : 172800,
      feature_count: 0,
      retry_after_s: null,
      detail: null,
    },
    features: [],
  };
}

async function stubApi(page: import('@playwright/test').Page) {
  await page.route('**/api/refresh', async (route) => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ queued: ['air', 'land'] }),
    });
  });

  await page.route('**/api/layers/air/snapshot', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(emptySnapshot('air')),
    });
  });

  await page.route('**/api/layers/land/snapshot', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(emptySnapshot('land')),
    });
  });
}

test(
  'Hormuz map boots in night-ink with OSM + OpenFreeMap attribution and no console errors',
  async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    // Registered BEFORE navigation so nothing fired during initial load is missed.
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });

    // Route interception MUST be registered before goto — see RECONCILIATION
    // note above the imports.
    await stubApi(page);

    await page.goto('/');

    // --- Clause: canvas mounts ---------------------------------------------
    const canvas = page.locator('.maplibregl-canvas');
    await expect(canvas).toBeVisible();

    // --- Test seam: wait for the implementer-exposed live Map instance -----
    await page.waitForFunction(() => Boolean((window as unknown as { __zijMap?: unknown }).__zijMap));

    // --- Clause: centered on the Hormuz region (~26.25N, 56.25E) -----------
    const center = await page.evaluate(() => {
      const map = (window as unknown as {
        __zijMap: { getCenter(): { lng: number; lat: number } };
      }).__zijMap;
      const c = map.getCenter();
      return { lng: c.lng, lat: c.lat };
    });
    expect(center.lng).toBeGreaterThan(56.25 - 0.5);
    expect(center.lng).toBeLessThan(56.25 + 0.5);
    expect(center.lat).toBeGreaterThan(26.25 - 0.5);
    expect(center.lat).toBeLessThan(26.25 + 0.5);

    // --- Clause: night-ink background (#101D30), not the default light style
    // MapLibre may normalize the paint value to an rgba() string rather than
    // echo back the hex literal, so assert on the normalized RGB channels
    // rather than a brittle raw-string match against "#101D30".
    const backgroundColor = await page.evaluate(() => {
      const map = (window as unknown as {
        __zijMap: { getPaintProperty(layer: string, prop: string): unknown };
      }).__zijMap;
      return map.getPaintProperty('background', 'background-color');
    });

    function normalizeToRgb(value: unknown): [number, number, number] {
      const s = String(value).trim();
      const hexMatch = /^#([0-9a-fA-F]{6})$/.exec(s);
      if (hexMatch) {
        const hex = hexMatch[1];
        return [
          parseInt(hex.slice(0, 2), 16),
          parseInt(hex.slice(2, 4), 16),
          parseInt(hex.slice(4, 6), 16),
        ];
      }
      const rgbaMatch = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(s);
      if (rgbaMatch) {
        return [Number(rgbaMatch[1]), Number(rgbaMatch[2]), Number(rgbaMatch[3])];
      }
      throw new Error(`Unrecognized paint color format: ${s}`);
    }

    const [r, g, b] = normalizeToRgb(backgroundColor);
    // --zij-ink: #101D30 -> rgb(16, 29, 48)
    expect(r).toBe(16);
    expect(g).toBe(29);
    expect(b).toBe(48);

    // --- Clause: attribution control shows OSM + OpenFreeMap credit --------
    const attribution = page.locator('.maplibregl-ctrl-attrib');
    await expect(attribution).toBeVisible();
    const attributionText = await attribution.innerText();
    expect(attributionText).toContain('OpenStreetMap');
    expect(attributionText).toContain('OpenFreeMap');

    // --- Clause: no uncaught console error / page error during load --------
    expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
    expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
  }
);
