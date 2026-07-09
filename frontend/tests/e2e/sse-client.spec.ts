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
 * `test.fail()` below is this web slice's analog to a strict pytest xfail
 * (DEC-33) — see `layers-refresh.spec.ts` for the precedent this repo has
 * standardized on. It marks the scenario "expected to fail." An unexpected
 * *pass* fails the run, so once the implementer greens the behavior, this
 * file must flip to failing-the-run until the test-author removes the
 * `test.fail()` marker in the final pass.
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
 * STUB MECHANISM: there is no live FastAPI backend in this e2e run
 * (`playwright.config.ts` serves the built static `vite preview` bundle on
 * :4173). `/api/events` is intercepted with `page.route()`, one live
 * `EventSource` connection attempt per intercepted request (exactly how the
 * browser's native EventSource reconnect issues a fresh HTTP request each
 * time). Per the WHATWG EventSource spec (processing model, §9.2), the
 * *shape* of each HTTP response fully determines the client's next
 * `readyState` without needing genuine long-lived streaming control:
 *
 *   - Attempt #1: `200`, `Content-Type: text/event-stream`, a body carrying
 *     a `retry: 1000` directive plus one `event: snapshot` block per
 *     stubbed layer, then the response ends (Playwright's `route.fulfill`
 *     always sends a complete body). A `text/event-stream` response ending
 *     without the client having called `.close()` is, per spec, an
 *     unexpected close — the browser queues the *reconnect* steps:
 *     `readyState = CONNECTING`, fires `error`, waits the `retry` interval,
 *     then re-fetches. This is what "the SSE stream drops" models, with no
 *     need to hold a socket open across the test.
 *   - Attempt #2 (the automatic reconnect): `500`. Per spec, a non-`200`
 *     status on connect *fails the connection permanently* —
 *     `readyState = CLOSED`, `error` fires, and the browser does not retry
 *     again. This is what "the connection fails fatally" models.
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
 * touch. Removing `test.fail()` happens only once every assertion below
 * passes for real, in the test-author's final marker-removal pass.
 */

import { test, expect, type Page } from '@playwright/test';

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

/** Registers page.route() interception for /api/events BEFORE navigation.
 * See the STUB MECHANISM note above the imports for why each attempt's HTTP
 * response shape alone is sufficient to drive the browser's native
 * EventSource through connecting -> open -> (drop) -> lost -> (fatal) ->
 * failed, with no long-lived streaming control needed. */
async function stubEvents(page: Page): Promise<{ attempts: () => number }> {
  let attempts = 0;

  await page.route('**/api/events', async (route) => {
    attempts += 1;
    if (attempts === 1) {
      // A 1s native retry interval leaves ample headroom to assert the
      // "connected, banner hidden" state before the natural body-end drop.
      const body =
        `retry: 1000\n\n` +
        sseEvent('snapshot', 1, AIR_SNAPSHOT) +
        sseEvent('snapshot', 2, LAND_SNAPSHOT);
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body,
      });
    } else {
      // Any non-2xx status on (re)connect fails an EventSource permanently
      // (readyState CLOSED) per the WHATWG spec — the fatal-failure clause.
      await route.fulfill({
        status: 500,
        contentType: 'text/plain',
        body: 'stub: simulated fatal SSE failure',
      });
    }
  });

  return { attempts: () => attempts };
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

test.fail(
  'SSE client dispatches full-state-on-connect, shows Reconnecting… on drop, and Connection failed — Retry on fatal close',
  async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });

    // Route interception MUST be registered before goto — there is no live
    // FastAPI backend in this e2e run.
    await stubEvents(page);
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
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('air').serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
    });
    expect(new Set(airSourceData.features.map((f) => f.properties.source_id))).toEqual(new Set(['896451']));

    const landSourceData = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('land').serialize().data as { features: Array<{ properties: Record<string, unknown> }> };
    });
    expect(new Set(landSourceData.features.map((f) => f.properties.source_id))).toEqual(new Set(['node/998811']));

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
    // banner appears, map stays interactive on last-known state.
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Reconnecting…');

    // Map stays interactive: canvas still visible, last-known GeoJSON state
    // is untouched (not cleared while merely "lost"), and the banner is a
    // slim strip (non-blocking), not a full-viewport overlay.
    await expect(canvas).toBeVisible();
    const airSourceDataDuringLoss = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
      return map.getSource('air').serialize().data as { features: unknown[] };
    });
    expect(airSourceDataDuringLoss.features).toHaveLength(1);
    const landSourceDataDuringLoss = await page.evaluate(() => {
      const map = (window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: unknown } } } })
        .__zijMap;
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
    await expect(retryButtonBeforeFail, 'no Retry action while merely "lost" (only on fatal failure)').toBeHidden();

    // === Clause: the connection fails fatally (readyState CLOSED) -> a =====
    // "Connection failed — Retry" action is shown.
    await expect(banner).toContainText('Connection failed', { timeout: 10_000 });

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
  },
);
