/**
 * Acceptance test — toggles refresh (issue #60). Encodes the feature's
 * Gherkin verbatim:
 *
 *   Given the app with badges mounted and the layer-control endpoints served
 *   When  a layer's Toggle is switched off
 *   Then  POST /api/layers/{domain}/toggle {enabled:false} is issued, its
 *         source clears, the badge grays
 *   And   no further SSE events are expected for that layer until re-enabled
 *   When  the layer's Refresh button is clicked
 *   Then  POST /api/layers/{domain}/refresh is issued and the badge reflects
 *         loading then live via SSE (no polling)
 *   When  the global Refresh all is clicked
 *   Then  POST /api/refresh is issued for all enabled layers
 *
 * This test was written before the implementation existed. It initially ran
 * under `test.fail()` (Playwright's expected-to-fail marker, the analog of a
 * strict pytest xfail — precedent: `layers-refresh.spec.ts`, `badges.spec.ts`,
 * `region-selector.spec.ts`) until every clause below was built. Once each
 * assertion was confirmed passing for real (a plain `test()` run) the
 * `test.fail()` marker was removed, so this now runs as a normal `test(...)`.
 *
 * SCOPE: `design/specs/frontend.md` §7 "Layer toggles (FR5)" / "Refresh
 * (FR6)". Toggle is exercised on `land` (a domain with a real map source, so
 * "source clears" is independently observable via `map.getSource('land')`).
 * Per-badge Refresh is exercised on `air` (proving the loading -> live
 * transition rides SSE, not a REST poll). Global "Refresh all" only proves
 * the POST is issued — the backend's own "enabled layers only" coalescing
 * guarantee is asserted server-side, not here. Marine is out of scope here
 * (no marine map layer yet) and is not touched by this test.
 *
 * STUB MECHANISM: no live FastAPI backend in this e2e run
 * (`playwright.config.ts` serves the built `vite preview` bundle on :4173).
 * As established by `badges.spec.ts` (see its file-header comment for the
 * full rationale — `page.route().fulfill()` cannot hold a stream open), this
 * test runs a REAL streaming Node `http` server on an ephemeral loopback port
 * and redirects the browser's `/api/events` request to it via
 * `route.continue({ url })`. One connection is held open for the whole test;
 * `push()` writes additional `snapshot` / `layer_status` SSE blocks down it
 * on demand, driving the "rides SSE, not polling" clause for real. The three
 * mutating REST endpoints this feature adds
 * (`POST /api/layers/{domain}/toggle`, `POST /api/layers/{domain}/refresh`,
 * `POST /api/refresh`) are answered via ordinary `page.route().fulfill()` —
 * they are simple request/response, not streams.
 *
 * LATER-FEATURE FALLOUT (region-selector, issue #59): the app
 * unconditionally fetches `GET /api/regions` and `GET /api/regions/active` on
 * load. `tests/e2e/helpers/stubRegionEndpoints.ts` answers both quietly, as
 * in every sibling spec since #59; this test asserts nothing about regions.
 *
 * LATER-FEATURE FALLOUT (marine-integrity, issue #62): the app now
 * unconditionally fetches `GET /api/config` on load (the client tick reads
 * de-emphasis/drop thresholds from it, spec §9). This test has no live
 * FastAPI backend, so an unstubbed call would leak through Vite's preview
 * proxy the same way the note above already documents.
 * `tests/e2e/helpers/stubConfigEndpoint.ts` answers it quietly; this test
 * asserts nothing about tick/de-emphasis behavior (that's
 * `marine-integrity.spec.ts`'s job).
 *
 * DEFENSIVE REST FALLBACK: `GET /api/layers/{air,marine,land}/snapshot` are
 * stubbed with empty fixtures (mirroring `badges.spec.ts`'s
 * `stubRestFallback`) purely so any cold-start or refresh-driven REST fetch
 * the implementation happens to make resolves quietly instead of 404ing
 * noisily — this test's assertions are driven entirely by the SSE fixtures
 * pushed below, never by these fallback bodies. The existing `airSseReceived`
 * / `landSseReceived` guards in `main.ts` (added in #58) are what keep a
 * racing cold-start REST fetch from clobbering the SSE-driven state this test
 * asserts against; this is the same reliance every prior SSE-asserting spec
 * (`badges.spec.ts`) already has on that guard.
 *
 * REQUIRED TEST SEAMS (the app must expose these; each is independently
 * asserted below):
 *
 *   1. `[data-testid="badge-{domain}"]` carries a `data-enabled` attribute —
 *      `"true"` by default (layers start enabled), independent of
 *      `data-status` (the wire `LayerStatus` carries no `enabled` field per
 *      feature-schema.md `LayerSnapshotMeta` — this is purely client-side
 *      toggle state).
 *   2. `[data-testid="toggle-button"]` (within a badge) — clicking it while
 *      the layer is enabled issues `POST /api/layers/{domain}/toggle` with
 *      JSON body `{ "enabled": false }`. Once that request's `200
 *      { layer, enabled:false }` response resolves, the badge's
 *      `data-enabled` flips to `"false"`.
 *   3. Disabling a layer that has a live map source (e.g. `land`) clears that
 *      source to zero features — reusing the `clear*Layer` semantics already
 *      established by earlier features (`source.setData({ type:
 *      'FeatureCollection', features: [] })`), driven this time from the
 *      toggle-off handler itself (not from a `region:changed` event).
 *   4. `[data-testid="refresh-button"]` (within a badge) — clicking it issues
 *      `POST /api/layers/{domain}/refresh`. The resulting `loading` -> `live`
 *      transition is driven ONLY by subsequent `layer_status` / `snapshot`
 *      SSE events on the existing connection — this test never stubs a REST
 *      re-fetch of that domain's snapshot as the source of the transition.
 *   5. While a badge's `data-status === "loading"`, that SAME badge's
 *      `[data-testid="refresh-button"]` carries the `disabled` attribute;
 *      once a subsequent non-`loading` status/snapshot event updates that
 *      badge, the button re-enables.
 *   6. `[data-testid="refresh-all"]` (existing seam, reused verbatim from
 *      `layers-refresh.spec.ts`) — clicking it issues `POST /api/refresh`.
 *
 * The `test.fail()` marker was removed only once every assertion below passed
 * for real.
 */

