/**
 * Acceptance test — caveat panel (issue #61). Encodes the feature's Gherkin
 * verbatim:
 *
 *   Given the app with the caveats endpoint served
 *   When  the Caveats button is opened from a domain's badge
 *   Then  the panel shows that domain's verbatim caveat bullets and its
 *         active-flag counts
 *   And   there is no "don't show again" (or any persistent-dismiss) control
 *         anywhere in the panel
 *   When  the panel is closed and reopened from the badge
 *   Then  it opens again from the badge in every status, including error
 *
 * This test was written before the implementation existed. It initially ran
 * under `test.fail()` (Playwright's expected-to-fail marker, the analog of a
 * pytest xfail — precedent: `badges.spec.ts`, `layers-refresh.spec.ts`,
 * `region-selector.spec.ts`, `toggles-refresh.spec.ts`) from when
 * `caveatPanel.ts` did not exist and the badges' Caveats button was a no-op
 * (`frontend/src/ui/badges.ts`'s click handler was just a `console.debug`),
 * so every clause below failed for real, until the behavior was built. The
 * assertions were confirmed to pass for real via Playwright's own
 * unexpected-pass artifact: under `test.fail()`, an all-clauses-passing run
 * is *reported* as a failure (`✘ … expected to fail but passed`) and
 * Playwright writes an on-failure screenshot but — critically — no
 * `error-context.md` (no assertion ever threw). That screenshot showed the
 * panel OPEN from the AIR badge while AIR was in `error` status, with the AIR
 * domain header, a Close button, both verbatim `AIR-ONLY-CAVEAT` bullets, and
 * the footer's `air_unique_flag_x: 7` count — i.e. the run walked every clause
 * below, including the final "reopen in error status" step, and every
 * assertion held. That is an XPASS, so the `test.fail()` marker was removed;
 * this now runs as a normal `test(...)`.
 *
 * CHROMIUM TEARDOWN CAVEAT (this box): per this repo's durable
 * Playwright-in-sandbox lesson (see `badges.spec.ts` notes), the chromium
 * worker's teardown can hang for minutes *after* the test itself has already
 * passed/failed and printed its result line — a slow or seemingly-hanging run
 * is not evidence this test is broken; read the per-test result line /
 * artifacts, not wall-clock time or exit code alone.
 *
 * REQUIRED TEST SEAMS (the app must expose these; each is independently
 * asserted below):
 *
 *   1. `[data-testid="caveat-panel"]` — ONE panel container, reused across
 *      domains (content swapped, never re-mounted — spec §5). Hidden/absent
 *      until first opened; this test asserts its Playwright-visible element
 *      count never exceeds 1 at any point, even after opening from a second,
 *      different domain's badge (proves reuse, not a fresh instance per open).
 *   2. `[data-testid="caveat-panel-domain"]` (inside the panel) — text
 *      containing the currently-shown domain's name (case-insensitive
 *      substring match, e.g. "marine"/"MARINE" both satisfy it), updated on
 *      every open/swap.
 *   3. `[data-testid="caveat-bullets"]` (inside the panel) — a container
 *      whose text content includes each of that domain's `caveats` array
 *      entries **verbatim** (exact substring, not a paraphrase) from
 *      `GET /api/layers/{domain}/caveats`.
 *   4. `[data-testid="caveat-panel-footer"]` (inside the panel) — text
 *      content that includes, for each key in the response's `active_flags`
 *      object, both the flag's name and its numeric count (e.g. the string
 *      "spoof_suspect_on_land" together with "3" appearing somewhere in the
 *      footer). Exact formatting/layout is unconstrained; only the presence
 *      of name+count is asserted here.
 *   5. `[data-testid="caveat-panel-close"]` (inside the panel) — a close
 *      control; clicking it hides the panel (session-only — see seam 6).
 *   6. **No persistent-dismiss affordance anywhere in the panel.** This test
 *      asserts, within the panel container: (a) no `input[type="checkbox"]`
 *      exists, and (b) no element's accessible text matches
 *      /don't show again/i or /dismiss forever/i, and (c) no element carries
 *      a `data-testid` matching /dont-show/i or /dismiss-forever/i. Closing
 *      is session-only — the badge's Caveats button is the only way back, in
 *      every status.
 *   7. The badge's existing `[data-testid="badge-{domain}"]
 *      [data-testid="caveats-button"]` (from `badges.ts`)
 *      opens/re-opens this panel and stays enabled in every `LayerStatus`,
 *      including `error` (already independently locked by `badges.spec.ts`;
 *      this test additionally proves it actually opens the panel, not just
 *      that the button exists/enabled).
 *
 * STUB MECHANISM: no live FastAPI backend in this e2e run
 * (`playwright.config.ts` serves the built `vite preview` bundle on :4173).
 * As established by `badges.spec.ts` / `sse-client.spec.ts`, `/api/events` is
 * answered by a REAL held-open Node `http` server (an atomic
 * `page.route().fulfill()` body cannot model a live multi-event stream); the
 * browser's request is redirected to it via `route.continue({ url })`. The
 * three per-domain `GET /api/layers/{domain}/caveats` calls, by contrast, are
 * ordinary request/response GETs — these are stubbed with plain
 * `page.route().fulfill()`, one distinct fixture body per domain (api.md's
 * `{domain, caveats, active_flags}` shape), so a domain swap is provably not
 * a coincidence of shared fixture text.
 *
 * LATER-FEATURE FALLOUT (region-selector, #59): `main.ts` unconditionally
 * fetches `GET /api/regions` / `GET /api/regions/active` on load;
 * `stubRegionEndpoints` answers both quietly, as in every sibling spec since
 * #59. `stubRestFallback` (mirroring `badges.spec.ts` /
 * `toggles-refresh.spec.ts`) answers the per-domain
 * `GET /api/layers/{domain}/snapshot` cold-start/refresh fallback quietly —
 * this test's assertions are driven entirely by the SSE fixture pushes and
 * the caveats stubs below, never by these fallback bodies.
 *
 * LATER-FEATURE FALLOUT (marine-integrity, issue #62): the app now
 * unconditionally fetches `GET /api/config` on load (the client tick reads
 * de-emphasis/drop thresholds from it, spec §9). This test has no live
 * FastAPI backend, so an unstubbed call would leak through Vite's preview
 * proxy the same way the region note above already documents.
 * `tests/e2e/helpers/stubConfigEndpoint.ts` answers it quietly; this test
 * asserts nothing about tick/de-emphasis behavior (that's
 * `marine-integrity.spec.ts`'s job).
 */

