/**
 * DEC-1 locked outer acceptance test — frontend-map/02-layers-refresh (issue
 * #20), the last v0 slice. Encodes `plans/frontend-map/02-layers-refresh.md`'s
 * Gherkin verbatim:
 *
 *   Given the backend serving air and land snapshots for Hormuz
 *   When  the page loads
 *   Then  aircraft symbols render on the map, rotated by true_track_deg, in
 *         the brass domain color
 *   And   land roads render as dun lines (motorway thickest) and point
 *         anchors render as symbols
 *   And   each layer shows both timestamps labeled in UTC and a feature count
 *   When  the Refresh button is clicked
 *   Then  POST /api/refresh is issued and the layers re-render from the new
 *         snapshots
 *
 * `test.fail()` was this web slice's analog to a strict pytest xfail (DEC-33):
 * it marked the scenario "expected to fail," so an unexpected *pass* failed
 * the run — mirroring "xfail(strict=True) turned XPASS, blocking commits
 * until the marker is removed." The implementer greened every clause below
 * (commit `defb2c0`); the test-author confirmed each assertion passes (see
 * the slice's evidence trace) and removed the `test.fail()` marker in this
 * final pass, so the scenario now runs as a normal `test(...)` and is
 * expected to pass for real.
 *
 * This slice has no live backend in the e2e run (`playwright.config.ts`
 * serves the production `vite build` + `vite preview` bundle on :4173, no
 * FastAPI process). All `/api/**` calls are intercepted with `page.route()`
 * and fulfilled from the fixtures below, modeled verbatim on the wire shapes
 * in `design/contracts/feature-schema.md` ("Wire examples → Air" / "→ Land").
 * SSE, region selection, layer toggles, caveats, and integrity markers are
 * explicitly out of scope for this slice (see the plan) — only the two REST
 * snapshot endpoints and the manual refresh endpoint are exercised.
 *
 * RECONCILIATION (slice frontend/01-sse-client, issue #57): the app now
 * unconditionally opens `EventSource('/api/events')` on load (spec §3). This
 * test has no live FastAPI backend, so an unstubbed `/api/events` would
 * error through Vite's preview proxy, logging a `console.error` this test
 * doesn't check for directly but which is still a genuine regression to the
 * app's boot post-condition — the same class of reconciliation
 * `map-init.spec.ts` already documents for the snapshot endpoints.
 * `tests/e2e/helpers/quietSseStub.ts` (a real, held-open streaming stub — see
 * its own comment for why a `page.route().fulfill()` stub can't safely stand
 * in here) is used below; this test doesn't exercise SSE and asserts nothing
 * about the connection banner. The banner's own non-blocking
 * `pointer-events: none` (layout.css) is what already keeps a
 * connection-lost state from swallowing the Refresh button's clicks, should
 * the stream ever error mid-test.
 *
 * RECONCILIATION (slice frontend/03-region-selector, issue #59): the app now
 * unconditionally fetches `GET /api/regions` and `GET /api/regions/active`
 * on load (region dropdown population + last-region restore). This test has
 * no live FastAPI backend, so those unstubbed calls would leak through
 * Vite's preview proxy to a connection refused, logging a browser
 * `console.error` that would trip this test's "zero console errors" clause
 * even though the layer rendering/refresh behavior this test actually
 * exercises works fine — the same class of reconciliation the SSE note above
 * already documents. `tests/e2e/helpers/stubRegionEndpoints.ts` is used
 * below to answer both quietly; this test asserts nothing about regions
 * (that's `region-selector.spec.ts`'s job).
 *
 * RECONCILIATION (slice frontend/06-marine-integrity, issue #62): the app
 * now unconditionally fetches `GET /api/config` on load (the client tick
 * reads de-emphasis/drop thresholds from it, spec §9). This test has no live
 * FastAPI backend, so an unstubbed call would leak through Vite's preview
 * proxy the same way the reconciliations above already document.
 * `tests/e2e/helpers/stubConfigEndpoint.ts` answers it quietly; this test
 * asserts nothing about tick/de-emphasis behavior (that's
 * `marine-integrity.spec.ts`'s job).
 *
 * REQUIRED TEST SEAMS (implementer must expose these — not the test-author's
 * to relax; each is independently asserted below):
 *
 *   1. `window.__zijMap` — the live MapLibre `Map`, assigned on `load` (the
 *      slice-01 seam, reused verbatim; see `map-init.spec.ts`).
 *   2. GeoJSON source ids: exactly `"air"` and `"land"` (`map.getSource(id)`).
 *      Each source's data (readable via the public `GeoJSONSource#serialize()`
 *      → `.data`, no need to wait for a render pass) must carry one GeoJSON
 *      Feature per wire Feature, with the wire `source_id` preserved verbatim
 *      as a top-level GeoJSON `properties.source_id` (so tests — and future
 *      popups, FR2/FR3 — can identify a rendered feature). `attrs` values
 *      (e.g. `true_track_deg`, `highway`) must be reachable from a MapLibre
 *      style expression by *some* form (flattened top-level `["get", ...]` or
 *      the two-argument `["get", key, ["get", "attrs"]]` form per spec
 *      §2 "Wire → GeoJSON") — this test does not care which, only that the
 *      resulting paint/layout expression demonstrably references the key.
 *   3. Layer ids:
 *        - `"air-aircraft"` — symbol layer, `icon-rotate` data-driven off
 *          `true_track_deg`, `icon-color` the brass token `--zij-brass`
 *          (`#D99A3B`).
 *        - `"land-roads"` — line layer, `line-color` the dun token
 *          `--zij-dun` (`#A38B62`), `line-width` stepped/matched by
 *          `attrs.highway` such that the numeric width immediately
 *          associated with the `"motorway"` literal is greater than the one
 *          associated with `"primary"` (this test flattens the raw
 *          expression array and reads the literal-followed-by-number pairs —
 *          it does not require any specific expression operator, only that a
 *          highway-value string literal is immediately followed by its
 *          numeric width in the flattened expression).
 *        - `"land-points"` — symbol layer rendering point anchors (e.g. the
 *          port node in the fixture below).
 *   4. Freshness + count DOM seams, one badge container per domain:
 *        - `[data-testid="badge-air"]`, `[data-testid="badge-land"]`
 *        - within each container: `[data-testid="freshness-fetched"]` and
 *          `[data-testid="freshness-source"]`, each rendering *exactly*
 *          `HH:MM:SS UTC` (NFR6 — literally containing "UTC", never a local
 *          time conversion) formatted from the snapshot's
 *          `timestamp_fetched` / `timestamp_source` respectively;
 *        - `[data-testid="feature-count"]`, whose text contains the
 *          snapshot's `meta.feature_count`.
 *   5. `[data-testid="refresh-all"]` — the global "Refresh all" button
 *      (spec §7). Clicking it must issue `POST /api/refresh`, then re-fetch
 *      both `GET /api/layers/{air,land}/snapshot` (this slice has no SSE —
 *      re-render is a poll-once, not a push) so the badges and both GeoJSON
 *      sources reflect the NEW snapshot fixtures below.
 *
 * This test is not the test-author's to loosen and not the implementer's to
 * touch. The `test.fail()` marker was removed only once every assertion
 * below passed for real, in the test-author's final marker-removal pass.
 */

