# Slice 02: Render air + land layers from REST with manual refresh and UTC freshness

- **Feature:** frontend-map
- **Slice slug:** layers-refresh
- **Issue:** #20
- **Branch:** feat/frontend-map/02-layers-refresh
- **Project directory:** `frontend`
- **Status:** ⧗ PR open ([#39](https://github.com/Muhanad-husn/Zij/pull/39))
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red** before implementation; **implementer** drives inner cycles and may not edit the outer test or `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

On load the page fetches `GET /api/layers/air/snapshot` and `.../land/snapshot` and renders
them on the Hormuz map: aircraft as heading-rotated brass symbols (one GeoJSON source,
`setData`), land as dun roads (motorway/trunk/primary width steps) + dashed rail + point
anchors. A "Refresh" button calls `POST /api/refresh` and re-pulls both snapshots. Each
layer shows its `timestamp_source`/`timestamp_fetched` in labeled **UTC** (NFR6) and a
feature count.

## INVEST check

- **Independent:** builds on slice 01's map; consumes `backend-api/02` (mockable in tests).
- **Valuable:** completes the visible v0 loop — real air + land over the Hormuz map with honest freshness and manual refresh.
- **Small:** three render modules (aviation/land) + one fetch client + a refresh control + freshness text.
- **Testable:** Playwright against a stubbed/served backend; Vitest for the wire→GeoJSON mapping.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the backend serving air and land snapshots for Hormuz
When  the page loads
Then  aircraft symbols render on the map, rotated by true_track_deg, in the brass domain color
And   land roads render as dun lines (motorway thickest) and point anchors render as symbols
And   each layer shows both timestamps labeled in UTC and a feature count
When  the Refresh button is clicked
Then  POST /api/refresh is issued and the layers re-render from the new snapshots
```

- **Boundary / endpoint:** the served page consuming the real `/api/layers/*` + `/api/refresh` endpoints (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/layers-refresh.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] Wire→GeoJSON: a point `Feature` (geometry null) becomes `{type:"Point",coordinates:[lon,lat]}`; a wire LineString is passed through; `attrs`/`status`/`timestamp_*` flatten into `properties`.
- [ ] Aviation symbol config uses `icon-rotate = true_track_deg` and the brass color token.
- [ ] Land line styling steps width by `highway` (motorway>trunk>primary) in the dun token; rail dashed.
- [ ] Timestamps format as `HH:MM:SS UTC` (never local time); a null `timestamp_source` renders a defined placeholder.
- [ ] The refresh action posts to `/api/refresh` and applies the returned/subsequent snapshots idempotently.

## Out of scope (deferred)

- Region picker, caveat panel, integrity markers, layer toggles, SSE, client-tick de-emphasis (v1).
- Marine layer (v1).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots of the rendered layers + post-refresh. CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Blocked-by: frontend-map/01, backend-api/02.
- 2026-07-06 built via `/sprint-start` (deps #19 + #18 both closed). Harness: red outer Playwright (`c29e383`, `test.fail()`) → implementer greened (`defb2c0`) → marker removed + 32 inner Vitest units (`6a77217`). Two-stage review: **Stage 1 PASS / Stage 2 DONE_WITH_CONCERNS, no must-fix**. FR10 finding #1 hardened in-branch (founder-approved) via red→green mini-loop: `Promise.all` → `Promise.allSettled` in `app/loadLayers.ts` (`8e9a274` red inner test → `49b603d` green). Suites: Vitest 44, Playwright 1, pytest 105 green. Evidence `ba3a774`. **PR [#39](https://github.com/Muhanad-husn/Zij/pull/39) into `main` — awaiting founder merge approval.** Non-blocking v1 follow-ups: shared test-helper module; `frontend/src` line-count watch.