import { test, expect, type Page } from '@playwright/test';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';
import { stubRegionEndpoints } from './helpers/stubRegionEndpoints';
import { stubConfigEndpoint } from './helpers/stubConfigEndpoint';

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

/** Defensive REST fallback stubs (mirrors `badges.spec.ts`/`toggles-refresh.spec.ts`). */
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
  await page.route('**/api/refresh', async (route) => {
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ queued: [] }) });
  });
}

// --- Caveats endpoint fixtures ---------------------------------------------
// Distinct, verbatim per-domain bullet text + active_flags so a domain swap
// is provable (no shared substrings between domains' bullets). Marine's
// fixture mirrors api.md's own worked example verbatim.

const CAVEATS_FIXTURE: Record<'air' | 'marine' | 'land', { caveats: string[]; active_flags: Record<string, number> }> = {
  air: {
    caveats: [
      'AIR-ONLY-CAVEAT: OpenSky coverage over this region depends on volunteer ADS-B receiver density.',
      'AIR-ONLY-CAVEAT: military and state aircraft routinely disable transponders and will not appear.',
    ],
    active_flags: { air_unique_flag_x: 7 },
  },
  marine: {
    caveats: [
      'Terrestrial AIS coverage in the Persian Gulf is receiver-dependent and uneven.',
      'Dark-fleet vessels routinely disable AIS and will not appear.',
      'GPS jamming produces on-land and circular ghost tracks.',
    ],
    active_flags: { spoof_suspect_on_land: 3, implausible_kinematics: 1 },
  },
  land: {
    caveats: ['LAND-ONLY-CAVEAT: OSM road/rail/POI tagging completeness varies by area and editor activity.'],
    active_flags: {},
  },
};

async function stubCaveats(page: Page): Promise<void> {
  for (const domain of ['air', 'marine', 'land'] as const) {
    await page.route(`**/api/layers/${domain}/caveats`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ domain, ...CAVEATS_FIXTURE[domain] }),
      });
    });
  }
}

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
    timestamp_fetched: '2026-07-10T10:05:03Z',
    timestamp_source: '2026-07-10T10:04:58Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 2,
    retry_after_s: null,
    detail: null,
    ...overrides,
  };
}

/** Asserts NO persistent-dismiss affordance exists anywhere within `panel`
 * (REQUIRED TEST SEAM #6). Checks (a) no checkbox input, (b) no visible text
 * matching common "don't show again" phrasing, (c) no testid naming such a
 * control. */
