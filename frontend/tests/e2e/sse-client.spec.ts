/**
 * DEC-1 locked outer acceptance test — frontend/01-sse-client (issue #57),
 * the first v1 frontend slice (walking skeleton for the live-update spine).
 * Encodes `plans/frontend/01-sse-client.md`'s Gherkin verbatim:
 *
 *   Given the app connected to a stub /api/events emitting a snapshot per
 *         enabled layer
 *   When  the page loads
 *   Then  the store receives each layer's snapshot and the map renders it
 *         (full-state-on-connect)
 *   When  the SSE stream drops
 *   Then  a non-blocking "Reconnecting…" banner appears and the map stays
 *         interactive
 *   When  the connection fails fatally (readyState CLOSED)
 *   Then  a "Connection failed — Retry" action is shown
 *
 * This scenario ran under `test.fail()` (this web slice's analog to a strict
 * pytest xfail, DEC-33 — see `layers-refresh.spec.ts` for the precedent this
 * repo standardized on) from the slice's red commit until the implementer
 * greened the underlying behavior. The test-author confirmed every clause
 * below passes for real and removed the marker in the final pass, so this
 * now runs as a normal `test(...)`.
 *
 * SCOPE NOTE (marine excluded): `design/specs/frontend.md` §2 has no marine
 * map-layer builder yet (`map/layers/marine.ts` does not exist — the plan's
 * own "Out of scope (deferred)" list defers "marine + integrity rendering"
 * to slice 06). This test's stub therefore emits `snapshot` only for the two
 * domains this codebase can already render (air, land) — a stub server
 * exercising a fully-enabled three-layer config's `event: snapshot` fan-out
 * is the SseClient/store's job to handle generically per-domain regardless
 * of layer count, and is covered by this slice's inner Vitest dispatch
 * tests, not by asserting unimplemented marine rendering at the e2e
 * boundary.
 *
 * STUB MECHANISM (revised from the original `page.route().fulfill()` draft):
 * there is no live FastAPI backend in this e2e run (`playwright.config.ts`
 * serves the built static `vite preview` bundle on :4173). `route.fulfill()`
 * delivers its `body` atomically — the whole response completes in one shot
 * — so a native `EventSource` fed that way opens, dispatches every queued
 * event, and hits body-end (an unexpected close) within the same task turn.
 * There is no way to observe a genuine "connected, streaming, then dropped"
 * window with that mechanism: `fulfill()` cannot hold a socket open.
 *
 * Instead this test runs a REAL streaming HTTP server (Node `http`, on an
 * ephemeral loopback port, in this same Playwright/Node process — no IPC
 * needed) and uses `route.continue({ url })` to redirect the browser's
 * `/api/events` request to it. Unlike `fulfill()`, `continue()` lets the
 * browser perform a genuine network request, so the real server can:
 *
 *   - Attempt #1: write `200` + `text/event-stream` headers, flush the
 *     `retry:` directive and both `event: snapshot` blocks, then HOLD the
 *     connection open (no `res.end()`) — a real, observable "connected and
 *     streaming" window the test asserts against before doing anything else.
 *     The test then explicitly ends that response once its "connected"
 *     assertions have run, modeling "the SSE stream drops": per the WHATWG
 *     EventSource spec this is an unexpected close, so the browser fires
 *     `error`, sets `readyState = CONNECTING`, and (per the `retry: 1000`
 *     directive) auto-reconnects ~1s later.
 *   - Attempt #2+ (the automatic reconnect, and any manual Retry): `500`.
 *     Per spec, a non-`200` status on connect fails the connection
 *     permanently (`readyState = CLOSED`, `error` fires, no further native
 *     retry) — this models "the connection fails fatally".
 *
 * The redirect target is cross-origin (a different port), so the real
 * server sets a permissive `Access-Control-Allow-Origin` header — a bare GET
 * EventSource request is CORS-simple (no custom headers), so no preflight
 * is needed, only that response header on the actual response.
 *
 * REQUIRED TEST SEAMS (implementer must expose these — not the test-author's
 * to relax; each is independently asserted below):
 *
 *   1. `window.__zijMap`, GeoJSON sources `"air"`/`"land"`, and the
 *      `[data-testid="badge-{air,land}"]` / `freshness-fetched` /
 *      `freshness-source` / `feature-count` seams — all reused verbatim
 *      from `map-init.spec.ts` / `layers-refresh.spec.ts`. Proves
 *      full-state-on-connect: the store applied each pushed `snapshot`
 *      and the map/badges rendered from it, with no REST call required.
 *   2. `[data-testid="connection-banner"]` — the single global banner
 *      (spec §3/§7). Hidden while `connection` is `connecting`/`open`.
 *      Visible and containing the literal text "Reconnecting…" while
 *      `connection === 'lost'`. Visible and containing the literal text
 *      "Connection failed" while `connection === 'failed'`.
 *   3. `[data-testid="connection-retry"]` — the manual retry action, only
 *      present/visible in the `failed` state, text containing "Retry",
 *      and wired to actually re-run `connect()` (clicking it must issue a
 *      new HTTP request to `/api/events` — an inert button would not
 *      satisfy "a ... Retry action is shown" in any meaningful sense).
 *
 * This test is not the test-author's to loosen and not the implementer's to
 * touch.
 */

