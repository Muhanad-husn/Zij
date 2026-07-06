# Slice 06: Marine rendering + client-tick de-emphasis + integrity markers

- **Feature:** frontend
- **Slice slug:** marine-integrity
- **Issue:** #62
- **Branch:** feat/frontend/06-marine-integrity
- **Project directory:** `frontend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red**
> before implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

The marine layer plus the FR9 render honesty machinery. A marine **symbol layer** (single SDF
vessel glyph, `icon-rotate` = `cog_deg` falling back to `heading_deg` else upright,
`icon-color` = `--zij-teal`) with a popup showing MMSI / name / SOG / COG / age (and flag
name(s) inline when present). **Client-tick de-emphasis/drop** for air + marine: a ~5–10 s
`store.tick` recomputes each feature's age from `position_age_s` + elapsed since
`timestamp_fetched`, compared against `deemphasize_after_s` / `drop_after_s` from
`GET /api/config` — de-emphasized → reduced opacity; a marine vessel past `drop_after_s` (2 h)
is removed from the GeoJSON before `setData`; land is exempt. **Integrity markers:** two circle
overlay layers filtered by `spoof_suspect_on_land` and `implausible_kinematics` in
`integrity_flags`, drawn as hollow warning rings (distinct color/dash) above the vessel symbol,
concentric when a vessel carries both — **never conditionally hidden** (NFR3).

## INVEST check

- **Independent:** consumes slice 01's snapshots + `GET /api/config` thresholds + integrity flags.
- **Valuable:** FR3 (marine projection) + FR9 (spoof/kinematics markers) — the theater honesty layer.
- **Small:** one symbol layer + two filtered circle layers + the tick recompute + one popup builder.
- **Testable:** Playwright asserts render/de-emphasis/rings; Vitest for rotation fallback + tick math.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the app receiving a marine snapshot over SSE
When  the layer renders
Then  vessels draw as teal glyphs rotated by cog_deg with MMSI/SOG/COG popups
When  a vessel has been silent longer than deemphasize_after_s (client tick)
Then  it renders de-emphasized, and past drop_after_s it disappears from the map
When  a vessel carries spoof_suspect_on_land
Then  its hollow warning ring renders (never hidden) and the popup names the flag
```

- **Boundary:** the served page rendering a marine snapshot with integrity flags (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/marine-integrity.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] Rotation source falls back `cog_deg` → `heading_deg` → none (upright) per nullability.
- [ ] Client-tick age (from `position_age_s` + elapsed) vs `deemphasize_after_s`/`drop_after_s` from `/api/config`.
- [ ] Past `drop_after_s`, a marine feature is removed from the GeoJSON before `setData`; land is untouched.
- [ ] Integrity ring layers filter on `spoof_suspect_on_land` / `implausible_kinematics`; both render concentrically.
- [ ] Marine popup lists flag name(s) inline when `integrity_flags` is non-empty.

## Out of scope (deferred)

- Backend flag computation (integrity feature); AISHub as the marine source (backend, transparent here).
- Raw-payload popup inspection (FR11, v2).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots (vessels rendered + de-emphasis + spoof-suspect ring).
      CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: frontend/01, integrity/01, api-core/01.
