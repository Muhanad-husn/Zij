/**
 *  locked outer acceptance test — frontend/03-region-selector (issue
 * #59). Encodes `plans/frontend/03-region-selector.md`'s Gherkin verbatim:
 *
 *   Given the app with the region endpoints served
 *   When  a predefined region is selected from the dropdown
 *   Then  POST /api/regions/activate {region_id} is issued and its credit
 *         cost was shown inline
 *   When  a custom bbox exceeding a layer's cap is entered
 *   Then  the layer's cap-naming message is shown and Confirm is disabled
 *         before activation
 *   When  a valid custom bbox is confirmed
 *   Then  POST /api/regions/activate {bbox,label} is issued and the map
 *         clears on region_changed
 *
 * `test.fail()` was this web slice's analog to a strict pytest xfail (
 * — see `layers-refresh.spec.ts`/`badges.spec.ts`/`sse-client.spec.ts` for
 * the precedent this repo standardized on): with no `ui/regionSelector.ts`
 * yet, every clause below failed, `test.fail()` made that an EXPECTED
 * failure so the suite reported green and the red commit landed under the
 * no-commit-on-red gate. the developer has since greened every clause; the
 * author confirmed each assertion passes for real and removed the
 * `test.fail()` marker in this final pass (mirroring every prior frontend
 * slice's follow-up commit) — this is now a normal `test()` and the
 * locked contract stands finalized.
 *
 * SCOPE NOTE (no marine map layer): `design/specs/frontend.md` §2 has no
 * marine map-layer builder yet (deferred to step per the plan's "Out of
 * scope" list). The `region_changed` clause therefore asserts only the air
 * and land GeoJSON source clear (mirroring `sse-client.spec.ts`'s own scope
 * note), never a marine map source.
 *
 * SCOPE NOTE (draw-on-map vs coordinate entry): spec §6 offers two custom
 * bbox input modes — draw-on-map (mouse drag over the canvas) and enter-
 * coordinates (four number inputs). The plan calls the coordinate path "the
 * keyboard-drivable one to drive in Playwright" — a mouse-drag-over-WebGL-
 * canvas interaction is unreliable at this e2e boundary, so this test drives
 * ONLY the coordinate-input mode. The draw-on-map handler is not exercised
 * or locked by this test.
 *
 * STUB MECHANISM: no live FastAPI backend in this e2e run
 * (`playwright.config.ts` serves the built `vite preview` bundle on :4173).
 * The four REST region endpoints (`GET /api/regions`, `POST
 * /api/regions/estimate`, `POST /api/regions/activate`, `GET
 * /api/regions/active`) are ordinary atomic request/response cycles, so
 * `page.route().fulfill()` is correct for them (per `layers-refresh.spec.ts`
 * precedent). `region_changed`, however, arrives over the live SSE stream
 * (api.md `GET /api/events`) — an atomic `fulfill()` body cannot model a
 * live push mid-test (see `sse-client.spec.ts`'s file-header STUB MECHANISM
 * comment for the full rationale: `fulfill()` delivers its body in one shot,
 * so a native `EventSource` fed that way opens and hits an unexpected close
 * in the same task turn — there is no way to hold it open and push a
 * later event). This test therefore runs a REAL streaming Node `http` server
 * on an ephemeral loopback port (mirroring `badges.spec.ts`'s
 * `startEventsFixtureServer` pattern exactly), redirects the browser's
 * `/api/events` request to it via `route.continue({ url })`, holds ONE
 * connection open for the whole test, and pushes a single `region_changed`
 * SSE block down it once the custom-bbox activation has been observed —
 * proving "the map clears on region_changed" against a real push, not a
 * page reload or a REST re-fetch.
 *
 * REQUIRED TEST SEAMS (developer must expose these — not the author's
 * to relax; each is independently asserted below):
 *
 *   1. `[data-testid="region-select"]` — a native `<select>` in the top bar
 *      (spec §7 "[Region: ... ▾]"), populated from `GET /api/regions` once
 *      it resolves. One `<option value="{id}">` per region, each carrying a
 *      `data-credit-cost="{aviation_credit_cost}"` attribute AND visible
 *      option text that contains that same numeral — both are asserted, so
 *      "each option showing its aviation_credit_cost inline" (plan Goal) is
 *      locked at the DOM-text level, not just a data attribute an
 *      developer could add without ever rendering it.
 *   2. `[data-testid="region-cost"]` — an element that, after a predefined
 *      region is selected, displays that SPECIFIC region's
 *      `aviation_credit_cost` (this test asserts its text contains the
 *      selected region's own cost number, distinguishing it from any other
 *      region's cost so a hardcoded/stale display would fail this check).
 *   3. `[data-testid="custom-bbox-toggle"]` — the top bar "Custom bbox…"
 *      button (spec §7). Clicking it reveals the coordinate-entry panel.
 *   4. `[data-testid="custom-bbox-panel"]` — the panel container, hidden
 *      until the toggle above is clicked.
 *   5. Within the panel: `[data-testid="bbox-west"]`,
 *      `[data-testid="bbox-south"]`, `[data-testid="bbox-east"]`,
 *      `[data-testid="bbox-north"]` — four `<input type="number">` fields
 *      (spec §6 "enter coordinates" mode), and `[data-testid="bbox-label"]`
 *      — a text input for the custom region's label (needed to build the
 *      `POST /api/regions/activate {bbox,label}` payload).
 *   6. Changing any of the four coordinate fields triggers, after a
 *      debounce (spec §6 "~300 ms"), exactly ONE `POST
 *      /api/regions/estimate {bbox}` call reflecting the fields' current
 *      values — not one call per keystroke/field. This test fills all four
 *      fields back-to-back with no artificial delay between them and
 *      asserts exactly one estimate request lands per round of edits.
 *   7. `[data-testid="bbox-estimate-area"]` / `[data-testid="bbox-estimate-
 *      cost"]` — render the estimate response's `area_sq_deg` /
 *      `aviation_credit_cost` VERBATIM (spec §6: "all math ... is
 *      server-computed and only formatted for display here"). This test
 *      asserts the displayed numbers equal the stub's numbers exactly,
 *      which would fail if the frontend ever recomputed them client-side
 *      from the raw bbox instead of trusting the response.
 *   8. `[data-testid="bbox-cap-message-air"]`,
 *      `[data-testid="bbox-cap-message-land"]`,
 *      `[data-testid="bbox-cap-message-marine"]` — one element per layer.
 *      When that layer's `layer_caps[layer].ok === false`, the element is
 *      visible and its text contains the response's `message` VERBATIM
 *      (api.md: "message ... names the exceeded cap", FR1 acceptance).
 *   9. `[data-testid="bbox-confirm"]` — the Confirm button. `disabled`
 *      whenever the current estimate has any `ok:false` layer (or no valid
 *      estimate is in hand yet); enabled once a fully-`ok:true` estimate has
 *      been rendered. Clicking it issues `POST /api/regions/activate
 *      {bbox,label}`.
 *  10. `window.__zijMap`, GeoJSON sources `"air"`/`"land"` — reused verbatim
 *      from `map-init.spec.ts`/`sse-client.spec.ts`/`layers-refresh.spec.ts`.
 *      Proves the "map clears on region_changed" clause: each source's
 *      `.serialize().data.features` must be empty immediately after the SSE
 *      `region_changed` push.
 *
 * This test is not the author's to loosen and not the developer's to
 * touch.
 */

