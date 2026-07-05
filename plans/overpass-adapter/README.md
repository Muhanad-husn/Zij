# Feature: Overpass adapter (`backend/sources/overpass.py`)

The land `PollAdapter` (PRD §6.3, D4): whitelisted Overpass QL over the region bbox,
`osm_base` capture, and Douglas-Peucker simplification to ≤5,000 features. Implements
[`overpass.md`](../../design/specs/overpass.md). Validating Overpass payload sizes and the
simplification budget against a real Hormuz response is one of v0's three purposes.

- **Slug:** overpass-adapter
- **Subproject:** v0
- **New system?** no (`backend/sources/` exists after opensky-adapter/01)
- **Project directory:** `.`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [fetch-land](01-fetch-land.md) ⭐ | Parse the real Hormuz Overpass fixture → `LayerSnapshot(LAND)` + `osm_base` + geometry | ☐ todo | — |
| 02 | [simplify](02-simplify.md) | Douglas-Peucker + deterministic ≤5,000 drop priority | ☐ todo | — |

⭐ = walking skeleton (first real land data; validates payload sizes).

## Out of scope (whole feature)

- Live mirror rotation is *implemented* (per spec) but tested against mocked failures, not real mirrors.
- The scheduler-owned cache serve-vs-fetch decision (backend-api wiring); this adapter always fetches when called.

## Depends on

`models`, `config`, `sources/base` (from opensky-adapter/01); `fixtures` (slice 01 needs
the committed Overpass fixture); `store` (the API wiring reads/writes the cache, not the
adapter). Adds runtime dep `shapely`.
