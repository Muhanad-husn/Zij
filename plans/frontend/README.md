# Feature: frontend

The v1 browser UI — `frontend/src/{sse,state,map,ui}` on the ADR-3 stack (Vite + vanilla
TS + MapLibre, no framework). Spec: `design/specs/frontend.md`. Buildable against
`design/contracts/api.md` + `feature-schema.md` alone. **NEW dir** (`plans/frontend/`),
distinct from v0's `plans/frontend-map/` (which shipped the static Hormuz map + air/land
REST render). This feature adds SSE, the region picker, layer toggles, 7-status badges,
the caveat panel, and marine + integrity rendering.

Consolidated from triage's 10-slice proposal to 6 (founder decision 2026-07-06, 80/20).

| Slice | Slug | Behaviour | Blocked-by | Skeleton |
|---|---|---|---|---|
| 01 | sse-client | `EventSource('/api/events')` wrapper → store dispatch + connection banner | api-core/01 | ⭐ ✅ PR #84 |
| 02 | badges | 7-status badges, both UTC timestamps, count, per-badge buttons (FR7) | 01 | |
| 03 | region-selector | predefined dropdown + custom bbox (draw/coords) + estimate + activate (FR1) | 01, api-core/02 | |
| 04 | toggles-refresh | per-domain toggle + per-badge/global refresh, loading via SSE (FR5/FR6) | 02, api-core/03 | |
| 05 | caveat-panel | non-dismissible slide-in caveat panel from every badge (FR9) | 02, api-core/04 | |
| 06 | marine-integrity | marine symbol layer + client-tick de-emphasis/drop + integrity rings (FR3/FR9) | 01, integrity/01, api-core/01 | |

Critical path: 01 → 02 → 03/04/05 and 01 → 06. All P0. Web slices: Playwright outer
(`frontend/tests/e2e/*.spec.ts`) + Vitest inner (`frontend/tests/unit/*.test.ts`);
CI via `tdd-ci` with `working-directory: frontend`.
