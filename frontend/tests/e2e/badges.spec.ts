/**
 *  locked outer acceptance test — frontend/02-badges (issue #58).
 * Encodes `plans/frontend/02-badges.md`'s Gherkin verbatim:
 *
 *   Given the app with a mounted badge per domain (air, marine, land)
 *   When  a layer transitions through each of the seven LayerStatus values
 *   Then  the badge shows that status's distinct color and label per §4
 *   And   both timestamps render as HH:MM:SS UTC (never local time)
 *   And   a rate-limited badge counts down from retry_after_s
 *   And   the Caveats button is present and enabled in every status,
 *         including error
 *
 * `test.fail()` was this web slice's analog to a strict pytest xfail (
 * — see `layers-refresh.spec.ts` for the precedent this repo standardized
 * on) from the slice's red commit until the developer greened every clause
 * below. the author confirmed each assertion passes for real (a plain
 * `test()` run: `✓ ... (3.0s)`, `1 passed`) and removed the `test.fail()`
 * marker in this final pass, so this now runs as a normal `test(...)`.
 *
 * SCOPE NOTE (marine badge, no marine map layer): `design/specs/frontend.md`
 * has no marine map-layer builder yet (deferred to step per the plan's
 * "Out of scope" list). This test mounts/asserts the marine BADGE only (via
 * `snapshot:marine` / `status:marine` store events) — it never touches
 * `window.__zijMap.getSource('marine')`. `main.ts` mounts a third
 * (`marine`) badge alongside air/land as of this slice.
 *
 * WHICH DOMAIN CARRIES WHICH STATUS: the Gherkin says "a layer transitions
 * through each of the seven ... values," not "every layer through every
 * value." `reconnecting` is marine-stream-only (feature-schema.md
 * LayerStatus note), so this test drives {live, reconnecting} through the
 * marine badge and the remaining six {live, stale, loading, rate-limited,
 * error, cached-fallback} through the air badge; the land badge only proves
 * "one badge per domain, always visible" (mounted, showing its initial
 * `live` snapshot). Together every one of the seven wire values is exercised
 * for real.
 *
 * STUB MECHANISM: no live FastAPI backend in this e2e run
 * (`playwright.config.ts` serves the built `vite preview` bundle on :4173).
 * As established by `sse-client.spec.ts` (see its file-header comment for
 * the full rationale — `page.route().fulfill()` cannot hold a stream open),
 * this test runs a REAL streaming Node `http` server on an ephemeral
 * loopback port and redirects the browser's `/api/events` request to it via
 * `route.continue({ url })`. Unlike `sse-client.spec.ts`, this test never
 * drops the connection — it holds ONE connection open for the whole test and
 * pushes a sequence of `snapshot` / `layer_status` SSE blocks down it as the
 * test drives each status transition, mirroring exactly how a real backend
 * would push scheduler-driven status changes (spec §3/§4: badges "update
 * imperatively on `status:{domain}` / `snapshot:{domain}` store events").
 *
 * RECONCILIATION (slice frontend/03-region-selector, issue #59): the app now
 * unconditionally fetches `GET /api/regions` and `GET /api/regions/active`
 * on load (region dropdown population + last-region restore). This test has
 * no live FastAPI backend, so those unstubbed calls would leak through
 * Vite's preview proxy to a connection refused, logging a browser
 * `console.error` that would trip this test's "zero console errors" clause
 * even though the badge behavior this test actually exercises works fine.
 * `tests/e2e/helpers/stubRegionEndpoints.ts` is used below to answer both
 * quietly; this test asserts nothing about regions (that's
 * `region-selector.spec.ts`'s job).
 *
 * RECONCILIATION (slice frontend/06-marine-integrity, issue #62): the app
 * now unconditionally fetches `GET /api/config` on load (the client tick
 * reads de-emphasis/drop thresholds from it, spec §9). This test has no live
 * FastAPI backend, so an unstubbed call would leak through Vite's preview
 * proxy the same way the reconciliation above already documents.
 * `tests/e2e/helpers/stubConfigEndpoint.ts` answers it quietly; this test
 * asserts nothing about tick/de-emphasis behavior (that's
 * `marine-integrity.spec.ts`'s job).
 *
 * REQUIRED TEST SEAMS (developer must expose these — not the author's
 * to relax; each is independently asserted below):
 *
 *   1. `[data-testid="badge-air"]`, `[data-testid="badge-marine"]`,
 *      `[data-testid="badge-land"]` — one badge container per domain,
 *      always mounted/visible regardless of status.
 *   2. Each badge container carries a `data-status` attribute holding the
 *      CURRENT raw wire `LayerStatus` value verbatim (e.g.
 *      `data-status="rate-limited"`, `data-status="cached-fallback"`),
 *      updated on every `status:{domain}` / `snapshot:{domain}` event.
 *   3. Within each badge: `[data-testid="status-indicator"]` — an element
 *      whose *computed* `background-color` resolves to the status's
 *      `--status-*` token color (tokens.css already defines all seven;
 *      `reconnecting` intentionally resolves to the same color as `loading`,
 *      since it is grouped with the loading family per the
 *      feature-schema.md LayerStatus note). This test reads the computed
 *      style, not any specific CSS mechanism, so a `[data-status="..."]`
 *      stylesheet selector or an inline style both satisfy it.
 *   4. `[data-testid="status-label"]` — the label text, matching §4's
 *      wording: `"Live"`, `"Loading…"`, `"Reconnecting…"`, `"Error"`,
 *      `"Rate-limited · retry in {n}s"` (with `{n}` a live client-side
 *      countdown seeded from `retry_after_s`), and `"Stale · {age}"` /
 *      `"Cached · {age}"` (this test only asserts the fixed `"Stale · "` /
 *      `"Cached · "` prefix — the exact `{age}` rendering is the
 *      developer's/inner-unit-tests' choice, not locked here).
 *   5. `[data-testid="status-detail"]` — present on every badge; its
 *      `data-detail` attribute equals `meta.detail` verbatim whenever
 *      `status === "error"` (spec §4: "`detail` shown on hover/expand" —
 *      this test asserts the underlying data is present and reachable, not
 *      a specific hover/expand interaction).
 *   6. `[data-testid="caveats-button"]` — a `<button>` (or equivalent),
 *      always rendered and never `disabled`, regardless of status
 *      (including `error` — spec §4: "always present and always enabled").
 *   7. Existing (unchanged) seams reused verbatim from
 *      `layers-refresh.spec.ts` / `sse-client.spec.ts`:
 *      `[data-testid="freshness-fetched"]`, `[data-testid="freshness-source"]`
 *      (each rendering exactly `HH:MM:SS UTC`, NFR6), and
 *      `[data-testid="feature-count"]`.
 *
 * This test is not the author's to loosen and not the developer's to
 * touch. The `test.fail()` marker was removed only once every assertion
 * below passed for real, in the author's final follow-up pass.
 */