import { test, expect, type Page } from '@playwright/test';
import { startQuietSseStub } from './helpers/quietSseStub';
import { stubRegionEndpoints } from './helpers/stubRegionEndpoints';
import { stubConfigEndpoint } from './helpers/stubConfigEndpoint';

// --- Fixtures ----------------------------------------------------------
// Modeled on design/contracts/feature-schema.md "Wire examples". Kept small
// and inline; each domain has an INITIAL snapshot (served until refresh) and
// a REFRESHED one (served after POST /api/refresh resolves), so "the layers
// re-render from the new snapshots" is independently observable.

const AIR_INITIAL = {
  meta: {
    layer: 'air',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-06T09:12:03Z',
    timestamp_source: '2026-07-06T09:11:58Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 2,
    retry_after_s: null,
    detail: null,
  },
  features: [
    {
      domain: 'air',
      source: 'opensky',
      source_id: '896451',
      label: 'IRA655',
      lat: 26.61,
      lon: 56.27,
      geometry_type: 'point',
      geometry: null,
      timestamp_source: '2026-07-06T09:11:58Z',
      timestamp_fetched: '2026-07-06T09:12:03Z',
      position_age_s: 5.0,
      status: 'live',
      integrity_flags: [],
      attrs: {
        altitude_m: 10668.0,
        geo_altitude_m: 10820.0,
        velocity_ms: 231.5,
        vertical_rate_ms: 0.0,
        true_track_deg: 118.4,
        position_source: 'ADS-B',
        on_ground: false,
      },
    },
    {
      domain: 'air',
      source: 'opensky',
      source_id: '896452',
      label: 'UAE202',
      lat: 26.75,
      lon: 56.1,
      geometry_type: 'point',
      geometry: null,
      timestamp_source: '2026-07-06T09:11:59Z',
      timestamp_fetched: '2026-07-06T09:12:03Z',
      position_age_s: 4.0,
      status: 'live',
      integrity_flags: [],
      attrs: {
        altitude_m: 9500.0,
        geo_altitude_m: 9600.0,
        velocity_ms: 210.0,
        vertical_rate_ms: -2.0,
        true_track_deg: 270.0,
        position_source: 'ADS-B',
        on_ground: false,
      },
    },
  ],
};

