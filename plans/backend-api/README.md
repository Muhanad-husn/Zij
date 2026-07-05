# Feature: Backend HTTP API (`backend/main.py`)

The FastAPI surface for the v0 spike — **REST only, no SSE, no scheduler** (founder
decision, 2026-07-05; SSE + registry push land in v1 with the scheduler). Hormuz is
hardcoded as the active region. Serves the static frontend in prod. A minimal subset of
[`api.md`](../../design/contracts/api.md).

- **Slug:** backend-api
- **Subproject:** v0
- **New system?** yes (`backend/main.py`)
- **Project directory:** `.`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [app-health-config](01-app-health-config.md) | FastAPI app: `GET /api/health`, `GET /api/config`, static serving | ☐ todo | — |
| 02 | [data-endpoints](02-data-endpoints.md) | `GET /api/layers/{air,land}/snapshot` + `POST /api/refresh` (manual, Hormuz) | ☐ todo | — |

## v0 API surface (the whole subset)

- `GET /api/health` — liveness.
- `GET /api/config` — effective non-secret config (regions, layers).
- `GET /api/layers/air/snapshot` — fetch OpenSky for Hormuz, return `LayerSnapshot(AIR)`.
- `GET /api/layers/land/snapshot` — serve `land_cache` if fresh, else fetch Overpass, return `LayerSnapshot(LAND)`.
- `POST /api/refresh` — force a fresh fetch of both layers (manual refresh, FR6-lite).

## Out of scope (whole feature)

- SSE `GET /api/events`, the scheduler, per-layer cadence/coalescing (v1).
- `POST /api/regions/activate` / `/estimate`, layer toggle, caveats, raw-feature, presets
  (v1 — Hormuz is hardcoded and there is no region switching in the spike).
- Marine snapshot (v1).

## Depends on

`models`, `config`, `store`, `opensky-adapter`, `overpass-adapter`. Adds runtime deps
`fastapi`, `uvicorn`.