import { test, expect, type Page } from '@playwright/test';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import { AddressInfo } from 'node:net';

// --- Fixtures ------------------------------------------------------------
// Modeled on design/contracts/feature-schema.md "Wire examples" (kept small
// — this slice proves dispatch + render wiring, not exhaustive per-domain
// rendering, which layers-refresh.spec.ts already covers for air/land).

const AIR_SNAPSHOT = {
  meta: {
    layer: 'air',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-09T10:05:03Z',
    timestamp_source: '2026-07-09T10:04:58Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 1,
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
      timestamp_source: '2026-07-09T10:04:58Z',
      timestamp_fetched: '2026-07-09T10:05:03Z',
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
  ],
};

const LAND_SNAPSHOT = {
  meta: {
    layer: 'land',
    region_id: 'hormuz',
    status: 'live',
    timestamp_fetched: '2026-07-08T02:00:11Z',
    timestamp_source: '2026-07-07T00:00:00Z',
    cadence_s: 86400,
    stale_after_s: 172800,
    feature_count: 1,
    retry_after_s: null,
    detail: null,
  },
  features: [
    {
      domain: 'land',
      source: 'overpass',
      source_id: 'node/998811',
      label: 'Shahid Rajaee Port',
      lat: 27.1,
      lon: 56.06,
      geometry_type: 'point',
      geometry: null,
      timestamp_source: '2026-07-07T00:00:00Z',
      timestamp_fetched: '2026-07-08T02:00:11Z',
      position_age_s: 118211.0,
      status: 'live',
      integrity_flags: [],
      attrs: { harbour: 'yes', landuse: 'port' },
    },
  ],
};

/** Renders one SSE wire block: `event:`/`id:`/`data:` lines terminated by
 * the blank line that dispatches it (WHATWG EventSource wire format). */
