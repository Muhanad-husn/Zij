/**
 * DEC-1 locked outer acceptance test — frontend/06-marine-integrity (issue
 * #62), the last v1 frontend feature slice. Encodes
 * `plans/frontend/06-marine-integrity.md`'s Gherkin verbatim:
 *
 *   Given the app receiving a marine snapshot over SSE
 *   When  the layer renders
 *   Then  vessels draw as teal glyphs rotated by cog_deg with MMSI/SOG/COG
 *         popups
 *   When  a vessel has been silent longer than deemphasize_after_s
 *         (client tick)
 *   Then  it renders de-emphasized, and past drop_after_s it disappears
 *         from the map
 *   When  a vessel carries spoof_suspect_on_land
 *   Then  its hollow warning ring renders (never hidden) and the popup
 *         names the flag
 *
 * `test.fail()` is this repo's web-slice analog to a strict pytest xfail
 * (DEC-33 — precedent: `layers-refresh.spec.ts`, `badges.spec.ts`,
 * `sse-client.spec.ts`, `region-selector.spec.ts`, `toggles-refresh.spec.ts`,
 * `caveat-panel.spec.ts`). `frontend/src/map/layers/marine.ts` and
 * `frontend/src/map/popup.ts` do not exist yet, and `main.ts` mounts a
 * marine BADGE only (no marine map source/layer, no client tick, no popup
 * infrastructure at all — see `main.ts`'s own comment: "Marine badge only
 * this slice — no marine map source/layer yet"). Every clause below
 * therefore fails for real today; `test.fail()` marks that an EXPECTED
 * failure so the suite reports green and this red commit lands under the
 * no-commit-on-red gate. The implementer greens every clause; the
 * test-author then confirms each assertion passes for real and removes the
 * `test.fail()` marker in a final pass — this test is not the test-author's
 * to loosen after that and not the implementer's to touch at any point.
 *
 * SCOPE: `design/specs/frontend.md` §2 "Marine" + §9 "State handling" (the
 * client tick) + FR3/FR9/NFR3. Air's own tick-driven de-emphasis (also
 * mentioned in the plan's Goal paragraph, "Client-tick de-emphasis/drop for
 * air + marine") is NOT exercised here — the plan's own Gherkin only names
 * "a vessel," never an aircraft, so this test stays inside that boundary;
 * any air-side de-emphasis wiring the implementer adds alongside the shared
 * tick mechanism is incidental, not locked by this file. Land is untouched
 * by tick (spec §2 "Land is the one domain exempt from §9's ticking
 * recompute") and already covered elsewhere — not re-asserted here.
 *
 * WHY REAL WALL-CLOCK TIME, NOT MOCKED: the client tick is a plain
 * `setInterval` in `main.ts`/`config.ts` (spec §9: "~5–10 s"), not sourced
 * from any endpoint this test can control. Rather than mock browser time
 * (untried in this codebase, and MapLibre's own render loop leans on
 * `requestAnimationFrame`, which time-mocking would also freeze), this test
 * stubs `GET /api/config`'s `layers.marine.deemphasize_after_s` /
 * `drop_after_s` down to small values (4 s / 16 s) via
 * `stubConfigEndpoint`'s override param — a legitimate use of the
 * documented config-sourcing seam (spec §9) — chosen with a wide enough gap
 * (12 s) to stay correct regardless of whether the implementer's tick
 * interval lands anywhere in the spec's own "~5–10 s" band, worst case
 * included. This keeps the wait real, bounded, and deterministic without
 * touching browser-internal timer plumbing this repo has never exercised
 * before. `test.setTimeout(...)` below is raised accordingly.
 *
 * STUB MECHANISM: no live FastAPI backend in this e2e run
 * (`playwright.config.ts` serves the built `vite preview` bundle on :4173).
 * As established by `badges.spec.ts` (see its file-header comment for the
 * full rationale — `page.route().fulfill()` cannot hold a stream open),
 * this test runs a REAL streaming Node `http` server on an ephemeral
 * loopback port and redirects the browser's `/api/events` request to it via
 * `route.continue({ url })`. One connection is held open for the whole
 * test; `push()` writes additional `snapshot` SSE blocks down it.
 * `GET /api/config`, `GET /api/regions`, `GET /api/regions/active`, and the
 * defensive per-domain snapshot/refresh fallbacks are ordinary
 * request/response GETs, stubbed with plain `page.route().fulfill()`.
 *
 * TEST-AUTHOR MARKER-REMOVAL FIX NOTE (DEC-33 second pass, both corrections
 * to test plumbing only — no locked assertion was loosened):
 *   1. `icon-rotate` is read via `getLayoutProperty` only, not
 *      `getPaintProperty` — it is a symbol LAYOUT property in maplibre-gl's
 *      style spec (`getPaintProperty` on it throws inside MapLibre's own
 *      `Transitionable.getValue`), mirroring `layers-refresh.spec.ts`'s
 *      identical air-aircraft check.
 *   2. V2 (the vessel tracked for de-emphasis/drop) carries an intentional
 *      `position_age_s` HEAD START, and V1/V3/V4 are RENEWED (re-pushed with
 *      a fresh timestamp) once V2's de-emphasized-but-present state is
 *      confirmed. Without this, all four vessels share one push instant
 *      under the same uniform client-tick age model (spec §9) and would age
 *      out together — no faithful implementation could satisfy "the other
 *      three vessels survive V2's drop" against the original uniform
 *      fixture. See the inline comments at the two `fixture.push('snapshot',
 *      ...)` call sites for the exact timing/margin reasoning.
 *
 * REQUIRED TEST SEAMS (implementer must expose these — not the test-author's
 * to relax; each is independently asserted below). Naming mirrors the
 * existing `air`/`air-aircraft` and `land`/`land-roads`/`land-points`
 * convention (`map/layers/aviation.ts`, `map/layers/land.ts`):
 *
 *   1. GeoJSON source id `"marine"` (`map.getSource('marine')`), populated
 *      via `wireToGeoJson` (or equivalent) from `snapshot:marine` events —
 *      one GeoJSON Feature per wire Feature, `properties.source_id`
 *      preserved verbatim (MMSI), `attrs` reachable from a style expression
 *      (flattened top-level and/or the two-argument `["get", key,
 *      ["get","attrs"]]` form, per spec §2 "Wire → GeoJSON").
 *   2. Layer id `"marine-vessels"` — a `symbol` layer on the `marine`
 *      source. `icon-rotate` data-driven off `cog_deg` (this test checks
 *      the raw expression references the key, mirroring
 *      `layers-refresh.spec.ts`'s `icon-rotate`/`true_track_deg` check —
 *      the `heading_deg`/upright fallback is this slice's own INNER Vitest
 *      concern, not locked at this e2e boundary). `icon-color` reads the
 *      `--zij-teal` token (`#4E9DB4`). `icon-opacity` is a data-driven
 *      expression referencing a client-computed `deemphasized` boolean
 *      GeoJSON property (spec §2/§9, verbatim property name) — checked both
 *      for the paint wiring's *existence* (present from the very first
 *      render, before any tick) and, later, for its *effect* (the property
 *      actually flips `true` once client-tick age exceeds
 *      `deemphasize_after_s`).
 *   3. Past `drop_after_s`, the vessel's GeoJSON Feature is removed from the
 *      `marine` source's data entirely (not just marked/hidden) — checked
 *      via `map.getSource('marine').serialize().data.features`, and that
 *      OTHER vessels sharing the same source are left untouched (proves a
 *      per-feature removal, not a blanket re-clear of the whole source).
 *   4. `[data-testid="marine-popup"]` — a popup content container, opened
 *      by clicking a rendered `marine-vessels` feature (spec §2 Performance
 *      budget: "one shared Popup instance, opened on a layer `click`
 *      handler"). Within it:
 *        - `[data-testid="popup-mmsi"]` — text equal to the vessel's wire
 *          `source_id` (MMSI) verbatim.
 *        - `[data-testid="popup-sog"]` — text containing the vessel's
 *          `attrs.sog_kn` numeral.
 *        - `[data-testid="popup-cog"]` — text containing the vessel's
 *          `attrs.cog_deg` numeral.
 *        - `[data-testid="popup-flags"]` — present ONLY when the vessel's
 *          `integrity_flags` is non-empty; carries a `data-flags` attribute
 *          equal to the raw `IntegrityFlag` value(s) verbatim (comma-joined
 *          if more than one) AND has non-empty, human-readable text
 *          mentioning the flag (FR3 popup / FR9 "the popup names the flag"
 *          — this test locks the underlying data reachability + visible
 *          naming, not one exact phrasing).
 *      Only one `.maplibregl-popup` is ever visible at a time (spec §2:
 *      "ONE shared Popup instance").
 *   5. Layer ids `"marine-spoof-ring"` (filtered by `spoof_suspect_on_land`
 *      being present in a feature's `integrity_flags`) and
 *      `"marine-kinematics-ring"` (filtered by `implausible_kinematics`) —
 *      both `circle` layers on the `marine` source, drawn hollow
 *      (no fill — `circle-color`/`circle-opacity` resolves fully
 *      transparent) with a nonzero `circle-stroke-width` in a color
 *      distinct from each other (spec §2: "distinct color/dash"). Neither
 *      layer's `visibility` layout property is ever `"none"` (NFR3: "never
 *      conditionally hidden"). A vessel carrying BOTH flags has both flag
 *      values present in its rendered `integrity_flags` GeoJSON property,
 *      so both filters independently match the same feature (concentric
 *      rendering) — the exact filter-DSL evaluation semantics are this
 *      slice's own INNER Vitest concern per the plan's unit list, not
 *      re-derived here.
 *
 * This test is not the test-author's to loosen and not the implementer's to
 * touch. The `test.fail()` marker is removed only once every assertion
 * below passes for real, in the test-author's final marker-removal pass.
 */

