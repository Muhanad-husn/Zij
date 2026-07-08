# Slice 01: Scheduler core runtime — per-layer poll loop with coalescing

- **Feature:** scheduler
- **Slice slug:** core-runtime
- **Issue:** #45
- **Branch:** feat/scheduler/01-core-runtime
- **Project directory:** `backend`
- **Status:** ✅ green — PR prepared (sprint v1)
- **Walking skeleton?** yes ⭐

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

A `Scheduler` opens one `asyncio.TaskGroup` with one `_poll_loop(domain)` task per enabled
poll layer. Each loop fetches on its own effective cadence (`max(cadence_s, cadence_floor_s)`)
via `asyncio.wait_for(_wake.wait(), timeout=cadence_s)` — timeout = scheduled tick, `_wake`
set = manual refresh. `_do_fetch` is single-flight per layer: a manual `refresh(domain)` during
an in-flight scheduled fetch **joins the same `asyncio.Future`** — exactly one upstream call,
one credit charge (FR6). A disabled layer parks purely on `_wake` (zero upstream spend, FR5).

## INVEST check

- **Independent:** uses only v0 `sources/base` + `models`; adapters mocked in tests.
- **Valuable:** the concurrency spine every later slice hangs on; proves coalescing (the FR6 credit guarantee).
- **Small:** one class, the loop, the `_inflight` Future primitive, control dicts.
- **Testable:** pytest-asyncio with a fake `PollAdapter` counting calls; freezegun for cadence timing.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a Scheduler running two mocked poll adapters (air, land) on independent cadences
When  a scheduled fetch for air is in flight and refresh("air") is called before it resolves
Then  exactly one adapter.fetch is issued for air and both callers receive the same snapshot
And   changing land's cadence does not alter air's tick timing (cadences independent, FR6)
And   a disabled layer's poll loop issues zero adapter.fetch calls until re-enabled (FR5)
```

- **Boundary:** `Scheduler` public methods (`run`, `refresh`, `set_enabled`) against mocked adapters.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_scheduler.py`.

## Inner loop — initial unit test list

- [ ] Effective cadence = `max(cadence_s, cadence_floor_s)`.
- [ ] `_wake` set → immediate wake; cleared after each wake; timeout → scheduled tick.
- [ ] `_do_fetch` shares one `Future` per layer; second concurrent caller awaits it (no 2nd `fetch`).
- [ ] Disabled layer parks on `_wake` only (no cadence timeout, no fetch); enabling sets `_wake`.
- [ ] `TaskGroup` starts one task per enabled poll layer; shutdown cancels cleanly.

## Out of scope (deferred)

- Status transitions / write path / integrity / SSE / fallback (slice 02).
- Backoff, stale timer (03); region switch, marine stream supervision (04).

## Definition of done

- [x] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [x] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [x] Evidence: pytest transcript (call-count assertions prove single-flight). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none new.
- 2026-07-08 built via the harness. Outer acceptance test committed red (strict-xfail,
  `3b904c8`); implementer greened the concurrency spine (coalescing/cadence/disable); inner
  units + green commit (`dd6e0a9`). Suite 113 passed.
- 2026-07-08 review loop-back: reviewer flagged missing per-layer failure isolation (FR10),
  which the frozen spec assigns to the Task model (this slice). Fixed behavior-first — red FR10
  test + exception-path unit + tightened cadence tolerance (`0ca3c5d`), isolation added and
  greened (`bae0b5f`). Re-review DONE / READY. Suite 115 passed, ruff clean.
- Known minor (accept-and-track for slice 02): `_do_fetch`'s no-joiner failure path leaves an
  unretrieved coalescing `Future`, so asyncio logs `Future exception was never retrieved` to
  stderr. Cosmetic; no test impact. Slice 02 reworks `_do_fetch` for the write path and will
  sweep this seam.
