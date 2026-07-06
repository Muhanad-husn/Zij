# Slice 01: SSE client — EventSource wrapper, store dispatch, connection banner

- **Feature:** frontend
- **Slice slug:** sse-client
- **Issue:** #57
- **Branch:** feat/frontend/01-sse-client
- **Project directory:** `frontend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** yes ⭐

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test (Playwright) **red**
> before implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

A thin `SseClient` opens exactly **one** `EventSource('/api/events')` for the app lifetime
(native reconnect/backoff, ADR-2) and dispatches its three events into the store:
`snapshot` → `applySnapshot`, `layer_status` → `applyLayerStatus`, `region_changed` →
`applyRegionChanged`. Full-state-on-connect is handled with no special logic — `applySnapshot`
is an idempotent full replace. A connection state machine `connecting → open → lost → failed`
drives a single global banner: `lost` shows a non-blocking "Reconnecting…" (map stays
interactive on last-known state); `failed` (readyState CLOSED) shows "Connection failed — Retry".

## INVEST check

- **Independent:** consumes `api-core/01`'s SSE stub (a served/stubbed `/api/events` in tests).
- **Valuable:** the live-update spine every later frontend slice renders from; proves reconnect UX.
- **Small:** one EventSource wrapper + store mutators + one banner element.
- **Testable:** Playwright against a stub SSE server; Vitest for dispatch + state-machine logic.

## Acceptance criterion (outer loop — the failing Playwright test)

```gherkin
Given the app connected to a stub /api/events emitting a snapshot per enabled layer
When  the page loads
Then  the store receives each layer's snapshot and the map renders it (full-state-on-connect)
When  the SSE stream drops
Then  a non-blocking "Reconnecting…" banner appears and the map stays interactive
When  the connection fails fatally (readyState CLOSED)
Then  a "Connection failed — Retry" action is shown
```

- **Boundary:** the served page consuming a stub `/api/events` (Playwright).
- **e2e test type:** Playwright end-to-end with screenshot artifacts (web slice).
- **e2e test file (planned):** `frontend/tests/e2e/sse-client.spec.ts`

## Inner loop — initial unit test list (Vitest)

- [ ] `snapshot`/`layer_status`/`region_changed` events dispatch to the matching store mutator.
- [ ] Connection state derives `connecting/open/lost/failed` from EventSource open/error + readyState.
- [ ] `applySnapshot` is an idempotent full replace (re-applying the same snapshot is a no-op delta).
- [ ] Exactly one `EventSource` is constructed for the app lifetime.
- [ ] `lost` vs `failed` map to the non-blocking banner vs the Retry action respectively.

## Out of scope (deferred)

- Badge rendering of status/timestamps (slice 02); region selector (03); toggles/refresh (04).
- Caveat panel (05); marine + integrity rendering + client tick (06).

## Definition of done

- [ ] Outer Playwright test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner Vitest behaviours covered; frontend test + lint green; refactor on green.
- [ ] Evidence: Playwright screenshots (connected render + Reconnecting banner + Retry action).
      CI (`tdd-ci`, `working-directory: frontend`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: api-core/01.
