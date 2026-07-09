// Region selector (spec §6, FR1). Two paths: predefined dropdown
// (`GET /api/regions` -> `POST /api/regions/activate {region_id}`, no
// client-side estimate — predefined regions are pre-costed) and custom bbox
// (coordinate-entry panel -> debounced `POST /api/regions/estimate` ->
// `POST /api/regions/activate {bbox,label}`). All area/cost/cap math is
// server-computed and rendered verbatim — never recomputed here (spec §6).
//
// No framework, imperative DOM (ADR-3), mirroring `ui/controls.ts`/`ui/badges.ts`.

import { activateRegion, estimateRegion, fetchActiveRegion, fetchRegions } from '../api/client';
import type { Store } from '../state/store';
import type { EstimateResult, RegionInfo } from '../state/types';

const DEBOUNCE_MS = 300;
const LAYERS = ['air', 'land', 'marine'] as const;
type CapLayer = (typeof LAYERS)[number];

export interface RegionSelector {
  container: HTMLElement;
}

/** Mounts the region selector (dropdown + "Custom bbox…" toggle/panel) into
 * `parent` (spec §7 top bar). */
export function mountRegionSelector(parent: HTMLElement, store: Store): RegionSelector {
  const container = document.createElement('div');
  container.className = 'zij-region-selector';

  const select = document.createElement('select');
  select.dataset.testid = 'region-select';
  container.appendChild(select);

  const regionCost = document.createElement('span');
  regionCost.className = 'zij-region-selector__cost';
  regionCost.dataset.testid = 'region-cost';
  regionCost.style.display = 'none';
  container.appendChild(regionCost);

  const customToggle = document.createElement('button');
  customToggle.type = 'button';
  customToggle.dataset.testid = 'custom-bbox-toggle';
  customToggle.textContent = 'Custom bbox…';
  container.appendChild(customToggle);

  const panel = document.createElement('div');
  panel.className = 'zij-bbox-panel';
  panel.dataset.testid = 'custom-bbox-panel';
  panel.style.display = 'none';
  container.appendChild(panel);

  function mountCoordInput(testid: string, placeholder: string): HTMLInputElement {
    const wrapper = document.createElement('label');
    wrapper.className = 'zij-bbox-panel__field';
    wrapper.textContent = placeholder;
    const input = document.createElement('input');
    input.type = 'number';
    input.dataset.testid = testid;
    wrapper.appendChild(input);
    panel.appendChild(wrapper);
    return input;
  }

  const westInput = mountCoordInput('bbox-west', 'West');
  const southInput = mountCoordInput('bbox-south', 'South');
  const eastInput = mountCoordInput('bbox-east', 'East');
  const northInput = mountCoordInput('bbox-north', 'North');

  const labelWrapper = document.createElement('label');
  labelWrapper.className = 'zij-bbox-panel__field';
  labelWrapper.textContent = 'Label';
  const labelInput = document.createElement('input');
  labelInput.type = 'text';
  labelInput.dataset.testid = 'bbox-label';
  labelWrapper.appendChild(labelInput);
  panel.appendChild(labelWrapper);

  const estimateRow = document.createElement('div');
  estimateRow.className = 'zij-bbox-panel__estimate';
  const estimateArea = document.createElement('span');
  estimateArea.dataset.testid = 'bbox-estimate-area';
  const estimateCost = document.createElement('span');
  estimateCost.dataset.testid = 'bbox-estimate-cost';
  estimateRow.append(estimateArea, estimateCost);
  panel.appendChild(estimateRow);

  const capMessages = {} as Record<CapLayer, HTMLElement>;
  for (const layer of LAYERS) {
    const el = document.createElement('div');
    el.className = 'zij-bbox-panel__cap-message';
    el.dataset.testid = `bbox-cap-message-${layer}`;
    el.style.display = 'none';
    panel.appendChild(el);
    capMessages[layer] = el;
  }

  const confirmButton = document.createElement('button');
  confirmButton.type = 'button';
  confirmButton.dataset.testid = 'bbox-confirm';
  confirmButton.textContent = 'Confirm';
  confirmButton.disabled = true;
  panel.appendChild(confirmButton);

  customToggle.addEventListener('click', () => {
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  });

  let regions: RegionInfo[] = [];
  let latestEstimate: EstimateResult | null = null;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  // Generation token bumped on every scheduled estimate so a late-resolving
  // response from a superseded (edited-away) bbox can be recognized as
  // stale and dropped — see scheduleEstimate().
  let latestEstimateReqId = 0;

  function optionLabel(region: RegionInfo): string {
    return `${region.label} — ${region.aviation_credit_cost} cr`;
  }

  function renderOptions(): void {
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a region…';
    select.appendChild(placeholder);
    for (const region of regions) {
      const option = document.createElement('option');
      option.value = region.id;
      option.dataset.creditCost = String(region.aviation_credit_cost);
      option.textContent = optionLabel(region);
      select.appendChild(option);
    }
  }

  function showRegionCost(region: RegionInfo): void {
    regionCost.textContent = `${region.aviation_credit_cost} cr`;
    regionCost.style.display = 'inline';
  }

  select.addEventListener('change', () => {
    const region = regions.find((r) => r.id === select.value);
    if (!region) {
      return;
    }
    // Predefined regions are pre-costed (config.md) — no estimate step, just
    // activate directly (spec §6).
    void activateRegion({ region_id: region.id })
      .then(() => {
        showRegionCost(region);
      })
      .catch((err) => {
        console.warn('[zij] region activate failed:', err);
      });
  });

  function parseBbox(): number[] | null {
    const raw = [westInput.value, southInput.value, eastInput.value, northInput.value];
    const values = raw.map(Number);
    if (values.some((v) => !Number.isFinite(v)) || raw.some((v) => v === '')) {
      return null;
    }
    return values;
  }

  /** Renders an estimate response verbatim — no client-side re-derivation of
   * area/cost/cap math (spec §6). */
  function renderEstimate(estimate: EstimateResult): void {
    latestEstimate = estimate;
    estimateArea.textContent = String(estimate.area_sq_deg);
    estimateCost.textContent = String(estimate.aviation_credit_cost);

    let allOk = true;
    for (const layer of LAYERS) {
      const cap = estimate.layer_caps[layer];
      const el = capMessages[layer];
      if (cap && !cap.ok) {
        allOk = false;
        el.textContent = cap.message ?? `${layer} exceeds its ${cap.cap_sq_deg} sq° cap`;
        el.style.display = 'block';
      } else {
        el.textContent = '';
        el.style.display = 'none';
      }
    }
    confirmButton.disabled = !allOk;
  }

  function scheduleEstimate(): void {
    // Single shared timer across all four fields (spec §6 "~300ms") — reset
    // on every edit so a burst of field changes collapses into exactly one
    // request once the burst settles.
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
    }
    // No valid estimate is in hand for the bbox now being edited — Confirm
    // must stay disabled until a fresh estimate resolves.
    latestEstimate = null;
    confirmButton.disabled = true;
    // Invalidate any in-flight estimate request from a prior edit so its
    // response — if it resolves after this one — is dropped as stale
    // rather than clobbering the UI with an out-of-date bbox's result.
    const reqId = ++latestEstimateReqId;
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      const bbox = parseBbox();
      if (!bbox) {
        return;
      }
      void estimateRegion(bbox)
        .then((estimate) => {
          if (reqId !== latestEstimateReqId) {
            return; // superseded by a later edit — discard stale response
          }
          renderEstimate(estimate);
        })
        .catch((err) => {
          console.warn('[zij] region estimate failed:', err);
        });
    }, DEBOUNCE_MS);
  }

  for (const input of [westInput, southInput, eastInput, northInput]) {
    input.addEventListener('input', scheduleEstimate);
  }

  confirmButton.addEventListener('click', () => {
    const bbox = parseBbox();
    if (!bbox || !latestEstimate) {
      return;
    }
    void activateRegion({ bbox, label: labelInput.value, save_as_preset: false }).catch((err) => {
      console.warn('[zij] custom region activate failed:', err);
    });
  });

  // spec §9: `ui/regionSelector.ts` subscribes to `region:changed` — reflect
  // the newly active region in the dropdown when it matches a known
  // predefined region/preset; a freshly-activated custom bbox has no entry
  // in `regions`, so the dropdown simply falls back to the placeholder.
  store.on('region:changed', (payload) => {
    const changed = payload as { region_id: string };
    const known = regions.find((r) => r.id === changed.region_id);
    select.value = known ? known.id : '';
  });

  async function init(): Promise<void> {
    try {
      const res = await fetchRegions();
      regions = res.regions;
      renderOptions();
    } catch (err) {
      console.warn('[zij] fetchRegions failed:', err);
    }
    try {
      const res = await fetchActiveRegion();
      if (res.active_region) {
        const region = res.active_region;
        select.value = region.id;
        showRegionCost(region);
      }
    } catch (err) {
      console.warn('[zij] fetchActiveRegion failed:', err);
    }
  }
  void init();

  parent.appendChild(container);

  return { container };
}