import { test, expect, type Page } from '@playwright/test';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';
import { stubRegionEndpoints } from './helpers/stubRegionEndpoints';
import { stubConfigEndpoint } from './helpers/stubConfigEndpoint';

// --- Status -> token color (tokens.css, verbatim) -------------------------
// Duplicated here (not imported) so this test proves the ACTUAL rendered
// color, independent of whichever mechanism (CSS selector, inline style)
// the developer wires up to read these same tokens.

const STATUS_HEX = {
  live: '#4CAF7D',
  stale: '#E8C468',
  loading: '#6FA8DC',
  'rate-limited': '#E08A3C',
  error: '#D9534F',
  'cached-fallback': '#9B8AA6',
  reconnecting: '#6FA8DC', // var(--status-loading) — grouped w/ loading family
} as const;

function hexToRgbTuple(hex: string): [number, number, number] {
  const clean = hex.replace('#', '');
  return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
}

/** Parses a browser-computed `background-color` (`rgb(r, g, b)` /
 * `rgba(r, g, b, a)`) into an `[r, g, b]` tuple — mirrors the
 * `normalizeToRgb` helper used by `layers-refresh.spec.ts` / `map-init.spec.ts`. */
function normalizeToRgb(value: unknown): [number, number, number] {
  const s = String(value).trim();
  const rgbaMatch = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(s);
  if (rgbaMatch) {
    return [Number(rgbaMatch[1]), Number(rgbaMatch[2]), Number(rgbaMatch[3])];
  }
  const hexMatch = /^#([0-9a-fA-F]{6})$/.exec(s);
  if (hexMatch) {
    return hexToRgbTuple(`#${hexMatch[1]}`);
  }
  throw new Error(`Unrecognized computed color format: ${s}`);
}

