// Wire types mirroring feature-schema.md / api.md verbatim (spec §1). Only
// the fields this slice touches are modeled; later slices extend this file
// rather than re-deriving shapes ad hoc.

export type Domain = 'air' | 'marine' | 'land';

export interface WireFeature {
  domain: string;
  source: string;
  source_id: string;
  label: string | null;
  lat: number;
  lon: number;
  geometry_type: 'point' | 'linestring' | 'polygon';
  geometry: GeoJSON.Geometry | null;
  timestamp_source: string | null;
  timestamp_fetched: string;
  position_age_s: number | null;
  status: string;
  integrity_flags: string[];
  attrs: Record<string, unknown>;
  /** Client-computed (spec §9 `state/derive.ts`) — set by `Store.tick`, never
   * by the wire. Absent/false until a tick has actually aged this feature
   * past its layer's `deemphasize_after_s`. */
  deemphasized?: boolean;
}

export interface LayerSnapshotMeta {
  layer: string;
  region_id: string;
  status: string;
  timestamp_fetched: string | null;
  timestamp_source: string | null;
  cadence_s: number;
  stale_after_s: number;
  feature_count: number;
  retry_after_s: number | null;
  detail: string | null;
}

export interface LayerSnapshot {
  meta: LayerSnapshotMeta;
  features: WireFeature[];
}

export interface RegionInfo {
  id: string;
  label: string;
  bbox: number[];
  aviation_credit_cost: number;
  kind: string;
}

export interface LayerCap {
  ok: boolean;
  cap_sq_deg: number;
  cost_credits?: number;
  message?: string;
}

export interface EstimateResult {
  valid: boolean;
  bbox: number[];
  area_sq_deg: number;
  aviation_credit_cost: number;
  layer_caps: Record<'air' | 'land' | 'marine', LayerCap>;
}

/** `GET /api/layers/{domain}/caveats` response (spec §5, api.md). Static
 * per-domain caveat bullets (verbatim) plus current active-flag counts. */
export interface CaveatResponse {
  domain: string;
  caveats: string[];
  active_flags: Record<string, number>;
}

/** `GET /api/config` response (spec §9 "GET /api/config layers shape",
 * api.md/config.md) — mirrors config.md's per-layer `[layers.*]` tables as
 * JSON. The client-tick (`Store.tick`) reads `deemphasize_after_s`/
 * `drop_after_s` from here rather than hardcoding thresholds. */
export interface LayerConfigAir {
  enabled: boolean;
  cadence_s: number;
  cadence_floor_s: number;
  deemphasize_after_s: number;
  stale_multiplier: number;
  custom_bbox_cap_sq_deg: number;
}

export interface LayerConfigMarine {
  enabled: boolean;
  cadence_s: number;
  cadence_floor_s: number;
  deemphasize_after_s: number;
  drop_after_s: number;
  stale_multiplier: number;
  custom_bbox_cap_sq_deg: number;
}

export interface LayerConfigLand {
  enabled: boolean;
  cadence_s: number;
  cadence_floor_s: number;
  stale_multiplier: number;
  simplify_tolerance_deg: number;
  max_rendered_features: number;
  custom_bbox_cap_sq_deg: number;
}

export interface AppConfig {
  regions: unknown[];
  layers: {
    air: LayerConfigAir;
    marine: LayerConfigMarine;
    land: LayerConfigLand;
  };
  stale_multiplier: number;
  custom_bbox_caps: { air: number; marine: number; land: number };
}