import { test, expect, type Page } from '@playwright/test';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';
import { stubRegionEndpoints } from './helpers/stubRegionEndpoints';
import { stubConfigEndpoint } from './helpers/stubConfigEndpoint';

// --- SSE fixture server ----------------------------------------------------
// A real, held-open Node `http` server (see `badges.spec.ts`'s file-header
// comment for why `page.route().fulfill()` can't model a live, multi-event
// stream). One connection is accepted and held open for the whole test;
// `push()` writes additional `snapshot`/`layer_status` SSE blocks down it on
// demand, letting the test drive each transition as if a real backend were
// pushing scheduler-driven status changes.

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
    res.setHeader('Access-Control-Allow-Origin', '*'); // cross-origin redirect target
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
      // Deliberately no res.end() — held open for the whole test.
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

/** Defensive REST fallback stubs — see file-header "DEFENSIVE REST FALLBACK".
 * Never asserted against directly; only keeps an incidental REST fetch from
 * 404ing noisily and tripping the zero-console-error clause. */
async function stubRestFallback(page: Page) {
  const empty = (layer: 'air' | 'marine' | 'land') => ({
    meta: {
      layer,
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: '2026-07-10T00:00:00Z',
      timestamp_source: '2026-07-10T00:00:00Z',
      cadence_s: 600,
      stale_after_s: 1200,
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
}

// --- Fixtures --------------------------------------------------------------
// meta-only (LayerSnapshotMeta) + trimmed feature lists per feature-schema.md
// "Wire examples". `features` kept minimal — this test asserts source
// feature COUNT (map rendering itself is `layers-refresh.spec.ts`'s job).

interface Meta {
  layer: 'air' | 'marine' | 'land';
  region_id: string;
  status: string;
  timestamp_fetched: string | null;
  timestamp_source: string | null;
  cadence_s: number;
  stale_after_s: number;
  feature_count: number;
  retry_after_s: number | null;
  detail: string | null;
}

function meta(layer: Meta['layer'], overrides: Partial<Meta> = {}): Meta {
  return {
    layer,
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-10T10:00:00Z',
    timestamp_source: '2026-07-10T09:59:55Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 2,
    retry_after_s: null,
    detail: null,
    ...overrides,
  };
}

function airFeature(sourceId: string, timestampFetched: string) {
  return {
    domain: 'air',
    source: 'opensky',
    source_id: sourceId,
    label: `FLT${sourceId}`,
    lat: 26.61,
    lon: 56.27,
    geometry_type: 'point',
    geometry: null,
    timestamp_source: '2026-07-10T09:59:55Z',
    timestamp_fetched: timestampFetched,
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
  };
}

function landFeature(sourceId: string, kind: 'road' | 'point') {
  if (kind === 'road') {
    return {
      domain: 'land',
      source: 'overpass',
      source_id: sourceId,
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
      timestamp_source: '2026-07-10T00:00:00Z',
      timestamp_fetched: '2026-07-10T00:00:11Z',
      position_age_s: 100.0,
      status: 'live',
      integrity_flags: [],
      attrs: { highway: 'motorway', ref: 'E15', surface: 'asphalt' },
    };
  }
  return {
    domain: 'land',
    source: 'overpass',
    source_id: sourceId,
    label: 'Shahid Rajaee Port',
    lat: 27.1,
    lon: 56.06,
    geometry_type: 'point',
    geometry: null,
    timestamp_source: '2026-07-10T00:00:00Z',
    timestamp_fetched: '2026-07-10T00:00:11Z',
    position_age_s: 100.0,
    status: 'live',
    integrity_flags: [],
    attrs: { harbour: 'yes', landuse: 'port' },
  };
}

/** `window.__zijMap.getSource(id)` feature count (map-init seam, reused
 * verbatim from `layers-refresh.spec.ts`). */
async function sourceFeatureCount(page: Page, id: 'air' | 'land'): Promise<number> {
  return page.evaluate((sourceId) => {
    const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
      .__zijMap;
    const source = map.getSource(sourceId);
    if (!source) return -1;
    const data = source.serialize().data as { features: unknown[] };
    return data.features.length;
  }, id);
}

test(
  "toggling a layer off issues POST .../toggle {enabled:false}, clears its map source and grays its badge; per-badge Refresh issues POST .../refresh and rides loading->live via SSE (no polling), disabling its own button meanwhile; global Refresh all issues POST /api/refresh",
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

      // Route interception MUST be registered before goto. NOTE: each
      // corresponding `page.waitForRequest(...)` promise is created
      // just-in-time, immediately before the click that is expected to
      // trigger it (and awaited immediately after) — never created upfront
      // and left dangling, since an earlier assertion failing first (as
      // every one of these does today, pre-implementation) would otherwise
      // leave a later `waitForRequest` promise's own internal timeout to
      // reject asynchronously, unhandled, well after the test has already
      // finished failing.
      await stubEvents(page, fixtureUrl);
      await stubRestFallback(page);
      await stubRegionEndpoints(page);
      await stubConfigEndpoint(page);

      await page.route('**/api/layers/land/toggle', async (route) => {
        expect(route.request().method()).toBe('POST');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ layer: 'land', enabled: false }),
        });
      });

      await page.route('**/api/layers/air/refresh', async (route) => {
        expect(route.request().method()).toBe('POST');
        await route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({ layer: 'air', queued: true }),
        });
      });

      await page.route('**/api/refresh', async (route) => {
        expect(route.request().method()).toBe('POST');
        await route.fulfill({
          status: 202,
          contentType: 'application/json',
          // `land` deliberately excluded — it was toggled off below, so a
          // real backend would not queue it (FR6 "all enabled layers").
          body: JSON.stringify({ queued: ['air', 'marine'] }),
        });
      });

      await page.goto('/');
      await fixture.connected;

      // === Given: badges mounted, layers enabled, initial live snapshots ===
      const airBadge = page.locator('[data-testid="badge-air"]');
      const landBadge = page.locator('[data-testid="badge-land"]');

      fixture.push('snapshot', {
        meta: meta('air', { feature_count: 2 }),
        features: [airFeature('896451', '2026-07-10T10:00:00Z'), airFeature('896452', '2026-07-10T10:00:00Z')],
      });
      fixture.push('snapshot', {
        meta: meta('land', { feature_count: 2 }),
        features: [landFeature('way/1001', 'road'), landFeature('node/998811', 'point')],
      });
      fixture.push('snapshot', { meta: meta('marine', { feature_count: 0 }), features: [] });

      await page.waitForFunction(() => {
        const map = (window as unknown as { __zijMap?: { getSource(id: string): unknown } }).__zijMap;
        return Boolean(map && map.getSource('air') && map.getSource('land'));
      });

      await expect(airBadge).toHaveAttribute('data-status', 'live');
      await expect(landBadge).toHaveAttribute('data-status', 'live');

      // REQUIRED SEAM #1: layers start enabled.
      await expect(landBadge, 'badge must expose data-enabled, defaulting to "true"').toHaveAttribute(
        'data-enabled',
        'true',
      );

      await expect.poll(() => sourceFeatureCount(page, 'land')).toBe(2);

      // === When: land's Toggle is switched off ================================
      const toggleRequestPromise = page.waitForRequest(
        (req) => req.url().includes('/api/layers/land/toggle') && req.method() === 'POST',
        { timeout: 5_000 },
      );
      await landBadge.locator('[data-testid="toggle-button"]').click();
      const toggleRequest = await toggleRequestPromise;

      // Then: POST /api/layers/land/toggle {enabled:false} is issued...
      expect(toggleRequest.method()).toBe('POST');
      expect(toggleRequest.postDataJSON()).toEqual({ enabled: false });

      // ...its source clears (REQUIRED SEAM #3)...
      await expect.poll(() => sourceFeatureCount(page, 'land'), {
        message: 'land GeoJSON source must clear to zero features once toggled off',
      }).toBe(0);

      // ...and the badge grays (REQUIRED SEAM #1/#2: data-enabled -> "false").
      await expect(landBadge).toHaveAttribute('data-enabled', 'false');

      // === And: no further SSE events are expected for that layer ============
      // (asserted implicitly below — this test never pushes another `land`
      // event for the rest of the run, and re-checks land's state at the very
      // end, after unrelated air/global-refresh activity, to prove nothing
      // spuriously re-enables or re-renders it.)

      // === When: air's Refresh button is clicked ==============================
      const refreshButton = airBadge.locator('[data-testid="refresh-button"]');
      await expect(refreshButton).toBeEnabled();
      const refreshRequestPromise = page.waitForRequest(
        (req) => req.url().includes('/api/layers/air/refresh') && req.method() === 'POST',
        { timeout: 5_000 },
      );
      await refreshButton.click();
      const refreshRequest = await refreshRequestPromise;

      // Then: POST /api/layers/air/refresh is issued...
      expect(refreshRequest.method()).toBe('POST');

      // ...and the badge reflects loading via SSE (REQUIRED SEAM #4/#5) — push
      // the `loading` layer_status the way a real backend would on accepting
      // the refresh request.
      fixture.push(
        'layer_status',
        meta('air', { status: 'loading', timestamp_fetched: null, timestamp_source: null, feature_count: 2 }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'loading');
      await expect(airBadge.locator('[data-testid="status-label"]')).toHaveText('Loading…');
      await expect(refreshButton, 'refresh-button must disable while its badge is loading').toBeDisabled();

      // ...then live via SSE (no polling) — REQUIRED SEAM #4: the new feature
      // count/source data must come from this pushed `snapshot`, never from a
      // REST re-fetch (the only air/land GET stubs in this test are the
      // defensive EMPTY fallback, which would fail these exact assertions).
      fixture.push('snapshot', {
        meta: meta('air', { status: 'live', feature_count: 3 }),
        features: [
          airFeature('896451', '2026-07-10T10:05:00Z'),
          airFeature('896452', '2026-07-10T10:05:00Z'),
          airFeature('896453', '2026-07-10T10:05:00Z'),
        ],
      });
      await expect(airBadge).toHaveAttribute('data-status', 'live');
      await expect(airBadge.locator('[data-testid="feature-count"]')).toContainText('3');
      await expect(refreshButton, 'refresh-button must re-enable once loading ends').toBeEnabled();
      await expect.poll(() => sourceFeatureCount(page, 'air'), {
        message: 'air GeoJSON source must reflect the SSE-pushed snapshot, not a REST fallback',
      }).toBe(3);

      // === When: the global Refresh all is clicked ============================
      const refreshAllButton = page.locator('[data-testid="refresh-all"]');
      await expect(refreshAllButton).toBeVisible();
      const refreshAllRequestPromise = page.waitForRequest(
        (req) => req.url().endsWith('/api/refresh') && req.method() === 'POST',
        { timeout: 5_000 },
      );
      await refreshAllButton.click();
      const refreshAllRequest = await refreshAllRequestPromise;

      // Then: POST /api/refresh is issued.
      expect(refreshAllRequest.method()).toBe('POST');

      // --- Land was never pushed another event: still off, still cleared -----
      await expect(landBadge).toHaveAttribute('data-enabled', 'false');
      expect(await sourceFeatureCount(page, 'land')).toBe(0);

      // --- Clause: no uncaught console error / page error at any point -------
      expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
      expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
    } finally {
      await fixture.shutdown();
    }
  },
);