const AIR_REFRESHED = {
  meta: {
    ...AIR_INITIAL.meta,
    timestamp_fetched: '2026-07-06T09:22:03Z',
    timestamp_source: '2026-07-06T09:21:58Z',
    feature_count: 3,
  },
  features: [
    { ...AIR_INITIAL.features[0], timestamp_fetched: '2026-07-06T09:22:03Z' },
    { ...AIR_INITIAL.features[1], timestamp_fetched: '2026-07-06T09:22:03Z' },
    {
      domain: 'air',
      source: 'opensky',
      source_id: '896453',
      label: 'QTR118',
      lat: 26.5,
      lon: 56.4,
      geometry_type: 'point',
      geometry: null,
      timestamp_source: '2026-07-06T09:21:55Z',
      timestamp_fetched: '2026-07-06T09:22:03Z',
      position_age_s: 8.0,
      status: 'live',
      integrity_flags: [],
      attrs: {
        altitude_m: 11000.0,
        geo_altitude_m: 11120.0,
        velocity_ms: 240.0,
        vertical_rate_ms: 1.5,
        true_track_deg: 45.0,
        position_source: 'ADS-B',
        on_ground: false,
      },
    },
  ],
};

const LAND_INITIAL = {
  meta: {
    layer: 'land',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-05T02:00:11Z',
    timestamp_source: '2026-07-04T00:00:00Z',
    cadence_s: 86400,
    stale_after_s: 172800,
    feature_count: 3,
    retry_after_s: null,
    detail: null,
  },
  features: [
    {
      domain: 'land',
      source: 'overpass',
      source_id: 'way/1001',
      label: 'Coastal Motorway',
      lat: 27.16,
      lon: 56.28,
      geometry_type: 'linestring',
      geometry: {
        type: 'LineString',
        coordinates: [
          [56.28, 27.16],
          [56.31, 27.18],
        ],
      },
      timestamp_source: '2026-07-04T00:00:00Z',
      timestamp_fetched: '2026-07-05T02:00:11Z',
      position_age_s: 118211.0,
      status: 'live',
      integrity_flags: [],
      attrs: { highway: 'motorway', ref: 'E15', surface: 'asphalt' },
    },
    {
      domain: 'land',
      source: 'overpass',
      source_id: 'way/23895671',
      label: 'Bandar Abbas Coastal Highway',
      lat: 27.18,
      lon: 56.31,
      geometry_type: 'linestring',
      geometry: {
        type: 'LineString',
        coordinates: [
          [56.31, 27.18],
          [56.34, 27.2],
        ],
      },
      timestamp_source: '2026-07-04T00:00:00Z',
      timestamp_fetched: '2026-07-05T02:00:11Z',
      position_age_s: 118211.0,
      status: 'live',
      integrity_flags: [],
      attrs: { highway: 'primary', ref: 'A9', surface: 'asphalt' },
    },
    {
      domain: 'land',
      source: 'overpass',
      source_id: 'node/998811',
      label: 'Shahid Rajaee Port',
      lat: 27.1,
      lon: 56.06,
      geometry_type: 'point',
      geometry: null,
      timestamp_source: '2026-07-04T00:00:00Z',
      timestamp_fetched: '2026-07-05T02:00:11Z',
      position_age_s: 118211.0,
      status: 'live',
      integrity_flags: [],
      attrs: { harbour: 'yes', landuse: 'port' },
    },
  ],
};

