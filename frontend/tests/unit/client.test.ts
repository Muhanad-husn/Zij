/**
 * Inner unit tests — plan/frontend-map/02-layers-refresh.md "Inner loop" unit
 * #5 (refresh action), against `src/api/client.ts` as actually built.
 *
 * `fetch` is replaced with a `vi.fn()` stand-in — hermetic, no real network,
 * no real map. Verifies the exact request (method + URL) and response
 * handling `refreshAll()`/`fetchSnapshot()` perform.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchSnapshot, refreshAll } from '../../src/api/client';

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
