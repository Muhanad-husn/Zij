/**
 * Inner unit tests — plan/frontend-map/02-layers-refresh.md "Inner loop" unit
 * #5 (refresh action), against `src/api/client.ts` as actually built.
 *
 * `fetch` is replaced with a `vi.fn()` stand-in — hermetic, no real network,
 * no real map. Verifies the exact request (method + URL) and response
 * handling `refreshAll()`/`fetchSnapshot()` perform.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  activateRegion,
  estimateRegion,
  fetchActiveRegion,
  fetchRegions,
  fetchSnapshot,
  refreshAll,
  refreshLayer,
  toggleLayer,
} from '../../src/api/client';
import type { EstimateResult } from '../../src/state/types';

describe('refreshAll — plan unit #5: posts to /api/refresh', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues a POST request to a URL ending in /api/refresh', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 202 });

    await refreshAll();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/refresh$/);
    expect(options?.method).toBe('POST');
  });

  it('throws when the backend responds with a non-ok status', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 });

    await expect(refreshAll()).rejects.toThrow(/503/);
  });
});

describe('fetchSnapshot — plan unit #5: GETs /api/layers/{domain}/snapshot', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests the air snapshot endpoint and returns the parsed JSON body', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const body = { meta: { layer: 'air' }, features: [] };
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => body });

    const result = await fetchSnapshot('air');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toMatch(/\/api\/layers\/air\/snapshot$/);
    expect(result).toEqual(body);
  });

  it('requests the land snapshot endpoint for the land domain', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ meta: {}, features: [] }) });

    await fetchSnapshot('land');

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toMatch(/\/api\/layers\/land\/snapshot$/);
  });

  it('throws when the backend responds with a non-ok status', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500 });

    await expect(fetchSnapshot('air')).rejects.toThrow(/500/);
  });
});

/**
 * Inner unit tests — plan/frontend/03-region-selector.md "Inner loop" (region
 * endpoints), against `src/api/client.ts` as actually built. The subtle
 * correctness point (per the author's follow-up-pass brief) is
 * `estimateRegion`'s split handling: a `200` resolves with the body verbatim,
 * a `422` is NOT a transport error — api.md models an over-cap bbox as a
 * `422` whose body carries the same `EstimateResult` shape under
 * `error.details`, and the client must unwrap that so the caller's normal
 * render path (not a catch block) handles the over-cap case. Only a genuinely
 * unexpected status should throw.
 */
describe('fetchRegions — GET /api/regions returns the regions list verbatim', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests /api/regions and returns the parsed body', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const body = { regions: [{ id: 'hormuz', label: 'Strait of Hormuz', bbox: [1, 2, 3, 4], aviation_credit_cost: 1, kind: 'predefined' }] };
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => body });

    const result = await fetchRegions();

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toMatch(/\/api\/regions$/);
    expect(result).toEqual(body);
  });

  it('throws when the backend responds with a non-ok status', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500 });

    await expect(fetchRegions()).rejects.toThrow(/500/);
  });
});

describe('fetchActiveRegion — GET /api/regions/active', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns { active_region: null } verbatim when nothing is active', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ active_region: null }) });

    const result = await fetchActiveRegion();

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toMatch(/\/api\/regions\/active$/);
    expect(result).toEqual({ active_region: null });
  });
});

describe('activateRegion — POST /api/regions/activate: predefined vs custom payload shapes', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends exactly {region_id} for a predefined selection — no bbox/label keys', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ active_region: { id: 'hormuz', label: 'Strait of Hormuz', bbox: [1, 2, 3, 4], aviation_credit_cost: 1, kind: 'predefined' } }),
    });

    await activateRegion({ region_id: 'hormuz' });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/regions\/activate$/);
    expect(options.method).toBe('POST');
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).toEqual({ region_id: 'hormuz' });
    expect(body).not.toHaveProperty('bbox');
    expect(body).not.toHaveProperty('label');
  });

  it('sends exactly {bbox,label} for a custom bbox — no region_id key', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ active_region: { id: 'custom:ab12', label: 'My Box', bbox: [52, 26, 56, 29], aviation_credit_cost: 1, kind: 'custom' } }),
    });

    await activateRegion({ bbox: [52, 26, 56, 29], label: 'My Box' });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).toEqual({ bbox: [52, 26, 56, 29], label: 'My Box' });
    expect(body).not.toHaveProperty('region_id');
  });
});