const LAND_REFRESHED = {
  meta: {
    ...LAND_INITIAL.meta,
    timestamp_fetched: '2026-07-06T09:22:05Z',
    feature_count: 4,
  },
  features: [
    ...LAND_INITIAL.features.map((f) => ({ ...f, timestamp_fetched: '2026-07-06T09:22:05Z' })),
    {
      domain: 'land',
      source: 'overpass',
      source_id: 'way/1002',
      label: 'Inland Trunk Road',
      lat: 27.05,
      lon: 56.2,
      geometry_type: 'linestring',
      geometry: {
        type: 'LineString',
        coordinates: [
          [56.18, 27.03],
          [56.22, 27.07],
        ],
      },
      timestamp_source: '2026-07-04T00:00:00Z',
      timestamp_fetched: '2026-07-06T09:22:05Z',
      position_age_s: 204125.0,
      status: 'live',
      integrity_flags: [],
      attrs: { highway: 'trunk', ref: 'B12', surface: 'asphalt' },
    },
  ],
};

// --- Helpers -------------------------------------------------------------

function normalizeToRgb(value: unknown): [number, number, number] {
  const s = String(value).trim();
  const hexMatch = /^#([0-9a-fA-F]{6})$/.exec(s);
  if (hexMatch) {
    const hex = hexMatch[1];
    return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
  }
  const rgbaMatch = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(s);
  if (rgbaMatch) {
    return [Number(rgbaMatch[1]), Number(rgbaMatch[2]), Number(rgbaMatch[3])];
  }
  throw new Error(`Unrecognized paint color format: ${s}`);
}

/** Flattens a nested MapLibre style-expression array into a single list of
 * its scalar leaves, in order — used to find "literal immediately followed
 * by its numeric value" pairs without depending on which expression operator
 * (match/step/case/...) the implementer chose. */
function flattenExpression(value: unknown): unknown[] {
  const out: unknown[] = [];
  const walk = (v: unknown) => {
    if (Array.isArray(v)) {
      v.forEach(walk);
    } else {
      out.push(v);
    }
  };
  walk(value);
  return out;
}

function numericValueFollowingLiteral(expr: unknown, literal: string): number {
  const flat = flattenExpression(expr);
  const idx = flat.indexOf(literal);
  if (idx === -1 || typeof flat[idx + 1] !== 'number') {
    throw new Error(
      `Expected a numeric value immediately after literal "${literal}" in expression: ${JSON.stringify(expr)}`,
    );
  }
  return flat[idx + 1] as number;
}