async function expectIndicatorColor(page: Page, domain: string, status: keyof typeof STATUS_HEX): Promise<void> {
  const rgb = await page
    .locator(`[data-testid="badge-${domain}"] [data-testid="status-indicator"]`)
    .evaluate((el) => getComputedStyle(el as HTMLElement).backgroundColor);
  expect(
    normalizeToRgb(rgb),
    `badge-${domain} status-indicator color for "${status}" (got ${rgb})`,
  ).toEqual(hexToRgbTuple(STATUS_HEX[status]));
}

// --- SSE fixture server ----------------------------------------------------
// A real, held-open Node `http` server (no `page.route().fulfill()` — see
// `sse-client.spec.ts`'s file-header comment for why an atomic fulfilled
// body can't model a live, multi-event stream). One connection is accepted
// and held open for the whole test; `push()` writes additional
// `snapshot`/`layer_status` SSE blocks down it on demand, letting the test
// drive each status transition as if a real backend were pushing them.

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
      // Should not happen in this test (no drop/reconnect scenario), but
      // answer defensively rather than hang a stray second connection.
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

/** Defensive REST fallback stubs, mirroring the RECONCILIATION precedent in
 * `map-init.spec.ts` / `sse-client.spec.ts` — this test does not assert on
 * these endpoints being called, only keeps an incidental REST fetch (air/land
 * on load, or a marine fetch the developer may add) from 404ing noisily. */
