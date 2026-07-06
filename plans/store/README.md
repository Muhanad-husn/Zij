# Feature: SQLite store (`backend/store.py` + `backend/schema.sql`)

The three-table SQLite responsibility (D4, NFR2; storage.md). A thin wrapper that
serializes/deserializes render-ready `Feature`/`LayerSnapshot` rows; it never parses source
payloads (STRUCTURE §3). v0 shipped `land_cache`; v1 adds the two remaining tables
(`fallback_snapshots` for FR8 restart resilience, `config_presets` for FR11 presets + the
persisted active-region config override).

- **Slug:** store
- **Subproject:** v0 (slice 01) → v1 (slices 02–03)
- **New system?** no (extends existing)
- **Project directory:** `backend`

## Slices

| # | Slice | Goal (one line) | Blocked-by | Status | PR |
|---|-------|-----------------|-----------|--------|----|
| 01 | [land-cache](01-land-cache.md) | `land_cache` round-trips a region's GeoJSON + `osm_base` + `fetched_at` | — | ☑ built | [#27](https://github.com/Muhanad-husn/Zij/pull/27) |
| 02 | [fallback-snapshots](02-fallback-snapshots.md) | one restart-resilience snapshot per mobile layer (air/marine), upsert-one-row (FR8) | — (new) | ▹ planned (v1) | — |
| 03 | [config-presets](03-config-presets.md) | region presets + config overrides incl. persisted `active_region` (FR11) | — (new) | ▹ planned (v1) | — |

## Out of scope (whole feature)

- No `features`/history/per-fetch-log table — contradicts the no-history non-goal (§4) and NFR2.
- Cache-freshness *policy* (the <24 h serve-or-fetch decision) and cold-start repopulation —
  those live in the scheduler / api-core wiring; the store only reads/writes rows.
- Applying `config_override` rows in the precedence chain — the `config` feature owns that merge.