/** Registers page.route() interception for /api/refresh + both snapshot
 * endpoints BEFORE navigation. Snapshot routes serve the INITIAL fixtures
 * until /api/refresh is POSTed, then serve the REFRESHED fixtures — modeling
 * this slice's poll-once (no SSE) re-render contract. */
async function stubApi(page: Page) {
  let refreshed = false;

  await page.route('**/api/refresh', async (route) => {
    expect(route.request().method()).toBe('POST');
    refreshed = true;
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
      body: JSON.stringify(refreshed ? AIR_REFRESHED : AIR_INITIAL),
    });
  });

  await page.route('**/api/layers/land/snapshot', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(refreshed ? LAND_REFRESHED : LAND_INITIAL),
    });
  });
}

test(
  'air + land snapshots render (rotated brass aircraft, dun land, UTC freshness + count) and Refresh re-renders from new snapshots',
  async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    // RECONCILIATION (frontend/01-sse-client, #57) — see file-header comment.
    const sseStub = await startQuietSseStub();

    try {
    // Registered BEFORE navigation so nothing fired during initial load is missed.
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });

    // Route interception MUST be registered before goto — there is no live
    // FastAPI backend in this e2e run (playwright.config.ts serves the built
    // static bundle only).
    await stubApi(page);
    await sseStub.attachTo(page);
    await stubRegionEndpoints(page);
    await stubConfigEndpoint(page);

    await page.goto('/');

    // --- Test seam: wait for the live Map + both GeoJSON sources -----------
    await page.waitForFunction(() => {
      const map = (window as unknown as { __zijMap?: { getSource(id: string): unknown } }).__zijMap;
      return Boolean(map && map.getSource('air') && map.getSource('land'));
    });

    // === Clause: aircraft symbols render, rotated by true_track_deg, brass ==
    const airSourceData = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('air').serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
    });
    const airSourceIds = new Set(airSourceData.features.map((f) => f.properties.source_id));
    expect(airSourceIds).toEqual(new Set(['896451', '896452']));

    const iconRotate = await page.evaluate(() =>
      (
        window as unknown as { __zijMap: { getLayoutProperty(layer: string, prop: string): unknown } }
      ).__zijMap.getLayoutProperty('air-aircraft', 'icon-rotate'),
    );
    expect(
      JSON.stringify(iconRotate),
      `icon-rotate must be data-driven off true_track_deg; got ${JSON.stringify(iconRotate)}`,
    ).toContain('true_track_deg');

    const iconColor = await page.evaluate(() =>
      (
        window as unknown as { __zijMap: { getPaintProperty(layer: string, prop: string): unknown } }
      ).__zijMap.getPaintProperty('air-aircraft', 'icon-color'),
    );
    const [airR, airG, airB] = normalizeToRgb(iconColor);
    // --zij-brass: #D99A3B -> rgb(217, 154, 59)
    expect(airR).toBe(217);
    expect(airG).toBe(154);
    expect(airB).toBe(59);

    const airLayerType = await page.evaluate(
      () => (window as unknown as { __zijMap: { getLayer(id: string): { type: string } | undefined } }).__zijMap
        .getLayer('air-aircraft')?.type ?? null,
    );
    expect(airLayerType).toBe('symbol');

    // === Clause: land roads render dun, motorway thickest; point anchors ===
    const landSourceData = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('land').serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
    });
    const landSourceIds = new Set(landSourceData.features.map((f) => f.properties.source_id));
    expect(landSourceIds).toEqual(new Set(['way/1001', 'way/23895671', 'node/998811']));

    const lineColor = await page.evaluate(() =>
      (
        window as unknown as { __zijMap: { getPaintProperty(layer: string, prop: string): unknown } }
      ).__zijMap.getPaintProperty('land-roads', 'line-color'),
    );
    const [landR, landG, landB] = normalizeToRgb(lineColor);
    // --zij-dun: #A38B62 -> rgb(163, 139, 98)
    expect(landR).toBe(163);
    expect(landG).toBe(139);
    expect(landB).toBe(98);

    const lineWidth = await page.evaluate(() =>
      (
        window as unknown as { __zijMap: { getPaintProperty(layer: string, prop: string): unknown } }
      ).__zijMap.getPaintProperty('land-roads', 'line-width'),
    );
    const motorwayWidth = numericValueFollowingLiteral(lineWidth, 'motorway');
    const primaryWidth = numericValueFollowingLiteral(lineWidth, 'primary');
    expect(
      motorwayWidth,
      `motorway width (${motorwayWidth}) must exceed primary width (${primaryWidth})`,
    ).toBeGreaterThan(primaryWidth);

    const landRoadsType = await page.evaluate(
      () => (window as unknown as { __zijMap: { getLayer(id: string): { type: string } | undefined } }).__zijMap
        .getLayer('land-roads')?.type ?? null,
    );
    expect(landRoadsType).toBe('line');

    const landPointsType = await page.evaluate(
      () => (window as unknown as { __zijMap: { getLayer(id: string): { type: string } | undefined } }).__zijMap
        .getLayer('land-points')?.type ?? null,
    );
    expect(landPointsType, 'land-points layer (point anchors) must be a symbol layer').toBe('symbol');

    // === Clause: each layer shows both timestamps in UTC + a feature count =
    const airBadge = page.locator('[data-testid="badge-air"]');
    await expect(airBadge).toBeVisible();
    await expect(airBadge.locator('[data-testid="freshness-fetched"]')).toHaveText('09:12:03 UTC');
    await expect(airBadge.locator('[data-testid="freshness-source"]')).toHaveText('09:11:58 UTC');
    await expect(airBadge.locator('[data-testid="feature-count"]')).toContainText('2');

    const landBadge = page.locator('[data-testid="badge-land"]');
    await expect(landBadge).toBeVisible();
    await expect(landBadge.locator('[data-testid="freshness-fetched"]')).toHaveText('02:00:11 UTC');
    await expect(landBadge.locator('[data-testid="freshness-source"]')).toHaveText('00:00:00 UTC');
    await expect(landBadge.locator('[data-testid="feature-count"]')).toContainText('3');

    // === Clause: Refresh issues POST /api/refresh, layers re-render ========
    const refreshButton = page.locator('[data-testid="refresh-all"]');
    await expect(refreshButton).toBeVisible();

    const refreshRequestPromise = page.waitForRequest(
      (req) => req.url().includes('/api/refresh') && req.method() === 'POST',
    );
    await refreshButton.click();
    const refreshRequest = await refreshRequestPromise;
    expect(refreshRequest.method()).toBe('POST');

    // New snapshot reflected in the badges (poll-once re-fetch, no SSE this slice).
    await expect(airBadge.locator('[data-testid="freshness-fetched"]')).toHaveText('09:22:03 UTC', {
      timeout: 10_000,
    });
    await expect(airBadge.locator('[data-testid="feature-count"]')).toContainText('3');
    await expect(landBadge.locator('[data-testid="freshness-fetched"]')).toHaveText('09:22:05 UTC');
    await expect(landBadge.locator('[data-testid="feature-count"]')).toContainText('4');

    // ... and reflected in the actual GeoJSON sources driving the map.
    const airSourceDataAfter = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('air').serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
    });
    const airSourceIdsAfter = new Set(airSourceDataAfter.features.map((f) => f.properties.source_id));
    expect(airSourceIdsAfter).toEqual(new Set(['896451', '896452', '896453']));

    const landSourceDataAfter = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('land').serialize().data as { features: unknown[] };
    });
    expect(landSourceDataAfter.features).toHaveLength(4);

    // --- Clause: no uncaught console error / page error during load/refresh
    expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
    expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
    } finally {
      await sseStub.close();
    }
  },
);