import { test, expect, type Page } from '@playwright/test';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';
import { stubRegionEndpoints } from './helpers/stubRegionEndpoints';
import { stubConfigEndpoint } from './helpers/stubConfigEndpoint';

// --zij-teal (#4E9DB4) -> rgb(78, 157, 180). Duplicated here (not imported)
// so this test proves the ACTUAL rendered color, independent of whichever
// mechanism reads the token (mirrors layers-refresh.spec.ts's own approach).
const TEAL_RGB: [number, number, number] = [78, 157, 180];

const MARINE_SOURCE_ID = 'marine';
const MARINE_LAYER_ID = 'marine-vessels';
const SPOOF_RING_LAYER_ID = 'marine-spoof-ring';
const KINEMATICS_RING_LAYER_ID = 'marine-kinematics-ring';

// Small test-only thresholds (see file-header "WHY REAL WALL-CLOCK TIME").
// 12 s gap between the two is intentionally wider than the spec's own
// "~5-10 s" tick-interval band, worst case included.
const TEST_DEEMPHASIZE_AFTER_S = 4;
const TEST_DROP_AFTER_S = 16;

// --- SSE fixture server (verbatim pattern from badges.spec.ts) -------------

function startEventsFixtureServer(): {
  server: Server;
  connected: Promise<void>;
  push: (event: string, data: unknown) => void;
  shutdown: () => Promise<void>;
} {
  let nextId = 1;
  let conn: ServerResponse | null = null;
  let resolveConnected!: () => void;
  const connected = new Promise<void>((resolve) => {
    resolveConnected = resolve;
  });
  const sockets = new Set<Socket>();

  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (!conn) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      res.write('retry: 1000\n\n');
      const flushable = res as ServerResponse & { flushHeaders?: () => void };
      flushable.flushHeaders?.();
      req.socket.setNoDelay(true);
      conn = res;
      resolveConnected();
    } else {
      res.writeHead(204);
      res.end();
    }
  });

  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });

  return {
    server,
    connected,
    push: (event: string, data: unknown) => {
      if (!conn) {
        throw new Error('startEventsFixtureServer: push() called before a client connected');
      }
      conn.write(`event: ${event}\nid: ${nextId++}\ndata: ${JSON.stringify(data)}\n\n`);
    },
    shutdown: async () => {
      conn?.end();
      conn = null;
      for (const socket of sockets) {
        socket.destroy();
      }
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}

async function listenEphemeral(server: Server): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as AddressInfo;
  return `http://127.0.0.1:${address.port}/api/events`;
}

