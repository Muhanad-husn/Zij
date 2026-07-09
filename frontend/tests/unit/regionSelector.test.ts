/**
 * Inner unit tests — plan/frontend/03-region-selector.md "Inner loop" unit
 * list, against `src/ui/regionSelector.ts` (`mountRegionSelector`) as
 * actually built. `src/api/client.ts` is `vi.mock`'d wholesale (no real
 * network); pure DOM via jsdom, mirroring `tests/unit/controls.test.ts`'s
 * pattern. Fake timers exercise the ~300ms debounce for real (a burst of
 * field edits must collapse into exactly one `estimateRegion` call, not one
 * per keystroke).
 *
 * Plan unit list covered here:
 *   - Dropdown options built from GET /api/regions with aviation_credit_cost
 *     shown per option.
 *   - A bbox change triggers a debounced (~300ms) single estimate call.
 *   - A layer_caps entry with ok:false renders its message and disables
 *     Confirm; all-ok:true enables it and hides messages.
 *   - Activate payload shape differs: predefined {region_id} vs custom
 *     {bbox,label} (no cross-contamination of fields).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mountRegionSelector } from '../../src/ui/regionSelector';
import { Store } from '../../src/state/store';
import * as client from '../../src/api/client';
import type { EstimateResult, RegionInfo } from '../../src/state/types';

vi.mock('../../src/api/client', () => ({
  fetchRegions: vi.fn(),
  fetchActiveRegion: vi.fn(),
  activateRegion: vi.fn(),
  estimateRegion: vi.fn(),
}));

function mockedClient() {
  return client as unknown as {
    fetchRegions: ReturnType<typeof vi.fn>;
    fetchActiveRegion: ReturnType<typeof vi.fn>;
    activateRegion: ReturnType<typeof vi.fn>;
    estimateRegion: ReturnType<typeof vi.fn>;
  };
}

const REGIONS: RegionInfo[] = [
  { id: 'hormuz', label: 'Strait of Hormuz', bbox: [55.0, 25.0, 57.5, 27.5], aviation_credit_cost: 1, kind: 'predefined' },
  { id: 'gulf-of-oman', label: 'Gulf of Oman', bbox: [56.5, 22.0, 62.0, 26.5], aviation_credit_cost: 2, kind: 'predefined' },
];

const VALID_BBOX = [52.0, 26.0, 56.0, 29.0];
const VALID_ESTIMATE: EstimateResult = {
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

const OVER_CAP_BBOX = [40.0, 20.0, 55.0, 32.0];
const OVER_CAP_ESTIMATE: EstimateResult = {
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

function testid(container: HTMLElement, id: string): HTMLElement {
  const el = container.querySelector(`[data-testid="${id}"]`);
  if (!el) {
    throw new Error(`missing [data-testid="${id}"]`);
  }
  return el as HTMLElement;
}

/** Mounts with a resolved regions list + no active region, then drains the
 * async `init()` microtasks so the dropdown is populated before assertions. */
async function mountReady(parent: HTMLElement, store: Store, regions: RegionInfo[] = REGIONS) {
  const c = mockedClient();
  c.fetchRegions.mockResolvedValue({ regions });
  c.fetchActiveRegion.mockResolvedValue({ active_region: null });
  const selector = mountRegionSelector(parent, store);
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  return selector;
}

