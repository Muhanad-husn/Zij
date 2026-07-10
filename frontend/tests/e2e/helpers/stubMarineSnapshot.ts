/**
 * Shared e2e helper — stubs `GET /api/layers/marine/snapshot`, which
 * `main.ts` now fetches unconditionally on every page load
 * (frontend/06-marine-integrity, #62) alongside the pre-existing air/land
 * snapshot fetches. Specs that predate slice 06 (`map-init.spec.ts`,
 * `layers-refresh.spec.ts`) stub only `**\/api/layers/{air,land}/snapshot` —
 * with no live FastAPI backend in this e2e run, the new marine call leaks
 * through Vite's preview proxy to a connection refused, logs a browser
 * `console.error`, and trips those specs' strict zero-console-error
 * assertions even though the behavior each of them actually tests works
 * fine (issue #107). This mirrors `stubConfigEndpoint.ts`'s role for the
 * same slice's `GET /api/config` ripple and `stubRegionEndpoints.ts`'s role
 * for the #59 ripple.
 *
 * `marine-integrity.spec.ts` (#62's own outer test) already stubs this
 * endpoint itself, looped alongside air/land with its own fixtures — it does
 * not use this helper. The other specs (`badges.spec.ts`,
 * `toggles-refresh.spec.ts`, `caveat-panel.spec.ts`) also already loop the
 * marine snapshot stub inline; `region-selector.spec.ts` and
 * `sse-client.spec.ts` tolerate the leak instead (a console-error filter and
 * a pageerror-only check, respectively) — this helper is only needed by the
 * two specs listed above.
 */
import type { Page } from '@playwright/test';

/** Registers the `GET /api/layers/marine/snapshot` stub with a minimal valid
 * empty `LayerSnapshot` (shape per `design/contracts/feature-schema.md`;
 * cadence/stale values mirror the bundled config's `[layers.marine]`
 * defaults per `design/contracts/config.md`). Call BEFORE `page.goto()`,
 * alongside a spec's other REST/SSE stubs. This test asserts nothing about
 * marine rendering — that's `marine-integrity.spec.ts`'s job. */
export async function stubMarineSnapshot(page: Page): Promise<void> {
  await page.route('**/api/layers/marine/snapshot', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        meta: {
          layer: 'marine',
          region_id: 'hormuz',
          status: 'live',
          timestamp_fetched: '2026-07-06T09:12:03Z',
          timestamp_source: '2026-07-06T09:11:58Z',
          cadence_s: 60,
          stale_after_s: 120,
          feature_count: 0,
          retry_after_s: null,
          detail: null,
        },
        features: [],
      }),
    });
  });
}