async function stubEvents(page: Page, fixtureUrl: string): Promise<void> {
  await page.route('**/api/events', async (route) => {
    await route.continue({ url: fixtureUrl });
  });
}

/** Defensive REST fallback stubs (mirrors badges.spec.ts / caveat-panel.spec.ts). */
async function stubRestFallback(page: Page) {
  const empty = (layer: 'air' | 'marine' | 'land') => ({
    meta: {
      layer,
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: '2026-07-10T00:00:00Z',
      timestamp_source: '2026-07-10T00:00:00Z',
      cadence_s: layer === 'marine' ? 60 : 600,
      stale_after_s: layer === 'marine' ? 120 : 1200,
      feature_count: 0,
      retry_after_s: null,
      detail: null,
    },
    features: [],
  });
  for (const layer of ['air', 'marine', 'land'] as const) {
    await page.route(`**/api/layers/${layer}/snapshot`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(empty(layer)) });
    });
  }
  await page.route('**/api/refresh', async (route) => {
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ queued: [] }) });
  });
}

// --- Fixtures ----------------------------------------------------------
// Modeled on design/contracts/feature-schema.md "Wire examples -> Marine".

interface MarineFeatureOptions {
  label?: string | null;
  lat: number;
  lon: number;
  cogDeg?: number | null;
  headingDeg?: number | null;
  sogKn?: number | null;
  integrityFlags?: string[];
  positionAgeS?: number;
  timestampFetched?: string;
}

