# Slice 02: Region endpoints — list, estimate, activate, active

- **Feature:** api-core
- **Slice slug:** region-endpoints
- **Issue:** #54
- **Branch:** feat/api-core/02-region-endpoints
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

The FR1 region surface per api.md: `GET /api/regions` lists predefined regions + saved presets
with `aviation_credit_cost`; `POST /api/regions/estimate {bbox}` validates a custom bbox with no
side effects — returns `area_sq_deg`, `aviation_credit_cost` (config credit-tier table), and a
per-layer `layer_caps` object; a cap violation yields `valid:false` + a cap-naming `message`
returned as `422 validation_error`. `POST /api/regions/activate` accepts a `region_id` or a
re-validated custom `{bbox, label, save_as_preset}` and calls `scheduler.activate_region`,
returning `{active_region}` (layer updates arrive over SSE, not in this response). `GET
/api/regions/active` returns the current region or `null`. This slice also **consolidates the
air/land snapshot handlers into one `/api/layers/{domain}/snapshot` route (#37)** now that marine
is a third domain.

## INVEST check

- **Independent:** config credit/cap math is pure; `scheduler.activate_region` is mocked/injected.
- **Valuable:** FR1 region selection + custom-bbox pricing — the front door to the whole monitor.
- **Small:** four routes, the estimate math (server-side, single source of truth), the #37 route merge.
- **Testable:** httpx `AsyncClient` asserting bodies + status codes + the mocked activate call.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given the app with the 7 predefined regions loaded
When  GET /api/regions is called
Then  it lists each region with its aviation_credit_cost and kind
When  POST /api/regions/estimate is called with an in-cap bbox
Then  200 returns area_sq_deg, aviation_credit_cost and all layer_caps ok:true
When  estimate is called with a bbox exceeding the land/marine cap
Then  422 validation_error carries that layer's ok:false and a cap-naming message
When  POST /api/regions/activate {region_id:"gulf-of-oman"} is called
Then  scheduler.activate_region is invoked and 200 returns the active RegionInfo
```

- **Boundary:** the four region routes over httpx; `scheduler.activate_region` mocked.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_api.py`.

## Inner loop — initial unit test list

- [ ] Credit-tier mapping (config.md area→credits table) and area computation for a bbox.
- [ ] Cap comparison per layer; `message` present only when `ok:false`, naming the exceeded cap.
- [ ] `activate` with a predefined id vs a custom bbox (re-validated server-side; 422 on cap violation).
- [ ] `GET /api/regions/active` returns the active region, else `null`.
- [ ] Consolidated `/api/layers/{domain}/snapshot` route serves air, land and marine (#37); `404` when no active region.

## Out of scope (deferred)

- The region-switch mechanics themselves (scheduler/04) — this slice only calls them.
- Toggle/refresh (slice 03); caveats/raw/presets (04); the region-selector UI (frontend/03).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (estimate math + cap 422 + activate call). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: config/02, scheduler/04. Absorbs #37.