import { test, expect, type Page, type Route } from '@playwright/test';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';

// --- Fixtures --------------------------------------------------------------
// Predefined regions per api.md "GET /api/regions" (labels/costs chosen to be
// mutually distinguishable so "shown inline" / "that SPECIFIC region's cost"
// assertions can't be satisfied by a hardcoded or stale display).

const REGIONS_RESPONSE = {
  regions: [
    { id: 'hormuz', label: 'Strait of Hormuz', bbox: [55.0, 25.0, 57.5, 27.5], aviation_credit_cost: 1, kind: 'predefined' },
    { id: 'gulf-of-oman', label: 'Gulf of Oman', bbox: [56.5, 22.0, 62.0, 26.5], aviation_credit_cost: 2, kind: 'predefined' },
  ],
};

const PREDEFINED_SELECTION = REGIONS_RESPONSE.regions[1]; // gulf-of-oman, cost 2

// Custom bbox exceeding land+marine caps — api.md "POST /api/regions/estimate"
// 422 example, verbatim (bbox/area/cost/messages unchanged from the contract).
const OVER_CAP_BBOX = [40.0, 20.0, 55.0, 32.0];
const OVER_CAP_ESTIMATE_BODY = {
  valid: false,
  bbox: OVER_CAP_BBOX,
  area_sq_deg: 180.0,
  aviation_credit_cost: 3,
  layer_caps: {
    air: { ok: true, cap_sq_deg: 100, cost_credits: 3 },
    land: { ok: false, cap_sq_deg: 40, message: 'Land bbox 180.0 sq° exceeds the 40 sq° cap.' },
    marine: { ok: false, cap_sq_deg: 40, message: 'Marine bbox 180.0 sq° exceeds the 40 sq° cap.' },
  },
};