function marineFeature(sourceId: string, o: MarineFeatureOptions) {
  const fetchedAt = o.timestampFetched ?? new Date().toISOString();
  return {
    domain: 'marine',
    source: 'aisstream',
    source_id: sourceId,
    label: o.label ?? null,
    lat: o.lat,
    lon: o.lon,
    geometry_type: 'point',
    geometry: null,
    timestamp_source: fetchedAt,
    timestamp_fetched: fetchedAt,
    position_age_s: o.positionAgeS ?? 0,
    status: 'live',
    integrity_flags: o.integrityFlags ?? [],
    attrs: {
      sog_kn: o.sogKn === undefined ? 12.4 : o.sogKn,
      cog_deg: o.cogDeg === undefined ? 341.0 : o.cogDeg,
      heading_deg: o.headingDeg === undefined ? 340 : o.headingDeg,
      nav_status: 'under way using engine',
      ship_type: 'tanker',
    },
  };
}

function marineMeta(overrides: Record<string, unknown> = {}) {
  const now = new Date().toISOString();
  return {
    layer: 'marine',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: now,
    timestamp_source: now,
    cadence_s: 60,
    stale_after_s: 120,
    feature_count: 4,
    retry_after_s: null,
    detail: null,
    ...overrides,
  };
}

/**
 * V1/V3/V4's fixture features, freshly timestamped (`timestamp_fetched` =
 * call time, `position_age_s` default 0) on every call. Used for BOTH the
 * initial push and the mid-test "renewal" push (see the de-emphasize/drop
 * clause below) so the two payloads stay identical apart from timestamp —
 * renewal resets these three vessels' age to ~0 so they cannot cross
 * `drop_after_s` at the same wall-clock moment V2 does, which is what makes
 * the final per-feature-removal assertion satisfiable at all (all four
 * vessels sharing one push instant, with the SAME uniform age model, would
 * otherwise all age out together — see the file-header defect-2 note).
 */
function otherVesselFeatures(v1: string, v3: string, v4: string) {
  return {
    v1: marineFeature(v1, { label: 'SHINE STAR', lat: 26.61, lon: 56.27, cogDeg: 341.0, sogKn: 12.4 }),
    v3: marineFeature(v3, {
      label: 'GHOST TANKER',
      lat: 26.7,
      lon: 56.4,
      cogDeg: 200.0,
      integrityFlags: ['spoof_suspect_on_land'],
    }),
    v4: marineFeature(v4, {
      label: 'DOUBLE FLAG',
      lat: 26.3,
      lon: 56.5,
      cogDeg: 15.0,
      integrityFlags: ['spoof_suspect_on_land', 'implausible_kinematics'],
    }),
  };
}

// --- Map read helpers --------------------------------------------------

async function marineSourceIds(page: Page): Promise<Set<string>> {
  const ids = await page.evaluate((sourceId) => {
    const map = (
      window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } | undefined } }
    ).__zijMap;
    const source = map.getSource(sourceId);
    if (!source) return [];
    const data = source.serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
    return data.features.map((f) => f.properties.source_id as string);
  }, MARINE_SOURCE_ID);
  return new Set(ids);
}

async function marineFeatureProps(page: Page, sourceId: string): Promise<Record<string, unknown> | null> {
  return page.evaluate(
    ({ srcId, wanted }) => {
      const map = (
        window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } | undefined } }
      ).__zijMap;
      const source = map.getSource(srcId);
      if (!source) return null;
      const data = source.serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
      const f = data.features.find((feat) => feat.properties.source_id === wanted);
      return f ? f.properties : null;
    },
    { srcId: MARINE_SOURCE_ID, wanted: sourceId },
  );
}

async function getPaintProp(page: Page, layerId: string, prop: string): Promise<unknown> {
  return page.evaluate(
    ({ layerId: id, prop: p }) =>
      (
        window as unknown as { __zijMap: { getPaintProperty(layer: string, prop: string): unknown } }
      ).__zijMap.getPaintProperty(id, p),
    { layerId, prop },
  );
}

