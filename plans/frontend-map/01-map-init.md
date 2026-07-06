# Slice 01: Interactive Hormuz map renders in night-ink with attribution ⭐

- **Feature:** frontend-map
- **Slice slug:** map-init
- **Issue:** #19
- **Branch:** feat/frontend-map/01-map-init
- **Project directory:** `frontend`
- **Status:** ⧗ PR #34 open (awaiting founder merge approval)
- **Walking skeleton?** **yes** (first visible product; validates the build + render perf)

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red** before implementation; **implementer** drives inner cycles and may not edit the outer test or `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Opening the app boots a single interactive MapLibre `Map` centered on the Hormuz bbox
(`[55.0, 25.0, 57.5, 27.5]`), styled with the night-ink identity (background `#101D30`,
not the default light style), rendering OpenFreeMap vector tiles with a visible OSM +
OpenFreeMap attribution control. The map is pannable/zoomable and does not error out if
`/api/*` is unreachable.

## INVEST check

- **Independent:** frontend-only; needs no backend data for map init.
- **Valuable:** proves the Vite build pipeline, the custom style, and MapLibre render perf on real Hormuz geography (NFR4).
- **Small:** `main.ts` entry + `map/map.ts` init + the custom style + minimal CSS.
- **Testable:** Playwright asserts the canvas mounts, the attribution shows, and no console error fires.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the built frontend served at /
When  the page is opened in a browser
Then  a MapLibre canvas mounts and is centered on the Hormuz region (center ~26.25N, 56.25E)
And   the attribution control shows "OpenStreetMap" and "OpenFreeMap"
And   the map background is the night-ink color (not the default light basemap)
And   no uncaught console error is thrown during load
```

- **Boundary / endpoint:** the served page `GET /` in a real browser (Playwright).
- **e2e test type:** Playwright end-to-end with a screenshot artifact (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/map-init.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] The map factory produces a config centered on the Hormuz bbox center at the expected zoom.
- [ ] The custom style's background paint is `--zij-ink` (#101D30), sourced from tokens, not hardcoded per call.
- [ ] The tile source URL points at the configured OpenFreeMap provider (no CDN JS/font).
- [ ] `AttributionControl` is added (non-collapsible desktop / compact mobile).

## Out of scope (deferred)

- Any layer data, badges, refresh, region picker (slice 02 / v1).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Walking-skeleton evidence: the Playwright screenshot of the Hormuz map. CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Establishes `frontend/` (Vite + vanilla TS + MapLibre, Playwright + Vitest).
- 2026-07-06 built via /sprint-start. Outer Playwright test red (`6c87ce8`) → implementer scaffold (`c604b93`) → inner Vitest units + finalized contract (`0de0cb1`) → CI jobs + error-log fix (`c55a574`, `544ac9f`) → evidence (`9839bd3`). Reviewer: stage-1 spec-compliance PASS, stage-2 solid; DONE_WITH_CONCERNS, two findings fixed in-PR. **PR #34** (Closes #19), awaiting founder merge approval. Follow-ups: spec-drift #35 (TESTING.md vs Playwright), backend `dist`-absent test over-strict, Windows Playwright teardown hang (Linux CI authoritative), cosmetic water/roads token duplication.
