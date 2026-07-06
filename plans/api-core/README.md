# Feature: api-core

The v1 HTTP + SSE surface — `backend/main.py` grown from v0's REST-only spike into the full
`design/contracts/api.md` contract. Adds the single SSE stream (`GET /api/events`, sse-starlette,
full-state-on-connect, ADR-2/ADR-12), region selection/estimate/activation, per-layer toggle +
refresh, the caveats endpoint, and the P1 raw-feature + presets endpoints (designed now, UI ships
v2). Wires the scheduler + registry + EventBus into the app lifespan (startup warm-cache path,
ARCHITECTURE §4.1). **NEW dir** (`plans/api-core/`), distinct from v0's `plans/backend-api/`
(which shipped `/api/health`, `/api/config`, the air/land snapshots, and `POST /api/refresh`).

Consolidated from triage's 7-slice proposal to 4 (founder decision 2026-07-06, 80/20).

| Slice | Slug | Behaviour | Blocked-by | Skeleton |
|---|---|---|---|---|
| 01 | sse-endpoint | `GET /api/events` full-state-on-connect + EventBus + scheduler/registry lifespan wiring | scheduler/02, store/02 | ⭐ |
| 02 | region-endpoints | `GET /api/regions`, `POST /api/regions/estimate`, `POST .../activate`, `GET .../active` (FR1); consolidates the snapshot route (**#37**) | config/02, scheduler/04 | |
| 03 | controls-refresh | `POST /api/layers/{domain}/toggle` + `.../refresh` + `POST /api/refresh`; refresh failures surface via SSE `layer_status` (**#38**) | scheduler/04, api-core/01 | |
| 04 | caveats-raw-presets | `GET .../caveats` (+active_flags), `GET /api/features/{domain}/{source_id}/raw` (P1), presets CRUD (P1) | integrity/02, store/03, api-core/01 | |

Critical path: 01 → 02/03 → 04. P0 for 01–03 (+ the P0 parts of 04: caveats); the raw-feature
and presets endpoints are P1 (designed now, UI lands v2). Absorbs already-filed **#37**
(consolidate `/api/layers/{domain}` snapshot route) into 02 and **#38** (surface per-layer refresh
failures via SSE) into 03. Tests: `backend/tests/test_api.py` (httpx `AsyncClient`, mocked
scheduler/registry; an `EventSource`-shaped SSE consumer for 01).