async function getLayoutProp(page: Page, layerId: string, prop: string): Promise<unknown> {
  return page.evaluate(
    ({ layerId: id, prop: p }) =>
      (
        window as unknown as { __zijMap: { getLayoutProperty(layer: string, prop: string): unknown } }
      ).__zijMap.getLayoutProperty(id, p),
    { layerId, prop },
  );
}

async function getLayerType(page: Page, layerId: string): Promise<string | null> {
  return page.evaluate(
    (id) =>
      (window as unknown as { __zijMap: { getLayer(id: string): { type: string } | undefined } }).__zijMap.getLayer(
        id,
      )?.type ?? null,
    layerId,
  );
}

async function getFilter(page: Page, layerId: string): Promise<unknown> {
  return page.evaluate(
    (id) => (window as unknown as { __zijMap: { getFilter(id: string): unknown } }).__zijMap.getFilter(id),
    layerId,
  );
}

function normalizeToRgba(value: unknown): [number, number, number, number] | 'transparent' {
  const s = String(value).trim().toLowerCase();
  if (s === 'transparent' || s === 'rgba(0, 0, 0, 0)' || s === 'rgba(0,0,0,0)') return 'transparent';
  const rgbaMatch = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/.exec(s);
  if (rgbaMatch) {
    return [
      Number(rgbaMatch[1]),
      Number(rgbaMatch[2]),
      Number(rgbaMatch[3]),
      rgbaMatch[4] !== undefined ? Number(rgbaMatch[4]) : 1,
    ];
  }
  const hexMatch = /^#([0-9a-f]{6})([0-9a-f]{2})?$/.exec(s);
  if (hexMatch) {
    const hex = hexMatch[1];
    const alphaHex = hexMatch[2];
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
      alphaHex ? parseInt(alphaHex, 16) / 255 : 1,
    ];
  }
  throw new Error(`Unrecognized color format: ${s}`);
}

/** True if a circle layer's fill is hollow — fully transparent color, or an
 * explicit zero circle-opacity. */
function isHollowFill(circleColor: unknown, circleOpacity: unknown): boolean {
  if (typeof circleOpacity === 'number' && circleOpacity === 0) return true;
  if (circleColor === undefined) return false;
  const rgba = normalizeToRgba(circleColor);
  return rgba === 'transparent' || rgba[3] === 0;
}

/** Waits (bounded) for `layerId` to have actually painted a feature at
 * `[lon, lat]`, then returns the CSS-pixel point (relative to the map
 * container) to click. Using `queryRenderedFeatures` rather than a blind
 * wait avoids a flaky click landing before the first real paint. */
async function waitForRenderedPoint(
  page: Page,
  layerId: string,
  lon: number,
  lat: number,
  timeoutMs = 20_000,
): Promise<{ x: number; y: number }> {
  return page.evaluate(
    ({ layerId: id, lon: lo, lat: la, timeoutMs: t }) => {
      return new Promise<{ x: number; y: number }>((resolve, reject) => {
        const map = (
          window as unknown as {
            __zijMap: {
              project(lngLat: [number, number]): { x: number; y: number };
              queryRenderedFeatures(point: [number, number], opts: { layers: string[] }): unknown[];
            };
          }
        ).__zijMap;
        const deadline = Date.now() + t;
        const check = () => {
          const point = map.project([lo, la]);
          const features = map.queryRenderedFeatures([point.x, point.y], { layers: [id] });
          if (features.length > 0) {
            resolve({ x: point.x, y: point.y });
            return;
          }
          if (Date.now() > deadline) {
            reject(
              new Error(
                `waitForRenderedPoint: timed out waiting for a rendered feature on layer "${id}" at [${lo},${la}]`,
              ),
            );
            return;
          }
          requestAnimationFrame(check);
        };
        check();
      });
    },
    { layerId, lon, lat, timeoutMs },
  );
}

async function clickMapPoint(page: Page, point: { x: number; y: number }): Promise<void> {
  const canvas = page.locator('.maplibregl-canvas');
  const box = await canvas.boundingBox();
  if (!box) {
    throw new Error('clickMapPoint: map canvas has no bounding box');
  }
  await page.mouse.click(box.x + point.x, box.y + point.y);
}

// --- Test -----------------------------------------------------------------
// Real wall-clock waits for the de-emphasis/drop clauses push this well past
// Playwright's 30s default. 200s gives headroom above the two 60s `.poll()`
// ceilings below even though the expected real timing (worst-case tick
// interval included) is well under a minute total.
test.setTimeout(200_000);