async function stubRestFallback(page: Page) {
  const empty = (layer: 'air' | 'marine' | 'land') => ({
    meta: {
      layer,
      region_id: 'hormuz',
      status: 'live',
      timestamp_fetched: '2026-07-09T00:00:00Z',
      timestamp_source: '2026-07-09T00:00:00Z',
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

// --- Fixtures --------------------------------------------------------------
// meta-only (LayerSnapshotMeta) blocks per feature-schema.md; `features: []`
// for `snapshot` events since this test asserts badge DOM only, never map
// rendering (that is `layers-refresh.spec.ts`'s job).

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
    timestamp_fetched: '2026-07-09T10:05:03Z',
    timestamp_source: '2026-07-09T10:04:58Z',
    cadence_s: 600,
    stale_after_s: 1200,
    feature_count: 2,
    retry_after_s: null,
    detail: null,
    ...overrides,
  };
}

test(
  'per-domain badges render every LayerStatus with distinct color+label, UTC timestamps, a rate-limited countdown, and an always-enabled Caveats button',
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

      await page.goto('/');
      await fixture.connected;

      // === Given: a badge per domain (air, marine, land), always visible ===
      const airBadge = page.locator('[data-testid="badge-air"]');
      const marineBadge = page.locator('[data-testid="badge-marine"]');
      const landBadge = page.locator('[data-testid="badge-land"]');

      // Initial `live` snapshot for all three domains.
      fixture.push('snapshot', { meta: meta('air', { feature_count: 2 }), features: [] });
      fixture.push('snapshot', { meta: meta('marine', { feature_count: 1 }), features: [] });
      fixture.push('snapshot', { meta: meta('land', { feature_count: 3 }), features: [] });

      await expect(airBadge).toBeVisible();
      await expect(marineBadge).toBeVisible();
      await expect(landBadge).toBeVisible();

      for (const [locator, domain, count] of [
        [airBadge, 'air', '2'],
        [marineBadge, 'marine', '1'],
        [landBadge, 'land', '3'],
      ] as const) {
        expect(await locator.getAttribute('data-status')).toBe('live');
        await expect(locator.locator('[data-testid="status-label"]')).toHaveText('Live');
        // NFR6: both timestamps UTC, labeled, never local time.
        await expect(locator.locator('[data-testid="freshness-fetched"]')).toHaveText('10:05:03 UTC');
        await expect(locator.locator('[data-testid="freshness-source"]')).toHaveText('10:04:58 UTC');
        await expect(locator.locator('[data-testid="feature-count"]')).toContainText(count);
        await expectIndicatorColor(page, domain, 'live');

        // Caveats button present + enabled in EVERY status, incl. this one.
        const caveats = locator.locator('[data-testid="caveats-button"]');
        await expect(caveats).toBeVisible();
        await expect(caveats).toBeEnabled();
      }

      // === air badge sweeps: stale, loading, rate-limited, error, cached ===

      // -- stale --
      fixture.push(
        'layer_status',
        meta('air', {
          status: 'stale',
          timestamp_fetched: '2026-07-09T11:00:00Z',
          timestamp_source: '2026-07-09T09:00:00Z',
          feature_count: 2,
        }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'stale');
      await expect(airBadge.locator('[data-testid="status-label"]')).toContainText('Stale · ');
      await expectIndicatorColor(page, 'air', 'stale');
      await expect(airBadge.locator('[data-testid="caveats-button"]')).toBeEnabled();

      // -- loading --
      fixture.push(
        'layer_status',
        meta('air', { status: 'loading', timestamp_fetched: null, timestamp_source: null, feature_count: 2 }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'loading');
      await expect(airBadge.locator('[data-testid="status-label"]')).toHaveText('Loading…');
      await expectIndicatorColor(page, 'air', 'loading');
      await expect(airBadge.locator('[data-testid="caveats-button"]')).toBeEnabled();

      // -- rate-limited (+ client-side countdown from retry_after_s) --
      fixture.push(
        'layer_status',
        meta('air', {
          status: 'rate-limited',
          timestamp_fetched: '2026-07-09T11:05:00Z',
          timestamp_source: '2026-07-09T11:00:00Z',
          retry_after_s: 8,
          feature_count: 2,
        }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'rate-limited');
      const rateLabel = airBadge.locator('[data-testid="status-label"]');
      await expect(rateLabel).toHaveText('Rate-limited · retry in 8s');
      await expectIndicatorColor(page, 'air', 'rate-limited');
      await expect(airBadge.locator('[data-testid="caveats-button"]')).toBeEnabled();

      await expect
        .poll(
          async () => {
            const text = (await rateLabel.textContent()) ?? '';
            const match = /retry in (\d+)s/.exec(text);
            return match ? Number(match[1]) : null;
          },
          { timeout: 10_000, message: 'rate-limited badge must count down client-side from retry_after_s' },
        )
        .toBeLessThan(8);

      // -- error (Caveats stays enabled — the whole point of the clause) --
      fixture.push(
        'layer_status',
        meta('air', {
          status: 'error',
          timestamp_fetched: '2026-07-09T11:10:00Z',
          timestamp_source: null,
          feature_count: 2,
          retry_after_s: null,
          detail: 'upstream 503',
        }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'error');
      await expect(airBadge.locator('[data-testid="status-label"]')).toHaveText('Error');
      await expectIndicatorColor(page, 'air', 'error');
      await expect(airBadge.locator('[data-testid="status-detail"]')).toHaveAttribute('data-detail', 'upstream 503');
      const caveatsDuringError = airBadge.locator('[data-testid="caveats-button"]');
      await expect(caveatsDuringError).toBeVisible();
      await expect(caveatsDuringError).toBeEnabled();

      // -- cached-fallback --
      fixture.push(
        'layer_status',
        meta('air', {
          status: 'cached-fallback',
          timestamp_fetched: '2026-07-09T05:00:00Z',
          timestamp_source: '2026-07-09T04:55:00Z',
          feature_count: 2,
          retry_after_s: null,
          detail: null,
        }),
      );
      await expect(airBadge).toHaveAttribute('data-status', 'cached-fallback');
      await expect(airBadge.locator('[data-testid="status-label"]')).toContainText('Cached · ');
      await expectIndicatorColor(page, 'air', 'cached-fallback');
      await expect(airBadge.locator('[data-testid="caveats-button"]')).toBeEnabled();

      // === marine badge: reconnecting (marine-stream-only, grouped w/ loading) ===
      fixture.push(
        'layer_status',
        meta('marine', {
          status: 'reconnecting',
          timestamp_fetched: '2026-07-09T10:05:03Z',
          timestamp_source: '2026-07-09T10:04:58Z',
          feature_count: 1,
          detail: 'websocket dropped',
        }),
      );
      await expect(marineBadge).toHaveAttribute('data-status', 'reconnecting');
      await expect(marineBadge.locator('[data-testid="status-label"]')).toHaveText('Reconnecting…');
      // Grouped with the loading family — same rendered color as `loading`.
      await expectIndicatorColor(page, 'marine', 'reconnecting');
      await expect(marineBadge.locator('[data-testid="caveats-button"]')).toBeEnabled();

      // --- Clause: no uncaught console error / page error at any point -------
      expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
      expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
    } finally {
      await fixture.shutdown();
    }
  },
);
