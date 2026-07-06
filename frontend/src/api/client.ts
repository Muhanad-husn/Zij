// Fetch wrappers over api.md endpoints (spec §1 `api/client.ts`). This slice
// only needs the two snapshot GETs and the global refresh POST — later
// slices add regions/estimate/activate/toggle/caveats/raw-feature/presets.

import { API_BASE } from '../config';
import type { Domain, LayerSnapshot } from '../state/types';

/** `GET /api/layers/{domain}/snapshot` (air/land only touch this slice). */
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