test(
  'marine vessels render as teal rotated glyphs with MMSI/SOG/COG popups, client-tick de-emphasis/drop, ' +
    'and never-hidden integrity rings (spoof + kinematics, concentric when both)',
  async ({ page }) => {
    const fixture = startEventsFixtureServer();
    const fixtureUrl = await listenEphemeral(fixture.server);
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    try {
      page.on('console', (msg) => {
        if (msg.type() === 'error') {
          consoleErrors.push(msg.text());
        }
      });
      page.on('pageerror', (err) => {
        pageErrors.push(err.message);
      });

      // Route interception MUST be registered before goto.
      await stubEvents(page, fixtureUrl);
      await stubRestFallback(page);
      await stubRegionEndpoints(page);
      await stubConfigEndpoint(page, {
        layers: {
          marine: {
            deemphasize_after_s: TEST_DEEMPHASIZE_AFTER_S,
            drop_after_s: TEST_DROP_AFTER_S,
          },
        },
      });

      await page.goto('/');
      await fixture.connected;

      await page.waitForFunction(
        () => {
          const map = (window as unknown as { __zijMap?: { getSource(id: string): unknown } }).__zijMap;
          return Boolean(map && map.getSource('marine'));
        },
        undefined,
        { timeout: 15_000 },
      );

      // === Given: a marine snapshot over SSE, four vessels =====================
      // V1: fresh, no flags — proves initial glyph render + rotation + popup,
      //     and (below) the "not already de-emphasized" default guard.
      // V2: given a `position_age_s` HEAD START of TEST_DEEMPHASIZE_AFTER_S —
      //     see the head-start comment below — tracked over real time for
      //     de-emphasis/drop, in isolation from V1/V3/V4 (which get RENEWED
      //     partway through, see the renewal push below).
      // V3: carries spoof_suspect_on_land only — ring + popup-names-the-flag.
      // V4: carries BOTH flags — concentric-ring data proof.
      const v1 = '422011111';
      const v2 = '422022222';
      const v3 = '422033333';
      const v4 = '422044444';

      // V2's head start places its de-emphasized-but-not-yet-dropped age
      // window (age in (deemphasize_after_s, drop_after_s]) at real elapsed
      // time (0, TEST_DROP_AFTER_S - TEST_DEEMPHASIZE_AFTER_S] = (0, 12]s
      // from THIS push — a 12s-wide window, still comfortably wider than the
      // spec's own worst-case ~10s tick interval (same pigeonhole margin the
      // file-header's 12s gap already relies on), just relocated to start at
      // push time instead of push+4s. Kept as its own wire object (`v2Feature`)
      // so the renewal push below can re-send V2 UNCHANGED — its age must
      // keep accruing from this ORIGINAL timestamp_fetched, uninterrupted,
      // for the client-tick drop mechanism under test to actually fire.
      const v2Feature = marineFeature(v2, {
        label: 'SILENT DRIFT',
        lat: 26.5,
        lon: 56.1,
        cogDeg: 90.0,
        sogKn: 5.0,
        positionAgeS: TEST_DEEMPHASIZE_AFTER_S,
      });

      const initialOthers = otherVesselFeatures(v1, v3, v4);
      fixture.push('snapshot', {
        meta: marineMeta({ feature_count: 4 }),
        features: [initialOthers.v1, v2Feature, initialOthers.v3, initialOthers.v4],
      });

      // === Then: the marine source/symbol layer renders =========================
      await expect
        .poll(async () => marineSourceIds(page), { message: 'marine source must carry all four pushed vessels' })
        .toEqual(new Set([v1, v2, v3, v4]));

      expect(await getLayerType(page, MARINE_LAYER_ID)).toBe('symbol');

      // icon-rotate is a symbol LAYOUT property (maplibre-gl style spec),
      // not a paint property — read via getLayoutProperty only, mirroring
      // layers-refresh.spec.ts's identical check for air-aircraft's
      // icon-rotate/true_track_deg (getPaintProperty on a layout-only
      // property throws inside MapLibre's Transitionable.getValue).
      const iconRotate = await getLayoutProp(page, MARINE_LAYER_ID, 'icon-rotate');
      expect(
        JSON.stringify(iconRotate),
        `icon-rotate must be data-driven off cog_deg; got ${JSON.stringify(iconRotate)}`,
      ).toContain('cog_deg');

      const iconColor = await getPaintProp(page, MARINE_LAYER_ID, 'icon-color');
      const rgbaColor = normalizeToRgba(iconColor);
      expect(rgbaColor, 'marine-vessels icon-color must not be fully transparent').not.toBe('transparent');
      if (rgbaColor !== 'transparent') {
        expect([rgbaColor[0], rgbaColor[1], rgbaColor[2]]).toEqual(TEAL_RGB);
      }

      // icon-opacity wiring must exist from the very first render (before any
      // tick has fired), not only reactively once a vessel actually ages out.
      const iconOpacity = await getPaintProp(page, MARINE_LAYER_ID, 'icon-opacity');
      expect(
        JSON.stringify(iconOpacity),
        `icon-opacity must be data-driven off a client-computed "deemphasized" property; got ${JSON.stringify(iconOpacity)}`,
      ).toContain('deemphasized');

      // Guard against a tautological/broken default: a freshly-pushed vessel
      // must NOT already be flagged de-emphasized moments after push. Checked
      // against V1 (age 0, no head start) rather than V2 — V2 intentionally
      // carries a head start (see above) so its own age is already past
      // deemphasize_after_s from the moment of push; V1's own default-guard
      // is a faithful stand-in since `wireToGeoJson` defaults `deemphasized`
      // identically for every feature regardless of that feature's age (it
      // is only ever recomputed by a client tick, never by the initial
      // snapshot render itself).
      const v1PropsInitial = await marineFeatureProps(page, v1);
      expect(
        v1PropsInitial ? Boolean(v1PropsInitial.deemphasized) : null,
        'a freshly-pushed vessel must not already render de-emphasized',
      ).toBe(false);

      // === Then: MMSI/SOG/COG popup on click (V1, no flags) =====================
      const v1Point = await waitForRenderedPoint(page, MARINE_LAYER_ID, 56.27, 26.61);
      await clickMapPoint(page, v1Point);

      const popup = page.locator('[data-testid="marine-popup"]');
      await expect(popup).toBeVisible();
      await expect(popup.locator('[data-testid="popup-mmsi"]')).toHaveText(v1);
      await expect(popup.locator('[data-testid="popup-sog"]')).toContainText('12.4');
      await expect(popup.locator('[data-testid="popup-cog"]')).toContainText('341');
      await expect(popup.locator('[data-testid="popup-flags"]')).toHaveCount(0);

      // Only one shared popup instance is ever visible (spec §2 perf budget).
      await expect(page.locator('.maplibregl-popup:visible')).toHaveCount(1);

      // === When: a vessel carries spoof_suspect_on_land ==========================
      // Then: hollow ring renders (never hidden) + popup names the flag (V3).
      const v3Point = await waitForRenderedPoint(page, MARINE_LAYER_ID, 56.4, 26.7);
      await clickMapPoint(page, v3Point);

      await expect(popup).toBeVisible();
      await expect(popup.locator('[data-testid="popup-mmsi"]')).toHaveText(v3);
      const flagsEl = popup.locator('[data-testid="popup-flags"]');
      await expect(flagsEl).toBeVisible();
      await expect(flagsEl).toHaveAttribute('data-flags', 'spoof_suspect_on_land');
      await expect(flagsEl).toContainText(/spoof/i);

      // Still exactly one shared popup instance after swapping content.
      await expect(page.locator('.maplibregl-popup:visible')).toHaveCount(1);

      // --- Ring layers: existence, filter, hollow paint, never hidden --------
      expect(await getLayerType(page, SPOOF_RING_LAYER_ID)).toBe('circle');
      expect(await getLayerType(page, KINEMATICS_RING_LAYER_ID)).toBe('circle');

      const spoofFilter = await getFilter(page, SPOOF_RING_LAYER_ID);
      expect(JSON.stringify(spoofFilter)).toContain('spoof_suspect_on_land');
      const kinematicsFilter = await getFilter(page, KINEMATICS_RING_LAYER_ID);
      expect(JSON.stringify(kinematicsFilter)).toContain('implausible_kinematics');

      const spoofVisibility = await getLayoutProp(page, SPOOF_RING_LAYER_ID, 'visibility');
      expect(spoofVisibility, 'spoof ring layer must never be hidden (NFR3)').not.toBe('none');
      const kinematicsVisibility = await getLayoutProp(page, KINEMATICS_RING_LAYER_ID, 'visibility');
      expect(kinematicsVisibility, 'kinematics ring layer must never be hidden (NFR3)').not.toBe('none');

      const spoofColor = await getPaintProp(page, SPOOF_RING_LAYER_ID, 'circle-color');
      const spoofOpacity = await getPaintProp(page, SPOOF_RING_LAYER_ID, 'circle-opacity');
      expect(isHollowFill(spoofColor, spoofOpacity), 'spoof ring must be hollow (stroke-only, no fill)').toBe(true);
      const kinematicsColor = await getPaintProp(page, KINEMATICS_RING_LAYER_ID, 'circle-color');
      const kinematicsOpacity = await getPaintProp(page, KINEMATICS_RING_LAYER_ID, 'circle-opacity');
      expect(
        isHollowFill(kinematicsColor, kinematicsOpacity),
        'kinematics ring must be hollow (stroke-only, no fill)',
      ).toBe(true);

      const spoofStrokeWidth = Number(await getPaintProp(page, SPOOF_RING_LAYER_ID, 'circle-stroke-width'));
      expect(spoofStrokeWidth, 'spoof ring must have a nonzero stroke').toBeGreaterThan(0);
      const kinematicsStrokeWidth = Number(await getPaintProp(page, KINEMATICS_RING_LAYER_ID, 'circle-stroke-width'));
      expect(kinematicsStrokeWidth, 'kinematics ring must have a nonzero stroke').toBeGreaterThan(0);

      const spoofStrokeColor = normalizeToRgba(await getPaintProp(page, SPOOF_RING_LAYER_ID, 'circle-stroke-color'));
      const kinematicsStrokeColor = normalizeToRgba(
        await getPaintProp(page, KINEMATICS_RING_LAYER_ID, 'circle-stroke-color'),
      );
      expect(
        JSON.stringify(spoofStrokeColor),
        'the two ring layers must use visually distinct stroke colors',
      ).not.toBe(JSON.stringify(kinematicsStrokeColor));

      // V4 carries BOTH flags — both filters independently match the same
      // rendered feature (concentric rendering's underlying data proof; the
      // filter-DSL evaluation itself is this slice's inner Vitest concern).
      const v4Props = await marineFeatureProps(page, v4);
      expect(v4Props, 'V4 must still be present in the marine source').not.toBeNull();
      const v4Flags = (v4Props?.integrity_flags ?? []) as string[];
      expect(v4Flags).toEqual(expect.arrayContaining(['spoof_suspect_on_land', 'implausible_kinematics']));

      // === When: V2 has been silent longer than deemphasize_after_s (tick) ======
      // Then: it renders de-emphasized, still present (not yet dropped).
      await expect
        .poll(
          async () => {
            const props = await marineFeatureProps(page, v2);
            return props ? Boolean(props.deemphasized) : null;
          },
          {
            timeout: 60_000,
            message: 'marine vessel must render de-emphasized once client-tick age exceeds deemphasize_after_s',
          },
        )
        .toBe(true);

      expect(await marineSourceIds(page), 'vessel must still be present once merely de-emphasized').toContain(v2);

      // Renew V1/V3/V4 (fresh timestamp_fetched, age resets to ~0) now that
      // V2's de-emphasized-but-present state is confirmed, so they cannot
      // cross drop_after_s at the same wall-clock moment V2 does — without
      // this, all four vessels share one push instant under the SAME uniform
      // age model (spec §9), so they would all age out together and the
      // "unrelated vessels survive" assertion below would be unsatisfiable
      // by any faithful implementation. This is an ordinary `snapshot` event
      // (idempotent full replace, ADR-12) like any other SSE push — NOT a
      // substitute for the client-tick drop mechanism under test. V2 itself
      // is re-sent as the SAME `v2Feature` object, UNCHANGED, so its age
      // keeps accruing from its original timestamp_fetched exactly as
      // before; only V1/V3/V4 are freshly timestamped.
      const renewedOthers = otherVesselFeatures(v1, v3, v4);
      fixture.push('snapshot', {
        meta: marineMeta({ feature_count: 4 }),
        features: [renewedOthers.v1, v2Feature, renewedOthers.v3, renewedOthers.v4],
      });

      // === And: past drop_after_s it disappears from the map =====================
      await expect
        .poll(async () => !(await marineSourceIds(page)).has(v2), {
          timeout: 60_000,
          message: 'marine vessel must be dropped from the source once client-tick age exceeds drop_after_s',
        })
        .toBe(true);

      // Per-feature removal, not a blanket re-clear: the other three vessels
      // (renewed above, but never dropped by any tick) remain.
      const idsAfterDrop = await marineSourceIds(page);
      expect(idsAfterDrop, 'unrelated vessels must survive another vessel being dropped').toEqual(
        new Set([v1, v3, v4]),
      );

      // --- Clause: no uncaught console error / page error at any point -------
      expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
      expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
    } finally {
      await fixture.shutdown();
    }
  },
);
