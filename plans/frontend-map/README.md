# Feature: Static map page (`frontend/`)

The v0 frontend: **one static MapLibre page, Hormuz hardcoded** (PRD §11, STRUCTURE §7).
Vite + vanilla TS ([ADR-3](../../design/docs/DECISIONS.md#adr-3--frontend-vite--vanilla-ts--maplibre)),
night-ink custom style (PRD §1.1), OpenFreeMap tiles. Renders the air + land layers pulled
over REST from the backend, with a manual refresh and honest per-layer freshness text. A
deliberately small slice of [`frontend.md`](../../design/specs/frontend.md) — no region
picker, no caveat panel, no SSE (all v1).

- **Slug:** frontend-map
- **Subproject:** v0
- **New system?** yes (`frontend/`)
- **Project directory:** `frontend`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [map-init](01-map-init.md) ⭐ | Interactive night-ink MapLibre map centered on Hormuz, with attribution | ⧗ PR open | [#34](https://github.com/Muhanad-husn/Zij/pull/34) |
| 02 | [layers-refresh](02-layers-refresh.md) | Render air + land from REST; manual refresh; UTC freshness display | ☐ todo | — |

⭐ = walking skeleton (first visible product; validates the frontend build + render perf).

## Out of scope (whole feature)

- Region selector / custom bbox (Hormuz hardcoded), caveat panel (FR9), integrity markers,
  layer toggle UI, SSE client — all v1.
- Marine layer (v1).

## Depends on

Slice 01 depends only on the frontend build (and, for evidence, the backend serving `/`).
Slice 02 depends on `backend-api/02` (the REST snapshots it renders). Web slices use
Playwright for the outer acceptance test (screenshot evidence) + Vitest for inner units,
per the TDD harness.