function sseEvent(event: string, id: number, data: unknown): string {
  return `event: ${event}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * A real streaming HTTP server standing in for `/api/events`. Runs in this
 * same Node process (no IPC needed): the test body holds a direct reference
 * to the in-flight response and decides, in real time, when "the stream
 * drops" by ending it itself.
 *
 * Attempt #1 connects, streams both fixture snapshots, and stays open (no
 * `res.end()`) until `dropFirstConnection()` is called. Every subsequent
 * attempt (native reconnect, or a manual Retry click) answers `500` — a
 * fatal, non-2xx connect response — modeling the permanent-failure clause.
 */
function startSseFixtureServer(): {
  url: string;
  server: Server;
  attempts: () => number;
  dropFirstConnection: () => void;
  shutdown: () => Promise<void>;
} {
  let attempts = 0;
  let firstResponse: ServerResponse | null = null;
  // Every socket that ever connects, tracked so shutdown() can force-close
  // sockets a browser keeps alive/idle rather than waiting on them — Node's
  // `server.close()` only stops accepting NEW connections and otherwise
  // waits indefinitely for already-open (e.g. keep-alive) sockets, which
  // hangs the Playwright worker process well past the test's own pass/fail.
  const sockets = new Set<import('node:net').Socket>();

  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    attempts += 1;
    // Cross-origin (the redirect target is a different port than the app
    // origin) — a bare GET EventSource request is CORS-simple, so only the
    // response header (no preflight) is needed.
    res.setHeader('Access-Control-Allow-Origin', '*');

    if (attempts === 1) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      // A 1s native retry interval leaves ample headroom between the drop
      // (triggered explicitly by the test, below) and the reconnect attempt.
      res.write('retry: 1000\n\n');
      res.write(sseEvent('snapshot', 1, AIR_SNAPSHOT));
      res.write(sseEvent('snapshot', 2, LAND_SNAPSHOT));
      const flushable = res as ServerResponse & { flushHeaders?: () => void };
      flushable.flushHeaders?.();
      req.socket.setNoDelay(true);
      // Deliberately no res.end() here — held open until the test calls
      // dropFirstConnection() once its "connected" assertions have run.
      firstResponse = res;
    } else {
      // Any non-2xx status on (re)connect fails an EventSource permanently
      // (readyState CLOSED) per the WHATWG spec — the fatal-failure clause.
      res.writeHead(500, { 'Content-Type': 'text/plain' });
      res.end('stub: simulated fatal SSE failure');
    }
  });

  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });

  return {
    url: '', // filled in by caller after listen()
    server,
    attempts: () => attempts,
    dropFirstConnection: () => {
      firstResponse?.end();
      firstResponse = null;
    },
    shutdown: async () => {
      firstResponse?.end();
      firstResponse = null;
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

/** Redirects the app's same-origin `/api/events` request to the real
 * streaming fixture server above via `route.continue({ url })` — unlike
 * `route.fulfill()`, `continue()` lets the browser perform a genuine network
 * request against the new URL, so the fixture server can hold the
 * connection open for real. Registered BEFORE navigation. */
async function stubEvents(page: Page, fixtureUrl: string): Promise<void> {
  await page.route('**/api/events', async (route) => {
    await route.continue({ url: fixtureUrl });
  });
}

/** Defensive REST fallback stubs (snapshot GET / global refresh POST) so
 * that if the app also issues an initial/independent REST fetch alongside
 * SSE (api.md: "GET /api/layers/{domain}/snapshot ... used for initial load
 * and reconnect-independent fetches"), it resolves quietly rather than
 * 404ing — mirrors the RECONCILIATION precedent in map-init.spec.ts. This
 * test does not assert on these endpoints being called. */
async function stubRestFallback(page: Page) {
  await page.route('**/api/layers/air/snapshot', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(AIR_SNAPSHOT) });
  });
  await page.route('**/api/layers/land/snapshot', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LAND_SNAPSHOT) });
  });
  await page.route('**/api/refresh', async (route) => {
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ queued: [] }) });
  });
}

test(
  'SSE client dispatches full-state-on-connect, shows Reconnecting… on drop, and Connection failed — Retry on fatal close',
  async ({ page }) => {
    const fixture = startSseFixtureServer();
    const fixtureUrl = await listenEphemeral(fixture.server);
    (fixture as { url: string }).url = fixtureUrl;

    try {
      const pageErrors: string[] = [];
      page.on('pageerror', (err) => {
        pageErrors.push(err.message);
      });

      // Route interception MUST be registered before goto — there is no live
      // FastAPI backend in this e2e run.
      await stubEvents(page, fixtureUrl);
      await stubRestFallback(page);

      await page.goto('/');

      // === Clause: page loads -> store receives each snapshot, map renders ===
      // (full-state-on-connect; no REST call required to see this data).
      await page.waitForFunction(() => {
        const map = (window as unknown as { __zijMap?: { getSource(id: string): unknown } }).__zijMap;
        return Boolean(map && map.getSource('air') && map.getSource('land'));
      });

      const airBadge = page.locator('[data-testid="badge-air"]');
      await expect(airBadge.locator('[data-testid="freshness-fetched"]')).toHaveText('10:05:03 UTC');
      await expect(airBadge.locator('[data-testid="freshness-source"]')).toHaveText('10:04:58 UTC');
      await expect(airBadge.locator('[data-testid="feature-count"]')).toContainText('1');

      const landBadge = page.locator('[data-testid="badge-land"]');
      await expect(landBadge.locator('[data-testid="freshness-fetched"]')).toHaveText('02:00:11 UTC');
      await expect(landBadge.locator('[data-testid="freshness-source"]')).toHaveText('00:00:00 UTC');
      await expect(landBadge.locator('[data-testid="feature-count"]')).toContainText('1');

      const airSourceData = await page.evaluate(() => {
        const map = (
          window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } }
        ).__zijMap;
        return map.getSource('air').serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
      });
      expect(new Set(airSourceData.features.map((f) => f.properties.source_id))).toEqual(new Set(['896451']));

      const landSourceData = await page.evaluate(() => {
        const map = (
          window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } }
        ).__zijMap;
        return map.getSource('land').serialize().data as {
          features: Array<{ properties: Record<string, unknown> }>;
        };
      });
      expect(new Set(landSourceData.features.map((f) => f.properties.source_id))).toEqual(
        new Set(['node/998811']),
      );

      const canvas = page.locator('.maplibregl-canvas');
      await expect(canvas).toBeVisible();
      const canvasBoxOpen = await canvas.boundingBox();
      expect(canvasBoxOpen, 'map canvas must have a bounding box').not.toBeNull();

      // While connected (open), the banner must be hidden — a banner that is
      // always rendered would trivially satisfy the later clauses, so this
      // guards against that stub.
      const banner = page.locator('[data-testid="connection-banner"]');
      await expect(banner).toBeHidden();

      // === Clause: the SSE stream drops -> non-blocking "Reconnecting…" =====
      // banner appears, map stays interactive on last-known state. The drop
      // is triggered for real: the fixture server's still-open first
      // response is ended now, which is an unexpected close for a live
      // EventSource connection.
      fixture.dropFirstConnection();

      await expect(banner).toBeVisible();
      await expect(banner).toContainText('Reconnecting…');

      // Map stays interactive: canvas still visible, last-known GeoJSON state
      // is untouched (not cleared while merely "lost"), and the banner is a
      // slim strip (non-blocking), not a full-viewport overlay.
      await expect(canvas).toBeVisible();
      const airSourceDataDuringLoss = await page.evaluate(() => {
        const map = (
          window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } }
        ).__zijMap;
        return map.getSource('air').serialize().data as { features: unknown[] };
      });
      expect(airSourceDataDuringLoss.features).toHaveLength(1);
      const landSourceDataDuringLoss = await page.evaluate(() => {
        const map = (
          window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } }
        ).__zijMap;
        return map.getSource('land').serialize().data as { features: unknown[] };
      });
      expect(landSourceDataDuringLoss.features).toHaveLength(1);

      const bannerBoxLost = await banner.boundingBox();
      expect(bannerBoxLost, 'banner must have a bounding box while visible').not.toBeNull();
      if (bannerBoxLost && canvasBoxOpen) {
        expect(
          bannerBoxLost.height,
          'the "Reconnecting…" banner must be a slim non-blocking strip, not a full-viewport overlay',
        ).toBeLessThan(canvasBoxOpen.height * 0.5);
      }

      const retryButtonBeforeFail = page.locator('[data-testid="connection-retry"]');
      await expect(
        retryButtonBeforeFail,
        'no Retry action while merely "lost" (only on fatal failure)',
      ).toBeHidden();

      // === Clause: the connection fails fatally (readyState CLOSED) -> a =====
      // "Connection failed — Retry" action is shown. The native reconnect
      // (retry: 1000) re-requests /api/events, which the fixture server now
      // answers with a fatal 500 (attempts() > 1).
      await expect(banner).toContainText('Connection failed', { timeout: 10_000 });
      expect(fixture.attempts()).toBeGreaterThan(1);

      const retryButton = page.locator('[data-testid="connection-retry"]');
      await expect(retryButton).toBeVisible();
      await expect(retryButton).toContainText('Retry');

      // The Retry action must be wired for real: clicking it re-runs connect()
      // and issues a fresh HTTP request to /api/events (an inert button would
      // not satisfy "a ... Retry action is shown" in any meaningful sense).
      const retryRequestPromise = page.waitForRequest(
        (req) => req.url().includes('/api/events') && req.method() === 'GET',
      );
      await retryButton.click();
      await retryRequestPromise;

      // --- Clause: no uncaught page error at any point in the above sequence -
      expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
    } finally {
      await fixture.shutdown();
    }
  },
);
