# Slice 05: Caveat panel — non-dismissible, reachable from every badge

- **Feature:** frontend
- **Slice slug:** caveat-panel
- **Issue:** #61
- **Branch:** feat/frontend/05-caveat-panel
- **Project directory:** `frontend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red**
> before implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

One reused caveat panel (`ui/caveatPanel.ts`), slide-in on the right (desktop) / bottom sheet
(mobile), opened from any badge's Caveats button. Content comes from
`GET /api/layers/{domain}/caveats`: the domain's **verbatim** static caveat bullets plus
`active_flags` counts (e.g. "3 marine positions currently flagged spoof-suspect"). It is
reachable from **every** badge in **every** status, and there is **no persistent-dismiss
control anywhere** (FR9) — closing hides it for the session only; the badge's Caveats button
is the only way back, every single time. Content is swapped per domain, not re-mounted.

## INVEST check

- **Independent:** opens from slice 02's Caveats button; consumes `api-core/04`'s caveats endpoint.
- **Valuable:** FR9 / NFR3 — the position-honesty surface; the one deliberately non-dismissible UI.
- **Small:** one panel component + a fetch/swap + counts footer.
- **Testable:** Playwright opens the panel from badges; Vitest for content fetch/swap + counts.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the app with the caveats endpoint served
When  the Caveats button is opened from a domain's badge
Then  the panel shows that domain's verbatim caveat bullets and its active-flag counts
And   there is no "don't show again" (or any persistent-dismiss) control anywhere in the panel
When  the panel is closed and reopened from the badge
Then  it opens again from the badge in every status, including error
```

- **Boundary:** the served page consuming `/api/layers/{domain}/caveats` (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/caveat-panel.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] Panel content is fetched and swapped per domain (bullets verbatim, not paraphrased).
- [ ] `active_flags` counts render in the footer from the endpoint response.
- [ ] No persistent-dismiss affordance exists in the panel DOM (asserted absent).
- [ ] The panel is reachable when the badge is in `error` status (Caveats never disabled).

## Out of scope (deferred)

- Computing the flags themselves (integrity feature, backend) — the panel only displays counts.
- Marine/integrity map rendering (slice 06).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots (panel open per domain + counts + reopen from badge).
      CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: frontend/02, api-core/04.
- 2026-07-10 ▸ PR #100 prepared into `main` (DONE_WITH_CONCERNS). Outer test
  `caveat-panel.spec.ts` red `a62aae3` → green `4ca0d3e` (`1 passed`, plain `test()`);
  143 Vitest green; reviewer Stage-1 PASS / Stage-2 done-with-concerns. Non-blocking
  finding → follow-up #101 (domain-switch fetch-failure with no prior cache leaves
  stale content). Awaiting founder merge approval.
