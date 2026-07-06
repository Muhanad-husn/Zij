# Slice 02: REST snapshot + manual refresh endpoints (Hormuz)

- **Feature:** backend-api
- **Slice slug:** data-endpoints
- **Issue:** #18
- **Branch:** feat/backend-api/02-data-endpoints
- **Project directory:** `.`
- **Status:** ⏳ PR open ([#36](https://github.com/Muhanad-husn/Zij/pull/36))
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

With Hormuz hardcoded as the active region, `GET /api/layers/air/snapshot` calls the
OpenSky adapter and returns `LayerSnapshot(AIR)` JSON (no `raw_payload`);
`GET /api/layers/land/snapshot` serves `land_cache` when fresh (<24 h) else calls the
Overpass adapter and writes through the cache, returning `LayerSnapshot(LAND)`;
`POST /api/refresh` forces a fresh fetch of both and returns `{"queued":[...]}`. Adapter
errors map to the api.md error envelope; one layer failing never blocks the other (FR10).

## INVEST check

- **Independent:** builds on slice 01's app + both adapters + store (adapters mocked via respx/fixtures in tests).
- **Valuable:** the product surface the frontend consumes — real snapshots over HTTP, manual refresh (v0's interaction model).
- **Small:** three handlers + region wiring + error mapping (no scheduler).
- **Testable:** `TestClient` + the recorded fixtures make every path deterministic.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given the app with Hormuz active, OpenSky and Overpass mocked to return the recorded Hormuz fixtures
When  GET /api/layers/air/snapshot is requested
Then  it returns 200 with a LayerSnapshot(AIR) whose feature_count matches the parsed states and whose body carries no raw_payload
And   GET /api/layers/land/snapshot returns 200 with a LayerSnapshot(LAND); a warm land_cache is served without a second Overpass call
And   POST /api/refresh returns 202 with {"queued":["air","land"]} and forces a fresh fetch of both
And   when the OpenSky mock returns 429, the air snapshot surfaces the rate_limited error envelope while the land snapshot still succeeds (FR10)
```

- **Boundary / endpoint:** HTTP routes `GET /api/layers/{air,land}/snapshot`, `POST /api/refresh` (real endpoints via `TestClient`).
- **e2e test type:** integration test with `TestClient` + respx-mocked upstreams (recorded fixtures).
- **e2e test file (planned):** `backend/tests/test_api.py::test_snapshots_and_refresh`

## Inner loop — initial unit test list

- [ ] `GET air/snapshot` returns the adapter's snapshot as JSON, `raw_payload` excluded.
- [ ] `GET land/snapshot` serves a fresh `land_cache` row without calling Overpass; a stale/absent cache triggers a fetch + write-through.
- [ ] `POST /api/refresh` → 202 `{"queued":["air","land"]}` and both adapters are invoked.
- [ ] `RateLimitedError` → `429` `rate_limited` envelope with `retry_after_s`; `AuthError` → `401`; `UpstreamError` → `502`.
- [ ] Failure isolation: an air-layer error leaves the land snapshot reachable and correct (FR10).

## Out of scope (deferred)

- SSE push, scheduler coalescing, region activation/estimate, toggles, caveats, presets (v1).
- Marine snapshot (v1).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence (transcript of the three endpoints against fixtures); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Blocked-by: backend-api/01, opensky-adapter/02, overpass-adapter/01, store/01.
- 2026-07-06 built via harness. Outer test committed red (`444ce3d`, strict-xfail DEC-33) → greened + inner tests (`4329390`) → two-stage review (Stage 1 pass; DONE_WITH_CONCERNS) → review findings #1 (unexpected-error → `internal` envelope) + #2 (integer `Retry-After`) hardened in-branch (`f0dfdbe`→`11770c7`). 105 passed, ruff clean. Review findings #3/#4 filed as v1 follow-ups #37/#38. PR #36 open into `main`; awaiting founder approval.
