// Client-tick derivation (spec §9 "State handling" / §2 "De-emphasis"). Pure
// functions, no DOM/network — `Store.tick` is the only caller. Kept separate
// from store.ts so the age/threshold math is independently reasoned about
// (and independently unit-testable) from the pub-sub plumbing.

import type { WireFeature } from './types';

/**
 * Recomputes a feature's current age in seconds: the wire's own
 * `position_age_s` (age *as of the fetch*) plus wall-clock elapsed since
 * `timestamp_fetched` (spec §9 "state/derive.ts recomputes age from
 * position_age_s + elapsed wall-clock since timestamp_fetched"). SSE only
 * pushes every `cadence_s`, too coarse for smooth de-emphasis — this is what
 * makes client-side ticking necessary at all.
 */
export function computeFeatureAgeS(feature: WireFeature, now: number): number {
  const baseAgeS = feature.position_age_s ?? 0;
  const fetchedAtMs = Date.parse(feature.timestamp_fetched);
  const elapsedS = Number.isFinite(fetchedAtMs) ? Math.max(0, (now - fetchedAtMs) / 1000) : 0;
  return baseAgeS + elapsedS;
}

/**
 * One domain's client-tick recompute (spec §2 Marine / Aviation de-emphasis,
 * §9). Returns a NEW array — features are never mutated in place, so the
 * caller's own `layer.features` reference stays a stable snapshot until
 * replaced. Each surviving feature carries a fresh `deemphasized` boolean.
 *
 * `dropAfterS` is optional (air has no drop threshold — spec §2 Aviation only
 * de-emphasizes; marine both de-emphasizes AND drops, spec §2 Marine). When
 * given, features whose age exceeds it are removed entirely rather than
 * merely marked — the marine-only "vessel disappears from the projection"
 * behavior.
 */
export function tickLayerFeatures(
  features: WireFeature[],
  now: number,
  deemphasizeAfterS: number,
  dropAfterS?: number,
): WireFeature[] {
  const next: WireFeature[] = [];
  for (const feature of features) {
    const ageS = computeFeatureAgeS(feature, now);
    if (dropAfterS !== undefined && ageS > dropAfterS) {
      continue;
    }
    next.push({ ...feature, deemphasized: ageS > deemphasizeAfterS });
  }
  return next;
}
