# Slice 02: Status ownership + the write path

- **Feature:** scheduler
- **Slice slug:** status-write-path
- **Issue:** #49
- **Branch:** feat/scheduler/02-status-write-path
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

The scheduler becomes the **sole writer** of `LayerStatus`, implementing the 7-state machine
(`loading → live/stale/cached-fallback/error`, `rate-limited`, marine-only `reconnecting`) per
the scheduler.md transition table and ARCHITECTURE §5. On every successful update it runs the
fixed write path **in order**: `integrity.apply(features, prev)` → `registry[domain] = snap` →
`events.publish_snapshot(snap)` → (air/marine only) `store.put_fallback(snap)`. The air `prev`
map is derived from the *outgoing* registry snapshot before it is replaced (`{source_id:
(lat, lon, timestamp_source)}`, empty on first fetch / after region switch); land `prev` is
empty. `raw_payload` never rides the published or persisted snapshot.

## INVEST check

- **Independent:** builds on slice 01's loop; integrity/registry/store are injected (mockable).
- **Valuable:** the FR7 status contract and the FR8/FR9/FR10 write path — the honesty machinery's spine.
- **Small:** the outcome→status mapping, the four-step write path, the air-prev derivation.
- **Testable:** pytest-asyncio with mocked integrity/registry/store asserting call order and status.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a Scheduler with mocked integrity, registry, event bus and store
When  a poll fetch returns a snapshot whose source timestamp is fresh
Then  the layer status is `live`, integrity ran before the registry was set, SSE published
      after the registry was set, and an air fallback row was persisted (raw_payload excluded)
When  a fetch returns a snapshot whose source age exceeds 2×cadence
Then  the layer status is `stale`
When  a fetch fails and a warm region-matched cache exists
Then  the layer status is `cached-fallback` (not `error`); with no cache it is `error`
```

- **Boundary:** `Scheduler` update path against mocked collaborators; assert status + call order.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_scheduler.py`.

## Inner loop — initial unit test list

- [ ] Outcome→status mapping: fresh→`live`, aged→`stale`, fail+cache→`cached-fallback`, fail+no-cache→`error`.
- [ ] Write path order is integrity → registry-set → SSE-publish → fallback-persist (recorded call sequence).
- [ ] `cached-fallback` beats `error` on any failure with a warm, region-matched row.
- [ ] Air `prev` derived from the outgoing registry snapshot before replacement; empty on first fetch.
- [ ] `raw_payload` excluded from both the published snapshot and the persisted fallback.

## Out of scope (deferred)

- Backoff per error class and the event-driven stale timer (slice 03).
- Region-switch sequence and enable/disable (slice 04); the actual SSE endpoint (api-core/01).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (call-order + status assertions). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: scheduler/01, integrity/01, store/02.
