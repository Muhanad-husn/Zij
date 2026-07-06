# Slice 03: Region selector — predefined + custom bbox with server-priced estimate

- **Feature:** frontend
- **Slice slug:** region-selector
- **Issue:** #59
- **Branch:** feat/frontend/03-region-selector
- **Project directory:** `frontend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red**
> before implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

A region selector in the top bar with two paths (FR1). **Predefined:** a dropdown populated
from `GET /api/regions`, each option showing its `aviation_credit_cost` inline; selecting one
calls `POST /api/regions/activate {region_id}`. **Custom bbox:** draw-on-map rectangle drag
(a temporary GeoJSON preview source) OR enter-coordinates (west/south/east/north inputs); on
every bbox change (debounced ~300 ms) `POST /api/regions/estimate` and render its
`area_sq_deg`, `aviation_credit_cost`, and per-layer `layer_caps` **verbatim** — if any
`ok:false`, show that layer's cap message inline and disable Confirm; Confirm →
`POST /api/regions/activate {bbox,label}`. On `region_changed` (SSE) all layers clear and
await fresh snapshots. The last-used region is restored on load. **All cost/cap math is
server-sourced** — never recomputed client-side.

## INVEST check

- **Independent:** consumes slice 01's store (`region_changed`) + `api-core/02`'s endpoints.
- **Valuable:** FR1 — the whole select-region loop, the app's primary control.
- **Small:** one dropdown + a bbox panel (draw + coords) + estimate rendering + activate call.
- **Testable:** Playwright against served/stubbed region endpoints; Vitest for payloads/rendering.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the app with the region endpoints served
When  a predefined region is selected from the dropdown
Then  POST /api/regions/activate {region_id} is issued and its credit cost was shown inline
When  a custom bbox exceeding a layer's cap is entered
Then  the layer's cap-naming message is shown and Confirm is disabled before activation
When  a valid custom bbox is confirmed
Then  POST /api/regions/activate {bbox,label} is issued and the map clears on region_changed
```

- **Boundary:** the served page consuming `/api/regions*` (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/region-selector.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] Dropdown options built from `GET /api/regions` with `aviation_credit_cost` shown per option.
- [ ] Bbox change triggers a debounced (~300 ms) `POST /api/regions/estimate`.
- [ ] A `layer_caps` entry with `ok:false` renders its `message` and disables Confirm.
- [ ] Activate payload shape differs for predefined (`region_id`) vs custom (`bbox,label`).
- [ ] `region_changed` clears all layer sources (stale features never linger under the new region).

## Out of scope (deferred)

- Saved presets create/list/delete UI (FR11, v2) — endpoints designed but UI deferred.
- Layer toggles/refresh (slice 04); caveat panel (05); marine/integrity (06).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots (predefined activation + cap-violation state + custom activation).
      CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: frontend/01, api-core/02.
