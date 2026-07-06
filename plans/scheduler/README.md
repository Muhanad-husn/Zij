# Feature: scheduler

`backend/scheduler.py` — the v1 runtime heart (spec: `design/specs/scheduler.md`,
ARCHITECTURE §5). One asyncio task per enabled poll layer + supervision of the marine
stream; per-layer cadence with floors; manual-refresh single-flight coalescing (FR6);
**sole ownership** of the 7-state `LayerStatus` machine (FR7); the write path
adapter→integrity→registry→SSE→fallback (FR8/FR9/FR10); region-switch and enable/disable.

Consolidated from triage's 9-slice proposal to 4 (founder decision 2026-07-06, 80/20).

| Slice | Slug | Behaviour | Blocked-by | Skeleton |
|---|---|---|---|---|
| 01 | core-runtime | TaskGroup, per-layer poll loop (cadence+floor+`_wake`), single-flight coalescing (FR6) | — (v0 `base`/`models`) | ⭐ |
| 02 | status-write-path | 7-state FSM (sole writer) + write path order integrity→registry→SSE→fallback | 01, integrity/01, store/02 | |
| 03 | backoff-stale | backoff per error class + event-driven stale timer | 02 | |
| 04 | region-toggle | region-switch sequence + enable/disable (FR5) | 02, store/03, sources-marine/02 | |

Critical path: 01 → 02 → 03/04. All P0. Tests: `backend/tests/test_scheduler.py` (pytest-asyncio,
freezegun for clock, adapter mocks, v0 opensky/overpass fixtures).
