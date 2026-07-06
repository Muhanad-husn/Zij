# Slice 04: Layer toggles and refresh — controls reflected through SSE

- **Feature:** frontend
- **Slice slug:** toggles-refresh
- **Issue:** #60
- **Branch:** feat/frontend/04-toggles-refresh
- **Project directory:** `frontend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red**
> before implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Per-domain layer control wired to the badge (FR5/FR6). A **toggle** calls
`POST /api/layers/{domain}/toggle {enabled}`; disabling immediately clears that domain's
GeoJSON source and grays the badge, and the frontend expects no further SSE for it until
re-enabled. A per-badge **Refresh** (`POST /api/layers/{domain}/refresh`) and one global
**Refresh all** (`POST /api/refresh`) are both fire-and-forget (202); the resulting
`loading → live/etc.` status rides SSE — the frontend never polls for completion. Buttons
disable for the brief `loading` window so coalescing is visible rather than click-flooded.

## INVEST check

- **Independent:** builds on slice 02's badges + buttons; consumes `api-core/03` controls.
- **Valuable:** FR5 (zero-budget disable) + FR6 (manual refresh) — user control over tempo/spend.
- **Small:** three POST wrappers + optimistic gray/clear + loading-driven disable.
- **Testable:** Playwright asserts POSTs + DOM state; Vitest for the fire-and-forget wrappers.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the app with badges mounted and the layer-control endpoints served
When  a layer's Toggle is switched off
Then  POST /api/layers/{domain}/toggle {enabled:false} is issued, its source clears, the badge grays
And   no further SSE events are expected for that layer until re-enabled
When  the layer's Refresh button is clicked
Then  POST /api/layers/{domain}/refresh is issued and the badge reflects loading then live via SSE (no polling)
When  the global Refresh all is clicked
Then  POST /api/refresh is issued for all enabled layers
```

- **Boundary:** the served page consuming `/api/layers/*/toggle|refresh` + `/api/refresh` (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/toggles-refresh.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] Toggle issues the POST and optimistically grays/clears the domain (reconciled by next status event).
- [ ] Per-badge Refresh POSTs and returns without awaiting completion (fire-and-forget).
- [ ] Buttons disable while the layer sits in `loading`, re-enable on the next status.
- [ ] Global "Refresh all" hits `/api/refresh` (not per-layer).

## Out of scope (deferred)

- The backend coalescing guarantee itself (scheduler feature) — asserted server-side, not here.
- Caveat panel (05); marine/integrity (06).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots (disabled/grayed badge + loading→live via SSE).
      CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: frontend/02, api-core/03.
