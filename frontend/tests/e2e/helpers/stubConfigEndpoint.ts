/**
 * Shared e2e helper — stubs `GET /api/config`, which `main.ts` now fires
 * unconditionally on every page load (marine-integrity, #62):
 * the store's client tick (spec §9) reads per-layer de-emphasis/drop
 * thresholds from this endpoint once at bootstrap, the same way toggle/
 * refresh reads region config from `GET /api/regions` (#59). Specs that
 * don't exercise tick/de-emphasis at all still need this to
 * resolve cleanly — otherwise, with no live FastAPI backend in this e2e run,
 * it leaks through Vite's preview proxy to a connection refused, logs a
 * browser `console.error`, and trips those specs' strict zero-console-error
 * assertions even though the feature each of them actually tests works
 * fine. This mirrors `stubRegionEndpoints.ts`'s role for the #59 ripple and
 * `quietSseStub.ts`'s role for `/api/events`.
 *
 * `marine-integrity.spec.ts` (#62's own acceptance test) does not use the
 * default fixture below unmodified — it overrides `layers.marine`'s
 * `deemphasize_after_s`/`drop_after_s` to small values so the client-tick
 * de-emphasis/drop clauses are observable within a bounded real-time wait,
 * without needing to fake browser time.
 */
import type { Page } from '@playwright/test';

/** Shape mirrors `design/contracts/api.md#get-apiconfig` /
 * `design/contracts/config.md`'s bundled per-layer defaults verbatim. */
export interface ConfigResponse {
  regions: unknown[];
  layers: {
    air: {
      enabled: boolean;
      cadence_s: number;
      cadence_floor_s: number;
      deemphasize_after_s: number;
      stale_multiplier: number;
      custom_bbox_cap_sq_deg: number;
    };
    marine: {
      enabled: boolean;
      cadence_s: number;
      cadence_floor_s: number;
      deemphasize_after_s: number;
      drop_after_s: number;
      stale_multiplier: number;
      custom_bbox_cap_sq_deg: number;
    };
    land: {
      enabled: boolean;
      cadence_s: number;
      cadence_floor_s: number;
      stale_multiplier: number;
      simplify_tolerance_deg: number;
      max_rendered_features: number;
      custom_bbox_cap_sq_deg: number;
    };
  };
  stale_multiplier: number;
  custom_bbox_caps: { air: number; marine: number; land: number };
}

/** Bundled-config defaults per config.md's `[layers.*]` tables. */
export function defaultConfigResponse(): ConfigResponse {
  return {
    regions: [],
    layers: {
      air: {
        enabled: true,
        cadence_s: 600,
        cadence_floor_s: 60,
        deemphasize_after_s: 60,
        stale_multiplier: 2,
        custom_bbox_cap_sq_deg: 100,
      },
      marine: {
        enabled: true,
        cadence_s: 60,
        cadence_floor_s: 60,
        deemphasize_after_s: 1800,
        drop_after_s: 7200,
        stale_multiplier: 2,
        custom_bbox_cap_sq_deg: 40,
      },
      land: {
        enabled: true,
        cadence_s: 86400,
        cadence_floor_s: 3600,
        stale_multiplier: 2,
        simplify_tolerance_deg: 0.0005,
        max_rendered_features: 5000,
        custom_bbox_cap_sq_deg: 40,
      },
    },
    stale_multiplier: 2,
    custom_bbox_caps: { air: 100, marine: 40, land: 40 },
  };
}

/** Registers the `GET /api/config` stub. Call BEFORE `page.goto()`, alongside
 * a spec's other REST/SSE stubs. `overrides` is deep-merged one level into
 * `layers.{air,marine,land}` only (enough for every current caller). */
export async function stubConfigEndpoint(
  page: Page,
  overrides?: {
    layers?: Partial<{
      air: Partial<ConfigResponse['layers']['air']>;
      marine: Partial<ConfigResponse['layers']['marine']>;
      land: Partial<ConfigResponse['layers']['land']>;
    }>;
  },
): Promise<void> {
  const base = defaultConfigResponse();
  const body: ConfigResponse = {
    ...base,
    layers: {
      air: { ...base.layers.air, ...overrides?.layers?.air },
      marine: { ...base.layers.marine, ...overrides?.layers?.marine },
      land: { ...base.layers.land, ...overrides?.layers?.land },
    },
  };
  await page.route('**/api/config', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