async function expectNoPersistentDismiss(panel: ReturnType<Page['locator']>): Promise<void> {
  await expect(panel.locator('input[type="checkbox"]')).toHaveCount(0);
  await expect(panel.getByText(/don'?t show again/i)).toHaveCount(0);
  await expect(panel.getByText(/dismiss forever/i)).toHaveCount(0);
  await expect(panel.locator('[data-testid*="dont-show" i]')).toHaveCount(0);
  await expect(panel.locator('[data-testid*="dismiss-forever" i]')).toHaveCount(0);
}

test(
  'the caveat panel opens from any badge, shows that domain\'s verbatim bullets + active-flag counts, ' +
    'has no persistent-dismiss control, reuses one instance across domain swaps, and reopens from the ' +
    'badge in every status including error',
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
      await stubConfigEndpoint(page);
      await stubCaveats(page);

      await page.goto('/');
      await fixture.connected;

      // === Given: the app with a badge per domain, caveats endpoint served ===
      fixture.push('snapshot', { meta: meta('air'), features: [] });
      fixture.push('snapshot', { meta: meta('marine'), features: [] });
      fixture.push('snapshot', { meta: meta('land'), features: [] });

      const airBadge = page.locator('[data-testid="badge-air"]');
      const marineBadge = page.locator('[data-testid="badge-marine"]');
      await expect(airBadge).toBeVisible();
      await expect(marineBadge).toBeVisible();

      const panel = page.locator('[data-testid="caveat-panel"]');

      // Before any open: at most one instance exists, and it is not visible.
      await expect(panel).toBeHidden();

      // === When: Caveats is opened from air's badge ===
      await airBadge.locator('[data-testid="caveats-button"]').click();

      // === Then: the panel shows AIR's verbatim bullets + active-flag counts ===
      await expect(panel).toBeVisible();
      await expect(panel).toHaveCount(1);
      await expect(panel.locator('[data-testid="caveat-panel-domain"]')).toContainText(/air/i);

      const airBullets = panel.locator('[data-testid="caveat-bullets"]');
      for (const bullet of CAVEATS_FIXTURE.air.caveats) {
        await expect(airBullets).toContainText(bullet);
      }
      // Domain-swap proof, part 1: marine's distinct bullet text is NOT present.
      for (const bullet of CAVEATS_FIXTURE.marine.caveats) {
        await expect(airBullets).not.toContainText(bullet);
      }

      const airFooter = panel.locator('[data-testid="caveat-panel-footer"]');
      for (const [flag, count] of Object.entries(CAVEATS_FIXTURE.air.active_flags)) {
        await expect(airFooter).toContainText(flag);
        await expect(airFooter).toContainText(String(count));
      }

      // === And: no persistent-dismiss control anywhere in the panel ===
      await expectNoPersistentDismiss(panel);

      // === When: Caveats is opened from a DIFFERENT domain's badge (marine) ===
      await marineBadge.locator('[data-testid="caveats-button"]').click();

      // === Then: the SAME panel instance now shows MARINE's content (swap, not remount) ===
      await expect(panel).toHaveCount(1); // still exactly one panel element, never two
      await expect(panel).toBeVisible();
      await expect(panel.locator('[data-testid="caveat-panel-domain"]')).toContainText(/marine/i);

      const marineBullets = panel.locator('[data-testid="caveat-bullets"]');
      for (const bullet of CAVEATS_FIXTURE.marine.caveats) {
        await expect(marineBullets).toContainText(bullet);
      }
      // Domain-swap proof, part 2: air's distinct bullet text is gone.
      for (const bullet of CAVEATS_FIXTURE.air.caveats) {
        await expect(marineBullets).not.toContainText(bullet);
      }

      const marineFooter = panel.locator('[data-testid="caveat-panel-footer"]');
      for (const [flag, count] of Object.entries(CAVEATS_FIXTURE.marine.active_flags)) {
        await expect(marineFooter).toContainText(flag);
        await expect(marineFooter).toContainText(String(count));
      }

      await expectNoPersistentDismiss(panel);

      // === When: the panel is closed (session-only — no persistent state) ===
      await panel.locator('[data-testid="caveat-panel-close"]').click();
      await expect(panel).toBeHidden();

      // === Then: it opens again from the badge — even in `error` status ===
      fixture.push(
        'layer_status',
        meta('air', {
          status: 'error',
          timestamp_fetched: '2026-07-10T11:10:00Z',
          timestamp_source: null,
          retry_after_s: null,
          detail: 'upstream 503',
        }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'error');

      const airCaveatsButtonDuringError = airBadge.locator('[data-testid="caveats-button"]');
      await expect(airCaveatsButtonDuringError).toBeVisible();
      await expect(airCaveatsButtonDuringError).toBeEnabled(); // never disabled, incl. error (spec §4/§5)
      await airCaveatsButtonDuringError.click();

      await expect(panel).toBeVisible();
      await expect(panel).toHaveCount(1); // reopened the SAME instance, not a second one
      await expect(panel.locator('[data-testid="caveat-panel-domain"]')).toContainText(/air/i);
      for (const bullet of CAVEATS_FIXTURE.air.caveats) {
        await expect(panel.locator('[data-testid="caveat-bullets"]')).toContainText(bullet);
      }

      // --- Clause: no uncaught console error / page error at any point -------
      expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
      expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
    } finally {
      await fixture.shutdown();
    }
  },
);
