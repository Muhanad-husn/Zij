# Slice 03: Layer controls — toggle + per-layer/global refresh

- **Feature:** api-core
- **Slice slug:** controls-refresh
- **Issue:** #55
- **Branch:** feat/api-core/03-controls-refresh
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

The FR5/FR6 control surface. `POST /api/layers/{domain}/toggle {enabled}` calls
`scheduler.set_enabled` and returns `{layer, enabled}` (disabling stops that adapter's scheduling
→ zero upstream budget; enabling triggers an immediate fetch). `POST /api/layers/{domain}/refresh`
calls `scheduler.refresh(domain)` and returns `202 {layer, queued:true}` — poll layers coalesce an
immediate fetch, marine forces an immediate `snapshot()`. `POST /api/refresh` calls
`scheduler.refresh_all` and returns `202 {queued:[...]}` for the enabled layers. All are
fire-and-forget; results ride SSE, not the HTTP response. Per **#38**, when a manual refresh's
underlying fetch fails, the failure surfaces as an SSE `layer_status` event
(`error`/`rate-limited`/`cached-fallback` with `detail`), never as a silent success.

## INVEST check

- **Independent:** `scheduler.set_enabled`/`refresh`/`refresh_all` are injected (mocked).
- **Valuable:** FR5 toggles (budget control) + FR6 manual refresh — direct operator levers.
- **Small:** three routes returning 200/202 + delegating to the scheduler; the #38 status-emit link.
- **Testable:** httpx asserting status codes + the mocked scheduler calls; a spy EventBus for #38.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given the app wired to a mocked scheduler and a spy EventBus
When  POST /api/layers/air/toggle {enabled:false} is called
Then  scheduler.set_enabled("air", False) runs and 200 returns {layer:"air", enabled:false}
When  POST /api/layers/air/refresh is called
Then  scheduler.refresh("air") runs and the response is 202 {layer:"air", queued:true}
When  POST /api/refresh is called with air+land enabled
Then  202 returns {queued:["air","land"]}
When  a queued refresh's fetch fails
Then  a layer_status SSE event conveys the error/rate-limited/cached-fallback state (#38)
```

- **Boundary:** the three control routes over httpx; scheduler + EventBus mocked/spied.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_api.py`.

## Inner loop — initial unit test list

- [ ] `toggle` delegates to `set_enabled` and echoes `{layer, enabled}`.
- [ ] per-layer `refresh` → `202 {layer, queued:true}`; `POST /api/refresh` → `202 {queued:[enabled...]}`.
- [ ] Only enabled layers appear in the `refresh_all` queued list.
- [ ] A failed queued refresh emits a `layer_status` event with the mapped status + `detail` (#38).
- [ ] Unknown `{domain}` → api.md error envelope (`404`/`validation_error`).

## Out of scope (deferred)

- The scheduler's coalescing/status internals (scheduler/01–03) — this slice only triggers them.
- Region endpoints (02); caveats/raw/presets (04); toggle/refresh UI (frontend/04).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (delegation + 202 bodies + #38 status emit). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: scheduler/04, api-core/01. Absorbs #38.
