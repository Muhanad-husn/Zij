/**
 * Inner unit test — frontend-map/02-layers-refresh hardening mini-loop
 * (issue #20), reviewer stage-2 finding #1: `main.ts` loaded the air+land
 * snapshots with `Promise.all`, so ONE domain's fetch rejecting caused
 * `Promise.all` to reject and NEITHER layer to render — violating FR10
 * (failure isolation: one domain failing must never block another from
 * rendering).
 *
 * Pins the extracted, dependency-injected orchestration seam
 * `loadLayers(tasks)` in `src/app/loadLayers.ts`: it must run every task's
 * `load()` concurrently via `Promise.allSettled`, call `render(result)` for
 * each FULFILLED task, `console.warn(label, err)` + skip `render` for each
 * REJECTED task, never throw, and return a record of which labels
 * succeeded.
 *
 * Hermetic — no real map, no network; `load`/`render` are `vi.fn()` stand-ins.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadLayers, type LayerLoadTask } from '../../src/app/loadLayers';

describe('loadLayers — failure isolation (FR10): one domain rejecting must not block another', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it('the SECOND task still renders when the FIRST task rejects, and loadLayers does not throw', async () => {
    const airRender = vi.fn();
    const landSnapshot = { meta: { layer: 'land' }, features: [] };
    const landRender = vi.fn();

    const tasks: LayerLoadTask[] = [
      { label: 'air', load: () => Promise.reject(new Error('air fetch failed')), render: airRender },
      { label: 'land', load: () => Promise.resolve(landSnapshot), render: landRender },
    ];

    await expect(loadLayers(tasks)).resolves.toBeDefined();

    expect(airRender).not.toHaveBeenCalled();
    expect(landRender).toHaveBeenCalledTimes(1);
    expect(landRender).toHaveBeenCalledWith(landSnapshot);
  });

  it('both tasks resolving: both renders are called with their respective snapshots; both labels report true', async () => {
    const airSnapshot = { meta: { layer: 'air' }, features: [] };
    const landSnapshot = { meta: { layer: 'land' }, features: [] };
    const airRender = vi.fn();
    const landRender = vi.fn();

    const tasks: LayerLoadTask[] = [
      { label: 'air', load: () => Promise.resolve(airSnapshot), render: airRender },
      { label: 'land', load: () => Promise.resolve(landSnapshot), render: landRender },
    ];

    const result = await loadLayers(tasks);

    expect(airRender).toHaveBeenCalledWith(airSnapshot);
    expect(landRender).toHaveBeenCalledWith(landSnapshot);
    expect(result).toEqual({ air: true, land: true });
  });

  it('a rejecting task logs a console.warn naming its label, skips its render, and reports false', async () => {
    const err = new Error('land fetch failed');
    const airSnapshot = { meta: { layer: 'air' }, features: [] };
    const airRender = vi.fn();
    const landRender = vi.fn();

    const tasks: LayerLoadTask[] = [
      { label: 'air', load: () => Promise.resolve(airSnapshot), render: airRender },
      { label: 'land', load: () => Promise.reject(err), render: landRender },
    ];

    const result = await loadLayers(tasks);

    expect(landRender).not.toHaveBeenCalled();
    expect(result.land).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith('land', err);
  });

  it('both tasks rejecting: neither render is called, loadLayers does not throw, both labels report false', async () => {
    const airRender = vi.fn();
    const landRender = vi.fn();

    const tasks: LayerLoadTask[] = [
      { label: 'air', load: () => Promise.reject(new Error('air down')), render: airRender },
      { label: 'land', load: () => Promise.reject(new Error('land down')), render: landRender },
    ];

    const result = await loadLayers(tasks);

    expect(airRender).not.toHaveBeenCalled();
    expect(landRender).not.toHaveBeenCalled();
    expect(result).toEqual({ air: false, land: false });
  });
});
