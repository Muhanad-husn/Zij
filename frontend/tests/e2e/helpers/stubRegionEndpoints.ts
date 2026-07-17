/**
 * Shared e2e helper — stubs the two region endpoints `main.ts` now fires
 * unconditionally on every page load (region-selector, #59):
 * `GET /api/regions` (populate the region dropdown) and `GET
 * /api/regions/active` (restore the last-active region). Specs that don't
 * exercise the region selector at all (`map-init.spec.ts`,
 * `layers-refresh.spec.ts`, `badges.spec.ts`) still need these to resolve
 * cleanly — otherwise, with no live FastAPI backend in this e2e run, they leak
 * through Vite's preview proxy to a connection refused, log a browser
 * "Failed to load resource: ... 500" diagnostic, and trip those specs'
 * strict zero-console-error assertions even though the feature each of them
 * actually tests works fine. This mirrors `quietSseStub.ts`'s role for
 * `/api/events`: a harness-only stub for an endpoint the spec doesn't care
 * about, added so an unrelated new on-load call doesn't leak into specs that
 * predate it.
 *
 * `region-selector.spec.ts` (#59's own outer test) already stubs these two
 * endpoints itself, with real fixture data it asserts against — it does not
 * use this helper.
 */
import type { Page } from '@playwright/test';

/** Registers the two on-load region-endpoint stubs on `page`. Call BEFORE
 * `page.goto()`, alongside the spec's other REST/SSE stubs. */
export async function stubRegionEndpoints(page: Page): Promise<void> {
  await page.route('**/api/regions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ regions: [] }),
    });
  });

  await page.route('**/api/regions/active', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ active_region: null }),
    });
  });
}