// Valid custom bbox — api.md "POST /api/regions/estimate" 200 example, verbatim.
const VALID_BBOX = [52.0, 26.0, 56.0, 29.0];
const VALID_ESTIMATE_BODY = {
  valid: true,
  bbox: VALID_BBOX,
  area_sq_deg: 12.0,
  aviation_credit_cost: 1,
  layer_caps: {
    air: { ok: true, cap_sq_deg: 100, cost_credits: 1 },
    land: { ok: true, cap_sq_deg: 40 },
    marine: { ok: true, cap_sq_deg: 40 },
  },
};

const CUSTOM_LABEL = 'My Box';

const CUSTOM_ACTIVE_REGION = {
  id: 'custom:ab12',
  label: CUSTOM_LABEL,
  bbox: VALID_BBOX,
  aviation_credit_cost: 1,
  kind: 'custom',
};

/** Minimal valid LayerSnapshot (one feature) per feature-schema.md — seeded
 * on cold start so the later "map clears" assertion has something real to
 * clear (an already-empty source clearing would be a tautology). */
function seededSnapshot(layer: 'air' | 'land') {
  return {
    meta: {
      layer,
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: '2026-07-09T10:05:03Z',
      timestamp_source: '2026-07-09T10:04:58Z',
      cadence_s: layer === 'air' ? 600 : 86400,
      stale_after_s: layer === 'air' ? 1200 : 172800,
      feature_count: 1,
      retry_after_s: null,
      detail: null,
    },
    features: [
      layer === 'air'
        ? {
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
          }
        : {
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
}

// --- SSE fixture server ------------------------------------------------
// Real, held-open Node `http` server standing in for `/api/events` — see the
// file-header STUB MECHANISM comment for why `page.route().fulfill()` cannot
// model a live mid-test push. One connection is accepted and held open for
// the whole test; `push()` writes an additional SSE block down it on demand
// (mirrors `badges.spec.ts`'s `startEventsFixtureServer` verbatim).
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

// --- REST stubs --------------------------------------------------------

interface Recorded {
  regionsRequests: number;
  estimateRequests: Array<{ bbox: number[] }>;
  activateRequests: unknown[];
}

async function stubRest(page: Page): Promise<Recorded> {
  const recorded: Recorded = { regionsRequests: 0, estimateRequests: [], activateRequests: [] };

  await page.route('**/api/regions', async (route: Route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    recorded.regionsRequests += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(REGIONS_RESPONSE) });
  });

  await page.route('**/api/regions/active', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ active_region: null }),
    });
  });

  await page.route('**/api/regions/estimate', async (route: Route) => {
    const body = route.request().postDataJSON() as { bbox: number[] };
    recorded.estimateRequests.push(body);
    if (JSON.stringify(body.bbox) === JSON.stringify(OVER_CAP_BBOX)) {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          error: {
            code: 'validation_error',
            message: 'Custom bbox exceeds one or more layer caps.',
            retry_after_s: null,
            details: OVER_CAP_ESTIMATE_BODY,
          },
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(VALID_ESTIMATE_BODY) });
  });

  await page.route('**/api/regions/activate', async (route: Route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    recorded.activateRequests.push(body);
    if ('region_id' in body) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ active_region: PREDEFINED_SELECTION }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ active_region: CUSTOM_ACTIVE_REGION }),
      });
    }
  });

  await page.route('**/api/layers/air/snapshot', async (route: Route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(seededSnapshot('air')) });
  });
  await page.route('**/api/layers/land/snapshot', async (route: Route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(seededSnapshot('land')) });
  });
  await page.route('**/api/refresh', async (route: Route) => {
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ queued: [] }) });
  });

  return recorded;
}