function fillBbox(container: HTMLElement, bbox: number[]) {
  const [west, south, east, north] = bbox;
  const westInput = testid(container, 'bbox-west') as HTMLInputElement;
  const southInput = testid(container, 'bbox-south') as HTMLInputElement;
  const eastInput = testid(container, 'bbox-east') as HTMLInputElement;
  const northInput = testid(container, 'bbox-north') as HTMLInputElement;
  westInput.value = String(west);
  westInput.dispatchEvent(new Event('input', { bubbles: true }));
  southInput.value = String(south);
  southInput.dispatchEvent(new Event('input', { bubbles: true }));
  eastInput.value = String(east);
  eastInput.dispatchEvent(new Event('input', { bubbles: true }));
  northInput.value = String(north);
  northInput.dispatchEvent(new Event('input', { bubbles: true }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('mountRegionSelector — dropdown options built from GET /api/regions', () => {
  it('renders one <option> per region with its aviation_credit_cost in a data-credit-cost attribute AND visible text', async () => {
    const parent = document.createElement('div');
    const store = new Store();
    const { container } = await mountReady(parent, store);

    const select = testid(container, 'region-select') as HTMLSelectElement;
    for (const region of REGIONS) {
      const option = select.querySelector(`option[value="${region.id}"]`) as HTMLOptionElement;
      expect(option, `option for ${region.id} must exist`).not.toBeNull();
      expect(option.dataset.creditCost).toBe(String(region.aviation_credit_cost));
      expect(option.textContent ?? '').toContain(String(region.aviation_credit_cost));
    }
  });
});

describe('mountRegionSelector — bbox change debounces (~300ms) into exactly one estimate call', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('a burst of four field edits collapses into a single POST-equivalent estimateRegion call reflecting the final values', async () => {
    const parent = document.createElement('div');
    const store = new Store();
    const c = mockedClient();
    // mountReady itself awaits microtasks under real timers normally, but
    // fake timers don't block promise microtask draining, only setTimeout.
    c.fetchRegions.mockResolvedValue({ regions: REGIONS });
    c.fetchActiveRegion.mockResolvedValue({ active_region: null });
    c.estimateRegion.mockResolvedValue(VALID_ESTIMATE);
    const { container } = mountRegionSelector(parent, store);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    testid(container, 'custom-bbox-toggle').click();
    fillBbox(container, VALID_BBOX);

    // Not yet — debounce hasn't elapsed.
    expect(c.estimateRegion).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(300);

    expect(c.estimateRegion).toHaveBeenCalledTimes(1);
    expect(c.estimateRegion).toHaveBeenCalledWith(VALID_BBOX);

    // No extra call fires later either — proves the burst genuinely
    // collapsed rather than merely being "not yet caught up".
    await vi.advanceTimersByTimeAsync(1000);
    expect(c.estimateRegion).toHaveBeenCalledTimes(1);
  });
});

describe('mountRegionSelector — layer_caps ok:false disables Confirm and shows the message; all-ok:true reverses both', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('an over-cap estimate shows each failing layer message verbatim and disables Confirm', async () => {
    const parent = document.createElement('div');
    const store = new Store();
    const c = mockedClient();
    c.fetchRegions.mockResolvedValue({ regions: REGIONS });
    c.fetchActiveRegion.mockResolvedValue({ active_region: null });
    c.estimateRegion.mockResolvedValue(OVER_CAP_ESTIMATE);
    const { container } = mountRegionSelector(parent, store);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    testid(container, 'custom-bbox-toggle').click();
    fillBbox(container, OVER_CAP_BBOX);
    await vi.advanceTimersByTimeAsync(300);
    await Promise.resolve();
    await Promise.resolve();

    const landMsg = testid(container, 'bbox-cap-message-land');
    const marineMsg = testid(container, 'bbox-cap-message-marine');
    expect(landMsg.style.display).not.toBe('none');
    expect(landMsg.textContent).toContain(OVER_CAP_ESTIMATE.layer_caps.land.message);
    expect(marineMsg.style.display).not.toBe('none');
    expect(marineMsg.textContent).toContain(OVER_CAP_ESTIMATE.layer_caps.marine.message);

    const confirm = testid(container, 'bbox-confirm') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
  });

  it('a subsequent all-ok:true estimate hides every cap message and re-enables Confirm', async () => {
    const parent = document.createElement('div');
    const store = new Store();
    const c = mockedClient();
    c.fetchRegions.mockResolvedValue({ regions: REGIONS });
    c.fetchActiveRegion.mockResolvedValue({ active_region: null });
    c.estimateRegion.mockResolvedValueOnce(OVER_CAP_ESTIMATE);
    const { container } = mountRegionSelector(parent, store);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    testid(container, 'custom-bbox-toggle').click();
    fillBbox(container, OVER_CAP_BBOX);
    await vi.advanceTimersByTimeAsync(300);
    await Promise.resolve();
    await Promise.resolve();
    expect((testid(container, 'bbox-confirm') as HTMLButtonElement).disabled).toBe(true);

    c.estimateRegion.mockResolvedValueOnce(VALID_ESTIMATE);
    fillBbox(container, VALID_BBOX);
    await vi.advanceTimersByTimeAsync(300);
    await Promise.resolve();
    await Promise.resolve();

    const landMsg = testid(container, 'bbox-cap-message-land');
    const marineMsg = testid(container, 'bbox-cap-message-marine');
    expect(landMsg.style.display).toBe('none');
    expect(marineMsg.style.display).toBe('none');

    const confirm = testid(container, 'bbox-confirm') as HTMLButtonElement;
    expect(confirm.disabled).toBe(false);
  });
});

describe('mountRegionSelector — activate payload shape: predefined {region_id} vs custom {bbox,label}, no cross-contamination', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('selecting a predefined region calls activateRegion with EXACTLY {region_id} — no bbox/label keys', async () => {
    const parent = document.createElement('div');
    const store = new Store();
    const c = mockedClient();
    c.fetchRegions.mockResolvedValue({ regions: REGIONS });
    c.fetchActiveRegion.mockResolvedValue({ active_region: null });
    c.activateRegion.mockResolvedValue({ active_region: REGIONS[1] });
    const { container } = mountRegionSelector(parent, store);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    const select = testid(container, 'region-select') as HTMLSelectElement;
    select.value = REGIONS[1].id;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await Promise.resolve();
    await Promise.resolve();

    expect(c.activateRegion).toHaveBeenCalledTimes(1);
    const payload = c.activateRegion.mock.calls[0][0] as Record<string, unknown>;
    expect(payload).toEqual({ region_id: REGIONS[1].id });
    expect(payload).not.toHaveProperty('bbox');
    expect(payload).not.toHaveProperty('label');
  });

  it('confirming a valid custom bbox calls activateRegion with bbox+label set and NO region_id key', async () => {
    const parent = document.createElement('div');
    const store = new Store();
    const c = mockedClient();
    c.fetchRegions.mockResolvedValue({ regions: REGIONS });
    c.fetchActiveRegion.mockResolvedValue({ active_region: null });
    c.estimateRegion.mockResolvedValue(VALID_ESTIMATE);
    c.activateRegion.mockResolvedValue({
      active_region: { id: 'custom:ab12', label: 'My Box', bbox: VALID_BBOX, aviation_credit_cost: 1, kind: 'custom' },
    });
    const { container } = mountRegionSelector(parent, store);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    testid(container, 'custom-bbox-toggle').click();
    fillBbox(container, VALID_BBOX);
    await vi.advanceTimersByTimeAsync(300);
    await Promise.resolve();
    await Promise.resolve();

    const labelInput = testid(container, 'bbox-label') as HTMLInputElement;
    labelInput.value = 'My Box';
    labelInput.dispatchEvent(new Event('input', { bubbles: true }));

    (testid(container, 'bbox-confirm') as HTMLButtonElement).click();
    await Promise.resolve();
    await Promise.resolve();

    expect(c.activateRegion).toHaveBeenCalledTimes(1);
    const payload = c.activateRegion.mock.calls[0][0] as Record<string, unknown>;
    expect(payload).not.toHaveProperty('region_id');
    expect(payload.bbox).toEqual(VALID_BBOX);
    expect(payload.label).toBe('My Box');
  });
});