describe('estimateRegion — POST /api/regions/estimate: 200 vs 422 branch', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const VALID_ESTIMATE: EstimateResult = {
    valid: true,
    bbox: [52, 26, 56, 29],
    area_sq_deg: 12.0,
    aviation_credit_cost: 1,
    layer_caps: {
      air: { ok: true, cap_sq_deg: 100, cost_credits: 1 },
      land: { ok: true, cap_sq_deg: 40 },
      marine: { ok: true, cap_sq_deg: 40 },
    },
  };

  const OVER_CAP_ESTIMATE: EstimateResult = {
    valid: false,
    bbox: [40, 20, 55, 32],
    area_sq_deg: 180.0,
    aviation_credit_cost: 3,
    layer_caps: {
      air: { ok: true, cap_sq_deg: 100, cost_credits: 3 },
      land: { ok: false, cap_sq_deg: 40, message: 'Land bbox 180.0 sq° exceeds the 40 sq° cap.' },
      marine: { ok: false, cap_sq_deg: 40, message: 'Marine bbox 180.0 sq° exceeds the 40 sq° cap.' },
    },
  };

  it('POSTs {bbox} and resolves with the 200 body verbatim (no client-side re-derivation)', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => VALID_ESTIMATE });

    const result = await estimateRegion([52, 26, 56, 29]);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/regions\/estimate$/);
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body as string)).toEqual({ bbox: [52, 26, 56, 29] });
    expect(result).toEqual(VALID_ESTIMATE);
  });

  it('on a 422, unwraps error.details into the SAME EstimateResult shape instead of throwing', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        error: {
          code: 'validation_error',
          message: 'Custom bbox exceeds one or more layer caps.',
          retry_after_s: null,
          details: OVER_CAP_ESTIMATE,
        },
      }),
    });

    const result = await estimateRegion([40, 20, 55, 32]);

    expect(result).toEqual(OVER_CAP_ESTIMATE);
    expect(result.layer_caps.land.ok).toBe(false);
    expect(result.layer_caps.land.message).toBe('Land bbox 180.0 sq° exceeds the 40 sq° cap.');
  });

  it('throws (does not silently resolve) on a genuinely unexpected status, e.g. 500', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) });

    await expect(estimateRegion([1, 2, 3, 4])).rejects.toThrow(/500/);
  });
});

/**
 * Inner unit tests — plan/frontend/04-toggles-refresh.md "Inner loop" units
 * #1/#2/#4, against `src/api/client.ts`'s `toggleLayer`/`refreshLayer` as
 * actually built.
 */
describe('toggleLayer — plan unit #1: POSTs /api/layers/{domain}/toggle {enabled}', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues a POST to a URL ending in /api/layers/land/toggle with body {enabled:false}', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ layer: 'land', enabled: false }),
    });

    const result = await toggleLayer('land', false);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/layers\/land\/toggle$/);
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body as string)).toEqual({ enabled: false });
    expect(result).toEqual({ layer: 'land', enabled: false });
  });

  it('sends {enabled:true} to re-enable a layer', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ layer: 'air', enabled: true }) });

    await toggleLayer('air', true);

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(options.body as string)).toEqual({ enabled: true });
  });

  it('throws when the backend responds with a non-ok status', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500 });

    await expect(toggleLayer('land', false)).rejects.toThrow(/500/);
  });
});

describe('refreshLayer — plan unit #2/#4: fire-and-forget POST /api/layers/{domain}/refresh', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues a POST to a URL ending in /api/layers/air/refresh, no body required', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 202 });

    await refreshLayer('air');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/layers\/air\/refresh$/);
    expect(options.method).toBe('POST');
  });

  it('resolves (does not return the response body) — the resulting status rides SSE, never a return value polled here', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ layer: 'air', queued: true }) });

    const result = await refreshLayer('air');

    expect(result).toBeUndefined();
  });

  it('throws when the backend responds with a non-ok status', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 });

    await expect(refreshLayer('land')).rejects.toThrow(/503/);
  });
});
