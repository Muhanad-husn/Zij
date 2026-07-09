# Slice 02: Layer badges — all seven statuses, both UTC timestamps, controls

- **Feature:** frontend
- **Slice slug:** badges
- **Issue:** #58
- **Branch:** feat/frontend/02-badges
- **Project directory:** `frontend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red**
> before implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

One badge per domain (air/marine/land), always visible, rendering **all seven** `LayerStatus`
values with the frontend.md §4 color/label mapping: `live`, `stale · {age}`, `loading…`,
`rate-limited · retry in {retry_after_s}s` (client-side countdown), `error` (detail on
hover), `cached-fallback · {age}`, `reconnecting` (grouped with loading, marine-only). Each
badge shows both `timestamp_fetched` and `timestamp_source` as `HH:MM:SS UTC` (NFR6 — never
local time), a feature count, and always-present Toggle / Refresh / Caveats buttons. Badges
update imperatively on `status:{domain}` / `snapshot:{domain}` store events (no full re-render).

## INVEST check

- **Independent:** consumes slice 01's store events; button wiring is later slices (04/05).
- **Valuable:** FR7 freshness visibility — the honesty surface for every layer's status.
- **Small:** one badge builder per domain + a status→style map + UTC formatter reuse.
- **Testable:** Playwright drives store events → asserts badge DOM; Vitest for the pure maps.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the app with a mounted badge per domain
When  a layer transitions through each of the seven LayerStatus values
Then  the badge shows that status's distinct color and label per §4
And   both timestamps render as HH:MM:SS UTC (never local time)
And   a rate-limited badge counts down from retry_after_s
And   the Caveats button is present and enabled in every status, including error
```

- **Boundary:** the served page with store events driving badge DOM (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/badges.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] `LayerStatus` → color/label map covers all seven values (incl. reconnecting grouped with loading).
- [ ] Timestamps format as `HH:MM:SS UTC`; a null `timestamp_source` renders a defined placeholder.
- [ ] `rate-limited` countdown decrements from `retry_after_s` on the client tick.
- [ ] Feature count updates from the latest `snapshot:{domain}` event.
- [ ] Caveats control is always rendered and enabled regardless of status.

## Out of scope (deferred)

- Wiring Toggle/Refresh behaviour (slice 04) and the caveat panel it opens (05).
- Region selector (03); marine/integrity rendering (06).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots of each status variant. CI (`tdd-ci`,
      `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: frontend/01.
- 2026-07-09 built + PR prepared. Outer test `frontend/tests/e2e/badges.spec.ts` red
  (`f2b0658`, `test.fail()`) → green (`47f5141`, marker removed). All seven `LayerStatus`
  states + marine badge + always-enabled Caveats shipped; implementer also fixed a
  pre-existing SSE-vs-REST cold-start race in `main.ts`. Vitest 89 green, backend 207 green,
  outer Playwright `1 passed`. Two-stage reviewer PASS/PASS, no blocking findings. Evidence
  `docs/tdd-evidence/frontend/02-badges/`. **PR #92** into `main` (`Closes #58`). Awaiting
  founder merge approval. Non-blocking follow-up: `LayerSnapshotMeta.status` typed `string`
  vs a `LayerStatus` union (inherited from slice 01).