test(
  'region selector: predefined activation shows credit cost inline, an over-cap custom bbox blocks Confirm with the cap-naming message, a valid custom bbox activates and region_changed clears the map',
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

      // Route interception MUST be registered before goto — there is no live
      // FastAPI backend in this e2e run.
      await stubEvents(page, fixtureUrl);
      const recorded = await stubRest(page);

      await page.goto('/');
      await fixture.connected;

      // Cold-start seed: both map sources carry one feature before any
      // region action runs, so "the map clears" is a real, observable
      // transition rather than a tautology on an already-empty source.
      await page.waitForFunction(() => {
        const map = (window as unknown as { __zijMap?: { getSource(id: string): unknown } }).__zijMap;
        return Boolean(map && map.getSource('air') && map.getSource('land'));
      });
      const readSourceFeatureCount = (domain: 'air' | 'land') =>
        page.evaluate((d) => {
          const map = (
            window as unknown as { __zijMap: { getSource(id: string): { serialize(): { data: { features: unknown[] } } } } }
          ).__zijMap;
          return map.getSource(d).serialize().data.features.length;
        }, domain);
      await expect.poll(() => readSourceFeatureCount('air')).toBe(1);
      await expect.poll(() => readSourceFeatureCount('land')).toBe(1);

      // === Given: the region endpoints served -> dropdown populated =========
      const regionSelect = page.locator('[data-testid="region-select"]');
      await expect(regionSelect).toBeVisible();
      await expect
        .poll(async () => (await regionSelect.locator('option').count()) >= REGIONS_RESPONSE.regions.length)
        .toBe(true);

      for (const region of REGIONS_RESPONSE.regions) {
        const option = regionSelect.locator(`option[value="${region.id}"]`);
        await expect(option).toHaveAttribute('data-credit-cost', String(region.aviation_credit_cost));
        const optionText = (await option.textContent()) ?? '';
        expect(
          optionText,
          `option for "${region.id}" must show its aviation_credit_cost (${region.aviation_credit_cost}) inline`,
        ).toContain(String(region.aviation_credit_cost));
      }

      // === When: a predefined region is selected from the dropdown ==========
      const activateRequestPromise = page.waitForRequest(
        (req) => req.url().includes('/api/regions/activate') && req.method() === 'POST',
      );
      await regionSelect.selectOption(PREDEFINED_SELECTION.id);
      await activateRequestPromise;

      // === Then: POST /api/regions/activate {region_id} is issued ===========
      await expect.poll(() => recorded.activateRequests.length).toBe(1);
      const predefinedBody = recorded.activateRequests[0] as Record<string, unknown>;
      expect(predefinedBody.region_id).toBe(PREDEFINED_SELECTION.id);
      expect(predefinedBody).not.toHaveProperty('bbox');

      // === ... and its credit cost was shown inline ==========================
      const regionCost = page.locator('[data-testid="region-cost"]');
      await expect(regionCost).toBeVisible();
      await expect(regionCost).toContainText(String(PREDEFINED_SELECTION.aviation_credit_cost));

      // === Custom bbox path: open the coordinate-entry panel =================
      const customToggle = page.locator('[data-testid="custom-bbox-toggle"]');
      await expect(customToggle).toBeVisible();
      await customToggle.click();

      const panel = page.locator('[data-testid="custom-bbox-panel"]');
      await expect(panel).toBeVisible();

      const west = panel.locator('[data-testid="bbox-west"]');
      const south = panel.locator('[data-testid="bbox-south"]');
      const east = panel.locator('[data-testid="bbox-east"]');
      const north = panel.locator('[data-testid="bbox-north"]');
      const labelInput = panel.locator('[data-testid="bbox-label"]');
      const confirmButton = panel.locator('[data-testid="bbox-confirm"]');

      // === When: a custom bbox exceeding a layer's cap is entered ============
      // All four fields filled back-to-back, no artificial delay between
      // them — this is what exercises the ~300ms debounce for real: if the
      // developer fired one estimate call per field change instead of
      // debouncing, the "exactly one estimate request" assertion below fails.
      await west.fill(String(OVER_CAP_BBOX[0]));
      await south.fill(String(OVER_CAP_BBOX[1]));
      await east.fill(String(OVER_CAP_BBOX[2]));
      await north.fill(String(OVER_CAP_BBOX[3]));

      await expect.poll(() => recorded.estimateRequests.length, { timeout: 5_000 }).toBe(1);
      expect(recorded.estimateRequests[0].bbox).toEqual(OVER_CAP_BBOX);

      // Give any (incorrect) extra debounced calls a moment to have fired —
      // proves the four field edits collapsed into exactly one network call.
      await page.waitForTimeout(600);
      expect(
        recorded.estimateRequests.length,
        'four rapid field edits must debounce into exactly one /api/regions/estimate call',
      ).toBe(1);

      // === Then: the layer's cap-naming message is shown ... =================
      const landCapMessage = panel.locator('[data-testid="bbox-cap-message-land"]');
      const marineCapMessage = panel.locator('[data-testid="bbox-cap-message-marine"]');
      await expect(landCapMessage).toBeVisible();
      await expect(landCapMessage).toContainText(OVER_CAP_ESTIMATE_BODY.layer_caps.land.message);
      await expect(marineCapMessage).toBeVisible();
      await expect(marineCapMessage).toContainText(OVER_CAP_ESTIMATE_BODY.layer_caps.marine.message);

      // === ... and Confirm is disabled before activation ======================
      await expect(confirmButton).toBeDisabled();
      // No new activate call fired while Confirm sits disabled (still only
      // the one predefined-selection activation from earlier).
      expect(recorded.activateRequests.length).toBe(1);

      // === When: a valid custom bbox is confirmed =============================
      await west.fill(String(VALID_BBOX[0]));
      await south.fill(String(VALID_BBOX[1]));
      await east.fill(String(VALID_BBOX[2]));
      await north.fill(String(VALID_BBOX[3]));

      await expect.poll(() => recorded.estimateRequests.length, { timeout: 5_000 }).toBe(2);
      expect(recorded.estimateRequests[1].bbox).toEqual(VALID_BBOX);

      // Estimate rendered verbatim from the server response — proves the
      // frontend is not recomputing area/cost client-side.
      const estimateArea = panel.locator('[data-testid="bbox-estimate-area"]');
      const estimateCost = panel.locator('[data-testid="bbox-estimate-cost"]');
      await expect(estimateArea).toContainText(String(VALID_ESTIMATE_BODY.area_sq_deg));
      await expect(estimateCost).toContainText(String(VALID_ESTIMATE_BODY.aviation_credit_cost));

      // Cap messages clear once every layer is ok:true.
      await expect(landCapMessage).toBeHidden();
      await expect(marineCapMessage).toBeHidden();

      await expect(confirmButton).toBeEnabled();

      await labelInput.fill(CUSTOM_LABEL);

      const customActivateRequestPromise = page.waitForRequest(
        (req) => req.url().includes('/api/regions/activate') && req.method() === 'POST',
      );
      await confirmButton.click();
      await customActivateRequestPromise;

      // === Then: POST /api/regions/activate {bbox,label} is issued ===========
      await expect.poll(() => recorded.activateRequests.length).toBe(2);
      const customBody = recorded.activateRequests[1] as Record<string, unknown>;
      expect(customBody.bbox).toEqual(VALID_BBOX);
      expect(customBody.label).toBe(CUSTOM_LABEL);
      expect(customBody).not.toHaveProperty('region_id');

      // === ... and the map clears on region_changed ===========================
      // Pushed for real over the held-open SSE connection (see file-header
      // STUB MECHANISM) — this is not a page reload or REST re-fetch.
      fixture.push('region_changed', { region_id: CUSTOM_ACTIVE_REGION.id, bbox: VALID_BBOX });

      await expect.poll(() => readSourceFeatureCount('air'), { timeout: 5_000 }).toBe(0);
      await expect.poll(() => readSourceFeatureCount('land'), { timeout: 5_000 }).toBe(0);

      // --- Clause: no uncaught console error / page error at any point -------
      // maintainer-adjudicated narrowing (spec discrepancy discussion,  "not the
      // author's to loosen" — this IS the author, and this is a
      // deliberate, approved revision, not a silent weakening): Chromium
      // itself emits a "Failed to load resource: the server responded with a
      // status of ___" console entry for ANY fetch()/XHR that completes with
      // a non-2xx status, regardless of whether page JS handles the response
      // (it does here — `estimateRegion()` checks `res.status === 422` and
      // returns `error.details`, no unhandled rejection). This scenario
      // deliberately exercises the api.md-mandated 422 over-cap estimate
      // response, so that browser-level diagnostic is expected noise, not an
      // application bug — filtered out here while genuine app-level
      // console.error calls are still caught.
      expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
      const appConsoleErrors = consoleErrors.filter(
        (t) => !/Failed to load resource: the server responded with a status of/i.test(t),
      );
      expect(appConsoleErrors, `app console errors: ${JSON.stringify(appConsoleErrors)}`).toHaveLength(0);
    } finally {
      await fixture.shutdown();
    }
  },
);
