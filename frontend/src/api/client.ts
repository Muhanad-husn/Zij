// Fetch wrappers over api.md endpoints (spec §1 `api/client.ts`): the
// snapshot GETs, the global refresh POST, and the
// regions/estimate/activate/toggle/caveats endpoints.

import { API_BASE } from '../config';
import type { AppConfig, CaveatResponse, Domain, EstimateResult, LayerSnapshot, RegionInfo } from '../state/types';

/** `GET /api/layers/{domain}/snapshot`. */
export async function fetchSnapshot(domain: Domain): Promise<LayerSnapshot> {
  const res = await fetch(`${API_BASE}/layers/${domain}/snapshot`);
  if (!res.ok) {
    throw new Error(`Zij: fetchSnapshot(${domain}) failed with ${res.status}`);
  }
  return (await res.json()) as LayerSnapshot;
}

/** `POST /api/refresh` — refresh all enabled layers (spec §7 "Refresh all"). */
export async function refreshAll(): Promise<void> {
  const res = await fetch(`${API_BASE}/refresh`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`Zij: refreshAll() failed with ${res.status}`);
  }
}

/** `POST /api/layers/{domain}/toggle {enabled}` — enable/disable one layer
 * (spec §7 FR5). `200 -> { layer, enabled }`. */
export async function toggleLayer(domain: Domain, enabled: boolean): Promise<{ layer: Domain; enabled: boolean }> {
  const res = await fetch(`${API_BASE}/layers/${domain}/toggle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    throw new Error(`Zij: toggleLayer(${domain}) failed with ${res.status}`);
  }
  return (await res.json()) as { layer: Domain; enabled: boolean };
}

/** `POST /api/layers/{domain}/refresh` — fire-and-forget force refresh of one
 * layer (spec §7 FR6); the resulting status rides SSE, never polled here. */
export async function refreshLayer(domain: Domain): Promise<void> {
  const res = await fetch(`${API_BASE}/layers/${domain}/refresh`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`Zij: refreshLayer(${domain}) failed with ${res.status}`);
  }
}

/** `GET /api/regions` — predefined regions + saved presets (spec §6, FR1/FR11). */
export async function fetchRegions(): Promise<{ regions: RegionInfo[] }> {
  const res = await fetch(`${API_BASE}/regions`);
  if (!res.ok) {
    throw new Error(`Zij: fetchRegions() failed with ${res.status}`);
  }
  return (await res.json()) as { regions: RegionInfo[] };
}

/** `GET /api/regions/active` — currently active region, if any. */
export async function fetchActiveRegion(): Promise<{ active_region: RegionInfo | null }> {
  const res = await fetch(`${API_BASE}/regions/active`);
  if (!res.ok) {
    throw new Error(`Zij: fetchActiveRegion() failed with ${res.status}`);
  }
  return (await res.json()) as { active_region: RegionInfo | null };
}

/** `POST /api/regions/activate` — activate a predefined region/preset (by id)
 * or a validated custom bbox (spec §6). */
export async function activateRegion(
  payload: { region_id: string } | { bbox: number[]; label: string; save_as_preset?: boolean },
): Promise<{ active_region: RegionInfo }> {
  const res = await fetch(`${API_BASE}/regions/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Zij: activateRegion() failed with ${res.status}`);
  }
  return (await res.json()) as { active_region: RegionInfo };
}

/** `GET /api/layers/{domain}/caveats` — static caveat bullets (verbatim) plus
 * current `active_flags` counts (spec §5, FR9). */
export async function fetchCaveats(domain: Domain): Promise<CaveatResponse> {
  const res = await fetch(`${API_BASE}/layers/${domain}/caveats`);
  if (!res.ok) {
    throw new Error(`Zij: fetchCaveats(${domain}) failed with ${res.status}`);
  }
  return (await res.json()) as CaveatResponse;
}

/** `GET /api/config` — bundled + region-independent per-layer config (spec §9
 * "GET /api/config layers shape"). The client-tick reads
 * `deemphasize_after_s`/`drop_after_s` thresholds from here once at
 * bootstrap, the same way region config is read from `GET /api/regions`. */
export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch(`${API_BASE}/config`);
  if (!res.ok) {
    throw new Error(`Zij: fetchConfig() failed with ${res.status}`);
  }
  return (await res.json()) as AppConfig;
}

/** `POST /api/regions/estimate` — validates + prices a custom bbox before
 * activation (spec §6). A `422` is not a transport error: the response body
 * carries the same `EstimateResult` shape (under `error.details`) with
 * `valid:false` and per-layer `message`s — resolve with that so the caller's
 * normal render path handles the over-cap case. Only genuinely unexpected
 * statuses throw. */
export async function estimateRegion(bbox: number[]): Promise<EstimateResult> {
  const res = await fetch(`${API_BASE}/regions/estimate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bbox }),
  });
  if (res.ok) {
    return (await res.json()) as EstimateResult;
  }
  if (res.status === 422) {
    const json = (await res.json()) as { error: { details: EstimateResult } };
    return json.error.details;
  }
  throw new Error(`Zij: estimateRegion() failed with ${res.status}`);
}
