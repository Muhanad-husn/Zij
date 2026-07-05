# Feature: SQLite store — land cache (`backend/store.py` + `backend/schema.sql`)

The `land_cache` table only (D4 makes SQLite non-optional even at v0; STRUCTURE §7). A
thin wrapper that serializes/deserializes render-ready land GeoJSON with its `osm_base`
and `fetched_at`, so the Overpass fetch runs at most daily and dev iterations don't hammer
public mirrors. Never parses source payloads (STRUCTURE §3). `fallback_snapshots` and
`config_presets` are v1.

- **Slug:** store
- **Subproject:** v0
- **New system?** yes
- **Project directory:** `.`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [land-cache](01-land-cache.md) | `land_cache` round-trips a region's GeoJSON + `osm_base` + `fetched_at` | ☐ todo | — |

## Out of scope (whole feature)

- `fallback_snapshots` and `config_presets` tables (v1, FR8/FR11).
- Cache-freshness *policy* (the <24 h serve-or-fetch decision) — that lives in the
  backend-api wiring slice; the store only reads/writes rows.
