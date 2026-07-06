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
